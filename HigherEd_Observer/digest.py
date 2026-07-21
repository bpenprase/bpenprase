"""
The New Universities Observatory - nightly digest builder
=========================================================
Fetches RSS feeds from higher-education news sources, sorts stories into
five channels using keyword filters, and writes a static page to
index.html in this folder (served by GitHub Pages).

Run normally:      python digest.py
Run with test data (no internet needed):  python digest.py --demo

Everything you might want to change is near the top:
  FEEDS       - the news sources
  CATEGORIES  - the five channels and their keywords
  DAYS_BACK   - how many days of stories to keep
  MAX_PER_CATEGORY - how many stories to show per channel
"""

import argparse
import html
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser

# ---------------------------------------------------------------------------
# 1. SOURCES
# Each feed has a short display name and its RSS url. If a feed stops
# working the script just prints a warning and moves on, so it is always
# safe to experiment - add a line, run it, and check the printed status.
# ---------------------------------------------------------------------------

FEEDS = [
    # --- verified working (from the first live run) ---
    {"name": "Inside Higher Ed",       "url": "https://www.insidehighered.com/rss.xml"},
    {"name": "Higher Ed Dive",         "url": "https://www.highereddive.com/feeds/news/"},
    {"name": "The PIE News",           "url": "https://thepienews.com/feed/"},
    {"name": "The Hechinger Report",   "url": "https://hechingerreport.org/feed/"},
    {"name": "The Guardian Higher Ed", "url": "https://www.theguardian.com/education/higher-education/rss"},
    {"name": "EdSurge",                "url": "https://www.edsurge.com/articles_rss"},
    {"name": "Higher Ed Strategy Assoc.", "url": "https://higheredstrategy.com/feed/"},
    {"name": "FULCRUM (ISEAS)",        "url": "https://fulcrum.sg/feed/"},
    # --- replacements with confirmed feed addresses ---
    # World Education News & Reviews: international ed, credential systems
    {"name": "WENR (WES)",             "url": "https://wenr.wes.org/feed"},
    # Arab higher education, incl. Gulf branch campuses
    {"name": "Al-Fanar Media",         "url": "https://www.al-fanarmedia.org/feed/", "boost": "branch"},
    # UK higher education policy analysis
    {"name": "Wonkhe",                 "url": "https://wonkhe.com/feed/"},
    # UK higher education policy think tank
    {"name": "HEPI",                   "url": "https://www.hepi.ac.uk/category/blog/feed/"},
    # Australia's tertiary education news (Australian branch campuses)
    {"name": "Campus Review (AU)",     "url": "https://www.campusreview.com.au/feed/"},
    # India's higher education coverage via a mainstream daily's feed
    {"name": "Indian Express Education", "url": "https://indianexpress.com/section/education/feed/", "boost": "india"},
    # NOTE: the World Bank blog no longer offers a readable feed; its
    # reports are tracked by resources.py on the biweekly sweep instead.
    # NOTE: University World News and Times Higher Education no longer
    # offer working public RSS feeds; read them via their free email
    # newsletters instead. Open Campus, EducationWorld India, and
    # Science|Business blocked or broke automated feed reads and were
    # replaced by the sources above.
]

# ---------------------------------------------------------------------------
# 2. CHANNELS
# A story is assigned to the channel whose keywords it matches best.
# Keyword matching is case-insensitive; a match in the headline counts
# double. "min_score" is how many points a story needs to qualify.
# The "color" is used by the page for the channel's spectrum band.
# ---------------------------------------------------------------------------

CATEGORIES = [
    {
        "id": "startups",
        "title": "New Startup Universities",
        "blurb": "Institutions being founded from scratch - new charters, new campuses, new models.",
        "color": "#0E7C7B",
        "min_score": 2,
        "keywords": [
            "new university", "startup university", "start-up university",
            "founding", "founded", "launches university", "new college",
            "new institution", "charter", "opens its doors", "first cohort",
            "inaugural class", "establish a university", "establishing a university",
            "newly established", "greenfield", "opens campus", "new campus",
            "breaks ground", "receives accreditation", "wins approval",
            "founding president", "founding vice-chancellor",
        ],
    },
    {
        "id": "programs",
        "title": "Innovative New Programs",
        "blurb": "New degrees, schools, curricula, and experiments in how universities teach.",
        "color": "#4356A5",
        "min_score": 2,
        "keywords": [
            "new program", "new programme", "new degree", "new school of",
            "new major", "launches degree", "microcredential", "micro-credential",
            "curriculum overhaul", "new curriculum", "interdisciplinary",
            "ai degree", "artificial intelligence program", "innovative program",
            "pilot program", "honors college", "new institute",
        ],
    },
    {
        "id": "branch",
        "title": "Branch Campuses",
        "blurb": "US, European, and Australian universities crossing borders - transnational education worldwide.",
        "color": "#B0762A",
        "min_score": 2,
        "keywords": [
            "branch campus", "international campus", "overseas campus",
            "transnational", "tne", "offshore campus", "campus in india",
            "campus in vietnam", "campus in malaysia", "campus in indonesia",
            "campus abroad", "gift city", "riyadh campus", "dubai campus",
            "qatar campus", "foreign campus", "foreign university",
            "joint campus", "satellite campus",
        ],
    },
    {
        "id": "india",
        "title": "Innovation in Indian Higher Education",
        "blurb": "The world's most dynamic market for new universities - policy, private growth, and foreign entry.",
        "color": "#A63D57",
        "min_score": 2,
        # a story must mention India at all...
        "requires": ["india", "indian", "iit", "ugc", "gift city"],
        # ...and score on institution-building signals, not exam news
        "keywords": [
            "new university", "private university", "foreign university",
            "foreign campus", "branch campus", "new campus", "gift city",
            "national education policy", "nep 2020", "ugc regulation",
            "twinning", "joint degree", "dual degree", "new institution",
            "liberal arts", "deemed university", "collaboration",
            "partnership", "enrolment growth", "gross enrolment",
        ],
    },
    {
        "id": "reports",
        "title": "Important New Reports",
        "blurb": "Major studies and reports offering a wide-angle view of the global landscape.",
        "color": "#6B5B95",
        "min_score": 3,
        "keywords": [
            "report", "new report", "report finds", "study finds",
            "survey finds", "survey", "white paper", "outlook",
            "analysis", "world bank", "unesco", "oecd", "british council",
            "annual review", "year in review", "landscape", "publishes",
            "according to", "data shows", "figures show",
        ],
    },
]

# General relevance terms: the "reports" channel additionally requires one
# of these, so that every routine "report" in the news does not flood it.
TOPIC_TERMS = [
    "universit", "higher education", "tertiary", "college", "campus",
    "transnational", "international education", "branch",
]

# A realistic browser identity; some sites block obvious bots.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")

# Stories whose HEADLINE contains any of these are skipped entirely -
# they are exam administration and contest noise, not institution news.
NOISE_TERMS = [
    "admit card", "answer key", "exam date", "exam dates", "hall ticket",
    "school assembly", "olympiad", "cut-off", "cutoff", "result declared",
    "results declared", "board exam", "registration begins",
    "application deadline", "toppers", "rank list", "merit list",
]

DAYS_BACK = 7          # keep stories from the past week
MAX_PER_CATEGORY = 8   # show at most this many per channel
OUTPUT = Path(__file__).parent / "index.html"
TEMPLATE = Path(__file__).parent / "template.html"


# ---------------------------------------------------------------------------
# Fetching and scoring
# ---------------------------------------------------------------------------

def fetch_all_feeds():
    """Download every feed; return a list of story dicts."""
    stories = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    for feed in FEEDS:
        try:
            parsed = feedparser.parse(feed["url"], agent=USER_AGENT)
            if parsed.bozo and not parsed.entries:
                print(f"  WARNING  {feed['name']}: could not read feed "
                      f"({parsed.get('bozo_exception', 'unknown error')})")
                continue
            count = 0
            for entry in parsed.entries:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    when = datetime.fromtimestamp(time.mktime(published), tz=timezone.utc)
                    if when < cutoff:
                        continue
                else:
                    when = datetime.now(timezone.utc)
                summary = clean_text(entry.get("summary", ""))
                stories.append({
                    "title": clean_text(entry.get("title", "Untitled")),
                    "link": entry.get("link", ""),
                    "summary": summary[:400],
                    "source": feed["name"],
                    "date": when,
                    "boost": feed.get("boost"),
                })
                count += 1
            print(f"  ok       {feed['name']}: {count} recent stories")
        except Exception as err:  # noqa: BLE001 - keep the digest resilient
            print(f"  WARNING  {feed['name']}: {err}")
    return stories


def clean_text(raw):
    """Strip HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def keyword_present(kw, text):
    """Match a keyword only at word boundaries, so short terms like 'tne'
    cannot hide inside unrelated words (e.g. 'kindergartners', 'partner')."""
    return re.search(r"\b" + re.escape(kw) + r"\b", text) is not None


def score_story(story, category):
    """Keyword points: 2 for a headline match, 1 for a summary match."""
    title = story["title"].lower()
    summary = story["summary"].lower()
    score = 0
    for kw in category["keywords"]:
        if keyword_present(kw, title):
            score += 2
        elif keyword_present(kw, summary):
            # a multi-word phrase is a strong signal wherever it appears
            score += 2 if " " in kw else 1
    return score


def is_on_topic(story):
    text = (story["title"] + " " + story["summary"]).lower()
    # "universit" is a deliberate stem (university/universities), so it
    # keeps plain substring matching; the rest use word boundaries.
    return ("universit" in text
            or any(keyword_present(term, text) for term in TOPIC_TERMS
                   if term != "universit"))


def categorize(stories):
    """Assign each story to its best-matching channel (or drop it)."""
    buckets = {c["id"]: [] for c in CATEGORIES}
    seen_links = set()
    for story in stories:
        if story["link"] in seen_links:
            continue
        seen_links.add(story["link"])
        title = story["title"].lower()
        if any(keyword_present(t, title) for t in NOISE_TERMS):
            continue
        best, best_score = None, 0
        for category in CATEGORIES:
            s = score_story(story, category)
            required = category.get("requires")
            if required:
                text = (story["title"] + " " + story["summary"]).lower()
                if not any(keyword_present(t, text) for t in required):
                    s = 0
            if story.get("boost") == category["id"] and s > 0:
                s += 1   # stories from a source focused on this channel get a nudge
            if category["id"] == "reports" and not is_on_topic(story):
                s = 0
            if s >= category["min_score"] and s > best_score:
                best, best_score = category, s
        if best:
            story["score"] = best_score
            buckets[best["id"]].append(story)
    for cid in buckets:
        buckets[cid].sort(key=lambda s: (s["date"]), reverse=True)
        buckets[cid] = buckets[cid][:MAX_PER_CATEGORY]
    return buckets


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------

def render(buckets, source_count):
    template = TEMPLATE.read_text(encoding="utf-8")
    total = sum(len(v) for v in buckets.values())
    now = datetime.now(timezone.utc)

    band = "".join(
        f'<a class="band-seg" href="#{c["id"]}" style="background:{c["color"]}"'
        f' title="{html.escape(c["title"])}"></a>'
        for c in CATEGORIES
    )

    sections = []
    for c in CATEGORIES:
        items = buckets[c["id"]]
        if items:
            cards = "".join(
                f'''<article class="story">
  <p class="story-meta"><span class="dot" style="background:{c["color"]}"></span>'''
                f'''{html.escape(s["source"])} &middot; {s["date"].strftime("%b %d")}</p>
  <h3><a href="{html.escape(s["link"])}">{html.escape(s["title"])}</a></h3>
  <p class="story-summary">{html.escape(s["summary"][:260])}{"&hellip;" if len(s["summary"]) > 260 else ""}</p>
</article>'''
                for s in items
            )
        else:
            cards = ('<p class="empty">No stories matched this channel in the '
                     'past week. The sweep continues tomorrow night.</p>')
        sections.append(f'''<section id="{c["id"]}" class="channel">
  <header class="channel-head" style="border-color:{c["color"]}">
    <h2><span class="channel-mark" style="background:{c["color"]}"></span>{html.escape(c["title"])}</h2>
    <p class="channel-blurb">{html.escape(c["blurb"])}</p>
  </header>
  <div class="stories">{cards}</div>
</section>''')

    page = (template
            .replace("{{DATE}}", now.strftime("%A, %B %d, %Y"))
            .replace("{{TIME}}", now.strftime("%H:%M UTC"))
            .replace("{{STORY_COUNT}}", str(total))
            .replace("{{SOURCE_COUNT}}", str(source_count))
            .replace("{{BAND}}", band)
            .replace("{{SECTIONS}}", "\n".join(sections)))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"\nWrote {OUTPUT} - {total} stories across {len(CATEGORIES)} channels.")


# ---------------------------------------------------------------------------
# Demo data so the page can be previewed without internet access
# ---------------------------------------------------------------------------

def demo_stories():
    now = datetime.now(timezone.utc)
    samples = [
        ("The PIE News", "New university receives charter to open liberal arts campus in Ho Chi Minh City",
         "The founding team says the new institution will enroll its first cohort in 2027, with a curriculum blending engineering and the liberal arts."),
        ("University World News", "Government invites bids for three new startup universities in second-tier cities",
         "The ministry's call marks the largest wave of greenfield institution founding in a decade, officials said."),
        ("Times Higher Education", "Australian university confirms branch campus in Gujarat's GIFT City",
         "The move extends the rapid growth of foreign campuses in India under the new transnational education rules."),
        ("The PIE News", "US institution wins accreditor approval for Riyadh campus",
         "The overseas campus will be the first of its kind in the kingdom and begins classes this fall."),
        ("EducationWorld India", "Private university boom reaches districts beyond the metros",
         "India's gross enrolment growth is drawing new entrants, with a dozen private universities chartered this year under state acts."),
        ("Inside Higher Ed", "University launches AI degree built around studio apprenticeships",
         "The new program replaces lectures with project studios, a model administrators call a test case for curriculum overhaul."),
        ("Higher Ed Dive", "College debuts microcredential pathway stacking into a full degree",
         "The new programme lets working adults assemble short credentials into a bachelor's over five years."),
        ("World Bank Education Blog", "New report: steering tertiary education toward resilient systems",
         "The World Bank's latest analysis of tertiary education outlines five principles for building university systems that deliver for all."),
        ("Higher Ed Strategy Assoc.", "Year in review: the global landscape of new institutions",
         "An annual report on higher education worldwide, including the surge of university founding across Asia."),
    ]
    return [{"title": t, "link": f"https://example.com/story-{i}", "summary": s,
             "source": src, "date": now - timedelta(hours=i * 5),
             "boost": "india" if "India" in src else None}
            for i, (src, t, s) in enumerate(samples)]


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true",
                        help="build the page from sample data (no internet)")
    args = parser.parse_args()

    print("The New Universities Observatory - nightly sweep")
    print("=" * 48)
    if args.demo:
        print("  (demo mode: using sample stories)")
        stories = demo_stories()
    else:
        stories = fetch_all_feeds()
    print(f"\nCollected {len(stories)} stories; filtering into channels...")
    buckets = categorize(stories)
    render(buckets, len(FEEDS))


if __name__ == "__main__":
    sys.exit(main())
