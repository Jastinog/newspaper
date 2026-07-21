import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor

from apps.harvester.models import PipelineSettings
from .events import PipelineEventRecorder
from .stages import ClassifyStage, DownloadStage, EmbedStage, ExtractStage, FetchFeedsStage

logger = logging.getLogger(__name__)


class HarvestManager:
    """Article-centric pipeline with four independent stages:

    fetch_feeds -> extract_content -> download_image -> COMPLETED
                                                     -> classify (enrichment)

    download_image is the terminal transition to COMPLETED. Classification is a
    separate enrichment pass over completed-but-unclassified articles (flagged
    via `Article.classified`), so it only runs on articles that passed the
    earlier checks and disabling it never strands an article mid-pipeline. Each
    stage runs in a worker thread and is re-submitted as soon as it finishes,
    without waiting on slower stages.
    """

    IDLE_SLEEP = 1
    ERROR_SLEEP = 10
    DEFAULT_MAX_WORKERS = 4
    MAX_WORKERS = 6
    EVENT_CLEANUP_INTERVAL_SEC = 300

    _instance: "HarvestManager | None" = None

    @classmethod
    def current(cls) -> "HarvestManager | None":
        return cls._instance

    def __init__(self):
        self._current_workers = self.DEFAULT_MAX_WORKERS
        self._executor = ThreadPoolExecutor(
            max_workers=self._current_workers, thread_name_prefix="harvest",
        )
        self._last_cleanup = 0.0
        self._running: dict[str, Future] = {}
        self._stage_idle: dict[str, float] = {}
        # Highest priority first: images -> extraction -> feed fetching ->
        # classification -> embedding (last: the CPU-heavy enrichment passes).
        self._stages = [
            DownloadStage(), ExtractStage(), FetchFeedsStage(),
            ClassifyStage(), EmbedStage(),
        ]
        HarvestManager._instance = self

    @property
    def is_active(self) -> bool:
        return PipelineSettings.load().is_active

    def _enabled_stages(self, settings):
        for stage in self._stages:
            yield stage, getattr(settings, stage.enable_field)

    def _ensure_pool_size(self, settings):
        desired = max(1, min(settings.max_workers, self.MAX_WORKERS))
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
                    time.sleep(self.IDLE_SLEEP)
                    continue
                self.dispatch(s)
                delay = s.stage_delay if self._running else self.IDLE_SLEEP
                time.sleep(delay)
            except Exception:
                logger.exception("HarvestManager error")
                time.sleep(self.ERROR_SLEEP)

    def dispatch(self, s) -> None:
        now_mono = time.monotonic()
        if now_mono - self._last_cleanup > self.EVENT_CLEANUP_INTERVAL_SEC:
            self._last_cleanup = now_mono
            self._executor.submit(PipelineEventRecorder.cleanup_old)

        for stage_key in list(self._running):
            future = self._running[stage_key]
            if future.done():
                try:
                    if not future.result():
                        self._stage_idle[stage_key] = now_mono
                except Exception:
                    pass
                del self._running[stage_key]

        self._ensure_pool_size(s)

        for stage, enabled in self._enabled_stages(s):
            key = stage.stage
            if not enabled or key in self._running:
                continue
            if now_mono - self._stage_idle.get(key, 0) < self.IDLE_SLEEP:
                continue
            self._running[key] = self._executor.submit(
                PipelineEventRecorder.run_stage, key, stage.run,
            )
            self._stage_idle.pop(key, None)
