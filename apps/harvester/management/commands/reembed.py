"""Backfill chunk vectors for completed articles that have none.

The embedding enrichment stage used to flag articles `embedded=True` even when
the local model was unavailable (degraded), so a batch could be marked done
with no `ArticleChunk` rows ever written. This command finds completed articles
that have content but no chunks and (re)embeds them with the local model, so the
embedding digest has real vectors to match against.

Idempotent and safe to re-run. Use `--dry-run` to preview.
"""

from django.core.management.base import BaseCommand

from apps.feed.models import Article, ArticleChunk
from apps.feed.services.embed import embed_article


class Command(BaseCommand):
    help = "Re-embed completed articles that have content but no chunk vectors"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show how many articles would be re-embedded without doing it",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Process at most this many articles (default: all)",
        )

    def handle(self, *, dry_run=False, limit=None, **options):
        have_chunks = set(ArticleChunk.objects.values_list("article_id", flat=True))

        qs = (
            Article.objects
            .filter(status=Article.Status.COMPLETED)
            .exclude(content="")
            .exclude(id__in=have_chunks)
            .order_by("-published")
        )
        # Pull the fields we need up front — one query, no per-article re-fetch.
        targets = list(qs.values_list("id", "title", "content"))
        total = len(targets)

        self.stdout.write(
            f"Completed articles with content but no chunks: {total}"
        )
        if not total:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill"))
            return

        if limit:
            targets = targets[:limit]
            self.stdout.write(f"Limiting to {len(targets)} articles")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing embedded"))
            return

        # Loads the local ONNX model once (singleton) on the first embed call.
        embedded = chunks_written = empty = failed = 0
        for i, (aid, title, content) in enumerate(targets, 1):
            try:
                n = embed_article(aid, title or "", content or "")
            except Exception:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  article {aid}: embed failed"))
                continue

            # Flag per-article (not batched at the end) so an interrupted run
            # keeps its progress. n == 0 means nothing was chunkable — still a
            # legitimate terminal state, so mark it done and don't reprocess.
            Article.objects.filter(id=aid).update(embedded=True)
            embedded += 1
            chunks_written += n
            if n == 0:
                empty += 1

            if i % 50 == 0 or i == len(targets):
                self.stdout.write(
                    f"  {i}/{len(targets)} processed "
                    f"({chunks_written} chunks, {empty} empty, {failed} failed)"
                )

        self.stdout.write(self.style.SUCCESS(
            f"Done: {embedded} articles embedded, {chunks_written} chunks written, "
            f"{empty} had no chunkable text, {failed} failed"
        ))
