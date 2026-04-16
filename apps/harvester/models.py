import threading
import time

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class RunStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    ERROR = "error", "Error"


class HarvesterRun(models.Model):
    """Abstract base for all pipeline run tracking models."""

    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=RunStatus.choices, db_index=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        abstract = True
        ordering = ["-started_at"]

    @property
    def duration(self):
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return None


class HarvesterFeed(HarvesterRun):
    """Tracks a single RSS feed fetch attempt."""

    feed = models.ForeignKey(
        "feed.Feed", on_delete=models.CASCADE, related_name="fetch_runs",
    )
    articles = models.ManyToManyField(
        "feed.Article", blank=True, related_name="fetch_runs",
    )
    new_articles = models.PositiveIntegerField(default=0)

    class Meta(HarvesterRun.Meta):
        indexes = [
            models.Index(fields=["feed", "-started_at"]),
        ]

    def __str__(self):
        return f"{self.feed} — {self.status} ({self.started_at:%Y-%m-%d %H:%M})"


class HarvesterContent(HarvesterRun):
    """Tracks a content extraction batch run."""

    articles = models.ManyToManyField(
        "feed.Article", blank=True, related_name="extract_runs",
    )
    articles_found = models.PositiveIntegerField(default=0)
    articles_extracted = models.PositiveIntegerField(default=0)
    articles_failed = models.PositiveIntegerField(default=0)
    articles_fallback = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Extract {self.status} ({self.started_at:%Y-%m-%d %H:%M})"


class HarvesterImage(HarvesterRun):
    """Tracks an image download batch run."""

    images_found = models.PositiveIntegerField(default=0)
    images_downloaded = models.PositiveIntegerField(default=0)
    images_skipped = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Download {self.status} ({self.started_at:%Y-%m-%d %H:%M})"


class DomainThrottle(models.Model):
    """Global per-domain rate limiting shared across all pipeline stages."""

    domain = models.CharField(max_length=255, unique=True)
    last_request_at = models.DateTimeField(default=timezone.now)
    locked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.domain


class HarvesterEmbedding(HarvesterRun):
    """Tracks an embedding batch run."""

    articles_found = models.PositiveIntegerField(default=0)
    articles_embedded = models.PositiveIntegerField(default=0)
    chunks_created = models.PositiveIntegerField(default=0)
    tokens_used = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Embed {self.status} ({self.started_at:%Y-%m-%d %H:%M})"


class PipelineSettings(models.Model):
    """Singleton (pk=1): controls the entire harvester pipeline."""

    is_active = models.BooleanField(default=True, verbose_name="Pipeline active")
    max_workers = models.PositiveSmallIntegerField(
        default=2, verbose_name="Max worker threads",
        validators=[MinValueValidator(1), MaxValueValidator(6)],
        help_text="Concurrent pipeline threads (1 = sequential, 2-6 = parallel). Lower = less CPU.",
    )
    stage_delay = models.FloatField(
        default=0.5, verbose_name="Delay between tasks (sec)",
        validators=[MinValueValidator(0.05), MaxValueValidator(60.0)],
        help_text="Pause between pipeline ticks (0.05–60s). Higher = less CPU load.",
    )
    enable_feed_fetching = models.BooleanField(default=True, verbose_name="Feed fetching")
    enable_rss_image_download = models.BooleanField(default=True, verbose_name="RSS image download")
    enable_content_extraction = models.BooleanField(default=True, verbose_name="Content extraction")
    enable_og_image_download = models.BooleanField(default=True, verbose_name="OG image download")
    enable_embedding = models.BooleanField(default=True, verbose_name="Embedding")
    updated_at = models.DateTimeField(auto_now=True)

    _thread_local = threading.local()

    class Meta:
        verbose_name = "Pipeline Settings"
        verbose_name_plural = "Pipeline Settings"

    def __str__(self):
        return "Pipeline Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        self._bust_cache()

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        """Return the singleton row, creating it if needed. Cached 5s per thread."""
        now = time.monotonic()
        local = cls._thread_local
        if hasattr(local, "obj") and (now - local.ts) < 5:
            return local.obj
        obj, _ = cls.objects.get_or_create(pk=1)
        local.obj = obj
        local.ts = now
        return obj

    @classmethod
    def set_field(cls, **kwargs):
        """Update fields and bust the thread-local cache."""
        cls.objects.filter(pk=1).update(**kwargs)
        cls._bust_cache()

    @classmethod
    def _bust_cache(cls):
        cls._thread_local.__dict__.clear()


STAGE_FIELDS = [
    ("enable_feed_fetching", "Feed Fetching"),
    ("enable_rss_image_download", "RSS Images"),
    ("enable_content_extraction", "Extraction"),
    ("enable_og_image_download", "OG Images"),
]
STAGE_FIELD_NAMES = frozenset(name for name, _ in STAGE_FIELDS)


# Pipeline event stage keys — single source of truth for Python side.
STAGE_FEED = "feed"
STAGE_RSS_IMG = "rss_img"
STAGE_EXTRACT = "extract"
STAGE_OG_IMG = "og_img"
STAGE_EMBED = "embed"


class PipelineEvent(models.Model):
    """Individual pipeline stage execution for timeline visualization."""

    stage = models.CharField(max_length=20)
    article_id = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField()
    duration_ms = models.PositiveIntegerField()
    success = models.BooleanField(default=True)

    class Meta:
        ordering = ["-started_at"]
