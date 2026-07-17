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
MAX_ENTRIES_PER_FEED = 60       # cap entries read per feed so one huge feed
                                # (e.g. TechNode's 2000) can't crowd out others
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

# Where per-channel URL lists are written (one .txt file per channel). These
# are plain text — one URL per line — designed to be imported into Google
# NotebookLM as sources. They live under data/urls/ so they're published on the
# GitHub Pages site alongside the digest and can be fetched at a stable address.
URL_DIR = Path(__file__).parent / "data" / "urls"

# Map each channel key to the clean filename requested for its URL list.
CHANNEL_FILENAMES = {
    "ai": "AI",
    "materials": "Materials",
    "synbio": "Synbio",
    "energywater": "Energy_Water",
    "spaceexploration": "Space",
    "astronomy": "Astro",
}


def write_url_lists(channels_out: list) -> None:
    """
    Write one plain-text file of story URLs per channel (plus a combined file)
    into data/urls/. One URL per line — the format NotebookLM expects when you
    paste website sources. Overwrites each run so the lists stay current.
    """
    URL_DIR.mkdir(parents=True, exist_ok=True)
    combined = []
    for channel in channels_out:
        fname = CHANNEL_FILENAMES.get(channel["key"], channel["key"])
        urls = [it["link"] for it in channel["items"] if it.get("link")]
        # A short header comment helps when the file is opened by a human; lines
        # starting with '#' are ignored by NotebookLM's URL import.
        header = [
            f"# Full Planet — {channel['name']} — story URLs",
            f"# Updated {dt.datetime.now(dt.timezone.utc).strftime('%d %B %Y %H:%M UTC')}",
            f"# {len(urls)} links",
            "",
        ]
        path = URL_DIR / f"{fname}.txt"
        path.write_text("\n".join(header + urls) + "\n", encoding="utf-8")
        print(f"    \u2192 wrote {len(urls):>2} URLs to {path.name}")
        combined.extend(urls)

    # A combined list of everything, deduplicated but order-preserving.
    seen = set()
    deduped = [u for u in combined if not (u in seen or seen.add(u))]
    (URL_DIR / "All_Channels.txt").write_text(
        "\n".join(["# Full Planet — all channels — story URLs", ""] + deduped) + "\n",
        encoding="utf-8",
    )
    print(f"    \u2192 wrote {len(deduped)} URLs to All_Channels.txt")


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
        # score terms: high-value terms that indicate strong on-theme relevance.
        # If absent, fall back to require then include terms.
        "_score_compiled": [as_word_pattern(t) for t in
                            (flt.get("score") or flt.get("require") or flt.get("include") or [])],
    }


def relevance_score(title: str, summary: str, flt: dict) -> float:
    """
    Score a story's relevance to a channel's theme.

    Matches in the TITLE count 3x; matches in the SUMMARY count 1x. Distinct
    matching terms are what count (not repeats), so a story that touches several
    on-theme concepts scores higher than one that repeats a single word. Returns
    0.0 for a story that would fail the filter outright (exclude / missing
    require), so callers can drop those first.
    """
    if not flt:
        return 1.0
    if not passes_filter(title + " " + summary, flt):
        return 0.0

    title_l = title.lower()
    summary_l = summary.lower()
    score = 0.0
    for pat in flt.get("_score_compiled", []):
        if pat.search(title_l):
            score += 3.0
        elif pat.search(summary_l):
            score += 1.0
    # a story that passed the filter but matched no score term still gets a
    # small floor so it isn't lost (it satisfied require/include some other way)
    return score if score > 0 else 0.5


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
    "israel21c.org": "ISRAEL21c",
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
    "renewablesnow.com": "Renewables Now",
    "renewableenergyworld.com": "Renewable Energy World",
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
            capped = min(n_entries, MAX_ENTRIES_PER_FEED)
            cap_note = f" (capped to {capped})" if n_entries > MAX_ENTRIES_PER_FEED else ""
            print(f"    \u00b7 {n_entries:>3} items from {feed_url}{tag}{cap_note}")

        src = source_name(parsed.feed, feed_url)
        # Cap how many entries we take from any single feed so an oversized
        # feed (e.g. TechNode's ~2000 items) can't dominate the regional pass.
        # feedparser returns entries newest-first, so a simple slice keeps the
        # most recent ones.
        for entry in parsed.entries[:MAX_ENTRIES_PER_FEED]:
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

            score = relevance_score(title, summary, flt) if flt else 1.0

            seen_links.add(link)
            out.append({
                "title": title,
                "link": link,
                "source": src,
                "summary": summary,
                "published": when.isoformat() if when else None,
                "regional": bool(region_label),
                "_sort": when.timestamp() if when else 0,
                "_score": score,
            })
    return out, filtered_out


def gather_channel(channel_key: str, channel: dict) -> dict:
    # Channels can override the global lookback window. Energy & Water research
    # feeds (ScienceDaily categories) update slowly — their newest items can be
    # 6-8 weeks old — so that channel looks back further to still surface them.
    lookback = channel.get("lookback_days", LOOKBACK_DAYS)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback)
    flt = compile_filter(channel.get("filter"))
    seen_links = set()

    # how many primary stories to show. Channels can override with "top_n";
    # otherwise use the global default.
    top_n = channel.get("top_n", MAX_ITEMS_PER_CHANNEL)

    # ---- PASS 1: primary high-quality feeds ----
    primary, primary_dropped = harvest(
        channel["feeds"], flt, cutoff, seen_links
    )
    # Rank by RELEVANCE first (most on-theme stories win), then by recency as a
    # tiebreaker. This keeps each channel focused on its theme even when a feed
    # carries marginal stories, and fills the channel with the best available.
    primary.sort(key=lambda x: (x["_score"], x["_sort"]), reverse=True)
    primary = primary[:top_n]
    # within the shown set, present newest-first for a natural reading order
    primary.sort(key=lambda x: x["_sort"], reverse=True)

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
        # rank regional by relevance too, then show newest-first
        regional.sort(key=lambda x: (x["_score"], x["_sort"]), reverse=True)
        regional = regional[:MAX_REGIONAL_PER_CHANNEL]
        regional.sort(key=lambda x: x["_sort"], reverse=True)
        print(f"      (regional kept {len(regional)}, set aside {regional_dropped})")

    items = primary + regional
    for it in items:
        it.pop("_sort", None)
        it.pop("_score", None)

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
    print("  [build version: 2026-07-17-stalefeeds — energy/synbio lookback widened, fresh energy feeds, AI science-gated]")
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

    # Also write per-channel URL lists for import into NotebookLM.
    print("  Writing per-channel URL lists (for NotebookLM)\u2026")
    write_url_lists(channels_out)


if __name__ == "__main__":
    main()
