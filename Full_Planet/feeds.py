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

CHANNELS = {
    "ai": {
        "name": "Artificial Intelligence",
        "tagline": "AI put to work in science and engineering \u2014 new materials, proteins, medicines, and discoveries.",
        "accent": "#5AA9E6",
        "feeds": [
            "https://www.technologyreview.com/topic/artificial-intelligence/feed",
            "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml",
            "https://rss.sciencedaily.com/computers_math/artificial_intelligence.xml",
            "https://spectrum.ieee.org/topic/artificial-intelligence/feed",
            "https://www.quantamagazine.org/feed/",
        ] + BROAD,
        # Must mention AI/ML (require) AND a science/engineering topic (include),
        # AND avoid business/consumer noise (exclude).
        "filter": {
            "require": [
                "AI", "A.I.", "artificial intelligence", "machine learning",
                "neural network", "deep learning", "algorithm", "generative",
                "AlphaFold", "ChatGPT", "language model", "GPT", "large language",
                "foundation model", "machine-learning",
            ],
            "include": [
                "protein", "materials", "material", "molecule", "molecular",
                "drug", "catalyst", "chemistry", "genomics", "genome",
                "biology", "biological", "medicine", "medical", "clinical",
                "disease", "physics", "quantum", "climate", "weather", "fusion",
                "battery", "solar", "energy", "engineering", "engineer",
                "simulation", "simulate", "microscopy", "telescope", "astronomy",
                "astrophysics", "neuroscience", "brain", "crystal",
                "semiconductor", "superconductor", "robotics", "discovery",
                "research", "laboratory", "experiment", "predict", "enzyme",
                "math", "mathematics", "mathematical", "conjecture", "proof",
                "theorem", "computation", "computational", "scientists",
                "researchers", "model",
            ],
            "exclude": [
                "chatbot", "copilot", "smartphone", "gadget", "stock", "shares",
                "valuation", "funding", "raises $", "billion", "lawsuit",
                "regulation", "regulators", "copyright", "layoffs", "hiring",
                "CEO", "advertising", "social media", "deepfake", "election",
                "misinformation", "subscription", "app store", "gaming",
                "video game", "influencer", "CES", "executive order",
            ],
        },
    },
    "materials": {
        "name": "Advanced Materials",
        "tagline": "New molecules, metals, and polymers for cleaner energy, water, and air.",
        "accent": "#E8A13A",
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
        "feeds": [
            "https://www.sciencedaily.com/rss/plants_animals/biotechnology.xml",
            "https://www.sciencedaily.com/rss/plants_animals/genetically_modified.xml",
            "https://www.sciencedaily.com/rss/plants_animals/genetics.xml",
        ] + BROAD,
        "filter": {
            "include": [
                "synthetic biology", "synthetic cell", "synthetic organism",
                "synthetic life", "synthetic lifeform", "spudcell", "spud cell",
                "artificial cell", "minimal cell", "cell-like system",
                "engineered bacteria", "engineered microbe", "engineered microbes",
                "engineered cell", "engineered organism", "engineered yeast",
                "engineered microorganism", "designer microbe", "designer organism",
                "genetically engineered", "genetically modified", "genetically programmed",
                "genetic circuit", "genetic circuits", "gene circuit",
                "biological computer", "biological computing", "cellular computing",
                "DNA computing", "DNA data storage", "DNA storage",
                "DNA synthesis", "DNA writing", "genome synthesis", "genome writing",
                "programmable cell", "programmed cell", "reprogrammed bacteria",
                "biosynthesis", "microbial factory", "cell factory",
                "metabolic engineering", "biomanufacturing", "biofoundry",
                "gene editing", "CRISPR", "base editing", "prime editing",
                "synthetic microbe", "chassis organism", "xenobot",
                "living material", "living machine", "living robot", "biobot",
                "biocomputing", "biocomputer", "DNA-based", "synthetic DNA",
                "engineered plant", "engineered crop", "grow and divide",
            ],
            "exclude": [
                "cancer", "tumor", "tumour", "alzheimer", "parkinson",
                "clinical trial", "patients", "symptom", "vaccine", "antibody",
                "dinosaur", "fossil", "wildlife", "conservation", "endangered",
                "biodiversity", "obesity", "diabetes", "depression",
                "human embryo", "IVF", "fertility", "gum disease",
            ],
        },
    },
    "energywater": {
        "name": "Energy & Water",
        "tagline": "Science and technology for sustainable energy and clean, fresh water for more of humanity.",
        "accent": "#33C6D6",
        "feeds": [
            "https://www.sciencedaily.com/rss/matter_energy/energy_technology.xml",
            "https://www.sciencedaily.com/rss/matter_energy/solar_energy.xml",
            "https://www.sciencedaily.com/rss/earth_climate/renewable_energy.xml",
            "https://www.sciencedaily.com/rss/earth_climate/water.xml",
        ] + BROAD,
        "filter": {
            "include": [
                "energy", "solar", "wind", "battery", "batteries", "hydrogen",
                "fuel cell", "renewable", "grid", "power", "electricity",
                "photovoltaic", "nuclear", "fusion", "geothermal", "biofuel",
                "desalination", "water", "freshwater", "clean water",
                "wastewater", "aquifer", "filtration", "purification",
                "carbon capture", "electrolysis", "turbine", "storage",
            ],
            "exclude": [
                "dinosaur", "fossil fuel lobby", "wildlife", "cancer",
                "dementia", "election",
            ],
        },
    },
    "spaceexploration": {
        "name": "Space Exploration",
        "tagline": "New missions, spacecraft, and technologies \u2014 NASA, ESA, ISRO, JAXA, SpaceX, CNES, and more.",
        "accent": "#F0894E",
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
                "astronaut", "cosmonaut", "crew", "space station", "ISS",
                "lunar", "moon", "Mars", "orbit", "orbital", "booster",
                "lander", "rover", "propulsion", "thruster", "spaceflight",
                "reusable", "NASA", "ESA", "ISRO", "JAXA", "CNES", "CNSA",
                "SpaceX", "Blue Origin", "Soyuz", "Artemis", "Gaganyaan",
                "Chandrayaan", "space agency", "payload", "deep space",
                "spaceport", "docking", "reentry", "asteroid sample",
                "Long March", "Starship", "Hayabusa", "space telescope",
                "Gateway", "Perseverance",
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
