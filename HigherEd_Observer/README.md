# The New Universities Observatory

A nightly digest of the founding of new universities worldwide — startup
institutions, international branch campuses, innovation in Indian higher
education, and the major reports that map the landscape.

Every night, GitHub Actions runs `digest.py`, which reads the RSS feeds of
about 14 higher-education news sources, sorts the past week's stories into
five channels using keyword filters, and rewrites `docs/index.html`.
GitHub Pages serves that page as the public site.

## Setup (one time, about five minutes)

1. **Upload these files** to your repository, keeping the folder structure:

   This kit lives as the folder `HigherEd_Observer/` inside the
   `bpenprase/bpenprase` repository, alongside other sites like
   `Full_Planet/`:

   ```
   (repo root)
   .github/workflows/digest.yml       - runs nightly (MUST be at repo root)
   .github/workflows/resources.yml    - runs on the 1st and 15th
   HigherEd_Observer/
       digest.py                      - nightly news digest builder
       resources.py                   - biweekly Resources & Reports builder
       template.html                  - design of the digest page
       template_resources.html        - design of the resources page
       requirements.txt
       README.md
       index.html                     - starter pages; both rebuilt
       resources.html                   automatically in place
   ```

   The site appears at
   `https://bpenprase.github.io/bpenprase/HigherEd_Observer/`.

2. **GitHub Pages is already on** for this repository (it serves the
   repo root, which is how Full_Planet works), so there is nothing to
   change there.

3. **Allow the workflow to save its work.** Go to
   *Settings → Actions → General*, scroll to "Workflow permissions,"
   choose **Read and write permissions**, and save.

4. **Run it once by hand** to check everything works: go to the
   *Actions* tab, click "Nightly digest" in the left sidebar, then
   "Run workflow." In a minute or two the page will rebuild with live
   stories. After that it runs automatically every night at 06:00 UTC
   (11 pm Pacific).

## Running it on your own computer (optional)

```
pip install -r requirements.txt
python digest.py               # fetches live feeds
python digest.py --demo        # sample stories, no internet needed
python resources.py            # curated stack + scan for new report PDFs
python resources.py --no-scan  # curated stack only, no internet needed
```

Then open `index.html` or `resources.html` in a browser.

## The Resources & Reports page

`resources.py` builds a second page on a slower rhythm (the 1st and 15th
of each month). It has two parts:

- **The curated stack** - the `CURATED` list at the top of the file:
  each entry is a title, organization, year, a short overview in your
  voice, and a link (direct PDF where one exists, otherwise the report's
  landing page). Editing this list is how the shelf grows.
- **Newly detected** - the script re-visits the report pages listed in
  `SCAN_PAGES` (British Council, World Bank, UNESCO IESALC, C-BERT,
  UUKi, NECHE), collects any PDF link matching the topic keywords that
  it has not recorded in `seen_reports.json`, and lists it on the page
  for review. When one deserves a permanent spot, copy it into
  `CURATED` with an overview.

## Making changes

Everything adjustable sits at the top of `digest.py`:

- **FEEDS** — add or remove news sources. If a feed address is wrong the
  script prints a warning and skips it, so experimenting is safe. The
  workflow's log (Actions tab) shows which feeds succeeded each night.
- **CATEGORIES** — the five channels, their descriptions, colors, and
  keyword lists. Tuning the keywords is the main way to improve the
  digest: add terms that should catch stories, raise `min_score` if a
  channel is catching too much noise.
- **DAYS_BACK** and **MAX_PER_CATEGORY** — how far back to look and how
  many stories to show per channel.

The look of the page lives entirely in `template.html` (colors, fonts,
layout, and the explanatory text).

## Ideas for later

- A Claude API step that reads the night's matches and writes a one-line
  "why this matters" note for each story.
- A scraper for NECHE commission actions and the C-BERT campus database,
  which have no RSS feeds but often carry the earliest signals.
- An archive page that keeps each night's digest instead of overwriting it.
