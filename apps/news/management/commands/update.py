from django.core.management.base import BaseCommand

from apps.news.services.updater import UpdateService


class Command(BaseCommand):
    help = "Fetch RSS feeds and embed new articles in one pass"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-embed", action="store_true",
            help="Only fetch feeds, skip embedding",
        )
        parser.add_argument(
            "--workers", type=int, default=20,
            help="Number of concurrent fetch threads",
        )

    def handle(self, *args, **options):
        service = UpdateService(
            workers=options["workers"],
            stdout=self.stdout,
        )
        result = service.run(skip_embed=options["skip_embed"])

        if result.fetch_errors:
            self.stderr.write(
                self.style.WARNING(f"{len(result.fetch_errors)} feeds had errors:")
            )
            for err in result.fetch_errors[:10]:
                self.stderr.write(f"  - {err}")
            if len(result.fetch_errors) > 10:
                self.stderr.write(f"  ... and {len(result.fetch_errors) - 10} more")
