"""
The New Universities Observatory - nightly digest builder
=========================================================
Fetches RSS feeds from higher-education news sources, sorts stories into
nine channels using keyword filters, and writes a static page to
index.html in this folder (served by GitHub Pages).

Run normally:      python digest.py
Run with test data (no internet needed):  python digest.py --demo

Everything you might want to change is near the top:
  FEEDS       - the news sources
  CATEGORIES  - the nine channels and their keywords
  FUA_NETWORK - the Future Universities Alliance summit institutions
  DAYS_BACK   - how many days of stories to keep
  MAX_PER_CATEGORY - how many stories to show per channel
"""

import argparse
import json
import html
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from urllib.parse import quote, urlparse

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
    # --- institutional newsrooms of startup universities; every story
    #     routes to the Startups channel (unverified /feed/ addresses:
    #     watch the log and delete any that come back blocked) ---
    {"name": "Krea University News",    "url": "https://krea.edu.in/feed/", "assign": "startups"},
    {"name": "Ashesi University News",  "url": "https://ashesi.edu.gh/feed/", "assign": "startups"},
    {"name": "Fulbright Univ. Vietnam News", "url": "https://fulbright.edu.vn/feed/", "assign": "startups"},
    {"name": "African Leadership Univ. News", "url": "https://alueducation.com/feed/", "assign": "startups"},
    {"name": "Harrisburg Univ. News",   "url": "https://harrisburgu.edu/feed/", "assign": "startups"},
    {"name": "Florida Poly News",       "url": "https://floridapoly.edu/feed/", "assign": "startups"},
    # --- Future Universities Alliance and its Sandbox cohort ---
    # the Alliance's own publication - leads the FUA Network channel
    {"name": "Future Universities (via Bing)",
     "url": "https://www.bing.com/news/search?q=site%3Afutureuniversities.substack.com&format=rss",
     "assign": "fua", "days": 30},
    # regional outlets that cover Sandbox startup institutions
    # (watchlist_only: they contribute only stories naming a tracked school)
    {"name": "VTDigger (Vermont)",      "url": "https://vtdigger.org/feed/", "watchlist_only": True},
    {"name": "The Astana Times",        "url": "https://astanatimes.com/feed/", "watchlist_only": True},
    {"name": "KCAW Sitka",              "url": "https://www.kcaw.org/feed/", "watchlist_only": True},
    {"name": "Korea Herald National",   "url": "https://www.koreaherald.com/rss/kh_National",
     "watchlist_only": True},
    {"name": "Premium Times (Nigeria)", "url": "https://www.premiumtimesng.com/feed", "watchlist_only": True},
    {"name": "TechCabal (Africa)",      "url": "https://techcabal.com/feed", "watchlist_only": True},
    # unverified addresses - the log will pass verdict; delete any 'blocked'
    # institutional newsrooms of Sandbox startups (unverified /feed/)
    {"name": "NewU University News",    "url": "https://newu.university/feed/", "assign": "startups"},
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

def google_news_feed(name, query, **flags):
    """A Google News RSS feed for a search query - the bridge to outlets
    that offer no feed of their own, and a global net for watchlist
    institutions that only local press covers."""
    url = ("https://news.google.com/rss/search?q=" + quote(query)
           + "&hl=en-US&gl=US&ceid=US:en")
    return {"name": name, "url": url, **flags}


FEEDS += [
    # backup route to the FUA Substack in case its direct feed blocks us
    google_news_feed("Future Universities (via GN)", "site:futureuniversities.substack.com",
                     assign="fua", days=30),
    # premium outlets with no working direct feed, via Google News
    google_news_feed("University World News (via GN)", "site:universityworldnews.com"),
    google_news_feed("Times Higher Education (via GN)", "site:timeshighereducation.com"),
    google_news_feed("Al-Fanar Media (via GN)", "site:al-fanarmedia.org"),
    google_news_feed("EducationWorld India (via GN)", "site:educationworld.in", region="india"),
    google_news_feed("Science|Business (via GN)", "site:sciencebusiness.net", region="europe"),
    google_news_feed("University Affairs (via GN)", "site:universityaffairs.ca"),
    # global nets for thin-coverage watchlist institutions - any outlet
    # anywhere that names them will surface here
    google_news_feed("Watchlist sweep 1 (via GN)",
        '"Parami University" OR "Soka University of America" OR "ShanghaiTech" OR '
        '"Shenzhen Technology University" OR "Sai University" OR "Mahindra University"'),
    google_news_feed("Watchlist sweep 2 (via GN)",
        '"Jio Institute" OR "Universal AI University" OR "Nevada State University" OR '
        '"Georgia Gwinnett" OR "Minerva University" OR "Asian University for Women"'),
    google_news_feed("Watchlist sweep 3 (via GN)",
        '"Taejae University" OR "Musizi University" OR "Africa Urban Lab" OR '
        '"Greenway Institute" OR "NewU University" OR "Outer Coast College" OR '
        '"Polymath University"'),
    google_news_feed("Watchlist sweep 4 (via GN)",
        '"Mohammed VI Polytechnic" OR "University of Doha" OR "Madan Bhandari" OR '
        '"Botho University" OR "Academic City University" OR "Zamorano University" OR '
        '"London Interdisciplinary School" OR "Atria University" OR "Newstate University"'),

    # --- Future Universities Alliance network: established universities in
    #     the official Innovation Sandbox cohort (Pathways 2 and 3) ---
    # Large universities appear in the news daily, so their queries carry
    # a qualifier that keeps results to institutional and teaching news.
    google_news_feed("FUA network sweep 1 (via GN)",
        '"Duke University" ("higher education" OR "new program" OR "new degree" OR "new school" OR launches OR partnership OR innovation)', watchlist_only=True),
    google_news_feed("FUA network sweep 2 (via GN)",
        '("Georgetown University" OR "Northeastern University" OR '
        '"University of North Texas") ("higher education" OR "new program" OR "new degree" OR "new school" OR launches OR partnership OR innovation)', watchlist_only=True),
    google_news_feed("FUA network sweep 3 (via GN)",
        '("University of Nebraska" OR "Chulalongkorn University" OR '
        '"Tecnológico de Monterrey" OR "Tec de Monterrey") ("higher education" OR "new program" OR "new degree" OR "new school" OR launches OR partnership OR innovation)',
        watchlist_only=True),
    # smaller members: any news that names them
    google_news_feed("FUA network sweep 4 (via GN)",
        '"Bard College" OR "Lehigh University" OR "Montclair State University" OR '
        '"Drew University" OR "Mercy University" OR "UNC Asheville" OR '
        '"University of North Carolina Asheville"', watchlist_only=True),
    google_news_feed("FUA network sweep 5 (via GN)",
        '"Vermont State Colleges" OR "Vermont State University" OR '
        '"Harper Adams University" OR "James Cook University" OR '
        '"Western Sydney University" OR "Elmbridge University"', watchlist_only=True),
    google_news_feed("FUA network sweep 6 (via GN)",
        '"Singapore Management University" OR "Universidad Francisco de Vitoria" OR '
        '"University of Central Punjab" OR "Duke Kunshan University" OR '
        '"Pomona College" OR "Soka University of America"', watchlist_only=True),

    # --- members' own websites (institutional newsrooms indexed by Google
    #     News); stories are matched to an institution by their web domain
    google_news_feed("Startup sites sweep 1 (via GN)",
        "site:greenwayinstitute.org OR site:newu.university OR site:newstateu.com OR "
        "site:outercoast.org OR site:aul.city OR site:cambridgespark.com OR "
        "site:nutm.edu.ng OR site:lis.ac.uk OR site:musizifoundation.org OR "
        "site:code.berlin", watchlist_only=True),
    google_news_feed("Startup sites sweep 2 (via GN)",
        "site:ozyegin.edu.tr OR site:um6p.ma OR site:udst.edu.qa OR "
        "site:zamorano.edu OR site:habib.edu.pk OR site:plaksha.edu.in OR "
        "site:ahduni.edu.in OR site:atriauniversity.edu.in OR site:acity.edu.gh OR "
        "site:minerva.edu", watchlist_only=True),
    google_news_feed("FUA member sites sweep 1 (via GN)",
        "site:bard.edu OR site:lehigh.edu OR site:montclair.edu OR site:drew.edu OR "
        "site:mercy.edu OR site:unca.edu OR site:vermontstate.edu", watchlist_only=True),
    google_news_feed("FUA member sites sweep 2 (via GN)",
        "site:harper-adams.ac.uk OR site:jcu.edu.au OR site:westernsydney.edu.au OR "
        "site:smu.edu.sg OR site:ufv.es OR site:ucp.edu.pk OR "
        "site:dukekunshan.edu.cn OR site:pomona.edu OR site:soka.edu",
        watchlist_only=True),
    google_news_feed("FUA member sites sweep 3 (via GN)",
        "(site:duke.edu OR site:georgetown.edu OR site:northeastern.edu OR "
        "site:unt.edu OR site:unl.edu OR site:chula.ac.th OR site:tec.mx) "
        '("higher education" OR "new program" OR "new degree" OR "new school" OR launches OR partnership OR innovation)', watchlist_only=True),
]


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
    "minerva university", "olin college",
    "harrisburg university", "nevada state university",
    "georgia gwinnett", "florida polytechnic", "florida poly",
    # Future Universities Alliance Sandbox cohort (safe name forms -
    # ambiguous names use exact multiword phrases to avoid false hits)
    "africa urban lab", "alwin education", "cambridge spark",
    "frontier institute of technology", "greenway institute",
    "invision u", "musizi university", "musizi",
    "national school of innovation", "nepal communiversity",
    "communiversity", "newstate university", "newu university",
    "outer coast college", "outsmart college", "outsmart education",
    "polymath university", "taejae university", "taejae",
    "academic city university", "atria university", "botho university",
    "london interdisciplinary school", "madan bhandari university",
    "nigerian university of technology and management",
    "universidad de la libertad", "mohammed vi polytechnic", "um6p",
    "university of doha", "udst", "zamorano university",
    "escuela agricola panamericana", "code university",
    "ozyegin university", "özyeğin university",
    # acronyms and variants confirmed distinctive by the census
    "bracu", "nutm", "invision university", "mbust",
]


def watchlist_hit(story):
    """True when a story names a tracked startup university AND reads
    like an education story - the second test stops name collisions
    (athletes, businesses, places) from leaking into the channel."""
    text = (story["title"] + " " + story["summary"]).lower()
    # broad dailies and search feeds must name the school in the headline,
    # so a passing mention deep in a story is not enough
    where = story["title"].lower() if story.get("watchlist_only") else text
    if not any(keyword_present(name, where) for name in WATCHLIST):
        return False
    if any(keyword_present(t, text) for t in SPORTS_TERMS):
        return False
    lenient_terms = TOPIC_TERMS + ["education", "school", "institute",
                                   "learning", "scholar"]
    return any(term in text for term in lenient_terms)


# Web domains of startup institutions on the watchlist. A story that
# comes from one of these sites (via the Google News site sweeps) is
# about that institution, so it goes to the Startups channel.
STARTUP_DOMAINS = [
    "greenwayinstitute.org", "newu.university", "newstateu.com",
    "outercoast.org", "aul.city", "cambridgespark.com", "nutm.edu.ng",
    "lis.ac.uk", "musizifoundation.org", "code.berlin", "ozyegin.edu.tr",
    "um6p.ma", "udst.edu.qa", "zamorano.edu", "habib.edu.pk",
    "plaksha.edu.in", "ahduni.edu.in", "atriauniversity.edu.in",
    "acity.edu.gh", "minerva.edu", "krea.edu.in",
    "ashesi.edu.gh", "fulbright.edu.vn", "alueducation.com",
    "harrisburgu.edu", "floridapoly.edu",
]

# Future Universities Alliance network: the established universities in
# the Alliance's official Innovation Sandbox cohort (Pathway 2, "New
# Initiatives in Existing Institutions", and Pathway 3, "Amplifying
# Signature Innovations"), plus Elmbridge University, a Sandbox
# participant at the October 2026 summit, and four institutions close to
# the Alliance: Tecnologico de Monterrey, Duke Kunshan University, Pomona
# College, and Soka University of America. Cohort members that are also
# on the startup WATCHLIST above (Habib, Plaksha, UM6P and others) keep
# going to the Startups channel. Stories naming a member below go to the
# FUA Network channel.
#   tier "strict": large universities with heavy daily news - a story
#                  must also be about institutional change or teaching
#                  innovation, not sports, hospitals, or lab results
#   tier "open":   smaller members - any higher-education story counts
FUA_NETWORK = [
    {"names": ["duke university"], "domain": "duke.edu", "tier": "strict"},
    {"names": ["georgetown university"], "domain": "georgetown.edu", "tier": "strict"},
    {"names": ["northeastern university"], "domain": "northeastern.edu",
     "tier": "strict"},
    {"names": ["university of north texas"], "domain": "unt.edu", "tier": "strict"},
    {"names": ["university of nebraska-lincoln", "university of nebraska\u2013lincoln",
               "university of nebraska lincoln"], "domain": "unl.edu",
     "tier": "strict"},
    {"names": ["chulalongkorn university"], "domain": "chula.ac.th", "tier": "strict"},
    {"names": ["bard college"], "domain": "bard.edu", "tier": "open"},
    {"names": ["lehigh university"], "domain": "lehigh.edu", "tier": "open"},
    {"names": ["montclair state university", "montclair state"],
     "domain": "montclair.edu", "tier": "open"},
    {"names": ["drew university"], "domain": "drew.edu", "tier": "open"},
    {"names": ["mercy university"], "domain": "mercy.edu", "tier": "open"},
    {"names": ["unc asheville", "university of north carolina asheville",
               "university of north carolina at asheville"],
     "domain": "unca.edu", "tier": "open"},
    {"names": ["vermont state university", "vermont state colleges"],
     "domain": "vermontstate.edu", "tier": "open"},
    {"names": ["harper adams university"], "domain": "harper-adams.ac.uk",
     "tier": "open"},
    {"names": ["james cook university"], "domain": "jcu.edu.au", "tier": "open"},
    {"names": ["western sydney university"], "domain": "westernsydney.edu.au",
     "tier": "open"},
    {"names": ["singapore management university"], "domain": "smu.edu.sg",
     "tier": "open"},
    {"names": ["universidad francisco de vitoria", "francisco de vitoria university"],
     "domain": "ufv.es", "tier": "open"},
    {"names": ["university of central punjab"], "domain": "ucp.edu.pk",
     "tier": "open"},
    {"names": ["elmbridge university"], "domain": None, "tier": "open"},
    {"names": ["tecnológico de monterrey", "tecnologico de monterrey",
               "tec de monterrey", "monterrey tech"], "domain": "tec.mx",
     "tier": "strict"},
    {"names": ["duke kunshan university", "duke kunshan"],
     "domain": "dukekunshan.edu.cn", "tier": "open"},
    {"names": ["pomona college"], "domain": "pomona.edu", "tier": "open"},
    {"names": ["soka university of america"], "domain": "soka.edu",
     "tier": "open"},
]

# Names that sit inside other institutions' names: a match is ignored
# when one of these longer phrases is what the story actually says.
NAME_EXCLUSIONS = {
    "mercy university": ["mercy university hospital"],
    "james cook university": ["james cook university hospital"],
}

# Stories about these subjects never count as network news.
SPORTS_TERMS = [
    "basketball", "football", "soccer", "baseball", "softball",
    "volleyball", "wrestling", "hockey", "lacrosse", "ncaa", "quarterback",
    "touchdown", "playoff", "playoffs", "head coach", "transfer portal",
    "march madness", "final four", "bowl game", "athletics", "athlete",
]
MEDICAL_TERMS = [
    "hospital", "patients", "clinical trial", "cancer", "health system",
    "surgery", "medical center",
]


def site_domain(url):
    """The bare web domain of a URL ("www.duke.edu/x" -> "duke.edu")."""
    try:
        netloc = urlparse(url or "").netloc.lower()
    except ValueError:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def domain_matches(domain, target):
    return bool(domain and target) and (domain == target
                                        or domain.endswith("." + target))


def startup_site_hit(story):
    """True when a story was published on a startup institution's site."""
    domain = site_domain(story.get("origin", ""))
    if not any(domain_matches(domain, d) for d in STARTUP_DOMAINS):
        return False
    text = (story["title"] + " " + story["summary"]).lower()
    return not any(keyword_present(t, text) for t in SPORTS_TERMS)


def network_tier(story, text):
    """The tier of the FUA member a story concerns, and how it was found
    ("title", "text" or "site"), or (None, None)."""
    domain = site_domain(story.get("origin", ""))
    title = story["title"].lower()
    best = (None, None)
    for member in FUA_NETWORK:
        def named_in(where):
            return any(keyword_present(n, where)
                       and not any(x in text for x in NAME_EXCLUSIONS.get(n, []))
                       for n in member["names"])
        if named_in(title):
            how = "title"
        elif named_in(text):
            how = "text"
        elif domain_matches(domain, member["domain"]):
            how = "site"
        else:
            continue
        if member["tier"] == "open":
            return ("open", how)
        best = ("strict", how)
    return best


def network_hit(story):
    """True when a story concerns an FUA network member and passes that
    member's tier test."""
    text = (story["title"] + " " + story["summary"]).lower()
    tier, how = network_tier(story, text)
    if not tier:
        return False
    # broad dailies and search feeds must name the member in the headline
    if how == "text" and story.get("watchlist_only"):
        return False
    if any(keyword_present(t, text) for t in SPORTS_TERMS):
        return False
    lenient_terms = TOPIC_TERMS + ["education", "school", "institute",
                                   "learning", "scholar"]
    if not any(term in text for term in lenient_terms):
        return False
    strict_signals = INSTITUTION_SIGNALS + [
        "higher education", "future of higher education",
        "future universities", "teaching and learning", "student success",
        "provost", "new model"]
    has_signal = (any(keyword_present(s, text) for s in strict_signals)
                  or offering_signal(text))
    # a post found only through its website (homecoming notes, event
    # pages) must be about programs, partnerships or institutional change
    if how == "site":
        return has_signal and not any(keyword_present(t, text)
                                      for t in MEDICAL_TERMS)
    if tier == "open":
        return True
    if any(keyword_present(t, text) for t in MEDICAL_TERMS):
        return False
    return has_signal


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

# The grammar of program announcements: a launch verb near an academic
# unit, or "new" + an academic unit. Catches "introduces new
# cybersecurity degree", "adds data science major", "opens new school
# of computing" without listing every phrasing by hand.
ACADEMIC_UNIT = (r"(?:degree|programme|program|major|minor|school|"
                 r"department|institute|cent(?:er|re)|certificate|"
                 r"curriculum|academy|faculty)")
NEW_OFFERING_RE = re.compile(
    r"\bnew\s+(?:[\w-]+\s+){0,3}?" + ACADEMIC_UNIT + r"s?\b")
LAUNCH_OFFERING_RE = re.compile(
    r"\b(?:launch|introduc|unveil|debut|announc|creat|establish|open|"
    r"start|begin|add|offer|develop|build|roll)\w*\s+"
    r"(?:(?:a|an|its|the|two|three|\d+)\s+)?(?:[\w-]+\s+){0,3}?"
    + ACADEMIC_UNIT + r"s?\b")


def offering_signal(text):
    """True when text announces a new academic offering."""
    return bool(NEW_OFFERING_RE.search(text) or LAUNCH_OFFERING_RE.search(text))


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
        # filled by network_hit() and by FUA's own posts, not by keywords
        "id": "fua",
        "title": "Future Universities Alliance Network",
        "blurb": ("News from the established universities of the Future Universities "
                  "Alliance and its Innovation Sandbox - how they are reinventing themselves "
                  "alongside the startups. Startup members appear under New Startup "
                  "Universities."),
        "color": "#E07A5F",
        "min_score": 99,
        "max": 12,
        "keywords": [],
    },
    {
        "id": "programs",
        "offerings": True,
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
        "title": "Indian Higher Education News",
        "blurb": "The world's most dynamic higher education market - policy, new institutions, and foreign entry.",
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
        "title": "US Higher Education News",
        "blurb": "The notable stories of American higher education - new models, policy, and institutional change.",
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
        "title": "European Higher Education News",
        "blurb": "Higher education across the UK and Europe - policy, reform, and new institutional forms.",
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
        "title": "Chinese Higher Education News",
        "blurb": "Higher education in China and Greater China - new universities, ventures, and reform.",
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
# Web pages that are not news, sometimes picked up from university sites.
PAGE_NOISE_TERMS = [
    "student catalog", "course catalog", "academic catalog", "catalogue",
    "endnote", "citation manager", "referencing", "libguides",
    "research guide", "library guide", "privacy policy", "terms of use",
    "cookie policy", "contact us", "frequently asked questions",
]

NOISE_TERMS = [
    "admit card", "answer key", "exam date", "exam dates", "hall ticket",
    "school assembly", "olympiad", "cut-off", "cutoff", "result declared",
    "results declared", "board exam", "registration begins",
    "application deadline", "toppers", "rank list", "merit list",
]

MANUAL_POSTS = Path(__file__).parent / "fua_posts.json"


def load_manual_posts():
    """Posts added by hand in fua_posts.json - the guaranteed channel
    for Future Universities Alliance posts (Substack blocks automated
    cloud readers, so search-engine bridges can lag). Each entry needs
    title, link, and date (YYYY-MM-DD); posts stay on the page 30 days."""
    if not MANUAL_POSTS.exists():
        return []
    try:
        data = json.loads(MANUAL_POSTS.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        print(f"  WARNING  fua_posts.json could not be read: {err}")
        return []
    out = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    for p in data.get("posts", []):
        try:
            when = datetime.strptime(p["date"], "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if when < cutoff:
            continue
        out.append({"title": p.get("title", "Untitled"),
                    "link": p.get("link", ""),
                    "summary": p.get("summary", ""),
                    "source": "Future Universities (FUA)", "date": when,
                    "boost": None, "region": None, "assign": "fua",
                    "watchlist_only": False})
    if out:
        print(f"  ok       FUA manual posts: {len(out)} within 30 days")
    return out


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
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Referer": url.split("/feed")[0] if "/feed" in url else url,
    }
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 429:
        # the site asked us to slow down - wait politely and retry once
        time.sleep(20)
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
    for feed in FEEDS:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=feed.get("days", DAYS_BACK)))
        if "news.google.com" in feed["url"]:
            time.sleep(3)   # many Google News queries run each night
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
                title = clean_text(entry.get("title", "Untitled"))
                source, origin = feed["name"], ""
                if "news.google.com" in feed["url"]:
                    # Google News names the real publisher and its website;
                    # show the publisher, and keep the site for matching
                    pub = entry.get("source") or {}
                    origin = pub.get("href") or pub.get("url") or ""
                    publisher = clean_text(pub.get("title", ""))
                    if " - " in title:
                        title, suffix = title.rsplit(" - ", 1)
                        publisher = publisher or suffix
                    if publisher:
                        source = publisher
                stories.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "summary": summary[:400],
                    "source": source,
                    "origin": origin,
                    "date": when,
                    "boost": feed.get("boost"),
                    "region": feed.get("region"),
                    "assign": feed.get("assign"),
                    "watchlist_only": feed.get("watchlist_only", False),
                })
                count += 1
            print(f"  ok       {feed['name']}: {count} recent stories")
        except Exception as err:  # noqa: BLE001 - keep the digest resilient
            if "429" in str(err):
                print(f"  waiting  {feed['name']}: rate-limited tonight - "
                      f"temporary, it will retry on the next sweep")
            elif "403" in str(err):
                print(f"  blocked  {feed['name']}: the site refuses "
                      f"automated readers - safe to delete this feed line")
            else:
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
    if category.get("offerings"):
        if offering_signal(title):
            score += 3
        elif offering_signal(summary):
            score += 2
    return score


def is_on_topic(story):
    text = (story["title"] + " " + story["summary"]).lower()
    return any(term in text for term in TOPIC_TERMS)


def categorize(stories):
    """Assign each story to its best-matching channel (or drop it)."""
    buckets = {c["id"]: [] for c in CATEGORIES}
    seen_links, seen_titles = set(), set()
    for story in stories:
        title_key = re.sub(r"[^a-z0-9]+", " ", story["title"].lower()).strip()
        if story["link"] in seen_links or title_key in seen_titles:
            continue
        seen_links.add(story["link"])
        seen_titles.add(title_key)
        title = story["title"].lower()
        if any(keyword_present(t, title) for t in NOISE_TERMS):
            continue
        if any(keyword_present(t, title) for t in PAGE_NOISE_TERMS):
            continue
        # search results titled with one or two words are pages, not news
        if story.get("origin") and len(title.split()) < 3:
            continue
        # institutional newsrooms: every story is about the institution
        if story.get("assign"):
            story["score"] = 10
            buckets[story["assign"]].append(story)
            continue
        # a story naming a tracked startup university, or published on
        # one of their websites, goes to Startups
        if watchlist_hit(story) or startup_site_hit(story):
            story["score"] = 10
            buckets["startups"].append(story)
            continue
        # a story about an FUA network member goes to the FUA channel
        if network_hit(story):
            story["score"] = 10
            buckets["fua"].append(story)
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
        limit = next((c.get("max", MAX_PER_CATEGORY) for c in CATEGORIES
                      if c["id"] == cid), MAX_PER_CATEGORY)
        buckets[cid] = trimmed[:limit]
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
        ("Inside Higher Ed", "Lehigh University launches global leadership minor",
         "The university adds a minor for students through its Iacocca Institute."),
        ("Duke Today", "Duke University unveils new model for global university partnerships",
         "The provost described how the plan will serve higher education partners worldwide."),
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
    stories += load_manual_posts()
    print(f"\nCollected {len(stories)} stories; filtering into channels...")
    buckets = categorize(stories)
    render(buckets, len(FEEDS))


if __name__ == "__main__":
    sys.exit(main())
