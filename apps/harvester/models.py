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


class HarvesterEmbedding(HarvesterRun):
    """Tracks an embedding batch run."""

    articles_found = models.PositiveIntegerField(default=0)
    articles_embedded = models.PositiveIntegerField(default=0)
    chunks_created = models.PositiveIntegerField(default=0)
    tokens_used = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Embed {self.status} ({self.started_at:%Y-%m-%d %H:%M})"
