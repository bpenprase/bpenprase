"""
Feed configuration for Full Planet.

Each channel maps to a curated list of RSS/Atom feed URLs drawn from the
project bibliography. Feeds were chosen to spread coverage across the US,
Europe, China, India, and the Global South wherever public feeds exist, and
to foreground the highest-quality outlets (Scientific American, Science/AAAS,
Nature, Physics World, APS Physics, AGU Eos) alongside topical wire feeds.

To add a source: find its RSS feed URL and drop it into the right channel.
To create a new channel: add a new entry with name/tagline/accent/feeds.

A channel may also carry an optional "filter" with include/exclude keyword
lists (see the "ai" and "synbio" channels). A story is kept only if it matches
an include term and avoids every exclude term; exclude always wins.

Accent colors are per-channel and echoed by the website.

Note: phys.org feeds were intentionally removed in favor of higher-quality,
more distinctive sources. Scientific American publishes section-specific feeds,
so each channel pulls the SciAm section that best matches it.
"""

# High-quality general-science feeds reused across several channels.
# Scientific American's main global feed and the Science/AAAS news feed both
# carry a broad mix; the per-channel keyword filters (where present) keep them
# on-topic, and channels without a filter simply get their most relevant
# section feed instead of the firehose.
SCIAM_GLOBAL = "https://rss.sciam.com/ScientificAmerican-Global"
SCIENCE_NEWS = "https://www.science.org/rss/news_current.xml"

CHANNELS = {
    "ai": {
        "name": "Artificial Intelligence",
        "tagline": "AI put to work in science and engineering \u2014 new materials, proteins, medicines, and discoveries.",
        "accent": "#5AA9E6",   # luminous blue
        "feeds": [
            "https://www.technologyreview.com/topic/artificial-intelligence/feed",
            "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml",
            "https://spectrum.ieee.org/topic/artificial-intelligence/feed",
            "https://www.quantamagazine.org/feed/",
            "https://www.nature.com/subjects/machine-learning.rss",
            SCIAM_GLOBAL,
            SCIENCE_NEWS,
        ],
        # This channel is specifically AI FOR SCIENCE & ENGINEERING, not
        # general AI industry/policy/product news. Keep a story only if it
        # connects machine intelligence to research or engineering, and drop
        # the chatbot / gadget / business / regulation coverage.
        "filter": {
            "include": [
                "AI", "artificial intelligence", "machine learning",
                "neural network", "deep learning", "algorithm", "model",
                "protein", "materials", "material", "molecule", "molecular",
                "drug discovery", "drug design", "catalyst", "chemistry",
                "genomics", "genome", "biology", "biological", "medicine",
                "medical", "clinical", "diagnosis", "disease", "cancer",
                "physics", "quantum", "climate", "weather", "fusion",
                "battery", "solar", "energy", "engineering", "engineer",
                "simulation", "simulate", "microscopy", "telescope",
                "astronomy", "astrophysics", "neuroscience", "brain",
                "crystal", "semiconductor", "superconductor", "chip design", "robotics",
                "scientific discovery", "research", "laboratory", "experiment",
                "prediction", "predict", "AlphaFold", "enzyme",
                "math", "mathematics", "mathematical", "conjecture", "proof",
                "theorem", "computation", "computational",
            ],
            # For this channel a story must ALSO mention AI/ML to qualify; the
            # builder enforces that via require_all below. Exclude strips the
            # business / consumer / policy coverage.
            "require": ["AI", "artificial intelligence", "machine learning",
                        "neural network", "deep learning", "algorithm",
                        "A.I.", "generative", "AlphaFold", "ChatGPT",
                        "language model", "GPT", "large language"],
            "exclude": [
                "chatbot", "chatbots", "copilot", "smartphone", "gadget",
                "stock", "shares", "valuation", "startup funding", "raises $",
                "lawsuit", "regulation", "regulators", "copyright",
                "layoffs", "hiring", "CEO", "advertising", "social media",
                "deepfake", "election", "misinformation", "subscription",
                "app store", "gaming", "video game", "influencer", "CES 2026",
            ],
        },
    },
    "materials": {
        "name": "Advanced Materials",
        "tagline": "New molecules, metals, and polymers for cleaner energy, water, and air.",
        "accent": "#E8A13A",   # warm amber
        "feeds": [
            "https://www.sciencedaily.com/rss/matter_energy/materials_science.xml",
            "https://www.sciencedaily.com/rss/matter_energy/nanotechnology.xml",
            "https://www.nature.com/subjects/materials-science.rss",
            "https://www.sciencedaily.com/rss/matter_energy/chemistry.xml",
            "https://physicsworld.com/c/materials/feed/",
        ],
    },
    "synbio": {
        "name": "Synthetic Biology",
        "tagline": "Engineered organisms and programmed DNA \u2014 cells built for computing, data storage, and chemical synthesis.",
        "accent": "#5FBF9B",   # living green
        "feeds": [
            "https://www.sciencedaily.com/rss/plants_animals/biotechnology.xml",
            "https://www.sciencedaily.com/rss/plants_animals/genetically_modified.xml",
            "https://www.sciencedaily.com/rss/plants_animals/genetic_engineering.xml",
            "https://www.nature.com/subjects/synthetic-biology.rss",
            "https://press.asimov.com/feed",
            SCIAM_GLOBAL,
        ],
        "filter": {
            "include": [
                "synthetic biology", "synthetic cell", "synthetic organism",
                "synthetic life", "synthetic lifeform", "spudcell", "spud cell",
                "artificial life", "created life",
                "synthetic genome", "artificial cell", "minimal cell",
                "engineered bacteria", "engineered microbe", "engineered microbes",
                "engineered cell", "engineered organism", "engineered yeast",
                "engineered microorganism", "designer microbe", "designer organism",
                "genetically engineered", "genetically modified", "genetically programmed",
                "genetic circuit", "genetic circuits", "gene circuit",
                "biological computer", "biological computing", "cellular computing",
                "DNA computing", "DNA data storage", "DNA storage",
                "DNA synthesis", "genome synthesis", "genome writing",
                "programmable cell", "programmed cell", "reprogrammed bacteria",
                "biosynthesis", "bio-based production", "microbial factory",
                "cell factory", "metabolic engineering", "biomanufacturing",
                "biofoundry", "gene editing", "CRISPR", "base editing", "prime editing",
                "synthetic microbe", "chassis organism", "xenobot", "living material",
                "living machine", "living robot", "biological robot", "biobot",
                "biocomputing", "biocomputer", "DNA-based", "DNA logic",
                "cell-free", "synthetic DNA", "artificial DNA", "orthogonal",
                "engineered plant", "engineered crop",
            ],
            "exclude": [
                "cancer", "tumor", "tumour", "alzheimer", "parkinson",
                "clinical trial", "patients", "patient ", "symptom",
                "diagnosis", "diagnostic", "vaccine", "antibody", "antibodies",
                "dinosaur", "fossil", "evolutionary history", "wildlife",
                "conservation", "endangered", "biodiversity", "ecosystem",
                "obesity", "diabetes", "depression", "mental health",
                "human embryo", "IVF", "fertility",
            ],
        },
    },
    "energywater": {
        "name": "Energy & Water",
        "tagline": "Science and technology for sustainable energy and clean, fresh water for more of humanity.",
        "accent": "#33C6D6",   # bright cyan-teal
        "feeds": [
            "https://www.sciencedaily.com/rss/matter_energy/energy_technology.xml",
            "https://www.sciencedaily.com/rss/matter_energy/solar_energy.xml",
            "https://www.sciencedaily.com/rss/earth_climate/renewable_energy.xml",
            "https://www.sciencedaily.com/rss/earth_climate/water.xml",
            "https://www.nature.com/subjects/energy.rss",
            "https://eos.org/feed",
        ],
    },
    "spaceexploration": {
        "name": "Space Exploration",
        "tagline": "New missions, spacecraft, and technologies for reaching and developing the space environment.",
        "accent": "#F0894E",   # coral / rocket orange
        "feeds": [
            "https://www.nasa.gov/feed/",
            "https://www.esa.int/rssfeed/Our_Activities/Human_and_Robotic_Exploration",
            "https://www.sciencedaily.com/rss/space_time/space_exploration.xml",
            "https://spectrum.ieee.org/topic/aerospace/feed",
            SCIAM_GLOBAL,
        ],
        # SciAm's Global feed is broad, and this channel shares the topic of
        # "space" with the astronomy channel. Keep the hardware/mission stories
        # here (rockets, spacecraft, crews, launches) and let telescope /
        # discovery stories flow to Astronomy instead.
        "filter": {
            "include": [
                "rocket", "launch", "spacecraft", "satellite", "mission",
                "astronaut", "crew", "space station", "ISS", "lunar", "moon",
                "Mars", "orbit", "orbital", "booster", "lander", "rover",
                "propulsion", "thruster", "spaceflight", "reusable",
                "NASA", "ESA", "SpaceX", "space agency", "payload",
                "space telescope", "deep space", "human spaceflight",
                "cargo", "docking", "reentry", "spaceport", "constellation",
            ],
            "exclude": [
                "cyclosporiasis", "allergy", "creatine", "sleep", "diet",
                "shark", "seal", "mice", "cats", "tick", "diarrhea",
            ],
        },
    },
    "astronomy": {
        "name": "Astronomy & Astrophysics",
        "tagline": "New telescopes, satellites, and discoveries across the cosmos.",
        "accent": "#B98CE0",   # nebula violet
        "feeds": [
            "https://www.sciencedaily.com/rss/space_time/astronomy.xml",
            "https://www.eso.org/public/news/feed/",
            "https://skyandtelescope.org/feed/",
            "https://www.sciencedaily.com/rss/space_time/astrophysics.xml",
            "https://www.nature.com/subjects/astronomy-and-planetary-science.rss",
            SCIAM_GLOBAL,
        ],
        # Keep the astronomy/astrophysics discovery stories; the SciAm Global
        # feed is broad, so require a cosmos-related term.
        "filter": {
            "include": [
                "galaxy", "galaxies", "star", "stars", "stellar", "quasar",
                "black hole", "supernova", "nebula", "cosmic", "cosmology",
                "universe", "exoplanet", "planet", "telescope", "astronomer",
                "astronomy", "astrophysics", "dark matter", "dark energy",
                "gravitational wave", "neutron star", "pulsar", "comet",
                "asteroid", "interstellar", "Milky Way", "eclipse", "cosmos",
                "observatory", "Webb", "Hubble", "redshift", "spectra",
            ],
            "exclude": [],
        },
    },
}
