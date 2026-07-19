from django.core.management.base import BaseCommand
from django.db.models import Count, Min

from apps.feed.models import Article


class Command(BaseCommand):
    help = "Remove empty (no content) articles and duplicate-title articles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would be deleted without deleting anything",
        )

    def handle(self, *, dry_run=False, **options):
        empty_qs = Article.objects.filter(content="")
        empty_ids = set(empty_qs.values_list("id", flat=True))

        # Duplicate titles: keep the oldest (lowest id) row per title, drop the rest.
        dup_titles = (
            Article.objects.exclude(title="")
            .values("title")
            .annotate(n=Count("id"), keep=Min("id"))
            .filter(n__gt=1)
        )
        dup_ids: set[int] = set()
        for row in dup_titles:
            dup_ids.update(
                Article.objects.filter(title=row["title"])
                .exclude(id=row["keep"])
                .values_list("id", flat=True)
            )

        to_delete = empty_ids | dup_ids
        self.stdout.write(
            f"Empty content: {len(empty_ids)} | "
            f"Duplicate titles: {len(dup_ids)} | "
            f"Total to delete: {len(to_delete)}"
        )

        if not to_delete:
            self.stdout.write(self.style.SUCCESS("Nothing to clean up"))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing deleted"))
            return

        deleted, _ = Article.objects.filter(id__in=to_delete).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} rows"))
