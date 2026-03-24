import json

from django.core.management.base import BaseCommand

from apps.feeds.feeds import DEFAULT_CATEGORIES, DEFAULT_FEEDS
from apps.feeds.models import Category, Feed
from apps.digest.models import DigestTopic, TopicEmbedding
from apps.core.services.ai import EmbeddingClient, EmbeddingError
from apps.core.services.ai.client import OpenAIClient, OpenAIError, fix_truncated_json


BIAS_SYSTEM_PROMPT = """\
You are a media bias analyst. Given a list of RSS feed sources (title, URL, category), \
classify each one by editorial lean and factuality.

Rules:
- Only classify news/media/politics feeds. For tech, dev, science, gaming, or other \
non-political feeds, return {"lean": "", "factuality": ""}.
- lean must be one of: "left", "center_left", "center", "center_right", "right", or "" (non-political).
- factuality must be one of: "high", "mixed", "low", or "" (non-political).
- Base your assessment on the publication's well-known editorial positioning.

Return a JSON object mapping feed title to {"lean": "...", "factuality": "..."} for every feed.\
"""

DEFAULT_TOPICS = [
    {
        "name_en": "AI \u2022 Technology",
        "name_ru": "AI \u2022 \u0422\u0435\u0445\u043d\u043e\u043b\u043e\u0433\u0438\u0438",
        "name_uk": "AI \u2022 \u0422\u0435\u0445\u043d\u043e\u043b\u043e\u0433\u0456\u0457",
        "queries": [
            "artificial intelligence, machine learning, deep learning, neural networks, "
            "large language models, GPT, Claude, AI research breakthroughs",
            "technology companies, tech startups, product launches, software platforms, "
            "digital services, mobile apps, Silicon Valley",
            "semiconductors, computer chips, hardware innovation, cloud computing, "
            "robotics, autonomous systems, tech industry trends",
        ],
    },
    {
        "name_en": "World Politics",
        "name_ru": "\u041c\u0438\u0440\u043e\u0432\u0430\u044f \u043f\u043e\u043b\u0438\u0442\u0438\u043a\u0430",
        "name_uk": "\u0421\u0432\u0456\u0442\u043e\u0432\u0430 \u043f\u043e\u043b\u0456\u0442\u0438\u043a\u0430",
        "queries": [
            "international relations, diplomacy, foreign policy, geopolitics, "
            "summits, treaties, international agreements",
            "elections, political leaders, government policy, political parties, "
            "democratic processes, regime changes, political crisis",
            "United Nations, NATO, European Union politics, G7, G20, "
            "international organizations, sanctions, global governance",
        ],
    },
    {
        "name_en": "Business \u2022 Economy",
        "name_ru": "\u0411\u0438\u0437\u043d\u0435\u0441 \u2022 \u042d\u043a\u043e\u043d\u043e\u043c\u0438\u043a\u0430",
        "name_uk": "\u0411\u0456\u0437\u043d\u0435\u0441 \u2022 \u0415\u043a\u043e\u043d\u043e\u043c\u0456\u043a\u0430",
        "queries": [
            "stock market, financial markets, economic indicators, GDP growth, "
            "inflation rates, interest rates, central bank policy",
            "corporate news, mergers and acquisitions, company earnings reports, "
            "business strategy, CEO changes, corporate governance",
            "global trade, supply chains, economic sanctions, tariffs, "
            "international commerce, currency markets, investment trends",
        ],
    },
    {
        "name_en": "Crypto \u2022 Fintech",
        "name_ru": "\u041a\u0440\u0438\u043f\u0442\u043e \u2022 \u0424\u0438\u043d\u0442\u0435\u0445",
        "name_uk": "\u041a\u0440\u0438\u043f\u0442\u043e \u2022 \u0424\u0456\u043d\u0442\u0435\u0445",
        "queries": [
            "cryptocurrency, Bitcoin, Ethereum, altcoins, token launches, "
            "crypto market, blockchain technology, DeFi, decentralized finance",
            "fintech startups, digital payments, neobanks, mobile banking, "
            "payment systems, digital wallets, financial technology innovation",
            "crypto regulation, SEC enforcement, stablecoins, NFTs, Web3, "
            "crypto exchanges, mining, staking, institutional crypto adoption",
        ],
    },
    {
        "name_en": "War \u2022 Conflicts",
        "name_ru": "\u0412\u043e\u0439\u043d\u0430 \u2022 \u041a\u043e\u043d\u0444\u043b\u0438\u043a\u0442\u044b",
        "name_uk": "\u0412\u0456\u0439\u043d\u0430 \u2022 \u041a\u043e\u043d\u0444\u043b\u0456\u043a\u0442\u0438",
        "queries": [
            "armed conflicts, military operations, war zones, battles, "
            "territorial disputes, ceasefire negotiations, peace talks",
            "Ukraine war, Russia military, NATO defense, weapons supplies, "
            "frontline updates, drone warfare, military aid",
            "Middle East conflicts, Gaza, Israel, terrorism, insurgency, "
            "humanitarian crisis, refugees, war casualties",
        ],
    },
    {
        "name_en": "Disasters \u2022 Emergencies",
        "name_ru": "\u041a\u0430\u0442\u0430\u0441\u0442\u0440\u043e\u0444\u044b \u2022 \u0427\u041f",
        "name_uk": "\u041a\u0430\u0442\u0430\u0441\u0442\u0440\u043e\u0444\u0456 \u2022 \u041d\u0421",
        "queries": [
            "natural disasters, earthquakes, tsunamis, volcanic eruptions, "
            "hurricanes, typhoons, floods, landslides, wildfires",
            "plane crashes, train derailments, ship sinkings, industrial accidents, "
            "explosions, building collapses, mine disasters, mass casualties",
            "emergency response, rescue operations, humanitarian aid, evacuation, "
            "death toll, disaster relief, FEMA, Red Cross, infrastructure damage",
        ],
    },
    {
        "name_en": "Science",
        "name_ru": "\u041d\u0430\u0443\u043a\u0430",
        "name_uk": "\u041d\u0430\u0443\u043a\u0430",
        "queries": [
            "scientific discoveries, research breakthroughs, physics, "
            "biology, chemistry, mathematics, academic publications",
            "space exploration, NASA, ESA, SpaceX, satellites, "
            "astronomy, cosmology, Mars missions, space station",
            "quantum computing, particle physics, CERN, climate science, "
            "paleontology, archaeology, ocean exploration, Nobel Prize",
        ],
    },
    {
        "name_en": "Health \u2022 Medicine",
        "name_ru": "\u0417\u0434\u043e\u0440\u043e\u0432\u044c\u0435 \u2022 \u041c\u0435\u0434\u0438\u0446\u0438\u043d\u0430",
        "name_uk": "\u0417\u0434\u043e\u0440\u043e\u0432'\u044f \u2022 \u041c\u0435\u0434\u0438\u0446\u0438\u043d\u0430",
        "queries": [
            "public health, disease outbreaks, epidemics, pandemics, "
            "vaccines, WHO reports, healthcare systems, health policy",
            "pharmaceutical industry, drug development, clinical trials, "
            "FDA approvals, biotechnology, gene therapy, medical devices",
            "mental health, cancer research, chronic diseases, nutrition, "
            "medical breakthroughs, hospital systems, health insurance",
        ],
    },
    {
        "name_en": "Crime \u2022 Justice",
        "name_ru": "\u041a\u0440\u0438\u043c\u0438\u043d\u0430\u043b \u2022 \u041f\u0440\u0430\u0432\u043e\u0441\u0443\u0434\u0438\u0435",
        "name_uk": "\u041a\u0440\u0438\u043c\u0456\u043d\u0430\u043b \u2022 \u041f\u0440\u0430\u0432\u043e\u0441\u0443\u0434\u0434\u044f",
        "queries": [
            "criminal cases, law enforcement, police operations, arrests, "
            "investigations, organized crime, drug trafficking",
            "court rulings, legal proceedings, trials, verdicts, "
            "supreme court decisions, judicial reforms, extradition",
            "fraud, corruption scandals, money laundering, "
            "human rights violations, war crimes prosecution, Interpol",
        ],
    },
    {
        "name_en": "Cybersecurity \u2022 Privacy",
        "name_ru": "\u041a\u0438\u0431\u0435\u0440\u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c \u2022 \u041f\u0440\u0438\u0432\u0430\u0442\u043d\u043e\u0441\u0442\u044c",
        "name_uk": "\u041a\u0456\u0431\u0435\u0440\u0431\u0435\u0437\u043f\u0435\u043a\u0430 \u2022 \u041f\u0440\u0438\u0432\u0430\u0442\u043d\u0456\u0441\u0442\u044c",
        "queries": [
            "cyber attacks, data breaches, hacking incidents, ransomware, "
            "malware, cyber threats, vulnerability disclosures",
            "digital privacy, surveillance, data protection laws, GDPR, "
            "online tracking, social media privacy, encryption policy",
            "information security, zero-day exploits, state-sponsored hacking, "
            "cyber warfare, critical infrastructure attacks, identity theft",
        ],
    },
    {
        "name_en": "Energy \u2022 Climate",
        "name_ru": "\u042d\u043d\u0435\u0440\u0433\u0435\u0442\u0438\u043a\u0430 \u2022 \u041a\u043b\u0438\u043c\u0430\u0442",
        "name_uk": "\u0415\u043d\u0435\u0440\u0433\u0435\u0442\u0438\u043a\u0430 \u2022 \u041a\u043b\u0456\u043c\u0430\u0442",
        "queries": [
            "climate change, global warming, carbon emissions, greenhouse gases, "
            "climate policy, Paris agreement, environmental regulations",
            "renewable energy, solar power, wind energy, electric vehicles, "
            "green technology, clean energy transition, battery storage",
            "oil and gas industry, energy prices, OPEC decisions, nuclear energy, "
            "energy security, power grid, fossil fuels",
        ],
    },
    {
        "name_en": "Sports",
        "name_ru": "\u0421\u043f\u043e\u0440\u0442",
        "name_uk": "\u0421\u043f\u043e\u0440\u0442",
        "queries": [
            "professional sports, football soccer, basketball, tennis, "
            "Formula 1, Olympics, championships, tournament results",
            "transfer news, player contracts, coaching changes, team standings, "
            "league tables, match highlights, sports injuries",
            "UFC, MMA, boxing, athletics, swimming, cycling, cricket, "
            "rugby, golf, esports, sports scandals, doping",
        ],
    },
    {
        "name_en": "Entertainment \u2022 Culture",
        "name_ru": "\u0420\u0430\u0437\u0432\u043b\u0435\u0447\u0435\u043d\u0438\u044f \u2022 \u041a\u0443\u043b\u044c\u0442\u0443\u0440\u0430",
        "name_uk": "\u0420\u043e\u0437\u0432\u0430\u0433\u0438 \u2022 \u041a\u0443\u043b\u044c\u0442\u0443\u0440\u0430",
        "queries": [
            "movies, box office, film festivals, Oscars, TV series, "
            "streaming platforms, Netflix, Disney, celebrity news",
            "music releases, concerts, tours, Grammy awards, albums, "
            "artists, gaming industry, video games, game releases",
            "art exhibitions, theatre, books, literature, cultural events, "
            "festivals, fashion, social media trends, viral content",
        ],
    },
    {
        "name_en": "Dev \u2022 Open Source",
        "name_ru": "\u0420\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u2022 Open Source",
        "name_uk": "\u0420\u043e\u0437\u0440\u043e\u0431\u043a\u0430 \u2022 Open Source",
        "queries": [
            "software development, programming languages, frameworks, libraries, "
            "developer tools, code editors, IDEs, debugging, testing",
            "open source projects, GitHub, Linux kernel, Apache, Mozilla, "
            "open source community, free software, licensing, contributions",
            "DevOps, CI/CD, cloud infrastructure, containers, Kubernetes, Docker, "
            "microservices, APIs, web development, backend, frontend",
        ],
    },
    {
        "name_en": "Society \u2022 Migration",
        "name_ru": "\u041e\u0431\u0449\u0435\u0441\u0442\u0432\u043e \u2022 \u041c\u0438\u0433\u0440\u0430\u0446\u0438\u044f",
        "name_uk": "\u0421\u0443\u0441\u043f\u0456\u043b\u044c\u0441\u0442\u0432\u043e \u2022 \u041c\u0456\u0433\u0440\u0430\u0446\u0456\u044f",
        "queries": [
            "social issues, inequality, protests, social movements, "
            "human rights, civil rights, discrimination, social justice",
            "immigration, migration policy, refugees, asylum seekers, "
            "border control, deportation, integration, diaspora",
            "education policy, demographics, religion, public opinion, "
            "welfare systems, poverty, homelessness, community development",
        ],
    },
]


class Command(BaseCommand):
    help = "Load default categories, RSS feeds, and digest topics"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-topics",
            action="store_true",
            help="Delete existing topics and recreate from DEFAULT_TOPICS",
        )

    def handle(self, *args, **options):
        self._seed_categories()
        self._seed_feeds()
        self._seed_topics(reset=options["reset_topics"])
        self._classify_feeds()

    def _seed_categories(self):
        cat_created = 0
        self._cat_map = {}
        for entry in DEFAULT_CATEGORIES:
            cat, is_new = Category.objects.get_or_create(
                slug=entry["slug"],
                defaults={"name": entry["name"], "order": entry["order"]},
            )
            self._cat_map[entry["slug"]] = cat
            if is_new:
                cat_created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Categories: {cat_created} new ({len(DEFAULT_CATEGORIES)} total)"
        ))

    def _seed_feeds(self):
        feed_created = 0
        for entry in DEFAULT_FEEDS:
            category = self._cat_map.get(entry["category"])
            _, is_new = Feed.objects.get_or_create(
                url=entry["url"],
                defaults={
                    "title": entry["title"],
                    "category": category,
                },
            )
            if is_new:
                feed_created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Feeds: {feed_created} new ({len(DEFAULT_FEEDS)} total)"
        ))

    def _seed_topics(self, reset=False):
        if reset:
            deleted, _ = DigestTopic.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Topics: deleted {deleted} objects"))
        elif DigestTopic.objects.exists():
            self.stdout.write(f"Topics: {DigestTopic.objects.count()} already exist, skipping (use --reset-topics)")
            return

        # Create topics with their search query embeddings
        for i, entry in enumerate(DEFAULT_TOPICS):
            topic = DigestTopic.objects.create(
                name_en=entry["name_en"],
                name_ru=entry["name_ru"],
                name_uk=entry["name_uk"],
                order=i,
            )
            for query in entry["queries"]:
                TopicEmbedding.objects.create(
                    topic=topic,
                    description=query,
                )

        self.stdout.write(self.style.SUCCESS(
            f"Topics: {len(DEFAULT_TOPICS)} created"
        ))

        # Generate embeddings
        try:
            client = EmbeddingClient()
        except EmbeddingError as e:
            self.stdout.write(self.style.WARNING(
                f"Skipping embeddings (no API key): {e}"
            ))
            return

        pending = list(TopicEmbedding.objects.filter(embedding__isnull=True))
        descriptions = [e.description for e in pending]
        vectors, total_tokens = client.embed_batch(descriptions)

        for emb_obj, vector in zip(pending, vectors):
            emb_obj.embedding = vector
            emb_obj.save(update_fields=["embedding"])

        self.stdout.write(self.style.SUCCESS(
            f"Embeddings: {len(vectors)} generated ({total_tokens} tokens)"
        ))

    def _classify_feeds(self):
        feeds = list(
            Feed.objects.filter(enabled=True, lean="", factuality="")
            .select_related("category")
        )
        if not feeds:
            self.stdout.write("Feed bias: all feeds already classified")
            return

        feed_lines = []
        for f in feeds:
            cat = f.category.name if f.category else "Uncategorized"
            feed_lines.append(f"- {f.title} | {f.url} | Category: {cat}")

        user_prompt = (
            f"Classify these {len(feed_lines)} feeds:\n\n"
            + "\n".join(feed_lines)
        )

        self.stdout.write(f"Feed bias: classifying {len(feeds)} feeds via LLM...")

        try:
            client = OpenAIClient()
            content, usage = client.chat(
                system=BIAS_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=4000,
                temperature=0.1,
            )
        except OpenAIError as e:
            self.stdout.write(self.style.WARNING(f"Feed bias: LLM error — {e}"))
            return

        content = fix_truncated_json(content)
        try:
            classifications = json.loads(content)
        except json.JSONDecodeError as e:
            self.stdout.write(self.style.WARNING(f"Feed bias: bad JSON — {e}"))
            return

        lean_choices = {c.value for c in Feed.Lean}
        fact_choices = {c.value for c in Feed.Factuality}

        to_update = []
        for feed in feeds:
            data = classifications.get(feed.title, {})
            lean = data.get("lean", "")
            factuality = data.get("factuality", "")

            if lean not in lean_choices:
                lean = ""
            if factuality not in fact_choices:
                factuality = ""

            if lean != feed.lean or factuality != feed.factuality:
                feed.lean = lean
                feed.factuality = factuality
                to_update.append(feed)

        if to_update:
            Feed.objects.bulk_update(to_update, fields=["lean", "factuality"])

        tokens = usage.get("total_tokens", 0)
        self.stdout.write(self.style.SUCCESS(
            f"Feed bias: {len(to_update)} classified ({tokens} tokens)"
        ))
