"""Seed digest sections, embeddings, translations, and config.

Idempotent: safe to run multiple times. Uses get_or_create on slug.
Generates embeddings for any SectionEmbedding entries missing vectors.
"""

from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.core.services.ai import EmbeddingClient
from apps.digest.models import (
    DigestConfig, DigestSection, DigestSectionTranslation, SectionEmbedding,
)


TOPICS = [
    {
        "slug": "world-politics",
        "order": 0,
        "description": "International relations, diplomacy, geopolitics, summits, treaties, sanctions",
        "translations": {
            "en": "World Politics & Diplomacy",
            "ru": "Мировая политика и дипломатия",
            "uk": "Світова політика та дипломатія",
        },
        "embeddings": [
            "International diplomacy and foreign policy negotiations between world leaders",
            "United Nations resolutions, votes, and multilateral agreements",
            "NATO alliance decisions, military cooperation, and defense pacts",
            "Geopolitical tensions and rivalry between major world powers",
            "Peace negotiations, ceasefire agreements, and conflict resolution talks",
            "Economic sanctions, trade embargoes, and diplomatic pressure campaigns",
            "Presidential and prime ministerial summits and bilateral meetings",
            "International treaties, accords, and diplomatic breakthroughs",
            "Global governance reform and international institution changes",
            "Diplomatic crises, ambassador recalls, and embassy incidents",
        ],
    },
    {
        "slug": "conflicts",
        "order": 1,
        "description": "Wars, military operations, terrorism, defense, security threats",
        "translations": {
            "en": "Conflicts & Security",
            "ru": "Конфликты и безопасность",
            "uk": "Конфлікти та безпека",
        },
        "embeddings": [
            "Armed conflicts, wars, and military operations around the world",
            "Terrorist attacks, extremist groups, and counter-terrorism operations",
            "Ceasefire violations, truce collapses, and escalation of hostilities",
            "Military weapons systems, defense technology, and arms deals",
            "Refugee crises and humanitarian disasters caused by conflict",
            "Cyber warfare, state-sponsored hacking, and digital security threats",
            "Nuclear weapons proliferation and disarmament negotiations",
            "Peacekeeping missions and international military interventions",
            "Intelligence operations, espionage scandals, and security breaches",
            "Civil unrest, coups, and political violence in unstable regions",
        ],
    },
    {
        "slug": "us-politics",
        "order": 2,
        "description": "US domestic politics, Congress, White House, elections, Supreme Court",
        "translations": {
            "en": "US Politics",
            "ru": "Политика США",
            "uk": "Політика США",
        },
        "embeddings": [
            "US presidential decisions, executive orders, and White House policy",
            "US Congress legislation, Senate votes, and House of Representatives bills",
            "US elections, primaries, polling data, and campaign developments",
            "US Supreme Court rulings, judicial appointments, and constitutional cases",
            "US political party dynamics, Republican and Democratic strategies",
            "US federal investigations, special counsel, and political scandals",
            "US immigration policy, border security, and reform debates",
            "US government budget, spending bills, and debt ceiling negotiations",
            "US state politics, gubernatorial races, and local government news",
            "US political figures, cabinet changes, and administration reshuffles",
        ],
    },
    {
        "slug": "europe",
        "order": 3,
        "description": "European Union, European politics, elections, migration, policy",
        "translations": {
            "en": "Europe",
            "ru": "Европа",
            "uk": "Європа",
        },
        "embeddings": [
            "European Union policy decisions, regulations, and institutional reforms",
            "European parliamentary elections and national elections across Europe",
            "European migration crisis, asylum policy, and border control measures",
            "Brexit aftermath and UK-EU relations developments",
            "European energy policy, gas supply issues, and green transition",
            "European economic policy, eurozone stability, and fiscal rules",
            "European defense and security cooperation initiatives",
            "Political developments in major European countries: Germany, France, Italy",
            "European social policy, labor markets, and welfare reform",
            "Central and Eastern European politics and EU integration progress",
        ],
    },
    {
        "slug": "economy",
        "order": 4,
        "description": "Global economy, stock markets, central banks, trade, inflation, business",
        "translations": {
            "en": "Economy & Markets",
            "ru": "Экономика и рынки",
            "uk": "Економіка та ринки",
        },
        "embeddings": [
            "Stock market movements, Wall Street trading, and major index changes",
            "Central bank interest rate decisions, Federal Reserve, and ECB policy",
            "Global inflation data, consumer prices, and cost of living trends",
            "International trade agreements, tariffs, and supply chain disruptions",
            "Major corporate earnings, mergers, acquisitions, and business deals",
            "Cryptocurrency markets, Bitcoin prices, and digital asset regulation",
            "Oil and energy prices, OPEC decisions, and commodity markets",
            "Employment data, unemployment rates, and labor market trends",
            "Global economic forecasts, GDP growth, and recession indicators",
            "Banking sector news, financial regulation, and fintech developments",
        ],
    },
    {
        "slug": "technology",
        "order": 5,
        "description": "Technology, AI, big tech, cybersecurity, startups, digital innovation",
        "translations": {
            "en": "Technology & AI",
            "ru": "Технологии и ИИ",
            "uk": "Технології та ШІ",
        },
        "embeddings": [
            "Artificial intelligence breakthroughs, new AI models, and machine learning advances",
            "Big tech companies: Apple, Google, Microsoft, Meta, Amazon news and strategy",
            "Cybersecurity incidents, data breaches, and online privacy threats",
            "Semiconductor industry, chip manufacturing, and tech supply chains",
            "Social media platforms, content moderation, and digital regulation",
            "Space technology, satellite launches, and commercial space industry",
            "Tech startup funding, venture capital, and unicorn company valuations",
            "Robotics advances, automation technology, and industrial innovation",
            "AI regulation, ethics debates, and government tech policy",
            "Cloud computing, enterprise software, and digital transformation news",
        ],
    },
    {
        "slug": "science-health",
        "order": 6,
        "description": "Medical breakthroughs, epidemics, space exploration, scientific research",
        "translations": {
            "en": "Science & Health",
            "ru": "Наука и здоровье",
            "uk": "Наука та здоров'я",
        },
        "embeddings": [
            "Medical research breakthroughs, new treatments, and drug approvals",
            "Pandemic monitoring, infectious disease outbreaks, and WHO alerts",
            "Space exploration missions, NASA discoveries, and Mars exploration",
            "Climate science research, environmental studies, and ecological findings",
            "Vaccine development, clinical trials, and immunization campaigns",
            "Mental health research, psychology studies, and public health policy",
            "Genetics research, gene therapy, and CRISPR technology advances",
            "Physics discoveries, quantum computing, and fundamental science",
            "Public health crises, healthcare system challenges, and hospital capacity",
            "Astronomy discoveries, telescope observations, and cosmic phenomena",
        ],
    },
    {
        "slug": "climate",
        "order": 7,
        "description": "Climate change, environmental policy, natural disasters, renewable energy",
        "translations": {
            "en": "Climate & Environment",
            "ru": "Климат и экология",
            "uk": "Клімат та екологія",
        },
        "embeddings": [
            "Climate change policy, COP summits, and emission reduction commitments",
            "Natural disasters: hurricanes, earthquakes, floods, wildfires, and droughts",
            "Renewable energy expansion, solar and wind power projects",
            "Environmental conservation, wildlife protection, and biodiversity loss",
            "Carbon capture technology, green hydrogen, and clean energy innovation",
            "Deforestation, ocean pollution, and plastic waste crisis",
            "Electric vehicles, transportation decarbonization, and green mobility",
            "Extreme weather events, heat waves, and climate adaptation measures",
            "Environmental regulation, pollution control, and industrial emissions",
            "Sustainable agriculture, food security, and water resource management",
        ],
    },
    {
        "slug": "society",
        "order": 8,
        "description": "Social movements, culture, education, demographics, media",
        "translations": {
            "en": "Society & Culture",
            "ru": "Общество и культура",
            "uk": "Суспільство та культура",
        },
        "embeddings": [
            "Social movements, protests, civil rights, and activism worldwide",
            "Education policy, university research, and academic freedom debates",
            "Cultural events, film festivals, art exhibitions, and literary awards",
            "Demographics trends, population changes, and migration patterns",
            "Media industry, journalism, press freedom, and disinformation",
            "Religious events, interfaith dialogue, and church-state relations",
            "Gender equality, women's rights, and LGBTQ+ rights developments",
            "Housing crisis, urban development, and infrastructure projects",
            "Celebrity news, entertainment industry, and pop culture phenomena",
            "Public opinion polls, societal trends, and generational shifts",
        ],
    },
    {
        "slug": "sports",
        "order": 9,
        "description": "Major sports leagues, Olympics, championships, transfers, records",
        "translations": {
            "en": "Sports",
            "ru": "Спорт",
            "uk": "Спорт",
        },
        "embeddings": [
            "Football (soccer) league results, Champions League, and World Cup news",
            "American sports: NFL, NBA, MLB, NHL scores and championship updates",
            "Olympic Games preparation, competition results, and medal standings",
            "Tennis Grand Slam tournaments, rankings, and major match results",
            "Formula 1 racing, MotoGP, and motorsport championship standings",
            "Transfer market news, player signings, and contract negotiations",
            "Sports doping scandals, anti-doping investigations, and athlete bans",
            "Boxing and MMA: major fights, title bouts, and combat sports news",
            "Cricket, rugby, and other international sports tournament results",
            "Sports business, broadcasting rights, stadium deals, and franchise values",
        ],
    },
]


class Command(BaseCommand):
    help = "Seed digest sections, embeddings, translations, and config (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-embed",
            action="store_true",
            help="Skip embedding generation (create section structure only)",
        )

    def handle(self, *args, **options):
        # 1. Ensure DigestConfig exists
        DigestConfig.get()
        self.stdout.write("DigestConfig: OK")

        # 2. Ensure languages exist
        languages = {}
        for code, name, default in [("en", "English", True), ("ru", "Russian", False), ("uk", "Ukrainian", False)]:
            lang, _ = Language.objects.get_or_create(code=code, defaults={"name": name})
            if default and not lang.is_default:
                lang.is_default = True
                lang.save(update_fields=["is_default"])
            languages[code] = lang

        # 3. Create sections, translations, embeddings
        total_embeddings_created = 0
        for section_data in TOPICS:
            section, created = DigestSection.objects.get_or_create(
                slug=section_data["slug"],
                defaults={
                    "order": section_data["order"],
                    "description": section_data["description"],
                },
            )
            status = "created" if created else "exists"

            # Translations
            for lang_code, name in section_data["translations"].items():
                DigestSectionTranslation.objects.get_or_create(
                    section=section,
                    language=languages[lang_code],
                    defaults={"name": name},
                )

            # Embeddings
            for desc in section_data["embeddings"]:
                _, emb_created = SectionEmbedding.objects.get_or_create(
                    section=section,
                    description=desc,
                )
                if emb_created:
                    total_embeddings_created += 1

            self.stdout.write(f"  [{section.order}] {section_data['translations']['en']}: {status}")

        self.stdout.write(f"Sections: {len(TOPICS)}, new embeddings: {total_embeddings_created}")

        # 4. Generate embeddings for pending
        if options["no_embed"]:
            self.stdout.write("Skipping embedding generation (--no-embed)")
            return

        pending = list(SectionEmbedding.objects.filter(embedding__isnull=True))
        if not pending:
            self.stdout.write("All embeddings already generated.")
            return

        self.stdout.write(f"Generating {len(pending)} embeddings...")
        client = EmbeddingClient()

        # Batch in groups of 20
        batch_size = 20
        for i in range(0, len(pending), batch_size):
            batch = pending[i:i + batch_size]
            descriptions = [e.description for e in batch]
            vectors, tokens = client.embed_batch(descriptions)
            for emb_obj, vector in zip(batch, vectors):
                emb_obj.embedding = vector
                emb_obj.save(update_fields=["embedding"])
            self.stdout.write(f"  Batch {i // batch_size + 1}: {len(batch)} embeddings, {tokens} tokens")

        self.stdout.write(self.style.SUCCESS(f"Done! {len(pending)} embeddings generated."))
