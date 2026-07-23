from django.core.management.base import BaseCommand
from django.db.models import F

from apps.feed.models import Article
from apps.feed.services.section import assign_section, reload_sections


class Command(BaseCommand):
    help = "Backfill section assignment for embedded articles that have none yet."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None,
                            help="Max articles to process (default: all pending)")
        parser.add_argument("--all", action="store_true",
                            help="Re-assign every embedded article, not just unsectioned ones")

    def handle(self, *args, **options):
        reload_sections()
        qs = Article.objects.filter(embedded=True)
        if not options["all"]:
            qs = qs.filter(sectioned=False)
        ids = list(
            qs.order_by(F("published").desc(nulls_last=True))
            .values_list("id", flat=True)
        )
        if options["limit"]:
            ids = ids[:options["limit"]]

        total = len(ids)
        assigned = 0
        self.stdout.write(f"Assigning sections for {total} articles...")
        for i, aid in enumerate(ids, 1):
            if assign_section(aid):
                assigned += 1
            Article.objects.filter(id=aid).update(sectioned=True)
            if i % 200 == 0:
                self.stdout.write(f"  {i}/{total} ({assigned} matched)")

        self.stdout.write(self.style.SUCCESS(
            f"Done: {assigned}/{total} articles assigned to a section "
            f"({total - assigned} cleared no section's score floor)."
        ))
