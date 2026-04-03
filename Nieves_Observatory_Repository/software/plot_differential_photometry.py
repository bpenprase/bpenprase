#!/usr/bin/env python3
"""
Standalone program to plot differential photometry from photcalib output CSV.
Creates a two-page plot:
  Page 1: Raw instrumental magnitudes for target and reference stars
  Page 2: Differential photometry with average and individual references
"""
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import os

def parse_args():
    """Parse command line arguments."""
    p = argparse.ArgumentParser(
        description="Plot differential photometry from photcalib CSV output"
    )
    p.add_argument("csv_file", help="Input CSV file from photcalib pipeline")
    p.add_argument("-o", "--output", help="Output plot filename (default: differential_photometry.pdf)")
    p.add_argument("--title", help="Plot title (default: auto-generated from filename)")
    p.add_argument("--show", action="store_true", help="Display plots interactively")
    p.add_argument("--markersize", type=float, default=8, help="Marker size (default: 8)")
    p.add_argument("--figsize", nargs=2, type=float, default=[12, 10], 
                   help="Figure size in inches (default: 12 10)")
    p.add_argument("--ylim", nargs=2, type=float, help="Y-axis limits for differential plots (deprecated, use --min/--max)")
    p.add_argument("--min", type=float, help="Minimum y-axis value for differential photometry plots")
    p.add_argument("--max", type=float, help="Maximum y-axis value for differential photometry plots")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    return p.parse_args()

def compute_differential_photometry(df, std_num):
    """
    Compute differential photometry for a given standard/reference star.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        The photometry data
    std_num : int
        Standard star number (1, 2, or 3)
    
    Returns:
    --------
    jd : array
        Julian dates (only where both target and standard have valid data)
    diff_mag : array
        Differential magnitude (target - standard)
    diff_mag_err : array
        Uncertainty in differential magnitude (propagated from individual uncertainties)
    global_error : float
        Standard deviation of the differential magnitude (for reference)
    """
    # Get column names for this standard
    std_mag_col = f'std{std_num}_inst_mag'
    std_mag_err_col = f'std{std_num}_inst_mag_err'
    
    # Filter for rows where both target and standard have valid magnitudes
    valid = (np.isfinite(df['target_inst_mag']) & 
             np.isfinite(df[std_mag_col]) & 
             np.isfinite(df['jd']))
    
    if not np.any(valid):
        return np.array([]), np.array([]), np.array([]), np.nan
    
    # Extract valid data
    jd = df.loc[valid, 'jd'].values
    target_mag = df.loc[valid, 'target_inst_mag'].values
    std_mag = df.loc[valid, std_mag_col].values
    
    # Get uncertainties if available
    if 'target_inst_mag_err' in df.columns and std_mag_err_col in df.columns:
        target_mag_err = df.loc[valid, 'target_inst_mag_err'].values
        std_mag_err = df.loc[valid, std_mag_err_col].values
        
        # Replace NaN errors with 0
        target_mag_err = np.nan_to_num(target_mag_err, nan=0.0)
        std_mag_err = np.nan_to_num(std_mag_err, nan=0.0)
        
        # Propagate uncertainties for differential photometry
        # diff = target - std, so error = sqrt(err_target^2 + err_std^2)
        diff_mag_err = np.sqrt(target_mag_err**2 + std_mag_err**2)
        
        # If all errors are 0 or too small, use a default based on SNR
        if np.all(diff_mag_err < 0.001):
            # Estimate from SNR if available
            if 'target_snr' in df.columns:
                target_snr = df.loc[valid, 'target_snr'].values
                # mag_err ≈ 1.0857/SNR
                target_mag_err = 1.0857 / np.where(target_snr > 0, target_snr, 100)
            else:
                target_mag_err = np.full_like(target_mag, 0.01)  # Default 0.01 mag
            
            if f'std{std_num}_snr' in df.columns:
                std_snr = df.loc[valid, f'std{std_num}_snr'].values
                std_mag_err = 1.0857 / np.where(std_snr > 0, std_snr, 100)
            else:
                std_mag_err = np.full_like(std_mag, 0.01)
            
            diff_mag_err = np.sqrt(target_mag_err**2 + std_mag_err**2)
    else:
        # No uncertainty columns available, estimate from scatter
        diff_mag_err = np.full_like(target_mag, np.nan)
    
    # Compute differential magnitude
    diff_mag = target_mag - std_mag
    
    # Compute global error as standard deviation of the differential magnitude
    global_error = np.std(diff_mag) if len(diff_mag) > 1 else 0.0
    
    return jd, diff_mag, diff_mag_err, global_error

def compute_average_differential(df):
    """
    Compute the average differential photometry across all valid reference stars.
    
    Parameters:
    -----------
    df : pandas.DataFrame
        The photometry data
    
    Returns:
    --------
    jd : array
        Julian dates where at least one reference is valid
    avg_diff : array
        Average differential magnitude
    avg_err : array
        Average uncertainty
    n_refs : array
        Number of reference stars used for each point
    global_error : float
        Standard deviation of the average differential
    """
    # Lists to collect all valid points
    all_jd = []
    all_diff = []
    all_err = []
    all_weights = []
    
    # Collect data from all reference stars
    for std_num in [1, 2, 3]:
        jd, diff_mag, diff_mag_err, _ = compute_differential_photometry(df, std_num)
        if len(jd) > 0:
            all_jd.extend(jd)
            all_diff.extend(diff_mag)
            if np.any(np.isfinite(diff_mag_err)):
                all_err.extend(diff_mag_err)
                # Use inverse variance as weight
                weights = 1.0 / (diff_mag_err**2 + 1e-10)
                all_weights.extend(weights)
            else:
                all_err.extend(np.zeros_like(diff_mag))
                all_weights.extend(np.ones_like(diff_mag))
    
    if len(all_jd) == 0:
        return np.array([]), np.array([]), np.array([]), np.array([]), np.nan
    
    # Convert to arrays
    all_jd = np.array(all_jd)
    all_diff = np.array(all_diff)
    all_err = np.array(all_err)
    all_weights = np.array(all_weights)
    
    # Get unique JD values
    unique_jd = np.unique(all_jd)
    avg_diff = np.zeros(len(unique_jd))
    avg_err = np.zeros(len(unique_jd))
    n_refs = np.zeros(len(unique_jd))
    
    # Compute weighted average for each unique JD
    for i, jd_val in enumerate(unique_jd):
        mask = all_jd == jd_val
        diff_at_jd = all_diff[mask]
        err_at_jd = all_err[mask]
        weights_at_jd = all_weights[mask]
        
        if np.sum(weights_at_jd) > 0:
            # Weighted average
            avg_diff[i] = np.average(diff_at_jd, weights=weights_at_jd)
            # Combined error
            avg_err[i] = 1.0 / np.sqrt(np.sum(weights_at_jd))
        else:
            # Simple average if no weights
            avg_diff[i] = np.mean(diff_at_jd)
            avg_err[i] = np.std(diff_at_jd) / np.sqrt(len(diff_at_jd)) if len(diff_at_jd) > 1 else 0.01
        
        n_refs[i] = len(diff_at_jd)
    
    # Global error
    global_error = np.std(avg_diff) if len(avg_diff) > 1 else 0.0
    
    return unique_jd, avg_diff, avg_err, n_refs, global_error

def create_instrumental_magnitude_plot(df, axes, jd_min, markersize=8, verbose=False):
    """
    Create the instrumental magnitude plot (Page 1).
    
    Parameters:
    -----------
    df : pandas.DataFrame
        The photometry data
    axes : matplotlib axes array
        Array of 4 subplot axes
    jd_min : float
        JD offset for relative time
    markersize : float
        Size of plot markers
    verbose : bool
        Print verbose information
    """
    # Colors for each star
    colors = ['black', 'blue', 'green', 'red']
    labels = ['Target', 'Ref 1', 'Ref 2', 'Ref 3']
    
    # Process each star
    for i, ax in enumerate(axes):
        if i == 0:
            # Target star
            mag_col = 'target_inst_mag'
            mag_err_col = 'target_inst_mag_err'
            snr_col = 'target_snr'
        else:
            # Reference stars
            std_num = i
            mag_col = f'std{std_num}_inst_mag'
            mag_err_col = f'std{std_num}_inst_mag_err'
            snr_col = f'std{std_num}_snr'
        
        # Filter for valid data
        valid = np.isfinite(df[mag_col]) & np.isfinite(df['jd'])
        
        if np.any(valid):
            jd = df.loc[valid, 'jd'].values
            mag = df.loc[valid, mag_col].values
            jd_relative = jd - jd_min
            
            # Get errors if available
            if mag_err_col in df.columns:
                mag_err = df.loc[valid, mag_err_col].values
                mag_err = np.nan_to_num(mag_err, nan=0.0)
                
                # If errors are too small, estimate from SNR
                if np.all(mag_err < 0.001) and snr_col in df.columns:
                    snr = df.loc[valid, snr_col].values
                    mag_err = 1.0857 / np.where(snr > 0, snr, 100)
                
                use_errors = np.any(mag_err > 0)
            else:
                mag_err = np.zeros_like(mag)
                use_errors = False
            
            # Calculate statistics
            mean_mag = np.mean(mag)
            std_mag = np.std(mag)
            
            # Plot with or without error bars
            if use_errors:
                ax.errorbar(jd_relative, mag, yerr=mag_err,
                           fmt='o', markersize=markersize,
                           color=colors[i], alpha=0.7,
                           capsize=3, capthick=1,
                           label=f'{labels[i]} (σ={std_mag:.3f} mag)')
            else:
                ax.plot(jd_relative, mag, 'o', markersize=markersize,
                       color=colors[i], alpha=0.7,
                       label=f'{labels[i]} (σ={std_mag:.3f} mag)')
            
            # Add mean line
            ax.axhline(mean_mag, color=colors[i], linestyle='--', alpha=0.5,
                      label=f'Mean = {mean_mag:.3f}')
            
            # Add ±1σ shaded region
            ax.fill_between([jd_relative.min(), jd_relative.max()],
                           [mean_mag - std_mag, mean_mag - std_mag],
                           [mean_mag + std_mag, mean_mag + std_mag],
                           alpha=0.2, color=colors[i])
            
            # Statistics text
            stats_text = f'N={len(jd)}, Mean={mean_mag:.3f}, σ={std_mag:.3f}'
            ax.text(0.02, 0.95, stats_text, transform=ax.transAxes,
                   fontsize=9, verticalalignment='top',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
            
            if verbose:
                print(f"\n{labels[i]}:")
                print(f"  Points: {len(jd)}")
                print(f"  Mean magnitude: {mean_mag:.3f}")
                print(f"  Std deviation: {std_mag:.3f}")
                print(f"  Magnitude range: {mag.min():.3f} to {mag.max():.3f}")
        else:
            # No valid data
            ax.text(0.5, 0.5, f'No valid data for {labels[i]}',
                   transform=ax.transAxes, ha='center', va='center',
                   fontsize=12, color='gray')
        
        # Set labels and formatting
        ax.set_ylabel(f'{labels[i]}\n(mag)', fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', fontsize=9)
        
        # Invert y-axis (brighter = smaller magnitude)
        ax.invert_yaxis()
    
    # Set x-axis label for bottom panel
    axes[-1].set_xlabel(f'JD - {jd_min:.1f} (days)', fontsize=12)

def create_differential_plot(df, axes, jd_min, markersize=8, ylim=None, verbose=False):
    """
    Create the differential photometry plot (Page 2) with 4 panels.
    Panel 1: Average of all references
    Panels 2-4: Individual reference stars
    
    Parameters:
    -----------
    df : pandas.DataFrame
        The photometry data
    axes : matplotlib axes array
        Array of 4 subplot axes
    jd_min : float
        JD offset for relative time
    markersize : float
        Size of plot markers
    ylim : tuple
        Y-axis limits (min, max) or None for auto
    verbose : bool
        Print verbose information
    """
    # Colors for each panel
    colors = ['purple', 'blue', 'green', 'red']
    
    # Panel 1: Average of all reference stars
    ax = axes[0]
    jd, avg_diff, avg_err, n_refs, global_error = compute_average_differential(df)
    
    if len(jd) > 0:
        jd_relative = jd - jd_min
        
        # Check if we have valid errors
        use_errors = np.any(np.isfinite(avg_err)) and np.any(avg_err > 0)
        
        if use_errors:
            ax.errorbar(jd_relative, avg_diff, yerr=avg_err,
                       fmt='o', markersize=markersize,
                       color=colors[0], alpha=0.7,
                       capsize=3, capthick=1,
                       label=f'Average (global σ={global_error:.3f} mag)')
            
            # Weighted mean
            weights = 1.0 / (avg_err**2 + 1e-10)
            weighted_mean = np.average(avg_diff, weights=weights)
            mean_label = f'Weighted mean = {weighted_mean:.3f}'
        else:
            ax.errorbar(jd_relative, avg_diff, yerr=global_error,
                       fmt='o', markersize=markersize,
                       color=colors[0], alpha=0.7,
                       capsize=3, capthick=1,
                       label=f'Average (σ={global_error:.3f} mag)')
            
            weighted_mean = np.mean(avg_diff)
            mean_label = f'Mean = {weighted_mean:.3f}'
        
        # Add mean line
        ax.axhline(weighted_mean, color=colors[0], linestyle='--', alpha=0.5,
                  label=mean_label)
        
        # Add shaded region
        ax.fill_between([jd_relative.min(), jd_relative.max()],
                       [weighted_mean - global_error, weighted_mean - global_error],
                       [weighted_mean + global_error, weighted_mean + global_error],
                       alpha=0.2, color=colors[0])
        
        # Statistics text
        avg_refs_used = np.mean(n_refs)
        rms = np.sqrt(np.mean((avg_diff - weighted_mean)**2))
        
        if use_errors:
            chi2 = np.sum(((avg_diff - weighted_mean) / avg_err)**2)
            chi2_dof = chi2 / (len(avg_diff) - 1) if len(avg_diff) > 1 else np.nan
            stats_text = f'N={len(jd)}, Avg refs used={avg_refs_used:.1f}, RMS={rms:.3f} mag, χ²/dof={chi2_dof:.2f}'
        else:
            stats_text = f'N={len(jd)}, Avg refs used={avg_refs_used:.1f}, RMS={rms:.3f} mag'
        
        ax.text(0.02, 0.95, stats_text, transform=ax.transAxes,
               fontsize=9, verticalalignment='top',
               bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        if verbose:
            print(f"\nAverage Differential:")
            print(f"  Points: {len(jd)}")
            print(f"  Average refs used: {avg_refs_used:.1f}")
            print(f"  Mean differential: {weighted_mean:.3f}")
            print(f"  Global std: {global_error:.3f}")
            print(f"  RMS: {rms:.3f}")
    else:
        ax.text(0.5, 0.5, 'No valid data for average',
               transform=ax.transAxes, ha='center', va='center',
               fontsize=12, color='gray')
    
    ax.set_ylabel('Target - Avg(Refs)\n(mag)', fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=9)
    
    # Set y-axis limits if specified
    if ylim is not None:
        ax.set_ylim(ylim)
    
    ax.invert_yaxis()
    
    # Panels 2-4: Individual reference stars
    for i in range(1, 4):
        ax = axes[i]
        std_num = i
        
        # Compute differential photometry
        jd, diff_mag, diff_mag_err, global_error = compute_differential_photometry(df, std_num)
        
        if len(jd) > 0:
            # Convert to relative days
            jd_relative = jd - jd_min
            
            # Check if we have valid individual errors
            use_individual_errors = np.any(np.isfinite(diff_mag_err)) and np.any(diff_mag_err > 0)
            
            if use_individual_errors:
                # Use individual photometric uncertainties for error bars
                ax.errorbar(jd_relative, diff_mag, yerr=diff_mag_err, 
                           fmt='o', markersize=markersize, 
                           color=colors[i], alpha=0.7,
                           capsize=3, capthick=1,
                           label=f'Ref {std_num} (global σ={global_error:.3f} mag)')
                
                # Calculate weighted mean if errors are available
                weights = 1.0 / (diff_mag_err**2 + 1e-10)
                weighted_mean = np.average(diff_mag, weights=weights)
                mean_label = f'Weighted mean = {weighted_mean:.3f}'
            else:
                # Fall back to using global standard deviation
                ax.errorbar(jd_relative, diff_mag, yerr=global_error, 
                           fmt='o', markersize=markersize, 
                           color=colors[i], alpha=0.7,
                           capsize=3, capthick=1,
                           label=f'Ref {std_num} (σ={global_error:.3f} mag)')
                
                weighted_mean = np.mean(diff_mag)
                mean_label = f'Mean = {weighted_mean:.3f}'
            
            # Add horizontal line at mean
            ax.axhline(weighted_mean, color=colors[i], linestyle='--', alpha=0.5,
                      label=mean_label)
            
            # Add shaded region for ±1σ (using global error for consistency)
            ax.fill_between([jd_relative.min(), jd_relative.max()], 
                           [weighted_mean - global_error, weighted_mean - global_error],
                           [weighted_mean + global_error, weighted_mean + global_error],
                           alpha=0.2, color=colors[i])
            
            # Statistics text
            rms = np.sqrt(np.mean((diff_mag - weighted_mean)**2))
            chi2_dof = np.nan
            if use_individual_errors:
                # Calculate reduced chi-squared if we have individual errors
                chi2 = np.sum(((diff_mag - weighted_mean) / diff_mag_err)**2)
                chi2_dof = chi2 / (len(diff_mag) - 1) if len(diff_mag) > 1 else np.nan
                stats_text = f'N={len(jd)}, RMS={rms:.3f} mag, χ²/dof={chi2_dof:.2f}'
            else:
                stats_text = f'N={len(jd)}, RMS={rms:.3f} mag'
            
            ax.text(0.02, 0.95, stats_text, transform=ax.transAxes,
                   fontsize=9, verticalalignment='top',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
            
            if verbose:
                print(f"\nReference {std_num} differential:")
                print(f"  Points with valid data: {len(jd)}")
                print(f"  Mean differential mag: {weighted_mean:.3f}")
                print(f"  Global std dev: {global_error:.3f}")
                if use_individual_errors:
                    print(f"  Mean individual error: {np.mean(diff_mag_err):.3f}")
                    print(f"  Reduced χ²: {chi2_dof:.2f}")
                print(f"  RMS: {rms:.3f}")
        else:
            # No valid data for this standard
            ax.text(0.5, 0.5, f'No valid data for Reference {std_num}',
                   transform=ax.transAxes, ha='center', va='center',
                   fontsize=12, color='gray')
            if verbose:
                print(f"\nReference {std_num}: No valid data")
        
        # Set labels and formatting
        ax.set_ylabel(f'Target - Ref{std_num}\n(mag)', fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', fontsize=9)
        
        # Set y-axis limits if specified
        if ylim is not None:
            ax.set_ylim(ylim)
        
        # Invert y-axis (brighter = smaller magnitude)
        ax.invert_yaxis()
    
    # Set x-axis label for bottom panel
    axes[-1].set_xlabel(f'JD - {jd_min:.1f} (days)', fontsize=12)

def create_plots(csv_file, output_file=None, title=None, 
                markersize=8, figsize=(12, 10), ylim=None,
                show=False, verbose=False):
    """
    Create both the instrumental magnitude and differential photometry plots.
    
    Parameters:
    -----------
    csv_file : str
        Path to input CSV file
    output_file : str
        Path to output plot file
    title : str
        Main plot title
    markersize : float
        Size of plot markers
    figsize : tuple
        Figure size (width, height) in inches
    ylim : tuple
        Y-axis limits (min, max) for differential plots
    show : bool
        Whether to display plots interactively
    verbose : bool
        Print verbose information
    """
    # Read the CSV file
    if verbose:
        print(f"Reading CSV file: {csv_file}")
    
    df = pd.read_csv(csv_file)
    
    if verbose:
        print(f"  Found {len(df)} images")
        print(f"  JD range: {df['jd'].min():.5f} to {df['jd'].max():.5f}")
        print(f"  Filter: {df['filter'].iloc[0]}")
    
    # Set main title if not provided
    if title is None:
        target_ra = df['target_ra'].iloc[0]
        target_dec = df['target_dec'].iloc[0]
        filter_name = df['filter'].iloc[0]
        title = f"Photometry: RA={target_ra:.4f}°, Dec={target_dec:.4f}° ({filter_name} filter)"
    
    # Find JD range for relative time conversion
    all_valid_jd = []
    
    # Check target
    valid = np.isfinite(df['target_inst_mag']) & np.isfinite(df['jd'])
    if np.any(valid):
        all_valid_jd.extend(df.loc[valid, 'jd'].values)
    
    # Check reference stars
    for std_num in [1, 2, 3]:
        std_mag_col = f'std{std_num}_inst_mag'
        valid = np.isfinite(df[std_mag_col]) & np.isfinite(df['jd'])
        if np.any(valid):
            all_valid_jd.extend(df.loc[valid, 'jd'].values)
    
    # Determine JD offset for relative days
    if all_valid_jd:
        jd_min = min(all_valid_jd)
    else:
        jd_min = df['jd'].min() if np.any(np.isfinite(df['jd'])) else 0
    
    if verbose:
        print(f"JD offset for relative time: {jd_min:.5f}")
        if ylim is not None:
            print(f"Y-axis limits for differential plots: {ylim[0]:.3f} to {ylim[1]:.3f}")
    
    # Create figures
    figures = []
    
    # Figure 1: Instrumental magnitudes
    fig1, axes1 = plt.subplots(4, 1, figsize=figsize, sharex=True)
    fig1.suptitle(f"{title}\nInstrumental Magnitudes", fontsize=14, fontweight='bold')
    create_instrumental_magnitude_plot(df, axes1, jd_min, markersize, verbose)
    plt.tight_layout()
    figures.append(fig1)
    
    # Figure 2: Differential photometry (4 panels)
    fig2, axes2 = plt.subplots(4, 1, figsize=figsize, sharex=True)
    fig2.suptitle(f"{title}\nDifferential Photometry", fontsize=14, fontweight='bold')
    create_differential_plot(df, axes2, jd_min, markersize, ylim, verbose)
    plt.tight_layout()
    figures.append(fig2)
    
    # Save or show the plots
    if output_file:
        if verbose:
            print(f"\nSaving plots to: {output_file}")
        
        # Determine format from extension
        ext = os.path.splitext(output_file)[1].lower()
        if ext == '.pdf':
            # Save both figures to a single PDF
            with PdfPages(output_file) as pdf:
                for fig in figures:
                    pdf.savefig(fig, bbox_inches='tight')
                    
                # Add metadata
                d = pdf.infodict()
                d['Title'] = title
                d['Subject'] = 'Differential Photometry Analysis'
                d['Keywords'] = f'Photometry, {df["filter"].iloc[0]} filter'
                d['Creator'] = 'plot_differential_photometry.py'
                
        elif ext in ['.png', '.jpg', '.jpeg']:
            # Save as separate image files
            base = os.path.splitext(output_file)[0]
            figures[0].savefig(f"{base}_instrumental{ext}", format=ext[1:], dpi=150, bbox_inches='tight')
            figures[1].savefig(f"{base}_differential{ext}", format=ext[1:], dpi=150, bbox_inches='tight')
            if verbose:
                print(f"  Saved as {base}_instrumental{ext} and {base}_differential{ext}")
        else:
            # Default to PDF
            with PdfPages(output_file + '.pdf') as pdf:
                for fig in figures:
                    pdf.savefig(fig, bbox_inches='tight')
            if verbose:
                print(f"  Saved as PDF (added .pdf extension)")
    
    if show:
        plt.show()
    else:
        # Close figures if not showing
        for fig in figures:
            plt.close(fig)
    
    # Print summary statistics
    if verbose:
        print("\n" + "="*60)
        print("DIFFERENTIAL PHOTOMETRY SUMMARY")
        print("="*60)
        
        # Target magnitude statistics
        valid_target = df[np.isfinite(df['target_inst_mag'])]
        if len(valid_target) > 0:
            target_mean = valid_target['target_inst_mag'].mean()
            target_std = valid_target['target_inst_mag'].std()
            print(f"\nTarget Instrumental Magnitude:")
            print(f"  Mean: {target_mean:.3f} mag")
            print(f"  Std:  {target_std:.3f} mag")
            print(f"  Min:  {valid_target['target_inst_mag'].min():.3f} mag")
            print(f"  Max:  {valid_target['target_inst_mag'].max():.3f} mag")
        
        # Reference star statistics
        for std_num in [1, 2, 3]:
            std_mag_col = f'std{std_num}_inst_mag'
            valid_std = df[np.isfinite(df[std_mag_col])]
            if len(valid_std) > 0:
                std_mean = valid_std[std_mag_col].mean()
                std_std = valid_std[std_mag_col].std()
                print(f"\nReference {std_num} Instrumental Magnitude:")
                print(f"  Mean: {std_mean:.3f} mag")
                print(f"  Std:  {std_std:.3f} mag")
        
        print("="*60)

def main():
    """Main function."""
    args = parse_args()
    
    # Check if input file exists
    if not os.path.exists(args.csv_file):
        print(f"Error: Input file '{args.csv_file}' not found")
        return 1
    
    # Set default output filename if not provided
    if args.output is None:
        base = os.path.splitext(args.csv_file)[0]
        output_file = base + '_plots.pdf'
    else:
        output_file = args.output
    
    # Handle y-axis limits
    ylim = None
    if args.min is not None and args.max is not None:
        ylim = (args.min, args.max)
    elif args.ylim is not None:
        ylim = args.ylim
        if args.verbose:
            print("Note: --ylim is deprecated, please use --min and --max instead")
    
    # Create the plots
    create_plots(
        args.csv_file,
        output_file=output_file,
        title=args.title,
        markersize=args.markersize,
        figsize=args.figsize,
        ylim=ylim,
        show=args.show,
        verbose=args.verbose
    )
    
    if not args.show:
        print(f"Plots saved to: {output_file}")
    
    return 0

if __name__ == "__main__":
    exit(main())