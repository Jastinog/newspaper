import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.feed.models import ArticleImageSource, Category, Feed

DEFAULT_IMAGE_SOURCES = [
    {"slug": "rss-image", "name": "RSS Image"},
    {"slug": "og-image", "name": "OG Image"},
]

DEFAULT_CATEGORIES = [
    {"slug": "world", "name": "World News", "order": 0},
    {"slug": "us", "name": "US News", "order": 1},
    {"slug": "europe", "name": "Europe", "order": 2},
    {"slug": "tech", "name": "Tech", "order": 3},
    {"slug": "ai", "name": "AI / ML", "order": 4},
    {"slug": "security", "name": "Security", "order": 5},
    {"slug": "science", "name": "Science", "order": 6},
    {"slug": "finance", "name": "Finance", "order": 7},
    {"slug": "dev", "name": "Dev & Programming", "order": 8},
    {"slug": "linux", "name": "Linux / Open Source", "order": 9},
    {"slug": "startups", "name": "Startups & VC", "order": 10},
    {"slug": "gaming", "name": "Gaming", "order": 11},
    {"slug": "design", "name": "Design / Product", "order": 12},
    {"slug": "media", "name": "Media / Blogs", "order": 13},
    {"slug": "mideast", "name": "Middle East", "order": 14},
    {"slug": "asia", "name": "Asia-Pacific", "order": 15},
    {"slug": "southasia", "name": "South Asia", "order": 16},
    {"slug": "africa", "name": "Africa", "order": 17},
    {"slug": "latam", "name": "Latin America", "order": 18},
    {"slug": "ru", "name": "Русские", "order": 19},
]
from apps.location.models import Country

FEED_FIELDS = ("title", "website", "description", "category", "country", "language", "reliability")


class Command(BaseCommand):
    help = "Load RSS feeds from rss_database.json"

    def handle(self, *args, **options):
        json_path = settings.BASE_DIR / "rss_database.json"
        with open(json_path) as f:
            data = json.load(f)

        entries = data["feeds"]
        self.stdout.write(f"Loading {len(entries)} feeds from {json_path.name}...")

        self._seed_image_sources()
        cat_map = self._seed_categories()
        countries = {c.code: c for c in Country.objects.all()}
        languages = {l.code: l for l in Language.objects.all()}
        existing = {f.url: f for f in Feed.objects.select_related("category", "country", "language").all()}

        to_create = []
        to_update = []

        for entry in entries:
            fields = self._entry_fields(entry, cat_map, countries, languages)
            feed = existing.get(entry["url"])

            if feed is None:
                to_create.append(Feed(url=entry["url"], **fields))
            else:
                changed = False
                for attr, value in fields.items():
                    if getattr(feed, attr) != value:
                        setattr(feed, attr, value)
                        changed = True
                if changed:
                    to_update.append(feed)

        if to_create:
            Feed.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            Feed.objects.bulk_update(to_update, fields=list(FEED_FIELDS))

        self.stdout.write(self.style.SUCCESS(
            f"Feeds: {len(to_create)} new, {len(to_update)} updated ({len(entries)} total)"
        ))

    def _seed_image_sources(self):
        for entry in DEFAULT_IMAGE_SOURCES:
            ArticleImageSource.objects.get_or_create(
                slug=entry["slug"],
                defaults={"name": entry["name"]},
            )

    def _seed_categories(self):
        cat_map = {}
        for entry in DEFAULT_CATEGORIES:
            cat, _ = Category.objects.get_or_create(
                slug=entry["slug"],
                defaults={"name": entry["name"], "order": entry["order"]},
            )
            cat_map[entry["slug"]] = cat
        return cat_map

    @staticmethod
    def _entry_fields(entry, cat_map, countries, languages):
        return {
            "title": entry["name"],
            "website": entry.get("website", ""),
            "description": entry.get("description", ""),
            "category": cat_map.get(entry.get("category", "")),
            "country": countries.get(entry.get("country_id", "")),
            "language": languages.get(entry.get("language_id", "")),
            "reliability": entry.get("reliability", 3),
        }
