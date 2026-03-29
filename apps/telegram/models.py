from django.conf import settings
from django.db import models


class TelegramChannel(models.Model):
    """Configuration for a Telegram channel where digests are posted."""

    name = models.CharField(
        max_length=200,
        help_text="Human-readable name for this channel",
    )
    bot_token = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Bot token override. Leave empty to use TELEGRAM_BOT_TOKEN from env",
    )
    chat_id = models.CharField(
        max_length=100,
        help_text="Channel ID (e.g. @mychannel or -1001234567890)",
    )
    language = models.ForeignKey(
        "core.Language",
        on_delete=models.CASCADE,
        help_text="Language for digest content posted to this channel",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Enable/disable posting to this channel",
    )
    top_n = models.PositiveIntegerField(
        default=10,
        help_text="Number of top news items to post (by importance)",
    )
    post_time = models.TimeField(
        help_text="Time of day to post the digest (server timezone)",
    )
    include_images = models.BooleanField(
        default=True,
        help_text="Include article images in posts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram Channel"
        verbose_name_plural = "Telegram Channels"

    def __str__(self):
        return f"{self.name} ({self.chat_id})"

    @property
    def effective_bot_token(self):
        return self.bot_token or settings.TELEGRAM_BOT_TOKEN


class TelegramPost(models.Model):
    """Log of posts sent to Telegram channels."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    channel = models.ForeignKey(
        TelegramChannel,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    digest = models.ForeignKey(
        "digest.Digest",
        on_delete=models.CASCADE,
        related_name="telegram_posts",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.SUCCESS,
    )
    items_posted = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("channel", "digest")]

    def __str__(self):
        return f"{self.channel.name} — {self.digest.date} ({self.status})"
