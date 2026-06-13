#!/usr/bin/env python3
"""
plot_differential_photometry.py — light curves from PhotoCalib CSV output.

Improvements over the original version:

  * Reference stars are detected dynamically (any number of stdN columns).
  * The averaged-reference panel uses inverse-variance weighting and
    automatically rejects unstable reference stars (those whose differential
    RMS is far above the others) before averaging.
  * Saturated or low-quality measurements are flagged on every panel
    (open red markers) and excluded from the statistics.
  * When PhotoCalib provides catalog zero points, a third page shows the
    calibrated photometric light curve of the target together with the
    per-image zero points.
  * Optional polynomial trend line (--trend N).
  * A printed summary table reports mean instrumental and calibrated
    magnitudes, RMS scatter, usable and rejected image counts, and which
    reference stars were used.

The command-line interface is backwards compatible.

Typical exoplanet workflow:

    python3 photcalib_robust_fixed.py ~/data/WASP-135b -f "r'" \\
        -o wasp135b_phot.csv --target-ra "17:49:08.39" --target-dec "+29:52:44.8"
    python3 plot_differential_photometry.py wasp135b_phot.csv \\
        -o wasp135b_transit.pdf --title "WASP-135b Transit" --verbose

Requires: numpy, pandas, matplotlib.
"""

import argparse
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

warnings.filterwarnings("ignore")

def set_page_title(fig, header, kind):
    """Headline the target name in bold, with the page kind and detail
    beneath it."""
    main, detail = header if isinstance(header, tuple) else (header, '')
    # Offsets in absolute inches so short and tall figures both lay out
    # the two-line title without overlap.
    h = fig.get_figheight()
    fig.suptitle(main, fontsize=15, fontweight='bold', y=1 - 0.10 / h)
    sub = kind + (f"   {detail}" if detail else '')
    fig.text(0.5, 1 - 0.42 / h, sub, ha='center', fontsize=9, color='#444')


PANEL_COLORS = ['purple', 'tab:blue', 'tab:green', 'tab:red',
                'tab:orange', 'tab:brown', 'tab:pink', 'tab:cyan']


# ----------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Create differential and calibrated light curves from "
                    "PhotoCalib CSV output.",
        epilog='Example: python3 plot_differential_photometry.py '
               'wasp135b_phot.csv -o transit.pdf --trend 2 --verbose')
    p.add_argument("csv_file", help="Input CSV file from the PhotoCalib pipeline")
    p.add_argument("-o", "--output",
                   help="Output plot filename (default: <csv>_lightcurve.pdf)")
    p.add_argument("--title", help="Plot title (default: auto-generated)")
    p.add_argument("--show", action="store_true",
                   help="Display plots interactively")
    p.add_argument("--markersize", type=float, default=8,
                   help="Marker size (default: 8)")
    p.add_argument("--figsize", nargs=2, type=float, default=[12, 10],
                   help="Figure size in inches: width height (default: 12 10)")
    p.add_argument("--ylim", nargs=2, type=float,
                   help="Y-axis limits for differential plots "
                        "(deprecated, use --min/--max)")
    p.add_argument("--min", type=float, dest="ymin",
                   help="Minimum y-axis value for differential plots")
    p.add_argument("--max", type=float, dest="ymax",
                   help="Maximum y-axis value for differential plots")
    p.add_argument("--trend", type=int, default=None, metavar="DEG",
                   help="Overlay a polynomial trend line of degree DEG on the "
                        "averaged differential panel (e.g. 1 or 2)")
    p.add_argument("--zoom-precision", type=float, default=0.5,
                   metavar="MAG",
                   help="Half-range in magnitudes for the final zoomed "
                        "light-curve page: y-axis spans the median target "
                        "magnitude +/- this value (default: 0.5)")
    p.add_argument("--reject-rms-factor", type=float, default=3.0,
                   help="Reject a reference star from the average when its "
                        "differential RMS exceeds this factor times the median "
                        "RMS of all references (default: 3.0)")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    return p.parse_args()


# ----------------------------------------------------------------------
# Data handling
# ----------------------------------------------------------------------

def detect_reference_stars(df):
    """Return the sorted list of reference star numbers present in the CSV."""
    nums = set()
    for col in df.columns:
        m = re.match(r'std(\d+)_inst_mag$', col)
        if m:
            nums.add(int(m.group(1)))
    return sorted(nums)


def quality_mask(df):
    """
    Boolean mask of low-quality rows: saturated target, processing errors,
    or explicit quality flags other than OK. These points are drawn with
    open red markers and excluded from statistics.
    """
    bad = pd.Series(False, index=df.index)
    if 'target_saturated' in df.columns:
        bad |= df['target_saturated'].astype(str).str.lower().isin(['true', '1'])
    if 'quality_flags' in df.columns:
        # Only flags that compromise the measurement itself mark a point as
        # low quality. NO_ZP merely means no catalog calibration was
        # available; the differential photometry is unaffected.
        fatal = ('SATURATED', 'LOW_SNR', 'FEW_REFS', 'PROCESSING_FAILED')
        flags = df['quality_flags'].fillna('').astype(str)
        bad |= flags.apply(lambda s: any(f in s for f in fatal))
    if 'error' in df.columns:
        bad |= df['error'].fillna('').astype(str).str.len() > 0
    return bad.values


def differential_for_reference(df, std_num):
    """
    Differential photometry (target - one reference star).

    Returns jd, diff_mag, diff_mag_err, bad_flag arrays restricted to rows
    where target, reference, and JD are all finite. Errors are propagated
    from both stars; when individual errors are missing they are estimated
    from SNR via mag_err ~ 1.0857/SNR.
    """
    mcol, ecol, scol = (f'std{std_num}_inst_mag', f'std{std_num}_inst_mag_err',
                        f'std{std_num}_snr')
    valid = (np.isfinite(df['target_inst_mag']) & np.isfinite(df[mcol])
             & np.isfinite(df['jd']))
    if not np.any(valid):
        return (np.array([]),) * 4

    jd = df.loc[valid, 'jd'].values
    diff = (df.loc[valid, 'target_inst_mag'] - df.loc[valid, mcol]).values

    terr = df.loc[valid, 'target_inst_mag_err'].values \
        if 'target_inst_mag_err' in df.columns else np.full(len(jd), np.nan)
    serr = df.loc[valid, ecol].values if ecol in df.columns \
        else np.full(len(jd), np.nan)

    # Fall back to SNR-based error estimates where errors are missing/zero.
    if 'target_snr' in df.columns:
        tsnr = df.loc[valid, 'target_snr'].values
        fallback = 1.0857 / np.where(tsnr > 0, tsnr, 100.0)
        terr = np.where(np.isfinite(terr) & (terr > 1e-4), terr, fallback)
    if scol in df.columns:
        ssnr = df.loc[valid, scol].values
        fallback = 1.0857 / np.where(ssnr > 0, ssnr, 100.0)
        serr = np.where(np.isfinite(serr) & (serr > 1e-4), serr, fallback)

    err = np.sqrt(np.nan_to_num(terr)**2 + np.nan_to_num(serr)**2)
    err[err <= 0] = 0.01
    bad = quality_mask(df)[valid.values]
    return jd, diff, err, bad


def weighted_average_differential(df, std_nums, reject_rms_factor=3.0,
                                  verbose=False):
    """
    Average-of-references differential light curve.

    For each exposure the target magnitude is compared against the
    inverse-variance-weighted mean of all valid reference star magnitudes.
    Reference stars whose individual differential RMS is more than
    reject_rms_factor times the median RMS of all references are treated as
    unstable (likely variables) and excluded from the average entirely.

    Returns jd, avg_diff, avg_err, n_refs, bad_flag, used_refs, rejected_refs.
    """
    # First pass: per-reference RMS to identify unstable references.
    rms_by_ref = {}
    for n in std_nums:
        _, diff, _, bad = differential_for_reference(df, n)
        good = diff[~bad] if len(diff) else diff
        if len(good) > 1:
            rms_by_ref[n] = float(np.std(good))
    used, rejected = list(std_nums), []
    if len(rms_by_ref) >= 3:
        median_rms = np.median(list(rms_by_ref.values()))
        rejected = [n for n, r in rms_by_ref.items()
                    if r > reject_rms_factor * median_rms]
        used = [n for n in std_nums if n not in rejected]
        if rejected and verbose:
            print(f"Rejected unstable reference star(s): "
                  f"{', '.join(f'Std{n} (RMS {rms_by_ref[n]:.3f})' for n in rejected)}")

    # Second pass: per-row weighted mean reference magnitude.
    bad_rows = quality_mask(df)
    jd_list, avg_list, err_list, n_list, bad_list = [], [], [], [], []
    for idx in range(len(df)):
        row = df.iloc[idx]
        if not (np.isfinite(row.get('jd', np.nan))
                and np.isfinite(row.get('target_inst_mag', np.nan))):
            continue
        mags, weights = [], []
        for n in used:
            m = row.get(f'std{n}_inst_mag', np.nan)
            if not np.isfinite(m):
                continue
            e = row.get(f'std{n}_inst_mag_err', np.nan)
            snr = row.get(f'std{n}_snr', np.nan)
            if not (np.isfinite(e) and e > 1e-4):
                e = 1.0857 / snr if np.isfinite(snr) and snr > 0 else 0.01
            mags.append(m)
            weights.append(1.0 / e**2)
        if not mags:
            continue
        mags, weights = np.array(mags), np.array(weights)
        ref_mean = np.average(mags, weights=weights)
        ref_err = 1.0 / np.sqrt(np.sum(weights))

        terr = row.get('target_inst_mag_err', np.nan)
        tsnr = row.get('target_snr', np.nan)
        if not (np.isfinite(terr) and terr > 1e-4):
            terr = 1.0857 / tsnr if np.isfinite(tsnr) and tsnr > 0 else 0.01

        jd_list.append(row['jd'])
        avg_list.append(row['target_inst_mag'] - ref_mean)
        err_list.append(np.sqrt(terr**2 + ref_err**2))
        n_list.append(len(mags))
        bad_list.append(bool(bad_rows[idx]))

    return (np.array(jd_list), np.array(avg_list), np.array(err_list),
            np.array(n_list), np.array(bad_list), used, rejected)


# ----------------------------------------------------------------------
# Plot helpers
# ----------------------------------------------------------------------

def plot_series(ax, jd, vals, errs, bad, color, label, markersize, ylim=None):
    """One light-curve panel: good points filled, flagged points open red."""
    good = ~bad
    if np.any(good):
        ax.errorbar(jd[good], vals[good], yerr=errs[good], fmt='o',
                    color=color, markersize=markersize / 2.0,
                    capsize=2, alpha=0.85, label=label)
    if np.any(bad):
        ax.errorbar(jd[bad], vals[bad], yerr=errs[bad], fmt='D',
                    markerfacecolor='none', markeredgecolor='red',
                    ecolor='red', markersize=markersize / 1.6, capsize=2,
                    alpha=0.9, label='flagged (saturated/low quality)')

    if np.sum(good) > 1:
        w = 1.0 / np.maximum(errs[good], 1e-6)**2
        wmean = np.average(vals[good], weights=w)
        rms = np.std(vals[good])
        chi2 = np.sum(((vals[good] - wmean) / np.maximum(errs[good], 1e-6))**2)
        chi2dof = chi2 / max(np.sum(good) - 1, 1)
        ax.axhline(wmean, ls='--', color=color, alpha=0.6, lw=1)
        ax.axhspan(wmean - rms, wmean + rms, color=color, alpha=0.12)
        ax.text(0.02, 0.95,
                f"N={int(np.sum(good))}, RMS={rms:.3f} mag, "
                f"\u03c7\u00b2/dof={chi2dof:.2f}, wmean={wmean:.3f}",
                transform=ax.transAxes, fontsize=8, va='top',
                bbox=dict(boxstyle='round', fc='white', alpha=0.8))
    ax.invert_yaxis()
    if ylim is not None:
        ax.set_ylim(max(ylim), min(ylim))  # inverted magnitude axis
    ax.legend(fontsize=7, loc='upper right')
    ax.grid(alpha=0.3)


def series_stats(vals, errs, bad):
    """(mean, rms, chi2/dof, n_good) over the good points of a series."""
    good = ~bad & np.isfinite(vals)
    if np.sum(good) < 1:
        return np.nan, np.nan, np.nan, 0
    v, e = vals[good], np.maximum(errs[good], 1e-6)
    w = 1.0 / e**2
    mean = np.average(v, weights=w)
    rms = np.std(v) if np.sum(good) > 1 else 0.0
    chi2dof = (np.sum(((v - mean) / e)**2) / max(np.sum(good) - 1, 1)
               if np.sum(good) > 1 else np.nan)
    return float(mean), float(rms), float(chi2dof), int(np.sum(good))


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------

def page_differential(pdf, df, std_nums, args, header, jd_min, ylim):
    """Page 1: averaged-reference differential plus per-reference panels."""
    jd, avg, err, n_refs, bad, used, rejected = weighted_average_differential(
        df, std_nums, args.reject_rms_factor, args.verbose)

    n_panels = 1 + len(std_nums)
    fig, axes = plt.subplots(n_panels, 1, figsize=args.figsize, sharex=True)
    axes = np.atleast_1d(axes)
    set_page_title(fig, header, "Differential Photometry")

    ax = axes[0]
    if len(jd):
        plot_series(ax, jd - jd_min, avg, err, bad, PANEL_COLORS[0],
                    f"Average of {len(used)} refs (weighted)",
                    args.markersize, ylim)
        # Annotate the number of references used per point when it varies.
        if len(set(n_refs)) > 1:
            for x, y, n in zip(jd - jd_min, avg, n_refs):
                ax.annotate(str(int(n)), (x, y), fontsize=5,
                            textcoords='offset points', xytext=(0, 5),
                            ha='center', alpha=0.6)
        if args.trend is not None and np.sum(~bad) > args.trend + 1:
            g = ~bad
            coeffs = np.polyfit(jd[g] - jd_min, avg[g], args.trend,
                                w=1.0 / np.maximum(err[g], 1e-6))
            xs = np.linspace((jd - jd_min).min(), (jd - jd_min).max(), 200)
            ax.plot(xs, np.polyval(coeffs, xs), '-', color='k',
                    alpha=0.5, lw=1.2, label=f'trend (deg {args.trend})')
            ax.legend(fontsize=7, loc='upper right')
    else:
        ax.text(0.5, 0.5, 'No valid data for averaged references',
                transform=ax.transAxes, ha='center')
    title = "Target \u2212 weighted avg of references"
    if rejected:
        title += f"  (rejected unstable: {', '.join(f'Std{n}' for n in rejected)})"
    ax.set_ylabel("Diff. mag")
    ax.set_title(title, fontsize=9)

    for k, n in enumerate(std_nums):
        ax = axes[k + 1]
        jd_n, diff, derr, bad_n = differential_for_reference(df, n)
        if len(jd_n):
            label = f"Std {n}" + (" [rejected from avg]" if n in rejected else "")
            plot_series(ax, jd_n - jd_min, diff, derr, bad_n,
                        PANEL_COLORS[(k + 1) % len(PANEL_COLORS)],
                        label, args.markersize, ylim)
        else:
            ax.text(0.5, 0.5, f'No valid data for Standard {n}',
                    transform=ax.transAxes, ha='center')
        ax.set_ylabel(f"Target \u2212 Std{n}\n(mag)")

    axes[-1].set_xlabel(f"JD \u2212 {jd_min:.1f} (days)")
    fig.tight_layout(rect=[0, 0, 1, 0.945])
    pdf.savefig(fig)
    plt.close(fig)
    return jd, avg, err, bad, used, rejected


def page_instrumental(pdf, df, std_nums, args, header, jd_min, verbose=False):
    """Page 2: raw instrumental magnitudes for target and each reference."""
    n_panels = 1 + len(std_nums)
    fig, axes = plt.subplots(n_panels, 1, figsize=args.figsize, sharex=True)
    axes = np.atleast_1d(axes)
    set_page_title(fig, header, "Instrumental Magnitudes")

    bad_rows = quality_mask(df)
    series = [('Target', 'target_inst_mag', 'target_inst_mag_err', 'target_snr')]
    series += [(f'Standard {n}', f'std{n}_inst_mag',
                f'std{n}_inst_mag_err', f'std{n}_snr') for n in std_nums]

    for k, (label, mcol, ecol, scol) in enumerate(series):
        ax = axes[k]
        valid = np.isfinite(df['jd']) & np.isfinite(df[mcol])
        if np.any(valid):
            jd = df.loc[valid, 'jd'].values - jd_min
            mags = df.loc[valid, mcol].values
            errs = df.loc[valid, ecol].values if ecol in df.columns \
                else np.full(len(jd), np.nan)
            if scol in df.columns:
                snr = df.loc[valid, scol].values
                fallback = 1.0857 / np.where(snr > 0, snr, 100.0)
                errs = np.where(np.isfinite(errs) & (errs > 1e-4), errs, fallback)
            bad = bad_rows[valid.values] if k == 0 else np.zeros(len(jd), bool)
            plot_series(ax, jd, mags, errs, bad,
                        PANEL_COLORS[k % len(PANEL_COLORS)],
                        label, args.markersize)
        else:
            ax.text(0.5, 0.5, f'No valid data for {label}',
                    transform=ax.transAxes, ha='center')
        ax.set_ylabel(f"{label}\nInst. Mag")

    axes[-1].set_xlabel(f"JD \u2212 {jd_min:.1f} (days)")
    fig.tight_layout(rect=[0, 0, 1, 0.945])
    pdf.savefig(fig)
    plt.close(fig)


def page_calibrated(pdf, df, args, header, jd_min, ylim):
    """
    Page 3 (when zero points are available): calibrated target light curve
    using PhotoCalib catalog zero points, plus the zero points themselves.
    """
    if 'target_calib_mag' not in df.columns:
        return None
    valid = (np.isfinite(df['jd']) & np.isfinite(df['target_calib_mag']))
    if not np.any(valid):
        return None

    jd = df.loc[valid, 'jd'].values - jd_min
    mags = df.loc[valid, 'target_calib_mag'].values
    errs = df.loc[valid, 'target_calib_mag_err'].values \
        if 'target_calib_mag_err' in df.columns else np.full(len(jd), 0.01)
    errs = np.where(np.isfinite(errs) & (errs > 0), errs, 0.01)
    bad = quality_mask(df)[valid.values]

    fig, axes = plt.subplots(2, 1, figsize=(args.figsize[0],
                                            args.figsize[1] * 0.7),
                             sharex=True,
                             gridspec_kw={'height_ratios': [2.2, 1]})
    set_page_title(fig, header, "Calibrated Photometry")

    plot_series(axes[0], jd, mags, errs, bad, 'darkgreen',
                'Target calibrated magnitude', args.markersize, ylim=None)
    filt = str(df['filter'].iloc[0]) if 'filter' in df.columns else ''
    axes[0].set_ylabel(f"Calibrated mag ({filt})")
    n_zp = int(df['zp_nstars'].max()) if 'zp_nstars' in df.columns else 0
    catalogs = set()
    for col in df.columns:
        if col.endswith('_catalog'):
            catalogs.update(c for c in df[col].dropna().astype(str).unique()
                            if c and c != 'nan')
    axes[0].set_title(f"Zero points from {n_zp} catalog reference star(s)"
                      + (f" [{', '.join(sorted(catalogs))}]" if catalogs else ""),
                      fontsize=9)

    if 'zp' in df.columns:
        zp_valid = valid & np.isfinite(df['zp'])
        zjd = df.loc[zp_valid, 'jd'].values - jd_min
        zp = df.loc[zp_valid, 'zp'].values
        zerr = df.loc[zp_valid, 'zp_err'].values \
            if 'zp_err' in df.columns else np.zeros(len(zjd))
        axes[1].errorbar(zjd, zp, yerr=np.nan_to_num(zerr), fmt='s',
                         color='gray', markersize=args.markersize / 2.2,
                         capsize=2)
        if len(zp) > 1:
            axes[1].axhline(np.mean(zp), ls='--', color='gray', alpha=0.6)
            axes[1].text(0.02, 0.9,
                         f"mean ZP={np.mean(zp):.3f}, scatter={np.std(zp):.3f}",
                         transform=axes[1].transAxes, fontsize=8, va='top')
        axes[1].set_ylabel("Zero point\n(mag)")
        axes[1].grid(alpha=0.3)

    axes[-1].set_xlabel(f"JD \u2212 {jd_min:.1f} (days)")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    pdf.savefig(fig)
    plt.close(fig)
    return mags, errs, bad


def page_zoom(pdf, df, args, header, jd_min, avg_result):
    """
    Final page: the light curve zoomed to median +/- zoom_precision mag.

    Auto-scaled pages let a single bad point dominate the y-axis; this
    page pins the range around the median so the genuine variation is
    visible. The calibrated magnitudes are used when PhotoCalib provided
    zero points; otherwise the averaged-reference differential curve is
    shown the same way.
    """
    prec = args.zoom_precision
    have_calib = ('target_calib_mag' in df.columns
                  and np.any(np.isfinite(df['target_calib_mag'])))

    if have_calib:
        valid = np.isfinite(df['jd']) & np.isfinite(df['target_calib_mag'])
        jd = df.loc[valid, 'jd'].values - jd_min
        mags = df.loc[valid, 'target_calib_mag'].values
        errs = df.loc[valid, 'target_calib_mag_err'].values \
            if 'target_calib_mag_err' in df.columns \
            else np.full(len(jd), 0.01)
        errs = np.where(np.isfinite(errs) & (errs > 0), errs, 0.01)
        bad = quality_mask(df)[valid.values]
        ylabel = "Calibrated mag"
        kind = "calibrated magnitude"
    elif avg_result is not None and len(avg_result[0]):
        jd, mags, errs, bad = avg_result[:4]
        ylabel = "Diff. mag (target \u2212 refs)"
        kind = "differential magnitude (no calibration available)"
    else:
        return

    good = ~bad & np.isfinite(mags)
    if not np.any(good):
        return
    med = float(np.median(mags[good]))

    fig, ax = plt.subplots(1, 1, figsize=(args.figsize[0],
                                          args.figsize[1] * 0.55))
    set_page_title(fig, header,
                   f"Zoomed Light Curve  (median {med:.3f} \u00b1 "
                   f"{prec:g} mag, {kind})")
    plot_series(ax, jd, mags, errs, bad, 'darkblue',
                'Target', args.markersize)
    ax.axhline(med, ls=':', color='k', alpha=0.5, lw=1)
    ax.set_ylim(med + prec, med - prec)  # inverted magnitude axis
    n_outside = int(np.sum(good & (np.abs(mags - med) > prec)))
    if n_outside:
        ax.text(0.98, 0.03, f"{n_outside} point(s) outside this range",
                transform=ax.transAxes, ha='right', fontsize=8,
                color='#a00')
    ax.set_ylabel(ylabel)
    ax.set_xlabel(f"JD \u2212 {jd_min:.1f} (days)")
    fig.tight_layout(rect=[0, 0, 1, 0.88])
    pdf.savefig(fig)
    plt.close(fig)


# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------

def print_summary(df, std_nums, avg_result, calib_result, used, rejected,
                  verbose=False):
    """Printed summary table of the run."""
    bad_rows = quality_mask(df)
    n_total = len(df)
    valid_target = np.isfinite(df['target_inst_mag']) & np.isfinite(df['jd'])
    n_usable = int(np.sum(valid_target & ~bad_rows))
    n_rejected = n_total - n_usable

    print("\n" + "=" * 64)
    print("LIGHT CURVE SUMMARY")
    print("=" * 64)
    if 'object' in df.columns:
        vals = [str(v).strip() for v in df['object'].dropna().astype(str)
                if str(v).strip() and str(v).strip().lower() != 'nan']
        if vals:
            print(f"Target:                        {vals[0]}")
    print(f"Images in CSV:                 {n_total}")
    print(f"Usable measurements:           {n_usable}")
    print(f"Rejected/flagged measurements: {n_rejected}")

    inst = df.loc[valid_target & ~bad_rows, 'target_inst_mag'].values
    if len(inst):
        print(f"Target mean instrumental mag:  {np.mean(inst):.3f} "
              f"(RMS {np.std(inst):.3f})")

    jd, avg, err, bad, *_ = (*avg_result,) if avg_result else (None,) * 4
    if avg_result and len(avg_result[0]):
        jd, avg, err, bad = avg_result[:4]
        mean, rms, chi2, n = series_stats(avg, err, bad)
        print(f"Differential (avg refs):       mean={mean:.3f}, RMS={rms:.3f}, "
              f"\u03c7\u00b2/dof={chi2:.2f} ({n} pts)")

    if calib_result is not None:
        cmags, cerrs, cbad = calib_result
        mean, rms, _, n = series_stats(cmags, cerrs, cbad)
        filt = str(df['filter'].iloc[0]) if 'filter' in df.columns else ''
        print(f"Target mean calibrated mag:    {mean:.3f} {filt} "
              f"(RMS {rms:.3f}, {n} pts)")
    else:
        print("Calibrated magnitudes:         not available "
              "(run PhotoCalib with --catalog)")

    ref_desc = ', '.join(f"Std{n}" for n in used)
    print(f"Reference stars used:          {ref_desc or 'none'}")
    if rejected:
        print(f"References rejected (unstable): "
              f"{', '.join(f'Std{n}' for n in rejected)}")

    if verbose:
        print("\nPer-reference differential statistics:")
        for n in std_nums:
            jd_n, diff, derr, bad_n = differential_for_reference(df, n)
            if len(jd_n):
                mean, rms, chi2, npts = series_stats(diff, derr, bad_n)
                note = "  [rejected]" if n in rejected else ""
                print(f"  Std{n}: N={npts}, mean={mean:.3f}, RMS={rms:.3f}, "
                      f"\u03c7\u00b2/dof={chi2:.2f}{note}")
    print("=" * 64)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def create_plots(args):
    df = pd.read_csv(args.csv_file)
    for col in df.columns:
        if col not in ('filename', 'filter', 'error', 'quality_flags',
                       'object') \
                and not col.endswith('_catalog') and df[col].dtype == object:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    std_nums = detect_reference_stars(df)
    if not std_nums:
        print("Error: no reference star columns (stdN_inst_mag) found in CSV.")
        sys.exit(1)
    if 'jd' not in df.columns or not np.any(np.isfinite(df['jd'])):
        print("Error: no valid Julian dates in CSV.")
        sys.exit(1)

    jd_min = np.floor(np.nanmin(df['jd']) * 10) / 10
    ylim = None
    if args.ymin is not None and args.ymax is not None:
        ylim = (args.ymin, args.ymax)
    elif args.ylim is not None:
        ylim = tuple(args.ylim)

    # Header text: the target's name leads when PhotoCalib recorded one,
    # followed by coordinates and filter.
    obj = ''
    if 'object' in df.columns:
        vals = [str(v).strip() for v in df['object'].dropna().astype(str)
                if str(v).strip() and str(v).strip().lower() != 'nan']
        if vals:
            obj = vals[0]
    parts = []
    if 'target_ra' in df.columns and np.isfinite(df['target_ra'].iloc[0]):
        parts.append(f"RA={df['target_ra'].iloc[0]:.4f}\u00b0, "
                     f"Dec={df['target_dec'].iloc[0]:.4f}\u00b0")
    if 'filter' in df.columns:
        parts.append(f"({df['filter'].iloc[0]} filter)")
    detail = ' '.join(parts)
    if args.title:
        header = (args.title, detail)
    elif obj:
        header = (obj, detail)
    else:
        header = (detail or os.path.basename(args.csv_file), '')

    output = args.output or os.path.splitext(args.csv_file)[0] + '_lightcurve.pdf'

    print(f"Read {len(df)} rows, {len(std_nums)} reference stars "
          f"({', '.join(f'Std{n}' for n in std_nums)})")

    if output.lower().endswith('.pdf'):
        with PdfPages(output) as pdf:
            avg_result = page_differential(pdf, df, std_nums, args, header,
                                           jd_min, ylim)
            page_instrumental(pdf, df, std_nums, args, header, jd_min)
            calib_result = page_calibrated(pdf, df, args, header, jd_min, ylim)
            page_zoom(pdf, df, args, header, jd_min, avg_result)
    else:
        # Non-PDF output: save the differential page only.
        class _OnePage:
            def __init__(self, path): self.path = path
            def savefig(self, fig): fig.savefig(self.path, dpi=150)
        shim = _OnePage(output)
        avg_result = page_differential(shim, df, std_nums, args, header,
                                       jd_min, ylim)
        calib_result = None

    used = avg_result[4] if avg_result else std_nums
    rejected = avg_result[5] if avg_result else []
    print(f"Saved light curves to {output}")
    print_summary(df, std_nums, avg_result, calib_result, used, rejected,
                  args.verbose)

    if args.show:
        print("Note: --show is unavailable with the non-interactive backend; "
              "open the saved file instead.")


def main():
    args = parse_args()
    if not os.path.exists(args.csv_file):
        print(f"Error: {args.csv_file} not found")
        sys.exit(1)
    try:
        create_plots(args)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
