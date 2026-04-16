import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import timedelta

from django.db import close_old_connections
from django.db.models import F, Q
from django.utils import timezone

from apps.feed.models import Article, Feed
from apps.harvester.models import (
    HarvesterFeed, PipelineEvent, PipelineSettings, RunStatus,
    STAGE_DOWNLOAD, STAGE_EXTRACT, STAGE_FEED,
)

from .downloader import download_article_image
from .extractor import fetch_and_extract
from .fetcher import fetch_single_feed, save_articles
from .http import get_domain
from .image_picker import pick_from_extraction
from .throttle import acquire_domain, release_domain

logger = logging.getLogger(__name__)

IDLE_SLEEP = 1
ERROR_SLEEP = 10
FEED_INTERVAL_MINUTES = 10
FEED_BATCH = 50
DOWNLOAD_BATCH = 30
EXTRACT_BATCH = 30
DAYS_LOOKBACK = 30
DEFAULT_MAX_WORKERS = 4
STAGE_DEADLINE_SEC = 30

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
    close_old_connections()
    started_at = timezone.now()
    try:
        result = fn(*args, **kwargs)
        if result:
            _record_event(stage, started_at, success=True)
        return result
    except Exception:
        logger.exception("Pipeline stage %s failed", fn.__name__)
        _record_event(stage, started_at, success=False)
        return False
    finally:
        close_old_connections()


def _cleanup_old_events():
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
    """Article-centric pipeline with three independent stages:

    fetch_feeds -> extract_content -> download_image -> COMPLETED

    Each stage runs in a worker thread and is re-submitted as soon as it
    finishes, without waiting on slower stages.
    """

    def __init__(self):
        global _instance
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
        now_mono = time.monotonic()
        if now_mono - self._last_cleanup > 300:
            self._last_cleanup = now_mono
            self._executor.submit(_cleanup_old_events)

        for stage in list(self._running):
            future = self._running[stage]
            if future.done():
                try:
                    if not future.result():
                        self._stage_idle[stage] = now_mono
                except Exception:
                    pass
                del self._running[stage]

        self._ensure_pool_size(s)

        for stage, enabled, fn in [
            (STAGE_DOWNLOAD, s.enable_image_download, self._download_images),
            (STAGE_EXTRACT, s.enable_content_extraction, self._extract_articles),
            (STAGE_FEED, s.enable_feed_fetching, self._fetch_feeds),
        ]:
            if not enabled or stage in self._running:
                continue
            if now_mono - self._stage_idle.get(stage, 0) < IDLE_SLEEP:
                continue
            self._running[stage] = self._executor.submit(_run_stage, stage, fn)
            self._stage_idle.pop(stage, None)

    # ------------------------------------------------------------------
    # Stage 1 (highest priority): download images for extracted articles
    # ------------------------------------------------------------------

    def _download_images(self) -> bool:
        candidates = list(
            Article.objects.filter(
                status=Article.Status.EXTRACTED,
                published__gte=_cutoff_days(),
            )
            .values_list("id", "image_url")
            .order_by("id")[:DOWNLOAD_BATCH]
        )
        if not candidates:
            return False

        processed = 0
        deadline = time.monotonic() + STAGE_DEADLINE_SEC
        for article_id, image_url in candidates:
            if time.monotonic() > deadline:
                break

            if not image_url:
                Article.objects.filter(id=article_id).update(status=Article.Status.COMPLETED)
                processed += 1
                continue

            domain = get_domain(image_url)
            if not acquire_domain(domain):
                continue

            try:
                download_article_image(article_id, image_url)
            finally:
                release_domain(domain)

            Article.objects.filter(id=article_id).update(status=Article.Status.COMPLETED)
            processed += 1
            logger.info("Completed article %s", article_id)

        return processed > 0

    # ------------------------------------------------------------------
    # Stage 2: Extract content, batched
    # ------------------------------------------------------------------

    def _extract_articles(self) -> bool:
        candidates = list(
            Article.objects
            .filter(status=Article.Status.PENDING)
            .filter(Q(published__gte=_cutoff_days()) | Q(published__isnull=True))
            .exclude(url="")
            .values_list("id", "url", "image_url")
            .order_by("id")[:EXTRACT_BATCH]
        )
        if not candidates:
            return False

        extracted = 0
        deadline = time.monotonic() + STAGE_DEADLINE_SEC
        for aid, url, current_image_url in candidates:
            if time.monotonic() > deadline:
                break
            domain = get_domain(url)
            if not acquire_domain(domain):
                continue

            try:
                _aid, clean_text, og_image, content_images, _err_cat, _err_msg = (
                    fetch_and_extract(aid, url)
                )
            finally:
                release_domain(domain)

            updates: dict = {"status": Article.Status.EXTRACTED}
            if clean_text:
                updates["content"] = clean_text
            if not current_image_url:
                picked = pick_from_extraction(og_image, content_images)
                if picked:
                    updates["image_url"] = picked[:2000]

            Article.objects.filter(id=aid).update(**updates)
            extracted += 1
            logger.info("Extracted article %s from %s", aid, domain)

        return extracted > 0

    # ------------------------------------------------------------------
    # Stage 3 (lowest priority): Fetch one feed
    # ------------------------------------------------------------------

    def _fetch_feeds(self) -> bool:
        cutoff = timezone.now() - timedelta(minutes=FEED_INTERVAL_MINUTES)
        candidates = list(
            Feed.objects
            .filter(enabled=True)
            .filter(Q(last_fetched__lt=cutoff) | Q(last_fetched__isnull=True))
            .values_list("id", "url", "title")
            .order_by(F("last_fetched").asc(nulls_first=True))[:FEED_BATCH]
        )
        if not candidates:
            return False

        fetched = 0
        deadline = time.monotonic() + STAGE_DEADLINE_SEC
        for feed_id, url, title in candidates:
            if time.monotonic() > deadline:
                break
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
                fetched += 1
            finally:
                release_domain(domain)

        return fetched > 0
