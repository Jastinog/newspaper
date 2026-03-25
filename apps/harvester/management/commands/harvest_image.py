from django.core.management.base import BaseCommand

from apps.harvester.services.downloader import DOWNLOAD_BATCH_SIZE, ImageDownloader


class Command(BaseCommand):
    help = "Download and resize images for articles that haven't been processed yet"

    def add_arguments(self, parser):
        parser.add_argument(
            "--workers", type=int, default=10,
            help="Number of concurrent download threads (default: 10)",
        )
        parser.add_argument(
            "--days", type=int, default=30,
            help="Only process articles from the last N days (default: 30)",
        )
        parser.add_argument(
            "--batch", type=int, default=DOWNLOAD_BATCH_SIZE,
            help=f"Batch size (default: {DOWNLOAD_BATCH_SIZE})",
        )

    def handle(self, *args, **options):
        downloader = ImageDownloader(
            workers=options["workers"],
            days=options["days"],
            stdout=self.stdout,
        )
        processed, downloaded, skipped = downloader.download_new(
            batch_size=options["batch"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {processed} images, downloaded {downloaded}, skipped {skipped}"
            )
        )
