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

import feedparser

from feeds import CHANNELS

# ---- tuning knobs -----------------------------------------------------------
MAX_ITEMS_PER_CHANNEL = 24      # how many headlines to show per channel
LOOKBACK_DAYS = 14             # ignore anything older than this
SNIPPET_CHARS = 220           # target length of the one-to-two sentence blurb
# -----------------------------------------------------------------------------

OUT = Path(__file__).parent / "data" / "digest.json"


def as_word_pattern(term: str) -> re.Pattern:
    """
    Compile a term into a case-insensitive regex.

    - Multi-word phrases (e.g. "DNA data storage") match as a phrase.
    - Single alphabetic words match on word boundaries so "gene" does not
      match "generous" and "cell" does not match "excellent".
    - Terms that already contain non-word characters (like "CRISPR-") are
      used as-is.
    """
    term = term.strip()
    if " " in term or not term.isalnum():
        return re.compile(re.escape(term), re.IGNORECASE)
    return re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)


def passes_filter(text: str, flt: dict) -> bool:
    """
    Decide whether an item's text belongs in a filtered channel.

    A channel's optional "filter" dict may contain:
      include: keep only items matching at least one of these terms
      exclude: drop items matching any of these terms (takes priority)

    With no filter, everything passes. Exclude always wins over include,
    so an item matching both an include and an exclude term is dropped.
    """
    if not flt:
        return True

    haystack = text.lower()

    for pat in flt.get("_exclude_compiled", []):
        if pat.search(haystack):
            return False

    includes = flt.get("_include_compiled", [])
    if not includes:
        return True                       # exclude-only filter
    return any(pat.search(haystack) for pat in includes)


def compile_filter(flt: dict | None) -> dict | None:
    """Pre-compile a channel's include/exclude term lists once, up front."""
    if not flt:
        return None
    return {
        "_include_compiled": [as_word_pattern(t) for t in flt.get("include", [])],
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


def source_name(feed_meta, url: str) -> str:
    title = feed_meta.get("title")
    if title:
        # trim common noise like " - RSS" or " | Latest"
        return re.sub(r"\s*[|\-–].*(rss|feed|latest|news)\s*$", "", title, flags=re.I).strip() or title
    return urlparse(url).netloc.replace("www.", "")


def gather_channel(channel_key: str, channel: dict) -> dict:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)
    flt = compile_filter(channel.get("filter"))
    items = []
    seen_links = set()
    filtered_out = 0

    for feed_url in channel["feeds"]:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as exc:                     # noqa: BLE001
            print(f"  ! {channel_key}: failed {feed_url} ({exc})")
            continue

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
