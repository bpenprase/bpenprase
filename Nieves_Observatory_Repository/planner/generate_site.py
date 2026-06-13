"""
Nieves Observatory -- nightly website generator
================================================
Runs the observing planner headlessly and writes the data files that the
public "Tonight at the Nieves Observatory" page reads:

    <outdir>/targets.json     all of tonight's candidate targets, with
                              coordinates, magnitudes, thumbnails,
                              best times, and hourly altitude tracks
    <outdir>/tonight_plan.txt a complete ACP plan for every target,
                              offered on the page as a download

Designed to run inside a GitHub Actions workflow every afternoon, but it
runs identically on a laptop:

    python generate_site.py --outdir site

Requires nieves_planner.py and nieves_catalog.csv in the same folder.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nieves_planner as planner

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# How many of each object class to offer on the page. This is a menu,
# not a plan, so it is deliberately generous; students narrow it down.
SITE_COUNTS = {
    "galaxies": 24, "nebulae": 14, "clusters": 14,
    "supernovae": 6, "comets": 6, "asteroids": 6,
    "planets": 7, "transits": 4,
}


def hourly_altitudes(ra_h, dec_deg, t0_utc, t1_utc, tz):
    """Altitude of a fixed target at each whole local hour in the
    window. Returns a list of {"t": "22:00", "alt": 41} dicts."""
    out = []
    # first whole hour at or after t0
    local = t0_utc.astimezone(tz)
    t = local.replace(minute=0, second=0, microsecond=0)
    if t < local:
        t += dt.timedelta(hours=1)
    end = t1_utc.astimezone(tz)
    while t <= end:
        alt = planner.altitude_deg(ra_h, dec_deg,
                                   planner.lst_hours(
                                       t.astimezone(dt.timezone.utc)))
        out.append({"t": t.strftime("%H:%M"), "alt": round(alt)})
        t += dt.timedelta(hours=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="site")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    a = ap.parse_args()

    tz = (ZoneInfo(planner.OBSERVATORY["timezone"]) if ZoneInfo
          else dt.timezone(dt.timedelta(hours=-8)))
    date_local = (dt.date.fromisoformat(a.date) if a.date
                  else dt.datetime.now(tz).date())

    print(f"Generating site data for the night of {date_local} ...")
    evening, morning = planner.twilight_times(date_local, tz)
    start = evening.time() if evening else dt.time(20, 30)
    end = morning.time() if morning else dt.time(4, 30)
    print(f"Astronomical darkness: {start.strftime('%H:%M')} -> "
          f"{end.strftime('%H:%M')} local")

    targets, t0, t1, tz = planner.assemble_targets(
        date_local, start, end, SITE_COUNTS, log=print)

    plan_text = planner.build_plan(targets, t0, tz)

    hours = []   # the page's shared hour axis
    local = t0.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    if local < t0.astimezone(tz):
        local += dt.timedelta(hours=1)
    while local <= t1.astimezone(tz):
        hours.append(local.strftime("%H:%M"))
        local += dt.timedelta(hours=1)

    ser = []
    for t in targets:
        row = {
            "name": t.get("name", ""),
            "class": t["class"],
            "type": t.get("type") or t["class"].title(),
            "mag": t.get("mag", t.get("vmag", "")),
            "size": t.get("size_arcmin", ""),
            "time_str": t.get("time_str", ""),
            "best_alt": round(t.get("best_alt", 0)) if t.get("best_alt")
                        else None,
            "link": t.get("link", ""),
            "source": t.get("source", ""),
        }
        if t["class"] == "supernova":
            row["type"] = f"Supernova {t.get('sn_type', '')}".strip()
            row["notes"] = (f"in {t.get('host', '?')}  "
                            f"(z = {t.get('redshift', '?')})")
        elif t["class"] == "transit":
            ev = t.get("event", "full")
            row["type"] = "Exoplanet transit"
            row["notes"] = (f"{ev} event, depth {t.get('depth_ppt', '?')} "
                            f"ppt, V = {t.get('vmag', '?')}")
            row["mag"] = t.get("vmag", "")
        else:
            row["notes"] = (t.get("common_names") or
                            t.get("comment", "") or "")
        if t.get("ra_h") is not None:
            row["ra"] = planner.ra_hours_to_hms(t["ra_h"])
            row["dec"] = planner.dec_deg_to_dms(t["dec_deg"])
            row["ra_h"] = round(t["ra_h"], 3)
            if t["class"] != "planet":
                row["thumb"] = planner.thumbnail_url(
                    t["ra_h"], t["dec_deg"], fov_deg=0.45, size=320)
            row["alts"] = hourly_altitudes(t["ra_h"], t["dec_deg"],
                                           t0, t1, tz)
        ser.append(row)

    lst0 = planner.lst_hours(t0)
    data = {
        "observatory": planner.OBSERVATORY["name"],
        "generated": dt.datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z"),
        "night_of": date_local.isoformat(),
        "window": {
            "start": t0.astimezone(tz).strftime("%H:%M"),
            "end": t1.astimezone(tz).strftime("%H:%M"),
            "lst_start": planner.ra_hours_to_hms(lst0),
        },
        "hours": hours,
        "min_altitude": planner.LIMITS["min_altitude_deg"],
        "targets": ser,
    }

    os.makedirs(a.outdir, exist_ok=True)
    json_path = os.path.join(a.outdir, "targets.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    plan_path = os.path.join(a.outdir, "tonight_plan.txt")
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(plan_text)
    print(f"\nWrote {json_path} ({len(ser)} targets) and {plan_path}")


if __name__ == "__main__":
    main()
