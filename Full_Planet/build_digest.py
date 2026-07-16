#!/usr/bin/env python3
"""
Full Planet — daily digest builder.

Reads the RSS/Atom feeds defined in feeds.py, sorts recent items into four
"exponential technology" channels, and writes docs/data/digest.json for the
static site to render.

No API keys required. Pure standard-library plus feedparser.
Run locally:  python build_digest.py
On GitHub:    runs automatically each day via the Actions workflow.
"""

import json
import re
import html
import datetime as dt
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import feedparser

from feeds import CHANNELS

# ---- tuning knobs -----------------------------------------------------------
MAX_ITEMS_PER_CHANNEL = 24      # how many headlines to show per channel
LOOKBACK_DAYS = 14             # ignore anything older than this
SNIPPET_CHARS = 220           # target length of the one-to-two sentence blurb
FETCH_TIMEOUT = 25            # seconds to wait per feed before giving up
# A real browser-like User-Agent. Several major outlets (Scientific American,
# BBC, and others) reject or throttle the default Python/feedparser agent, so
# we present a normal browser UA to fetch the feed bytes ourselves.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 FullPlanet/1.0 (+https://github.com)"
)
# -----------------------------------------------------------------------------


def fetch_feed(url: str):
    """
    Fetch a feed's raw bytes with a browser-like User-Agent, following
    redirects, then hand the content to feedparser. Returns a parsed feed
    object, or None if the fetch failed outright.

    This is more robust than feedparser.parse(url) because many outlets block
    the default feedparser User-Agent (returning 403/empty), which was causing
    Scientific American and BBC to silently return nothing.
    """
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    try:
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
    except HTTPError as exc:
        print(f"    ! HTTP {exc.code} for {url}")
        return None
    except (URLError, TimeoutError, Exception) as exc:   # noqa: BLE001
        print(f"    ! fetch error for {url}: {exc}")
        return None
    return feedparser.parse(raw)


OUT = Path(__file__).parent / "data" / "digest.json"


def as_word_pattern(term: str) -> re.Pattern:
    """
    Compile a term into a case-insensitive regex.

    - Multi-word phrases (e.g. "DNA data storage") match as a phrase.
    - Single alphabetic words match on word boundaries so "gene" does not
      match "generous" and "cell" does not match "excellent". Single words
      also match a simple plural, so "protein" matches "proteins" and
      "catalyst" matches "catalysts".
    - Terms that already contain non-word characters (like "CRISPR-") are
      used as-is.
    """
    term = term.strip()
    if " " in term or not term.isalnum():
        return re.compile(re.escape(term), re.IGNORECASE)
    # allow an optional simple plural ending (s / es) on single words
    return re.compile(r"\b" + re.escape(term) + r"(?:es|s)?\b", re.IGNORECASE)


def passes_filter(text: str, flt: dict) -> bool:
    """
    Decide whether an item's text belongs in a filtered channel.

    A channel's optional "filter" dict may contain:
      include: keep only items matching at least one of these terms
      require: if present, the item must ALSO match at least one of these
               (used to demand, e.g., an AI mention on top of a science topic)
      exclude: drop items matching any of these terms (takes priority)

    With no filter, everything passes. Exclude always wins. When both include
    and require are present, an item must satisfy include AND require AND avoid
    exclude — this is how the AI channel demands "AI + a science topic."
    """
    if not flt:
        return True

    haystack = text.lower()

    for pat in flt.get("_exclude_compiled", []):
        if pat.search(haystack):
            return False

    requires = flt.get("_require_compiled", [])
    if requires and not any(pat.search(haystack) for pat in requires):
        return False

    includes = flt.get("_include_compiled", [])
    if not includes:
        return True                       # exclude/require-only filter
    return any(pat.search(haystack) for pat in includes)


def compile_filter(flt: dict | None) -> dict | None:
    """Pre-compile a channel's include/require/exclude term lists once."""
    if not flt:
        return None
    return {
        "_include_compiled": [as_word_pattern(t) for t in flt.get("include", [])],
        "_require_compiled": [as_word_pattern(t) for t in flt.get("require", [])],
        "_exclude_compiled": [as_word_pattern(t) for t in flt.get("exclude", [])],
    }


def clean_text(raw: str) -> str:
    """Strip HTML tags and collapse whitespace into a clean snippet."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)          # remove tags
    text = html.unescape(text)                    # decode entities
    text = re.sub(r"\s+", " ", text).strip()      # collapse whitespace
    if len(text) > SNIPPET_CHARS:
        # cut on a sentence boundary if we can, else on a word boundary
        cut = text[:SNIPPET_CHARS]
        boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        if boundary > SNIPPET_CHARS * 0.5:
            text = cut[: boundary + 1]
        else:
            text = cut.rsplit(" ", 1)[0] + "\u2026"
    return text


def entry_datetime(entry) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
    return None


# Map feed domains to clean, human-friendly source names. Falls back to the
# feed's own title (tidied) or the domain if a source isn't listed here.
SOURCE_NAMES = {
    "rss.sciam.com": "Scientific American",
    "scientificamerican.com": "Scientific American",
    "feeds.bbci.co.uk": "BBC Science",
    "bbc.co.uk": "BBC Science",
    "science.org": "Science (AAAS)",
    "nature.com": "Nature",
    "sciencedaily.com": "ScienceDaily",
    "rss.sciencedaily.com": "ScienceDaily",
    "technologyreview.com": "MIT Technology Review",
    "spectrum.ieee.org": "IEEE Spectrum",
    "quantamagazine.org": "Quanta Magazine",
    "press.asimov.com": "Asimov Press",
    "nasa.gov": "NASA",
    "esa.int": "ESA",
    "eso.org": "ESO",
    "skyandtelescope.org": "Sky & Telescope",
    "physicsworld.com": "Physics World",
    "eos.org": "AGU Eos",
    "restofworld.org": "Rest of World",
}


def source_name(feed_meta, url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    if host in SOURCE_NAMES:
        return SOURCE_NAMES[host]
    title = feed_meta.get("title")
    if title:
        # trim common noise like " - RSS", " | Latest", " Content: Global"
        cleaned = re.sub(r"\s*[:|\-–].*$", "", title).strip()
        return cleaned or title
    return host


def gather_channel(channel_key: str, channel: dict) -> dict:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)
    flt = compile_filter(channel.get("filter"))
    items = []
    seen_links = set()
    filtered_out = 0

    for feed_url in channel["feeds"]:
        parsed = fetch_feed(feed_url)
        if parsed is None:
            continue

        # feedparser sets .bozo when a feed is malformed or unreachable
        n_entries = len(parsed.entries)
        if n_entries == 0:
            print(f"    ! FEED EMPTY (check URL): {feed_url}")
        else:
            print(f"    \u00b7 {n_entries:>3} items from {feed_url}")

        src = source_name(parsed.feed, feed_url)
        for entry in parsed.entries:
            link = entry.get("link")
            title = clean_text(entry.get("title", ""))
            if not link or not title or link in seen_links:
                continue

            when = entry_datetime(entry)
            if when and when < cutoff:
                continue

            summary = clean_text(
                entry.get("summary") or entry.get("description") or ""
            )

            # topic filter: title + summary must clear the channel's keywords
            if flt and not passes_filter(title + " " + summary, flt):
                filtered_out += 1
                continue

            seen_links.add(link)
            items.append(
                {
                    "title": title,
                    "link": link,
                    "source": src,
                    "summary": summary,
                    "published": when.isoformat() if when else None,
                    # sort key: unknown dates sink to the bottom
                    "_sort": when.timestamp() if when else 0,
                }
            )

    items.sort(key=lambda x: x["_sort"], reverse=True)
    for it in items:
        it.pop("_sort", None)

    if flt:
        print(f"      (topic filter kept {len(items)}, set aside {filtered_out})")

    return {
        "key": channel_key,
        "name": channel["name"],
        "tagline": channel["tagline"],
        "accent": channel["accent"],
        "items": items[:MAX_ITEMS_PER_CHANNEL],
    }


def main() -> None:
    print("Building Full Planet digest\u2026")
    channels_out = []
    for key, channel in CHANNELS.items():
        print(f"  \u2022 {channel['name']}")
        channels_out.append(gather_channel(key, channel))

    total = sum(len(c["items"]) for c in channels_out)
    digest = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "generated_human": dt.datetime.now(dt.timezone.utc).strftime("%d %B %Y, %H:%M UTC"),
        "total_items": total,
        "channels": channels_out,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(digest, indent=2, ensure_ascii=False))
    print(f"Wrote {OUT} \u2014 {total} items across {len(channels_out)} channels.")


if __name__ == "__main__":
    main()
