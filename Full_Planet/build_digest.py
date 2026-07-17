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
import ssl
import datetime as dt
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import feedparser

from feeds import CHANNELS

# ---- tuning knobs -----------------------------------------------------------
MAX_ITEMS_PER_CHANNEL = 24      # how many primary headlines to show per channel
MAX_REGIONAL_PER_CHANNEL = 10   # how many regional (2nd-pass) items to append
LOOKBACK_DAYS = 21             # ignore anything older than this
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


def _read(url: str, context=None):
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    with urlopen(req, timeout=FETCH_TIMEOUT, context=context) as resp:
        return resp.read()


def fetch_feed(url: str):
    """
    Fetch a feed's raw bytes with a browser-like User-Agent, following
    redirects, then hand the content to feedparser. Returns a parsed feed
    object, or None if the fetch failed outright.

    More robust than feedparser.parse(url) because many outlets block the
    default feedparser User-Agent. Also retries once with a relaxed SSL
    context, since some feeds (e.g. older Scientific American endpoints)
    have handshake quirks that abort a strict TLS connection.
    """
    try:
        raw = _read(url)
    except HTTPError as exc:
        print(f"    ! HTTP {exc.code} for {url}")
        return None
    except (ssl.SSLError, URLError) as exc:
        # retry once with a permissive SSL context for handshake quirks
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            raw = _read(url, context=ctx)
            print(f"    (recovered {url} via relaxed SSL)")
        except Exception as exc2:                        # noqa: BLE001
            print(f"    ! fetch error for {url}: {exc2}")
            return None
    except Exception as exc:                             # noqa: BLE001
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
    # regional / Global South sources
    "scidev.net": "SciDev.Net",
    "thehindu.com": "The Hindu",
    "indianexpress.com": "Indian Express",
    "theconversation.com": "The Conversation",
    "downtoearth.org.in": "Down To Earth",
    "dialogue.earth": "Dialogue Earth",
    # China (state-affiliated sources are labeled transparently)
    "scmp.com": "South China Morning Post",
    "xinhuanet.com": "Xinhua (state media)",
    "chinadaily.com.cn": "China Daily (state media)",
    "technode.com": "TechNode",
    # East & Southeast Asia
    "sj.jst.go.jp": "Science Japan",
    "koreaherald.com": "The Korea Herald",
    "asianscientist.com": "Asian Scientist",
    "rappler.com": "Rappler",
    # Middle East
    "timesofisrael.com": "The Times of Israel",
    "al-fanarmedia.org": "Al-Fanar Media",
    "thenationalnews.com": "The National (UAE)",
    "aljazeera.com": "Al Jazeera",
    # Continental Europe
    "dw.com": "Deutsche Welle",
    "rss.dw.com": "Deutsche Welle",
    "mpg.de": "Max Planck Society",
    "home.cern": "CERN",
    "cern.ch": "CERN",
    "news.cnrs.fr": "CNRS News",
    "cnrs.fr": "CNRS News",
    "swissinfo.ch": "SWI swissinfo",
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


def harvest(feed_urls, flt, cutoff, seen_links, region_label=None):
    """
    Fetch a list of feeds, filter their entries, and return matching items.
    Shared by both the primary pass and the regional (second) pass.
    `seen_links` is shared across passes so the same story never appears twice.
    """
    out = []
    filtered_out = 0
    for feed_url in feed_urls:
        parsed = fetch_feed(feed_url)
        if parsed is None:
            continue

        n_entries = len(parsed.entries)
        if n_entries == 0:
            print(f"    ! FEED EMPTY (check URL): {feed_url}")
        else:
            tag = " [regional]" if region_label else ""
            print(f"    \u00b7 {n_entries:>3} items from {feed_url}{tag}")

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

            if flt and not passes_filter(title + " " + summary, flt):
                filtered_out += 1
                continue

            seen_links.add(link)
            out.append({
                "title": title,
                "link": link,
                "source": src,
                "summary": summary,
                "published": when.isoformat() if when else None,
                "regional": bool(region_label),
                "_sort": when.timestamp() if when else 0,
            })
    return out, filtered_out


def gather_channel(channel_key: str, channel: dict) -> dict:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)
    flt = compile_filter(channel.get("filter"))
    seen_links = set()

    # ---- PASS 1: primary high-quality feeds ----
    primary, primary_dropped = harvest(
        channel["feeds"], flt, cutoff, seen_links
    )
    primary.sort(key=lambda x: x["_sort"], reverse=True)
    primary = primary[:MAX_ITEMS_PER_CHANNEL]

    # ---- PASS 2: regional / Global South feeds, appended AFTER ----
    regional = []
    if channel.get("regional_feeds"):
        print("    -- second pass: regional sources --")
        # A channel may use a looser filter for its regional pass (some regional
        # outlets phrase things differently); fall back to the main filter.
        rflt = compile_filter(channel.get("regional_filter") or channel.get("filter"))
        regional, regional_dropped = harvest(
            channel["regional_feeds"], rflt, cutoff, seen_links,
            region_label="regional"
        )
        regional.sort(key=lambda x: x["_sort"], reverse=True)
        regional = regional[:MAX_REGIONAL_PER_CHANNEL]
        print(f"      (regional kept {len(regional)}, set aside {regional_dropped})")

    items = primary + regional
    for it in items:
        it.pop("_sort", None)

    if flt:
        print(f"      (primary filter kept {len(primary)}, set aside {primary_dropped})")

    return {
        "key": channel_key,
        "name": channel["name"],
        "tagline": channel["tagline"],
        "accent": channel["accent"],
        "items": items,
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
