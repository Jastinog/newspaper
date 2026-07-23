"""Generate card thumbnails for articles that have a full image but no thumbnail.

Thumbnails were added after the fact, so existing articles serve the full-size
`image` on card grids until backfilled. This downscales the already-stored
`image` (no re-download — the source may be gone and the stored WebP is enough)
into the lighter `thumbnail` rendition.

Idempotent and safe to re-run. Use `--dry-run` to preview.
"""

import uuid

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image

from apps.feed.models import Article
from apps.harvester.services.images.downloader import ImageDownloader


class Command(BaseCommand):
    help = "Generate card thumbnails for articles that have an image but no thumbnail"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show how many articles would be processed without doing it",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Process at most this many articles (default: all)",
        )

    def handle(self, *, dry_run=False, limit=None, **options):
        qs = (
            Article.objects
            .exclude(image="")
            .filter(thumbnail="")
            .order_by("-published")
        )
        total = qs.count()

        self.stdout.write(f"Articles with an image but no thumbnail: {total}")
        if not total:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill"))
            return

        if limit:
            qs = qs[:limit]
            planned = min(limit, total)
            self.stdout.write(f"Limiting to {planned} articles")
        else:
            planned = total

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing generated"))
            return

        # Stream instances in one query — the loop needs the model to save the
        # thumbnail, so `.iterator()` avoids both a per-row re-fetch and loading
        # the whole result set into memory.
        done = failed = 0
        for i, article in enumerate(qs.only("id", "image", "thumbnail").iterator(), 1):
            try:
                with article.image.open("rb") as fh:
                    thumb = ImageDownloader.encode_thumbnail(Image.open(fh))
                article.thumbnail.save(
                    f"{uuid.uuid4().hex}.webp", ContentFile(thumb), save=False,
                )
                article.save(update_fields=["thumbnail"])
                done += 1
            except Exception as e:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  article {article.pk}: {e}"))

            if i % 50 == 0 or i == planned:
                self.stdout.write(f"  {i}/{planned} processed ({done} done, {failed} failed)")

        self.stdout.write(self.style.SUCCESS(
            f"Done: {done} thumbnails generated, {failed} failed"
        ))
