#!/usr/bin/env python3
"""
ExposeCheck — FITS image quality report generator.

Originally a simple saturation checker, ExposeCheck now produces a full
per-image quality report for a directory of FITS images:

  * saturation statistics (count, percentage, total pixels analyzed)
  * region statistics (mean, median, min, max, standard deviation)
  * exposure time and other header metadata
  * number of stars detected (DAOStarFinder, photutils)

and an end-of-run summary covering the whole image set. Results are saved
to CSV (named {directory}_{mode}.csv, as before) and optionally to a
human-readable text report.

Backwards-compatible usage (unchanged from the original):

    python exposecheck.py /NGC7331 -target
    python exposecheck.py August_2025_flats -center
    python exposecheck.py /HAT-P-31 -all

New options:

    --saturation 60000      custom saturation threshold in ADU
    --no-stars              skip star detection (faster)
    --fwhm 4.0              FWHM guess for star detection (default 4.0 px)
    --threshold-sigma 5.0   detection threshold in background sigma
    --report report.txt     also write a human-readable text report

Example for an exoplanet time series:

    python exposecheck.py ~/data/WASP-135b -target --report wasp135b_quality.txt

Requires: numpy, astropy; photutils (only for star detection).
"""

import argparse
import csv
import os
import sys
import warnings

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats

# photutils is only needed for star detection; degrade gracefully without it.
try:
    from photutils.detection import DAOStarFinder
    PHOTUTILS_AVAILABLE = True
except ImportError:
    PHOTUTILS_AVAILABLE = False
    DAOStarFinder = None

# --- photutils 2.x / 3.x compatibility -------------------------------
# photutils 3.0 renamed DAOStarFinder's 'peakmax' parameter to 'peak_max'
# and the output columns 'xcentroid'/'ycentroid' to 'x_centroid'/'y_centroid'.
import inspect as _inspect
if PHOTUTILS_AVAILABLE:
    _PEAK_KW = ('peak_max' if 'peak_max' in
                _inspect.signature(DAOStarFinder.__init__).parameters else 'peakmax')
else:
    _PEAK_KW = 'peakmax'

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
# File and region helpers
# ----------------------------------------------------------------------

def is_fits_file(filename):
    """True if the filename looks like a FITS image."""
    return filename.lower().endswith(('.fits', '.fit', '.fts'))


def get_central_region(data, region_type='center'):
    """
    Extract a central region from the image data.

    'center' returns the inner half (1/4 of each dimension from center),
    'target' returns the inner fifth (1/10 of each dimension from center).
    These match the original ExposeCheck definitions exactly.
    """
    h, w = data.shape
    cx, cy = w // 2, h // 2

    if region_type == 'center':
        dx, dy = w // 4, h // 4
    elif region_type == 'target':
        dx, dy = w // 10, h // 10
    else:
        raise ValueError(f"Unknown region_type: {region_type}")

    x1, x2 = max(0, cx - dx), min(w, cx + dx)
    y1, y2 = max(0, cy - dy), min(h, cy + dy)
    return data[y1:y2, x1:x2]


def extract_header_info(header):
    """Pull commonly used metadata out of a FITS header, tolerating absences."""
    obj = header.get('OBJECT', 'Unknown')
    exptime = header.get('EXPTIME', header.get('EXPOSURE', 'N/A'))
    filt = header.get('FILTER', header.get('FILTNAM', 'N/A'))
    date = header.get('DATE-OBS', 'N/A')
    ut = header.get('UT', header.get('UTSTART', 'N/A'))
    jd = header.get('JD', 'N/A')
    return obj, exptime, filt, date, ut, jd


# ----------------------------------------------------------------------
# Star detection
# ----------------------------------------------------------------------

def count_stars(region, fwhm=4.0, threshold_sigma=5.0, saturation=65000.0,
                max_pixels=4_000_000):
    """
    Count stars in a region using DAOStarFinder.

    The background level and noise are estimated with sigma-clipped statistics
    (subsampled for very large regions, which is statistically equivalent and
    much faster). Detections brighter than the saturation level are excluded
    via DAOStarFinder's peakmax parameter, and mild sharpness/roundness cuts
    reject hot pixels and cosmic rays.

    For very large regions the image is analyzed in 2x2-binned form to keep
    runtime reasonable; binning preserves real stars (FWHM of a few pixels)
    while averaging down single-pixel artifacts. Returns -1 on failure.
    """
    if not PHOTUTILS_AVAILABLE:
        return -1

    try:
        work = region
        binned = False
        if work.size > max_pixels:
            # 2x2 binning: trim to even dimensions, then average blocks.
            h, w = work.shape
            work = work[:h - h % 2, :w - w % 2]
            work = work.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
            binned = True

        # Subsample for background statistics on big arrays.
        flat = work.ravel()
        if flat.size > 1_000_000:
            flat = flat[:: flat.size // 1_000_000]
        _, bkg_median, bkg_std = sigma_clipped_stats(flat, sigma=3.0, maxiters=5)
        if not np.isfinite(bkg_std) or bkg_std <= 0:
            return -1

        eff_fwhm = max(fwhm / 2.0, 2.0) if binned else fwhm
        finder = make_daofinder(
            fwhm=eff_fwhm,
            threshold=threshold_sigma * bkg_std,
            peak_max=saturation - bkg_median,
            sharplo=0.2, sharphi=1.0,
            roundlo=-1.0, roundhi=1.0,
        )
        sources = finder(work - bkg_median)
        return 0 if sources is None else len(sources)
    except Exception:
        return -1


# ----------------------------------------------------------------------
# Per-image analysis
# ----------------------------------------------------------------------

def process_image(filepath, analysis_mode, saturation=65000.0,
                  detect_stars=True, fwhm=4.0, threshold_sigma=5.0):
    """
    Analyze one FITS image: saturation, region statistics, star count.

    Returns a dict keyed by the CSV column names.
    """
    with fits.open(filepath) as hdul:
        # Use the first HDU that contains a 2D image.
        data, header = None, None
        for hdu in hdul:
            if hasattr(hdu, 'data') and isinstance(hdu.data, np.ndarray) and hdu.data.ndim == 2:
                data = hdu.data.astype(np.float32)
                header = hdu.header
                break
        if data is None:
            raise ValueError("no 2D image HDU found")

    if analysis_mode == 'all':
        region = data
    else:
        region = get_central_region(data, analysis_mode)

    saturated = int(np.sum(region > saturation))
    total = int(region.size)
    percent_sat = 100.0 * saturated / total

    obj, exptime, filt, date, ut, jd = extract_header_info(header)

    n_stars = count_stars(region, fwhm, threshold_sigma, saturation) if detect_stars else -1

    return {
        'Image': os.path.basename(filepath),
        'Object': obj,
        'ExpTime': exptime,
        'Filter': filt,
        'Date': date,
        'UT': ut,
        'JulianDate': jd,
        'Saturated': saturated,
        'TotalPix': total,
        'PctSaturated': percent_sat,
        'Mean': float(np.mean(region)),
        'Median': float(np.median(region)),
        'Min': float(np.min(region)),
        'Max': float(np.max(region)),
        'StdDev': float(np.std(region)),
        'NStars': n_stars,
    }


# ----------------------------------------------------------------------
# Directory scan, summary, and reports
# ----------------------------------------------------------------------

COLUMNS = ['Image', 'Object', 'ExpTime', 'Filter', 'Date', 'UT', 'JulianDate',
           'Saturated', 'TotalPix', 'PctSaturated', 'Mean', 'Median',
           'Min', 'Max', 'StdDev', 'NStars']


def format_row(row):
    """Format one result dict as a console line."""
    return ("{Image:32.32} {Object:14.14} {ExpTime!s:>7} {Filter!s:>6} "
            "{Saturated:>9} {PctSaturated:>7.3f} {Mean:>9.1f} {Median:>9.1f} "
            "{Min:>7.0f} {Max:>7.0f} {StdDev:>8.1f} {NStars:>7}").format(**row)


def build_summary(report, saturation):
    """Compute end-of-run summary statistics across the image set."""
    if not report:
        return {}
    pct = np.array([r['PctSaturated'] for r in report])
    medians = np.array([r['Median'] for r in report])
    star_counts = np.array([r['NStars'] for r in report if r['NStars'] >= 0])
    return {
        'n_images': len(report),
        'n_with_saturation': int(np.sum(pct > 0)),
        'worst_pct': float(np.max(pct)),
        'worst_image': report[int(np.argmax(pct))]['Image'],
        'median_background': float(np.median(medians)),
        'typical_n_stars': float(np.median(star_counts)) if len(star_counts) else None,
        'saturation_level': saturation,
    }


def print_summary(summary):
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Images processed:            {summary['n_images']}")
    print(f"Images with saturation:      {summary['n_with_saturation']} "
          f"(threshold > {summary['saturation_level']:.0f} ADU)")
    print(f"Worst saturation:            {summary['worst_pct']:.3f}% "
          f"({summary['worst_image']})")
    print(f"Median background (set):     {summary['median_background']:.1f} ADU")
    if summary['typical_n_stars'] is not None:
        print(f"Typical stars detected:      {summary['typical_n_stars']:.0f}")
    elif not PHOTUTILS_AVAILABLE:
        print("Star detection skipped:      photutils not installed")


def write_text_report(path, directory, analysis_mode, report, summary):
    """Write a human-readable text report mirroring the console output."""
    with open(path, 'w') as f:
        f.write("ExposeCheck Image Quality Report\n")
        f.write(f"Directory: {directory}\nRegion analyzed: {analysis_mode}\n")
        f.write("=" * 70 + "\n\n")
        for r in report:
            f.write(f"{r['Image']}\n")
            f.write(f"  Object: {r['Object']}   ExpTime: {r['ExpTime']}   "
                    f"Filter: {r['Filter']}   Date: {r['Date']}\n")
            f.write(f"  Saturated pixels: {r['Saturated']} of {r['TotalPix']} "
                    f"({r['PctSaturated']:.3f}%)\n")
            f.write(f"  ADU stats: mean={r['Mean']:.1f}  median={r['Median']:.1f}  "
                    f"min={r['Min']:.0f}  max={r['Max']:.0f}  std={r['StdDev']:.1f}\n")
            if r['NStars'] >= 0:
                f.write(f"  Stars detected: {r['NStars']}\n")
            f.write("\n")
        f.write("=" * 70 + "\nSUMMARY\n")
        f.write(f"Images processed:        {summary['n_images']}\n")
        f.write(f"Images with saturation:  {summary['n_with_saturation']}\n")
        f.write(f"Worst saturation:        {summary['worst_pct']:.3f}% "
                f"({summary['worst_image']})\n")
        f.write(f"Median background:       {summary['median_background']:.1f} ADU\n")
        if summary['typical_n_stars'] is not None:
            f.write(f"Typical stars detected:  {summary['typical_n_stars']:.0f}\n")


def scan_directory(directory, analysis_mode, saturation, detect_stars,
                   fwhm, threshold_sigma, report_path=None):
    """Scan a directory of FITS files, analyze each, write CSV (and report)."""
    mode_descriptions = {
        'all': 'entire image',
        'center': 'inner half (central 50%)',
        'target': 'inner 1/5 (central 20%)',
    }
    print(f"\nAnalyzing {mode_descriptions[analysis_mode]} of each image "
          f"(saturation > {saturation:.0f} ADU)\n")

    header_line = ("{:32} {:14} {:>7} {:>6} {:>9} {:>7} {:>9} {:>9} "
                   "{:>7} {:>7} {:>8} {:>7}").format(
        'Image', 'Object', 'ExpTime', 'Filter', 'Saturated', '%Sat',
        'Mean', 'Median', 'Min', 'Max', 'StdDev', 'NStars')
    print(header_line)
    print("-" * len(header_line))

    report = []
    for fname in sorted(os.listdir(directory)):
        if not is_fits_file(fname):
            continue
        try:
            row = process_image(os.path.join(directory, fname), analysis_mode,
                                saturation, detect_stars, fwhm, threshold_sigma)
            report.append(row)
            print(format_row(row))
        except Exception as e:
            print(f"{fname:32} ERROR: {e}")

    if not report:
        print("\nNo FITS images were successfully processed.")
        return

    # CSV output, named exactly as the original program did.
    csv_path = f"{os.path.basename(os.path.normpath(directory))}_{analysis_mode}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(report)
    print(f"\nCSV report saved as: {csv_path}")

    summary = build_summary(report, saturation)
    print_summary(summary)

    if report_path:
        write_text_report(report_path, directory, analysis_mode, report, summary)
        print(f"Text report saved as: {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description="FITS image quality reports: saturation, statistics, and star counts.",
        epilog="Example: python exposecheck.py ~/data/WASP-135b -target "
               "--report wasp135b_quality.txt")
    parser.add_argument("directory", help="Directory containing FITS images")

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("-all", action="store_true",
                            help="Analyze entire image")
    mode_group.add_argument("-center", action="store_true",
                            help="Analyze inner half of image (central 50%%)")
    mode_group.add_argument("-target", action="store_true",
                            help="Analyze inner 1/5 of image (central 20%%)")

    parser.add_argument("--saturation", type=float, default=65000.0,
                        help="Saturation threshold in ADU (default: 65000)")
    parser.add_argument("--no-stars", action="store_true",
                        help="Skip star detection for faster processing")
    parser.add_argument("--fwhm", type=float, default=4.0,
                        help="FWHM in pixels for star detection (default: 4.0)")
    parser.add_argument("--threshold-sigma", type=float, default=5.0,
                        help="Star detection threshold in background sigma (default: 5.0)")
    parser.add_argument("--report", default=None, metavar="FILE",
                        help="Also write a human-readable text report to FILE")

    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"Error: {args.directory} is not a directory")
        sys.exit(1)

    analysis_mode = 'all' if args.all else ('center' if args.center else 'target')
    detect_stars = not args.no_stars
    if detect_stars and not PHOTUTILS_AVAILABLE:
        print("Note: photutils not installed; star detection will be skipped. "
              "Install with: pip install photutils")
        detect_stars = False

    scan_directory(args.directory, analysis_mode, args.saturation, detect_stars,
                   args.fwhm, args.threshold_sigma, args.report)


if __name__ == "__main__":
    main()
