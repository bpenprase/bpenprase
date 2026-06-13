#!/usr/bin/env python3
"""
NSUT Control Panel — graphical front end for the Nieves Soka University
Telescope image-processing suite.

This program is a wrapper around the four command-line tools (it never
duplicates their logic, it simply runs them for you):

    exposecheck.py                  image quality / saturation reports
    fits-image-combiner.py          calibration, alignment, stacking
    photcalib_robust_fixed.py       aperture photometry and calibration
    plot_differential_photometry.py light curves

Place this file in the same directory as those four scripts and run:

    python3 nsut_gui.py

Choose the directory holding your science images, pick a filter and a
reduction mode, point the GUI at your darks and flats (either a master
FITS file or a directory of raw frames, in which case a master is built
for you), choose where the products should go, and press Run. Results
appear on the dashboard: a sortable table of image quality for saturation
checks, a zoomable preview of the stacked image, or the differential
light curve for photometry runs. Everything the underlying programs
print is captured in the Log tab, along with the exact commands used,
so the GUI doubles as a way to learn the command-line interface.

Requires: numpy, matplotlib, astropy (all already required by the suite),
plus tkinter, which ships with standard Python installations. On some
Linux systems tkinter is a separate package (e.g. sudo apt install
python3-tk).
"""

import csv
import os
import time
import queue
import re
import subprocess
import sys
import threading
import warnings

import numpy as np

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

warnings.filterwarnings("ignore")

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))

SCRIPTS = {
    "exposecheck": os.path.join(HERE, "exposecheck.py"),
    "combiner": os.path.join(HERE, "fits-image-combiner.py"),
    "photcalib": os.path.join(HERE, "photcalib_robust_fixed.py"),
    "plotter": os.path.join(HERE, "plot_differential_photometry.py"),
}

FILTERS = ["autoselect", "g'", "r'", "i'", "z'", "B", "V", "H-a", "OIII", "SII"]

MODES = [
    "Saturation check",
    "Simple image stacking",
    "Image stacking with flat fielding",
    "Image stacking with flat fielding and dark subtraction",
    "Image stacking with dark subtraction",
    "Differential photometry",
]

COMBINE_METHODS = ["avsigclip", "average", "median", "nomax"]
SAT_REGIONS = ["target", "center", "all"]

FITS_EXTENSIONS = (".fits", ".fit", ".fts")


def filter_tag(filter_name):
    """A filesystem-safe version of the filter name for output filenames."""
    return filter_name.replace("'", "p")


def is_fits_dir(path):
    """True if path is a directory containing at least one FITS file."""
    if not os.path.isdir(path):
        return False
    return any(f.lower().endswith(FITS_EXTENSIONS) for f in os.listdir(path))


def derive_object_name(cfg):
    """The target's name from the first science image's OBJECT/TARGET
    header, or an empty string when none is present. Used as the stack
    filename prefix when the user left the Object field blank. The
    combiner sanitizes the prefix itself, so the raw header value is
    returned unaltered (the science directory name is NOT used here, to
    avoid mislabeling a stack with an unrelated folder name)."""
    try:
        from astropy.io import fits as pyfits
        for f in sorted(os.listdir(cfg["science_dir"])):
            if not f.lower().endswith(FITS_EXTENSIONS):
                continue
            hdr = pyfits.getheader(os.path.join(cfg["science_dir"], f))
            for key in ("OBJECT", "TARGET", "TARGNAME", "OBJNAME"):
                v = hdr.get(key)
                if v and str(v).strip():
                    return str(v).strip()
            break  # only the first FITS file
    except Exception:
        pass
    return ""


def derive_run_name(cfg):
    """A filesystem-safe name for this run's products: the user's object
    name if given, else the OBJECT/TARGET header of the first science
    image, else the science directory's own name."""
    name = cfg.get("object", "").strip()
    if not name:
        try:
            from astropy.io import fits as pyfits
            for f in sorted(os.listdir(cfg["science_dir"])):
                if not f.lower().endswith(FITS_EXTENSIONS):
                    continue
                hdr = pyfits.getheader(os.path.join(cfg["science_dir"], f))
                for key in ("OBJECT", "TARGET", "TARGNAME", "OBJNAME"):
                    v = hdr.get(key)
                    if v and str(v).strip():
                        name = str(v).strip()
                        break
                break  # only the first FITS file
        except Exception:
            pass
    if not name:
        name = os.path.basename(os.path.normpath(cfg["science_dir"]))
    name = name.replace("'", "p").replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9._+-]", "", name) or "target"


# ----------------------------------------------------------------------
# Pipeline planning (pure logic, kept separate from the interface so it
# can be tested without a display and read as documentation of exactly
# what each mode does)
# ----------------------------------------------------------------------

def build_plan(cfg):
    """
    Translate a configuration dictionary into the list of commands to run.

    cfg keys: mode, science_dir, filter, dark_path, flat_path, output_dir,
              ra, dec, sat_region, combine_method, catalog

    Returns (steps, products) where steps is a list of
    (description, command_list, working_dir) tuples executed in order, and
    products describes what the dashboard should display afterwards.
    Raises ValueError with a human-readable message when the configuration
    is incomplete.
    """
    mode = cfg["mode"]
    science = cfg["science_dir"]
    out = cfg["output_dir"]
    py = sys.executable
    tag = filter_tag(cfg["filter"])

    if not is_fits_dir(science):
        raise ValueError("Please choose a science image directory that "
                         "contains FITS files.")
    if not os.path.isdir(out):
        raise ValueError("Please choose an output directory.")

    steps = []
    products = {"mode": mode}
    obj = cfg.get("object", "").strip()
    autoselect = cfg["filter"] == "autoselect"

    if autoselect and "flat" in mode:
        raise ValueError(
            "Autoselect cannot be combined with flat fielding, because a "
            "flat field is filter-specific: each filter's stack needs its "
            "own master flat. Choose a specific filter for flat-fielded "
            "stacking, or use a mode without flats.")
    if autoselect and mode == "Differential photometry":
        raise ValueError(
            "Differential photometry needs a specific filter; autoselect "
            "applies to stacking modes only.")

    # ---------------- Saturation check ----------------
    if mode == "Saturation check":
        region = cfg.get("sat_region", "target")
        report = os.path.join(out, "quality_report.txt")
        steps.append((
            f"Image quality report ({region} region)",
            [py, "-u", SCRIPTS["exposecheck"], science, f"-{region}",
             "--report", report],
            out,  # exposecheck writes its CSV into the working directory
        ))
        csv_name = f"{os.path.basename(os.path.normpath(science))}_{region}.csv"
        products["table_csv"] = os.path.join(out, csv_name)
        products["report"] = report
        return steps, products

    # ---------------- Differential photometry ----------------
    if mode == "Differential photometry":
        ra, dec = cfg.get("ra", "").strip(), cfg.get("dec", "").strip()
        if not ra or not dec:
            raise ValueError("Differential photometry needs the target RA "
                             "and Dec (hh:mm:ss / dd:mm:ss or decimal "
                             "degrees).")
        zoom_raw = cfg.get("zoom_precision", "").strip()
        if zoom_raw:
            try:
                zoom_val = float(zoom_raw)
                if zoom_val <= 0:
                    raise ValueError
            except ValueError:
                raise ValueError("Mag precision (zoom) must be a positive "
                                 "number, e.g. 0.5 or 0.05.")
        else:
            zoom_val = 0.5

        run_name = derive_run_name(cfg)
        phot_dir = science
        alignment = cfg.get("alignment", "default")
        if alignment in ("shift", "shift and rotate"):
            # Pre-align the whole series onto the first frame's pixel grid
            # and stamp its WCS into every registered frame, then point
            # the photometry at the registered copies. This rescues data
            # sets with large dithers, field rotation, or frames whose
            # own WCS solutions are missing or inconsistent.
            reg_dir = os.path.join(out, f"registered_{run_name}_{tag}")
            reg_cmd = [py, "-u", SCRIPTS["combiner"], science,
                       "--register-dir", reg_dir,
                       "--filter", cfg["filter"]]
            if obj:
                reg_cmd += ["--object", obj]
            if alignment == "shift":
                reg_cmd += ["--no-rotation"]
            reg_cmd += ["--diagnostics"]
            steps.append((f"Pre-aligning frames ({alignment})", reg_cmd, out))
            phot_dir = reg_dir

        phot_csv = os.path.join(out, f"{run_name}_photometry_{tag}.csv")
        lc_pdf = os.path.join(out, f"{run_name}_lightcurve_{tag}.pdf")
        phot_cmd = [py, "-u", SCRIPTS["photcalib"], phot_dir,
                    "-f", cfg["filter"], "-o", phot_csv,
                    "--target-ra", ra, "--target-dec", dec,
                    "--catalog", cfg.get("catalog", "auto"),
                    "--create-diagnostics"]
        if cfg.get("object", "").strip():
            phot_cmd += ["--object-name", cfg["object"].strip()]
        steps.append(("Aperture photometry and calibration", phot_cmd, out))
        steps.append(("Light curve plots",
                      [py, "-u", SCRIPTS["plotter"], phot_csv, "-o", lc_pdf,
                       "--verbose", "--zoom-precision", str(zoom_val)],
                      out))
        products["phot_csv"] = phot_csv
        products["lc_pdf"] = lc_pdf
        return steps, products

    # ---------------- Stacking modes ----------------
    use_dark = "dark" in mode
    use_flat = "flat" in mode
    use_bias = bool(cfg.get("use_bias"))
    method = cfg.get("combine_method", "avsigclip")

    bias_file = None
    if use_bias:
        bias = cfg.get("bias_path", "")
        if not bias:
            raise ValueError("Bias subtraction is checked, so a directory "
                             "of bias frames (or a master bias file) is "
                             "needed.")
        if os.path.isdir(bias):
            if not is_fits_dir(bias):
                raise ValueError("The bias directory contains no FITS "
                                 "files.")
            bias_file = os.path.join(out, "master_bias.fits")
            steps.append((
                "Building master bias (median combine)",
                [py, "-u", SCRIPTS["combiner"], bias, "-c", "median",
                 "--noalign", "-o", bias_file],
                out))
        else:
            bias_file = bias

    dark_file = None
    if use_dark:
        dark = cfg.get("dark_path", "")
        if not dark:
            raise ValueError("This mode needs a master dark file or a "
                             "directory of dark frames.")
        if os.path.isdir(dark):
            if not is_fits_dir(dark):
                raise ValueError("The darks directory contains no FITS files.")
            dark_file = os.path.join(out, "master_dark.fits")
            dark_cmd = [py, "-u", SCRIPTS["combiner"], dark, "-c", "median",
                        "--noalign", "-o", dark_file]
            if bias_file:
                dark_cmd[4:4] = ["-bias", bias_file]
            steps.append((
                "Building master dark (median combine)",
                dark_cmd,
                out))
        else:
            dark_file = dark

    flat_file = None
    if use_flat:
        flat = cfg.get("flat_path", "")
        if not flat:
            raise ValueError("This mode needs a master flat file or a "
                             "directory of flat frames.")
        if os.path.isdir(flat):
            if not is_fits_dir(flat):
                raise ValueError("The flats directory contains no FITS files.")
            flat_file = os.path.join(out, f"master_flat_{tag}.fits")
            # --filter restricts the master to flats taken through the
            # selected filter (directories often mix filters).
            cmd = [py, "-u", SCRIPTS["combiner"], flat, "-c", "avsigclip",
                   "--noalign", "--normalize", "--filter", cfg["filter"],
                   "-o", flat_file]
            if bias_file:
                cmd[3:3] = ["-bias", bias_file]
            if dark_file:
                cmd[3:3] = ["-dark", dark_file]
            steps.append((
                f"Building master flat ({cfg['filter']} frames only, "
                f"sigma-clipped, normalized)", cmd, out))
        else:
            flat_file = flat

    # The combiner names the stack from the object name (the Object field,
    # else the OBJECT/TARGET header) plus the frame count, filter, binning,
    # and method, writing it into the chosen output directory. The GUI
    # recovers the exact path from the log.
    cmd = [py, "-u", SCRIPTS["combiner"], science, "-c", method,
           "--filter", cfg["filter"],
           "--diagnostics"]  # bare flag: named from the stack itself
    # Resolve an object name for the filename prefix: the explicit Object
    # field if given, otherwise the header-derived name. Passing it as
    # --object also restricts the stack to frames of that object, which is
    # only what we want when the user actually typed a name; for a
    # header-derived name we pass it purely for naming via --object-name.
    if obj:
        cmd += ["--object", obj]
    else:
        derived = derive_object_name(cfg)
        if derived:
            cmd += ["--object-name", derived]
    if bias_file:
        cmd[4:4] = ["-bias", bias_file]
    if dark_file:
        cmd[4:4] = ["-dark", dark_file]
    if flat_file:
        cmd[4:4] = ["-flat", flat_file]
    desc = ("Aligning and stacking science images (one stack per filter)"
            if autoselect else "Aligning and stacking science images")
    steps.append((desc, cmd, out))

    products["stack_fits"] = None  # resolved from the combiner's output
    return steps, products


# ----------------------------------------------------------------------
# The application
# ----------------------------------------------------------------------

class NSUTGui(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("NSUT Control Panel — Nieves Soka University Telescope")
        self.geometry("1180x760")
        self.minsize(980, 640)

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Run.TButton", font=("TkDefaultFont", 11, "bold"))

        self.q = queue.Queue()
        self.worker = None
        self.last_products = None

        self._build_controls()
        self._build_dashboard()
        self._on_mode_change()
        self._check_scripts()
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_controls(self):
        panel = ttk.Frame(self, padding=10)
        panel.pack(side="left", fill="y")

        def browse_dir(var):
            path = filedialog.askdirectory()
            if path:
                var.set(path)

        def browse_dir_or_file(var):
            path = filedialog.askopenfilename(
                filetypes=[("FITS files", "*.fits *.fit *.fts"),
                           ("All files", "*.*")])
            if path:
                var.set(path)

        def row(label):
            f = ttk.Frame(panel)
            f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, width=18, anchor="w").pack(side="left")
            return f

        ttk.Label(panel, text="NSUT Image Reduction",
                  font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Configure a reduction and press Run.",
                  foreground="#555").pack(anchor="w", pady=(0, 8))

        # Science directory
        self.science_var = tk.StringVar()
        f = row("Science images")
        ttk.Entry(f, textvariable=self.science_var, width=30).pack(
            side="left", fill="x", expand=True)
        ttk.Button(f, text="Browse…", width=9,
                   command=lambda: browse_dir(self.science_var)).pack(side="left")

        # Object name (optional): only frames whose OBJECT header matches
        # are used for stacking.
        self.object_var = tk.StringVar()
        f = row("Object name")
        ttk.Entry(f, textvariable=self.object_var, width=22).pack(side="left")
        ttk.Label(f, text=" optional", foreground="#777").pack(side="left")

        # Filter
        self.filter_var = tk.StringVar(value=FILTERS[0])
        f = row("Filter")
        ttk.Combobox(f, textvariable=self.filter_var, values=FILTERS,
                     state="readonly", width=8).pack(side="left")

        # Mode
        self.mode_var = tk.StringVar(value=MODES[0])
        f = row("Reduction mode")
        cb = ttk.Combobox(f, textvariable=self.mode_var, values=MODES,
                          state="readonly", width=38)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())

        # Bias (checkbox-driven, independent of the reduction mode). Bias
        # and dark are both subtracted from every frame before alignment
        # and combining, removing fixed-pattern noise.
        self.use_bias_var = tk.BooleanVar(value=False)
        f = row("")
        self.bias_check = ttk.Checkbutton(
            f, text="Subtract bias frames", variable=self.use_bias_var,
            command=self._on_mode_change)
        self.bias_check.pack(side="left")

        self.bias_var = tk.StringVar()
        f = row("Bias (dir/file)")
        self.bias_entry = ttk.Entry(f, textvariable=self.bias_var, width=30)
        self.bias_entry.pack(side="left", fill="x", expand=True)
        self.bias_btn_d = ttk.Button(
            f, text="Dir…", width=5, command=lambda: browse_dir(self.bias_var))
        self.bias_btn_d.pack(side="left")
        self.bias_btn_f = ttk.Button(
            f, text="File…", width=5,
            command=lambda: browse_dir_or_file(self.bias_var))
        self.bias_btn_f.pack(side="left")

        # Darks
        self.dark_var = tk.StringVar()
        f = row("Darks (dir/file)")
        self.dark_entry = ttk.Entry(f, textvariable=self.dark_var, width=30)
        self.dark_entry.pack(side="left", fill="x", expand=True)
        self.dark_btn_d = ttk.Button(
            f, text="Dir…", width=5, command=lambda: browse_dir(self.dark_var))
        self.dark_btn_d.pack(side="left")
        self.dark_btn_f = ttk.Button(
            f, text="File…", width=5,
            command=lambda: browse_dir_or_file(self.dark_var))
        self.dark_btn_f.pack(side="left")

        # Flats
        self.flat_var = tk.StringVar()
        f = row("Flats (dir/file)")
        self.flat_entry = ttk.Entry(f, textvariable=self.flat_var, width=30)
        self.flat_entry.pack(side="left", fill="x", expand=True)
        self.flat_btn_d = ttk.Button(
            f, text="Dir…", width=5, command=lambda: browse_dir(self.flat_var))
        self.flat_btn_d.pack(side="left")
        self.flat_btn_f = ttk.Button(
            f, text="File…", width=5,
            command=lambda: browse_dir_or_file(self.flat_var))
        self.flat_btn_f.pack(side="left")

        # Output directory
        self.output_var = tk.StringVar()
        f = row("Output directory")
        ttk.Entry(f, textvariable=self.output_var, width=30).pack(
            side="left", fill="x", expand=True)
        ttk.Button(f, text="Browse…", width=9,
                   command=lambda: browse_dir(self.output_var)).pack(side="left")

        # Target coordinates (differential photometry)
        self.ra_var = tk.StringVar()
        self.dec_var = tk.StringVar()
        f = row("Target RA")
        self.ra_entry = ttk.Entry(f, textvariable=self.ra_var, width=18)
        self.ra_entry.pack(side="left")
        ttk.Label(f, text=" e.g. 22:37:03.6", foreground="#777").pack(side="left")
        f = row("Target Dec")
        self.dec_entry = ttk.Entry(f, textvariable=self.dec_var, width=18)
        self.dec_entry.pack(side="left")
        ttk.Label(f, text=" e.g. +34:25:08", foreground="#777").pack(side="left")

        # Options that depend on the mode
        self.sat_region_var = tk.StringVar(value="target")
        f = row("Saturation region")
        self.sat_region_cb = ttk.Combobox(
            f, textvariable=self.sat_region_var, values=SAT_REGIONS,
            state="readonly", width=8)
        self.sat_region_cb.pack(side="left")

        self.method_var = tk.StringVar(value="avsigclip")
        f = row("Combine method")
        self.method_cb = ttk.Combobox(
            f, textvariable=self.method_var, values=COMBINE_METHODS,
            state="readonly", width=10)
        self.method_cb.pack(side="left")

        self.align_var = tk.StringVar(value="default")
        f = row("Alignment")
        self.align_cb = ttk.Combobox(
            f, textvariable=self.align_var,
            values=["default", "shift", "shift and rotate"],
            state="readonly", width=16)
        self.align_cb.pack(side="left")
        ttk.Label(f, text=" pre-align frames",
                  foreground="#777").pack(side="left")

        self.zoom_var = tk.StringVar()
        f = row("Mag precision (zoom)")
        self.zoom_entry = ttk.Entry(f, textvariable=self.zoom_var, width=8)
        self.zoom_entry.pack(side="left")
        ttk.Label(f, text=" \u00b1 mag for zoomed plot (default 0.5)",
                  foreground="#777").pack(side="left")

        self.catalog_var = tk.StringVar(value="auto")
        f = row("Catalog")
        self.catalog_cb = ttk.Combobox(
            f, textvariable=self.catalog_var,
            values=["auto", "apass", "panstarrs", "sdss", "none"],
            state="readonly", width=10)
        self.catalog_cb.pack(side="left")
        ttk.Label(f, text=" (calibration source)",
                  foreground="#777").pack(side="left")

        ttk.Separator(panel).pack(fill="x", pady=10)

        self.run_btn = ttk.Button(panel, text="▶  Run reduction",
                                  style="Run.TButton",
                                  command=self.run_pipeline)
        self.run_btn.pack(fill="x", pady=(0, 6))

        self.progress = ttk.Progressbar(panel, mode="indeterminate")
        self.progress.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(panel, textvariable=self.status_var, wraplength=300,
                  foreground="#333").pack(anchor="w", pady=(6, 0))

    def _build_dashboard(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(side="left", fill="both", expand=True,
                           padx=(0, 6), pady=6)

        # Log tab
        log_frame = ttk.Frame(self.notebook)
        self.notebook.add(log_frame, text="  Log  ")
        self.log = scrolledtext.ScrolledText(
            log_frame, wrap="word", font=("Courier", 9), state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("cmd", foreground="#0a5", font=("Courier", 9, "bold"))
        self.log.tag_configure("err", foreground="#c00")
        self.log.tag_configure("head", foreground="#03c",
                               font=("Courier", 10, "bold"))

        # Quality table tab
        table_frame = ttk.Frame(self.notebook)
        self.notebook.add(table_frame, text="  Image Quality  ")
        cols = ("Image", "ExpTime", "Filter", "Saturated", "%Sat",
                "Median", "Max", "NStars")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        widths = (320, 70, 60, 80, 70, 80, 80, 70)
        for c, w in zip(cols, widths):
            self.tree.heading(
                c, text=c,
                command=lambda col=c: self._sort_tree(col, False))
            self.tree.column(c, width=w, anchor="e" if c != "Image" else "w")
        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.tag_configure("warn", background="#ffe8e0")

        # Preview tab (thumbnails / plots)
        prev_frame = ttk.Frame(self.notebook)
        self.notebook.add(prev_frame, text="  Preview  ")
        self.fig = Figure(figsize=(7, 5), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=prev_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(self.canvas, prev_frame)
        ax = self.fig.add_subplot(111)
        ax.text(0.5, 0.5, "Run a reduction to see results here.",
                ha="center", va="center", color="#888")
        ax.set_axis_off()
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Interface behavior
    # ------------------------------------------------------------------

    def _check_scripts(self):
        missing = [name for name, path in SCRIPTS.items()
                   if not os.path.exists(path)]
        if missing:
            messagebox.showwarning(
                "Missing pipeline scripts",
                "These scripts were not found next to nsut_gui.py:\n\n  "
                + "\n  ".join(SCRIPTS[m] for m in missing)
                + "\n\nPlace the GUI in the same directory as the four "
                  "NSUT programs.")

    def _on_mode_change(self):
        """Enable only the controls relevant to the selected mode."""
        mode = self.mode_var.get()
        is_sat = mode == "Saturation check"
        is_phot = mode == "Differential photometry"
        is_stack = not is_sat and not is_phot
        use_dark = "dark" in mode
        use_flat = "flat" in mode

        def setstate(widgets, on):
            for w in widgets:
                w.configure(state=("normal" if on else "disabled"))

        setstate([self.dark_entry, self.dark_btn_d, self.dark_btn_f], use_dark)
        setstate([self.flat_entry, self.flat_btn_d, self.flat_btn_f], use_flat)
        # Bias is checkbox-driven and available for any stacking mode; its
        # picker is enabled only when the box is checked.
        use_bias = bool(self.use_bias_var.get())
        self.bias_check.configure(state="normal" if is_stack else "disabled")
        setstate([self.bias_entry, self.bias_btn_d, self.bias_btn_f],
                 is_stack and use_bias)
        setstate([self.ra_entry, self.dec_entry], is_phot)
        self.sat_region_cb.configure(state="readonly" if is_sat else "disabled")
        self.method_cb.configure(state="readonly" if is_stack else "disabled")
        self.catalog_cb.configure(state="readonly" if is_phot else "disabled")
        self.align_cb.configure(state="readonly" if is_phot else "disabled")
        self.zoom_entry.configure(state="normal" if is_phot else "disabled")

    def _append_log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _sort_tree(self, col, reverse):
        def keyfn(v):
            try:
                return float(v)
            except ValueError:
                return v
        items = [(keyfn(self.tree.set(k, col)), k)
                 for k in self.tree.get_children("")]
        items.sort(reverse=reverse, key=lambda t: t[0])
        for i, (_, k) in enumerate(items):
            self.tree.move(k, "", i)
        self.tree.heading(col,
                          command=lambda: self._sort_tree(col, not reverse))

    # ------------------------------------------------------------------
    # Running the pipeline
    # ------------------------------------------------------------------

    def run_pipeline(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "A reduction is already running.")
            return

        cfg = {
            "mode": self.mode_var.get(),
            "science_dir": self.science_var.get().strip(),
            "filter": self.filter_var.get(),
            "object": self.object_var.get(),
            "use_bias": bool(self.use_bias_var.get()),
            "bias_path": self.bias_var.get().strip(),
            "dark_path": self.dark_var.get().strip(),
            "flat_path": self.flat_var.get().strip(),
            "output_dir": self.output_var.get().strip(),
            "ra": self.ra_var.get(),
            "dec": self.dec_var.get(),
            "sat_region": self.sat_region_var.get(),
            "combine_method": self.method_var.get(),
            "catalog": self.catalog_var.get(),
            "alignment": self.align_var.get(),
            "zoom_precision": self.zoom_var.get(),
        }
        try:
            steps, products = build_plan(cfg)
        except ValueError as e:
            messagebox.showerror("Configuration problem", str(e))
            return

        self.last_products = products
        self._run_dir = cfg["output_dir"]
        self._run_started0 = time.time()
        self.run_btn.configure(state="disabled")
        self.progress.start(12)
        self._run_started = time.time()
        self.status_var.set("Running…")
        self.notebook.select(0)
        self._append_log("=" * 70, "head")
        self._append_log(f"Starting: {cfg['mode']}  (filter {cfg['filter']})",
                         "head")

        self.worker = threading.Thread(target=self._worker,
                                       args=(steps,), daemon=True)
        self.worker.start()

    def _worker(self, steps):
        """Run each pipeline step as a subprocess, streaming its output."""
        try:
            for desc, cmd, cwd in steps:
                self.q.put(("log", f"\n--- {desc} ---", "head"))
                self.q.put(("log", "$ " + " ".join(cmd), "cmd"))
                env = dict(os.environ, PYTHONUNBUFFERED="1")
                proc = subprocess.Popen(
                    cmd, cwd=cwd, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                    env=env)
                for line in proc.stdout:
                    line = line.rstrip()
                    self.q.put(("log", line, None))
                    m = re.search(r"Final combined image saved as '(.+)'",
                                  line)
                    if m:
                        path = m.group(1)
                        if not os.path.isabs(path):
                            path = os.path.join(cwd, path)
                        self.q.put(("saved_file", path, None))
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Step failed (exit code {proc.returncode}): {desc}")
            self.q.put(("done", None, None))
        except Exception as e:
            self.q.put(("error", str(e), None))

    def _poll_queue(self):
        try:
            while True:
                kind, payload, tag = self.q.get_nowait()
                if kind == "log":
                    self._append_log(payload, tag)
                elif kind == "saved_file":
                    # Collect every combined image the run produced; the
                    # science stacks always come after any master frames,
                    # and autoselect can produce several stacks.
                    if self.last_products is not None:
                        self.last_products.setdefault("stacks", []).append(payload)
                        self.last_products["stack_fits"] = payload
                elif kind == "done":
                    self._finish(success=True)
                elif kind == "error":
                    self._append_log(f"ERROR: {payload}", "err")
                    self._finish(success=False)
        except queue.Empty:
            pass
        if self.worker and self.worker.is_alive() and \
                getattr(self, "_run_started", None):
            mins, secs = divmod(int(time.time() - self._run_started), 60)
            self.status_var.set(f"Running… {mins:d} m {secs:02d} s "
                                f"(see Log tab for live progress)")
        self.after(100, self._poll_queue)

    def _finish(self, success):
        self.progress.stop()
        self.run_btn.configure(state="normal")
        self._run_started = None
        if not success:
            self.status_var.set("Failed — see Log tab for details.")
            return
        self.status_var.set("Done.")
        self._append_log("\nReduction complete.", "head")
        try:
            self._show_products(self.last_products)
        except Exception as e:
            self._append_log(f"Could not display results: {e}", "err")

    # ------------------------------------------------------------------
    # Dashboard displays
    # ------------------------------------------------------------------

    def _show_products(self, products):
        mode = products["mode"]
        if mode == "Saturation check":
            self._show_quality_table(products["table_csv"])
            self.notebook.select(1)
        elif mode == "Differential photometry":
            self._show_light_curve(products["phot_csv"])
            self.notebook.select(2)
        else:
            stacks = [p for p in products.get("stacks", [])
                      if os.path.exists(p)
                      and not os.path.basename(p).startswith("master_")]
            if not stacks and getattr(self, "_run_dir", None):
                # Fallback: newest stack files written to the output
                # directory since this run started.
                cand = []
                for f in os.listdir(self._run_dir):
                    p = os.path.join(self._run_dir, f)
                    if ("_stack_" in f and f.lower().endswith(
                            (".fits", ".fit", ".fts"))
                            and os.path.getmtime(p) >= self._run_started0):
                        cand.append(p)
                stacks = sorted(cand, key=os.path.getmtime)
            if not stacks:
                raise FileNotFoundError(
                    "Could not locate the combined output file(s) in the log.")
            if len(stacks) == 1:
                self._show_stack_thumbnail(stacks[0])
            else:
                self._show_stack_grid(stacks)
            self.notebook.select(2)

    def _show_quality_table(self, csv_path):
        """Populate the dashboard table from the ExposeCheck CSV."""
        for item in self.tree.get_children(""):
            self.tree.delete(item)
        if not os.path.exists(csv_path):
            raise FileNotFoundError(csv_path)
        with open(csv_path, newline="") as f:
            for r in csv.DictReader(f):
                pct = float(r.get("PctSaturated", 0) or 0)
                vals = (r.get("Image", ""), r.get("ExpTime", ""),
                        r.get("Filter", ""), r.get("Saturated", ""),
                        f"{pct:.3f}", f"{float(r.get('Median', 0)):.0f}",
                        f"{float(r.get('Max', 0)):.0f}", r.get("NStars", ""))
                tags = ("warn",) if pct > 0.01 else ()
                self.tree.insert("", "end", values=vals, tags=tags)
        self._append_log(f"Quality table loaded from {csv_path} "
                         "(rows with >0.01% saturation highlighted).")

    def _show_stack_thumbnail(self, fits_path):
        """Render a zscale-stretched preview of the combined image."""
        from astropy.io import fits as pyfits
        from astropy.visualization import ZScaleInterval

        data = pyfits.getdata(fits_path).astype(np.float32)
        step = max(1, max(data.shape) // 1400)
        small = data[::step, ::step]
        vmin, vmax = ZScaleInterval().get_limits(small)

        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.imshow(small, cmap="gray", vmin=vmin, vmax=vmax, origin="lower",
                  interpolation="nearest")
        ax.set_title(f"{os.path.basename(fits_path)}   "
                     f"({data.shape[1]}×{data.shape[0]} px, "
                     f"displayed every {step} px)", fontsize=10)
        ax.set_xticks([]), ax.set_yticks([])
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _show_stack_grid(self, fits_paths, max_panels=6):
        """Render zscale previews of several stacks side by side (used by
        autoselect runs that produce one stack per filter)."""
        from astropy.io import fits as pyfits
        from astropy.visualization import ZScaleInterval

        paths = fits_paths[:max_panels]
        ncols = 2 if len(paths) <= 4 else 3
        nrows = int(np.ceil(len(paths) / ncols))
        self.fig.clear()
        for i, p in enumerate(paths, start=1):
            ax = self.fig.add_subplot(nrows, ncols, i)
            try:
                data = pyfits.getdata(p).astype(np.float32)
                step = max(1, max(data.shape) // 700)
                small = data[::step, ::step]
                vmin, vmax = ZScaleInterval().get_limits(small)
                ax.imshow(small, cmap="gray", vmin=vmin, vmax=vmax,
                          origin="lower", interpolation="nearest")
            except Exception as e:
                ax.text(0.5, 0.5, f"could not load\n{e}", ha="center",
                        va="center", fontsize=7)
            ax.set_title(os.path.basename(p), fontsize=7)
            ax.set_xticks([]), ax.set_yticks([])
        if len(fits_paths) > max_panels:
            self.fig.suptitle(f"Showing {max_panels} of {len(fits_paths)} "
                              f"stacks", fontsize=9)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _show_light_curve(self, csv_path):
        """Draw the differential (and calibrated) light curve from the
        PhotoCalib CSV, mirroring the plotter's weighted-average logic."""
        import pandas as pd

        df = pd.read_csv(csv_path)
        for col in df.columns:
            if df[col].dtype == object and not col.endswith("_catalog") \
                    and col not in ("filename", "filter", "error",
                                    "quality_flags"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        std_nums = sorted(int(m.group(1)) for c in df.columns
                          if (m := re.match(r"std(\d+)_inst_mag$", c)))
        jd0 = np.floor(np.nanmin(df["jd"]) * 10) / 10

        jd_list, diff_list, err_list = [], [], []
        for _, row in df.iterrows():
            if not (np.isfinite(row.get("jd", np.nan))
                    and np.isfinite(row.get("target_inst_mag", np.nan))):
                continue
            mags, weights = [], []
            for n in std_nums:
                m = row.get(f"std{n}_inst_mag", np.nan)
                if not np.isfinite(m):
                    continue
                e = row.get(f"std{n}_inst_mag_err", np.nan)
                snr = row.get(f"std{n}_snr", np.nan)
                if not (np.isfinite(e) and e > 1e-4):
                    e = 1.0857 / snr if np.isfinite(snr) and snr > 0 else 0.01
                mags.append(m)
                weights.append(1.0 / e**2)
            if not mags:
                continue
            ref_mean = np.average(mags, weights=weights)
            terr = row.get("target_inst_mag_err", np.nan)
            if not (np.isfinite(terr) and terr > 1e-4):
                tsnr = row.get("target_snr", np.nan)
                terr = 1.0857 / tsnr if np.isfinite(tsnr) and tsnr > 0 else 0.01
            jd_list.append(row["jd"] - jd0)
            diff_list.append(row["target_inst_mag"] - ref_mean)
            err_list.append(np.sqrt(terr**2 + 1.0 / np.sum(weights)))

        jd_a, diff_a, err_a = map(np.array, (jd_list, diff_list, err_list))
        have_calib = ("target_calib_mag" in df.columns
                      and np.any(np.isfinite(df["target_calib_mag"])))

        self.fig.clear()
        if have_calib:
            ax1, ax2 = self.fig.subplots(2, 1, sharex=True)
        else:
            ax1 = self.fig.add_subplot(111)
            ax2 = None

        if len(jd_a):
            ax1.errorbar(jd_a, diff_a, yerr=err_a, fmt="o", color="purple",
                         capsize=3, markersize=5)
            mean, rms = np.mean(diff_a), np.std(diff_a)
            ax1.axhline(mean, ls="--", color="purple", alpha=0.6)
            ax1.axhspan(mean - rms, mean + rms, color="purple", alpha=0.12)
            ax1.set_title(f"Differential light curve "
                          f"(N={len(jd_a)}, RMS={rms:.3f} mag, "
                          f"{len(std_nums)} reference stars)", fontsize=10)
        else:
            ax1.text(0.5, 0.5, "No valid measurements", ha="center")
        ax1.set_ylabel("Target − refs (mag)")
        ax1.invert_yaxis()
        ax1.grid(alpha=0.3)

        if ax2 is not None:
            v = np.isfinite(df["jd"]) & np.isfinite(df["target_calib_mag"])
            cerr = df.loc[v, "target_calib_mag_err"] \
                if "target_calib_mag_err" in df.columns else None
            ax2.errorbar(df.loc[v, "jd"] - jd0, df.loc[v, "target_calib_mag"],
                         yerr=cerr, fmt="s", color="darkgreen", capsize=3,
                         markersize=5)
            filt = str(df["filter"].iloc[0]) if "filter" in df.columns else ""
            ax2.set_ylabel(f"Calibrated mag ({filt})")
            ax2.invert_yaxis()
            ax2.grid(alpha=0.3)
            ax2.set_xlabel(f"JD − {jd0:.1f} (days)")
        else:
            ax1.set_xlabel(f"JD − {jd0:.1f} (days)")
            self._append_log("No calibrated magnitudes in the CSV (catalog "
                             "matching unavailable); showing the "
                             "differential curve only.")

        self.fig.tight_layout()
        self.canvas.draw_idle()


def main():
    app = NSUTGui()
    app.mainloop()


if __name__ == "__main__":
    main()
