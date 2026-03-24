import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.core.models import Language
from apps.feed.models import Category, Feed
from apps.location.models import Country


class Command(BaseCommand):
    help = "Load RSS feeds from rss_database.json"

    def handle(self, *args, **options):
        json_path = Path(__file__).parent / "rss_database.json"
        with open(json_path) as f:
            data = json.load(f)

        feeds = data["feeds"]
        self.stdout.write(f"Loading {len(feeds)} feeds from {json_path.name}...")

        # Pre-load lookups
        countries = {c.code: c for c in Country.objects.all()}
        languages = {l.code: l for l in Language.objects.all()}

        created = 0
        updated = 0
        for entry in feeds:
            # Category
            cat_slug = slugify(entry.get("category", ""))
            category = None
            if cat_slug:
                category, _ = Category.objects.get_or_create(
                    slug=cat_slug,
                    defaults={"name": entry["category"].title()},
                )

            country = countries.get(entry.get("country_id", ""))
            language = languages.get(entry.get("language_id", ""))

            feed, is_new = Feed.objects.get_or_create(
                url=entry["url"],
                defaults={
                    "title": entry["name"],
                    "website": entry.get("website", ""),
                    "description": entry.get("description", ""),
                    "category": category,
                    "country": country,
                    "language": language,
                    "reliability": entry.get("reliability", 3),
                },
            )

            if is_new:
                created += 1
            else:
                # Update existing feed with new data
                changed = False
                for field, value in [
                    ("title", entry["name"]),
                    ("website", entry.get("website", "")),
                    ("description", entry.get("description", "")),
                    ("category", category),
                    ("country", country),
                    ("language", language),
                    ("reliability", entry.get("reliability", 3)),
                ]:
                    if getattr(feed, field) != value:
                        setattr(feed, field, value)
                        changed = True
                if changed:
                    feed.save()
                    updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Feeds: {created} new, {updated} updated ({len(feeds)} total)"
        ))
