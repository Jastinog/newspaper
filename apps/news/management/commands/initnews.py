from django.core.management.base import BaseCommand

from apps.news.feeds import DEFAULT_CATEGORIES, DEFAULT_FEEDS
from apps.news.models import Category, Feed, TopicEmbedding
from apps.news.services.embeddings import EmbeddingClient, EmbeddingError

# Multiple search queries per topic to capture different angles
TOPIC_QUERIES = [
    # 0: AI • Technology
    [
        "artificial intelligence, machine learning, deep learning, neural networks, "
        "large language models, GPT, Claude, AI research breakthroughs",
        "technology companies, tech startups, product launches, software platforms, "
        "digital services, mobile apps, Silicon Valley",
        "semiconductors, computer chips, hardware innovation, cloud computing, "
        "robotics, autonomous systems, tech industry trends",
    ],
    # 1: World Politics
    [
        "international relations, diplomacy, foreign policy, geopolitics, "
        "summits, treaties, international agreements",
        "elections, political leaders, government policy, political parties, "
        "democratic processes, regime changes, political crisis",
        "United Nations, NATO, European Union politics, G7, G20, "
        "international organizations, sanctions, global governance",
    ],
    # 2: Business • Economy
    [
        "stock market, financial markets, economic indicators, GDP growth, "
        "inflation rates, interest rates, central bank policy",
        "corporate news, mergers and acquisitions, company earnings reports, "
        "business strategy, CEO changes, corporate governance",
        "global trade, supply chains, economic sanctions, tariffs, "
        "international commerce, currency markets, investment trends",
    ],
    # 3: Science • Health
    [
        "scientific discoveries, research breakthroughs, space exploration, "
        "physics, biology, chemistry, astronomy advances",
        "public health, medical research, disease outbreaks, epidemics, "
        "vaccines, healthcare systems, WHO reports",
        "pharmaceutical industry, drug development, clinical trials, "
        "biotechnology, genetics, medical devices, mental health",
    ],
    # 4: War • Conflicts
    [
        "armed conflicts, military operations, war zones, battles, "
        "territorial disputes, ceasefire negotiations, peace talks",
        "Ukraine war, Russia military, NATO defense, weapons supplies, "
        "frontline updates, drone warfare, military aid",
        "Middle East conflicts, Gaza, Israel, terrorism, insurgency, "
        "humanitarian crisis, refugees, war casualties",
    ],
    # 5: Crime • Justice
    [
        "criminal cases, law enforcement, police operations, arrests, "
        "investigations, organized crime, drug trafficking",
        "court rulings, legal proceedings, trials, verdicts, "
        "supreme court decisions, judicial reforms, extradition",
        "fraud, corruption scandals, money laundering, "
        "human rights violations, war crimes prosecution, Interpol",
    ],
    # 6: Cybersecurity • Privacy
    [
        "cyber attacks, data breaches, hacking incidents, ransomware, "
        "malware, cyber threats, vulnerability disclosures",
        "digital privacy, surveillance, data protection laws, GDPR, "
        "online tracking, social media privacy, encryption policy",
        "information security, zero-day exploits, state-sponsored hacking, "
        "cyber warfare, critical infrastructure attacks, identity theft",
    ],
    # 7: Energy • Climate
    [
        "climate change, global warming, carbon emissions, greenhouse gases, "
        "climate policy, Paris agreement, environmental regulations",
        "renewable energy, solar power, wind energy, electric vehicles, "
        "green technology, clean energy transition, battery storage",
        "oil and gas industry, energy prices, OPEC decisions, nuclear energy, "
        "energy security, power grid, natural disasters weather",
    ],
    # 8: Sports • Entertainment
    [
        "professional sports, football soccer, basketball, tennis, Formula 1, "
        "Olympics, championships, tournament results, transfer news",
        "entertainment industry, movies, box office, music releases, "
        "streaming platforms, celebrity news, TV series, awards",
        "gaming industry, esports, cultural events, festivals, "
        "arts exhibitions, book releases, theatre, concerts",
    ],
    # 9: Society • Culture
    [
        "social issues, inequality, protests, social movements, "
        "human rights, immigration, migration policy, civil rights",
        "education policy, university research, cultural trends, "
        "demographics, religion, community development, social welfare",
        "lifestyle trends, food industry, travel, fashion, "
        "social media culture, generational shifts, public opinion polls",
    ],
]


class Command(BaseCommand):
    help = "Load default categories, RSS feeds, and topic embeddings"

    def handle(self, *args, **options):
        self._seed_categories()
        self._seed_feeds()
        self._seed_topic_embeddings()

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

    def _seed_topic_embeddings(self):
        existing = TopicEmbedding.objects.count()
        if existing:
            self.stdout.write(f"Topic embeddings: {existing} already exist, skipping")
            return

        self.stdout.write("Generating topic embeddings...")
        try:
            client = EmbeddingClient()
        except EmbeddingError as e:
            self.stdout.write(self.style.WARNING(
                f"Skipping topic embeddings (no API key): {e}"
            ))
            return

        query_map = [
            (topic_idx, query)
            for topic_idx, queries in enumerate(TOPIC_QUERIES)
            for query in queries
        ]

        all_queries = [query for _, query in query_map]
        embeddings, total_tokens = client.embed_batch(all_queries)

        for (topic_idx, query), embedding in zip(query_map, embeddings):
            TopicEmbedding.objects.create(
                topic_index=topic_idx,
                description=query,
                embedding=embedding,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Topic embeddings: {len(embeddings)} created ({total_tokens} tokens)"
        ))
