"""The fixed topic taxonomy for article classification (36 topics).

Each topic maps to a natural-language hypothesis label fed to the zero-shot NLI
model. `slug` is the stable key used for the Topic table and URLs; `order` sets
nav ordering; `label` is the phrase the model reasons about (tuned so related
topics stay distinguishable, e.g. Science vs Space, Business vs Economy).

Classification is multi-label, so overlapping topics (Crime/Law,
Entertainment/Film/Music, Science/Space) can co-occur on one article — each is
scored independently.
"""

# (slug, display name, order, NL label for the NLI hypothesis)
TAXONOMY = [
    # Politics & world
    ("politics",      "Politics",         0,  "politics, government and elections"),
    ("world",         "World",            1,  "international affairs and foreign relations"),
    ("military",      "Military",         2,  "the military, defense and armed conflict"),
    ("immigration",   "Immigration",      3,  "immigration and migration"),
    ("human-rights",  "Human Rights",     4,  "human rights and social justice"),
    ("religion",      "Religion",         5,  "religion and faith"),

    # Business & money
    ("business",      "Business",         6,  "business, companies, finance and corporate deals"),
    ("economy",       "Economy",          7,  "the economy, inflation, jobs and trade"),
    ("crypto",        "Crypto",           8,  "cryptocurrency and blockchain"),
    ("startups",      "Startups",         9,  "startups and venture capital"),
    ("real-estate",   "Real Estate",      10, "real estate and property"),

    # Tech
    ("technology",    "Technology",       11, "technology, software and gadgets"),
    ("ai",            "AI",               12, "artificial intelligence and machine learning"),
    ("cybersecurity", "Cybersecurity",    13, "cybersecurity, hacking and data breaches"),
    ("gaming",        "Gaming",           14, "video games and the gaming industry"),
    ("media",         "Media",            15, "media, the press and journalism"),

    # Science
    ("science",       "Science",          16, "scientific research and discovery"),
    ("space",         "Space",            17, "space, astronomy and spaceflight"),
    ("environment",   "Environment",      18, "the environment, climate and conservation"),
    ("weather",       "Weather",          19, "weather and natural disasters"),
    ("energy",        "Energy",           20, "energy, oil, gas and power"),

    # Health
    ("health",        "Health",           21, "health, medicine and disease"),
    ("mental-health", "Mental Health",    22, "mental health and wellbeing"),

    # Society & living
    ("education",     "Education",        23, "education and schools"),
    ("crime",         "Crime",            24, "crime and law enforcement"),
    ("law",           "Law",              25, "courts, trials and legal affairs"),
    ("lifestyle",     "Lifestyle",        26, "lifestyle and personal life"),
    ("travel",        "Travel",           27, "travel and tourism"),
    ("food",          "Food",             28, "food, drinks, cooking and restaurants"),
    ("fashion",       "Fashion",          29, "fashion and style"),
    ("automotive",    "Automotive",       30, "cars and the automotive industry"),

    # Culture & sport
    ("sports",        "Sports",           31, "sports and athletic competition"),
    ("entertainment", "Entertainment",    32, "entertainment, celebrities and pop culture"),
    ("film-tv",       "Film & TV",        33, "film, television and streaming"),
    ("music",         "Music",            34, "music and the music industry"),
    ("arts",          "Arts",             35, "art, museums, books and literature"),

    # Content type (orthogonal axis, multi-label): opinion/ideas pieces
    ("opinion",       "Opinion",          36, "opinion, commentary or a personal essay"),
]

HYPOTHESIS_TEMPLATE = "This news article is about {}."

# label phrase -> slug (used to map model output back to a Topic)
LABEL_TO_SLUG = {label: slug for slug, _name, _order, label in TAXONOMY}
CANDIDATE_LABELS = [label for _slug, _name, _order, label in TAXONOMY]

# Keep every topic scoring at/above this floor in ArticleTopic; the *display*
# threshold is applied at query time and can be higher than this.
STORE_FLOOR = 0.40
# Default threshold for showing a topic (chips, topic pages, filters).
DISPLAY_THRESHOLD = 0.55
