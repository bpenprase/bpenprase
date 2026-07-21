"""
The New Universities Observatory - Resources & Reports builder
==============================================================
Builds resources.html: a curated stack of major reports on the
founding of new universities, plus a "newly detected" section filled by
scanning the report-publishing pages of foundations, trackers, and
agencies for new PDF links.

Runs on a slower cadence than the nightly digest (every two weeks).

Run normally:            python resources.py
Curated list only:       python resources.py --no-scan   (no internet needed)

What you might want to edit:
  CURATED     - the hand-picked stack of reports (title, org, year,
                overview, link). This is the heart of the page.
  SCAN_PAGES  - report-index pages to comb for new PDF links.
  PDF_KEYWORDS - a candidate PDF must match one of these terms.
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

# ---------------------------------------------------------------------------
# 1. THE CURATED STACK
# Reports appear on the page in this order. "link" may be a direct PDF
# or a report landing page; "kind" labels which it is.
# ---------------------------------------------------------------------------

CURATED = [
    {
        "title": "Steering Tertiary Education: Toward Resilient Systems that Deliver for All",
        "org": "World Bank", "year": "2021", "kind": "PDF",
        "link": "https://documents1.worldbank.org/curated/en/394931632506279551/pdf/Steering-Tertiary-Education-Toward-Resilient-Systems-that-Deliver-for-All.pdf",
        "overview": ("The World Bank's framework paper on tertiary education - the five 'STEER' "
                     "principles that guide the largest financier of higher education worldwide. "
                     "The best single statement of how the Bank thinks about building, diversifying, "
                     "and sustaining university systems."),
    },
    {
        "title": "A Global Framework for Transnational Education Engagement",
        "org": "British Council", "year": "2024", "kind": "PDF",
        "link": "https://www.britishcouncil.org/sites/default/files/global_tne_framework_research_report.pdf",
        "overview": ("Developed with the QAA and Education Insight, this framework analyzes national "
                     "environments for transnational education and proposes a consistent language and "
                     "data foundation for comparing TNE across countries - including the new Indian "
                     "regulatory environment."),
    },
    {
        "title": "Transnational Education: A Classification Framework and Data Collection Guidelines",
        "org": "British Council & DAAD", "year": "", "kind": "PDF",
        "link": "https://www.britishcouncil.org/sites/default/files/tne_classification_framework-final.pdf",
        "overview": ("The standard reference for what counts as what in cross-border higher education: "
                     "branch campuses, franchises, joint degrees, validation. Essential for anyone "
                     "trying to compare numbers across studies that define TNE differently."),
    },
    {
        "title": "The Shape of Things to Come: The Evolution of Transnational Education",
        "org": "British Council", "year": "2013", "kind": "PDF",
        "link": "https://www.britishcouncil.org/sites/default/files/the_shape_of_things_to_come_2.pdf",
        "overview": ("A landmark study of program and provider mobility with a focus on host countries, "
                     "written with Jane Knight among others. Older now, but the analytical groundwork "
                     "for most of what followed."),
    },
    {
        "title": "Thinking Higher and Beyond: Perspectives on the Futures of Higher Education to 2050",
        "org": "UNESCO IESALC", "year": "2021", "kind": "PDF",
        "link": "https://www.iau-hesd.net/sites/default/files/documents/unesco_iesalc_report.pdf",
        "overview": ("Twenty-five experts from every world region imagine what higher education could "
                     "become by 2050. The conceptual opening of UNESCO's Futures of Higher Education "
                     "project, and a rich source of framing for why new institutions get founded."),
    },
    {
        "title": "Transforming Higher Education: Global Collaboration on Visioning and Action",
        "org": "UNESCO", "year": "2026", "kind": "Report page",
        "link": "https://www.unesco.org/en/articles/transforming-higher-education-global-roadmap-future",
        "overview": ("UNESCO's roadmap for higher education, built from the third World Higher Education "
                     "Conference and consultations with over 15,000 participants. Frames a sector of 269 "
                     "million students and 22,000+ institutions, with seven guiding principles for its "
                     "transformation."),
    },
    {
        "title": "Higher Education Global Trends Report",
        "org": "UNESCO IESALC", "year": "2026", "kind": "Report page",
        "link": "https://www.iesalc.unesco.org/en/articles/shaping-future-higher-education-launch-unescos-global-trends-report",
        "overview": ("The first edition of UNESCO's global trends study - a system-level snapshot of "
                     "inclusion, equity, quality, and mobility across world higher education, linked to "
                     "the Higher Education Policy Observatory's comparative data."),
    },
    {
        "title": "International Branch Campuses: Trends & Developments / Success Factors of Mature IBCs",
        "org": "OBHE & C-BERT", "year": "2016-2017", "kind": "Report page",
        "link": "https://www.cbert.org/our-work",
        "overview": ("The two definitive joint reports on the branch campus phenomenon, with full "
                     "listings of campuses in operation and in development, and interview-based analysis "
                     "of what makes decade-old campuses succeed. C-BERT's research page collects them "
                     "alongside two decades of related scholarship."),
    },
    {
        "title": "The Scale of UK Higher Education Transnational Education (annual series)",
        "org": "Universities UK International", "year": "annual", "kind": "Report page",
        "link": "https://www.universitiesuk.ac.uk/universities-uk-international/insights-and-publications/uuki-insights/scale-uk-transnational-education",
        "overview": ("The annual census of UK TNE - over half a million students studying for UK awards "
                     "in more than 200 countries and territories, broken down by provider, location, and "
                     "mode. UK TNE enrollment is on track to overtake onshore international recruitment."),
    },
    {
        "title": "Becoming Accredited: A Guide for Institutions Abroad",
        "org": "NECHE", "year": "", "kind": "PDF",
        "link": "https://www.neche.org/wp-content/uploads/2018/12/Becoming-Accredited-for-Insts-Abroad-Guide.pdf",
        "overview": ("The pathway document from the most internationally active US accreditor - how a "
                     "new institution outside the United States earns eligibility, candidacy, and "
                     "accreditation. Reading it is the fastest way to understand the gate every new "
                     "US-accredited university abroad must pass through."),
    },
    {
        "title": "Tertiary Education and Skills (TES) Program",
        "org": "World Bank & Mastercard Foundation", "year": "2022-", "kind": "Report page",
        "link": "https://www.worldbank.org/en/programs/tes",
        "overview": ("The umbrella trust fund now carrying the World Bank's current work on tertiary "
                     "education and skills, launched with the Mastercard Foundation. Its publications "
                     "track where new institutional capacity is being financed worldwide."),
    },
]

# ---------------------------------------------------------------------------
# 2. PAGES TO SCAN FOR NEW REPORTS
# Every two weeks the script visits these pages, collects PDF links whose
# text or address matches PDF_KEYWORDS, and lists anything not seen
# before in a "Newly detected" section for your review. Promote the good
# ones into CURATED by hand.
# ---------------------------------------------------------------------------

SCAN_PAGES = [
    {"name": "British Council - TNE research",
     "url": "https://www.britishcouncil.org/research-insight/research-topics/transnational-education"},
    {"name": "World Bank - Tertiary education research",
     "url": "https://www.worldbank.org/en/topic/tertiaryeducation/research"},
    {"name": "UNESCO IESALC - Publications",
     "url": "https://www.iesalc.unesco.org/en/publications/"},
    {"name": "C-BERT - Research",
     "url": "https://www.cbert.org/our-work"},
    {"name": "UUKi - Publications",
     "url": "https://www.universitiesuk.ac.uk/universities-uk-international/insights-and-publications/uuki-publications"},
    {"name": "NECHE - Publications and guides",
     "url": "https://www.neche.org/resources/"},
]

PDF_KEYWORDS = [
    "transnational", "tne", "branch campus", "tertiary", "higher education",
    "university", "universities", "cross-border", "international campus",
    "accredit", "quality assurance",
]

SEEN_FILE = Path(__file__).parent / "seen_reports.json"
OUTPUT = Path(__file__).parent / "resources.html"
TEMPLATE = Path(__file__).parent / "template_resources.html"
MAX_NEW = 20


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_for_new_pdfs():
    """Visit each scan page; return PDF links not recorded in seen_reports.json."""
    import requests
    from bs4 import BeautifulSoup

    seen = set()
    if SEEN_FILE.exists():
        seen = set(json.loads(SEEN_FILE.read_text()))
    # every curated link counts as already known
    seen.update(item["link"] for item in CURATED)

    found = []
    for page in SCAN_PAGES:
        try:
            resp = requests.get(page["url"], timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (NewUniversitiesObservatory resources bot)"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            count = 0
            for a in soup.find_all("a", href=True):
                href = urljoin(page["url"], a["href"])
                text = " ".join(a.get_text().split())
                if ".pdf" not in href.lower():
                    continue
                haystack = (href + " " + text).lower()
                if not any(kw in haystack for kw in PDF_KEYWORDS):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                found.append({
                    "title": text if 5 < len(text) < 160 else href.rsplit("/", 1)[-1],
                    "link": href,
                    "source": page["name"],
                })
                count += 1
            print(f"  ok       {page['name']}: {count} new PDF links")
        except Exception as err:  # noqa: BLE001 - stay resilient
            print(f"  WARNING  {page['name']}: {err}")

    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=1))
    return found[:MAX_NEW]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(new_finds):
    template = TEMPLATE.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc)

    cards = []
    for r in CURATED:
        year = f" &middot; {html.escape(r['year'])}" if r["year"] else ""
        cards.append(f'''<article class="report">
  <p class="report-meta">{html.escape(r["org"])}{year} &middot; <span class="kind">{html.escape(r["kind"])}</span></p>
  <h3><a href="{html.escape(r["link"])}">{html.escape(r["title"])}</a></h3>
  <p class="report-overview">{html.escape(r["overview"])}</p>
</article>''')

    if new_finds:
        items = "".join(
            f'<li><a href="{html.escape(f["link"])}">{html.escape(f["title"])}</a>'
            f'<span class="found-src"> &mdash; found on {html.escape(f["source"])}</span></li>'
            for f in new_finds)
        new_section = f'''<section class="channel" id="new">
  <header class="channel-head" style="border-color:#B0762A">
    <h2><span class="channel-mark" style="background:#B0762A"></span>Newly Detected This Sweep</h2>
    <p class="channel-blurb">PDF links found on the scanned report pages since the last sweep,
    awaiting review. The keepers get promoted into the stack above.</p>
  </header>
  <ul class="found-list">{items}</ul>
</section>'''
    else:
        new_section = ('<p class="empty">No new reports detected on the scanned pages this '
                       'sweep. The next sweep is in two weeks.</p>')

    page = (template
            .replace("{{DATE}}", now.strftime("%B %d, %Y"))
            .replace("{{REPORT_COUNT}}", str(len(CURATED)))
            .replace("{{REPORTS}}", "\n".join(cards))
            .replace("{{NEW_SECTION}}", new_section))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"\nWrote {OUTPUT} - {len(CURATED)} curated reports, "
          f"{len(new_finds)} newly detected.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-scan", action="store_true",
                        help="skip the web scan; build the curated stack only")
    args = parser.parse_args()

    print("The New Universities Observatory - resources sweep")
    print("=" * 50)
    new_finds = [] if args.no_scan else scan_for_new_pdfs()
    render(new_finds)


if __name__ == "__main__":
    sys.exit(main())
