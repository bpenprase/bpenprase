# Full Planet

**A daily portrait of progress in science and technology — from every part of the world.**

Full Planet gathers the newest advances in four fast-moving fields, sorts them into
channels, and publishes a clean daily digest as a website. Each headline links straight
to its original source.

The six channels:

- **Artificial Intelligence** — AI applied to medicine, materials, energy, and discovery
- **Advanced Materials** — new molecules, metals, and polymers for cleaner energy, water, and air
- **Synthetic Biology** — engineered organisms and programmed DNA for computing, data storage, and chemical synthesis
- **Energy & Water** — sustainable energy generation and clean, fresh water for more of humanity
- **Space Exploration** — new missions, spacecraft, and technologies for the space environment
- **Astronomy & Astrophysics** — new telescopes, satellites, and discoveries across the cosmos

---

## How it works (the short version)

1. A small Python script (`build_digest.py`) reads a list of public RSS feeds.
2. It sorts the newest stories into the six channels and saves them to `docs/data/digest.json`.
3. The website in the `docs/` folder reads that file and displays the headlines.
4. A GitHub Action re-runs the script **once a day**, so the site stays current on its own.

You never have to touch the code day to day. Once it's set up, it updates itself.

---

## Setting it up on GitHub (step by step)

You don't need to install anything on your computer for this. Everything happens on GitHub.

**1. Create the repository**
   - On GitHub, click **New repository**. Name it something like `full-planet`.
   - Choose **Public**. Click **Create repository**.

**2. Upload these files**
   - On the new repository page, click **uploading an existing file**.
   - Drag in everything from this project folder, keeping the folder structure intact
     (the `docs/` folder, the `.github/` folder, `build_digest.py`, `feeds.py`, etc.).
   - Click **Commit changes**.

**3. Turn on GitHub Pages (this publishes the website)**
   - Go to **Settings → Pages**.
   - Under **Source**, choose **Deploy from a branch**.
   - Set the branch to **main** and the folder to **/docs**. Click **Save**.
   - After a minute, GitHub shows you the live web address. That's your site.

**4. Let the daily updater run**
   - Go to the **Actions** tab. If prompted, click to enable workflows.
   - You'll see **Daily digest**. Click it, then **Run workflow** to build it once right now
     (instead of waiting until tomorrow morning).
   - From then on it runs automatically every day at 09:00 UTC.

That's it. Your site is live and refreshes itself daily.

---

## Making it yours

**Change which sources feed each channel**
Open `feeds.py`. Each channel has a list of feed web addresses. Add a line to include a
new source, or delete a line to remove one. Save the file (commit the change on GitHub) and
the next daily build uses your new list.

**Add a whole new channel**
In `feeds.py`, copy one of the existing channel blocks, give it a new short key, name,
tagline, accent color, and feeds. Then add a matching card to `docs/index.html` (copy an
existing `channel-card` block and change its `?c=` link and text). 

**Focus a channel on a narrow topic (keyword filtering)**
Some feeds are broad. The Synthetic Biology channel, for example, draws on
general biotechnology and genetics feeds that also carry medical and wildlife
stories. To keep only the stories you want, a channel in `feeds.py` can include
an optional `filter` block:

```python
"filter": {
    "include": ["engineered microbe", "synthetic cell", "DNA data storage"],
    "exclude": ["cancer", "clinical trial", "wildlife"],
},
```

A story is kept only if its headline or summary matches one of the `include`
terms and none of the `exclude` terms. Exclude always wins, so a story about
"engineered bacteria to detect cancer" is dropped as medical, not synthetic
biology. Single words match whole words only (so "gene" won't match "generous"),
and multi-word phrases match exactly. To loosen or tighten a channel, just add or
remove terms and re-run the build. Only Synthetic Biology uses a filter today;
any channel can adopt one the same way.

**Change the schedule**
In `.github/workflows/daily-digest.yml`, the line `cron: "0 9 * * *"` sets the time
(09:00 UTC). Change the numbers to update at a different hour.

**Change the wording or colors**
The landing-page text lives in `docs/index.html`. Colors and fonts live in
`docs/assets/style.css` at the top, under `:root`.

---

## Running it on your own computer (optional)

If you ever want to preview locally:

```bash
pip install -r requirements.txt
python build_digest.py          # fetches feeds, writes data/digest.json
python -m http.server 8000      # then open http://localhost:8000
```

> Note: the sample `digest.json` included here lets the site display example headlines
> before the first real build runs. The daily build replaces it with live stories.

---

## A note on sources and fairness

Feeds were chosen to spread coverage across the United States, Europe, China, India, and
the Global South wherever public feeds exist. Some regions publish fewer machine-readable
feeds in English, so the balance isn't perfect — `feeds.py` is the place to keep widening
it over time. Headlines always link back to the original publisher; Full Planet is a
non-commercial educational project.
