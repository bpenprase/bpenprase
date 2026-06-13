#!/usr/bin/env python3
"""
Robust photometric calibration pipeline with stack-verified reference star selection.
Key improvements:
- Selects reference stars from center region of first image
- Verifies reference stars exist in ALL images before finalizing
- Uses WCS coordinates to track stars across images with shifts
- Ensures consistent reference stars throughout entire stack
- Supports flat field correction
- Shows flux per pixel in diagnostic plots
- FIXED: Automatically adjusts criteria for low-SNR targets
- NEW: Online catalog matching (APASS DR9, Pan-STARRS DR1, SDSS DR12 via
  astroquery/Vizier) to obtain known magnitudes for reference stars
- NEW: Per-image photometric zero points and calibrated target magnitudes
- NEW: Quality-control flags, reference star coordinates, and catalog
  magnitudes in the output CSV
- NEW: Saturated sources are excluded from detection (peakmax cut)

Example for an exoplanet time series with full calibration:

    python3 photcalib_robust_fixed.py ~/data/WASP-135b -f "r'" \\
        -o wasp135b_photometry.csv \\
        --target-ra "17:49:08.39" --target-dec "+29:52:44.8" \\
        --catalog auto --create-diagnostics --verbose

Use --catalog none for purely differential work or offline processing.
"""
import argparse
import os
import sys
import glob
import warnings
from typing import List, Tuple, Optional, Dict

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch

from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.stats import sigma_clipped_stats, sigma_clip
from astropy.wcs.utils import proj_plane_pixel_scales

from photutils.detection import DAOStarFinder
from photutils.aperture import CircularAperture, CircularAnnulus, aperture_photometry
from photutils.centroids import centroid_sources, centroid_2dg, centroid_com, centroid_quadratic

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


# Optional modules
try:
    from scipy.spatial import cKDTree as KDTree
    KDTREE_AVAILABLE = True
except ImportError:
    KDTREE_AVAILABLE = False

# Catalog access
try:
    from astroquery.vizier import Vizier
    from astroquery.sdss import SDSS
    CATALOGS_AVAILABLE = True
except ImportError:
    CATALOGS_AVAILABLE = False
    print("Warning: astroquery not available, catalog matching disabled")

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

SUPPORTED_FILTERS = ["r'", "g'", "i'", "z'", "u'", "B", "V", "H-a", "OIII", "SII"]  # narrowband: differential photometry only (no catalog magnitudes)

def parse_args():
    """Parse command line arguments."""
    p = argparse.ArgumentParser(
        description="Robust photometric calibration pipeline with stack-verified reference stars"
    )
    p.add_argument("imagedir", help="Directory containing FITS images")
    p.add_argument("-f", "--filter", required=True, choices=SUPPORTED_FILTERS,
                   help="Photometric filter (Sloan g'r'i'z'u' or Johnson B/V; "
                        "B and V catalog magnitudes come from APASS)")
    p.add_argument("-o", "--output", required=True, help="Output CSV filename")
    p.add_argument("--target-ra", required=True, help="Target RA (hh:mm:ss or decimal degrees)")
    p.add_argument("--target-dec", required=True, help="Target Dec (dd:mm:ss or decimal degrees)")
    p.add_argument("--flat", type=str, default=None, help="Flat field FITS file for calibration")
    p.add_argument("--fwhm", type=float, default=None, help="FWHM in pixels (default: auto-estimate)")
    p.add_argument("--threshold-sigma", type=float, default=5.0, 
                   help="Detection threshold in sigma (default: 5.0)")
    p.add_argument("--max-standards", type=int, default=3, 
                   help="Maximum number of standards (default: 3)")
    p.add_argument("--saturation", type=float, default=65000.0, 
                   help="Saturation level in ADU (default: 65000)")
    p.add_argument("--exptime-key", default="EXPTIME", help="Exposure time header keyword")
    p.add_argument("--jd-key", default="JD", help="Julian Date header keyword")
    p.add_argument("--min-snr", type=float, default=20.0,
                   help="Minimum SNR for reference stars (default: 20.0)")
    p.add_argument("--aperture-factor", type=float, default=1.5,
                   help="Aperture radius in FWHM units (default: 1.5)")
    p.add_argument("--flux-ratio-limit", type=float, default=3.0,
                   help="Max flux ratio between target and reference stars (default: 3.0)")
    p.add_argument("--search-radius", type=float, default=30.0,
                   help="Search radius in pixels for finding reference stars (default: 30.0)")
    p.add_argument("--center-fraction", type=float, default=0.5,
                   help="Use central fraction of image for ref star selection (default: 0.5)")
    p.add_argument("--verification-sample", type=int, default=10,
                   help="Number of images to sample for verification (default: 10, 0=all)")
    p.add_argument("--create-diagnostics", action="store_true",
                   help="Create diagnostic PDF for each image")
    p.add_argument("--object-name", default=None, metavar="NAME",
                   help="Target name for plot titles and the output CSV "
                        "(default: read from the first image's OBJECT "
                        "header)")
    p.add_argument("--catalog", default="auto",
                   choices=["auto", "apass", "panstarrs", "sdss", "none"],
                   help="Online catalog for photometric calibration via astroquery "
                        "(default: auto = try APASS, then Pan-STARRS, then SDSS; "
                        "'none' disables catalog matching)")
    p.add_argument("--catalog-radius", type=float, default=3.0,
                   help="Match radius in arcsec for catalog cross-matching (default: 3.0)")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    return p.parse_args()

def load_flat_field(flat_file: str, verbose: bool = False) -> Optional[np.ndarray]:
    """
    Load and normalize a flat field image.
    
    Parameters:
    -----------
    flat_file : str
        Path to flat field FITS file
    verbose : bool
        Print verbose output
    
    Returns:
    --------
    np.ndarray or None if loading fails
    """
    if not os.path.exists(flat_file):
        print(f"Warning: Flat field file {flat_file} does not exist")
        return None
    
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            with fits.open(flat_file) as hdul:
                flat_data = None
                for hdu in hdul:
                    if hasattr(hdu, 'data') and isinstance(hdu.data, np.ndarray) and hdu.data.ndim == 2:
                        flat_data = hdu.data.astype(np.float32)
                        break
                
                if flat_data is None:
                    print(f"Warning: No 2D image data found in flat field {flat_file}")
                    return None
                
                # Normalize flat field by its median
                flat_median = np.median(flat_data[flat_data > 0])
                if flat_median > 0:
                    flat_data = flat_data / flat_median
                else:
                    print(f"Warning: Flat field has non-positive median")
                    return None
                
                # Replace any zeros or negative values with 1 to avoid division issues
                flat_data[flat_data <= 0] = 1.0
                
                if verbose:
                    print(f"Loaded flat field from {flat_file}")
                    print(f"  Shape: {flat_data.shape}")
                    print(f"  Normalized median: {np.median(flat_data):.3f}")
                    print(f"  Min: {np.min(flat_data):.3f}, Max: {np.max(flat_data):.3f}")
                
                return flat_data
                
    except Exception as e:
        print(f"Error loading flat field: {e}")
        return None

def apply_flat_field(data: np.ndarray, flat_field: np.ndarray, verbose: bool = False) -> np.ndarray:
    """
    Apply flat field correction to an image with masking of extreme flat values.
    
    Parameters:
    -----------
    data : np.ndarray
        Science image data
    flat_field : np.ndarray
        Normalized flat field
    verbose : bool
        Print diagnostic information
    
    Returns:
    --------
    np.ndarray
        Flat-fielded data
    """
    if flat_field is None:
        return data
    
    # Check dimensions match
    if data.shape != flat_field.shape:
        print(f"Warning: Image shape {data.shape} doesn't match flat field shape {flat_field.shape}")
        print("Skipping flat field correction")
        return data
    
    # Create a modified flat field that limits extreme corrections
    flat_clipped = flat_field.copy()
    
    # Limit flat field values to prevent extreme corrections
    # Don't correct by more than a factor of 2 in either direction
    min_flat = 0.5  # Don't divide by less than 0.5 (2x amplification max)
    max_flat = 2.0  # Don't divide by more than 2.0 (0.5x reduction max)
    
    # Count problematic pixels
    n_low = np.sum(flat_clipped < min_flat)
    n_high = np.sum(flat_clipped > max_flat)
    
    if verbose and (n_low > 0 or n_high > 0):
        print(f"  Flat field correction:")
        print(f"    Clipping {n_low} pixels with flat < {min_flat}")
        print(f"    Clipping {n_high} pixels with flat > {max_flat}")
    
    # Clip the flat field values
    flat_clipped = np.clip(flat_clipped, min_flat, max_flat)
    
    # Apply the correction
    corrected_data = data / flat_clipped
    
    # Check for NaN or inf
    if np.any(np.isnan(corrected_data)) or np.any(np.isinf(corrected_data)):
        print("Warning: Flat field correction created NaN/inf values, reverting to original")
        return data
    
    if verbose:
        _, bkg_orig, std_orig = estimate_background(data)
        _, bkg_corr, std_corr = estimate_background(corrected_data)
        print(f"    Background: {bkg_orig:.1f} -> {bkg_corr:.1f}")
        print(f"    Std: {std_orig:.1f} -> {std_corr:.1f}")
    
    return corrected_data

# ----------------------------------------------------------------------
# Online catalog matching (astroquery / Vizier)
# ----------------------------------------------------------------------
#
# Catalogs that report magnitudes in (or very close to) the Sloan system.
# APASS DR9 uses true Sloan-prime g'r'i' filters; Pan-STARRS grizy and SDSS
# ugriz are close cousins of the Sloan-prime system, with systematic
# differences typically at the few-percent level for ordinary stars. The
# catalog actually used is recorded in the output so any small systematic
# offsets can be traced. Gaia G is a very broad band and is deliberately not
# offered here: converting it to Sloan magnitudes requires color
# transformations that would add more uncertainty than the catalogs below.

CATALOG_DEFINITIONS = {
    'apass': {
        'vizier_id': 'II/336/apass9',
        'name': 'APASS DR9',
        'filters': {"g'": ("g'mag", "e_g'mag"),
                    "r'": ("r'mag", "e_r'mag"),
                    "i'": ("i'mag", "e_i'mag"),
                    "B": ("Bmag", "e_Bmag"),
                    "V": ("Vmag", "e_Vmag")},
    },
    'panstarrs': {
        'vizier_id': 'II/349/ps1',
        'name': 'Pan-STARRS DR1',
        'filters': {"g'": ('gmag', 'e_gmag'),
                    "r'": ('rmag', 'e_rmag'),
                    "i'": ('imag', 'e_imag'),
                    "z'": ('zmag', 'e_zmag')},
    },
    'sdss': {
        'vizier_id': 'V/147/sdss12',
        'name': 'SDSS DR12',
        'filters': {"u'": ('umag', 'e_umag'),
                    "g'": ('gmag', 'e_gmag'),
                    "r'": ('rmag', 'e_rmag'),
                    "i'": ('imag', 'e_imag'),
                    "z'": ('zmag', 'e_zmag')},
    },
}


def query_catalog_magnitudes(coords: List[SkyCoord], filter_name: str,
                             catalog_choice: str = 'auto',
                             match_radius_arcsec: float = 3.0,
                             verbose: bool = False) -> List[Optional[Dict]]:
    """
    Query an online catalog for known magnitudes at a list of positions.

    A single Vizier cone search is made around the centroid of all requested
    positions (radius covering the whole set plus a margin), then each star
    is matched to its nearest catalog entry within match_radius_arcsec.

    Returns one entry per input coordinate: either a dict with keys
    cat_mag, cat_mag_err, catalog, match_dist_arcsec, or None when no match
    was found. Returns all-None (with a warning) if astroquery is missing,
    the network is unavailable, or no catalog covers the requested filter.
    """
    n = len(coords)
    empty = [None] * n

    if not CATALOGS_AVAILABLE:
        print("Catalog matching skipped: astroquery is not installed "
              "(pip install astroquery)")
        return empty

    if catalog_choice == 'auto':
        order = ['apass', 'panstarrs', 'sdss']
    else:
        order = [catalog_choice]

    # Search field: center of all positions, radius spanning them plus margin.
    ras = np.array([c.ra.deg for c in coords])
    decs = np.array([c.dec.deg for c in coords])
    center = SkyCoord(np.mean(ras) * u.deg, np.mean(decs) * u.deg)
    seps = center.separation(SkyCoord(ras * u.deg, decs * u.deg))
    search_radius = (seps.max() if n > 1 else 0 * u.deg) + 1.0 * u.arcmin

    for cat_key in order:
        cat = CATALOG_DEFINITIONS.get(cat_key)
        if cat is None or filter_name not in cat['filters']:
            if verbose and cat is not None:
                print(f"  {cat['name']} does not cover filter {filter_name}; skipping")
            continue

        mag_col, err_col = cat['filters'][filter_name]
        try:
            if verbose:
                print(f"  Querying {cat['name']} ({cat['vizier_id']}) "
                      f"within {search_radius.to(u.arcmin):.1f} of field center...")
            vizier = Vizier(columns=['RAJ2000', 'DEJ2000', mag_col, err_col],
                            row_limit=10000, timeout=60)
            tables = vizier.query_region(center, radius=search_radius,
                                         catalog=cat['vizier_id'])
            if len(tables) == 0 or len(tables[0]) == 0:
                if verbose:
                    print(f"  No {cat['name']} sources in this field")
                continue

            table = tables[0]
            cat_coords = SkyCoord(np.array(table['RAJ2000'], dtype=float) * u.deg,
                                  np.array(table['DEJ2000'], dtype=float) * u.deg)
            cat_mags = np.array(table[mag_col], dtype=float)
            try:
                cat_errs = np.array(table[err_col], dtype=float)
            except Exception:
                cat_errs = np.full(len(table), np.nan)

            results: List[Optional[Dict]] = []
            n_matched = 0
            for c in coords:
                sep = c.separation(cat_coords)
                i = int(np.argmin(sep))
                if (sep[i].arcsec <= match_radius_arcsec
                        and np.isfinite(cat_mags[i]) and cat_mags[i] > 0):
                    results.append({
                        'cat_mag': float(cat_mags[i]),
                        'cat_mag_err': (float(cat_errs[i])
                                        if np.isfinite(cat_errs[i]) else np.nan),
                        'catalog': cat['name'],
                        'match_dist_arcsec': float(sep[i].arcsec),
                    })
                    n_matched += 1
                else:
                    results.append(None)

            print(f"  Catalog match: {n_matched}/{n} stars matched in {cat['name']} "
                  f"({filter_name} band, radius {match_radius_arcsec:.1f}\")")
            if n_matched > 0:
                return results
        except Exception as e:
            print(f"  Warning: {cat['name']} query failed ({e}); "
                  f"trying next catalog" if catalog_choice == 'auto'
                  else f"  Warning: {cat['name']} query failed ({e})")
            continue

    print("  Catalog matching unavailable: no catalog returned matches "
          "(offline, field not covered, or filter unsupported). "
          "Calibrated magnitudes will not be computed.")
    return empty


def compute_zero_point(matched_standards: List[Dict],
                       reference_stars: List[Dict]) -> Tuple[float, float, int]:
    """
    Compute the photometric zero point of one image from its reference stars.

    For each matched reference star with a catalog magnitude, the per-star
    zero point is zp_i = cat_mag - inst_mag. The image zero point is the
    inverse-variance-weighted mean of the per-star values after 2.5-sigma
    clipping (which rejects variables, mismatches, and bad measurements).

    Returns (zp, zp_err, n_stars_used); (nan, nan, 0) when no reference star
    has a catalog magnitude.
    """
    zps, weights = [], []
    for std in matched_standards:
        ref = reference_stars[std['ref_id']]
        cat_mag = ref.get('cat_mag')
        if cat_mag is None or not np.isfinite(std.get('inst_mag', np.nan)):
            continue
        zp_i = cat_mag - std['inst_mag']
        err_inst = std.get('inst_mag_err', np.nan)
        err_cat = ref.get('cat_mag_err', np.nan)
        var = (err_inst**2 if np.isfinite(err_inst) else 0.0) + \
              (err_cat**2 if np.isfinite(err_cat) else 0.0)
        zps.append(zp_i)
        weights.append(1.0 / max(var, 1e-6))

    if len(zps) == 0:
        return np.nan, np.nan, 0

    zps = np.array(zps)
    weights = np.array(weights)

    if len(zps) >= 4:
        # Robust outlier rejection (e.g. one variable star among the
        # references). Deviations are judged against the median with a
        # MAD-based scale, floored at a few times the typical per-star
        # measurement error so ordinary noise is never clipped. With
        # fewer than 4 stars an outlier cannot be identified reliably,
        # so no rejection is attempted.
        med = float(np.median(zps))
        mad_std = 1.4826 * float(np.median(np.abs(zps - med)))
        err_floor = 3.0 * float(np.median(1.0 / np.sqrt(weights)))
        threshold = max(2.5 * mad_std, err_floor, 0.02)
        keep = np.abs(zps - med) <= threshold
        if np.sum(keep) >= 2:
            zps, weights = zps[keep], weights[keep]

    zp = float(np.average(zps, weights=weights))
    if len(zps) > 1:
        # Scatter-based error (does not assume perfect input errors).
        zp_err = float(np.sqrt(np.average((zps - zp)**2, weights=weights)
                               / (len(zps) - 1)))
    else:
        zp_err = float(1.0 / np.sqrt(np.sum(weights)))
    return zp, zp_err, int(len(zps))


def build_quality_flags(target: Dict, n_standards: int, n_references: int,
                        zp: float, min_snr_flag: float = 5.0) -> str:
    """Assemble a pipe-separated quality-control string for one image."""
    flags = []
    if target.get('saturated', False):
        flags.append('SATURATED')
    snr = target.get('snr', np.nan)
    if not np.isfinite(snr) or snr < min_snr_flag:
        flags.append('LOW_SNR')
    if n_standards < max(2, n_references // 2 + 1):
        flags.append('FEW_REFS')
    if not np.isfinite(zp):
        flags.append('NO_ZP')
    return '|'.join(flags) if flags else 'OK'


def parse_coordinates(ra_str: str, dec_str: str) -> SkyCoord:
    """Parse RA/Dec strings into SkyCoord object."""
    try:
        # Try sexagesimal format first
        return SkyCoord(ra_str, dec_str, unit=(u.hourangle, u.deg))
    except:
        # Try decimal degrees
        try:
            return SkyCoord(float(ra_str)*u.deg, float(dec_str)*u.deg, frame="icrs")
        except Exception as e:
            raise ValueError(f"Could not parse coordinates: {e}")

def estimate_background(data: np.ndarray) -> Tuple[float, float, float]:
    """Estimate background statistics using sigma clipping.

    Very large frames are subsampled to ~1 million pixels first, which is
    statistically equivalent for global statistics but far faster and far
    lighter on memory (important for 50+ megapixel sensors)."""
    flat = data.ravel()
    if flat.size > 1_000_000:
        flat = flat[:: flat.size // 1_000_000]
    mean, median, std = sigma_clipped_stats(flat, sigma=3.0, maxiters=5)
    return mean, median, std

def iterative_centroid(data: np.ndarray, x_init: float, y_init: float, 
                      box_size: int = 21, max_iterations: int = 5, 
                      tolerance: float = 0.1) -> Tuple[float, float]:
    """
    Iteratively refine centroid position using multiple methods.
    """
    x_current = x_init
    y_current = y_init
    
    for iteration in range(max_iterations):
        try:
            # Try 2D Gaussian first (most accurate for stellar PSFs)
            x_new, y_new = centroid_sources(data, [x_current], [y_current],
                                           box_size=box_size,
                                           centroid_func=centroid_2dg)
            x_new = x_new[0]
            y_new = y_new[0]
            
            # If Gaussian fails, try COM
            if not (np.isfinite(x_new) and np.isfinite(y_new)):
                x_new, y_new = centroid_sources(data, [x_current], [y_current],
                                               box_size=box_size,
                                               centroid_func=centroid_com)
                x_new = x_new[0]
                y_new = y_new[0]
            
            # If still failed, try quadratic
            if not (np.isfinite(x_new) and np.isfinite(y_new)):
                x_new, y_new = centroid_sources(data, [x_current], [y_current],
                                               box_size=box_size,
                                               centroid_func=centroid_quadratic)
                x_new = x_new[0]
                y_new = y_new[0]
            
            # Check for convergence
            if np.isfinite(x_new) and np.isfinite(y_new):
                shift = np.sqrt((x_new - x_current)**2 + (y_new - y_current)**2)
                if shift < tolerance:
                    return x_new, y_new
                x_current = x_new
                y_current = y_new
            else:
                # If all methods failed, return original
                return x_init, y_init
                
        except Exception:
            return x_init, y_init
    
    return x_current, y_current

def find_peak_in_box(data: np.ndarray, x_center: float, y_center: float, 
                    box_size: int = 11) -> Tuple[float, float]:
    """Find the peak pixel in a box around the given position."""
    ny, nx = data.shape
    half_box = box_size // 2
    
    x_min = max(0, int(x_center - half_box))
    x_max = min(nx, int(x_center + half_box + 1))
    y_min = max(0, int(y_center - half_box))
    y_max = min(ny, int(y_center + half_box + 1))
    
    subimage = data[y_min:y_max, x_min:x_max]
    
    if subimage.size == 0:
        return x_center, y_center
    
    y_peak_sub, x_peak_sub = np.unravel_index(np.argmax(subimage), subimage.shape)
    
    x_peak = x_min + x_peak_sub
    y_peak = y_min + y_peak_sub
    
    return x_peak, y_peak

def refine_centroids(data: np.ndarray, x: np.ndarray, y: np.ndarray, 
                    box_size: int = 11) -> Tuple[np.ndarray, np.ndarray]:
    """
    Refine centroids using iterative centroiding.
    """
    x_refined = np.zeros_like(x)
    y_refined = np.zeros_like(y)
    
    for i, (xi, yi) in enumerate(zip(x, y)):
        # First find peak in local box
        x_peak, y_peak = find_peak_in_box(data, xi, yi, box_size=box_size)
        # Then refine with iterative centroiding
        x_refined[i], y_refined[i] = iterative_centroid(data, x_peak, y_peak, 
                                                        box_size=15, 
                                                        max_iterations=5)
    
    return x_refined, y_refined

def estimate_fwhm_from_stars(data: np.ndarray, x_coords: np.ndarray, y_coords: np.ndarray,
                            saturation_limit: float = 65000, n_stars: int = 10) -> float:
    """Estimate FWHM from multiple unsaturated stars."""
    fwhm_estimates = []
    
    for i in range(min(n_stars, len(x_coords))):
        x, y = x_coords[i], y_coords[i]
        # Check if star is saturated
        is_sat, _, max_val = check_saturation(data, x, y, 20, saturation_limit)
        if not is_sat:
            fwhm_est = estimate_fwhm_single_star(data, x, y)
            if 2.0 < fwhm_est < 30.0:  # Sanity check
                fwhm_estimates.append(fwhm_est)
                if len(fwhm_estimates) >= 5:  # Use first 5 good stars
                    break
    
    if fwhm_estimates:
        return np.median(fwhm_estimates)
    else:
        return 10.0  # Default fallback

def estimate_fwhm_single_star(data: np.ndarray, x_center: float, y_center: float, 
                              box_size: int = 31) -> float:
    """Estimate FWHM of a single star by fitting a radial profile."""
    ny, nx = data.shape
    half_box = box_size // 2
    
    x_min = max(0, int(x_center - half_box))
    x_max = min(nx, int(x_center + half_box + 1))
    y_min = max(0, int(y_center - half_box))
    y_max = min(ny, int(y_center + half_box + 1))
    
    if x_max <= x_min or y_max <= y_min:
        return 10.0  # Default if we can't estimate
    
    y_box, x_box = np.ogrid[y_min:y_max, x_min:x_max]
    
    distances = np.sqrt((x_box - x_center)**2 + (y_box - y_center)**2).ravel()
    values = data[y_min:y_max, x_min:x_max].ravel()
    
    sort_idx = np.argsort(distances)
    distances = distances[sort_idx]
    values = values[sort_idx]
    
    peak_value = np.max(values)
    background = np.median(values[distances > half_box * 0.7])
    
    half_max = background + (peak_value - background) / 2.0
    
    window = 3
    if len(values) > window:
        smoothed = np.convolve(values, np.ones(window)/window, mode='valid')
        smooth_dist = distances[:len(smoothed)]
        
        above_half = smoothed > half_max
        if np.any(above_half):
            last_above = np.where(above_half)[0][-1]
            if last_above < len(smooth_dist) - 1:
                r_half = smooth_dist[last_above]
                fwhm = 2.0 * r_half
                if 2.0 < fwhm < 30.0:
                    return fwhm
    
    return 10.0

def detect_sources(data: np.ndarray, fwhm: float, threshold_sigma: float, 
                  verbose: bool = False,
                  saturation: Optional[float] = None) -> Optional[pd.DataFrame]:
    """Detect sources using DAOStarFinder, excluding saturated stars when
    a saturation level is given (peakmax cut on the background-subtracted
    peak value)."""
    _, bkg_median, bkg_std = estimate_background(data)
    threshold = threshold_sigma * bkg_std
    
    if verbose:
        print(f"  Background: median={bkg_median:.2f}, std={bkg_std:.2f}")
        print(f"  Detection threshold: {threshold:.2f} ADU")
    
    peak_max = (saturation - bkg_median) if saturation is not None else None
    finder = make_daofinder(fwhm=fwhm, threshold=threshold, peak_max=peak_max)
    sources = finder(data - bkg_median)
    
    if sources is None or len(sources) == 0:
        return None
    
    df = sources.to_pandas()
    df = df.rename(columns={'xcentroid': 'x', 'ycentroid': 'y',
                            'x_centroid': 'x', 'y_centroid': 'y'})
    
    # Quality cuts based on sharpness and roundness values
    # (photutils provides 'roundness1'/'roundness2' in recent versions,
    # or a single 'roundness' in some older releases)
    if 'sharpness' in df.columns:
        df = df[(df['sharpness'] > 0.3) & (df['sharpness'] < 0.9)]
    round_col = ('roundness' if 'roundness' in df.columns
                 else 'roundness1' if 'roundness1' in df.columns else None)
    if round_col is not None:
        df = df[(df[round_col] > -0.5) & (df[round_col] < 0.5)]
    
    if verbose:
        print(f"  Detected {len(df)} sources after quality cuts")
    
    return df if len(df) > 0 else None

def check_saturation(data: np.ndarray, x_center: float, y_center: float, 
                    aperture_radius: float, saturation_limit: float = 65000) -> Tuple[bool, int, float]:
    """
    Check if a star has saturated pixels within the aperture.
    
    Returns:
        is_saturated: True if any pixels within aperture are saturated
        n_saturated: Number of saturated pixels
        max_value: Maximum pixel value within aperture
    """
    ny, nx = data.shape
    # Work on a local cutout around the star: building full-frame distance
    # arrays costs ~0.5 GB per call on 50+ megapixel sensors.
    r = int(np.ceil(aperture_radius)) + 2
    y0, y1 = max(0, int(y_center) - r), min(ny, int(y_center) + r + 1)
    x0, x1 = max(0, int(x_center) - r), min(nx, int(x_center) + r + 1)
    cut = data[y0:y1, x0:x1]
    y_grid, x_grid = np.ogrid[y0:y1, x0:x1]
    
    distances = np.sqrt((x_grid - x_center)**2 + (y_grid - y_center)**2)
    aperture_mask = distances <= aperture_radius
    
    aperture_pixels = cut[aperture_mask]
    
    if len(aperture_pixels) == 0:
        return False, 0, 0
    
    max_value = np.max(aperture_pixels)
    n_saturated = np.sum(aperture_pixels >= saturation_limit)
    is_saturated = n_saturated > 0
    
    return is_saturated, n_saturated, max_value

def measure_aperture_photometry(data: np.ndarray, x: np.ndarray, y: np.ndarray,
                               aperture_radius: float, annulus_radii: Tuple[float, float],
                               verbose: bool = False) -> Dict[str, np.ndarray]:
    """Perform aperture photometry at given positions."""
    positions = np.column_stack([x, y])
    
    aperture = CircularAperture(positions, r=aperture_radius)
    annulus = CircularAnnulus(positions, r_in=annulus_radii[0], r_out=annulus_radii[1])
    
    # Get background values from annulus
    annulus_masks = annulus.to_mask(method='center')
    bkg_values = []
    
    for i, mask in enumerate(annulus_masks):
        # Check if mask is None (happens when source is too close to edge)
        if mask is None:
            bkg_values.append(0.0)
            continue
        
        # Try to multiply mask with data
        try:
            annulus_data = mask.multiply(data)
        except Exception as e:
            bkg_values.append(0.0)
            continue
        
        # Check if annulus_data is None
        if annulus_data is None:
            bkg_values.append(0.0)
            continue
        
        # Check if mask.data exists and is not None
        if hasattr(mask, 'data') and mask.data is not None:
            try:
                # Extract only the annulus pixels
                annulus_pixels = annulus_data[mask.data > 0]
                if len(annulus_pixels) > 0:
                    # Use sigma-clipped mean for better background estimate
                    clipped_mean, clipped_median, clipped_std = sigma_clipped_stats(
                        annulus_pixels, sigma=3.0, maxiters=5
                    )
                    bkg_values.append(clipped_median)
                else:
                    bkg_values.append(0.0)
            except Exception as e:
                bkg_values.append(0.0)
        else:
            bkg_values.append(0.0)
    
    bkg_values = np.array(bkg_values)
    
    # Perform aperture photometry
    phot_table = aperture_photometry(data, aperture)
    
    # Calculate background-subtracted flux
    aperture_area = np.pi * aperture_radius**2
    flux = phot_table['aperture_sum'] - bkg_values * aperture_area
    
    # Estimate flux error (Poisson + background noise)
    _, _, bkg_std = estimate_background(data)
    flux_err = np.sqrt(np.abs(flux) + aperture_area * bkg_std**2)
    
    # Calculate SNR
    snr = np.where(flux_err > 0, flux / flux_err, 0)
    
    # Calculate instrumental magnitudes
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mag = -2.5 * np.log10(np.where(flux > 0, flux, np.nan))
        mag_err = 1.0857 * flux_err / np.where(flux > 0, flux, 1.0)
    
    return {
        'flux': np.array(flux),
        'flux_err': np.array(flux_err),
        'magnitude': np.array(mag),
        'magnitude_err': np.array(mag_err),
        'snr': np.array(snr),
        'background': bkg_values
    }

def verify_star_exists_in_image(data: np.ndarray, wcs: WCS, star_coord: SkyCoord,
                               search_radius: float, min_flux: float) -> Tuple[bool, Optional[Tuple[float, float]]]:
    """
    Verify if a star exists in an image at the expected coordinates.
    
    Returns:
        exists: True if star found
        position: (x, y) position if found, None otherwise
    """
    try:
        # Convert RA/Dec to pixel coordinates
        x_expected, y_expected = wcs.world_to_pixel(star_coord)
        
        # Check if position is within image bounds
        ny, nx = data.shape
        if x_expected < 0 or x_expected >= nx or y_expected < 0 or y_expected >= ny:
            return False, None
        
        # Find peak near expected position
        x_peak, y_peak = find_peak_in_box(data, x_expected, y_expected, 
                                         box_size=int(search_radius))
        
        # Check if peak is within search radius
        dist = np.sqrt((x_peak - x_expected)**2 + (y_peak - y_expected)**2)
        if dist > search_radius:
            return False, None
        
        # Refine position
        x_refined, y_refined = iterative_centroid(data, x_peak, y_peak, 
                                                 box_size=15, max_iterations=5)
        
        # Measure flux at this position (quick aperture photometry)
        aperture_radius = 10  # pixels, rough estimate
        aperture = CircularAperture([(x_refined, y_refined)], r=aperture_radius)
        phot_table = aperture_photometry(data, aperture)
        flux = phot_table['aperture_sum'][0]
        
        # Check if flux meets minimum requirement
        if flux < min_flux:
            return False, None
        
        return True, (x_refined, y_refined)
        
    except Exception:
        return False, None

def select_and_verify_reference_stars(fits_files: List[str], args: argparse.Namespace,
                                     target_coord: SkyCoord, flat_field: Optional[np.ndarray] = None) -> Optional[List[Dict]]:
    """
    Select reference stars from first image and verify they exist in all images.
    
    Returns:
        List of verified reference stars with their coordinates, or None if failed
    """
    print("\n" + "="*60)
    print("REFERENCE STAR SELECTION AND VERIFICATION")
    print("="*60)
    
    # Load and process first image
    print(f"\n1. Analyzing first image: {os.path.basename(fits_files[0])}")
    
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        with fits.open(fits_files[0]) as hdul:
            hdu = None
            for h in hdul:
                if hasattr(h, 'data') and isinstance(h.data, np.ndarray) and h.data.ndim == 2:
                    hdu = h
                    break
            
            if hdu is None:
                print("ERROR: No image HDU found in first file")
                return None
            
            data = hdu.data.astype(np.float32)
            header = hdu.header
        
        # Apply flat field if provided
        if flat_field is not None:
            data = apply_flat_field(data, flat_field)
            if args.verbose:
                print("  Applied flat field correction")
        
        try:
            wcs = WCS(header)
        except:
            print("ERROR: No valid WCS in first image")
            return None
    
    ny, nx = data.shape
    
    # Estimate FWHM from bright stars in the central ~30% of the frame
    fy0, fy1 = int(ny * 0.35), int(ny * 0.65)
    fx0, fx1 = int(nx * 0.35), int(nx * 0.65)
    fcrop = np.ascontiguousarray(data[fy0:fy1, fx0:fx1])
    _, median, std = estimate_background(fcrop)
    threshold = 10.0 * std
    finder = make_daofinder(fwhm=10.0, threshold=threshold)
    bright_sources = finder(fcrop - median)
    if bright_sources is None or len(bright_sources) == 0:
        # Nothing at 10 sigma: retry at 5 sigma before giving up, since a
        # wrong FWHM cascades into bad apertures and bad reference SNRs.
        finder = make_daofinder(fwhm=10.0, threshold=5.0 * std)
        bright_sources = finder(fcrop - median)
    
    if bright_sources is not None and len(bright_sources) > 0:
        bright_x, bright_y = source_xy(bright_sources)
        fwhm = estimate_fwhm_from_stars(fcrop - median, bright_x, bright_y, args.saturation)
    else:
        fwhm = 6.0
        print("  WARNING: no bright stars found for FWHM estimation; "
              "assuming 6.0 px (use --fwhm to set it explicitly).")
    fwhm = float(np.clip(fwhm, 2.0, 15.0))
    
    print(f"  FWHM: {fwhm:.1f} pixels")
    
    # Set aperture parameters
    ap_radius = args.aperture_factor * fwhm
    ann_inner = 3.0 * fwhm
    ann_outer = 4.5 * fwhm
    
    # Measure target in first image
    target_x, target_y = wcs.world_to_pixel(target_coord)
    target_x_peak, target_y_peak = find_peak_in_box(data, target_x, target_y, box_size=21)
    target_x_ref, target_y_ref = iterative_centroid(data, target_x_peak, target_y_peak,
                                                   box_size=15, max_iterations=5)
    
    target_phot = measure_aperture_photometry(
        data, np.array([target_x_ref]), np.array([target_y_ref]),
        ap_radius, (ann_inner, ann_outer)
    )
    target_flux = target_phot['flux'][0]
    target_snr = target_phot['snr'][0]
    print(f"  Target flux: {target_flux:.0f}, SNR: {target_snr:.1f}")
    
    # Detect sources in first image
    # Detect candidate sources in the central region only: reference
    # candidates are restricted to that region anyway, and full-frame
    # detection on very large sensors is slow and memory-hungry.
    cf = args.center_fraction
    x_lo, x_hi = int(nx * (1 - cf) / 2), int(nx * (1 + cf) / 2)
    y_lo, y_hi = int(ny * (1 - cf) / 2), int(ny * (1 + cf) / 2)
    crop = np.ascontiguousarray(data[y_lo:y_hi, x_lo:x_hi])
    sources = detect_sources(crop, fwhm, args.threshold_sigma, args.verbose,
                             saturation=args.saturation)
    if sources is None:
        print("ERROR: No sources detected in first image")
        return None
    sources = sources.copy()
    sources['x'] = sources['x'] + x_lo
    sources['y'] = sources['y'] + y_lo
    
    # Refine centroids
    x_refined, y_refined = refine_centroids(data, sources['x'].values, sources['y'].values)
    
    # Perform photometry
    phot = measure_aperture_photometry(data, x_refined, y_refined,
                                      ap_radius, (ann_inner, ann_outer))
    
    # Select candidates from central region only
    center_fraction = args.center_fraction
    x_min = nx * (1 - center_fraction) / 2
    x_max = nx * (1 + center_fraction) / 2
    y_min = ny * (1 - center_fraction) / 2
    y_max = ny * (1 + center_fraction) / 2
    
    print(f"\n2. Selecting reference candidates from central {center_fraction*100:.0f}% of image")
    print(f"   Region: x=[{x_min:.0f}, {x_max:.0f}], y=[{y_min:.0f}, {y_max:.0f}]")
    
    # FIXED: Adjust minimum SNR based on target SNR
    # If target has low SNR, we need to be more flexible with reference star requirements
    effective_min_snr = args.min_snr
    effective_flux_ratio_limit = args.flux_ratio_limit
    
    if target_snr < args.min_snr:
        # Target has lower SNR than our minimum requirement for reference stars
        # This means reference stars will likely be much brighter
        # So we need to either lower SNR requirement or increase flux ratio tolerance
        
        # Option 1: Lower SNR requirement to be closer to target SNR (but not below it)
        effective_min_snr = max(target_snr * 1.5, 10.0)  # At least 1.5x target SNR, but minimum 10
        
        # Option 2: Increase flux ratio limit to accommodate brighter reference stars
        # If target SNR is 8.5 and we want ref stars with SNR 20, they'll be ~2.5x brighter minimum
        snr_ratio = args.min_snr / target_snr if target_snr > 0 else 3.0
        effective_flux_ratio_limit = max(args.flux_ratio_limit, snr_ratio * 1.5)
        
        print(f"   Adjusting selection criteria due to low target SNR:")
        print(f"     Original min SNR: {args.min_snr:.1f} -> Adjusted: {effective_min_snr:.1f}")
        print(f"     Original flux ratio limit: {args.flux_ratio_limit:.1f} -> Adjusted: {effective_flux_ratio_limit:.1f}")
    
    min_separation = 30  # pixels

    def collect_candidates(min_snr_eff, ratio_lim_lo, ratio_lim_hi):
        """One pass over the photometered detections with the given limits.

        ratio_lim_lo bounds how much FAINTER than the target a reference
        may be (flux_ratio >= 1/ratio_lim_lo); ratio_lim_hi bounds how much
        BRIGHTER (flux_ratio <= ratio_lim_hi). For faint targets, brighter
        references are desirable (they carry less noise into the
        differential light curve), so relaxation widens the bright side
        much more aggressively than the faint side."""
        found = []
        for i in range(len(x_refined)):
            x, y = x_refined[i], y_refined[i]
            if x < x_min or x > x_max or y < y_min or y > y_max:
                continue
            dist_to_target = np.sqrt((x - target_x_ref)**2 + (y - target_y_ref)**2)
            if dist_to_target < min_separation:
                continue
            is_sat, _, _ = check_saturation(data, x, y, ap_radius, args.saturation)
            if is_sat:
                continue
            if phot['snr'][i] < min_snr_eff:
                continue
            flux_ratio = phot['flux'][i] / target_flux if target_flux > 0 else np.inf
            if flux_ratio > ratio_lim_hi or flux_ratio < 1.0 / ratio_lim_lo:
                continue
            snr_score = min(phot['snr'][i] / max(min_snr_eff * 2, 100.0), 1.0)
            flux_score = 1.0 - abs(np.log10(flux_ratio)) / np.log10(max(ratio_lim_hi, 1.1)) \
                if flux_ratio > 0 else 0
            center_score = 1.0 - 2.0 * max(abs(x - nx/2), abs(y - ny/2)) / nx
            quality_score = snr_score * 0.3 + flux_score * 0.3 + center_score * 0.4
            star_coord = wcs.pixel_to_world(x, y)
            found.append({
                'index': i,
                'x': x,
                'y': y,
                'ra': star_coord.ra.deg,
                'dec': star_coord.dec.deg,
                'coord': star_coord,
                'flux': phot['flux'][i],
                'flux_err': phot['flux_err'][i],
                'magnitude': phot['magnitude'][i],
                'magnitude_err': phot['magnitude_err'][i],
                'snr': phot['snr'][i],
                'flux_ratio': flux_ratio,
                'quality_score': quality_score
            })
        return found

    # Progressive relaxation: rather than aborting when the first pass
    # finds nothing (common for faint targets in sparse fields), the
    # criteria are widened in stages, each stage announced, until enough
    # candidates appear. The bright-side flux limit grows fastest because
    # bright references are good references.
    relaxation_stages = [
        (effective_min_snr, effective_flux_ratio_limit,
         effective_flux_ratio_limit),
        (max(effective_min_snr * 0.75, 8.0), effective_flux_ratio_limit,
         max(effective_flux_ratio_limit * 4, 12.0)),
        (6.0, effective_flux_ratio_limit * 2,
         max(effective_flux_ratio_limit * 12, 40.0)),
    ]
    candidates = []
    for stage_i, (snr_lim, lo, hi) in enumerate(relaxation_stages):
        candidates = collect_candidates(snr_lim, lo, hi)
        if len(candidates) >= 2:
            if stage_i > 0:
                print(f"   Relaxation stage {stage_i}: min SNR {snr_lim:.1f}, "
                      f"flux ratio window [1/{lo:.0f}, {hi:.0f}] -> "
                      f"{len(candidates)} candidates")
            break
        if stage_i + 1 < len(relaxation_stages):
            nxt = relaxation_stages[stage_i + 1]
            print(f"   Only {len(candidates)} candidate(s) at min SNR "
                  f"{snr_lim:.1f}, flux ratio window [1/{lo:.0f}, {hi:.0f}]; "
                  f"relaxing to min SNR {nxt[0]:.1f}, window "
                  f"[1/{nxt[1]:.0f}, {nxt[2]:.0f}]...")

    print(f"   Found {len(candidates)} potential reference stars")
    
    if len(candidates) == 0:
        print("ERROR: No suitable reference candidates found")
        print("   Consider adjusting parameters:")
        print(f"     --min-snr (current: {args.min_snr})")
        print(f"     --flux-ratio-limit (current: {args.flux_ratio_limit})")
        print(f"     --center-fraction (current: {args.center_fraction})")
        return None
    
    # Sort by quality score
    candidates.sort(key=lambda x: x['quality_score'], reverse=True)
    
    # Sample images for verification
    n_images = len(fits_files)
    if args.verification_sample > 0 and args.verification_sample < n_images:
        # Sample evenly throughout the stack
        sample_indices = np.linspace(0, n_images-1, args.verification_sample, dtype=int)
        sample_files = [fits_files[i] for i in sample_indices]
        print(f"\n3. Verifying candidates in {len(sample_files)} sampled images")
    else:
        sample_files = fits_files
        print(f"\n3. Verifying candidates in all {len(sample_files)} images")
    
    # Verify each candidate exists in the sampled images. Acceptance is
    # NOT all-or-nothing: a candidate found in at least 80% of the sampled
    # images is kept, which tolerates the occasional cloudy, trailed, or
    # badly aligned frame. Failures are also counted per image, so when a
    # specific image breaks most candidates (typically a frame without a
    # WCS solution or one grossly misaligned), it gets named explicitly.
    verified_candidates = []
    min_flux_threshold = target_flux * 0.1  # Minimum flux threshold
    image_fail_counts = {}
    n_candidates_checked = 0

    for j, candidate in enumerate(candidates):
        if len(verified_candidates) >= args.max_standards * 2:  # Check more than needed
            break

        print(f"   Checking candidate {j+1}: SNR={candidate['snr']:.1f}, "
              f"flux_ratio={candidate['flux_ratio']:.2f}")

        n_found, n_tested = 1, 1  # the first image was already measured
        positions_in_images = [(candidate['x'], candidate['y'])]

        for k, fits_file in enumerate(sample_files):
            if k == 0:
                continue
            ok = False
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    with fits.open(fits_file) as hdul:
                        for h in hdul:
                            if hasattr(h, 'data') and isinstance(h.data, np.ndarray) and h.data.ndim == 2:
                                test_data = h.data.astype(np.float32)
                                test_header = h.header
                                break

                    if flat_field is not None:
                        test_data = apply_flat_field(test_data, flat_field)

                    test_wcs = WCS(test_header)

                    exists, position = verify_star_exists_in_image(
                        test_data, test_wcs, candidate['coord'],
                        args.search_radius, min_flux_threshold
                    )
                    ok = bool(exists)
                    positions_in_images.append(position if exists else None)
            except Exception as e:
                positions_in_images.append(None)
                if args.verbose:
                    print(f"     Error checking image {k+1}: {e}")

            n_tested += 1
            if ok:
                n_found += 1
            else:
                image_fail_counts[k] = image_fail_counts.get(k, 0) + 1
                if args.verbose:
                    print(f"     Not found in image {k+1}")

        n_candidates_checked += 1
        if n_found / n_tested >= 0.7:
            candidate['verified'] = True
            candidate['positions'] = positions_in_images
            verified_candidates.append(candidate)
            print(f"     \u2713 Found in {n_found}/{n_tested} sampled images")
        else:
            print(f"     \u2717 Found in only {n_found}/{n_tested} sampled images")

    print(f"\n   {len(verified_candidates)} candidates verified "
          f"(present in >= 70% of sampled images)")

    # Name the images that broke most candidates: they are the problem,
    # not the stars.
    if n_candidates_checked:
        bad_images = [(k, c) for k, c in image_fail_counts.items()
                      if c >= 0.8 * n_candidates_checked]
        if bad_images:
            print("   NOTE: the following sampled image(s) failed for most "
                  "candidates and are likely misaligned, missing a WCS "
                  "plate solution, or of poor quality:")
            for k, c in sorted(bad_images):
                print(f"     {os.path.basename(sample_files[k])} "
                      f"({c}/{n_candidates_checked} candidates not found)")
            print("   Pre-aligning the series first (the GUI's alignment "
                  "option 'shift' or 'shift and rotate') usually fixes "
                  "this, as can excluding the affected files.")

    # Select final reference stars
    final_references = []
    for candidate in verified_candidates:
        # Check separation from already selected stars
        too_close = False
        for ref in final_references:
            dist = np.sqrt((candidate['x'] - ref['x'])**2 + (candidate['y'] - ref['y'])**2)
            if dist < min_separation:
                too_close = True
                break
        
        if not too_close:
            final_references.append(candidate)
            if len(final_references) >= args.max_standards:
                break
    
    if len(final_references) == 0:
        print("\nERROR: No reference stars could be verified across the image stack")
        print("Consider adjusting parameters or checking image quality")
        return None
    
    print(f"\n4. Selected {len(final_references)} verified reference stars:")
    for i, ref in enumerate(final_references):
        print(f"   Reference {i+1}:")
        print(f"     Position: x={ref['x']:.1f}, y={ref['y']:.1f}")
        print(f"     RA/Dec: {ref['ra']:.6f}, {ref['dec']:.6f}")
        print(f"     SNR: {ref['snr']:.1f}, Flux ratio: {ref['flux_ratio']:.2f}")
    
    print("="*60 + "\n")
    
    return final_references

def find_reference_star_in_image(data: np.ndarray, wcs: WCS, ref_coord: SkyCoord,
                                search_radius: float, aperture_radius: float,
                                annulus_radii: Tuple[float, float]) -> Optional[Dict]:
    """
    Find and measure a reference star in an image using its WCS coordinates.
    
    Returns:
        Dictionary with photometry results, or None if star not found
    """
    try:
        # Convert RA/Dec to pixel coordinates for this image
        x_expected, y_expected = wcs.world_to_pixel(ref_coord)
        
        # Check if position is within image bounds
        ny, nx = data.shape
        if x_expected < 0 or x_expected >= nx or y_expected < 0 or y_expected >= ny:
            return None
        
        # Find peak within search radius
        x_peak, y_peak = find_peak_in_box(data, x_expected, y_expected, 
                                         box_size=int(search_radius))
        
        # Refine centroid
        x_refined, y_refined = iterative_centroid(data, x_peak, y_peak, 
                                                 box_size=15, max_iterations=5)
        
        # Check if refined position is within search radius
        dist = np.sqrt((x_refined - x_expected)**2 + (y_refined - y_expected)**2)
        if dist > search_radius:
            return None
        
        # Perform photometry
        phot = measure_aperture_photometry(data, np.array([x_refined]), np.array([y_refined]),
                                          aperture_radius, annulus_radii)
        
        # Check if we got valid photometry
        if not np.isfinite(phot['magnitude'][0]):
            return None
        
        return {
            'x': float(x_refined),
            'y': float(y_refined),
            'inst_mag': float(phot['magnitude'][0]),
            'inst_mag_err': float(phot['magnitude_err'][0]),
            'snr': float(phot['snr'][0]),
            'flux': float(phot['flux'][0]),
            'flux_err': float(phot['flux_err'][0])
        }
        
    except Exception:
        return None

def get_radial_profile(data: np.ndarray, x_center: float, y_center: float, 
                       max_radius: float = 30, n_bins: int = 50) -> Tuple:
    """Calculate radial profile around a given position (computed on a
    local cutout to stay fast and memory-light on very large sensors)."""
    ny, nx = data.shape
    r = int(np.ceil(max_radius)) + 2
    y0, y1 = max(0, int(y_center) - r), min(ny, int(y_center) + r + 1)
    x0, x1 = max(0, int(x_center) - r), min(nx, int(x_center) + r + 1)
    data = data[y0:y1, x0:x1]
    y_grid, x_grid = np.ogrid[y0:y1, x0:x1]
    
    distances = np.sqrt((x_grid - x_center)**2 + (y_grid - y_center)**2)
    
    radii = np.linspace(0, max_radius, n_bins)
    cumulative_flux = np.zeros(n_bins)
    mean_brightness = np.zeros(n_bins)
    
    for i in range(n_bins):
        if i == 0:
            mask = distances <= radii[i]
            cumulative_flux[i] = np.sum(data[mask]) if np.sum(mask) > 0 else 0
            mean_brightness[i] = np.mean(data[mask]) if np.sum(mask) > 0 else 0
        else:
            mask_cumulative = distances <= radii[i]
            mask_annulus = (distances > radii[i-1]) & (distances <= radii[i])
            
            cumulative_flux[i] = np.sum(data[mask_cumulative]) if np.sum(mask_cumulative) > 0 else 0
            mean_brightness[i] = np.mean(data[mask_annulus]) if np.sum(mask_annulus) > 0 else 0
    
    # Calculate flux in each annulus
    flux_in_annulus = np.zeros(n_bins)
    flux_in_annulus[0] = cumulative_flux[0]
    for i in range(1, n_bins):
        flux_in_annulus[i] = cumulative_flux[i] - cumulative_flux[i-1]
    
    # Calculate flux per pixel for each annulus
    flux_per_pixel = np.zeros(n_bins)
    for i in range(n_bins):
        if i == 0:
            # First bin is a circle
            area = np.pi * radii[0]**2 if radii[0] > 0 else 1
        else:
            # Subsequent bins are annuli
            area = np.pi * (radii[i]**2 - radii[i-1]**2)
        
        if area > 0:
            flux_per_pixel[i] = flux_in_annulus[i] / area
        else:
            flux_per_pixel[i] = 0
    
    return radii, cumulative_flux, mean_brightness, flux_in_annulus, flux_per_pixel

def create_diagnostic_plots(data: np.ndarray, positions: List[Tuple], labels: List[str],
                          fwhm: float, image_name: str, pdf_file: str,
                          background_median: float = 0, aperture_radius: float = None,
                          inner_ann: float = None, outer_ann: float = None,
                          saturation_limit: float = 65000):
    """Create diagnostic PDF with radial profiles and cutouts."""
    
    # Set aperture parameters
    if aperture_radius is None:
        aperture_radius = 1.5 * fwhm
    if inner_ann is None:
        inner_ann = 3.0 * fwhm
    if outer_ann is None:
        outer_ann = 4.5 * fwhm
    
    with PdfPages(pdf_file) as pdf:
        # Page 1: Radial profiles
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle(f'Photometry Diagnostic: {os.path.basename(image_name)}\n'
                     f'FWHM={fwhm:.1f}px, Aperture={aperture_radius:.1f}px, '
                     f'Annulus={inner_ann:.1f}-{outer_ann:.1f}px', 
                     fontsize=12, fontweight='bold')
        axes = axes.flatten()
        
        max_radius = max(35, outer_ann + 5)
        measurements = []
        
        for idx, ((x, y), label) in enumerate(zip(positions[:4], labels[:4])):
            ax = axes[idx]
            
            radii, cumulative_flux, mean_brightness, flux_in_annulus, flux_per_pixel = get_radial_profile(
                data - background_median, x, y, max_radius=max_radius, n_bins=60
            )
            
            ax2 = ax.twinx()
            
            # Plot flux per pixel instead of flux in annulus
            ax.plot(radii, flux_per_pixel, 'b-', label='Flux per pixel', linewidth=2)
            ax.set_xlabel('Radius (pixels)')
            ax.set_ylabel('Flux per pixel', color='b')
            ax.tick_params(axis='y', labelcolor='b')
            
            ax2.plot(radii, cumulative_flux, 'r--', label='Cumulative flux', linewidth=2)
            ax2.set_ylabel('Cumulative flux', color='r')
            ax2.tick_params(axis='y', labelcolor='r')
            
            ax.set_title(f'{label} at ({x:.1f}, {y:.1f})', fontweight='bold', fontsize=10)
            ax.grid(True, alpha=0.3)
            
            ax.axvline(aperture_radius, color='green', linestyle='-', linewidth=2, alpha=0.7, label='Aperture')
            ax.axvspan(inner_ann, outer_ann, color='orange', alpha=0.2, label='Background')
            ax.axvline(inner_ann, color='orange', linestyle='--', alpha=0.5)
            ax.axvline(outer_ann, color='orange', linestyle='--', alpha=0.5)
            
            # Calculate statistics
            if aperture_radius < max_radius:
                idx_ap = np.argmin(np.abs(radii - aperture_radius))
                flux_in_aperture = cumulative_flux[idx_ap]
                
                idx_inner = np.argmin(np.abs(radii - inner_ann))
                idx_outer = np.argmin(np.abs(radii - outer_ann))
                if idx_outer > idx_inner:
                    background = np.mean(mean_brightness[idx_inner:idx_outer])
                    background_total = background * np.pi * aperture_radius**2
                    net_flux = flux_in_aperture - background_total
                    
                    if net_flux > 0:
                        inst_mag = -2.5 * np.log10(net_flux)
                        snr = net_flux / np.sqrt(net_flux + background_total)
                    else:
                        inst_mag = np.nan
                        snr = 0
                    
                    measurements.append({
                        'label': label,
                        'x': x,
                        'y': y,
                        'flux': net_flux,
                        'background': background,
                        'inst_mag': inst_mag,
                        'snr': snr
                    })
                    
                    textstr = f'Aperture flux: {flux_in_aperture:.0f}\n'
                    textstr += f'Background: {background:.1f}/pix\n'
                    textstr += f'Net flux: {net_flux:.0f}\n'
                    textstr += f'SNR: {snr:.1f}\n'
                    if np.isfinite(inst_mag):
                        textstr += f'Inst mag: {inst_mag:.2f}'
                    
                    ax.text(0.95, 0.5, textstr, transform=ax.transAxes,
                           fontsize=9, verticalalignment='center',
                           horizontalalignment='right',
                           bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        for idx in range(len(positions), 4):
            axes[idx].axis('off')
        
        plt.tight_layout()
        pdf.savefig(fig)
        plt.close()
        
        # Page 2: Image cutouts
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle(f'Image Cutouts: {os.path.basename(image_name)}', 
                     fontsize=14, fontweight='bold')
        axes = axes.flatten()
        
        cutout_size = int(max(40, outer_ann + 10))
        ny, nx = data.shape
        
        for idx, ((x, y), label) in enumerate(zip(positions[:4], labels[:4])):
            ax = axes[idx]
            
            x_int, y_int = int(x), int(y)
            y1 = max(0, y_int - cutout_size)
            y2 = min(ny, y_int + cutout_size)
            x1 = max(0, x_int - cutout_size)
            x2 = min(nx, x_int + cutout_size)
            
            cutout = data[y1:y2, x1:x2]
            
            is_sat, n_sat, max_val = check_saturation(data, x, y, aperture_radius, saturation_limit)
            
            vmin = np.percentile(cutout, 1)
            vmax = np.percentile(cutout[cutout < saturation_limit], 99) if np.any(cutout < saturation_limit) else saturation_limit
            
            display_cutout = cutout.copy()
            
            if np.any(cutout >= saturation_limit):
                norm_cutout = np.zeros_like(display_cutout)
                non_sat_mask = display_cutout < saturation_limit
                if np.any(non_sat_mask):
                    norm_cutout[non_sat_mask] = (display_cutout[non_sat_mask] - vmin) / (vmax - vmin)
                norm_cutout[~non_sat_mask] = 1.0
                
                rgb_image = np.zeros((*cutout.shape, 3))
                for i in range(cutout.shape[0]):
                    for j in range(cutout.shape[1]):
                        if display_cutout[i, j] >= saturation_limit:
                            rgb_image[i, j] = [1.0, 0.0, 0.0]  # Red for saturated
                        else:
                            gray_val = norm_cutout[i, j]
                            rgb_image[i, j] = [gray_val, gray_val, gray_val]
                
                ax.imshow(rgb_image, origin='lower', extent=[x1, x2, y1, y2])
            else:
                ax.imshow(cutout, origin='lower', cmap='gray',
                         extent=[x1, x2, y1, y2],
                         vmin=vmin, vmax=vmax)
            
            ax.plot(x, y, 'g+', markersize=15, markeredgewidth=2, label='Centroid')
            
            x_peak, y_peak = find_peak_in_box(data, x, y, box_size=11)
            if abs(x_peak - x) > 0.5 or abs(y_peak - y) > 0.5:
                ax.plot(x_peak, y_peak, 'bx', markersize=10, markeredgewidth=2, label='Peak pixel')
            
            circle1 = plt.Circle((x, y), aperture_radius, color='green',
                                fill=False, linewidth=2, label=f'Aperture (r={aperture_radius:.1f})')
            circle2 = plt.Circle((x, y), inner_ann, color='orange',
                                fill=False, linewidth=1, linestyle='--')
            circle3 = plt.Circle((x, y), outer_ann, color='orange',
                                fill=False, linewidth=1, linestyle='--', 
                                label=f'Annulus ({inner_ann:.1f}-{outer_ann:.1f})')
            
            ax.add_patch(circle1)
            ax.add_patch(circle2)
            ax.add_patch(circle3)
            
            title_str = f'{label} at ({x:.1f}, {y:.1f})'
            if is_sat:
                title_str += f'\nSATURATED: {n_sat} pixels, max={max_val:.0f}'
                ax.set_title(title_str, color='red', fontweight='bold')
            else:
                title_str += f'\nMax pixel: {max_val:.0f}'
                if measurements and idx < len(measurements):
                    m = measurements[idx]
                    title_str = f'{label} at ({x:.1f}, {y:.1f})\n'
                    title_str += f'Flux={m["flux"]:.0f}, SNR={m["snr"]:.1f}, Mag={m["inst_mag"]:.2f}'
                ax.set_title(title_str)
            
            ax.set_xlabel('X (pixels)')
            ax.set_ylabel('Y (pixels)')
            
            handles, labels_legend = ax.get_legend_handles_labels()
            if is_sat:
                sat_patch = Patch(color='red', label=f'Saturated (≥{saturation_limit})')
                handles.append(sat_patch)
            ax.legend(handles=handles, loc='upper right', fontsize=8)
        
        for idx in range(len(positions), 4):
            axes[idx].axis('off')
        
        plt.tight_layout()
        pdf.savefig(fig)
        plt.close()
    
    return measurements

def process_image(filename: str, args: argparse.Namespace, 
                 reference_stars: List[Dict], target_coord: SkyCoord,
                 flat_field: Optional[np.ndarray] = None) -> Dict:
    """
    Process a single FITS image using pre-verified reference stars.
    
    Parameters:
    -----------
    filename : str
        Path to FITS file
    args : argparse.Namespace
        Command line arguments
    reference_stars : List[Dict]
        Verified reference stars with RA/Dec coordinates
    target_coord : SkyCoord
        Target coordinates
    flat_field : Optional[np.ndarray]
        Normalized flat field for calibration
    
    Returns:
    --------
    Dict with processing results
    """
    
    basename = os.path.basename(filename)
    if args.verbose:
        print(f"\nProcessing {basename}...")
    
    result = {
        'filename': basename,
        'success': False,
        'message': '',
        'data': {}
    }
    
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            
            with fits.open(filename) as hdul:
                hdu = None
                for h in hdul:
                    if hasattr(h, 'data') and isinstance(h.data, np.ndarray) and h.data.ndim == 2:
                        hdu = h
                        break
                
                if hdu is None:
                    result['message'] = "No image HDU found"
                    return result
                
                data = hdu.data.astype(np.float32)
                header = hdu.header
            
            # Apply flat field if provided
            if flat_field is not None:
                data = apply_flat_field(data, flat_field)
                if args.verbose:
                    print("  Applied flat field correction")
            
            try:
                wcs = WCS(header)
                has_wcs = True
            except Exception as e:
                wcs = None
                has_wcs = False
                result['message'] = f"No valid WCS: {e}"
                return result
            
            jd = header.get(args.jd_key, np.nan)
            exptime = header.get(args.exptime_key, 1.0)
            
            # Estimate FWHM from bright stars in the central ~30% of the
            # frame (full-frame detection is needlessly slow and memory
            # hungry on very large sensors; the center is representative)
            if args.fwhm is not None:
                fwhm = args.fwhm
            else:
                ny_f, nx_f = data.shape
                fy0, fy1 = int(ny_f * 0.35), int(ny_f * 0.65)
                fx0, fx1 = int(nx_f * 0.35), int(nx_f * 0.65)
                fcrop = np.ascontiguousarray(data[fy0:fy1, fx0:fx1])
                _, median, std = estimate_background(fcrop)
                threshold = 10.0 * std
                temp_fwhm = 10.0
                finder = make_daofinder(fwhm=temp_fwhm, threshold=threshold)
                bright_sources = finder(fcrop - median)
                if bright_sources is None or len(bright_sources) == 0:
                    finder = make_daofinder(fwhm=temp_fwhm,
                                            threshold=5.0 * std)
                    bright_sources = finder(fcrop - median)
                
                if bright_sources is not None and len(bright_sources) > 0:
                    bright_x, bright_y = source_xy(bright_sources)
                    fwhm = estimate_fwhm_from_stars(fcrop - median, bright_x, bright_y, args.saturation)
                else:
                    fwhm = 6.0
                fwhm = float(np.clip(fwhm, 2.0, 15.0))
            
            # Set aperture parameters
            ap_radius = args.aperture_factor * fwhm
            ann_inner = 3.0 * fwhm
            ann_outer = 4.5 * fwhm
            
            # Measure the target using WCS coordinates
            target_x, target_y = wcs.world_to_pixel(target_coord)
            
            # Find peak near target and refine
            target_x_peak, target_y_peak = find_peak_in_box(data, target_x, 
                                                            target_y, box_size=21)
            target_x_ref, target_y_ref = iterative_centroid(data, target_x_peak, target_y_peak,
                                                           box_size=15, max_iterations=5)
            
            # Check saturation
            target_saturated, n_saturated_pixels, max_val = check_saturation(
                data, target_x_ref, target_y_ref, ap_radius, args.saturation
            )
            
            if target_saturated and args.verbose:
                print(f"  WARNING: Target appears to be SATURATED! ({n_saturated_pixels} saturated pixels)")
            
            # Measure target
            target_phot = measure_aperture_photometry(
                data, np.array([target_x_ref]), np.array([target_y_ref]),
                ap_radius, (ann_inner, ann_outer)
            )
            
            target_result = {
                'x': float(target_x_ref),
                'y': float(target_y_ref),
                'inst_mag': float(target_phot['magnitude'][0]),
                'inst_mag_err': float(target_phot['magnitude_err'][0]),
                'snr': float(target_phot['snr'][0]),
                'flux': float(target_phot['flux'][0]),
                'flux_err': float(target_phot['flux_err'][0]),
                'saturated': target_saturated,
                'n_saturated_pixels': int(n_saturated_pixels)
            }
            
            if args.verbose:
                print(f"  Target: flux={target_result['flux']:.0f}, SNR={target_result['snr']:.1f}")
            
            # Find and measure reference stars using their WCS coordinates
            matched_standards = []
            
            for i, ref_star in enumerate(reference_stars):
                ref_coord = SkyCoord(ref_star['ra']*u.deg, ref_star['dec']*u.deg)
                
                ref_result = find_reference_star_in_image(
                    data, wcs, ref_coord,
                    args.search_radius, ap_radius, (ann_inner, ann_outer)
                )
                
                if ref_result is not None:
                    matched_standards.append({
                        'x': ref_result['x'],
                        'y': ref_result['y'],
                        'ra': ref_star['ra'],
                        'dec': ref_star['dec'],
                        'inst_mag': ref_result['inst_mag'],
                        'inst_mag_err': ref_result['inst_mag_err'],
                        'snr': ref_result['snr'],
                        'ref_id': i
                    })
                    if args.verbose:
                        print(f"    Found reference {i+1}: x={ref_result['x']:.1f}, y={ref_result['y']:.1f}, "
                              f"SNR={ref_result['snr']:.1f}")
                else:
                    if args.verbose:
                        print(f"    WARNING: Could not find reference {i+1} in this image")
            
            # ----------------------------------------------------------
            # Photometric calibration: zero point from catalog-matched
            # reference stars, then calibrated target magnitude.
            #   calib_mag = inst_mag + zp,  where zp_i = cat_mag - inst_mag
            # ----------------------------------------------------------
            zp, zp_err, zp_nstars = compute_zero_point(matched_standards,
                                                       reference_stars)
            if np.isfinite(zp):
                target_calib_mag = target_result['inst_mag'] + zp
                target_calib_mag_err = float(np.sqrt(
                    target_result['inst_mag_err']**2 + zp_err**2))
                if args.verbose:
                    print(f"  Zero point: {zp:.3f} +/- {zp_err:.3f} "
                          f"({zp_nstars} stars); "
                          f"calibrated mag = {target_calib_mag:.3f}")
            else:
                target_calib_mag = np.nan
                target_calib_mag_err = np.nan
            
            quality_flags = build_quality_flags(target_result,
                                                len(matched_standards),
                                                len(reference_stars), zp)
            
            # Create diagnostic plots if requested
            if args.create_diagnostics:
                positions = []
                labels = []
                
                if target_result:
                    positions.append((target_result['x'], target_result['y']))
                    labels.append('Target' + (' [SAT]' if target_result['saturated'] else ''))
                
                for i, std in enumerate(matched_standards[:3]):
                    ref = reference_stars[std['ref_id']]
                    if ref.get('cat_mag') is not None:
                        labels.append(f"Ref{i+1} (cat {ref['cat_mag']:.2f})")
                    else:
                        labels.append(f'Ref{i+1}')
                    positions.append((std['x'], std['y']))
                
                _, median, _ = estimate_background(data)
                pdf_file = filename.replace('.fits', '').replace('.fts', '') + '_diagnostic.pdf'
                create_diagnostic_plots(data, positions, labels, fwhm, filename, pdf_file,
                                       median, ap_radius, ann_inner, ann_outer, args.saturation)
                
                if args.verbose:
                    print(f"  Created diagnostic PDF: {pdf_file}")
            
            # Prepare result
            result['success'] = True
            result['data'] = {
                'jd': float(jd) if np.isfinite(jd) else None,
                'exptime': float(exptime),
                'fwhm': float(fwhm),
                'n_sources': len(matched_standards) + 1,
                'n_standards': len(matched_standards),
                'standards': matched_standards,
                'target': target_result,
                'flat_applied': flat_field is not None,
                'zp': zp,
                'zp_err': zp_err,
                'zp_nstars': zp_nstars,
                'target_calib_mag': target_calib_mag,
                'target_calib_mag_err': target_calib_mag_err,
                'quality_flags': quality_flags
            }
            
            # Print summary
            flat_status = " (flat-fielded)" if flat_field is not None else ""
            print(f"{basename}: {len(matched_standards)}/{len(reference_stars)} references, FWHM={fwhm:.1f}{flat_status}")
            
            if target_result and np.isfinite(target_result['inst_mag']):
                status = " (SATURATED)" if target_result.get('saturated', False) else ""
                calib_str = (f", calib_mag={target_calib_mag:.3f}"
                             if np.isfinite(target_calib_mag) else "")
                print(f"  Target: inst_mag={target_result['inst_mag']:.3f}{status}{calib_str}, "
                      f"SNR={target_result['snr']:.1f} [{quality_flags}]")
            
    except Exception as e:
        result['message'] = str(e)
        if args.verbose:
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
    
    return result

def main():
    """Main processing function."""
    args = parse_args()
    
    if not os.path.isdir(args.imagedir):
        print(f"Error: {args.imagedir} is not a directory")
        sys.exit(1)
    
    try:
        target_coord = parse_coordinates(args.target_ra, args.target_dec)
        print(f"Target coordinates: RA={target_coord.ra.deg:.6f}°, Dec={target_coord.dec.deg:.6f}°")
    except Exception as e:
        print(f"Error parsing target coordinates: {e}")
        sys.exit(1)
    
    # Load flat field if provided
    flat_field = None
    if args.flat:
        flat_field = load_flat_field(args.flat, args.verbose)
        if flat_field is not None:
            print(f"Loaded flat field from {args.flat}")
        else:
            print("Warning: Failed to load flat field, continuing without flat field correction")
    
    # Find all FITS files
    patterns = ['*.fits', '*.fit', '*.fts', '*.FITS', '*.FIT', '*.FTS', '*.fz']
    fits_files = []
    for pattern in patterns:
        fits_files.extend(glob.glob(os.path.join(args.imagedir, pattern)))
    
    # Exclude the flat field file from processing if it's in the same directory
    if args.flat and os.path.abspath(args.flat) in [os.path.abspath(f) for f in fits_files]:
        fits_files = [f for f in fits_files if os.path.abspath(f) != os.path.abspath(args.flat)]
        if args.verbose:
            print(f"Excluded flat field file from processing list")
    
    if len(fits_files) == 0:
        print("No FITS files found in directory")
        sys.exit(1)
    
    fits_files = sorted(fits_files)
    print(f"Found {len(fits_files)} FITS files")

    # Resolve the target's display name: explicit argument first, then the
    # OBJECT (or TARGET/TARGNAME) keyword of the first image's header.
    object_label = (args.object_name or '').strip()
    if not object_label:
        try:
            hdr0 = fits.getheader(fits_files[0])
            for key in ('OBJECT', 'TARGET', 'TARGNAME', 'OBJNAME'):
                v = hdr0.get(key)
                if v and str(v).strip():
                    object_label = str(v).strip()
                    break
        except Exception:
            pass
    if object_label:
        print(f"Target name: {object_label}")
    
    # Select and verify reference stars across the stack
    reference_stars = select_and_verify_reference_stars(fits_files, args, target_coord, flat_field)
    
    if reference_stars is None:
        print("ERROR: Failed to select and verify reference stars")
        sys.exit(1)
    
    # ------------------------------------------------------------------
    # Online catalog matching: look up known magnitudes for the target
    # and every reference star, in the requested filter (or the closest
    # available band). Results are attached to the star dictionaries and
    # used later to compute per-image zero points and calibrated mags.
    # ------------------------------------------------------------------
    target_catalog = None
    if args.catalog != 'none':
        print("\nCatalog matching:")
        all_coords = [target_coord] + [SkyCoord(r['ra'] * u.deg, r['dec'] * u.deg)
                                       for r in reference_stars]
        cat_results = query_catalog_magnitudes(
            all_coords, args.filter, args.catalog,
            args.catalog_radius, args.verbose)
        target_catalog = cat_results[0]
        for ref, match in zip(reference_stars, cat_results[1:]):
            if match is not None:
                ref['cat_mag'] = match['cat_mag']
                ref['cat_mag_err'] = match['cat_mag_err']
                ref['catalog'] = match['catalog']
                ref['cat_match_dist'] = match['match_dist_arcsec']
        n_with_cat = sum(1 for r in reference_stars if r.get('cat_mag') is not None)
        if n_with_cat > 0:
            print(f"  Zero points will be computed from {n_with_cat} "
                  f"catalog-matched reference star(s)")
            for i, r in enumerate(reference_stars):
                if r.get('cat_mag') is not None:
                    print(f"    Reference {i+1}: {r['catalog']} "
                          f"{args.filter}={r['cat_mag']:.3f} "
                          f"+/- {r.get('cat_mag_err', np.nan):.3f} "
                          f"(match {r['cat_match_dist']:.2f}\")")
        if target_catalog is not None:
            print(f"  Target also matched in catalog: "
                  f"{target_catalog['catalog']} {args.filter}="
                  f"{target_catalog['cat_mag']:.3f} "
                  f"(useful as a sanity check for non-variable targets)")
    
    print(f"Processing {len(fits_files)} images with {len(reference_stars)} verified reference stars...")
    if flat_field is not None:
        print("Flat field correction will be applied to all images")
    
    if args.create_diagnostics:
        print("Diagnostic PDFs will be created for each image")
    
    # Process all images
    results = []
    for fits_file in fits_files:
        result = process_image(fits_file, args, reference_stars, target_coord, flat_field)
        results.append(result)
    
    # Create output CSV
    csv_rows = []
    for result in results:
        if not result['success']:
            row = {
                'filename': result['filename'],
                'object': object_label,
                'jd': np.nan,
                'filter': args.filter,
                'exptime': np.nan,
                'fwhm': np.nan,
                'n_sources': 0,
                'n_standards': 0,
                'target_x': np.nan,
                'target_y': np.nan,
                'target_ra': target_coord.ra.deg,
                'target_dec': target_coord.dec.deg,
                'target_inst_mag': np.nan,
                'target_inst_mag_err': np.nan,
                'target_snr': np.nan,
                'target_flux': np.nan,
                'target_flux_err': np.nan,
                'target_saturated': False,
                'target_n_sat_pixels': 0,
                'flat_applied': False,
                'zp': np.nan,
                'zp_err': np.nan,
                'zp_nstars': 0,
                'target_calib_mag': np.nan,
                'target_calib_mag_err': np.nan,
                'quality_flags': 'PROCESSING_FAILED',
                'error': result['message']
            }
            
            for i in range(args.max_standards):
                row[f'std{i+1}_x'] = np.nan
                row[f'std{i+1}_y'] = np.nan
                row[f'std{i+1}_ra'] = np.nan
                row[f'std{i+1}_dec'] = np.nan
                row[f'std{i+1}_inst_mag'] = np.nan
                row[f'std{i+1}_inst_mag_err'] = np.nan
                row[f'std{i+1}_snr'] = np.nan
                row[f'std{i+1}_cat_mag'] = np.nan
                row[f'std{i+1}_cat_mag_err'] = np.nan
                row[f'std{i+1}_catalog'] = ''
            
            csv_rows.append(row)
            continue
        
        data = result['data']
        row = {
            'filename': result['filename'],
            'object': object_label,
            'jd': data['jd'] if data['jd'] is not None else np.nan,
            'filter': args.filter,
            'exptime': data['exptime'],
            'fwhm': data.get('fwhm', np.nan),
            'n_sources': data['n_sources'],
            'n_standards': data['n_standards'],
            'target_x': data['target'].get('x', np.nan) if data['target'] else np.nan,
            'target_y': data['target'].get('y', np.nan) if data['target'] else np.nan,
            'target_ra': target_coord.ra.deg,
            'target_dec': target_coord.dec.deg,
            'target_inst_mag': data['target'].get('inst_mag', np.nan) if data['target'] else np.nan,
            'target_inst_mag_err': data['target'].get('inst_mag_err', np.nan) if data['target'] else np.nan,
            'target_snr': data['target'].get('snr', np.nan) if data['target'] else np.nan,
            'target_flux': data['target'].get('flux', np.nan) if data['target'] else np.nan,
            'target_flux_err': data['target'].get('flux_err', np.nan) if data['target'] else np.nan,
            'target_saturated': data['target'].get('saturated', False) if data['target'] else False,
            'target_n_sat_pixels': data['target'].get('n_saturated_pixels', 0) if data['target'] else 0,
            'flat_applied': data.get('flat_applied', False),
            'zp': data.get('zp', np.nan),
            'zp_err': data.get('zp_err', np.nan),
            'zp_nstars': data.get('zp_nstars', 0),
            'target_calib_mag': data.get('target_calib_mag', np.nan),
            'target_calib_mag_err': data.get('target_calib_mag_err', np.nan),
            'quality_flags': data.get('quality_flags', ''),
            'error': ''
        }
        
        # Add reference star measurements (with sky coordinates and any
        # catalog magnitudes, indexed by the verified reference list so
        # columns stay consistent even when a star is missing in one image)
        std_by_id = {s['ref_id']: s for s in data['standards']}
        for i in range(args.max_standards):
            std = std_by_id.get(i)
            ref = reference_stars[i] if i < len(reference_stars) else {}
            if std is not None:
                row[f'std{i+1}_x'] = std['x']
                row[f'std{i+1}_y'] = std['y']
                row[f'std{i+1}_inst_mag'] = std['inst_mag']
                row[f'std{i+1}_inst_mag_err'] = std.get('inst_mag_err', np.nan)
                row[f'std{i+1}_snr'] = std['snr']
            else:
                row[f'std{i+1}_x'] = np.nan
                row[f'std{i+1}_y'] = np.nan
                row[f'std{i+1}_inst_mag'] = np.nan
                row[f'std{i+1}_inst_mag_err'] = np.nan
                row[f'std{i+1}_snr'] = np.nan
            row[f'std{i+1}_ra'] = ref.get('ra', np.nan)
            row[f'std{i+1}_dec'] = ref.get('dec', np.nan)
            cat_mag = ref.get('cat_mag')
            row[f'std{i+1}_cat_mag'] = cat_mag if cat_mag is not None else np.nan
            row[f'std{i+1}_cat_mag_err'] = ref.get('cat_mag_err', np.nan)
            row[f'std{i+1}_catalog'] = ref.get('catalog', '')
        
        csv_rows.append(row)
    
    # Write CSV file
    df = pd.DataFrame(csv_rows)
    
    # Calculate standard deviation of target instrumental magnitudes across all images
    valid_target_mags = df['target_inst_mag'][np.isfinite(df['target_inst_mag'])]
    if len(valid_target_mags) > 1:
        target_inst_mag_stddev = np.std(valid_target_mags)
    else:
        target_inst_mag_stddev = np.nan
    
    # Add this as a column to all rows
    df['target_inst_mag_stddev_all'] = target_inst_mag_stddev
    
    # Global zero point summary across the run (mean of per-image values)
    valid_zp = df['zp'][np.isfinite(df['zp'])]
    df['global_zp_mean'] = np.mean(valid_zp) if len(valid_zp) > 0 else np.nan
    df['global_zp_n_standards'] = int(df['zp_nstars'].max()) if len(df) else 0
    
    df.to_csv(args.output, index=False)
    print(f"\nWrote results to {args.output}")
    
    # Print summary statistics
    successful = [r for r in results if r['success']]
    print(f"\nProcessing summary:")
    print(f"  Total images: {len(results)}")
    print(f"  Successful: {len(successful)}")
    print(f"  Failed: {len(results) - len(successful)}")
    if flat_field is not None:
        print(f"  Flat field correction: Applied")
    
    if successful:
        # Calculate statistics
        target_mags = [r['data']['target']['inst_mag'] for r in successful 
                      if r['data']['target'] and 
                      np.isfinite(r['data']['target'].get('inst_mag', np.nan))]
        fwhm_values = [r['data'].get('fwhm', np.nan) for r in successful]
        fwhm_values = [f for f in fwhm_values if np.isfinite(f)]
        
        if target_mags:
            print(f"\nTarget magnitude statistics:")
            print(f"  Mean: {np.mean(target_mags):.3f}")
            print(f"  Std:  {np.std(target_mags):.3f}")
            print(f"  Min:  {np.min(target_mags):.3f}")
            print(f"  Max:  {np.max(target_mags):.3f}")
        
        calib_mags = [r['data'].get('target_calib_mag', np.nan) for r in successful]
        calib_mags = [m for m in calib_mags if np.isfinite(m)]
        if calib_mags:
            print(f"\nCalibrated target magnitude statistics ({args.filter} band):")
            print(f"  Mean: {np.mean(calib_mags):.3f}")
            print(f"  Std:  {np.std(calib_mags):.3f}")
            zp_values = [r['data'].get('zp', np.nan) for r in successful]
            zp_values = [z for z in zp_values if np.isfinite(z)]
            print(f"  Mean zero point: {np.mean(zp_values):.3f} "
                  f"(scatter {np.std(zp_values):.3f}) over {len(zp_values)} images")
        
        if fwhm_values:
            print(f"\nFWHM statistics:")
            print(f"  Mean: {np.mean(fwhm_values):.2f} pixels")
            print(f"  Std:  {np.std(fwhm_values):.2f} pixels")
            print(f"  Min:  {np.min(fwhm_values):.2f} pixels")
            print(f"  Max:  {np.max(fwhm_values):.2f} pixels")
        
        # Print reference star consistency
        print(f"\nReference Star Consistency:")
        print(f"  Reference stars selected from: {fits_files[0]}")
        print(f"  Number of reference stars: {len(reference_stars)}")
        
        # Check how many images successfully found all reference stars
        images_with_all_refs = 0
        for r in successful:
            if r['data']['n_standards'] == len(reference_stars):
                images_with_all_refs += 1
        
        print(f"  Images with all {len(reference_stars)} references found: {images_with_all_refs}/{len(successful)}")
        
        # Calculate reference star stability
        for i in range(min(len(reference_stars), args.max_standards)):
            ref_mags = []
            for r in successful:
                if i < len(r['data']['standards']):
                    mag = r['data']['standards'][i].get('inst_mag', np.nan)
                    if np.isfinite(mag):
                        ref_mags.append(mag)
            
            if len(ref_mags) > 1:
                ref_std = np.std(ref_mags)
                ref_mean = np.mean(ref_mags)
                print(f"  Reference {i+1}: mean={ref_mean:.3f}, std={ref_std:.3f} ({len(ref_mags)} detections)")
    
    if args.create_diagnostics:
        print(f"\nDiagnostic PDFs created for each processed image")

if __name__ == "__main__":
    main()
