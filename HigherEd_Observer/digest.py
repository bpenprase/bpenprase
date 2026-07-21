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
    {"name": "Inside Higher Ed",       "url": "https://www.insidehighered.com/rss.xml", "region": "us"},
    {"name": "Higher Ed Dive",         "url": "https://www.highereddive.com/feeds/news/", "region": "us"},
    {"name": "The PIE News",           "url": "https://thepienews.com/feed/"},
    {"name": "The Hechinger Report",   "url": "https://hechingerreport.org/feed/", "region": "us"},
    {"name": "The Guardian Higher Ed", "url": "https://www.theguardian.com/education/higher-education/rss"},
    {"name": "EdSurge",                "url": "https://www.edsurge.com/articles_rss", "region": "us"},
    {"name": "Higher Ed Strategy Assoc.", "url": "https://higheredstrategy.com/feed/"},
    {"name": "FULCRUM (ISEAS)",        "url": "https://fulcrum.sg/feed/"},
    # --- replacements with confirmed feed addresses ---
    # World Education News & Reviews: international ed, credential systems
    {"name": "WENR (WES)",             "url": "https://wenr.wes.org/feed"},
    # UK higher education policy analysis
    {"name": "Wonkhe",                 "url": "https://wonkhe.com/feed/", "region": "europe"},
    # UK higher education policy think tank
    {"name": "HEPI",                   "url": "https://www.hepi.ac.uk/category/blog/feed/", "region": "europe"},
    # Australia's tertiary education news (Australian branch campuses)
    {"name": "Campus Review (AU)",     "url": "https://www.campusreview.com.au/feed/"},
    # India's higher education coverage via a mainstream daily's feed
    {"name": "Indian Express Education", "url": "https://indianexpress.com/section/education/feed/",
     "boost": "india", "region": "india"},
    # --- added for broader yield ---
    # global student mobility and TNE market intelligence
    {"name": "ICEF Monitor",            "url": "https://monitor.icef.com/feed/"},
    # US higher ed leadership and innovation
    {"name": "University Business",     "url": "https://universitybusiness.com/feed/", "region": "us"},
    # US campus technology and innovation
    {"name": "eCampus News",            "url": "https://www.ecampusnews.com/feed/", "region": "us"},
    # China coverage in English (watch the log; drop if it warns)
    {"name": "Sixth Tone (China)",      "url": "https://www.sixthtone.com/rss", "region": "china"},
    # NOTE: Al-Fanar Media, University Affairs (CA), EducationWorld
    # India, and Science|Business hard-block automated readers (403)
    # and were removed after testing.
    # --- regional dailies that cover the watchlist institutions ---
    # (confirmed feed addresses from the startup-university source study)
    {"name": "TBS Education (Bangladesh)", "url": "https://www.tbsnews.net/bangladesh/education/rss.xml"},
    {"name": "The Daily Star (Bangladesh)", "url": "https://www.thedailystar.net/rss.xml",
     "watchlist_only": True},
    {"name": "VnExpress International", "url": "https://e.vnexpress.net/rss/news.rss",
     "watchlist_only": True},
    {"name": "MyJoyOnline (Ghana)",     "url": "https://www.myjoyonline.com/feed/",
     "watchlist_only": True},
    # China news in English with education coverage (unverified address)
    {"name": "China Daily",             "url": "https://www.chinadaily.com.cn/rss/china_rss.xml",
     "region": "china"},
    # International higher education news with strong Europe coverage
    {"name": "Erudera News",            "url": "https://erudera.com/feed/"},
    # --- institutional newsrooms of startup universities; every story
    #     routes to the Startups channel (unverified /feed/ addresses:
    #     watch the log and delete any that come back blocked) ---
    {"name": "Krea University News",    "url": "https://krea.edu.in/feed/", "assign": "startups"},
    {"name": "Ashesi University News",  "url": "https://ashesi.edu.gh/feed/", "assign": "startups"},
    {"name": "Fulbright Univ. Vietnam News", "url": "https://fulbright.edu.vn/feed/", "assign": "startups"},
    {"name": "African Leadership Univ. News", "url": "https://alueducation.com/feed/", "assign": "startups"},
    {"name": "Harrisburg Univ. News",   "url": "https://harrisburgu.edu/feed/", "assign": "startups"},
    {"name": "Florida Poly News",       "url": "https://floridapoly.edu/feed/", "assign": "startups"},
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

# Startup universities tracked by name (from the book chapter on
# startup universities - institutions roughly 20 years old or less).
# A story mentioning any of these goes straight to the Startups channel.
WATCHLIST = [
    # India
    "ashoka university", "azim premji university", "krea university",
    "plaksha university", "plaksha", "shiv nadar university",
    "sai university", "mahindra university", "jindal global",
    "ahmedabad university", "jio institute", "universal ai university",
    # South and Southeast Asia
    "habib university", "brac university", "asian university for women",
    "parami university", "fulbright university vietnam",
    "fulbright university",
    # Africa
    "ashesi", "african leadership university",
    # China
    "southern university of science and technology", "sustech",
    "shanghaitech", "shenzhen technology university",
    # United States
    "minerva university", "olin college", "soka university",
    "harrisburg university", "nevada state university",
    "georgia gwinnett", "florida polytechnic", "florida poly",
]


def watchlist_hit(story):
    """Return True when a story names a tracked startup university."""
    text = (story["title"] + " " + story["summary"]).lower()
    return any(keyword_present(name, text) for name in WATCHLIST)


# Signals that a story is about building, changing, or founding
# institutions - shared by the regional channels below.
INSTITUTION_SIGNALS = [
    "new university", "new campus", "new college", "new institution",
    "new school of", "new program", "new programme", "new degree",
    "branch campus", "foreign campus", "foreign university",
    "international campus", "transnational", "joint degree", "dual degree",
    "twinning", "merger", "charter", "accreditation", "founding",
    "launches", "launched", "opens", "breaks ground", "reform",
    "innovation", "innovative", "microcredential", "micro-credential",
    "microcredentials", "ai degree", "ai program", "ai curriculum",
    "ai literacy", "ai in education", "ai in the classroom",
    "teaching with ai", "artificial intelligence",
    "online learning", "curriculum", "liberal arts", "expansion",
    "partnership", "collaboration", "enrolment", "enrollment",
    "new degree program", "interdisciplinary", "project-based",
    "experiential learning", "competency-based", "stackable",
    "certificate program", "apprenticeship", "work-based",
    "redesign", "first-of-its-kind", "first of its kind", "pilot",
]

# Everyday higher-ed policy and institutional vocabulary - used by the
# regional channels, which aim to catch the notable HE stories of their
# region, not only institution-founding news.
REGIONAL_EXTRAS = [
    "funding", "tuition", "fees", "vice-chancellor", "chancellor",
    "provost", "admissions", "admission", "recruitment",
    "international students", "rankings", "ranking", "research",
    "policy", "regulation", "governance", "quality assurance",
    "scholarship", "scholarships", "graduate employment", "graduates",
]

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
            "seeks accreditation", "accreditation candidacy",
            "provisional accreditation", "founding president",
            "founding vice-chancellor", "inaugural president",
            "will open", "set to open", "plans to open", "opens its doors",
            "new medical school", "new law school", "new engineering school",
            "announces new university", "announces new college",
            "convocation", "young university", "founding class",
            "residential college", "need-based",
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
            "ai degree", "ai program", "artificial intelligence program",
            "innovative program", "pilot program", "honors college",
            "new institute", "new degree program", "project-based",
            "interdisciplinary", "stackable", "certificate program",
            "apprenticeship", "bootcamp", "competency-based",
            "experiential learning", "new certificate", "launches program",
            "pedagogy", "course redesign", "general education",
            "core curriculum", "first-year experience", "capstone",
            "studio-based", "team-taught", "block plan",
            "flipped classroom", "teaching innovation",
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
        "min_score": 1,
        # a story must mention India at all...
        "requires": ["india", "indian", "iit", "ugc", "gift city"],
        "region": "india",
        # ...and score on institution-building signals, not exam news
        "keywords": INSTITUTION_SIGNALS + [
            "private university", "gift city", "national education policy",
            "nep 2020", "ugc regulation", "deemed university",
            "gross enrolment",
        ] + REGIONAL_EXTRAS,
    },
    {
        "id": "us",
        "title": "Innovation in US Higher Education",
        "blurb": "New models, programs, and institutional experiments across American higher education.",
        "color": "#3A7D44",
        "min_score": 1,
        "requires": ["united states", "american", "u.s.", "usa"],
        "region": "us",
        "keywords": INSTITUTION_SIGNALS + [
            "community college", "work college", "honors college",
            "competency-based", "accreditor",
        ] + REGIONAL_EXTRAS,
    },
    {
        "id": "europe",
        "title": "Innovation in European Higher Education",
        "blurb": "New institutions and reform across the UK and Europe, including the European Universities alliances.",
        "color": "#33658A",
        "min_score": 1,
        "requires": ["europe", "european", "uk", "britain", "british",
                     "england", "scotland", "wales", "ireland", "germany",
                     "german", "france", "french", "netherlands", "dutch",
                     "spain", "italy", "nordic", "erasmus", "bologna"],
        "region": "europe",
        "keywords": INSTITUTION_SIGNALS + [
            "european universities initiative", "university alliance",
            "bologna process", "erasmus",
        ] + REGIONAL_EXTRAS,
    },
    {
        "id": "china",
        "title": "Innovation in Chinese Higher Education",
        "blurb": "New universities, sino-foreign ventures, and reform across China and Greater China.",
        "color": "#C03221",
        "min_score": 1,
        "requires": ["china", "chinese", "hong kong", "macau", "beijing",
                     "shanghai", "shenzhen", "tsinghua", "peking",
                     "greater bay"],
        "region": "china",
        "keywords": INSTITUTION_SIGNALS + [
            "sino-foreign", "joint venture university", "double first-class",
            "c9 league",
        ] + REGIONAL_EXTRAS,
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
# Deliberate stems, matched as substrings (each is long enough to be
# unambiguous): "universit" catches university/universities, "college"
# catches colleges, "student" catches students, and so on.
TOPIC_TERMS = [
    "universit", "higher education", "tertiary", "college", "campus",
    "transnational", "international education", "student", "faculty",
    "degree", "academic", "curriculum", "enrolment", "enrollment",
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
MAX_PER_SOURCE = 2     # ...and at most this many from any one source per channel
OUTPUT = Path(__file__).parent / "index.html"
TEMPLATE = Path(__file__).parent / "template.html"


# ---------------------------------------------------------------------------
# Fetching and scoring
# ---------------------------------------------------------------------------

def fetch_feed(url):
    """Download a feed like a browser would, and repair it if needed."""
    import requests
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": ("application/rss+xml, application/atom+xml, "
                   "application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8"),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url.split("/feed")[0] if "/feed" in url else url,
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    content = resp.content
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        # some feeds embed bytes XML forbids; strip them and retry once
        cleaned = re.sub(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b"", content)
        parsed = feedparser.parse(cleaned)
    return parsed, content


def looks_like_challenge_page(content):
    """True when a 'feed' is actually an HTML bot-check or error page."""
    head = content[:600].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def fetch_all_feeds():
    """Download every feed; return a list of story dicts."""
    stories = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    for feed in FEEDS:
        try:
            parsed, content = fetch_feed(feed["url"])
            if not parsed.entries:
                if looks_like_challenge_page(content):
                    print(f"  blocked  {feed['name']}: the site refuses "
                          f"automated readers - safe to delete this feed line")
                    continue
                if parsed.bozo:
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
                    "region": feed.get("region"),
                    "assign": feed.get("assign"),
                    "watchlist_only": feed.get("watchlist_only", False),
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
    return any(term in text for term in TOPIC_TERMS)


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
        # institutional newsrooms: every story is about the institution
        if story.get("assign"):
            story["score"] = 10
            buckets[story["assign"]].append(story)
            continue
        # a story naming a tracked startup university goes to Startups
        if watchlist_hit(story):
            story["score"] = 10
            buckets["startups"].append(story)
            continue
        # broad national feeds contribute watchlist stories only
        if story.get("watchlist_only"):
            continue
        best, best_score = None, 0
        for category in CATEGORIES:
            s = score_story(story, category)
            required = category.get("requires")
            if required:
                if not is_on_topic(story):
                    continue   # regional channels only take higher-ed stories
                text = (story["title"] + " " + story["summary"]).lower()
                geo_match = any(keyword_present(t, text) for t in required)
                source_match = (story.get("region") is not None
                                and story.get("region") == category.get("region"))
                if not (geo_match or source_match):
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
        per_source, trimmed = {}, []
        for s in buckets[cid]:
            n = per_source.get(s["source"], 0)
            if n >= MAX_PER_SOURCE:
                continue
            per_source[s["source"]] = n + 1
            trimmed.append(s)
        buckets[cid] = trimmed[:MAX_PER_CATEGORY]
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
        ("University Business", "American university opens competency-based honors college",
         "The new college pairs a project-based curriculum with employer partnerships in a model leaders call a first for the region."),
        ("Wonkhe", "European universities alliance wins approval for joint degree across five countries",
         "The new programme under the European Universities Initiative lets students assemble a single degree from partner campuses in Germany, France, and Spain."),
        ("Sixth Tone (China)", "New sino-foreign joint venture university breaks ground in Shenzhen",
         "The partnership brings a European engineering curriculum to China's Greater Bay Area, with a founding class planned for 2028."),
        ("The Daily Star (Bangladesh)", "BRAC University hosts research day as summer cohort arrives",
         "The university welcomed its newest students while faculty presented projects across disciplines."),
        ("Krea University News", "Fifth convocation celebrates 477 graduates in Chennai",
         "The ceremony marked the young university's largest graduating class to date."),
    ]
    return [{"title": t, "link": f"https://example.com/story-{i}", "summary": s,
             "source": src, "date": now - timedelta(hours=i * 5),
             "boost": "india" if "India" in src else None,
             "region": {"University Business": "us", "Wonkhe": "europe",
                        "Sixth Tone (China)": "china"}.get(src),
             "assign": "startups" if src == "Krea University News" else None,
             "watchlist_only": src == "The Daily Star (Bangladesh)"}
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
