from django.core.management.base import BaseCommand

from apps.news.services.ingest import UpdateService


class Command(BaseCommand):
    help = "Fetch RSS feeds, extract full content, and embed articles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-extract", action="store_true",
            help="Skip content extraction step",
        )
        parser.add_argument(
            "--skip-images", action="store_true",
            help="Skip image download step",
        )
        parser.add_argument(
            "--skip-embed", action="store_true",
            help="Skip embedding step",
        )
        parser.add_argument(
            "--workers", type=int, default=20,
            help="Number of concurrent threads",
        )
        parser.add_argument(
            "--days", type=int, default=30,
            help="Only extract articles from the last N days (default: 30)",
        )

    def handle(self, *args, **options):
        service = UpdateService(
            workers=options["workers"],
            days=options["days"],
            stdout=self.stdout,
        )
        result = service.run(
            skip_extract=options["skip_extract"],
            skip_images=options["skip_images"],
            skip_embed=options["skip_embed"],
        )

        if result.fetch_errors:
            self.stderr.write(
                self.style.WARNING(f"{len(result.fetch_errors)} feed errors:")
            )
            for err in result.fetch_errors[:10]:
                self.stderr.write(f"  - {err}")
            if len(result.fetch_errors) > 10:
                self.stderr.write(
                    f"  ... and {len(result.fetch_errors) - 10} more"
                )

        if result.extract_errors:
            self.stderr.write(
                self.style.WARNING(
                    f"{len(result.extract_errors)} extraction errors"
                )
            )
            self.stderr.write(
                "Run 'manage.py debug_extract --errors' for details"
            )
