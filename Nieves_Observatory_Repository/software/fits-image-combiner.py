import argparse
import os
import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clip, mad_std
from scipy.ndimage import shift as scipy_shift
from photutils.detection import DAOStarFinder
from scipy.spatial import cKDTree

def load_fits_data(filepath):
    with fits.open(filepath) as hdul:
        data = hdul[0].data.astype(np.float32)
        header = hdul[0].header
    return data, header

def save_fits_data(data, header, output_path):
    hdu = fits.PrimaryHDU(data, header=header)
    hdu.writeto(output_path, overwrite=True)

def normalize_flat(flat_data):
    return flat_data / np.median(flat_data)

def subtract_dark(image_data, dark_data):
    return image_data - dark_data

def apply_calibrations(image, dark_data, flat_data):
    if dark_data is not None:
        image = subtract_dark(image, dark_data)
    if flat_data is not None:
        image = image / flat_data
    return image

def find_star_centroids(image, max_stars=20, verbose=True):
    bkg_sigma = mad_std(image)
    daofind = DAOStarFinder(fwhm=3.0, threshold=5. * bkg_sigma)
    sources = daofind(image)
    if sources is None or len(sources) == 0:
        print("No stars found!")
        return np.array([])

    sources.sort('flux')
    brightest = sources[::-1][:max_stars]
    coords = np.array([(row['xcentroid'], row['ycentroid']) for row in brightest])

    if verbose:
        print(f"Detected {len(coords)} stars. Centroids (x, y):")
        for i, (x, y) in enumerate(coords):
            print(f"  Star {i+1}: x={x:.2f}, y={y:.2f}")
    return coords

def match_star_positions(ref_coords, target_coords, max_radius=15.0):
    tree = cKDTree(ref_coords)
    matched_shifts = []

    for i, tc in enumerate(target_coords):
        dist, idx = tree.query(tc, distance_upper_bound=max_radius)
        if dist < max_radius:
            matched_shifts.append(ref_coords[idx] - tc)
            print(f"  Matched Star {i+1}: Ref({ref_coords[idx][0]:.2f},{ref_coords[idx][1]:.2f}) "
                  f"Target({tc[0]:.2f},{tc[1]:.2f}) Shift(dx={ref_coords[idx][0] - tc[0]:.2f}, dy={ref_coords[idx][1] - tc[1]:.2f})")

    return np.array(matched_shifts)

def compute_star_matching_shift(ref_image, target_image):
    print("Finding stars in reference image:")
    ref_stars = find_star_centroids(ref_image)

    print("Finding stars in target image:")
    tgt_stars = find_star_centroids(target_image)

    if len(ref_stars) == 0 or len(tgt_stars) == 0:
        print("Warning: No stars found for alignment.")
        return (0.0, 0.0)

    matched = match_star_positions(ref_stars, tgt_stars)
    if len(matched) == 0:
        print("Warning: No matched stars found.")
        return (0.0, 0.0)

    dx, dy = np.mean(matched, axis=0)
    return dy, dx

def combine_images(image_stack, method="average", sigma=3.0):
    if method == "median":
        return np.median(image_stack, axis=0)
    elif method == "avsigclip":
        clipped = sigma_clip(image_stack, sigma=sigma, axis=0)
        return np.mean(clipped, axis=0).filled(0)
    elif method == "nomax":
        # Remove the maximum value at each pixel position and average the rest
        # Sort along the stack axis (axis=0)
        sorted_stack = np.sort(image_stack, axis=0)
        # Remove the last (maximum) value and compute mean
        # If we have N images, take indices 0 to N-2 (excluding the maximum at N-1)
        if image_stack.shape[0] > 1:
            return np.mean(sorted_stack[:-1], axis=0)
        else:
            # If only one image, just return it
            return image_stack[0]
    else:  # default to average
        return np.mean(image_stack, axis=0)

def normalize_output(image, method="average"):
    """Normalize the output image by dividing by the average or median of all pixels."""
    if method == "median":
        norm_value = np.median(image)
    else:  # average
        norm_value = np.mean(image)
    
    if norm_value != 0:
        return image / norm_value
    else:
        print("Warning: Normalization value is zero, skipping normalization.")
        return image

def process_images(image_dir, dark_path=None, flat_path=None, sigma=3.0, 
                  combine_method="average", noalign=False, normalize=False, output_path="combined_output_star_match_final.fits"):
    dark_data = load_fits_data(dark_path)[0] if dark_path else None
    flat_data = normalize_flat(load_fits_data(flat_path)[0]) if flat_path else None

    image_files = [os.path.join(image_dir, f) for f in sorted(os.listdir(image_dir))
                   if f.lower().endswith(('.fits', '.fts'))]
    image_stack = []

    if not image_files:
        raise ValueError("No valid FITS or FTS images found in directory.")

    # Load reference image
    ref_image, header = load_fits_data(image_files[0])
    ref_image = apply_calibrations(ref_image, dark_data, flat_data)
    image_stack.append(ref_image)

    # Process remaining images
    if noalign:
        print("\nAlignment disabled (--noalign flag set)")
        # Just load and calibrate images without alignment
        for file in image_files[1:]:
            print(f"Loading file: {os.path.basename(file)}")
            img_data, _ = load_fits_data(file)
            img_data = apply_calibrations(img_data, dark_data, flat_data)
            image_stack.append(img_data)
    else:
        # Perform alignment
        for file in image_files[1:]:
            print(f"\nAligning file: {os.path.basename(file)}")
            img_data, _ = load_fits_data(file)
            img_data = apply_calibrations(img_data, dark_data, flat_data)
            shift_vals = compute_star_matching_shift(ref_image, img_data)
            print(f"  Applying shift: dy={shift_vals[0]:.2f}, dx={shift_vals[1]:.2f}")
            shifted_img = scipy_shift(img_data, shift=shift_vals, order=3, mode='constant', cval=0.0)
            image_stack.append(shifted_img)

    # Stack and combine images
    image_stack = np.stack(image_stack)
    print(f"\nCombining {len(image_stack)} images using {combine_method} method...")
    combined = combine_images(image_stack, method=combine_method, sigma=sigma)
    
    # Apply normalization if requested
    if normalize:
        print(f"Normalizing output using {combine_method} of pixel values...")
        combined = normalize_output(combined, method=combine_method)
    
    # Save output
    save_fits_data(combined, header, output_path)
    print(f"Final combined image saved as '{output_path}'")
    
    # Print statistics
    print(f"\nOutput image statistics:")
    print(f"  Min: {np.min(combined):.4f}")
    print(f"  Max: {np.max(combined):.4f}")
    print(f"  Mean: {np.mean(combined):.4f}")
    print(f"  Median: {np.median(combined):.4f}")

def main():
    parser = argparse.ArgumentParser(description="Align and combine FITS images using bright star matching.")
    parser.add_argument("directory", help="Directory containing FITS images")
    parser.add_argument("-dark", help="Dark frame FITS file", default=None)
    parser.add_argument("-flat", help="Flat field FITS file", default=None)
    parser.add_argument("-N", type=float, default=3.0, help="Sigma value for avsigclip (default: 3.0)")
    parser.add_argument("-c", "--combine", choices=["average", "median", "avsigclip", "nomax"], default="average",
                        help="Combination method: average, median, avsigclip, or nomax (average after removing max pixel)")
    parser.add_argument("--noalign", action="store_true", 
                        help="Skip star alignment and just stack images as-is")
    parser.add_argument("--normalize", action="store_true",
                        help="Normalize final image by dividing by average (for -c average) or median (for -c median) of all pixels")
    parser.add_argument("-o", "--output", default="combined_output_star_match_final.fits",
                        help="Output filename for the combined image (default: combined_output_star_match_final.fits)")
    
    args = parser.parse_args()
    process_images(args.directory, 
                  dark_path=args.dark, 
                  flat_path=args.flat, 
                  sigma=args.N, 
                  combine_method=args.combine,
                  noalign=args.noalign,
                  normalize=args.normalize,
                  output_path=args.output)

if __name__ == "__main__":
    main()