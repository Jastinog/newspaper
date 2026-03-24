import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.feed.feeds import DEFAULT_CATEGORIES
from apps.feed.models import Category, Feed
from apps.location.models import Country

FEED_FIELDS = ("title", "website", "description", "category", "country", "language", "reliability")


class Command(BaseCommand):
    help = "Load RSS feeds from rss_database.json"

    def handle(self, *args, **options):
        json_path = Path(__file__).parent / "rss_database.json"
        with open(json_path) as f:
            data = json.load(f)

        entries = data["feeds"]
        self.stdout.write(f"Loading {len(entries)} feeds from {json_path.name}...")

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
