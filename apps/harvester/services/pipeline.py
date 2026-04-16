import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta

from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from apps.billing.models import APIUsage
from apps.core.services.ai import EMBEDDING_MODEL, EmbeddingClient, calculate_cost
from apps.core.services.ai.embeddings import BATCH_SIZE
from apps.feed.models import Article, ArticleChunk, ArticleImage, ArticleImageSource, ArticlePipeline, Feed
from apps.harvester.models import (
    HarvesterFeed, PipelineEvent, PipelineSettings, RunStatus,
    STAGE_EMBED, STAGE_EXTRACT, STAGE_FEED, STAGE_OG_IMG, STAGE_RSS_IMG,
)

from .chunker import chunk_text
from .downloader import download_and_resize, save_image_result, select_primary_image
from .extractor import fetch_and_extract
from .fetcher import fetch_single_feed, save_articles
from .http import get_domain
from .throttle import acquire_domain, release_domain

logger = logging.getLogger(__name__)

IDLE_SLEEP = 1        # seconds – quick re-check when no work found
ERROR_SLEEP = 10
FEED_INTERVAL_MINUTES = 10
CANDIDATE_POOL = 30
DAYS_LOOKBACK = 30
DEFAULT_MAX_WORKERS = 2
DEFAULT_STAGE_DELAY = 0.5

_instance: "HarvestManager | None" = None


def get_manager() -> "HarvestManager | None":
    return _instance


def _cutoff_days():
    return timezone.now() - timedelta(days=DAYS_LOOKBACK)


def _record_event(stage, started_at, success, article_id=None):
    finished_at = timezone.now()
    duration_ms = max(1, int((finished_at - started_at).total_seconds() * 1000))
    try:
        PipelineEvent.objects.create(
            stage=stage, started_at=started_at, finished_at=finished_at,
            duration_ms=duration_ms, success=success, article_id=article_id,
        )
    except Exception:
        logger.debug("Failed to record pipeline event", exc_info=True)


def _run_stage(stage, fn, *args, **kwargs):
    """Run a pipeline stage in a worker thread with DB connection management."""
    close_old_connections()
    started_at = timezone.now()
    try:
        result = fn(*args, **kwargs)
        if result:
            article_id = result if isinstance(result, int) else None
            _record_event(stage, started_at, success=True, article_id=article_id)
        return result
    except Exception:
        logger.exception("Pipeline stage %s failed", fn.__name__)
        _record_event(stage, started_at, success=False)
        return False
    finally:
        close_old_connections()


def _cleanup_old_events():
    """Delete stale PipelineEvent rows (runs in a worker thread)."""
    close_old_connections()
    try:
        PipelineEvent.objects.filter(
            started_at__lt=timezone.now() - timedelta(hours=1),
        ).delete()
    except Exception:
        logger.debug("Failed to clean up pipeline events", exc_info=True)
    finally:
        close_old_connections()


class HarvestManager:
    """Article-centric pipeline with independent, non-blocking stages.

    Pipeline per article:
      fetch -> download RSS image -> extract content -> download OG image -> embed -> completed

    Each stage runs independently: when one finishes, it is re-submitted
    immediately without waiting for slower stages to complete.
    """

    def __init__(self):
        global _instance
        self._og_source = None
        self._current_workers = DEFAULT_MAX_WORKERS
        self._executor = ThreadPoolExecutor(
            max_workers=self._current_workers, thread_name_prefix="harvest",
        )
        self._last_cleanup = 0.0
        self._running: dict[str, Future] = {}
        self._stage_idle: dict[str, float] = {}
        _instance = self

    @property
    def is_active(self) -> bool:
        return PipelineSettings.load().is_active

    def _ensure_pool_size(self, settings):
        """Recreate thread pool if max_workers changed in admin."""
        desired = max(1, min(settings.max_workers, 6))
        if desired != self._current_workers and not self._running:
            self._executor.shutdown(wait=False)
            self._current_workers = desired
            self._executor = ThreadPoolExecutor(
                max_workers=desired, thread_name_prefix="harvest",
            )
            logger.info("Pipeline pool resized to %d workers", desired)

    def run(self):
        logger.info("HarvestManager started")
        while True:
            try:
                s = PipelineSettings.load()
                if not s.is_active:
                    time.sleep(IDLE_SLEEP)
                    continue
                self.dispatch(s)
                delay = s.stage_delay if self._running else IDLE_SLEEP
                time.sleep(delay)
            except Exception:
                logger.exception("HarvestManager error")
                time.sleep(ERROR_SLEEP)

    def dispatch(self, s) -> None:
        """Submit enabled stages and collect results without blocking.

        Each stage runs independently: as soon as one finishes, it is
        re-submitted on the next tick. Stages that found no work back off
        for IDLE_SLEEP before retrying.
        """
        now_mono = time.monotonic()
        if now_mono - self._last_cleanup > 300:
            self._last_cleanup = now_mono
            self._executor.submit(_cleanup_old_events)

        # Harvest results from completed futures
        for stage in list(self._running):
            future = self._running[stage]
            if future.done():
                try:
                    if not future.result():
                        self._stage_idle[stage] = now_mono
                except Exception:
                    pass
                del self._running[stage]

        # Resize pool after collecting futures so self._running is accurate
        self._ensure_pool_size(s)

        for stage, enabled, fn, args, kwargs in [
            (STAGE_EMBED, False,  # embedding disabled — Edition pipeline doesn't use it
             self._embed_one, (), {}),
            (STAGE_OG_IMG, s.enable_og_image_download,
             self._download_image, ("og-image", "og_images_at"),
             {"article__pipeline__content_extracted_at__isnull": False}),
            (STAGE_EXTRACT, s.enable_content_extraction,
             self._extract_one, (), {}),
            (STAGE_RSS_IMG, s.enable_rss_image_download,
             self._download_image, ("rss-image", "rss_images_at"), {}),
            (STAGE_FEED, s.enable_feed_fetching,
             self._fetch_one_feed, (), {}),
        ]:
            if not enabled or stage in self._running:
                continue
            if now_mono - self._stage_idle.get(stage, 0) < IDLE_SLEEP:
                continue
            self._running[stage] = self._executor.submit(
                _run_stage, stage, fn, *args, **kwargs)
            self._stage_idle.pop(stage, None)

    # ------------------------------------------------------------------
    # Stage 1 (highest priority): Embed one article -> mark completed
    # ------------------------------------------------------------------

    def _embed_one(self) -> bool:
        # Atomically claim one unembedded article to prevent concurrent embedding
        from django.db import transaction

        with transaction.atomic():
            pipeline = (
                ArticlePipeline.objects
                .select_for_update(skip_locked=True)
                .filter(embedded_at__isnull=True)
                .exclude(article__content="")
                .select_related("article")
                .first()
            )
            if not pipeline:
                return False
            # Mark as embedded immediately to prevent other workers from picking it up
            now = timezone.now()
            pipeline.embedded_at = now
            pipeline.completed_at = now
            pipeline.save(update_fields=["embedded_at", "completed_at"])

        article = pipeline.article
        chunks = chunk_text(article.title, article.content)

        try:
            client = EmbeddingClient()
            all_embeddings = []
            total_tokens = 0
            for i in range(0, len(chunks), BATCH_SIZE):
                batch_texts = chunks[i:i + BATCH_SIZE]
                embeddings, tokens = client.embed_batch(batch_texts)
                all_embeddings.extend(embeddings)
                total_tokens += tokens
                APIUsage.objects.create(
                    service=APIUsage.Service.EMBEDDING,
                    api_type=APIUsage.APIType.EMBEDDING,
                    model=EMBEDDING_MODEL,
                    prompt_tokens=tokens,
                    completion_tokens=0,
                    total_tokens=tokens,
                    cost_usd=calculate_cost(EMBEDDING_MODEL, tokens),
                )
        except Exception as e:
            logger.warning("Embed failed for article %s: %s", article.id, e)
            return False

        chunk_objects = [
            ArticleChunk(
                article_id=article.id,
                chunk_index=idx,
                chunk_text=text,
                embedding=emb,
                model=EMBEDDING_MODEL,
            )
            for idx, (text, emb) in enumerate(zip(chunks, all_embeddings))
        ]
        ArticleChunk.objects.bulk_create(chunk_objects, ignore_conflicts=True)
        logger.info("Embedded article %s (%d chunks, %d tokens)", article.id, len(chunks), total_tokens)
        return article.id

    # ------------------------------------------------------------------
    # Stages 2 & 4: Download one image (OG or RSS)
    # ------------------------------------------------------------------

    def _download_image(self, source_slug: str, pipeline_field: str,
                        **extra_filters) -> bool:
        """Download one pending image for the given source type.

        Args:
            source_slug: "og-image" or "rss-image".
            pipeline_field: ArticlePipeline field to timestamp on success.
            **extra_filters: additional queryset filters (e.g. content_extracted check).
        """
        qs = ArticleImage.objects.filter(
            downloaded=False,
            source__slug=source_slug,
            article__published__gte=_cutoff_days(),
            **extra_filters,
        )

        candidates = list(
            qs.values_list("id", "source_url", "article_id")
            .order_by("?")[:CANDIDATE_POOL]
        )
        if not candidates:
            return False

        for img_id, source_url, article_id in candidates:
            domain = get_domain(source_url)
            if not acquire_domain(domain):
                continue

            try:
                result = download_and_resize(source_url)
                save_image_result(img_id, result)
                if source_slug == "og-image":
                    select_primary_image(article_id)
                ArticlePipeline.objects.filter(article_id=article_id).update(
                    **{pipeline_field: timezone.now()},
                )
                logger.info("Downloaded %s %s from %s", source_slug, img_id, domain)
            finally:
                release_domain(domain)
            return article_id

        return False

    # ------------------------------------------------------------------
    # Stage 3: Extract content for one article
    # ------------------------------------------------------------------

    def _extract_one(self) -> bool:
        candidates = list(
            Article.objects
            .filter(pipeline__content_extracted_at__isnull=True)
            .filter(Q(published__gte=_cutoff_days()) | Q(published__isnull=True))
            .exclude(url="")
            .values_list("id", "url")
            .order_by("?")[:CANDIDATE_POOL]
        )
        if not candidates:
            return False

        for aid, url in candidates:
            domain = get_domain(url)
            if not acquire_domain(domain):
                continue

            try:
                article_id, clean_text, og_image, content_images, _err_cat, _err_msg = (
                    fetch_and_extract(aid, url)
                )
                self._save_extract_result(
                    article_id, clean_text, og_image, content_images,
                )
                logger.info("Extracted article %s from %s", article_id, domain)
            finally:
                release_domain(domain)
            return aid

        return False

    # ------------------------------------------------------------------
    # Stage 5 (lowest priority): Fetch one feed
    # ------------------------------------------------------------------

    def _fetch_one_feed(self) -> bool:
        cutoff = timezone.now() - timedelta(minutes=FEED_INTERVAL_MINUTES)
        candidates = list(
            Feed.objects
            .filter(enabled=True)
            .filter(Q(last_fetched__lt=cutoff) | Q(last_fetched__isnull=True))
            .values_list("id", "url", "title")
            .order_by("?")[:CANDIDATE_POOL]
        )
        if not candidates:
            return False

        for feed_id, url, title in candidates:
            domain = get_domain(url)
            if not acquire_domain(domain):
                continue

            try:
                _fid, entries, error = fetch_single_feed(feed_id, url, title)
                now = timezone.now()

                if error:
                    HarvesterFeed.objects.create(
                        feed_id=feed_id, finished_at=now,
                        status=RunStatus.ERROR, error_message=error,
                    )
                    logger.warning("Feed %s error: %s", title, error)
                else:
                    new_count, article_ids = save_articles(feed_id, entries)
                    run = HarvesterFeed.objects.create(
                        feed_id=feed_id, finished_at=now,
                        status=RunStatus.SUCCESS, new_articles=new_count,
                    )
                    if article_ids:
                        run.articles.add(*article_ids)
                    logger.info("Feed %s: %d new articles", title, new_count)

                Feed.objects.filter(id=feed_id).update(last_fetched=now)
            finally:
                release_domain(domain)
            return True

        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_og_source(self):
        if self._og_source is None:
            self._og_source, _ = ArticleImageSource.objects.get_or_create(
                slug="og-image", defaults={"name": "OG Image"},
            )
        return self._og_source

    def _save_extract_result(self, article_id, clean_text, og_image, content_images):
        if og_image:
            ArticleImage.objects.get_or_create(
                article_id=article_id,
                source_url=og_image[:2000],
                defaults={"source": self._get_og_source()},
            )

        if not ArticleImage.objects.filter(article_id=article_id).exists():
            for img_url in content_images:
                ArticleImage.objects.get_or_create(
                    article_id=article_id,
                    source_url=img_url[:2000],
                )

        if clean_text:
            Article.objects.filter(id=article_id).update(content=clean_text)

        ArticlePipeline.objects.filter(article_id=article_id).update(
            content_extracted_at=timezone.now(),
        )
