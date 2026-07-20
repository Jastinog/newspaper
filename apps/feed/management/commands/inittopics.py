from django.core.cache import cache
from django.core.management.base import BaseCommand

from apps.feed.models import Topic
from apps.feed.services.classify.taxonomy import TAXONOMY


class Command(BaseCommand):
    help = "Seed / update the Topic taxonomy from taxonomy.py"

    def handle(self, *args, **options):
        created = updated = 0
        for slug, name, order, _label in TAXONOMY:
            obj, was_created = Topic.objects.update_or_create(
                slug=slug,
                defaults={"name": name, "order": order},
            )
            created += was_created
            updated += not was_created

        cache.delete("nav_topics")  # refresh the site-wide topic nav
        self.stdout.write(self.style.SUCCESS(
            f"Topics: {created} created, {updated} updated ({len(TAXONOMY)} total)"
        ))
