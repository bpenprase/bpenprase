#!/usr/bin/env python3
"""
NSUT RGB Image Generator — build color images from three FITS frames.

Choose one FITS image for each of the red, green, and blue channels,
pick an alignment mode, and press "Load & align". A color preview
appears, and each channel has brightness and contrast sliders that
update the preview live:

  * brightness sets which data level appears as middle gray on screen
    (higher = brighter image), expressed relative to each channel's own
    sky background;
  * contrast sets how tightly data values are mapped around that level
    (higher = punchier, narrower range).

Alignment modes:

  * none            channels are used as-is (must already be registered)
  * shift           star-matched translation onto the red frame
  * shift + rotate  star-matched rigid transform (translation + rotation)
  * WCS             alignment from the images' own plate solutions; this
                    also handles different pixel scales / binnings

The star-matched modes reuse the alignment engine from
fits-image-combiner.py, which must sit in the same directory as this
program (as in the standard NSUT installation).

When the result looks right, choose an output directory, format (PNG,
JPG, or TIFF), optionally a filename, and press "Save image". If the
filename is left blank, it is built from the red image's name plus the
alignment mode and ".rgb", e.g.  m31_r.shift.rotate.rgb.png

Requires: numpy, astropy, scipy, matplotlib, photutils, tkinter, and
Pillow (pip install pillow) for JPG/TIFF output.
"""

import importlib.util
import os
import queue
import re
import sys
import threading
import warnings

import numpy as np

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
from scipy.ndimage import affine_transform, shift as scipy_shift

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
COMBINER_PATH = os.path.join(HERE, "fits-image-combiner.py")

ALIGN_MODES = ["none", "shift", "shift + rotate", "WCS"]
FORMATS = ["PNG", "JPG", "TIFF"]
CHANNELS = ["R", "G", "B"]
CHANNEL_COLORS = {"R": "#c0392b", "G": "#27ae60", "B": "#2980b9"}

ALIGN_SUFFIX = {"none": "", "shift": ".shift",
                "shift + rotate": ".shift.rotate", "WCS": ".wcs"}


def load_combiner():
    """Import the alignment engine from fits-image-combiner.py."""
    if not os.path.exists(COMBINER_PATH):
        return None
    spec = importlib.util.spec_from_file_location("nsut_combiner",
                                                  COMBINER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_first_image(path):
    """Load the first 2D image HDU and its header from a FITS file."""
    with fits.open(path) as hdul:
        for hdu in hdul:
            if hasattr(hdu, 'data') and isinstance(hdu.data, np.ndarray) \
                    and hdu.data.ndim == 2:
                return hdu.data.astype(np.float32), hdu.header
    raise ValueError(f"No 2D image found in {os.path.basename(path)}")


def channel_stats(data):
    """Robust sky median and noise for one channel (subsampled)."""
    flat = data.ravel()
    if flat.size > 1_000_000:
        flat = flat[:: flat.size // 1_000_000]
    nz = flat[flat != 0]
    if len(nz) > 1000:
        flat = nz
    _, med, std = sigma_clipped_stats(flat, sigma=3.0, maxiters=5)
    if not np.isfinite(std) or std <= 0:
        std = max(1.0, float(np.std(flat)))
    return float(med), float(std)


def stretch(data, median, std, brightness, contrast):
    """
    Map data values to display values in [0, 1].

    The level shown as middle gray is  median + std*(60 - brightness)*0.4
    (so the slider moves it in units of the sky noise), and the full
    black-to-white range spans  std * 10**((100 - contrast)/40)  around
    it. Defaults of 50/50 give a dark sky with bright stars saturating.
    """
    center = median + std * (60.0 - brightness) * 0.4
    width = std * 10.0 ** ((100.0 - contrast) / 40.0)
    return np.clip(0.5 + (data - center) / width, 0.0, 1.0)


def wcs_affine(ref_header, ch_header, ref_shape):
    """
    Affine transform mapping reference-grid pixels to channel pixels,
    fitted from the two WCS solutions over a grid of control points.

    Returns (A, b) with p_channel ~= A @ p_ref + b in (x, y) pixels.
    TAN-projected frames of the same field are affine to excellent
    accuracy, and the fit absorbs scale differences (binning), rotation,
    and offset all at once.
    """
    ref_wcs = WCS(ref_header)
    ch_wcs = WCS(ch_header)
    ny, nx = ref_shape
    gx, gy = np.meshgrid(np.linspace(0, nx - 1, 5),
                         np.linspace(0, ny - 1, 5))
    pts_ref = np.column_stack([gx.ravel(), gy.ravel()])
    sky = ref_wcs.pixel_to_world(pts_ref[:, 0], pts_ref[:, 1])
    cx, cy = ch_wcs.world_to_pixel(sky)
    pts_ch = np.column_stack([cx, cy])
    if not np.all(np.isfinite(pts_ch)):
        raise ValueError("WCS conversion produced invalid pixel positions; "
                         "check that both images have valid plate "
                         "solutions.")
    # Least-squares affine: [x_ref, y_ref, 1] @ M = [x_ch, y_ch]
    design = np.column_stack([pts_ref, np.ones(len(pts_ref))])
    M, *_ = np.linalg.lstsq(design, pts_ch, rcond=None)
    A = M[:2].T            # 2x2
    b = M[2]               # offset
    resid = pts_ch - (design @ M)
    rms = float(np.sqrt(np.mean(np.sum(resid**2, axis=1))))
    if rms > 1.0:
        print(f"  WCS affine fit residual {rms:.2f} px (distortion or "
              f"inconsistent solutions); alignment may be imperfect.")
    return A, b


def resample_affine(data, A, b, out_shape, order=2):
    """
    Resample a channel onto the reference grid given p_ch = A @ p_ref + b.

    scipy's affine_transform works in (row, col) order with
    input = M @ output + offset, so the axes are swapped with P.
    """
    P = np.array([[0.0, 1.0], [1.0, 0.0]])
    M = P @ A @ P
    offset = P @ b
    return affine_transform(data, M, offset=offset, order=order,
                            output_shape=out_shape, mode='constant',
                            cval=0.0)


def sanitize_stem(name):
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = stem.replace("'", "p").replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9._+-]", "", stem) or "image"


# ----------------------------------------------------------------------
# The application
# ----------------------------------------------------------------------

class RGBGui(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("NSUT RGB Image Generator")
        self.geometry("1180x720")
        self.minsize(960, 600)
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self.comb = load_combiner()
        self.q = queue.Queue()
        self.worker = None
        self.aligned = None        # dict R/G/B -> full-res aligned array
        self.preview = None        # dict R/G/B -> downsampled array
        self.stats = None          # dict R/G/B -> (median, std)
        self.align_used = "none"

        self._build_controls()
        self._build_preview()
        if self.comb is None:
            messagebox.showwarning(
                "Combiner not found",
                "fits-image-combiner.py was not found next to this "
                "program. The 'shift' and 'shift + rotate' alignment "
                "modes will be unavailable; 'WCS' and 'none' still work.")
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------

    def _build_controls(self):
        panel = ttk.Frame(self, padding=10)
        panel.pack(side="left", fill="y")

        ttk.Label(panel, text="RGB Image Generator",
                  font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Pick three FITS images, align, adjust, save.",
                  foreground="#555").pack(anchor="w", pady=(0, 8))

        def row(label, color=None):
            f = ttk.Frame(panel)
            f.pack(fill="x", pady=2)
            lbl = tk.Label(f, text=label, width=15, anchor="w",
                           fg=color or "black")
            lbl.pack(side="left")
            return f

        # Channel file pickers
        self.file_vars = {}
        for ch, label in zip(CHANNELS, ["Red image", "Green image",
                                        "Blue image"]):
            var = tk.StringVar()
            self.file_vars[ch] = var
            f = row(label, CHANNEL_COLORS[ch])
            ttk.Entry(f, textvariable=var, width=26).pack(
                side="left", fill="x", expand=True)
            ttk.Button(f, text="Browse…", width=9,
                       command=lambda v=var: self._browse_fits(v)).pack(
                side="left")

        # Alignment mode
        self.align_var = tk.StringVar(value="shift + rotate")
        f = row("Alignment")
        ttk.Combobox(f, textvariable=self.align_var, values=ALIGN_MODES,
                     state="readonly", width=14).pack(side="left")

        self.load_btn = ttk.Button(panel, text="Load && align channels",
                                   command=self.load_and_align)
        self.load_btn.pack(fill="x", pady=(8, 4))
        self.progress = ttk.Progressbar(panel, mode="indeterminate")
        self.progress.pack(fill="x")
        self.status_var = tk.StringVar(value="Choose three images.")
        ttk.Label(panel, textvariable=self.status_var, wraplength=300,
                  foreground="#333").pack(anchor="w", pady=(4, 6))

        ttk.Separator(panel).pack(fill="x", pady=4)

        # Brightness / contrast sliders per channel
        self.sliders = {}
        for ch in CHANNELS:
            grp = ttk.LabelFrame(panel, text=f"  {ch} channel  ", padding=4)
            grp.pack(fill="x", pady=3)
            self.sliders[ch] = {}
            for kind in ("brightness", "contrast"):
                f = ttk.Frame(grp)
                f.pack(fill="x")
                ttk.Label(f, text=kind.capitalize(), width=10,
                          anchor="w").pack(side="left")
                var = tk.DoubleVar(value=50.0)
                s = ttk.Scale(f, from_=0, to=100, variable=var,
                              command=lambda _v: self._update_preview())
                s.pack(side="left", fill="x", expand=True)
                self.sliders[ch][kind] = var

        ttk.Separator(panel).pack(fill="x", pady=4)

        # Output controls
        self.outdir_var = tk.StringVar()
        f = row("Output directory")
        ttk.Entry(f, textvariable=self.outdir_var, width=26).pack(
            side="left", fill="x", expand=True)
        ttk.Button(f, text="Browse…", width=9,
                   command=lambda: self._browse_dir(self.outdir_var)).pack(
            side="left")

        self.format_var = tk.StringVar(value="PNG")
        f = row("Format")
        ttk.Combobox(f, textvariable=self.format_var, values=FORMATS,
                     state="readonly", width=8).pack(side="left")

        self.name_var = tk.StringVar()
        f = row("Filename")
        ttk.Entry(f, textvariable=self.name_var, width=26).pack(
            side="left", fill="x", expand=True)
        ttk.Label(f, text=" optional", foreground="#777").pack(side="left")

        self.save_btn = ttk.Button(panel, text="Save image",
                                   command=self.save_image,
                                   state="disabled")
        self.save_btn.pack(fill="x", pady=(8, 0))

    def _build_preview(self):
        frame = ttk.Frame(self)
        frame.pack(side="left", fill="both", expand=True, padx=(0, 6),
                   pady=6)
        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        ax = self.fig.add_subplot(111)
        ax.text(0.5, 0.5, "Load three channels to see a preview.",
                ha="center", va="center", color="#888")
        ax.set_axis_off()
        self.canvas.draw_idle()
        self._image_artist = None

    # ------------------------------------------------------------------

    def _browse_fits(self, var):
        path = filedialog.askopenfilename(
            filetypes=[("FITS files", "*.fits *.fit *.fts"),
                       ("All files", "*.*")])
        if path:
            var.set(path)

    def _browse_dir(self, var):
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    # ------------------------------------------------------------------
    # Loading and alignment (worker thread)
    # ------------------------------------------------------------------

    def load_and_align(self):
        if self.worker and self.worker.is_alive():
            return
        paths = {ch: self.file_vars[ch].get().strip() for ch in CHANNELS}
        missing = [ch for ch, p in paths.items() if not p or
                   not os.path.exists(p)]
        if missing:
            messagebox.showerror(
                "Missing images",
                f"Please choose existing FITS files for: "
                f"{', '.join(missing)}")
            return
        mode = self.align_var.get()
        if mode in ("shift", "shift + rotate") and self.comb is None:
            messagebox.showerror(
                "Alignment unavailable",
                "Star alignment needs fits-image-combiner.py in the same "
                "directory; use WCS or none, or install the combiner.")
            return
        self.load_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Loading and aligning…")
        self.worker = threading.Thread(target=self._align_worker,
                                       args=(paths, mode), daemon=True)
        self.worker.start()

    def _align_worker(self, paths, mode):
        try:
            data, headers = {}, {}
            for ch in CHANNELS:
                self.q.put(("status", f"Loading {ch} channel…"))
                data[ch], headers[ch] = load_first_image(paths[ch])

            ref_shape = data["R"].shape
            aligned = {"R": data["R"]}

            for ch in ("G", "B"):
                self.q.put(("status", f"Aligning {ch} channel ({mode})…"))
                aligned[ch] = self._align_channel(
                    data[ch], headers[ch], data["R"], headers["R"],
                    ref_shape, mode, ch)

            # Common valid region: first equalize shapes, then crop away
            # borders where any resampled channel has no data (blank
            # edges from shifting/rotating would otherwise show up as
            # colored fringes around the picture).
            ny = min(a.shape[0] for a in aligned.values())
            nx = min(a.shape[1] for a in aligned.values())
            for ch in CHANNELS:
                aligned[ch] = np.ascontiguousarray(aligned[ch][:ny, :nx])

            valid = np.ones((ny, nx), dtype=bool)
            for ch in CHANNELS:
                valid &= aligned[ch] != 0
            # Greedy rectangle shrink: peel away any edge row/column that
            # still contains invalid pixels. (Row and column validity are
            # interdependent — a blank stripe on the left makes every row
            # partially invalid — so simple per-axis thresholds cannot
            # find the clean interior rectangle, but this does.)
            r0, r1, c0, c1 = 0, ny, 0, nx
            changed = True
            while changed and r1 - r0 > 0.6 * ny and c1 - c0 > 0.6 * nx:
                changed = False
                if not valid[r0, c0:c1].all():
                    r0 += 1; changed = True
                if r1 > r0 and not valid[r1 - 1, c0:c1].all():
                    r1 -= 1; changed = True
                if not valid[r0:r1, c0].all():
                    c0 += 1; changed = True
                if c1 > c0 and not valid[r0:r1, c1 - 1].all():
                    c1 -= 1; changed = True
            # Guard: keep at least 60% of each dimension (heavily rotated
            # channels would otherwise overcrop).
            if (r1 - r0 > 0.6 * ny and c1 - c0 > 0.6 * nx
                    and ((r1 - r0) < ny or (c1 - c0) < nx)):
                self.q.put(("status",
                            f"Cropping to common coverage "
                            f"({c1 - c0} x {r1 - r0} px)…"))
                for ch in CHANNELS:
                    aligned[ch] = np.ascontiguousarray(
                        aligned[ch][r0:r1, c0:c1])
            ny, nx = aligned["R"].shape

            stats = {ch: channel_stats(aligned[ch]) for ch in CHANNELS}
            step = max(1, max(ny, nx) // 1000)
            preview = {ch: aligned[ch][::step, ::step] for ch in CHANNELS}
            self.q.put(("aligned", (aligned, preview, stats, mode,
                                    paths["R"])))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _align_channel(self, ch_data, ch_header, ref_data, ref_header,
                       ref_shape, mode, ch_name):
        """Bring one channel onto the red frame's pixel grid."""
        if mode == "none":
            return ch_data

        if mode == "WCS":
            A, b = wcs_affine(ref_header, ch_header, ref_shape)
            return resample_affine(ch_data, A, b, ref_shape).astype(
                np.float32)

        # Star-matched modes use the combiner's engine. Different image
        # sizes are reconciled by integer binning when possible.
        comb = self.comb
        work = ch_data
        if work.shape != ref_shape:
            factors = comb.binning_factors(work.shape, ref_shape)
            if factors is None:
                raise ValueError(
                    f"{ch_name} channel shape {work.shape} cannot be "
                    f"integer-binned to the red frame {ref_shape}; use "
                    f"the WCS alignment mode for mixed binnings.")
            work = comb.bin_image(work, factors[0], factors[1],
                                  'mean').astype(np.float32)
            work = work[:ref_shape[0], :ref_shape[1]]

        allow_rot = (mode == "shift + rotate")
        ref_stars, fwhm = comb.find_star_centroids(ref_data, verbose=False)
        ch_stars, _ = comb.find_star_centroids(work, fwhm=fwhm,
                                               verbose=False)
        if len(ref_stars) < 3 or len(ch_stars) < 3:
            raise ValueError(f"Too few stars detected to align the "
                             f"{ch_name} channel; try the WCS mode.")
        result = comb.match_and_measure_shift(
            ref_stars, ch_stars, match_radius=max(3.0, 0.75 * fwhm),
            consensus_tol=max(2.0, 0.5 * fwhm),
            allow_rotation=allow_rot, verbose=False)
        if result is None:
            raise ValueError(f"Could not align the {ch_name} channel to "
                             f"the red frame; try the WCS mode or check "
                             f"that the fields overlap.")
        self.q.put(("status",
                    f"{ch_name}: {result['n_matched']} stars, "
                    f"dx={result['dx']:+.1f}, dy={result['dy']:+.1f}"
                    + (f", rot={result['rot_deg']*60:.1f}'"
                       if abs(result['rot_deg']) > 1e-4 else "")))
        if allow_rot and abs(result['rot_deg']) > 1e-4:
            return comb.apply_rigid_transform(work, result['R'],
                                              result['t']).astype(np.float32)
        return scipy_shift(work, shift=(result['dy'], result['dx']),
                           order=3, mode='constant', cval=0.0).astype(
            np.float32)

    # ------------------------------------------------------------------

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "error":
                    self.progress.stop()
                    self.load_btn.configure(state="normal")
                    self.status_var.set("Failed.")
                    messagebox.showerror("Alignment failed", payload)
                elif kind == "aligned":
                    (self.aligned, self.preview, self.stats,
                     self.align_used, self._red_path) = payload
                    self.progress.stop()
                    self.load_btn.configure(state="normal")
                    self.save_btn.configure(state="normal")
                    self.status_var.set(
                        f"Aligned ({self.align_used}). Adjust sliders, "
                        f"then save.")
                    self._update_preview(force=True)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    # ------------------------------------------------------------------
    # Preview and saving
    # ------------------------------------------------------------------

    def _compose(self, source):
        """Stack the three stretched channels into an RGB array."""
        chans = []
        for ch in CHANNELS:
            med, std = self.stats[ch]
            b = self.sliders[ch]["brightness"].get()
            c = self.sliders[ch]["contrast"].get()
            chans.append(stretch(source[ch], med, std, b, c))
        return np.dstack(chans)

    def _update_preview(self, force=False):
        if self.preview is None:
            return
        rgb = self._compose(self.preview)
        if self._image_artist is None or force:
            self.fig.clear()
            ax = self.fig.add_subplot(111)
            self._image_artist = ax.imshow(rgb, origin="lower",
                                           interpolation="nearest")
            ax.set_xticks([]), ax.set_yticks([])
            ax.set_title("Preview (downsampled)", fontsize=9)
            self.fig.tight_layout()
        else:
            self._image_artist.set_data(rgb)
        self.canvas.draw_idle()

    def default_filename(self):
        stem = sanitize_stem(self._red_path)
        ext = {"PNG": ".png", "JPG": ".jpg",
               "TIFF": ".tiff"}[self.format_var.get()]
        return f"{stem}{ALIGN_SUFFIX[self.align_used]}.rgb{ext}"

    def save_image(self):
        if self.aligned is None:
            return
        outdir = self.outdir_var.get().strip()
        if not outdir or not os.path.isdir(outdir):
            messagebox.showerror("Output directory",
                                 "Please choose an output directory.")
            return
        try:
            from PIL import Image
        except ImportError:
            messagebox.showerror(
                "Pillow required",
                "Saving images requires the Pillow library:\n\n"
                "    pip install pillow")
            return

        name = self.name_var.get().strip()
        ext = {"PNG": ".png", "JPG": ".jpg",
               "TIFF": ".tiff"}[self.format_var.get()]
        if not name:
            name = self.default_filename()
        elif not name.lower().endswith(ext):
            name = os.path.splitext(name)[0] + ext
        path = os.path.join(outdir, name)

        self.status_var.set("Rendering full-resolution image…")
        self.update_idletasks()
        try:
            rgb = self._compose(self.aligned)
            img8 = (np.flipud(rgb) * 255).astype(np.uint8)  # origin lower
            im = Image.fromarray(img8, mode="RGB")
            if ext == ".jpg":
                im.save(path, quality=95)
            else:
                im.save(path)
            self.status_var.set(f"Saved {name} \u2713")
        except Exception as e:
            self.status_var.set("Save failed.")
            messagebox.showerror("Save failed", str(e))


def main():
    app = RGBGui()
    app.mainloop()


if __name__ == "__main__":
    main()
