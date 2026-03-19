from django.core.management.base import BaseCommand

from apps.news.feeds import DEFAULT_CATEGORIES, DEFAULT_FEEDS
from apps.news.models import Category, DigestTopic, Feed, TopicEmbedding
from apps.news.services.ai import EmbeddingClient, EmbeddingError

DEFAULT_TOPICS = [
    {
        "name_en": "AI • Technology",
        "name_ru": "AI • Технологии",
        "name_uk": "AI • Технології",
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
        "name_ru": "Мировая политика",
        "name_uk": "Світова політика",
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
        "name_en": "Business • Economy",
        "name_ru": "Бизнес • Экономика",
        "name_uk": "Бізнес • Економіка",
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
        "name_en": "Science • Health",
        "name_ru": "Наука • Здоровье",
        "name_uk": "Наука • Здоров'я",
        "queries": [
            "scientific discoveries, research breakthroughs, space exploration, "
            "physics, biology, chemistry, astronomy advances",
            "public health, medical research, disease outbreaks, epidemics, "
            "vaccines, healthcare systems, WHO reports",
            "pharmaceutical industry, drug development, clinical trials, "
            "biotechnology, genetics, medical devices, mental health",
        ],
    },
    {
        "name_en": "War • Conflicts",
        "name_ru": "Война • Конфликты",
        "name_uk": "Війна • Конфлікти",
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
        "name_en": "Crime • Justice",
        "name_ru": "Криминал • Правосудие",
        "name_uk": "Кримінал • Правосуддя",
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
        "name_en": "Cybersecurity • Privacy",
        "name_ru": "Кибербезопасность • Приватность",
        "name_uk": "Кібербезпека • Приватність",
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
        "name_en": "Energy • Climate",
        "name_ru": "Энергетика • Климат",
        "name_uk": "Енергетика • Клімат",
        "queries": [
            "climate change, global warming, carbon emissions, greenhouse gases, "
            "climate policy, Paris agreement, environmental regulations",
            "renewable energy, solar power, wind energy, electric vehicles, "
            "green technology, clean energy transition, battery storage",
            "oil and gas industry, energy prices, OPEC decisions, nuclear energy, "
            "energy security, power grid, natural disasters weather",
        ],
    },
    {
        "name_en": "Sports • Entertainment",
        "name_ru": "Спорт • Развлечения",
        "name_uk": "Спорт • Розваги",
        "queries": [
            "professional sports, football soccer, basketball, tennis, Formula 1, "
            "Olympics, championships, tournament results, transfer news",
            "entertainment industry, movies, box office, music releases, "
            "streaming platforms, celebrity news, TV series, awards",
            "gaming industry, esports, cultural events, festivals, "
            "arts exhibitions, book releases, theatre, concerts",
        ],
    },
    {
        "name_en": "Society • Culture",
        "name_ru": "Общество • Культура",
        "name_uk": "Суспільство • Культура",
        "queries": [
            "social issues, inequality, protests, social movements, "
            "human rights, immigration, migration policy, civil rights",
            "education policy, university research, cultural trends, "
            "demographics, religion, community development, social welfare",
            "lifestyle trends, food industry, travel, fashion, "
            "social media culture, generational shifts, public opinion polls",
        ],
    },
]


class Command(BaseCommand):
    help = "Load default categories, RSS feeds, and digest topics"

    def handle(self, *args, **options):
        self._seed_categories()
        self._seed_feeds()
        self._seed_topics()

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

    def _seed_topics(self):
        if DigestTopic.objects.exists():
            self.stdout.write(f"Topics: {DigestTopic.objects.count()} already exist, skipping")
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
