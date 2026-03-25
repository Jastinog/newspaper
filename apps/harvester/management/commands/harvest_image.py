from django.core.management.base import BaseCommand

from apps.harvester.services.downloader import ImageDownloader


class Command(BaseCommand):
    help = "Download and resize images for articles that haven't been processed yet"

    def add_arguments(self, parser):
        parser.add_argument(
            "--workers", type=int, default=10,
            help="Number of concurrent download threads (default: 10)",
        )
        parser.add_argument(
            "--days", type=int, default=7,
            help="Only process articles from the last N days (default: 7)",
        )

    def handle(self, *args, **options):
        downloader = ImageDownloader(
            workers=options["workers"],
            days=options["days"],
            stdout=self.stdout,
        )
        processed, downloaded, skipped = downloader.download_new()
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {processed} images, downloaded {downloaded}, skipped {skipped}"
            )
        )
