from django.core.management.base import BaseCommand

from apps.news.services.updater import FeedFetcher


class Command(BaseCommand):
    help = "Fetch articles from all enabled RSS feeds"

    def add_arguments(self, parser):
        parser.add_argument(
            "--workers", type=int, default=20,
            help="Number of concurrent fetch threads",
        )

    def handle(self, *args, **options):
        fetcher = FeedFetcher(workers=options["workers"], stdout=self.stdout)
        feeds_count, new_articles, errors = fetcher.fetch_all()

        if errors:
            self.stderr.write(self.style.WARNING(f"{len(errors)} feeds had errors:"))
            for err in errors[:10]:
                self.stderr.write(f"  - {err}")
            if len(errors) > 10:
                self.stderr.write(f"  ... and {len(errors) - 10} more")
