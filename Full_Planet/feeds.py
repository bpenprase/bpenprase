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
DOWN_TO_EARTH = "https://www.downtoearth.org.in/rss/all"

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
TIMES_OF_ISRAEL = "https://www.timesofisrael.com/feed/"          # independent
AL_FANAR = "https://al-fanarmedia.org/feed/"                     # independent nonprofit, Arab HE/science

# --- Continental Europe (English) ---
DW_SCIENCE = "https://rss.dw.com/xml/rss_en_science"             # German public broadcaster
DW_ENVIRONMENT = "https://rss.dw.com/xml/rss_en_environment"     # German public broadcaster
MAX_PLANCK = "https://www.mpg.de/en/research.rss"                # independent research org
CERN_NEWS = "https://home.cern/api/news/news/feed.rss"           # intergovernmental physics lab
CNRS_NEWS = "https://news.cnrs.fr/rss"                           # French public research agency

# Region groupings for convenient reuse.
ASIA_GENERAL = [SCMP_SCIENCE, SCMP_CHINA_TECH, XINHUA_SCITECH, TECHNODE,
                SCIENCE_JAPAN, KOREA_HERALD_BIZ, ASIAN_SCIENTIST]
GLOBAL_SOUTH = [SCIDEV, HINDU_SCI, INDIAN_EXPRESS_TECH, CONVERSATION_AFRICA,
                RAPPLER_SCIENCE, CONVERSATION_ID, TIMES_OF_ISRAEL, AL_FANAR]
EUROPE = [DW_SCIENCE, MAX_PLANCK, CERN_NEWS, CNRS_NEWS]

# Default broad regional set: a balanced world mix used by most channels.
REGIONAL = (
    [SCIDEV, HINDU_SCI, INDIAN_EXPRESS_TECH, CONVERSATION_AFRICA]   # India / Africa / Global South
    + [SCMP_SCIENCE, SCMP_CHINA_TECH, XINHUA_SCITECH]               # China (indep + state)
    + [SCIENCE_JAPAN, KOREA_HERALD_BIZ, ASIAN_SCIENTIST]           # East & SE Asia
    + [TIMES_OF_ISRAEL, AL_FANAR]                                   # Middle East
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
            "include": [],  # require + exclude is enough; keep all AI that isn't noise
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
        },
    },
    "materials": {
        "name": "Advanced Materials",
        "tagline": "New molecules, metals, and polymers for cleaner energy, water, and air.",
        "accent": "#E8A13A",
        "regional_feeds": REGIONAL + [CERN_NEWS, CNRS_NEWS],
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
        "regional_feeds": REGIONAL + [ASIAN_SCIENTIST],
        "regional_filter": {
            # Looser than the primary: global outlets frame synthetic biology
            # as "biotech / gene editing / GMO / engineered microbes." Require
            # any such signal; that's enough to stay on-topic without demanding
            # the exact primary vocabulary.
            "require": [
                "synthetic biology", "synthetic cell", "engineered", "engineer",
                "genetically modified", "genetically engineered", "gmo",
                "gene-edited", "gene edited", "gene editing", "CRISPR",
                "genome editing", "bioengineer", "biotech", "biotechnology",
                "gene therapy", "gene drive", "microbe", "bacteria engineered",
                "designer organism", "biomanufactur", "metabolic engineering",
                "fermentation", "cultured", "lab-grown", "DNA storage",
                "living material", "biofuel", "bioremediation",
            ],
            "include": [],
            "exclude": ["dinosaur", "fossil", "wildlife", "conservation"],
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
        # Synthetic biology = human-designed/engineered life and programmed DNA.
        # The require gate demands an engineering/synthetic signal so the broad
        # bacteria/microbiology/cell-biology feeds don't flood the channel with
        # basic biology. The include list then also catches the APPLICATIONS you
        # care about (carbon capture, bioremediation, chemical synthesis) when
        # paired with that engineering signal.
        "filter": {
            "require": [
                # any of these signals that a story is about *engineered* life
                "synthetic biology", "synthetic cell", "synthetic organism",
                "synthetic life", "synthetic genome", "synthetic microbe",
                "synthetic bacteria", "synthetic yeast", "synthetic cells",
                "synthetic dna", "spudcell", "spud cell", "artificial cell",
                "artificial chromosome", "minimal cell", "create life",
                "created life", "creating life",
                "engineered", "engineer", "engineering",
                "genetically modified", "genetically engineered", "gmo",
                "gene-edited", "gene edited", "gene editing", "gene-editing",
                "genome editing", "genome-edited", "genome synthesis",
                "genome writing", "CRISPR", "base editing", "prime editing",
                "gene drive", "genetic circuit", "gene circuit",
                "bioengineer", "bioengineered", "bioengineering",
                "metabolic engineering", "biomanufactur", "biofoundry",
                "biosynthesis", "designer microbe", "designer organism",
                "programmable cell", "programmed cell", "programmed microbe",
                "program microbes", "reprogrammed", "reprogram",
                "biological computer", "biological computing", "biocomputing",
                "DNA computing", "DNA data storage", "DNA storage",
                "data in DNA", "data into DNA", "store data", "stores data",
                "digital data in", "DNA synthesis", "DNA writing", "living material",
                "living machine", "living robot", "xenobot", "biobot",
                "microbial factory", "cell factory", "chassis organism",
                "modified bacteria", "modified microbe", "modified yeast",
                "modified organism", "phage engineering", "cell-free system",
            ],
            "include": [
                # applications & contexts (only kept if a require term is also
                # present). Empty entries here would keep everything that passes
                # require; instead we list application terms so mixed feeds stay
                # on-topic. Leave broad so "engineered X to do Y" is captured.
                "microbe", "microbes", "bacteria", "bacterium", "yeast", "cell",
                "cells", "organism", "enzyme", "protein", "DNA", "genome",
                "gene", "genes", "microorganism", "algae", "plant", "crop",
                "virus", "phage", "chromosome", "biology", "biological",
                "carbon", "CO2", "carbon dioxide", "sequester", "capture",
                "bioremediation", "clean up", "cleanup", "pollution", "pollutant",
                "waste", "toxin", "environment", "biofuel", "fuel", "chemical",
                "synthesize", "synthesis", "produce", "production", "manufacture",
                "material", "compound", "drug", "medicine", "fertilizer",
                "nitrogen", "plastic", "degrade", "recycling", "data", "computing",
                "storage", "circuit", "sensor", "biosensor", "vaccine",
            ],
            "exclude": [
                "dinosaur", "fossil", "wildlife", "conservation", "endangered",
                "biodiversity", "human embryo", "IVF", "fertility clinic",
            ],
        },
    },
    "energywater": {
        "name": "Energy & Water",
        "tagline": "New ways to generate clean energy, capture carbon, and bring fresh water and power to people, cities, and transport.",
        "accent": "#33C6D6",
        "regional_feeds": REGIONAL + [DOWN_TO_EARTH, DW_ENVIRONMENT, RAPPLER_ENV, CNRS_NEWS],
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
            ],
            "include": [],  # require gate is specific enough; keep all that pass
            "exclude": [
                "dinosaur", "fossil discovery", "wildlife", "extinction",
                "endangered", "species", "coral", "shark", "whale", "insect",
                "butterfly", "bird", "heatwave", "hurricane", "typhoon",
                "wildfire smoke", "cancer", "dementia", "vaccine", "election",
                "lawsuit", "stock market", "El Ni", "sea level rise",
                "solar flare", "solar wind", "solar system", "solar eclipse",
                "coronal mass", "sunspot", "solar storm", "solar panel installer",
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
