"""
Feed configuration for Full Planet.

Design principle (important):
Broad, high-quality outlets — Scientific American, BBC Science & Environment,
Science/AAAS — carry a little of everything. Rather than drop them (which
loses their quality) or dump them raw into one channel (which pollutes it),
we feed them into EVERY channel and let each channel's keyword filter keep
only the on-topic stories. That means every channel needs a filter. Niche
topical feeds (ScienceDaily sections, Nature subjects, NASA, ESA, ESO) are
already on-topic, but they pass through the same filter harmlessly.

Verified-live feeds (fetched and confirmed working July 2026):
  - https://rss.sciam.com/ScientificAmerican-Global   (Scientific American)
  - https://feeds.bbci.co.uk/news/science_and_environment/rss.xml  (BBC)
  - https://www.science.org/rss/news_current.xml       (Science / AAAS)

Space agencies: NASA and ESA publish reliable English RSS. ISRO, JAXA, CNES,
and the Chinese agencies largely do not, but their missions (and SpaceX
launches) are covered by BBC / Scientific American, so the Space Exploration
filter captures them by keyword regardless of which outlet reports them.

To add a source: paste its RSS URL into the right channel's "feeds" list.
To tune a channel: edit its include / require / exclude keyword lists.
"""

# ---- broad, verified, high-quality feeds reused across all channels ----
# Scientific American's newer syndication endpoint (proper SSL; the older
# rss.sciam.com host has a broken TLS handshake that fails on CI runners).
SCIAM = "https://www.scientificamerican.com/platform/syndication/rss/"
BBC_SCIENCE = "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"
SCIENCE_AAAS = "https://www.science.org/rss/news_current.xml"
BROAD = [SCIAM, BBC_SCIENCE, SCIENCE_AAAS]

# ---- regional / global feeds (second pass, appended after primary) ----
# These broaden coverage to science from China, East and Southeast Asia, the
# Middle East, continental Europe, India, Africa, and Latin America. All are
# run through each channel's regional filter, so only on-topic stories appear.
#
# STATE-AFFILIATION LABELS: sources whose display name is tagged in
# build_digest.py's SOURCE_NAMES map (e.g. "Xinhua (state media)") are
# state-owned or state-funded outlets, shown transparently so readers can weigh
# them accordingly. Public research bodies (Max Planck, CERN, DW, CNRS) are
# government-funded but editorially credible and are NOT tagged as state media.

# --- India & Global South (already established, verified working) ---
SCIDEV = "https://www.scidev.net/global/global_rss.xml"          # Global South nonprofit
HINDU_SCI = "https://www.thehindu.com/sci-tech/science/feeder/default.rss"
HINDU_TECH = "https://www.thehindu.com/sci-tech/technology/feeder/default.rss"
INDIAN_EXPRESS_TECH = "https://indianexpress.com/section/technology/feed/"
CONVERSATION_AFRICA = "https://theconversation.com/africa/articles.atom"

# --- China (mix of independent-leaning and clearly-labeled state media) ---
SCMP_SCIENCE = "https://www.scmp.com/rss/318224/feed"            # Alibaba-owned, HK
SCMP_CHINA_TECH = "https://www.scmp.com/rss/320663/feed"         # Alibaba-owned, HK
XINHUA_SCITECH = "http://www.xinhuanet.com/english/rss/scirss.xml"  # PRC state media
TECHNODE = "https://technode.com/feed/"                          # independent China-tech

# --- East Asia (Japan, Korea) ---
SCIENCE_JAPAN = "https://sj.jst.go.jp/feed/rss.xml"              # Japan govt research agency
KOREA_HERALD_BIZ = "https://www.koreaherald.com/rss/kh_Business"  # independent (tech under Business)

# --- Southeast Asia ---
ASIAN_SCIENTIST = "https://www.asianscientist.com/feed/"         # independent, Singapore
RAPPLER_SCIENCE = "https://www.rappler.com/science/feed"         # independent, Philippines
RAPPLER_TECH = "https://www.rappler.com/technology/feed"         # independent, Philippines
RAPPLER_ENV = "https://www.rappler.com/environment/feed"         # independent, Philippines
CONVERSATION_ID = "https://theconversation.com/id/articles.atom"  # Indonesia academics

# --- Middle East ---
# Note: Times of Israel and Al-Fanar hard-block bots (403), and ISRAEL21c's
# feed returned empty, so we currently have no reliable Middle East science
# feed. The regional mix still spans China, India, Japan, Korea, SE Asia,
# Africa, and Europe. (Al Jazeera's all-news feed is state-funded; omitted.)

# --- Continental Europe (English) ---
DW_SCIENCE = "https://rss.dw.com/xml/rss_en_science"             # German public broadcaster
DW_ENVIRONMENT = "https://rss.dw.com/xml/rss_en_environment"     # German public broadcaster
MAX_PLANCK = "https://www.mpg.de/en/research.rss"                # independent research org
# CERN_NEWS removed: https://home.cern/api/news/news/feed.rss returns HTTP 404.
CNRS_NEWS = "https://news.cnrs.fr/rss"                           # French public research agency

# Region groupings for convenient reuse.
ASIA_GENERAL = [SCMP_SCIENCE, SCMP_CHINA_TECH, XINHUA_SCITECH, TECHNODE,
                SCIENCE_JAPAN, KOREA_HERALD_BIZ, ASIAN_SCIENTIST]
GLOBAL_SOUTH = [SCIDEV, HINDU_SCI, INDIAN_EXPRESS_TECH, CONVERSATION_AFRICA,
                RAPPLER_SCIENCE, CONVERSATION_ID]
EUROPE = [DW_SCIENCE, MAX_PLANCK, CNRS_NEWS]

# Default broad regional set: a balanced world mix used by most channels.
REGIONAL = (
    [SCIDEV, HINDU_SCI, INDIAN_EXPRESS_TECH, CONVERSATION_AFRICA]   # India / Africa / Global South
    + [SCMP_SCIENCE, SCMP_CHINA_TECH, XINHUA_SCITECH]               # China (indep + state)
    + [SCIENCE_JAPAN, KOREA_HERALD_BIZ, ASIAN_SCIENTIST]           # East & SE Asia
    + [DW_SCIENCE, MAX_PLANCK]                                      # Europe
)


CHANNELS = {
    "ai": {
        "name": "Artificial Intelligence",
        "tagline": "AI put to work in science and engineering \u2014 new materials, proteins, medicines, and discoveries.",
        "accent": "#5AA9E6",
        "regional_feeds": REGIONAL + [TECHNODE, RAPPLER_TECH],
        "regional_filter": {
            "require": ["AI", "A.I.", "artificial intelligence", "machine learning",
                        "neural network", "deep learning", "algorithm", "generative",
                        "AlphaFold", "foundation model", "reinforcement learning"],
            "include": [],
            # Same strong exclude as the primary pass, so the "around the world"
            # AI stories are also focused on AI-for-science, not general AI.
            "exclude": [
                "chatbot", "chatbots", "copilot", "smartphone", "gadget",
                "stock", "shares", "valuation", "funding round", "raises $",
                "billion", "lawsuit", "regulation", "regulators", "copyright",
                "layoffs", "hiring", "CEO", "advertising", "social media",
                "deepfake", "election", "misinformation", "subscription",
                "app store", "gaming", "video game", "influencer", "CES",
                "executive order", "warehouse", "customer service", "retail",
                "translation app", "homework", "tutor", "recommendation",
                "recommendations", "surveillance", "cybersecurity", "coding",
                "self-driving", "autonomous vehicle", "content creation",
                "image generation", "art generator", "job market", "workforce",
                "productivity", "virtual assistant", "voice assistant",
                "search engine", "ad revenue", "data privacy", "facial recognition",
                "startup", "benchmark", "leaderboard", "smartphone app",
            ],
        },
        "feeds": [
            "https://www.technologyreview.com/topic/artificial-intelligence/feed",
            "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml",
            "https://rss.sciencedaily.com/computers_math/artificial_intelligence.xml",
            "https://spectrum.ieee.org/topic/artificial-intelligence/feed",
            "https://www.quantamagazine.org/feed/",
        ] + BROAD,
        # Approach: REQUIRE an AI/ML signal, then use a strong EXCLUDE list to
        # remove general-AI / consumer / business stories. We do NOT also require
        # a science-domain term, because that double-gate was rejecting most
        # genuine AI-for-science stories (their headlines don't always name the
        # domain). Instead, "AI minus the noise" keeps the channel full while
        # staying focused on AI applied to research and engineering.
        "filter": {
            "require": [
                "AI", "A.I.", "artificial intelligence", "machine learning",
                "neural network", "deep learning", "algorithm", "generative",
                "AlphaFold", "ChatGPT", "language model", "GPT", "large language",
                "foundation model", "machine-learning", "deep-learning",
                "transformer model", "diffusion model", "reinforcement learning",
            ],
            "include": [
                # AI story must ALSO touch a science/engineering DOMAIN. This
                # is what keeps the channel focused on "AI used to solve science
                # & engineering problems" rather than general AI news. There's
                # ample AI-for-science volume, so this gate doesn't starve it.
                "protein", "proteins", "molecule", "molecules", "molecular",
                "drug", "drugs", "material", "materials", "catalyst", "catalysis",
                "chemistry", "chemical", "genome", "genomic", "genomics", "gene",
                "genes", "medicine", "medical", "disease", "diagnosis", "diagnostic",
                "clinical", "physics", "quantum", "fusion", "plasma", "climate",
                "weather", "battery", "batteries", "solar", "astronomy",
                "astrophysics", "telescope", "galaxy", "galaxies", "cosmic",
                "cosmology", "exoplanet", "black hole", "neutron star",
                "neuroscience", "brain", "enzyme", "enzymes", "biology",
                "biological", "biomedical", "cell", "cells", "crystal",
                "semiconductor", "superconductor", "biochemistry", "spectroscopy",
                "mathematics", "mathematical", "theorem", "proof", "vaccine",
                "antibiotic", "antibody", "cancer", "tumor", "microscopy",
                "microscope", "simulation", "fluid dynamics", "seismic",
                "earthquake", "nanoparticle", "photonic", "laser", "atom",
                "atoms", "particle", "biomolecule", "RNA", "DNA", "scientific",
                "science", "research", "discovery", "engineering", "biotech",
                "biotechnology", "materials science", "drug discovery",
                "protein structure", "weather forecast", "fusion reactor",
                "particle physics", "quantum computing", "gene expression",
                "biomarker", "genetic", "microbiome", "bacteria", "virus",
                "photosynthesis", "energy", "renewable", "battery material",
            ],
            "exclude": [
                # consumer / product / business / policy / general-tech AI noise
                "chatbot", "chatbots", "copilot", "smartphone", "gadget",
                "stock", "shares", "valuation", "funding round", "raises $",
                "billion", "lawsuit", "regulation", "regulators", "copyright",
                "layoffs", "hiring", "CEO", "advertising", "social media",
                "deepfake", "election", "misinformation", "subscription",
                "app store", "gaming", "video game", "influencer", "CES",
                "executive order", "warehouse", "customer service", "retail",
                "translation app", "homework", "tutor", "recommendation",
                "recommendations", "surveillance", "network intrusion",
                "cybersecurity", "coding", "self-driving", "autonomous vehicle",
                "content creation", "image generation", "art generator",
                "job market", "workforce", "productivity", "virtual assistant",
                "voice assistant", "search engine", "ad revenue", "data privacy",
                "facial recognition", "OpenAI", "Anthropic", "Google DeepMind",
                "Nvidia", "startup", "benchmark", "leaderboard",
                "open-source model", "fine-tuning",
            ],
            # SCORE terms rank stories by how strongly they're about AI applied
            # to science & engineering. A story matching these in its title
            # ranks highest; the top 12 are shown. This keeps the channel from
            # drifting toward general AI while still drawing on many feeds.
            "score": [
                "protein", "proteins", "protein folding", "protein structure",
                "materials science", "new material", "new materials", "molecule",
                "molecules", "molecular", "drug discovery", "drug design",
                "new drug", "catalyst", "chemistry", "chemical reaction",
                "genomics", "genome", "gene expression", "disease diagnosis",
                "medical imaging", "physics", "quantum", "fusion", "plasma",
                "particle physics", "superconductor", "semiconductor",
                "enzyme", "biochemistry", "crystal", "spectroscopy",
                "mathematical proof", "theorem", "scientific discovery",
                "astrophysics", "astronomy", "telescope", "cosmology",
                "galaxy", "galaxies", "exoplanet", "black hole", "neutron star",
                "antibiotic", "antibody", "vaccine", "cancer", "structural biology",
                "cell biology", "neuroscience", "climate model", "weather forecast",
                "fluid dynamics", "seismic", "nanoparticle", "battery material",
                "solar cell", "chemical synthesis", "quantum chemistry",
                "biomolecule", "genome sequencing", "material properties",
            ],
        },
        "top_n": 12,  # show the 12 most science-relevant AI stories
    },
    "materials": {
        "name": "Advanced Materials",
        "tagline": "New molecules, metals, and polymers for cleaner energy, water, and air.",
        "accent": "#E8A13A",
        "regional_feeds": REGIONAL + [CNRS_NEWS],
        "regional_filter": {
            "require": ["material", "nanotech", "nanomaterial", "biosensor",
                        "polymer", "molecule", "catalyst", "chemistry", "graphene",
                        "coating", "membrane", "semiconductor", "battery", "alloy"],
            "include": [], "exclude": [],
        },
        "feeds": [
            "https://www.sciencedaily.com/rss/matter_energy/materials_science.xml",
            "https://www.sciencedaily.com/rss/matter_energy/nanotechnology.xml",
            "https://www.sciencedaily.com/rss/matter_energy/chemistry.xml",
        ] + BROAD,
        "filter": {
            "include": [
                "material", "materials", "polymer", "alloy", "metal", "crystal",
                "nanomaterial", "nanotech", "nanoparticle", "molecule",
                "molecular", "catalyst", "composite", "graphene", "ceramic",
                "semiconductor", "superconductor", "coating", "membrane",
                "battery", "electrode", "chemistry", "chemical", "compound",
                "fabric", "textile", "concrete", "steel", "photonic",
            ],
            "exclude": [
                "dinosaur", "fossil", "wildlife", "butterfly", "capybara",
                "horse", "gecko", "dementia", "cancer", "heatwave",
            ],
        },
    },
    "synbio": {
        "name": "Synthetic Biology",
        "tagline": "Engineered organisms and programmed DNA \u2014 cells built for computing, data storage, and chemical synthesis.",
        "accent": "#5FBF9B",
        # Biotech/genetics ScienceDaily feeds also update slowly, so look back
        # further to surface genuine synthetic-biology research.
        "lookback_days": 45,
        "regional_feeds": REGIONAL + [ASIAN_SCIENTIST],
        "regional_filter": {
            # Looser than the primary but still SPECIFIC. Earlier this list had
            # bare terms ("engineer", "microbe", "cultured", "lab-grown") that
            # falsely matched off-topic stories ("engineers build a telescope",
            # "microbes on Mars", "rocket engine", "lab-grown diamond"). Every
            # term here now names a synthetic-biology concept explicitly.
            "require": [
                "synthetic biology", "synthetic cell", "synthetic organism",
                "engineered bacteria", "engineered microbe", "engineered microbes",
                "engineered cell", "engineered cells", "engineered organism",
                "engineered yeast", "engineered microorganism", "engineered enzyme",
                "engineered gene", "engineered plant", "engineered crop",
                "genetically modified", "genetically engineered", "gmo",
                "gene-edited", "gene edited", "gene editing", "gene-editing",
                "CRISPR", "genome editing", "genome-edited", "base editing",
                "prime editing", "bioengineered", "bioengineering",
                "gene therapy", "gene drive", "genetic circuit",
                "designer microbe", "designer organism", "metabolic engineering",
                "biomanufactur", "synthetic genome", "cultured meat",
                "lab-grown meat", "cultivated meat", "DNA data storage",
                "living material", "biofuel", "bioremediation",
                "microbial factory", "cell factory", "programmable cell",
            ],
            "include": [],
            "exclude": ["dinosaur", "fossil", "wildlife", "conservation",
                        "telescope", "galaxy", "exoplanet", "asteroid",
                        "rocket", "spacecraft", "diamond", "Mars rover"],
        },
        "feeds": [
            # Verified against ScienceDaily's official RSS index. These are the
            # feeds most likely to carry synthetic-biology / bioengineering news.
            "https://www.sciencedaily.com/rss/plants_animals/biotechnology.xml",
            "https://www.sciencedaily.com/rss/plants_animals/biotechnology_and_bioengineering.xml",
            "https://www.sciencedaily.com/rss/plants_animals/genetically_modified.xml",
            "https://www.sciencedaily.com/rss/plants_animals/genetics.xml",
            "https://www.sciencedaily.com/rss/plants_animals/bacteria.xml",
            "https://www.sciencedaily.com/rss/plants_animals/microbiology.xml",
            "https://www.sciencedaily.com/rss/plants_animals/microbes_and_more.xml",
            "https://www.sciencedaily.com/rss/plants_animals/molecular_biology.xml",
            "https://www.sciencedaily.com/rss/plants_animals/cell_biology.xml",
            "https://www.sciencedaily.com/rss/matter_energy/biochemistry.xml",
        ] + BROAD,
        # Synthetic biology = human-designed / engineered life and programmed
        # DNA. The require gate lists SPECIFIC synbio concepts (never a bare
        # "engineer"/"cell", which would match rocket engineers or basic cell
        # biology). Matching any one is enough — no second include gate — so the
        # channel fills well. A score list then ranks the most on-theme stories.
        "filter": {
            "require": [
                # engineered organisms & synthetic life
                "synthetic biology", "synthetic cell", "synthetic cells",
                "synthetic organism", "synthetic life", "synthetic genome",
                "synthetic microbe", "synthetic bacteria", "synthetic yeast",
                "synthetic dna", "spudcell", "spud cell", "artificial cell",
                "artificial chromosome", "minimal cell", "minimal genome",
                "engineered bacteria", "engineered microbe", "engineered microbes",
                "engineered cell", "engineered cells", "engineered organism",
                "engineered yeast", "engineered microorganism", "engineered enzyme",
                "engineered gene", "engineered genome", "engineered plant",
                "engineered crop", "engineered algae", "engineered virus",
                "engineered bacteriophage", "engineered protein",
                # genetic engineering techniques
                "genetically modified", "genetically engineered", "gmo",
                "gene-edited", "gene edited", "gene editing", "gene-editing",
                "genome editing", "genome-edited", "genome synthesis",
                "genome writing", "CRISPR", "base editing", "prime editing",
                "gene drive", "genetic circuit", "gene circuit", "genetic engineering",
                "bioengineered", "bioengineering", "synthetic gene",
                # applied synbio
                "metabolic engineering", "biomanufacturing", "biofoundry",
                "biosynthesis", "designer microbe", "designer organism",
                "designer cell", "programmable cell", "programmed cell",
                "programmed microbe", "program microbes", "reprogrammed cell",
                "reprogrammed bacteria", "cell factory", "microbial factory",
                "chassis organism", "modified bacteria", "modified microbe",
                "modified yeast", "modified organism", "phage engineering",
                "cell-free system", "cultured meat", "cultivated meat",
                "lab-grown meat", "biofabrication",
                # bio-computing / DNA data
                "biological computer", "biological computing", "biocomputing",
                "DNA computing", "DNA data storage", "DNA storage",
                "data in DNA", "data into DNA", "DNA synthesis", "DNA writing",
                "living material", "living machine", "living robot",
                "xenobot", "biobot",
            ],
            "include": [],  # require-only: any specific synbio term is enough
            "score": [
                # rank the most clearly on-theme (engineered life + applications)
                "synthetic biology", "engineered bacteria", "engineered microbe",
                "engineered cell", "engineered organism", "synthetic cell",
                "synthetic organism", "synthetic life", "artificial cell",
                "genetically engineered", "gene editing", "CRISPR",
                "genome editing", "designer organism", "designer microbe",
                "living material", "DNA data storage", "biomanufacturing",
                "metabolic engineering", "biosynthesis", "cell factory",
                # applications you care about
                "carbon", "sequester", "capture", "bioremediation", "cleanup",
                "clean up", "pollution", "biofuel", "chemical synthesis",
                "synthesize", "produce", "manufacture", "sustainable",
                "environment", "plastic", "waste", "biosensor",
            ],
            "exclude": [
                # Only clearly off-topic terms. The specific require gate keeps
                # this channel focused, so we DON'T exclude context words like
                # "wildlife"/"endangered" that legitimately appear in summaries
                # of engineered-organism stories (e.g. "microbe that protects
                # endangered habitats"). We keep astronomy/space terms to block
                # the leaks seen earlier, plus a couple of paleontology terms.
                "dinosaur", "fossil", "human embryo", "IVF", "fertility clinic",
                "telescope", "galaxy", "exoplanet", "rocket", "spacecraft",
                "asteroid", "lab-grown diamond",
            ],
        },
    },
    "energywater": {
        "name": "Energy & Water",
        "tagline": "New ways to generate clean energy, capture carbon, and bring fresh water and power to people, cities, and transport.",
        "accent": "#33C6D6",
        # ScienceDaily's energy category feeds update slowly (newest items are
        # often 6-8 weeks old), so this channel looks back 60 days to still
        # surface that research, and adds daily-updating renewable-news feeds.
        "lookback_days": 60,
        "regional_feeds": REGIONAL + [DW_ENVIRONMENT, RAPPLER_ENV, CNRS_NEWS],
        "regional_filter": {
            "require": ["solar power", "solar energy", "solar panel", "solar farm",
                        "wind power", "wind energy", "wind turbine", "renewable",
                        "battery", "hydrogen", "clean energy", "clean water",
                        "drinking water", "water access", "desalination",
                        "sanitation", "power grid", "electricity access",
                        "off-grid", "biogas", "irrigation", "groundwater",
                        "clean power", "water purification", "microgrid",
                        "hydropower", "geothermal", "energy storage", "biofuel",
                        "carbon capture", "electric vehicle", "green energy"],
            "include": [],
            "exclude": ["dinosaur", "wildlife", "solar flare", "solar wind",
                        "solar system", "solar eclipse", "coronal"],
        },
        "feeds": [
            "https://www.sciencedaily.com/rss/matter_energy/energy_technology.xml",
            "https://www.sciencedaily.com/rss/matter_energy/solar_energy.xml",
            "https://www.sciencedaily.com/rss/earth_climate/renewable_energy.xml",
            "https://www.sciencedaily.com/rss/earth_climate/water.xml",
            "https://www.sciencedaily.com/rss/matter_energy/fuel_cells.xml",
            "https://www.sciencedaily.com/rss/matter_energy/batteries.xml",
            "https://www.sciencedaily.com/rss/matter_energy/nuclear_energy.xml",
            "https://www.sciencedaily.com/rss/matter_energy/alternative_fuels.xml",
            "https://www.sciencedaily.com/rss/matter_energy/wind_energy.xml",
            "https://www.sciencedaily.com/rss/earth_climate/energy.xml",
            # daily-updating renewable-energy news outlets (fix for stale
            # ScienceDaily category feeds — these carry current stories)
            "https://renewablesnow.com/feed/",
            "https://www.renewableenergyworld.com/feed/",
        ] + BROAD,
        # Focus tightly on (1) GENERATING clean/green energy — solar, wind,
        # fusion, nuclear, geothermal, hydro, hydrogen — and (2) SOURCING and
        # TREATING water — desalination, atmospheric water harvesting,
        # purification, conservation. Deliberately excludes generic "battery/
        # EV/smart-grid/energy-efficiency" consumer-tech and business stories,
        # which were diluting the channel. The require gate demands a specific
        # generation or water-technology term.
        "filter": {
            "require": [
                # --- clean energy GENERATION ---
                "solar power", "solar energy", "solar cell", "solar panel",
                "solar farm", "photovoltaic", "photovoltaics", "perovskite solar",
                "concentrated solar", "wind power", "wind turbine", "wind farm",
                "wind energy", "offshore wind", "nuclear power", "nuclear reactor",
                "nuclear fusion", "fusion energy", "fusion reactor", "fusion power",
                "tokamak", "geothermal", "hydropower", "hydroelectric",
                "tidal energy", "tidal power", "wave energy", "hydrogen fuel",
                "green hydrogen", "hydrogen production", "clean hydrogen",
                "biofuel", "biogas", "bioenergy", "renewable energy",
                "renewable power", "clean energy", "green energy",
                "sustainable energy", "clean power", "carbon-free",
                "power generation", "electricity generation", "energy generation",
                "fuel cell", "artificial photosynthesis", "nuclear fission",
                # --- carbon capture (clean-energy adjacent) ---
                "carbon capture", "carbon sequestration", "direct air capture",
                "carbon dioxide removal", "CO2 capture", "carbon storage",
                # --- WATER sourcing & treatment ---
                "desalination", "desalinate", "atmospheric water",
                "water from air", "water harvesting", "water purification",
                "water filtration", "water treatment", "clean water",
                "fresh water", "freshwater", "drinking water", "potable water",
                "safe water", "water access", "water scarcity", "wastewater",
                "water recycling", "water conservation", "water reclamation",
                "groundwater", "aquifer recharge", "water supply", "sanitation",
                "solar still", "reverse osmosis", "water membrane",
                # --- energy storage tied to clean/renewable power ---
                "grid-scale battery", "grid storage", "energy storage",
                "renewable storage", "flow battery", "solid-state battery",
                "sodium-ion battery", "long-duration storage", "battery storage",
                "green ammonia", "hydrogen storage", "thermal storage",
                # --- water verb forms & extras ---
                "purify water", "purifies water", "purifying water",
                "clean drinking water", "water crisis", "water technology",
                "harvest water", "harvesting water", "atmospheric moisture",
            ],
            "include": [],  # require gate is specific enough; keep all that pass
            "score": [
                # rank the clearest clean-generation & water-tech stories highest
                "solar cell", "solar power", "solar energy", "photovoltaic",
                "wind power", "wind turbine", "wind energy", "nuclear fusion",
                "fusion energy", "fusion reactor", "geothermal", "green hydrogen",
                "hydrogen fuel", "renewable energy", "clean energy", "clean power",
                "tidal energy", "wave energy", "hydropower", "fuel cell",
                "carbon capture", "direct air capture", "energy storage",
                "grid storage", "perovskite", "desalination", "water purification",
                "atmospheric water", "water harvesting", "clean water",
                "drinking water", "water treatment", "wastewater", "reverse osmosis",
                "efficiency", "breakthrough", "generate", "generation", "renewable",
            ],
            "exclude": [
                # Only truly off-topic terms. We rely on the REQUIRE gate (which
                # demands a specific energy/water technology term) to keep the
                # channel focused. The old list wrongly killed real energy
                # stories whose summaries mentioned "climate", "species",
                # "sea level rise", etc. as ordinary context.
                "goldfish", "aquarium", "dinosaur", "horoscope", "astrology",
                "solar flare", "solar wind", "solar system", "solar eclipse",
                "coronal mass", "sunspot", "solar storm",
            ],
        },
    },
    "spaceexploration": {
        "name": "Space Exploration",
        "tagline": "New missions, spacecraft, and technologies \u2014 NASA, ESA, ISRO, JAXA, SpaceX, CNES, and more.",
        "accent": "#F0894E",
        "regional_feeds": [SCIDEV, HINDU_SCI, HINDU_TECH, INDIAN_EXPRESS_TECH,
                            SCMP_SCIENCE, SCMP_CHINA_TECH, XINHUA_SCITECH,
                            SCIENCE_JAPAN, KOREA_HERALD_BIZ, CNRS_NEWS,
                            DW_SCIENCE, TECHNODE, ASIAN_SCIENTIST],
        "regional_filter": {
            "require": [
                # generic space terms (any agency/company)
                "space", "rocket", "launch", "satellite", "mission",
                "spacecraft", "orbit", "orbital", "lunar", "moon", "Mars",
                "astronaut", "cosmonaut", "taikonaut", "space agency",
                "space station", "deep space", "spaceport", "reusable rocket",
                "space telescope", "space probe", "space mission",
                # agencies worldwide
                "ISRO", "NASA", "ESA", "JAXA", "CNES", "CNSA", "KARI", "Roscosmos",
                "China National Space", "European Space", "Japanese space",
                # missions/programs
                "Chandrayaan", "Gaganyaan", "PSLV", "GSLV", "Long March",
                "Tiangong", "Tianwen", "Chang'e", "Shenzhou", "Artemis",
                "Hayabusa", "SLIM", "Ariane", "Vega rocket",
                # private space companies
                "SpaceX", "Starship", "Falcon", "Blue Origin", "Rocket Lab",
                "Sierra Space", "Firefly", "Relativity Space", "Skyroot",
                "Agnikul", "iSpace", "Landspace", "Galactic Energy",
                "private space", "commercial space", "space startup",
            ],
            "include": [],
            "exclude": ["horoscope", "astrology", "stock market", "cricket",
                        "election", "box office", "recipe", "smartphone launch",
                        "cryptocurrency", "IPO", "quarterly earnings", "Bollywood"],
        },
        "feeds": [
            "https://www.nasa.gov/feed/",
            "https://www.esa.int/rssfeed/Our_Activities/Human_and_Robotic_Exploration",
            "https://www.esa.int/rssfeed/TopNews",
            "https://www.sciencedaily.com/rss/space_time/space_exploration.xml",
        ] + BROAD,
        # Captures missions from any agency (ISRO, JAXA, CNES, CNSA, SpaceX,
        # Blue Origin) reported by NASA/ESA or the broad outlets.
        "filter": {
            "include": [
                "rocket", "launch", "spacecraft", "satellite", "mission",
                "astronaut", "cosmonaut", "taikonaut", "crew", "space station", "ISS",
                "lunar", "moon", "Mars", "orbit", "orbital", "booster",
                "lander", "rover", "propulsion", "thruster", "spaceflight",
                "reusable", "NASA", "ESA", "ISRO", "JAXA", "CNES", "CNSA",
                "SpaceX", "Blue Origin", "Rocket Lab", "Sierra Space", "Firefly",
                "Relativity Space", "Skyroot", "Agnikul", "Landspace", "iSpace",
                "Soyuz", "Artemis", "Gaganyaan", "Tiangong", "Tianwen", "Chang'e",
                "Shenzhou", "Chandrayaan", "space agency", "payload", "deep space",
                "spaceport", "docking", "reentry", "asteroid sample",
                "Long March", "Starship", "Falcon", "Hayabusa", "space telescope",
                "Gateway", "Perseverance", "Ariane", "commercial space",
                "private space", "space startup", "satellite constellation",
            ],
            "exclude": [
                "dinosaur", "heatwave", "typhoon", "capybara", "butterfly",
                "depression", "soulmate", "mushroom",
            ],
        },
    },
    "astronomy": {
        "name": "Astronomy & Astrophysics",
        "tagline": "New telescopes, satellites, and discoveries across the cosmos.",
        "accent": "#B98CE0",
        "regional_feeds": [SCIDEV, HINDU_SCI, INDIAN_EXPRESS_TECH,
                            SCMP_SCIENCE, SCIENCE_JAPAN, MAX_PLANCK, CNRS_NEWS],
        "regional_filter": {
            "require": ["galaxy", "star", "cosmic", "telescope", "astronomer",
                        "astronomy", "astrophysics", "black hole", "universe",
                        "exoplanet", "supernova", "cosmology", "observatory",
                        "planet", "nebula", "asteroid", "comet"],
            "include": [], "exclude": [],
        },
        "feeds": [
            "https://www.sciencedaily.com/rss/space_time/astronomy.xml",
            "https://www.eso.org/public/news/feed/",
            "https://skyandtelescope.org/feed/",
            "https://www.sciencedaily.com/rss/space_time/astrophysics.xml",
        ] + BROAD,
        "filter": {
            "include": [
                "galaxy", "galaxies", "star", "stars", "stellar", "quasar",
                "black hole", "supernova", "nebula", "cosmic", "cosmology",
                "universe", "exoplanet", "planet", "telescope", "astronomer",
                "astronomy", "astrophysics", "dark matter", "dark energy",
                "gravitational wave", "neutron star", "pulsar", "comet",
                "asteroid", "interstellar", "Milky Way", "eclipse", "cosmos",
                "observatory", "Webb", "Hubble", "white dwarf", "redshift",
                "planetary", "meteor", "solar flare",
            ],
            "exclude": [
                "dinosaur", "heatwave", "typhoon", "capybara",
            ],
        },
    },
}
