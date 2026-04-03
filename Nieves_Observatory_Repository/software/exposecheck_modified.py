import argparse
import os
import numpy as np
from astropy.io import fits
import csv

def is_fits_file(filename):
    return filename.lower().endswith(('.fits', '.fit', '.fts'))

def get_central_region(data, region_type='center'):
    """
    Extract a central region from the image data.
    
    Parameters:
    - data: 2D numpy array of image data
    - region_type: 'center' for inner half (1/4 from center in each direction)
                   'target' for inner 1/5 (1/10 from center in each direction)
    """
    h, w = data.shape
    cx, cy = w // 2, h // 2
    
    if region_type == 'center':
        # Inner half: extend by 1/4 of dimension from center
        dx, dy = w // 4, h // 4
    elif region_type == 'target':
        # Inner 1/5: extend by 1/10 of dimension from center
        dx, dy = w // 10, h // 10
    else:
        raise ValueError(f"Unknown region_type: {region_type}")
    
    # Ensure we don't go out of bounds
    x1 = max(0, cx - dx)
    x2 = min(w, cx + dx)
    y1 = max(0, cy - dy)
    y2 = min(h, cy + dy)
    
    return data[y1:y2, x1:x2]

def extract_header_info(header):
    obj = header.get('OBJECT', 'Unknown')
    exptime = header.get('EXPTIME', header.get('EXPOSURE', 'N/A'))
    filt = header.get('FILTER', header.get('FILTNAM', 'N/A'))
    date = header.get('DATE-OBS', 'N/A')
    ut = header.get('UT', header.get('UTSTART', 'N/A'))
    jd = header.get('JD', 'N/A')
    return obj, exptime, filt, date, ut, jd

def process_image(filepath, analysis_mode):
    """
    Process a FITS image to check for saturation.
    
    Parameters:
    - filepath: path to the FITS file
    - analysis_mode: 'all' for entire image, 'center' for inner half, 'target' for inner 1/5
    """
    with fits.open(filepath) as hdul:
        data = hdul[0].data.astype(np.float32)
        header = hdul[0].header

    if data.ndim != 2:
        raise ValueError(f"{filepath} is not a 2D image.")

    if analysis_mode == 'all':
        region = data
    elif analysis_mode == 'center':
        region = get_central_region(data, 'center')
    elif analysis_mode == 'target':
        region = get_central_region(data, 'target')
    else:
        raise ValueError(f"Unknown analysis mode: {analysis_mode}")
    
    saturated = np.sum(region > 65000)
    total = region.size
    mean_val = np.mean(region)
    percent_sat = 100.0 * saturated / total

    obj, exptime, filt, date, ut, jd = extract_header_info(header)
    return [os.path.basename(filepath), obj, exptime, filt, date, ut, jd, saturated, total, percent_sat, mean_val]

def scan_directory(directory, analysis_mode):
    """
    Scan directory for FITS files and analyze them.
    
    Parameters:
    - directory: path to directory containing FITS files
    - analysis_mode: 'all', 'center', or 'target'
    """
    report = []
    header_row = ["Image", "Object", "ExpTime", "Filter", "Date", "UT", "Julian Date", "Saturated", "TotalPix", "% Saturated", "Mean"]
    
    # Print mode being used
    mode_descriptions = {
        'all': 'entire image',
        'center': 'inner half (central 50%)',
        'target': 'inner 1/5 (central 20%)'
    }
    print(f"\nAnalyzing {mode_descriptions[analysis_mode]} of each image\n")
    
    print("{:30} {:20} {:>8} {:>8} {:>10} {:>10} {:>13} {:>10} {:>10} {:>12} {:>10}".format(*header_row))
    print("-" * 150)

    for fname in sorted(os.listdir(directory)):
        if not is_fits_file(fname):
            continue
        try:
            row = process_image(os.path.join(directory, fname), analysis_mode)
            report.append(row)
            print("{:30} {:20} {:>8} {:>8} {:>10} {:>10} {:>13} {:10} {:10} {:12.2f} {:10.2f}".format(
                row[0], row[1], str(row[2]), str(row[3]), str(row[4]), str(row[5]), str(row[6]), row[7], row[8], row[9], row[10]))
        except Exception as e:
            print("{:30} ERROR: {}".format(fname, str(e)))

    # Save CSV with mode suffix
    csv_path = f"{os.path.basename(os.path.normpath(directory))}_{analysis_mode}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header_row)
        writer.writerows(report)
    print(f"\nCSV report saved as: {csv_path}")

def main():
    parser = argparse.ArgumentParser(description="Check for saturated pixels in FITS images.")
    parser.add_argument("directory", help="Directory containing FITS images")
    
    # Create mutually exclusive group for analysis options
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("-all", action="store_true", 
                           help="Analyze entire image")
    mode_group.add_argument("-center", action="store_true", 
                           help="Analyze inner half of image (central 50%)")
    mode_group.add_argument("-target", action="store_true", 
                           help="Analyze inner 1/5 of image (central 20%)")
    
    args = parser.parse_args()
    
    # Determine analysis mode
    if args.all:
        analysis_mode = 'all'
    elif args.center:
        analysis_mode = 'center'
    elif args.target:
        analysis_mode = 'target'
    
    scan_directory(args.directory, analysis_mode)

if __name__ == "__main__":
    main()