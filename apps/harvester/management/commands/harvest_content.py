from django.core.management.base import BaseCommand

from apps.harvester.services.extractor import ContentExtractor, EXTRACT_BATCH_SIZE


class Command(BaseCommand):
    help = "Extract article content for a batch of unfetched articles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch", type=int, default=EXTRACT_BATCH_SIZE,
            help=f"Batch size (default: {EXTRACT_BATCH_SIZE})",
        )
        parser.add_argument(
            "--workers", type=int, default=10,
            help="Number of concurrent threads (default: 10)",
        )
        parser.add_argument(
            "--days", type=int, default=30,
            help="Only extract articles from the last N days (default: 30)",
        )

    def handle(self, *args, **options):
        extractor = ContentExtractor(
            workers=options["workers"],
            days=options["days"],
            stdout=self.stdout,
        )
        total, extracted, errors = extractor.extract_new(
            batch_size=options["batch"],
        )

        self.stdout.write(self.style.SUCCESS(
            f"Found {total}, extracted {extracted}, failed {total - extracted}"
        ))

        if errors:
            self.stderr.write(self.style.WARNING(f"{len(errors)} errors:"))
            for err in errors[:10]:
                self.stderr.write(f"  - {err}")
