#!/usr/bin/env python3
"""
FITS Image Combiner — calibration, alignment, and stacking of FITS images.

Improvements over the original version:

  * Star detection rejects saturated stars, hot pixels, and cosmic rays
    (peakmax cut plus DAOStarFinder sharpness/roundness limits), and refines
    every centroid with a center-of-mass fit.
  * Frame-to-frame matching uses an offset-consensus algorithm that is robust
    to large shifts: the translation supported by the most star pairs is found
    first, then matches are confirmed with a KD-tree at that offset.
  * The final shift is the sigma-clipped mean over all matched stars, with
    the RMS residual reported and warnings raised when alignment is weak
    (few matches or high residuals).
  * Sub-pixel alignment via cubic-spline interpolation (scipy order=3).
  * Optional per-frame diagnostics CSV (--diagnostics) recording stars
    detected, stars matched, dx/dy, RMS residual, and alignment status.
  * Optional bias frame support (-bias), complementing -dark and -flat.

The command-line interface is backwards compatible with the original.

Typical usage for an exoplanet time-series or deep-sky stack:

    # Master calibration frames
    python fits-image-combiner.py bias/      -c average  --noalign -o master_bias.fits
    python fits-image-combiner.py darks_300s/ -c median  --noalign -o master_dark_300s.fits
    python fits-image-combiner.py r_flats/   -c avsigclip -N 2.5 --noalign --normalize -o master_r_flat.fits

    # Aligned science stack with diagnostics
    python fits-image-combiner.py NGC7331_r/ -dark master_dark_300s.fits \\
        -flat master_r_flat.fits -c avsigclip -N 3.0 \\
        --diagnostics ngc7331_alignment.csv -o NGC7331_r_combined.fits

Requires: numpy, scipy, astropy, photutils.
"""

import argparse
import csv
import os
import re
import sys
import warnings

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clip, sigma_clipped_stats
from scipy.ndimage import shift as scipy_shift, affine_transform
from scipy.spatial import cKDTree
from photutils.detection import DAOStarFinder
from photutils.centroids import centroid_sources, centroid_com

# --- photutils 2.x / 3.x compatibility -------------------------------
# photutils 3.0 renamed DAOStarFinder's 'peakmax' parameter to 'peak_max'
# and the output columns 'xcentroid'/'ycentroid' to 'x_centroid'/'y_centroid'.
import inspect as _inspect
_PEAK_KW = ('peak_max' if 'peak_max' in
            _inspect.signature(DAOStarFinder.__init__).parameters else 'peakmax')

def make_daofinder(fwhm, threshold, peak_max=None, **kwargs):
    """Construct a DAOStarFinder, mapping peak_max to the installed API."""
    if peak_max is not None:
        kwargs[_PEAK_KW] = peak_max
    return DAOStarFinder(fwhm=fwhm, threshold=threshold, **kwargs)

def source_xy(sources):
    """Return (x, y) arrays from a DAOStarFinder table, any photutils version."""
    if 'xcentroid' in sources.colnames:
        return np.array(sources['xcentroid']), np.array(sources['ycentroid'])
    return np.array(sources['x_centroid']), np.array(sources['y_centroid'])
# ----------------------------------------------------------------------


warnings.filterwarnings("ignore")


# ----------------------------------------------------------------------
# FITS I/O and calibration
# ----------------------------------------------------------------------

def load_fits_data(filepath):
    """Load the first 2D image HDU from a FITS file as float32."""
    with fits.open(filepath) as hdul:
        for hdu in hdul:
            if hasattr(hdu, 'data') and isinstance(hdu.data, np.ndarray) and hdu.data.ndim == 2:
                return hdu.data.astype(np.float32), hdu.header
    raise ValueError(f"No 2D image HDU found in {filepath}")


def save_fits_data(data, header, output_path):
    """Write a 2D image to FITS, preserving the reference header."""
    fits.PrimaryHDU(data.astype(np.float32), header=header).writeto(
        output_path, overwrite=True)


def bin_image(data, fy, fx, method='sum'):
    """
    Software-bin an image by integer factors (fy, fx).

    method='sum' mimics hardware CCD binning, where the charge of the
    binned pixels is summed in the readout register: correct for science
    frames, darks, and biases. method='mean' is used for flats, whose
    pixel values represent relative response rather than accumulated
    charge (the master flat is re-normalized afterwards in any case).
    """
    ny, nx = data.shape
    data = data[:ny - ny % fy, :nx - nx % fx]
    view = data.reshape(ny // fy, fy, nx // fx, fx)
    return view.sum(axis=(1, 3)) if method == 'sum' else view.mean(axis=(1, 3))


def binning_factors(big_shape, small_shape):
    """
    Integer factors (fy, fx) by which big_shape must be binned to reach
    small_shape, or None when the shapes are not integer multiples.
    """
    if big_shape == small_shape:
        return (1, 1)
    fy, fx = big_shape[0] / small_shape[0], big_shape[1] / small_shape[1]
    if fy >= 1 and fx >= 1 and fy == int(fy) and fx == int(fx):
        return (int(fy), int(fx))
    return None


def get_image_shape(filepath):
    """Read the 2D image shape from a FITS file via its headers (cheap)."""
    try:
        with fits.open(filepath) as hdul:
            for hdu in hdul:
                h = hdu.header
                if h.get('NAXIS', 0) == 2 and h.get('NAXIS1') and h.get('NAXIS2'):
                    return (int(h['NAXIS2']), int(h['NAXIS1']))
    except Exception:
        pass
    return None


def get_header_filter(filepath):
    """Read the FILTER keyword from a FITS header (None when absent)."""
    try:
        header = fits.getheader(filepath)
        value = header.get('FILTER', header.get('FILTNAM'))
        return None if value is None else str(value).strip()
    except Exception:
        return None


_FILTER_SYNONYMS = {
    # Observatories label narrowband filters inconsistently; these all
    # normalize to a canonical key (after lowercasing and removing
    # spaces, hyphens, and underscores).
    'halpha': 'ha', 'halfa': 'ha', 'h@': 'ha',
    'o3': 'oiii', 'oxygeniii': 'oiii', 'oxygen3': 'oiii',
    's2': 'sii', 'sulphurii': 'sii', 'sulfurii': 'sii', 'sulfur2': 'sii',
}


def _normalize_filter(name):
    key = re.sub(r"[\s\-_]", "", str(name).lower())
    return _FILTER_SYNONYMS.get(key, key)


def object_matches(value, wanted):
    """Object-name comparison that ignores case, whitespace, hyphens, and
    underscores, so 'NGC 7331', 'ngc7331', and 'NGC_7331' all match."""
    if value is None:
        return False
    norm = lambda s: re.sub(r"[\s\-_]", "", str(s).lower())
    return norm(value) == norm(wanted)


def filter_matches(value, wanted):
    """Filter-name comparison that ignores case, whitespace, hyphens, and
    common narrowband synonyms (H-a / Ha / Halpha, OIII / O3, SII / S2)."""
    if value is None:
        return False
    return _normalize_filter(value) == _normalize_filter(wanted)


def normalize_flat(flat_data):
    """Normalize a flat field to median 1.0 (positive pixels only)."""
    med = np.median(flat_data[flat_data > 0])
    if med <= 0:
        raise ValueError("Flat field has non-positive median; cannot normalize.")
    flat = flat_data / med
    flat[flat <= 0] = 1.0  # avoid division problems on dead pixels
    return flat


def apply_calibrations(image, bias_data=None, dark_data=None, flat_data=None):
    """Apply bias subtraction, dark subtraction, and flat division in order."""
    if bias_data is not None:
        image = image - bias_data
    if dark_data is not None:
        image = image - dark_data
    if flat_data is not None:
        image = image / flat_data
    return image


# ----------------------------------------------------------------------
# Star detection
# ----------------------------------------------------------------------

def estimate_fwhm(image, bkg_median, bkg_std, saturation=65000.0):
    """
    Quick FWHM estimate from the brightest unsaturated stars: detect with a
    generous trial FWHM, then measure each star's effective FWHM from the
    area of its profile above half maximum. Returns the median, clamped to
    a sensible range, or a default of 5.0 px when nothing is measurable.
    """
    try:
        # The central ~30% of the frame is representative and far cheaper
        # to convolve than the full sensor.
        ny, nx = image.shape
        if image.size > 12_000_000:
            image = np.ascontiguousarray(
                image[int(ny * 0.35):int(ny * 0.65),
                      int(nx * 0.35):int(nx * 0.65)])
        finder = make_daofinder(fwhm=8.0, threshold=12.0 * bkg_std,
                                peak_max=saturation - bkg_median,
                                exclude_border=True)
        sources = finder(image - bkg_median)
        if sources is None or len(sources) == 0:
            return 5.0
        sources.sort('flux', reverse=True)
        x, y = source_xy(sources[:25])
        fwhms = []
        for xi, yi in zip(x.astype(int), y.astype(int)):
            cut = image[max(0, yi - 15):yi + 16, max(0, xi - 15):xi + 16] - bkg_median
            if cut.size < 100:
                continue
            peak = cut.max()
            if peak <= 0:
                continue
            fwhms.append(2.0 * np.sqrt(np.sum(cut > peak / 2) / np.pi))
        if not fwhms:
            return 5.0
        return float(np.clip(np.median(fwhms), 2.0, 15.0))
    except Exception:
        return 5.0


def find_star_centroids(image, max_stars=40, fwhm=None, threshold_sigma=8.0,
                        saturation=65000.0, verbose=True,
                        detect_max_pixels=12_000_000):
    """
    Detect bright, unsaturated stars and refine their centroids.

    Algorithm:
      1. Estimate background median and noise with sigma-clipped statistics
         (subsampled, zeros from blank borders excluded).
      2. Detect candidates with DAOStarFinder, using a peakmax cut (rejects
         saturated stars) and sharpness/roundness limits (rejects hot
         pixels and cosmic rays). On very large sensors the detection runs
         on a mean-binned copy of the frame, which cuts the convolution
         cost by the binning area; only the candidate POSITIONS come from
         the binned copy.
      3. Keep the brightest max_stars detections.
      4. Refine every centroid at FULL resolution with a center-of-mass
         fit in an FWHM-scaled box, so alignment accuracy is unaffected
         by the binned detection.

    Returns ((N, 2) array of (x, y) centroids brightest-first, fwhm).
    """
    flat = image.ravel()
    if flat.size > 1_000_000:
        flat = flat[:: flat.size // 1_000_000]
    nz = flat[flat != 0]  # exclude blank borders / dead regions
    if len(nz) > 1000:
        flat = nz
    _, bkg_median, bkg_std = sigma_clipped_stats(flat, sigma=3.0, maxiters=5)

    if not np.isfinite(bkg_std) or bkg_std <= 0:
        if verbose:
            print("  Could not estimate background noise; no stars found.")
        return np.empty((0, 2)), 5.0

    if fwhm is None:
        fwhm = estimate_fwhm(image, bkg_median, bkg_std, saturation)
        if verbose:
            print(f"  Auto-estimated FWHM: {fwhm:.1f} px")

    # Choose a detection binning that brings the convolution under
    # detect_max_pixels; candidate positions scale back up afterwards.
    det_bin = 1
    while image.size / det_bin**2 > detect_max_pixels and det_bin < 4:
        det_bin *= 2
    if det_bin > 1:
        ny, nx = image.shape
        det_img = image[:ny - ny % det_bin, :nx - nx % det_bin]
        det_img = det_img.reshape(ny // det_bin, det_bin,
                                  nx // det_bin, det_bin).mean(axis=(1, 3))
        det_fwhm = max(fwhm / det_bin, 1.8)
        dflat = det_img.ravel()[:: max(1, det_img.size // 1_000_000)]
        dnz = dflat[dflat != 0]
        if len(dnz) > 1000:
            dflat = dnz
        _, det_med, det_std = sigma_clipped_stats(dflat, sigma=3.0, maxiters=5)
    else:
        det_img, det_fwhm = image, fwhm
        det_med, det_std = bkg_median, bkg_std

    finder = make_daofinder(
        fwhm=det_fwhm,
        threshold=threshold_sigma * det_std,
        peak_max=saturation - det_med,     # reject saturated stars
        sharplo=0.25, sharphi=0.95,        # reject hot pixels / blends
        roundlo=-0.8, roundhi=0.8,         # reject cosmic rays / streaks
        exclude_border=True,
    )
    sources = finder(det_img - det_med)
    if sources is None or len(sources) == 0:
        if verbose:
            print("  No stars found!")
        return np.empty((0, 2)), fwhm

    sources.sort('flux', reverse=True)
    sources = sources[:max_stars]

    x, y = source_xy(sources)
    if det_bin > 1:
        # Map binned-pixel coordinates to full-resolution coordinates
        # (center of the binned pixel block).
        x = x * det_bin + (det_bin - 1) / 2.0
        y = y * det_bin + (det_bin - 1) / 2.0

    # Refine centroids at full resolution in an FWHM-scaled box.
    box = max(int(2 * fwhm) | 1, 7)
    try:
        xr, yr = centroid_sources(image - bkg_median, x, y, box_size=box,
                                  centroid_func=centroid_com)
        good = np.isfinite(xr) & np.isfinite(yr)
        x, y = np.where(good, xr, x), np.where(good, yr, y)
    except Exception:
        pass

    coords = np.column_stack([x, y])
    if verbose:
        binnote = f", detected on {det_bin}x{det_bin}-binned copy" \
            if det_bin > 1 else ""
        print(f"  Detected {len(coords)} unsaturated stars "
              f"(background={bkg_median:.1f}, noise={bkg_std:.1f} ADU, "
              f"FWHM={fwhm:.1f} px{binnote})")
    return coords, fwhm


# ----------------------------------------------------------------------
# Star matching and shift estimation
# ----------------------------------------------------------------------

def estimate_offset_consensus(ref_coords, target_coords, tolerance=2.0):
    """
    Find the translation that maps target stars onto reference stars by
    offset consensus, which works even for shifts much larger than the
    typical star separation.

    Every (reference, target) pair implies a candidate offset; the true
    translation is the offset that the most pairs agree on. A KD-tree over
    all pairwise offsets finds, for each candidate, how many other offsets
    lie within `tolerance` pixels; the densest cluster wins and its mean
    is returned as the initial shift estimate.
    """
    offsets = (ref_coords[:, None, :] - target_coords[None, :, :]).reshape(-1, 2)
    if len(offsets) == 0:
        return None
    tree = cKDTree(offsets)
    counts = tree.query_ball_point(offsets, r=tolerance, return_length=True)
    best = int(np.argmax(counts))
    if counts[best] < 3:
        # Fewer than three agreeing pairs is indistinguishable from
        # coincidence and produces garbage transforms; report no consensus.
        return None
    cluster = offsets[tree.query_ball_point(offsets[best], r=tolerance)]
    return cluster.mean(axis=0)


def ransac_pair_match(ref_coords, target_coords, match_radius=3.0,
                      allow_rotation=True, min_matches=3,
                      n_brightest=30, dist_tol=2.0, min_pair_dist=100.0):
    """
    Rotation-robust star matching by pairwise-distance RANSAC.

    Translation-offset consensus fails when the field has rotated between
    frames (common across nights, after meridian flips, or with rotator
    repositioning), because the apparent offset then varies across the
    field. This matcher is invariant to rotation: distances between star
    pairs do not change under rotation + translation, so every reference
    pair whose separation matches a target pair's separation proposes a
    rigid transform (the rotation that maps one segment onto the other).
    Each hypothesis is scored by how many stars it brings into agreement,
    and the best one wins.

    Returns (R, t, n_inliers) for the best hypothesis with at least
    min_matches inliers, or None.
    """
    refs = ref_coords[:n_brightest]
    tgts = target_coords[:n_brightest]
    if len(refs) < 2 or len(tgts) < 2:
        return None

    def pair_list(pts):
        pairs = []
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                d = float(np.hypot(*(pts[j] - pts[i])))
                if d >= min_pair_dist:
                    pairs.append((d, i, j))
        pairs.sort()
        return pairs

    ref_pairs = pair_list(refs)
    tgt_pairs = pair_list(tgts)
    if not ref_pairs or not tgt_pairs:
        return None
    tgt_d = np.array([p[0] for p in tgt_pairs])

    ref_tree = cKDTree(ref_coords)
    best = None  # (n_inliers, R, t)
    n_hyp = 0
    target_inliers = 0.8 * min(len(ref_coords), len(target_coords))

    for d, i, j in ref_pairs:
        lo = np.searchsorted(tgt_d, d - dist_tol)
        hi = np.searchsorted(tgt_d, d + dist_tol)
        for idx in range(lo, hi):
            _, k, l = tgt_pairs[idx]
            # Two correspondence orderings per matching pair.
            for (a, b) in (((i, k), (j, l)), ((i, l), (j, k))):
                (ri, tk), (rj, tl) = a, b
                v_ref = refs[rj] - refs[ri]
                v_tgt = tgts[tl] - tgts[tk]
                ang = (np.arctan2(v_ref[1], v_ref[0])
                       - np.arctan2(v_tgt[1], v_tgt[0]))
                if not allow_rotation and abs(np.degrees(ang)) > 0.5:
                    continue
                c, s = np.cos(ang), np.sin(ang)
                R = np.array([[c, -s], [s, c]])
                t = refs[ri] - R @ tgts[tk]
                moved = target_coords @ R.T + t
                dist, _ = ref_tree.query(moved,
                                         distance_upper_bound=match_radius)
                n_in = int(np.sum(np.isfinite(dist) & (dist < match_radius)))
                n_hyp += 1
                if best is None or n_in > best[0]:
                    best = (n_in, R, t)
                    if n_in >= target_inliers:
                        return best[1], best[2], best[0]
                if n_hyp > 4000:
                    break
            if n_hyp > 4000:
                break
        if n_hyp > 4000:
            break

    if best is None or best[0] < min_matches:
        return None
    return best[1], best[2], best[0]


def fit_rigid_transform(ref_pts, tgt_pts, allow_rotation=True):
    """
    Least-squares rigid transform (rotation + translation, no scale) mapping
    target-frame star positions onto reference-frame positions:

        p_ref ~= R @ p_tgt + t

    Solved with the 2D Kabsch algorithm (SVD of the cross-covariance of the
    centered point sets). Returns (R, t, residuals) where residuals is the
    per-star (N, 2) array of ref - (R @ tgt + t).
    """
    rc, tc = ref_pts.mean(axis=0), tgt_pts.mean(axis=0)
    R0, T0 = ref_pts - rc, tgt_pts - tc
    if allow_rotation and len(ref_pts) >= 2:
        H = T0.T @ R0
        U, _, Vt = np.linalg.svd(H)
        d = np.sign(np.linalg.det(Vt.T @ U.T))
        R = Vt.T @ np.diag([1.0, d]) @ U.T
    else:
        R = np.eye(2)
    t = rc - R @ tc
    residuals = ref_pts - (tgt_pts @ R.T + t)
    return R, t, residuals


def match_pairs(ref_coords, tgt_transformed, match_radius):
    """One-to-one nearest-neighbor matching within match_radius pixels.

    Returns (ref_idx, tgt_idx) index arrays of the matched pairs."""
    tree = cKDTree(ref_coords)
    dist, idx = tree.query(tgt_transformed, distance_upper_bound=match_radius)
    good = np.isfinite(dist) & (dist < match_radius)
    best = {}
    for t_i in np.where(good)[0]:
        r_i = idx[t_i]
        if r_i not in best or dist[t_i] < best[r_i][0]:
            best[r_i] = (dist[t_i], t_i)
    ref_idx = np.array(sorted(best.keys()), dtype=int)
    tgt_idx = np.array([best[r][1] for r in ref_idx], dtype=int)
    return ref_idx, tgt_idx


def refine_transform(ref_coords, target_coords, R, t, match_radius,
                     clip_sigma=2.5, allow_rotation=True):
    """
    Refine an initial rigid transform: match all stars one-to-one at the
    given transform, fit, sigma-clip residual outliers, re-match at the
    tight radius, and fit once more.

    Returns (R, t, n_matched, rms) or None when matching collapses.
    """
    transformed = target_coords @ R.T + t
    ref_idx, tgt_idx = match_pairs(ref_coords, transformed,
                                   max(2.0 * match_radius, 6.0))
    if len(ref_idx) < 2:
        return None
    R, t, residuals = fit_rigid_transform(ref_coords[ref_idx],
                                          target_coords[tgt_idx],
                                          allow_rotation)
    rdist = np.sqrt(np.sum(residuals**2, axis=1))
    clipped = sigma_clip(rdist, sigma=clip_sigma, maxiters=5)
    keep = ~clipped.mask
    if np.sum(keep) >= 2:
        R, t, _ = fit_rigid_transform(ref_coords[ref_idx[keep]],
                                      target_coords[tgt_idx[keep]],
                                      allow_rotation)

    # Final pass at the tight radius with the refined transform.
    transformed = target_coords @ R.T + t
    ref_idx, tgt_idx = match_pairs(ref_coords, transformed, match_radius)
    if len(ref_idx) < 2:
        return None
    R, t, residuals = fit_rigid_transform(ref_coords[ref_idx],
                                          target_coords[tgt_idx],
                                          allow_rotation)
    rdist = np.sqrt(np.sum(residuals**2, axis=1))
    clipped = sigma_clip(rdist, sigma=clip_sigma, maxiters=5)
    keep = ~clipped.mask if np.sum(~clipped.mask) >= 2 \
        else np.ones(len(rdist), bool)
    R, t, residuals = fit_rigid_transform(ref_coords[ref_idx[keep]],
                                          target_coords[tgt_idx[keep]],
                                          allow_rotation)
    n_matched = int(np.sum(keep))
    rms = float(np.sqrt(np.mean(np.sum(residuals**2, axis=1))))
    return R, t, n_matched, rms


def match_and_measure_shift(ref_coords, target_coords, match_radius=3.0,
                            consensus_tol=2.0, clip_sigma=2.5,
                            allow_rotation=True, min_matches=3,
                            verbose=True):
    """
    Match stars between frames and measure the frame transform robustly.

    Two hypothesis generators are tried, cheapest first:

      1. Translation offset consensus: the translation that the most star
         pairs agree on. Fast and accurate for ordinary dithers with
         little rotation between frames.
      2. Pairwise-distance RANSAC: rotation-invariant matching that
         handles large dithers combined with field rotation (multi-night
         data sets, meridian flips, rotator repositioning).

    Whichever hypothesis survives refinement with the most matched stars
    wins. Refinement fits a rigid transform (2D Kabsch) with sigma-clipped
    outlier rejection and a final tight-radius re-match.

    Returns a dict with keys dx, dy, rot_deg, R, t, n_matched, rms, or
    None when no hypothesis reaches min_matches matched stars (the caller
    should then treat the frame as unalignable rather than apply a
    transform fit from too few stars).
    """
    results = []

    # Hypothesis 1: translation consensus.
    coarse_tol = max(consensus_tol, 6.0)
    initial = estimate_offset_consensus(ref_coords, target_coords,
                                        tolerance=coarse_tol)
    if initial is not None:
        refined = refine_transform(ref_coords, target_coords,
                                   np.eye(2), initial, match_radius,
                                   clip_sigma, allow_rotation)
        if refined is not None:
            results.append(refined)

    # Hypothesis 2: rotation-robust RANSAC, tried when consensus failed
    # or produced a weak solution.
    if not results or results[0][2] < max(min_matches, 5):
        hyp = ransac_pair_match(ref_coords, target_coords,
                                match_radius=match_radius,
                                allow_rotation=allow_rotation,
                                min_matches=min_matches)
        if hyp is not None:
            R0, t0, _ = hyp
            refined = refine_transform(ref_coords, target_coords, R0, t0,
                                       match_radius, clip_sigma,
                                       allow_rotation)
            if refined is not None:
                results.append(refined)

    if not results:
        return None
    R, t, n_matched, rms = max(results, key=lambda r: r[2])
    # A genuine overlap shares most of its bright stars between frames, so
    # beyond the absolute minimum, the matches must account for a
    # reasonable fraction of the stars available; this rejects the rare
    # coincidental fits a random field can produce.
    min_required = max(min_matches,
                       int(np.ceil(0.25 * min(len(ref_coords),
                                              len(target_coords)))))
    if n_matched < min_required:
        if verbose:
            print(f"  Only {n_matched} star(s) could be matched "
                  f"(required {min_required}); alignment rejected.")
        return None

    rot_deg = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    center = ref_coords.mean(axis=0)
    eff = (R @ center + t) - center
    dx, dy = float(eff[0]), float(eff[1])

    if verbose:
        rot_str = (f", rotation={rot_deg * 60:.2f} arcmin"
                   if abs(rot_deg) > 1e-4 else "")
        print(f"  Matched {n_matched} stars")
        print(f"  Transform: dx={dx:+.3f}, dy={dy:+.3f}{rot_str}, "
              f"RMS residual={rms:.3f} px")

    return {'dx': dx, 'dy': dy, 'rot_deg': rot_deg, 'R': R, 't': t,
            'n_matched': n_matched, 'rms': rms}


def apply_rigid_transform(image, R, t, order=3):
    """
    Resample an image onto the reference frame given the rigid transform
    p_ref = R @ p_tgt + t (in x, y pixel coordinates).

    scipy.ndimage.affine_transform computes input = M @ output + offset in
    (row, col) = (y, x) order, so the inverse mapping is converted with the
    axis-swap matrix P: M = P R^-1 P, offset = -P R^-1 t.
    """
    Rinv = np.linalg.inv(R)
    P = np.array([[0.0, 1.0], [1.0, 0.0]])
    M = P @ Rinv @ P
    offset = -(P @ Rinv @ t)
    return affine_transform(image, M, offset=offset, order=order,
                            mode='constant', cval=0.0)


# ----------------------------------------------------------------------
# Image combination
# ----------------------------------------------------------------------

def combine_images(image_stack, method="average", sigma=3.0, chunk_rows=512):
    """
    Combine a stack along axis 0 with the chosen statistical method.

    The combination is performed in horizontal slabs of chunk_rows rows so
    that memory-hungry operations (sigma clipping creates masked arrays,
    sorting creates a full copy) stay bounded even for very large sensors.
    """
    n, ny, nx = image_stack.shape
    out = np.empty((ny, nx), dtype=np.float32)
    for y0 in range(0, ny, chunk_rows):
        y1 = min(y0 + chunk_rows, ny)
        slab = image_stack[:, y0:y1, :]
        if method == "median":
            out[y0:y1] = np.median(slab, axis=0)
        elif method == "avsigclip":
            clipped = sigma_clip(slab, sigma=sigma, axis=0)
            out[y0:y1] = np.mean(clipped, axis=0).filled(0)
        elif method == "nomax":
            if n > 1:
                out[y0:y1] = np.mean(np.sort(slab, axis=0)[:-1], axis=0)
            else:
                out[y0:y1] = slab[0]
        else:
            out[y0:y1] = np.mean(slab, axis=0)
    return out


def normalize_output(image, method="average"):
    """Normalize the combined image by its mean (or median for -c median)."""
    norm = np.median(image) if method == "median" else np.mean(image)
    if norm == 0:
        print("Warning: normalization value is zero, skipping normalization.")
        return image
    return image / norm


# ----------------------------------------------------------------------
# Main processing
# ----------------------------------------------------------------------

def process_images(image_dir, bias_path=None, dark_path=None, flat_path=None,
                   sigma=3.0, combine_method="average", noalign=False,
                   normalize=False, max_stars=40, fwhm=None,
                   saturation=65000.0, min_matches=3, max_rms=1.0,
                   allow_rotation=True, keep_unaligned=False,
                   scale_exptime=True, diagnostics_path=None,
                   filter_name=None, object_name=None, output_path=None,
                   register_dir=None, name_only=None):
    """Load, calibrate, align, and combine all FITS images in a directory."""
    bias_data = load_fits_data(bias_path)[0] if bias_path else None
    dark_data = load_fits_data(dark_path)[0] if dark_path else None
    flat_data = normalize_flat(load_fits_data(flat_path)[0]) if flat_path else None

    calib_files = {os.path.abspath(p) for p in (bias_path, dark_path, flat_path) if p}
    all_fits = [f for f in sorted(os.listdir(image_dir))
                if f.lower().endswith(('.fits', '.fit', '.fts'))]
    image_files, own_outputs = [], []
    for f in all_fits:
        full = os.path.join(image_dir, f)
        if os.path.abspath(full) in calib_files:
            continue
        # Recognize this suite's own products by name and leave them out:
        # stacking a previous stack or a master frame into a new stack
        # silently corrupts it.
        if re.search(r"_stack_\d+_", f) or f.startswith("master_"):
            own_outputs.append(f)
            continue
        image_files.append(full)
    if own_outputs:
        print(f"Ignoring {len(own_outputs)} previous pipeline output(s) "
              f"found in the directory (rename them if you truly want them "
              f"stacked):")
        for f in own_outputs:
            print(f"  {f}")
    if not image_files:
        raise ValueError("No valid FITS images found in directory.")

    # ------------------------------------------------------------------
    # Filter selection. The FILTER keyword of every frame is read first.
    # When --filter was given, only matching frames are kept. When it was
    # not, but the directory mixes filters, the filter of the first frame
    # is adopted automatically, since stacking frames taken through
    # different filters is never meaningful. Either way the program
    # reports exactly which frames were used and which were set aside.
    # ------------------------------------------------------------------
    # Single header pass per file: filter, image shape, and exposure time
    # are all read here (large directories pay once, not three times).
    file_meta = {}
    for f in image_files:
        meta = {'filter': None, 'shape': None, 'exptime': 0.0,
                'object': None}
        try:
            with fits.open(f) as hdul:
                for hdu in hdul:
                    h = hdu.header
                    if meta['filter'] is None:
                        v = h.get('FILTER', h.get('FILTNAM'))
                        if v is not None:
                            meta['filter'] = str(v).strip()
                    if meta['object'] is None:
                        v = h.get('OBJECT', h.get('OBJNAME'))
                        if v is not None:
                            meta['object'] = str(v).strip()
                    if meta['shape'] is None and h.get('NAXIS', 0) == 2 \
                            and h.get('NAXIS1') and h.get('NAXIS2'):
                        meta['shape'] = (int(h['NAXIS2']), int(h['NAXIS1']))
                    if not meta['exptime']:
                        meta['exptime'] = float(
                            h.get('EXPTIME', h.get('EXPOSURE', 0)) or 0)
        except Exception:
            pass
        file_meta[f] = meta
    header_filters = {f: m['filter'] for f, m in file_meta.items()}

    # ------------------------------------------------------------------
    # Object selection: when an object name is given, keep only frames
    # whose OBJECT header matches it (ignoring case, spaces, hyphens, and
    # underscores), so a directory holding several targets stacks cleanly.
    # ------------------------------------------------------------------
    if object_name:
        selected, skipped = [], []
        for f in image_files:
            if object_matches(file_meta[f]['object'], object_name):
                selected.append(f)
            else:
                skipped.append(f)
        if skipped:
            print(f"Object selection: using {len(selected)} of "
                  f"{len(image_files)} FITS files with OBJECT matching "
                  f"{object_name!r}")
            for f in skipped:
                print(f"  skipping {os.path.basename(f)} "
                      f"(OBJECT = {file_meta[f]['object']!r})")
        if not selected:
            raise ValueError(f"No images in {image_dir} have OBJECT "
                             f"matching {object_name!r} in their headers.")
        image_files = selected

    if not filter_name:
        distinct = {v for v in header_filters.values() if v is not None}
        if len(distinct) > 1:
            filter_name = header_filters[image_files[0]]
            print(f"Multiple filters found in {image_dir}: "
                  f"{', '.join(sorted(repr(d) for d in distinct))}")
            print(f"Adopting the first frame's filter, {filter_name!r}. "
                  f"Use --filter to choose a different one.")

    used_filter = None
    if filter_name:
        selected, skipped = [], []
        for f in image_files:
            if filter_matches(header_filters[f], filter_name):
                selected.append(f)
            else:
                skipped.append(f)
        if skipped:
            print(f"Filter selection: using {len(selected)} of "
                  f"{len(image_files)} FITS files with FILTER = "
                  f"{filter_name!r}")
            for f in skipped:
                print(f"  skipping {os.path.basename(f)} "
                      f"(FILTER = {header_filters[f]!r})")
        if not selected:
            raise ValueError(f"No images in {image_dir} have FILTER = "
                             f"{filter_name!r} in their headers.")
        image_files = selected
        used_filter = filter_name.strip()
    else:
        # Uniform directory (or no FILTER keywords at all)
        uniform = {v for v in header_filters.values() if v is not None}
        if len(uniform) == 1:
            used_filter = uniform.pop().strip()

    # ------------------------------------------------------------------
    # Shape reconciliation: science frames and calibration frames may have
    # been taken at different camera binnings (e.g. 1x1 science with 2x2
    # flats). The working resolution is the smallest of the frames in
    # play; every higher-resolution frame is software-binned down to it.
    # Science frames, darks, and biases are binned by summation (mimicking
    # hardware binning); flats are binned by averaging and re-normalized.
    # ------------------------------------------------------------------
    science_shapes = {f: file_meta[f]['shape'] for f in image_files
                      if file_meta[f]['shape'] is not None}
    if not science_shapes:
        raise ValueError(f"No 2D images found among the selected files.")
    science_shape = science_shapes[image_files[0]]

    # The working resolution is the smallest frame in play, scanning every
    # selected science frame (directories sometimes mix camera binnings
    # within one filter) as well as the calibration frames.
    shapes = {'science': min(science_shapes.values(),
                             key=lambda s: s[0] * s[1])}
    for name, arr in (('bias', bias_data), ('dark', dark_data),
                      ('flat', flat_data)):
        if arr is not None:
            shapes[name] = arr.shape
    target_shape = min(shapes.values(), key=lambda s: s[0] * s[1])

    if len(set(science_shapes.values())) > 1:
        from collections import Counter
        counts = Counter(science_shapes.values())
        print("Science frames have mixed sizes (mixed camera binnings):")
        for s, n in sorted(counts.items(), key=lambda kv: -kv[0][0]):
            print(f"  {s[1]} x {s[0]}: {n} frame(s)")
        print(f"  -> all frames will be brought to "
              f"{target_shape[1]} x {target_shape[0]}.")

    science_bin = binning_factors(science_shape, target_shape) or (1, 1)
    if len(set(shapes.values())) > 1:
        print("\nFrame sizes differ (different camera binnings):")
        for name, s in shapes.items():
            print(f"  {name}: {s[1]} x {s[0]}")
        for name, s in shapes.items():
            if binning_factors(s, target_shape) is None:
                raise ValueError(
                    f"The {name} frame shape {s} is not an integer multiple "
                    f"of the smallest frame shape {target_shape}; these "
                    f"frames cannot be combined.")
        print(f"  -> working resolution will be {target_shape[1]} x "
              f"{target_shape[0]}; higher-resolution frames are "
              f"software-binned to match.")

        if science_bin != (1, 1):
            print(f"  WARNING: science images will be binned (summed) to "
                  f"match; the output stack is at the reduced resolution. "
                  f"For full resolution, take calibration frames at the "
                  f"science binning.")
            # The saturation threshold for star detection is scaled per
            # frame by the binning each frame actually receives (frames in
            # a mixed-binning directory may need different factors).
        if bias_data is not None:
            fy, fx = binning_factors(bias_data.shape, target_shape)
            if (fy, fx) != (1, 1):
                print(f"  WARNING: bias binned {fy}x{fx} by summation; "
                      f"mixing binnings for bias/dark frames is approximate.")
                bias_data = bin_image(bias_data, fy, fx, 'sum')
        if dark_data is not None:
            fy, fx = binning_factors(dark_data.shape, target_shape)
            if (fy, fx) != (1, 1):
                print(f"  WARNING: dark binned {fy}x{fx} by summation; "
                      f"mixing binnings for bias/dark frames is approximate.")
                dark_data = bin_image(dark_data, fy, fx, 'sum')
        if flat_data is not None:
            fy, fx = binning_factors(flat_data.shape, target_shape)
            if (fy, fx) != (1, 1):
                print(f"  Flat binned {fy}x{fx} (averaged, re-normalized).")
                flat_data = normalize_flat(bin_image(flat_data, fy, fx, 'mean'))

    def prepare_science(img, name=''):
        """Bin a science frame to the working resolution when needed.

        Returns (image, area_factor) where area_factor is the number of
        original pixels summed into each output pixel (1 when no binning
        was applied): the saturation level for star detection must scale
        with it. A frame whose shape cannot be integer-binned to the
        working resolution is rejected."""
        if img.shape == target_shape:
            return img, 1
        factors = binning_factors(img.shape, target_shape)
        if factors is None:
            raise ValueError(
                f"{name}: shape {img.shape} is incompatible with the "
                f"working resolution {target_shape}")
        print(f"  ({name}: binned {factors[0]}x{factors[1]} to match the "
              f"working resolution)")
        binned = bin_image(img, factors[0], factors[1], 'sum').astype(np.float32)
        return binned, factors[0] * factors[1]

    diagnostics = []

    # Reference frame: first image, calibrated.
    print(f"Reference frame: {os.path.basename(image_files[0])}")
    ref_image, header = load_fits_data(image_files[0])
    ref_image, ref_area = prepare_science(ref_image,
                                          os.path.basename(image_files[0]))
    ref_image = apply_calibrations(ref_image, bias_data, dark_data, flat_data)
    registered_records = [(os.path.basename(image_files[0]), header)]
    ref_exptime = float(header.get('EXPTIME', header.get('EXPOSURE', 0)) or 0)
    ref_bkg_level = float(np.median(ref_image[::97, ::97]))

    # Mixed exposure times: frames are scaled to the reference frame's
    # exposure so the combination (especially sigma clipping) compares
    # like with like. Disable with --no-exptime-scale.
    all_exptimes = [file_meta[f]['exptime'] for f in image_files]
    exptime_scaling = False
    if scale_exptime and ref_exptime > 0:
        valid_exps = [e for e in all_exptimes if e > 0]
        if valid_exps and (max(valid_exps) / min(valid_exps)) > 1.05:
            exptime_scaling = True
            print(f"Exposure times range {min(valid_exps):.0f}-"
                  f"{max(valid_exps):.0f} s; frames will be scaled to the "
                  f"reference exposure of {ref_exptime:.0f} s before "
                  f"combination.")
            if dark_data is not None:
                print("  NOTE: a single master dark is being applied to "
                      "frames of different exposure times, which is only "
                      "approximate; matched-exposure darks are better "
                      "practice.")
    image_stack = [ref_image]
    diagnostics.append({'filename': os.path.basename(image_files[0]),
                        'n_detected': -1, 'n_matched': -1,
                        'dx': 0.0, 'dy': 0.0, 'rot_deg': 0.0, 'rms': 0.0,
                        'aligned': True, 'note': 'reference frame'})

    ref_stars = None
    if not noalign:
        print("Finding alignment stars in reference frame:")
        ref_stars, ref_fwhm = find_star_centroids(
            ref_image, max_stars=max_stars, fwhm=fwhm,
            saturation=saturation * ref_area)
        fwhm = ref_fwhm  # reuse the measured FWHM for all later frames
        diagnostics[0]['n_detected'] = len(ref_stars)
        if len(ref_stars) < min_matches:
            print("WARNING: too few stars in the reference frame for alignment; "
                  "falling back to --noalign behavior.")
            noalign = True

    n_warned = 0
    n_total = len(image_files)
    for file_idx, (file, file_exptime) in enumerate(
            zip(image_files[1:], all_exptimes[1:]), start=2):
        basename = os.path.basename(file)
        img_data, frame_header = load_fits_data(file)
        diag = {'filename': basename, 'n_detected': -1, 'n_matched': 0,
                'dx': 0.0, 'dy': 0.0, 'rot_deg': 0.0, 'rms': np.nan,
                'aligned': False, 'note': ''}
        try:
            img_data, frame_area = prepare_science(img_data, basename)
        except ValueError as e:
            print(f"  WARNING: skipping {basename}: {e}")
            diag['note'] = 'skipped: incompatible image size'
            diagnostics.append(diag)
            continue
        img_data = apply_calibrations(img_data, bias_data, dark_data, flat_data)

        # Exposure scaling happens before anything else looks at the data,
        # so the level check, detection, and saturation threshold all see
        # consistent values.
        exp_scale = 1.0
        if exptime_scaling and file_exptime > 0:
            exp_scale = ref_exptime / file_exptime
            if exp_scale != 1.0:
                img_data = img_data * exp_scale
        frame_sat = saturation * frame_area * exp_scale

        if noalign:
            print(f"Loading file (no alignment) ({file_idx}/{n_total}): "
                  f"{basename}")
            diag['note'] = 'alignment disabled'
            diag['aligned'] = True
            image_stack.append(img_data)
            registered_records.append((basename, frame_header))
            diagnostics.append(diag)
            continue

        print(f"\nAligning file ({file_idx}/{n_total}): {basename}")
        bkg_check = float(np.median(img_data[::97, ::97]))
        if bkg_check > 0.75 * frame_sat:
            print(f"  WARNING: sky background ({bkg_check:.0f} ADU) is near "
                  f"the saturation level; this frame is probably unusable "
                  f"(twilight, clouds, or moonlight).")

        # Data-level sanity check: a frame whose background differs from
        # the reference by more than a factor of 100 (after exposure
        # scaling) is almost certainly not a raw science frame: typical
        # culprits are previous stack outputs, normalized masters, or
        # otherwise processed files left in the science directory. Such a
        # frame can pass alignment (the stars are in the right places!)
        # while quietly corrupting the combination, so it is excluded.
        if ref_bkg_level > 10 and not keep_unaligned:
            if bkg_check < ref_bkg_level / 100 or \
                    bkg_check > ref_bkg_level * 100:
                print(f"  WARNING: data level ({bkg_check:.1f} ADU "
                      f"background) is wildly inconsistent with the "
                      f"reference frame ({ref_bkg_level:.1f} ADU); this "
                      f"looks like a processed file (previous stack, "
                      f"normalized master), not a raw frame. EXCLUDED "
                      f"from the stack (--keep-unaligned overrides).")
                diag['note'] = 'inconsistent data level; excluded'
                n_warned += 1
                diagnostics.append(diag)
                continue
        tgt_stars, _ = find_star_centroids(img_data, max_stars=max_stars,
                                           fwhm=fwhm, saturation=frame_sat)
        diag['n_detected'] = len(tgt_stars)

        result = None
        if len(tgt_stars) >= min_matches:
            result = match_and_measure_shift(
                ref_stars, tgt_stars,
                match_radius=max(3.0, 0.75 * fwhm),
                consensus_tol=max(2.0, 0.5 * fwhm),
                allow_rotation=allow_rotation,
                min_matches=min_matches)

        if result is None:
            # A frame that cannot be aligned must not pollute the stack:
            # at typical dither amplitudes, adding it unshifted smears
            # every star into a streak. It is excluded unless the user
            # explicitly asked to keep unaligned frames.
            if keep_unaligned:
                print(f"  WARNING: could not align {basename}; stacking "
                      f"unshifted (--keep-unaligned).")
                diag['note'] = 'alignment failed; stacked unshifted'
                image_stack.append(img_data)
                registered_records.append((basename, frame_header))
            else:
                print(f"  WARNING: could not align {basename}; EXCLUDED "
                      f"from the stack.")
                diag['note'] = 'alignment failed; excluded from stack'
            n_warned += 1
            diagnostics.append(diag)
            continue

        diag.update({'n_matched': result['n_matched'], 'dx': result['dx'],
                     'dy': result['dy'], 'rot_deg': result['rot_deg'],
                     'rms': result['rms'], 'aligned': True})

        if result['rms'] > max_rms:
            print(f"  WARNING: RMS residual {result['rms']:.2f} px exceeds "
                  f"{max_rms:.2f} px; alignment may be unreliable.")
            diag['note'] = f"high RMS ({result['rms']:.2f} px)"
            n_warned += 1

        # Sub-pixel resampling with cubic-spline interpolation. A pure
        # translation uses scipy_shift; when rotation was detected the full
        # rigid transform is applied (essential on wide fields, where even
        # 0.1 degrees of rotator drift displaces corner stars by many px).
        if abs(result['rot_deg']) > 1e-4:
            shifted = apply_rigid_transform(img_data, result['R'], result['t'])
        else:
            shifted = scipy_shift(img_data,
                                  shift=(result['dy'], result['dx']),
                                  order=3, mode='constant', cval=0.0)
        image_stack.append(shifted)
        registered_records.append((basename, frame_header))
        diagnostics.append(diag)

    # ------------------------------------------------------------------
    # Register-only mode: write each aligned frame to its own FITS file,
    # carrying its original header (JD, EXPTIME, FILTER, OBJECT, ...) but
    # with the REFERENCE frame's WCS stamped in, since every frame now
    # lives on the reference pixel grid. This gives a time series whose
    # frames all agree about where the sky is, which is exactly what
    # WCS-based photometry needs.
    # ------------------------------------------------------------------
    if register_dir is not None:
        if len(image_stack) == 0:
            raise ValueError("No frames could be aligned; nothing to "
                             "register.")
        os.makedirs(register_dir, exist_ok=True)
        try:
            from astropy.wcs import WCS as _WCS
            ref_wcs_header = _WCS(header).to_header(relax=True)
        except Exception:
            ref_wcs_header = None
        n_written = 0
        for arr, (basename, frame_header) in zip(image_stack,
                                                 registered_records):
            out_hdr = (frame_header.copy() if frame_header is not None
                       else fits.Header())
            if ref_wcs_header is not None:
                # Remove any stale WCS, then stamp the reference solution.
                for key in list(out_hdr.keys()):
                    if key and (key.startswith(('CRVAL', 'CRPIX', 'CDELT',
                                                'CTYPE', 'CUNIT', 'CROTA',
                                                'CD1_', 'CD2_', 'PC1_',
                                                'PC2_', 'PV1_', 'PV2_',
                                                'A_', 'B_', 'AP_', 'BP_'))
                            or key in ('EQUINOX', 'RADESYS', 'LONPOLE',
                                       'LATPOLE', 'WCSAXES')):
                        try:
                            del out_hdr[key]
                        except KeyError:
                            pass
                out_hdr.update(ref_wcs_header)
            out_hdr['HISTORY'] = ('Registered to reference frame by NSUT '
                                  'fits-image-combiner')
            stem = os.path.splitext(basename)[0]
            stem = re.sub(r"[^A-Za-z0-9._+-]", "",
                          stem.replace("'", "p").replace(" ", "_"))
            out_path = os.path.join(register_dir, f"reg_{stem}.fits")
            fits.PrimaryHDU(arr.astype(np.float32),
                            header=out_hdr).writeto(out_path, overwrite=True)
            n_written += 1
        n_excluded = len(image_files) - n_written
        print(f"\nRegistered {n_written} aligned frame(s) to "
              f"'{register_dir}'"
              + (f" ({n_excluded} excluded)" if n_excluded > 0 else ""))
        if diagnostics_path:
            if diagnostics_path == 'auto':
                diagnostics_path = os.path.join(
                    register_dir, "registration_alignment_diagnostics.csv")
            with open(diagnostics_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['filename',
                                                       'n_detected',
                                                       'n_matched', 'dx',
                                                       'dy', 'rot_deg',
                                                       'rms', 'aligned',
                                                       'note'])
                writer.writeheader()
                writer.writerows(diagnostics)
            print(f"Alignment diagnostics saved as '{diagnostics_path}'")
        return

    if len(image_stack) == 0:
        raise ValueError("No frames could be aligned; nothing to combine. "
                         "Re-run with --keep-unaligned to stack regardless "
                         "(rarely a good idea) or check the data quality.")
    n_excluded = len(image_files) - len(image_stack)
    if n_excluded > 0:
        print(f"\n{n_excluded} of {len(image_files)} frames excluded "
              f"(unalignable or incompatible).")
    # ------------------------------------------------------------------
    # Automatic output naming, unless -o was given:
    #     <first input file>_stack_<N>_<filter>_b<binning>_<method>.fits
    # e.g. g_00001_stack_7_gp_b2_avsigclip.fits. The filter tag replaces
    # the prime with 'p' to stay filesystem-friendly (g' -> gp), and the
    # binning is the effective output binning: the camera binning read
    # from the first frame's header times any software binning applied
    # above to match the calibration frames.
    # ------------------------------------------------------------------
    # Named here, after exclusions, so the frame count in the filename
    # reflects what was actually combined.
    if output_path is None:
        # Prefer the object name as the prefix (explicit --object, else the
        # OBJECT/TARGET header of the first frame), so stacks are grouped
        # and identifiable by target; fall back to the first frame's
        # filename stem when no object name is available.
        prefix = None
        if object_name and object_name.strip():
            prefix = object_name.strip()
        elif name_only and name_only.strip():
            prefix = name_only.strip()
        else:
            try:
                hdr_obj = fits.getheader(image_files[0])
                for key in ('OBJECT', 'TARGET', 'TARGNAME', 'OBJNAME'):
                    v = hdr_obj.get(key)
                    if v and str(v).strip():
                        prefix = str(v).strip()
                        break
            except Exception:
                pass
        if not prefix:
            prefix = os.path.splitext(os.path.basename(image_files[0]))[0]
        # Filenames and headers can contain apostrophes (filter names),
        # spaces, and other characters that confuse shells and pattern
        # matching; sanitize the prefix before building on it.
        first = prefix.replace("'", "p").replace(" ", "_")
        first = re.sub(r"[^A-Za-z0-9._+-]", "", first) or "stack"
        parts = [first, "stack", str(len(image_stack))]
        if used_filter:
            parts.append(used_filter.replace("'", "p").replace(" ", ""))
        try:
            hdr0 = fits.getheader(image_files[0])
            hw_x = int(hdr0.get('XBINNING', 1))
            hw_y = int(hdr0.get('YBINNING', hw_x))
        except Exception:
            hw_x = hw_y = 1
        bin_x = hw_x * science_bin[1]
        bin_y = hw_y * science_bin[0]
        parts.append(f"b{bin_x}" if bin_x == bin_y else f"b{bin_y}x{bin_x}")
        parts.append(combine_method)
        output_path = "_".join(parts) + ".fits"
        print(f"Output file: {output_path}")

    image_stack = np.stack(image_stack)
    print(f"\nCombining {len(image_stack)} images using {combine_method} "
          f"method... (this step can take a few minutes for many large "
          f"frames)")
    combined = combine_images(image_stack, method=combine_method, sigma=sigma)

    if normalize:
        print(f"Normalizing output using {combine_method} of pixel values...")
        combined = normalize_output(combined, method=combine_method)

    save_fits_data(combined, header, output_path)
    print(f"Final combined image saved as '{output_path}'")

    print("\nOutput image statistics:")
    print(f"  Min: {np.min(combined):.4f}")
    print(f"  Max: {np.max(combined):.4f}")
    print(f"  Mean: {np.mean(combined):.4f}")
    print(f"  Median: {np.median(combined):.4f}")

    if not noalign:
        n_aligned = sum(1 for d in diagnostics if d['aligned'])
        print(f"\nAlignment summary: {n_aligned}/{len(diagnostics)} frames aligned"
              + (f", {n_warned} warnings" if n_warned else ""))

    if diagnostics_path:
        if diagnostics_path == 'auto':
            diagnostics_path = (os.path.splitext(output_path)[0]
                                + "_alignment_diagnostics.csv")
        with open(diagnostics_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['filename', 'n_detected',
                                                   'n_matched', 'dx', 'dy',
                                                   'rot_deg', 'rms',
                                                   'aligned', 'note'])
            writer.writeheader()
            writer.writerows(diagnostics)
        print(f"Alignment diagnostics saved as '{diagnostics_path}'")


def main():
    parser = argparse.ArgumentParser(
        description="Align and combine FITS images using robust multi-star matching.",
        epilog="Example: python fits-image-combiner.py NGC7331_r/ "
               "-dark master_dark.fits -flat master_flat.fits -c avsigclip "
               "--diagnostics alignment.csv -o NGC7331_combined.fits")
    parser.add_argument("directory", help="Directory containing FITS images")
    parser.add_argument("-bias", help="Master bias FITS file", default=None)
    parser.add_argument("-dark", help="Master dark FITS file", default=None)
    parser.add_argument("-flat", help="Master flat FITS file", default=None)
    parser.add_argument("-N", type=float, default=3.0,
                        help="Sigma value for avsigclip (default: 3.0)")
    parser.add_argument("-c", "--combine",
                        choices=["average", "median", "avsigclip", "nomax"],
                        default="average",
                        help="Combination method (default: average)")
    parser.add_argument("--noalign", action="store_true",
                        help="Skip star alignment and stack images as-is")
    parser.add_argument("--normalize", action="store_true",
                        help="Normalize final image (mean for average/avsigclip, "
                             "median for median)")
    parser.add_argument("--max-stars", type=int, default=40,
                        help="Maximum alignment stars per frame (default: 40)")
    parser.add_argument("--fwhm", type=float, default=None,
                        help="FWHM in pixels for star detection "
                             "(default: auto-estimated from the reference frame)")
    parser.add_argument("--saturation", type=float, default=65000.0,
                        help="Saturation level in ADU; saturated stars are "
                             "excluded from alignment (default: 65000)")
    parser.add_argument("--no-rotation", action="store_true",
                        help="Fit translation only; by default a small field "
                             "rotation is also fit and corrected when present")
    parser.add_argument("--register-dir", default=None, metavar="DIR",
                        help="Instead of combining, write each ALIGNED frame "
                             "as its own FITS file into DIR, with the "
                             "reference frame's WCS stamped into every "
                             "header (frames that fail alignment are not "
                             "written). Useful for pre-aligning a time "
                             "series before differential photometry.")
    parser.add_argument("--keep-unaligned", action="store_true",
                        help="Stack frames that could not be aligned instead "
                             "of excluding them (the default exclusion "
                             "protects the stack from smearing)")
    parser.add_argument("--no-exptime-scale", action="store_true",
                        help="Do not scale frames with differing exposure "
                             "times to the reference exposure before "
                             "combining")
    parser.add_argument("--min-matches", type=int, default=3,
                        help="Minimum matched stars for reliable alignment (default: 3)")
    parser.add_argument("--diagnostics", nargs='?', const='auto',
                        default=None, metavar="FILE",
                        help="Write per-frame alignment diagnostics to a CSV "
                             "file. With no FILE (or FILE 'auto'), the name "
                             "is derived from the output stack: "
                             "<stack>_alignment_diagnostics.csv")
    parser.add_argument("--filter", default=None, metavar="NAME",
                        help="Only combine images whose FITS header FILTER "
                             "matches (case-insensitive). Strongly "
                             "recommended when building master flats from a "
                             "directory that mixes filters. The special "
                             "value 'autoselect' discovers every filter "
                             "present in the directory and produces one "
                             "stack per filter.")
    parser.add_argument("--object", default=None, metavar="NAME",
                        help="Only combine images whose FITS header OBJECT "
                             "matches (case/spacing-insensitive, so "
                             "'NGC 7331' matches 'ngc7331'). Also used as "
                             "the output filename prefix.")
    parser.add_argument("--object-name", default=None, metavar="NAME",
                        help="Object name used only as the output filename "
                             "prefix (does NOT filter frames). Ignored when "
                             "--object is given. Without either, the prefix "
                             "comes from the first frame's OBJECT/TARGET "
                             "header.")
    parser.add_argument("-o", "--output", default=None,
                        help="Output filename for the combined image "
                             "(default: <first input>_stack_<N>_<filter>_"
                             "b<binning>_<method>.fits, e.g. "
                             "g_00001_stack_7_gp_b2_avsigclip.fits)")

    args = parser.parse_args()
    def run_one(filter_name, output_path, diagnostics_path):
        process_images(args.directory,
                       bias_path=args.bias,
                       dark_path=args.dark,
                       flat_path=args.flat,
                       sigma=args.N,
                       combine_method=args.combine,
                       noalign=args.noalign,
                       normalize=args.normalize,
                       max_stars=args.max_stars,
                       fwhm=args.fwhm,
                       saturation=args.saturation,
                       min_matches=args.min_matches,
                       allow_rotation=not args.no_rotation,
                       keep_unaligned=args.keep_unaligned,
                       scale_exptime=not args.no_exptime_scale,
                       diagnostics_path=diagnostics_path,
                       filter_name=filter_name,
                       object_name=args.object,
                       name_only=args.object_name,
                       output_path=output_path,
                       register_dir=args.register_dir)

    autoselect = (args.filter is not None
                  and args.filter.strip().lower().replace('-', '')
                  in ('autoselect', 'auto select'))

    if not autoselect:
        try:
            run_one(args.filter, args.output, args.diagnostics)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
        return

    # ------------------------------------------------------------------
    # Autoselect: discover every filter present in the directory (after
    # any object-name selection) and produce one stack per filter. New
    # or unanticipated filter names (U, narrowband, anything the camera
    # reports) are handled automatically, since the groups come from the
    # headers themselves.
    # ------------------------------------------------------------------
    try:
        files = [os.path.join(args.directory, f)
                 for f in sorted(os.listdir(args.directory))
                 if f.lower().endswith(('.fits', '.fit', '.fts'))]
        groups = {}  # normalized filter -> (representative name, count)
        for f in files:
            try:
                hdr = fits.getheader(f)
            except Exception:
                continue
            if args.object:
                obj = hdr.get('OBJECT', hdr.get('OBJNAME'))
                if not object_matches(obj, args.object):
                    continue
            v = hdr.get('FILTER', hdr.get('FILTNAM'))
            v = None if v is None else str(v).strip()
            if not v:
                continue
            key = _normalize_filter(v)
            if key not in groups:
                groups[key] = [v, 0]
            groups[key][1] += 1
        if not groups:
            print("Error: no FITS files with FILTER keywords found.")
            sys.exit(1)

        print(f"Autoselect: found {len(groups)} filter(s) in "
              f"{args.directory}:")
        for key, (name, n) in sorted(groups.items()):
            print(f"  {name!r}: {n} frame(s)")

        def per_filter_path(base, tag):
            if base in (None, 'auto'):
                return base
            stem, ext = os.path.splitext(base)
            return f"{stem}_{tag}{ext}"

        outputs, failures = [], []
        for key, (name, n) in sorted(groups.items()):
            tag = name.replace("'", "p").replace(" ", "")
            print("\n" + "=" * 60)
            print(f"Stacking filter {name!r} ({n} frame(s))")
            print("=" * 60)
            try:
                run_one(name,
                        per_filter_path(args.output, tag),
                        per_filter_path(args.diagnostics, tag))
                outputs.append(name)
            except Exception as e:
                print(f"Error stacking filter {name!r}: {e}")
                failures.append(name)

        print("\n" + "=" * 60)
        print(f"Autoselect complete: {len(outputs)} of {len(groups)} "
              f"filter stacks produced"
              + (f"; failed: {', '.join(repr(f) for f in failures)}"
                 if failures else "."))
        if failures:
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
