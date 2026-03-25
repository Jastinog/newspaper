import logging
import time
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.billing.models import APIUsage
from apps.core.services.ai import EMBEDDING_MODEL, EmbeddingClient, calculate_cost
from apps.core.services.ai.embeddings import BATCH_SIZE
from apps.feed.models import Article, ArticleChunk, ArticleImage, ArticleImageSource, ArticlePipeline, Feed
from apps.harvester.models import HarvesterFeed, PipelineSettings, RunStatus

from .chunker import chunk_text
from .downloader import download_and_resize, save_image_result, select_primary_image
from .extractor import fetch_and_extract
from .fetcher import fetch_single_feed, save_articles
from .http import get_domain
from .throttle import acquire_domain, release_domain

logger = logging.getLogger(__name__)

IDLE_SLEEP = 5
WORK_SLEEP = 0.5
ERROR_SLEEP = 10
FEED_INTERVAL_MINUTES = 10
CANDIDATE_POOL = 30
DAYS_LOOKBACK = 30

_instance: "HarvestManager | None" = None


def get_manager() -> "HarvestManager | None":
    return _instance


def _cutoff_days():
    return timezone.now() - timedelta(days=DAYS_LOOKBACK)


class HarvestManager:
    """Article-centric pipeline that processes one unit of work at a time.

    Pipeline per article:
      fetch -> download RSS image -> extract content -> download OG image -> embed -> completed

    Priority order (finish articles before starting new ones):
      1. embed         -- no domain needed, finishes the article
      2. download OG   -- after content extracted
      3. extract       -- advances fresh articles
      4. download RSS  -- right after fetch
      5. fetch feed    -- brings new articles into the pipeline
    """

    def __init__(self):
        global _instance
        self._og_source = None
        _instance = self

    @property
    def is_active(self) -> bool:
        return PipelineSettings.load().is_active

    def run(self):
        logger.info("HarvestManager started")
        while True:
            try:
                if not self.is_active:
                    time.sleep(IDLE_SLEEP)
                    continue
                did_work = self.dispatch()
                time.sleep(WORK_SLEEP if did_work else IDLE_SLEEP)
            except Exception:
                logger.exception("HarvestManager error")
                time.sleep(ERROR_SLEEP)

    def dispatch(self) -> bool:
        s = PipelineSettings.load()
        return (
            (s.enable_embedding and self._embed_one())
            or (s.enable_og_image_download and self._download_image(
                "og-image", "og_images_at",
                article__pipeline__content_extracted_at__isnull=False))
            or (s.enable_content_extraction and self._extract_one())
            or (s.enable_rss_image_download and self._download_image(
                "rss-image", "rss_images_at"))
            or (s.enable_feed_fetching and self._fetch_one_feed())
        )

    # ------------------------------------------------------------------
    # Stage 1 (highest priority): Embed one article -> mark completed
    # ------------------------------------------------------------------

    def _embed_one(self) -> bool:
        row = (
            Article.objects
            .filter(pipeline__embedded_at__isnull=True)
            .exclude(content="")
            .values_list("id", "title", "content")
            .first()
        )
        if not row:
            return False

        article_id, title, content = row
        chunks = chunk_text(title, content)
        now = timezone.now()

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
            logger.warning("Embed failed for article %s: %s", article_id, e)
            ArticlePipeline.objects.filter(article_id=article_id).update(
                embedded_at=now, completed_at=now,
            )
            return True

        chunk_objects = [
            ArticleChunk(
                article_id=article_id,
                chunk_index=idx,
                chunk_text=text,
                embedding=emb,
                model=EMBEDDING_MODEL,
            )
            for idx, (text, emb) in enumerate(zip(chunks, all_embeddings))
        ]
        ArticleChunk.objects.bulk_create(chunk_objects, ignore_conflicts=True)
        ArticlePipeline.objects.filter(article_id=article_id).update(
            embedded_at=now, completed_at=now,
        )
        logger.info("Embedded article %s (%d chunks, %d tokens)", article_id, len(chunks), total_tokens)
        return True

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
            return True

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
            .values_list("id", "url", "rss_content")
            .order_by("?")[:CANDIDATE_POOL]
        )
        if not candidates:
            return False

        for aid, url, rss_content in candidates:
            domain = get_domain(url)
            if not acquire_domain(domain):
                continue

            try:
                article_id, clean_text, og_image, content_images, err_cat, _err_msg = (
                    fetch_and_extract(aid, url)
                )
                self._save_extract_result(
                    article_id, clean_text, og_image, content_images,
                    err_cat, rss_content,
                )
                logger.info("Extracted article %s from %s", article_id, domain)
            finally:
                release_domain(domain)
            return True

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

    def _save_extract_result(self, article_id, clean_text, og_image, content_images,
                             err_cat, rss_content):
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

        if err_cat:
            use_fallback = rss_content and len(rss_content) >= 50
            content = rss_content if use_fallback else ""
            Article.objects.filter(id=article_id).update(content=content)
        else:
            Article.objects.filter(id=article_id).update(content=clean_text)

        ArticlePipeline.objects.filter(article_id=article_id).update(
            content_extracted_at=timezone.now(),
        )
