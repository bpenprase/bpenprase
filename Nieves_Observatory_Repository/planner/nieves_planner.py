"""
Nieves Observatory ACP Plan Generator
=====================================
Generates ACP observing plans for the Nieves Observatory (Soka University
of America, Aliso Viejo, CA) with live target selection:

  * Deep-sky objects (galaxies, nebulae, star clusters) from a bundled
    OpenNGC-derived catalog (nieves_catalog.csv), filtered for visibility.
  * Bright supernovae fetched live from David Bishop's "Latest Supernovae"
    active-object page at rochesterastronomy.org.
  * Bright comets fetched live from theskylive.com.
  * Exoplanet transits fetched live from Eric Jensen's Swarthmore
    Transit Finder (Tapir).
  * Planets and bright asteroids from built-in lists (positions for the
    planets are computed with low-precision Keplerian elements, good to
    a fraction of a degree -- plenty for visibility decisions; ACP does
    the precise pointing itself).

The plan is sorted by Right Ascension beginning at the western edge of
the visibility window, so targets are observed before they set.

No third-party packages are required: everything uses the Python
standard library. Run with no arguments for the GUI, or see --help
for the command-line (headless) mode used by automated pipelines.

Author: built for Bryan Penprase / Nieves Observatory, 2026.
"""

import csv
import datetime as dt
import html as _html_mod
import json
import math
import os
import re
import sys
import urllib.request
import urllib.parse
from html.parser import HTMLParser

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

# ----------------------------------------------------------------------
# CONFIGURATION -- edit these values to tune the system
# ----------------------------------------------------------------------

OBSERVATORY = {
    "name": "Nieves Observatory",
    "latitude": 33.5553,        # degrees North (Soka University, Aliso Viejo)
    "longitude": -117.7342,     # degrees East (negative = West)
    "timezone": "America/Los_Angeles",
}

LIMITS = {
    "min_altitude_deg": 30.0,    # only schedule targets above this altitude
    "max_dec": 90.0,
    "min_dec": -35.0,
    "dso_mag_limit": 12.0,       # deep-sky objects brighter than this
    "sn_mag_bright": 11.5,       # supernova window (latest magnitude)
    "sn_mag_faint": 14.5,
    "comet_mag_limit": 14.0,
    "transit_max_vmag": 13.0,
    "transit_min_depth_ppt": 5.0,  # minimum transit depth, parts per thousand
}

# Exposure recipes per object class. Edit freely; lists must be equal length.
FILTER_PROFILES = {
    "galaxy":    {"count": [1, 1, 1, 1], "interval": [600, 600, 600, 600],
                  "binning": [1, 1, 1, 1], "filter": ["r'", "g'", "i'", "z'"]},
    "cluster":   {"count": [1, 1, 1, 1], "interval": [600, 600, 600, 600],
                  "binning": [1, 1, 1, 1], "filter": ["r'", "g'", "i'", "z'"]},
    "nebula":    {"count": [1, 1, 1, 1], "interval": [600, 600, 600, 600],
                  "binning": [1, 3, 3, 3], "filter": ["r'", "Ha", "OIII", "SII"]},
    "supernova": {"count": [3, 3], "interval": [300, 300],
                  "binning": [1, 1], "filter": ["r'", "g'"]},
    "comet":     {"count": [3], "interval": [300], "binning": [1], "filter": ["r'"]},
    "asteroid":  {"count": [3], "interval": [300], "binning": [1], "filter": ["r'"]},
    "planet":    {"count": [10], "interval": [30], "binning": [1], "filter": ["r'"]},
    "transit":   {"interval": 120, "binning": 2, "filter": "r'"},  # special handling
    # ingress/egress "edge" observations: short exposures for 15 min
    # on each side of the edge
    "transit_edge": {"interval": 60, "binning": 2, "filter": "r'",
                     "minutes_each_side": 15},
}

# Bright asteroids that ACP can resolve by name (MP <name>). The planner
# checks none of these for visibility (their positions move); ACP's
# #WAITINLIMITS directive protects against below-horizon pointing.
BRIGHT_ASTEROIDS = ["Vesta", "Ceres", "Pallas", "Juno", "Iris", "Hebe",
                    "Flora", "Metis", "Eunomia", "Psyche"]

PLANETS = ["Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune"]

CATALOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "nieves_catalog.csv")

URLS = {
    "rochester_active": "https://www.rochesterastronomy.org/snimages/snactive.html",
    "rochester_main": "https://www.rochesterastronomy.org/supernova.html",
    "skylive_comets": "https://theskylive.com/comets",
    "skylive_asteroids": "https://theskylive.com/asteroids-and-dwarf-planets",
    "skylive_base": "https://theskylive.com",
    "swarthmore_csv": "https://astro.swarthmore.edu/transits/print_transits.cgi",
    "hips2fits": ("https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
                  "?hips=CDS%2FP%2FDSS2%2Fcolor&width={w}&height={h}&fov={fov}"
                  "&projection=TAN&coordsys=icrs&ra={ra}&dec={dec}&format=png"),
    "simbad": "https://simbad.u-strasbg.fr/simbad/sim-id?Ident={ident}",
}

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36 "
              "NievesObservatoryPlanner/1.0 (educational use)")

# ----------------------------------------------------------------------
# BASIC ASTRONOMY -- time, coordinates, altitude
# ----------------------------------------------------------------------

def julian_date(t_utc):
    """Julian Date from a timezone-aware UTC datetime."""
    y, m = t_utc.year, t_utc.month
    d = (t_utc.day + t_utc.hour / 24 + t_utc.minute / 1440 +
         t_utc.second / 86400)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def gmst_hours(t_utc):
    """Greenwich Mean Sidereal Time in hours."""
    jd = julian_date(t_utc)
    t = (jd - 2451545.0) / 36525.0
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0) +
            0.000387933 * t * t - t * t * t / 38710000.0)
    return (gmst % 360.0) / 15.0


def lst_hours(t_utc, longitude_deg=None):
    """Local Sidereal Time in hours at the observatory."""
    if longitude_deg is None:
        longitude_deg = OBSERVATORY["longitude"]
    return (gmst_hours(t_utc) + longitude_deg / 15.0) % 24.0


def parse_ra_hours(s):
    """'HH:MM:SS' or 'HH:MM' or '22h28m27s' -> hours (float)."""
    s = s.strip()
    m = re.match(r"(\d{1,2})[h:\s](\d{1,2})(?:[m:\s](\d{1,2}(?:\.\d+)?))?", s)
    if not m:
        raise ValueError(f"Cannot parse RA: {s!r}")
    h = float(m.group(1)) + float(m.group(2)) / 60.0
    if m.group(3):
        h += float(m.group(3)) / 3600.0
    return h


def parse_dec_deg(s):
    """'+DD:MM:SS' style -> degrees (float)."""
    s = s.strip()
    m = re.match(r"([+-]?)(\d{1,2})[d°:\s](\d{1,2})(?:['m:\s](\d{1,2}(?:\.\d+)?))?", s)
    if not m:
        raise ValueError(f"Cannot parse Dec: {s!r}")
    sign = -1.0 if m.group(1) == "-" else 1.0
    d = float(m.group(2)) + float(m.group(3)) / 60.0
    if m.group(4):
        d += float(m.group(4)) / 3600.0
    return sign * d


def ra_hours_to_hms(ra_h):
    ra_h %= 24.0
    h = int(ra_h)
    mm = (ra_h - h) * 60
    m = int(mm)
    s = int(round((mm - m) * 60))
    if s == 60:
        s = 0
        m += 1
    if m == 60:
        m = 0
        h = (h + 1) % 24
    return f"{h:02d}:{m:02d}:{s:02d}"


def dec_deg_to_dms(dec):
    sign = "-" if dec < 0 else "+"
    dec = abs(dec)
    d = int(dec)
    mm = (dec - d) * 60
    m = int(mm)
    s = int(round((mm - m) * 60))
    if s == 60:
        s = 0
        m += 1
    if m == 60:
        m = 0
        d += 1
    return f"{sign}{d:02d}:{m:02d}:{s:02d}"


def altitude_deg(ra_h, dec_deg, lst_h, lat_deg=None):
    """Altitude of an object (degrees) for a given LST."""
    if lat_deg is None:
        lat_deg = OBSERVATORY["latitude"]
    ha = math.radians((lst_h - ra_h) * 15.0)
    lat = math.radians(lat_deg)
    dec = math.radians(dec_deg)
    sin_alt = (math.sin(lat) * math.sin(dec) +
               math.cos(lat) * math.cos(dec) * math.cos(ha))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def visible_during_window(ra_h, dec_deg, t_start_utc, t_end_utc,
                          min_alt=None, samples=13):
    """True if the object is above min_alt at any sampled time in the window.
    Returns (visible, best_alt, best_time_utc)."""
    if min_alt is None:
        min_alt = LIMITS["min_altitude_deg"]
    total = (t_end_utc - t_start_utc).total_seconds()
    best_alt, best_t = -90.0, t_start_utc
    for i in range(samples):
        t = t_start_utc + dt.timedelta(seconds=total * i / (samples - 1))
        alt = altitude_deg(ra_h, dec_deg, lst_hours(t))
        if alt > best_alt:
            best_alt, best_t = alt, t
    return best_alt >= min_alt, best_alt, best_t


# ----------------------------------------------------------------------
# SUN AND PLANET POSITIONS (low-precision Keplerian elements)
# Based on the standard truncated elements (P. Schlyter / Meeus); good
# to roughly 0.1 degree -- ample for visibility and RA sorting.
# ----------------------------------------------------------------------

def _kepler(M, e):
    """Solve Kepler's equation (M, e in radians/unitless) -> eccentric anomaly."""
    E = M + e * math.sin(M) * (1.0 + e * math.cos(M))
    for _ in range(10):
        dE = (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        E -= dE
        if abs(dE) < 1e-8:
            break
    return E


_ELEMENTS = {
    # name: (N, i, w, a, e, M)  each as (value_at_d0, rate_per_day)
    "Mercury": ((48.3313, 3.24587e-5), (7.0047, 5.00e-8), (29.1241, 1.01444e-5),
                (0.387098, 0), (0.205635, 5.59e-10), (168.6562, 4.0923344368)),
    "Venus":   ((76.6799, 2.46590e-5), (3.3946, 2.75e-8), (54.8910, 1.38374e-5),
                (0.723330, 0), (0.006773, -1.302e-9), (48.0052, 1.6021302244)),
    "Mars":    ((49.5574, 2.11081e-5), (1.8497, -1.78e-8), (286.5016, 2.92961e-5),
                (1.523688, 0), (0.093405, 2.516e-9), (18.6021, 0.5240207766)),
    "Jupiter": ((100.4542, 2.76854e-5), (1.3030, -1.557e-7), (273.8777, 1.64505e-5),
                (5.20256, 0), (0.048498, 4.469e-9), (19.8950, 0.0830853001)),
    "Saturn":  ((113.6634, 2.38980e-5), (2.4886, -1.081e-7), (339.3939, 2.97661e-5),
                (9.55475, 0), (0.055546, -9.499e-9), (316.9670, 0.0334442282)),
    "Uranus":  ((74.0005, 1.3978e-5), (0.7733, 1.9e-8), (96.6612, 3.0565e-5),
                (19.18171, -1.55e-8), (0.047318, 7.45e-9), (142.5905, 0.011725806)),
    "Neptune": ((131.7806, 3.0173e-5), (1.7700, -2.55e-7), (272.8461, -6.027e-6),
                (30.05826, 3.313e-8), (0.008606, 2.15e-9), (260.2471, 0.005995147)),
}


def _ecliptic_xyz(name, d):
    """Heliocentric ecliptic rectangular coordinates of a planet at day d
    (days since 2000 Jan 0.0 = JD 2451543.5)."""
    (N0, Nr), (i0, ir), (w0, wr), (a0, ar), (e0, er), (M0, Mr) = _ELEMENTS[name]
    N = math.radians(N0 + Nr * d)
    i = math.radians(i0 + ir * d)
    w = math.radians(w0 + wr * d)
    a = a0 + ar * d
    e = e0 + er * d
    M = math.radians((M0 + Mr * d) % 360.0)
    E = _kepler(M, e)
    xv = a * (math.cos(E) - e)
    yv = a * (math.sqrt(1 - e * e) * math.sin(E))
    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)
    xh = r * (math.cos(N) * math.cos(v + w) -
              math.sin(N) * math.sin(v + w) * math.cos(i))
    yh = r * (math.sin(N) * math.cos(v + w) +
              math.cos(N) * math.sin(v + w) * math.cos(i))
    zh = r * (math.sin(v + w) * math.sin(i))
    return xh, yh, zh


def sun_radec(t_utc):
    """Geocentric RA (hours), Dec (deg) of the Sun. ~0.01 deg accuracy."""
    d = julian_date(t_utc) - 2451543.5
    w = math.radians(282.9404 + 4.70935e-5 * d)
    e = 0.016709 - 1.151e-9 * d
    M = math.radians((356.0470 + 0.9856002585 * d) % 360.0)
    E = _kepler(M, e)
    xv = math.cos(E) - e
    yv = math.sqrt(1 - e * e) * math.sin(E)
    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)
    lon = v + w
    xs = r * math.cos(lon)
    ys = r * math.sin(lon)
    ecl = math.radians(23.4393 - 3.563e-7 * d)
    xe, ye, ze = xs, ys * math.cos(ecl), ys * math.sin(ecl)
    ra = math.degrees(math.atan2(ye, xe)) % 360.0
    dec = math.degrees(math.atan2(ze, math.sqrt(xe * xe + ye * ye)))
    return ra / 15.0, dec


def planet_radec(name, t_utc):
    """Geocentric RA (hours), Dec (deg) of a planet (low precision)."""
    d = julian_date(t_utc) - 2451543.5
    xh, yh, zh = _ecliptic_xyz(name, d)
    # Sun's position gives Earth's heliocentric position (negated)
    w = math.radians(282.9404 + 4.70935e-5 * d)
    e = 0.016709 - 1.151e-9 * d
    M = math.radians((356.0470 + 0.9856002585 * d) % 360.0)
    E = _kepler(M, e)
    xv = math.cos(E) - e
    yv = math.sqrt(1 - e * e) * math.sin(E)
    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)
    lon_s = v + w
    xs = r * math.cos(lon_s)
    ys = r * math.sin(lon_s)
    # geocentric ecliptic coordinates of planet
    xg = xh + xs
    yg = yh + ys
    zg = zh
    ecl = math.radians(23.4393 - 3.563e-7 * d)
    xe = xg
    ye = yg * math.cos(ecl) - zg * math.sin(ecl)
    ze = yg * math.sin(ecl) + zg * math.cos(ecl)
    ra = math.degrees(math.atan2(ye, xe)) % 360.0
    dec = math.degrees(math.atan2(ze, math.sqrt(xe * xe + ye * ye)))
    return ra / 15.0, dec


def twilight_times(date_local, tz):
    """Return (evening_end, morning_start) of astronomical twilight
    (sun altitude -18 deg) as local datetimes for the night beginning
    on date_local. Scans in 2-minute steps."""
    base = dt.datetime(date_local.year, date_local.month, date_local.day,
                       12, 0, tzinfo=tz)  # local noon
    evening_end = None
    morning_start = None
    t = base
    end = base + dt.timedelta(hours=24)
    prev_alt = None
    while t <= end:
        t_utc = t.astimezone(dt.timezone.utc)
        ra, dec = sun_radec(t_utc)
        alt = altitude_deg(ra, dec, lst_hours(t_utc))
        if prev_alt is not None:
            if prev_alt > -18.0 >= alt and evening_end is None:
                evening_end = t
            if prev_alt < -18.0 <= alt and evening_end is not None \
               and morning_start is None:
                morning_start = t
        prev_alt = alt
        t += dt.timedelta(minutes=2)
    return evening_end, morning_start


# ----------------------------------------------------------------------
# WEB FETCH HELPERS
# ----------------------------------------------------------------------

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class _TableParser(HTMLParser):
    """Generic HTML table parser: collects every <tr> as a list of cell
    texts, plus any hrefs found in each cell."""

    def __init__(self):
        super().__init__()
        self.rows = []          # list of (cells, hrefs) per row
        self._cells = None
        self._hrefs = None
        self._buf = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cells, self._hrefs = [], []
        elif tag in ("td", "th") and self._cells is not None:
            self._buf = []
        elif tag == "a" and self._buf is not None:
            for k, v in attrs:
                if k == "href":
                    self._hrefs.append(v)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._buf is not None:
            self._cells.append(" ".join("".join(self._buf).split()))
            self._buf = None
        elif tag == "tr" and self._cells is not None:
            if self._cells:
                self.rows.append((self._cells, self._hrefs))
            self._cells = None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)


def parse_html_tables(html):
    p = _TableParser()
    p.feed(html)
    return p.rows


# ----------------------------------------------------------------------
# LIVE TARGET SOURCES
# ----------------------------------------------------------------------

def fetch_supernovae(mag_bright=None, mag_faint=None, html=None):
    """Bright active supernovae from rochesterastronomy.org.

    Returns a list of dicts: name, host, ra_h, dec_deg, mag, sn_type,
    redshift, link, ra_str, dec_str. Filtered to the magnitude window
    and to declinations observable from the Nieves Observatory.
    Magnitudes flagged stale (>1 month old, marked '*') are skipped.
    """
    if mag_bright is None:
        mag_bright = LIMITS["sn_mag_bright"]
    if mag_faint is None:
        mag_faint = LIMITS["sn_mag_faint"]
    if html is None:
        html = http_get(URLS["rochester_active"])
    rows = parse_html_tables(html)
    # locate header row to map columns
    col = None
    out = []
    for cells, hrefs in rows:
        lowered = [c.lower() for c in cells]
        if col is None:
            if "r.a." in lowered and "decl." in lowered:
                col = {name: i for i, name in enumerate(lowered)}
            continue
        try:
            name = cells[col.get("sn", 0)]
            ra_s = cells[col["r.a."]]
            dec_s = cells[col["decl."]]
            mag_s = cells[col["latest mag"]]
            host = cells[col.get("host galaxy", 1)]
            sn_type = cells[col.get("type", 7)]
            z = cells[col.get("z", 8)]
        except (KeyError, IndexError):
            continue
        if "*" in mag_s:          # stale photometry
            continue
        m = re.search(r"(\d{1,2}\.\d)", mag_s)
        if not m:
            continue
        mag = float(m.group(1))
        if not (mag_bright <= mag <= mag_faint):
            continue
        try:
            ra_h = parse_ra_hours(ra_s)
            dec = parse_dec_deg(dec_s)
        except ValueError:
            continue
        if not (LIMITS["min_dec"] <= dec <= LIMITS["max_dec"]):
            continue
        link = URLS["rochester_main"]
        for h in hrefs:
            if h and not h.lower().startswith(("javascript", "#", "mailto")):
                link = urllib.parse.urljoin(URLS["rochester_active"], h)
                break
        out.append({
            "name": name, "host": host, "ra_h": ra_h, "dec_deg": dec,
            "ra_str": ra_s, "dec_str": dec_s, "mag": mag,
            "sn_type": sn_type, "redshift": z, "link": link,
        })
    out.sort(key=lambda x: x["mag"])
    return out


_SKYLIVE_ANCHOR_RE = re.compile(r"<a\b[^>]*?/[a-z0-9\-]+-info[^>]*>", re.I)
_HREF_RE = re.compile(
    r"href\s*=\s*[\"'](?:https?://(?:www\.)?theskylive\.com)?"
    r"/([a-z0-9\-]+)-info(?:#[\w\-]*)?[\"']", re.I)
_TITLE_RE = re.compile(
    r"title\s*=\s*[\"'](?:Comet|Asteroid|Dwarf\s+Planet)?\s*([^:\"']+)",
    re.I)


def parse_skylive_cards(html, log=None):
    """Parse theskylive.com list pages (comets, asteroids-and-dwarf-planets).

    These pages are a sequence of 'cards', one per object: anchor links
    to /<slug>-info (in any attribute order, with or without a title),
    followed by lines such as 'Magnitude: 8.6 (Observed - COBS)' and
    'J2000: 00h 09m 38s / +01deg 49' 36"'.

    Returns a list of dicts: slug, name, mag (float or None),
    ra_h, dec_deg (floats or None), link.
    """
    say = log or (lambda m: None)
    hits = []   # (position, slug, name-or-None)
    for m in _SKYLIVE_ANCHOR_RE.finditer(html):
        tag = m.group(0)
        hm = _HREF_RE.search(tag)
        if not hm:
            continue
        tm = _TITLE_RE.search(tag)
        hits.append((m.start(), hm.group(1),
                     tm.group(1).strip() if tm else None))
    # collapse consecutive duplicates (each card links to its page
    # several times: image, heading, Details link)
    cards = []
    for pos, slug, name in hits:
        if cards and cards[-1][1] == slug:
            if name and not cards[-1][2]:
                cards[-1] = (cards[-1][0], slug, name)
            continue
        cards.append((pos, slug, name))
    out = []
    seen = set()
    for i, (pos, slug, name) in enumerate(cards):
        if slug in seen:
            continue
        seen.add(slug)
        end = cards[i + 1][0] if i + 1 < len(cards) else min(
            len(html), pos + 8000)
        # The live pages put markup inside the values themselves, e.g.
        # 00<sup>h</sup> 09<sup>m</sup>, so strip all tags and decode
        # entities first, then parse the resulting plain text.
        seg = _html_mod.unescape(re.sub(r"<[^>]+>", " ", html[pos:end]))
        seg = " ".join(seg.split())
        mag = None
        mm = re.search(r"Magnitude\s*:?[^0-9\-]{0,12}(\d{1,2}\.\d)", seg)
        if mm:
            mag = float(mm.group(1))
        ra_h = dec = None
        coord_re = (r"(\d{1,2})\s*h\s*(\d{1,2})\s*m\s*(\d{1,2})\s*s\s*/?\s*"
                    r"([+\-\u2212]?\s*\d{1,3})\s*[\u00b0\u00ba]\s*(\d{1,2})"
                    r"(?:\s*[\u2019\u02b9']\s*(\d{1,2}))?")
        cm = re.search(r"J2000\s*:?\s*" + coord_re, seg)
        if not cm:   # fall back to the Apparent coordinates line
            cm = re.search(coord_re, seg)
        if cm:
            ra_h = (float(cm.group(1)) + float(cm.group(2)) / 60 +
                    float(cm.group(3)) / 3600)
            sd = cm.group(4).replace("\u2212", "-").replace(" ", "")
            sign = -1.0 if sd.startswith("-") else 1.0
            dec = sign * (abs(float(sd)) + float(cm.group(5)) / 60 +
                          (float(cm.group(6)) / 3600 if cm.group(6) else 0.0))
        if not name:
            name = slug.replace("-", " ")
        out.append({"slug": slug, "name": name, "mag": mag,
                    "ra_h": ra_h, "dec_deg": dec,
                    "link": f"{URLS['skylive_base']}/{slug}-info",
                    "excerpt": seg[:200]})
    say(f"  parsed {len(out)} objects from theskylive page "
        f"({len(html)} characters fetched)")
    if not out:
        first = " ".join(html[:300].split())
        say(f"  ! page yielded no object cards; it begins: {first}")
    return out


def fetch_comets(mag_limit=None, max_comets=5, list_html=None, log=print):
    """Bright comets from theskylive.com/comets. Coordinates (J2000) and
    magnitudes are read directly from the list page cards.
    Returns list of dicts: name, designation, mag, ra_h, dec_deg, link.
    """
    if mag_limit is None:
        mag_limit = LIMITS["comet_mag_limit"]
    if list_html is None:
        list_html = http_get(URLS["skylive_comets"])
    comet_slug = re.compile(r"^(c\d{4}[a-z0-9]+|x?\d{1,3}[pdi](\b|-)|"
                            r"\d+i-)", re.I)
    out = []
    for c in parse_skylive_cards(list_html, log=log):
        if not (comet_slug.match(c["slug"]) or
                re.search(r"(^|\b)(C/|P/|\d+[PDI]/)", c["name"])):
            continue   # not a comet card (nav links etc.)
        if c["mag"] is None or c["mag"] > mag_limit:
            continue
        if c["ra_h"] is None:
            log(f"  ! no coordinates parsed for {c['name']}; skipping")
            log(f"    card text begins: {c.get('excerpt','')[:160]}")
            continue
        out.append({"name": c["name"],
                    "designation": _comet_designation(c["name"]),
                    "mag": c["mag"], "ra_h": c["ra_h"],
                    "dec_deg": c["dec_deg"], "link": c["link"]})
        if len(out) >= max_comets:
            break
    out.sort(key=lambda x: x["mag"])
    return out


def fetch_asteroids(mag_limit=14.0, max_asteroids=5, list_html=None,
                    log=print):
    """Bright asteroids and dwarf planets from
    theskylive.com/asteroids-and-dwarf-planets, with J2000 coordinates
    and magnitudes read from the list page cards.
    Returns list of dicts: name, acp_name, mag, ra_h, dec_deg, link.
    """
    if list_html is None:
        list_html = http_get(URLS["skylive_asteroids"])
    comet_slug = re.compile(r"^(c\d{4}[a-z0-9]+|x?\d{1,3}[pdi](\b|-)|"
                            r"\d+i-)", re.I)
    not_asteroids = {"sun", "moon", "mercury", "venus", "mars", "jupiter",
                     "saturn", "uranus", "neptune"}
    out = []
    for c in parse_skylive_cards(list_html, log=log):
        name = c["name"]
        # asteroid cards are typically '4 Vesta', '1 Ceres', '3200
        # Phaethon'; skip comets/planets that may share the page layout
        if comet_slug.match(c["slug"]) or c["slug"] in not_asteroids:
            continue
        if re.search(r"(C/|P/\d{4}|\d+[PI]/)", name):
            continue
        if c["mag"] is None or c["mag"] > mag_limit:
            continue
        if c["ra_h"] is None:
            log(f"  ! no coordinates parsed for {name}; skipping "
                f"(card begins: {c.get('excerpt','')[:120]})")
            continue
        # ACP minor-planet target: strip a leading catalog number
        m = re.match(r"\d+\s+(.+)", name)
        acp_name = m.group(1) if m else name
        out.append({"name": name, "acp_name": acp_name, "mag": c["mag"],
                    "ra_h": c["ra_h"], "dec_deg": c["dec_deg"],
                    "link": c["link"]})
        if len(out) >= max_asteroids:
            break
    out.sort(key=lambda x: x["mag"])
    return out


def _comet_designation(name):
    """'C/2025 R2 (SWAN)' -> 'C/2025 R2'; '12P/Pons-Brooks' unchanged."""
    m = re.match(r"((?:C|P|I)/\d{4}\s+[A-Z]+\d*)", name)
    if m:
        return m.group(1)
    m = re.match(r"(\d+[PI]/[\w\-'. ]+)", name)
    if m:
        return m.group(1).strip()
    return name


def fetch_transits(date_local, tz, max_vmag=None, min_depth=None,
                   csv_text=None, log=None):
    """Tonight's observable exoplanet transits from the Swarthmore
    Transit Finder (Eric Jensen's Tapir), as CSV.

    Returns list of dicts: name, vmag, start/mid/end (local datetime),
    duration_hr, depth_ppt, ra_h, dec_deg, ra_str, dec_str, link.
    Pass log=print (or any callable) for step-by-step diagnostics.
    """
    say = log or (lambda m: None)
    if max_vmag is None:
        max_vmag = LIMITS["transit_max_vmag"]
    if min_depth is None:
        min_depth = LIMITS["transit_min_depth_ppt"]
    if csv_text is None:
        params = {
            "observatory_string": "Specified_Lat_Long",
            "use_utc": "0",
            "observatory_latitude": f"{OBSERVATORY['latitude']:.4f}",
            "observatory_longitude": f"{OBSERVATORY['longitude']:.4f}",
            "timezone": OBSERVATORY["timezone"],
            "start_date": date_local.strftime("%m-%d-%Y"),
            "days_to_print": "1",
            "days_in_past": "0",
            "minimum_start_elevation": "30",
            "minimum_end_elevation": "30",
            "and_vs_or": "or",   # above 30 deg at start OR end (less strict)
            "minimum_ha": "-12",
            "maximum_ha": "12",
            "baseline_hrs": "1",
            "minimum_depth": str(min_depth),
            "maximum_V_mag": str(max_vmag),
            "target_string": "",
            "single_object": "0",
            "print_html": "2",     # 2 = raw CSV
            "twilight": "-12",
            "max_airmass": "2.4",
        }
        url = URLS["swarthmore_csv"] + "?" + urllib.parse.urlencode(params)
        say(f"  transit query: {url}")
        csv_text = http_get(url, timeout=90)
        say(f"  response: {len(csv_text)} characters")
    first_line = csv_text.splitlines()[0] if csv_text.strip() else "(empty)"
    if not first_line.lower().lstrip("\ufeff").startswith("name"):
        say("  ! response does not look like the expected CSV; "
            f"first line is: {first_line[:160]}")
    reader = csv.DictReader(csv_text.lstrip("\ufeff").splitlines())
    fields = reader.fieldnames or []
    say(f"  CSV columns: {fields}")

    # Resolve columns by normalized name so the parser survives
    # capitalization, spacing, and small wording changes on the server.
    def _norm(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    nmap = {_norm(f): f for f in fields}

    def col(*candidates, contains=None):
        for c in candidates:
            if _norm(c) in nmap:
                return nmap[_norm(c)]
        if contains:
            for f in fields:
                if contains in _norm(f):
                    return f
        return None

    k_name = col("Name") or (fields[0] if fields else None)
    k_v = col("V", "Vmag", "V mag", contains="vmag") or col("V")
    k_coords = col("coords(J2000)", contains="coord")
    k_depth = col("depth(ppt)", contains="depth")
    k_dur = col("duration(hours)", contains="duration")
    k_start = col("start time", "start_time", contains="starttime")
    k_mid = col("mid time", "mid_time", contains="midtime")
    k_end = col("end time", "end_time", contains="endtime")
    missing = [lbl for lbl, k in (("name", k_name), ("V", k_v),
                                  ("coords", k_coords), ("depth", k_depth),
                                  ("duration", k_dur), ("start", k_start),
                                  ("mid", k_mid), ("end", k_end)) if not k]
    if missing:
        say(f"  ! could not identify CSV column(s): {', '.join(missing)}")

    out = []
    skipped = {"no V/depth": 0, "V too faint": 0, "bad coords": 0,
               "bad times": 0}
    for r in reader:
        try:
            name = r[k_name].strip()
            vmag = float(r[k_v])
            coords = r[k_coords].strip()
            depth = float(r[k_depth])
            dur = float(r[k_dur])
        except (KeyError, ValueError, TypeError, AttributeError):
            skipped["no V/depth"] += 1
            continue
        if vmag > max_vmag:
            skipped["V too faint"] += 1
            continue
        cm = re.match(r"(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
                      r"([+-]?\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)", coords)
        if not cm:
            skipped["bad coords"] += 1
            continue
        ra_str, dec_str = cm.group(1), cm.group(2)
        # Tapir formats output dates as YYYY-MM-DD (DateTime->ymd) with
        # HH:MM times; accept a few variants defensively, including
        # bare HH:MM (assumed to be the requested night).
        times = {}
        ok = True
        for key, kk in (("start time", k_start), ("mid time", k_mid),
                        ("end time", k_end)):
            raw = (r.get(kk) or "").strip()
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
                        "%m-%d-%Y %H:%M", "%m/%d/%Y %H:%M"):
                try:
                    parsed = dt.datetime.strptime(raw, fmt).replace(tzinfo=tz)
                    break
                except ValueError:
                    continue
            if parsed is None and re.fullmatch(r"\d{1,2}:\d{2}", raw):
                hh, mm_ = map(int, raw.split(":"))
                parsed = dt.datetime.combine(
                    date_local, dt.time(hh, mm_), tzinfo=tz)
                if hh < 12:          # past-midnight times belong to the
                    parsed += dt.timedelta(days=1)   # following morning
            if parsed is None:
                ok = False
            else:
                times[key] = parsed
        if not ok:
            skipped["bad times"] += 1
            continue
        out.append({
            "name": name, "vmag": vmag,
            "start": times["start time"], "mid": times["mid time"],
            "end": times["end time"], "duration_hr": dur,
            "depth_ppt": depth,
            "ra_h": parse_ra_hours(ra_str), "dec_deg": parse_dec_deg(dec_str),
            "ra_str": ra_str[:8], "dec_str": dec_str[:9],
            "pct_transit": r.get("percent_transit_observable", ""),
            "link": "https://astro.swarthmore.edu/transits.cgi",
        })
    say(f"  parsed {len(out)} transit events"
        + (f"; skipped {skipped}" if any(skipped.values()) else ""))
    out.sort(key=lambda x: x["start"])
    return out


# ----------------------------------------------------------------------
# CATALOG
# ----------------------------------------------------------------------

def load_catalog(path=CATALOG_FILE):
    cat = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["ra_h"] = parse_ra_hours(r["ra"])
                r["dec_deg"] = parse_dec_deg(r["dec"])
                r["mag_f"] = float(r["mag"])
            except ValueError:
                continue
            cat.append(r)
    return cat


def select_dso(catalog, cls, n, t_start_utc, t_end_utc, mag_limit=None,
               exclude=None):
    """Pick the n 'best' visible objects of a class: brightest first,
    preferring objects with common names (more engaging for students),
    all above the altitude limit somewhere in the window."""
    if mag_limit is None:
        mag_limit = LIMITS["dso_mag_limit"]
    exclude = exclude or set()
    pool = []
    for obj in catalog:
        if obj["class"] != cls or obj["mag_f"] > mag_limit:
            continue
        if obj["name"] in exclude:
            continue
        vis, best_alt, _ = visible_during_window(
            obj["ra_h"], obj["dec_deg"], t_start_utc, t_end_utc)
        if vis:
            pool.append((obj, best_alt))
    # rank: named objects first, then brighter, then higher
    pool.sort(key=lambda p: (0 if p[0]["common_names"] else 1,
                             p[0]["mag_f"], -p[1]))
    return [p[0] for p in pool[:n]]


# ----------------------------------------------------------------------
# PLAN BUILDING
# ----------------------------------------------------------------------

def _block_lines(profile, target_line, comment=None, extra_directives=None):
    lines = []
    if comment:
        for c in comment.splitlines():
            lines.append(f"; {c}")
    lines.append("#posang 0")
    lines.append("#count " + ",".join(str(c) for c in profile["count"]))
    lines.append("#interval " + ",".join(str(i) for i in profile["interval"]))
    lines.append("#binning " + ",".join(str(b) for b in profile["binning"]))
    lines.append("#filter " + ",".join(profile["filter"]))
    if extra_directives:
        lines.extend(extra_directives)
    lines.append(target_line)
    return lines


def sort_targets(targets, t_start_utc):
    """Order targets by RA beginning at the western edge of the sky
    (about three hours past the meridian) at the start of the window,
    so objects about to set are observed first. Targets with unknown
    positions (name-resolved asteroids) go last. This single function
    defines the order used by both the plan and the catalog display."""
    lst0 = lst_hours(t_start_utc)
    origin = (lst0 - 3.0) % 24.0

    def sort_key(t):
        if t.get("ra_h") is None:
            return 99.0
        return (t["ra_h"] - origin) % 24.0

    return sorted(targets, key=sort_key)


def annotate_best_times(targets, t_start_utc, t_end_utc, tz):
    """Attach a human-readable local 'time_str' to each target: for
    transits, the transit window; for fixed targets, the local time at
    which the object is highest during the window (with its altitude);
    for name-resolved moving targets, a placeholder."""
    for t in targets:
        if t["class"] == "transit":
            event = t.get("event", "full")
            if event == "ingress":
                t["time_str"] = (f"{t['start'].strftime('%H:%M')} "
                                 "ingress (falling)")
            elif event == "egress":
                t["time_str"] = (f"{t['end'].strftime('%H:%M')} "
                                 "egress (rising)")
            else:
                t["time_str"] = (f"{t['start'].strftime('%H:%M')}-"
                                 f"{t['end'].strftime('%H:%M')} full transit")
        elif t.get("ra_h") is None:
            t["time_str"] = "(ACP resolves)"
        else:
            _, best_alt, best_t = visible_during_window(
                t["ra_h"], t["dec_deg"], t_start_utc, t_end_utc, samples=25)
            local = best_t.astimezone(tz)
            t["time_str"] = f"{local.strftime('%H:%M')} ({best_alt:.0f}\u00b0)"
            t["best_alt"] = best_alt
    return targets


def build_plan(targets, t_start_utc, tz, include_header=True,
               include_shutdown=True):
    """targets: list of dicts with keys
         class  -- one of FILTER_PROFILES keys
         name   -- display name / ACP target name
         ra_h, dec_deg -- may be None for asteroids
         plus class-specific fields.
    Returns the plan text, with targets ordered by sort_targets().
    Transits keep their RA slot but carry a #WAITUNTIL directive.
    """
    lst0 = lst_hours(t_start_utc)
    ordered = sort_targets(targets, t_start_utc)

    out = []
    if include_header:
        local = t_start_utc.astimezone(tz)
        out += [
            f"; ACP observing plan -- {OBSERVATORY['name']}",
            f"; Generated {dt.datetime.now(tz).strftime('%Y-%m-%d %H:%M %Z')}",
            f"; Observing window starts {local.strftime('%Y-%m-%d %H:%M %Z')}"
            f"  (LST {ra_hours_to_hms(lst0)})",
            "; Targets sorted by RA from the western horizon eastward.",
            "",
            "#AUTOFOCUS",
            "#TRACKON",
            "",
        ]

    for t in ordered:
        cls = t["class"]
        if cls == "transit":
            out += _transit_block(t, tz)
        elif cls in ("comet", "asteroid"):
            prefix = "CT" if cls == "comet" else "MP"
            label = t.get("designation") or t.get("acp_name") or t["name"]
            comment = t.get("comment", f"{cls.title()}: {t['name']}")
            out += _block_lines(FILTER_PROFILES[cls], f"{prefix} {label}",
                                comment=comment)
            out.append("#WAITINLIMITS 60")
        elif cls == "planet":
            out += _block_lines(FILTER_PROFILES[cls], t["name"],
                                comment=f"Planet: {t['name']}")
            out.append("#WAITINLIMITS 60")
        elif cls == "supernova":
            comment = (f"Supernova {t['name']} in {t.get('host','?')}  "
                       f"Type {t.get('sn_type','?')}  mag {t.get('mag','?')}  "
                       f"z={t.get('redshift','?')}")
            target_line = (f"{t['name'].replace(' ', '_')}\t"
                           f"{t['ra_str']}\t{t['dec_str']}")
            out += _block_lines(FILTER_PROFILES[cls], target_line,
                                comment=comment)
        else:  # galaxy / cluster / nebula from catalog
            bits = [f"{t.get('type','')}", f"mag {t.get('mag','')}"]
            if t.get("size_arcmin"):
                bits.append(f"size {t['size_arcmin']}'")
            if t.get("common_names"):
                bits.append(t["common_names"])
            comment = "  ".join(b for b in bits if b)
            out += _block_lines(FILTER_PROFILES[cls], t["name"],
                                comment=comment)
        out.append("")

    if include_shutdown:
        out.append("#SHUTDOWN")
    return "\n".join(out) + "\n"


def _transit_block(t, tz):
    """Exoplanet transit block. For event='full', covers the whole
    transit with baseline either side. For 'ingress'/'egress', takes a
    short-exposure time series for 15 minutes on each side of the edge."""
    event = t.get("event", "full")
    if event in ("ingress", "egress"):
        prof = FILTER_PROFILES["transit_edge"]
        pad_min = prof["minutes_each_side"]
        edge = t["start"] if event == "ingress" else t["end"]
        obs_start = edge - dt.timedelta(minutes=pad_min)
        obs_end = edge + dt.timedelta(minutes=pad_min)
        direction = ("brightness FALLING into transit" if event == "ingress"
                     else "brightness RISING out of transit")
        n = max(5, int((obs_end - obs_start).total_seconds()
                       // prof["interval"]))
        name = t["name"].replace(" ", "_")
        return [
            f"; EXOPLANET TRANSIT {event.upper()}: {t['name']}  "
            f"V={t['vmag']}  depth {t['depth_ppt']} ppt",
            f"; Edge at {edge.strftime('%H:%M %Z')} local -- {direction}.",
            f"; Time series {obs_start.strftime('%H:%M')} -> "
            f"{obs_end.strftime('%H:%M')} "
            f"({pad_min} min each side of the edge).",
            f"; Full transit {t['start'].strftime('%H:%M')} -> "
            f"{t['end'].strftime('%H:%M')}, duration {t['duration_hr']:.2f} h.",
            "; NOTE: WAITUNTIL pauses the queue -- schedule sparingly.",
            f"#WAITUNTIL 1, {obs_start.strftime('%m/%d/%Y %H:%M:%S')}",
            "#posang 0",
            f"#count {n}",
            f"#interval {prof['interval']}",
            f"#binning {prof['binning']}",
            f"#filter {prof['filter']}",
            f"{name}\t{t['ra_str']}\t{t['dec_str']}",
        ]
    prof = FILTER_PROFILES["transit"]
    baseline_min = 30
    obs_start = t["start"] - dt.timedelta(minutes=baseline_min)
    obs_end = t["end"] + dt.timedelta(minutes=baseline_min)
    n = max(5, int((obs_end - obs_start).total_seconds() // prof["interval"]))
    name = t["name"].replace(" ", "_")
    lines = [
        f"; EXOPLANET TRANSIT (full): {t['name']}  V={t['vmag']}  "
        f"depth {t['depth_ppt']} ppt",
        f"; Transit {t['start'].strftime('%H:%M')} -> "
        f"{t['end'].strftime('%H:%M %Z')} "
        f"(mid {t['mid'].strftime('%H:%M')}), duration "
        f"{t['duration_hr']:.2f} h",
        f"; Observation includes {baseline_min} min baseline either side.",
        "; NOTE: WAITUNTIL pauses the queue -- schedule sparingly.",
        f"#WAITUNTIL 1, {obs_start.strftime('%m/%d/%Y %H:%M:%S')}",
        "#posang 0",
        f"#count {n}",
        f"#interval {prof['interval']}",
        f"#binning {prof['binning']}",
        f"#filter {prof['filter']}",
        f"{name}\t{t['ra_str']}\t{t['dec_str']}",
    ]
    return lines


# ----------------------------------------------------------------------
# HIGH-LEVEL ASSEMBLY (shared by GUI and CLI)
# ----------------------------------------------------------------------

def assemble_targets(date_local, start_time, end_time, counts,
                     sn_mag_range=None, comet_mag_limit=None,
                     transit_vmag=None, transit_depth=None,
                     asteroid_names=None, log=print):
    """counts: dict with keys galaxies, nebulae, clusters, supernovae,
    comets, asteroids, planets, transits (ints).
    Returns (targets, t_start_utc, t_end_utc, tz, messages)."""
    tz = ZoneInfo(OBSERVATORY["timezone"]) if ZoneInfo else dt.timezone(
        dt.timedelta(hours=-8))
    t_start = dt.datetime.combine(date_local, start_time, tzinfo=tz)
    t_end = dt.datetime.combine(date_local, end_time, tzinfo=tz)
    if t_end <= t_start:
        t_end += dt.timedelta(days=1)     # window crosses midnight
    t_start_utc = t_start.astimezone(dt.timezone.utc)
    t_end_utc = t_end.astimezone(dt.timezone.utc)

    targets = []

    # --- deep-sky from catalog
    catalog = load_catalog()
    for cls, key in (("galaxy", "galaxies"), ("nebula", "nebulae"),
                     ("cluster", "clusters")):
        n = counts.get(key, 0)
        if n > 0:
            picks = select_dso(catalog, cls, n, t_start_utc, t_end_utc)
            log(f"Selected {len(picks)} {key} from catalog.")
            for p in picks:
                targets.append({**p, "class": cls, "source": "OpenNGC",
                                "link": URLS["simbad"].format(
                                    ident=urllib.parse.quote(p["catalog_id"]))})

    # --- supernovae (live)
    n = counts.get("supernovae", 0)
    if n > 0:
        lo, hi = sn_mag_range or (LIMITS["sn_mag_bright"],
                                  LIMITS["sn_mag_faint"])
        try:
            sne = fetch_supernovae(lo, hi)
            chosen = []
            for sn in sne:
                vis, _, _ = visible_during_window(
                    sn["ra_h"], sn["dec_deg"], t_start_utc, t_end_utc)
                if vis:
                    chosen.append(sn)
                if len(chosen) >= n:
                    break
            log(f"Supernovae: {len(sne)} in mag {lo}-{hi}; "
                f"{len(chosen)} visible tonight.")
            for sn in chosen:
                targets.append({**sn, "class": "supernova",
                                "source": "Rochester"})
        except Exception as exc:
            log(f"! Supernova fetch failed: {exc}")

    # --- comets (live)
    n = counts.get("comets", 0)
    if n > 0:
        try:
            comets = fetch_comets(comet_mag_limit, max_comets=n * 3, log=log)
            chosen = []
            for c in comets:
                vis, _, _ = visible_during_window(
                    c["ra_h"], c["dec_deg"], t_start_utc, t_end_utc)
                if vis:
                    chosen.append(c)
                if len(chosen) >= n:
                    break
            log(f"Comets: {len(comets)} bright; {len(chosen)} visible.")
            for c in chosen:
                targets.append({**c, "class": "comet", "source": "TheSkyLive",
                                "comment": f"Comet {c['name']}  "
                                           f"mag {c['mag']}"})
        except Exception as exc:
            log(f"! Comet fetch failed: {exc}")

    # --- transits (live): full transits when they fit, otherwise an
    # ingress or egress "edge" observation (15 min each side)
    n = counts.get("transits", 0)
    if n > 0:
        try:
            trs = fetch_transits(date_local, tz, transit_vmag, transit_depth,
                                 log=log)
            pad = dt.timedelta(
                minutes=FILTER_PROFILES["transit_edge"]["minutes_each_side"])
            chosen = []
            for t in trs:
                overlap = (min(t["end"], t_end) -
                           max(t["start"], t_start)).total_seconds()
                frac = max(0.0, overlap) / max(
                    1.0, (t["end"] - t["start"]).total_seconds())
                event = None
                if frac >= 0.9:
                    event = "full"
                elif (t_start <= t["start"] - pad
                      and t["start"] + pad <= t_end):
                    event = "ingress"     # brightness falling
                elif (t_start <= t["end"] - pad
                      and t["end"] + pad <= t_end):
                    event = "egress"      # brightness rising
                tag = event if event and len(chosen) < n else (
                    "no usable event in window" if not event else "quota full")
                log(f"    {t['name']:18s} V={t['vmag']:.1f} "
                    f"{t['start'].strftime('%H:%M')}-"
                    f"{t['end'].strftime('%H:%M')} "
                    f"depth {t['depth_ppt']:.0f} ppt  [{tag}]")
                if event and len(chosen) < n:
                    chosen.append({**t, "class": "transit", "event": event,
                                   "source": "Swarthmore"})
            log(f"Transits: {len(trs)} tonight; using {len(chosen)} "
                f"({', '.join(c['event'] for c in chosen) or 'none'}).")
            targets.extend(chosen)
        except Exception as exc:
            log(f"! Transit fetch failed: {exc}")

    # --- planets (computed visibility)
    n = counts.get("planets", 0)
    if n > 0:
        mid = t_start_utc + (t_end_utc - t_start_utc) / 2
        vis_planets = []
        for p in PLANETS:
            ra, dec = planet_radec(p, mid)
            vis, best_alt, _ = visible_during_window(
                ra, dec, t_start_utc, t_end_utc)
            if vis:
                vis_planets.append((p, ra, dec, best_alt))
        vis_planets.sort(key=lambda x: -x[3])
        log(f"Planets visible: {', '.join(p[0] for p in vis_planets) or 'none'}")
        for p, ra, dec, _ in vis_planets[:n]:
            targets.append({"class": "planet", "name": p, "ra_h": ra,
                            "dec_deg": dec, "source": "computed",
                            "mag": "", "type": "Planet",
                            "link": f"https://theskylive.com/{p.lower()}-info"})

    # --- asteroids (live from theskylive; ACP still resolves the
    # precise ephemeris at run time via the MP target line)
    n = counts.get("asteroids", 0)
    if n > 0:
        try:
            asts = fetch_asteroids(mag_limit=14.0, max_asteroids=n * 4,
                                   log=log)
            chosen = []
            for a in asts:
                vis, _, _ = visible_during_window(
                    a["ra_h"], a["dec_deg"], t_start_utc, t_end_utc)
                if vis:
                    chosen.append(a)
                if len(chosen) >= n:
                    break
            log(f"Asteroids: {len(asts)} bright; {len(chosen)} visible.")
            for a in chosen:
                targets.append({**a, "class": "asteroid",
                                "source": "TheSkyLive", "type": "Asteroid",
                                "comment": f"Asteroid {a['name']}  "
                                           f"mag {a['mag']}"})
            if not chosen:
                raise RuntimeError("no asteroids from live fetch")
        except Exception as exc:
            log(f"! Asteroid live fetch unavailable ({exc}); "
                f"using built-in bright list instead.")
            for a in (asteroid_names or BRIGHT_ASTEROIDS)[:n]:
                targets.append({"class": "asteroid", "name": a,
                                "acp_name": a, "ra_h": None,
                                "dec_deg": None, "source": "built-in list",
                                "mag": "", "type": "Asteroid",
                                "comment": f"Asteroid {a} (ACP resolves "
                                           f"position; WAITINLIMITS guards)",
                                "link": URLS["skylive_asteroids"]})

    targets = sort_targets(targets, t_start_utc)
    annotate_best_times(targets, t_start_utc, t_end_utc, tz)
    return targets, t_start_utc, t_end_utc, tz


def thumbnail_url(ra_h, dec_deg, fov_deg=0.4, size=180):
    return URLS["hips2fits"].format(w=size, h=size, fov=fov_deg,
                                    ra=ra_h * 15.0, dec=dec_deg)


# ----------------------------------------------------------------------
# COMMAND-LINE (headless) MODE -- also the entry point for the future
# GitHub Pages pipeline.
# ----------------------------------------------------------------------

def run_cli(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Nieves Observatory ACP plan "
                                             "generator (headless mode)")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--start", default="20:30", help="local start HH:MM")
    ap.add_argument("--end", default="04:30", help="local end HH:MM")
    for k in ("galaxies", "nebulae", "clusters", "supernovae", "comets",
              "asteroids", "planets", "transits"):
        ap.add_argument(f"--{k}", type=int, default=0)
    ap.add_argument("--out", default="nieves_plan.txt")
    ap.add_argument("--json", default=None,
                    help="also write the target list as JSON (for web use)")
    ap.add_argument("--test-transits", action="store_true",
                    help="diagnostic: query the Swarthmore Transit Finder "
                         "only and print everything found")
    ap.add_argument("--test-sources", action="store_true",
                    help="diagnostic: test all four live sources "
                         "(supernovae, comets, asteroids, transits) and "
                         "report exactly what each one returns")
    a = ap.parse_args(argv)

    date_local = (dt.date.fromisoformat(a.date) if a.date
                  else dt.date.today())
    tz = (ZoneInfo(OBSERVATORY["timezone"]) if ZoneInfo
          else dt.timezone(dt.timedelta(hours=-8)))

    if a.test_sources:
        print(f"=== Live source diagnostics for {date_local} ===")
        print("\n[1/4] Supernovae (rochesterastronomy.org)")
        try:
            html = http_get(URLS["rochester_active"])
            print(f"  fetched {len(html)} characters")
            sne = fetch_supernovae(html=html)
            print(f"  {len(sne)} SNe in mag "
                  f"{LIMITS['sn_mag_bright']}-{LIMITS['sn_mag_faint']}:")
            for s in sne[:8]:
                print(f"    {s['name']:12s} mag {s['mag']:4.1f} "
                      f"in {s['host'][:22]:22s} RA {s['ra_str'][:8]} "
                      f"-> {s['link']}")
        except Exception as exc:
            print(f"  FETCH FAILED: {type(exc).__name__}: {exc}")
        print("\n[2/4] Comets (theskylive.com/comets)")
        try:
            comets = fetch_comets(max_comets=8, log=print)
            for c in comets:
                print(f"    {c['designation']:16s} mag {c['mag']:4.1f}  "
                      f"RA {ra_hours_to_hms(c['ra_h'])} "
                      f"Dec {dec_deg_to_dms(c['dec_deg'])}  {c['link']}")
            if not comets:
                print("    (none passed the magnitude limit "
                      f"{LIMITS['comet_mag_limit']})")
        except Exception as exc:
            print(f"  FETCH FAILED: {type(exc).__name__}: {exc}")
        print("\n[3/4] Asteroids (theskylive.com/asteroids-and-dwarf-planets)")
        try:
            asts = fetch_asteroids(max_asteroids=8, log=print)
            for x in asts:
                print(f"    {x['name']:18s} mag {x['mag']:4.1f}  "
                      f"RA {ra_hours_to_hms(x['ra_h'])} "
                      f"Dec {dec_deg_to_dms(x['dec_deg'])}  (MP "
                      f"{x['acp_name']})")
            if not asts:
                print("    (none parsed/passed limits)")
        except Exception as exc:
            print(f"  FETCH FAILED: {type(exc).__name__}: {exc}")
        print("\n[4/4] Exoplanet transits (Swarthmore Transit Finder)")
        try:
            trs = fetch_transits(date_local, tz, log=print)
            for t in trs:
                print(f"    {t['name']:20s} V={t['vmag']:4.1f}  "
                      f"{t['start'].strftime('%H:%M')}-"
                      f"{t['end'].strftime('%H:%M')}  "
                      f"depth {t['depth_ppt']:.0f} ppt")
            if not trs:
                print("    (no events passed the server-side filters "
                      f"V<{LIMITS['transit_max_vmag']}, "
                      f"depth>{LIMITS['transit_min_depth_ppt']} ppt)")
        except Exception as exc:
            print(f"  FETCH FAILED: {type(exc).__name__}: {exc}")
            print("  If this is an SSL certificate error on macOS: "
                  "pip3 install certifi, or run Python's "
                  "'Install Certificates.command'.")
        print("\n=== End diagnostics ===")
        return

    if a.test_transits:
        print(f"Transit Finder diagnostic for {date_local} "
              f"(V<{LIMITS['transit_max_vmag']}, "
              f"depth>{LIMITS['transit_min_depth_ppt']} ppt):")
        try:
            trs = fetch_transits(date_local, tz, log=print)
        except Exception as exc:
            print(f"\n  FETCH FAILED: {type(exc).__name__}: {exc}")
            print("  If this is an SSL certificate error on macOS, run the "
                  "'Install Certificates.command' that ships with Python, "
                  "or: pip3 install certifi")
            return
        if not trs:
            print("  Server reachable but no events passed the filters; "
                  "try a fainter V limit or smaller depth in LIMITS.")
        for t in trs:
            print(f"  {t['name']:20s} V={t['vmag']:5.1f}  "
                  f"{t['start'].strftime('%Y-%m-%d %H:%M')} -> "
                  f"{t['end'].strftime('%H:%M')}  "
                  f"depth {t['depth_ppt']:.1f} ppt  "
                  f"RA {t['ra_str']} Dec {t['dec_str']}")
        return

    start = dt.time.fromisoformat(a.start)
    end = dt.time.fromisoformat(a.end)
    counts = {k: getattr(a, k) for k in ("galaxies", "nebulae", "clusters",
                                         "supernovae", "comets", "asteroids",
                                         "planets", "transits")}
    targets, t0, t1, tz = assemble_targets(date_local, start, end, counts)
    plan = build_plan(targets, t0, tz)
    with open(a.out, "w") as f:
        f.write(plan)
    print(f"\nPlan with {len(targets)} targets written to {a.out}")
    if a.json:
        ser = []
        for t in targets:
            row = {k: v for k, v in t.items()
                   if isinstance(v, (str, int, float, type(None)))}
            if t.get("ra_h") is not None:
                row["thumbnail"] = thumbnail_url(t["ra_h"], t["dec_deg"])
            ser.append(row)
        with open(a.json, "w") as f:
            json.dump({"generated": dt.datetime.now().isoformat(),
                       "observatory": OBSERVATORY["name"],
                       "targets": ser}, f, indent=2)
        print(f"Target JSON written to {a.json}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_cli(sys.argv[1:])
    else:
        from nieves_gui import main as gui_main
        gui_main()
