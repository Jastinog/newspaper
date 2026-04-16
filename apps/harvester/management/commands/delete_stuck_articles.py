from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.feed.models import Article


class Command(BaseCommand):
    help = (
        "Delete articles whose pipeline never completed (any of rss_images_at, "
        "content_extracted_at, og_images_at is NULL). They will be re-collected "
        "on the next feed fetch."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would be deleted without deleting.",
        )
        parser.add_argument(
            "--reset-hwm", action="store_true",
            help="Also reset Feed.last_entry_published so deleted articles can be re-fetched.",
        )

    def handle(self, *args, **options):
        stuck = Article.objects.filter(
            Q(pipeline__rss_images_at__isnull=True)
            | Q(pipeline__content_extracted_at__isnull=True)
            | Q(pipeline__og_images_at__isnull=True)
            | Q(pipeline__isnull=True),
        )
        count = stuck.count()
        feed_ids = list(stuck.values_list("feed_id", flat=True).distinct())

        self.stdout.write(f"Stuck articles: {count} across {len(feed_ids)} feeds")

        if options["dry_run"]:
            self.stdout.write("Dry run — nothing deleted.")
            return

        deleted, per_model = stuck.delete()
        self.stdout.write(f"Deleted {deleted} rows total: {per_model}")

        if options["reset_hwm"]:
            from apps.feed.models import Feed
            updated = Feed.objects.filter(id__in=feed_ids).update(
                last_entry_published=None,
            )
            self.stdout.write(f"Reset last_entry_published on {updated} feeds")
