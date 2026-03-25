from django.core.management.base import BaseCommand

from apps.harvester.models import RunStatus
from apps.harvester.services.scheduler import FeedHarvester


class Command(BaseCommand):
    help = "Run a single feed harvest tick"

    def handle(self, **options):
        runs = FeedHarvester(stdout=self.stdout).harvest()

        if not runs:
            self.stdout.write("No eligible feeds")
            return

        total_new = sum(r.new_articles for r in runs)
        errors = [r for r in runs if r.status == RunStatus.ERROR]

        self.stdout.write(self.style.SUCCESS(
            f"Fetched {len(runs)} feeds, {total_new} new articles"
        ))

        for r in errors:
            self.stderr.write(f"  {r.feed}: {r.error_message}")
