from django.core.management.base import BaseCommand

from apps.news.feeds import DEFAULT_CATEGORIES, DEFAULT_FEEDS
from apps.news.models import Category, Feed


class Command(BaseCommand):
    help = "Load default categories and RSS feeds into the database"

    def handle(self, *args, **options):
        # Seed categories
        cat_created = 0
        cat_map = {}
        for entry in DEFAULT_CATEGORIES:
            cat, is_new = Category.objects.get_or_create(
                slug=entry["slug"],
                defaults={"name": entry["name"], "order": entry["order"]},
            )
            cat_map[entry["slug"]] = cat
            if is_new:
                cat_created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Categories: {cat_created} new ({len(DEFAULT_CATEGORIES)} total)"
        ))

        # Seed feeds
        feed_created = 0
        for entry in DEFAULT_FEEDS:
            category = cat_map.get(entry["category"])
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
