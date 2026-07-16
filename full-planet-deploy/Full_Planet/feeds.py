"""
Feed configuration for Full Planet.

Each channel maps to a curated list of RSS/Atom feed URLs drawn from the
project bibliography. Feeds were chosen to spread coverage across the US,
Europe, China, India, and the Global South wherever public feeds exist.

To add a source: find its RSS feed URL and drop it into the right channel.
To create a new channel: add a new entry with name/tagline/accent/feeds.

Accent colors are per-channel and echoed by the website.
"""

CHANNELS = {
    "ai": {
        "name": "Artificial Intelligence",
        "tagline": "Machine intelligence turned toward medicine, materials, energy, and discovery.",
        "accent": "#5AA9E6",   # luminous blue
        "feeds": [
            "https://www.technologyreview.com/topic/artificial-intelligence/feed",
            "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml",
            "https://phys.org/rss-feed/technology-news/machine-learning-ai/",
            "https://spectrum.ieee.org/topic/artificial-intelligence/feed",
            "https://www.quantamagazine.org/feed/",
            "https://restofworld.org/feed/latest/",
        ],
    },
    "materials": {
        "name": "Advanced Materials",
        "tagline": "New molecules, metals, and polymers for cleaner energy, water, and air.",
        "accent": "#E8A13A",   # warm amber
        "feeds": [
            "https://www.sciencedaily.com/rss/matter_energy/materials_science.xml",
            "https://phys.org/rss-feed/chemistry-news/materials-science/",
            "https://www.sciencedaily.com/rss/matter_energy/nanotechnology.xml",
            "https://phys.org/rss-feed/nanotech-news/",
        ],
    },
    "synbio": {
        "name": "Synthetic Biology",
        "tagline": "Engineered organisms and programmed DNA \u2014 cells built for computing, data storage, and chemical synthesis.",
        "accent": "#5FBF9B",   # living green
        "feeds": [
            "https://www.sciencedaily.com/rss/plants_animals/biotechnology.xml",
            "https://phys.org/rss-feed/biology-news/biotechnology/",
            "https://www.sciencedaily.com/rss/plants_animals/genetically_modified.xml",
            "https://www.sciencedaily.com/rss/plants_animals/genetic_engineering.xml",
            "https://phys.org/rss-feed/biology-news/molecular-biology/",
            "https://press.asimov.com/feed",
        ],
        # Biology is enormous. This channel is specifically SYNTHETIC BIOLOGY:
        # human-designed organisms and directly programmed cells and DNA.
        # An item is kept only if it matches an "include" term AND avoids the
        # "exclude" terms (which strip out ordinary medical-genetics and
        # disease-biology stories that these broad feeds also carry).
        "filter": {
            "include": [
                "synthetic biology", "synthetic cell", "synthetic organism",
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
            "https://phys.org/rss-feed/technology-news/energy-green-tech/",
            "https://www.sciencedaily.com/rss/earth_climate/water.xml",
            "https://phys.org/rss-feed/earth-news/environment/",
        ],
    },
    "spaceexploration": {
        "name": "Space Exploration",
        "tagline": "New missions, spacecraft, and technologies for reaching and developing the space environment.",
        "accent": "#F0894E",   # coral / rocket orange
        "feeds": [
            "https://www.nasa.gov/feed/",
            "https://www.esa.int/rssfeed/Our_Activities/Human_and_Robotic_Exploration",
            "https://phys.org/rss-feed/space-news/space-exploration/",
            "https://www.sciencedaily.com/rss/space_time/space_exploration.xml",
            "https://spectrum.ieee.org/topic/aerospace/feed",
        ],
    },
    "astronomy": {
        "name": "Astronomy & Astrophysics",
        "tagline": "New telescopes, satellites, and discoveries across the cosmos.",
        "accent": "#B98CE0",   # nebula violet
        "feeds": [
            "https://www.sciencedaily.com/rss/space_time/astronomy.xml",
            "https://phys.org/rss-feed/space-news/astronomy/",
            "https://www.eso.org/public/news/feed/",
            "https://skyandtelescope.org/feed/",
            "https://www.sciencedaily.com/rss/space_time/astrophysics.xml",
            "https://phys.org/rss-feed/space-news/astronomy/cosmology/",
        ],
    },
}
