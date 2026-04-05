import uuid

from django.db import models


class Client(models.Model):
    """A recognized visitor device/browser. Persists across sessions via localStorage."""

    client_id = models.UUIDField(unique=True, db_index=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    # Device info (updated each session)
    device_type = models.CharField(max_length=20, blank=True, default="")
    browser = models.CharField(max_length=50, blank=True, default="")
    os = models.CharField(max_length=50, blank=True, default="")
    user_agent = models.CharField(max_length=500, blank=True, default="")

    # Privacy-safe identity
    ip_hash = models.CharField(max_length=64, blank=True, default="")

    # Geo (updated each session)
    country = models.CharField(max_length=2, blank=True, default="")
    country_name = models.CharField(max_length=100, blank=True, default="")
    city = models.CharField(max_length=200, blank=True, default="")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Bot classification
    is_bot = models.BooleanField(default=False)
    bot_name = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["-last_seen"]
        indexes = [
            models.Index(fields=["-last_seen"]),
            models.Index(fields=["is_bot", "-last_seen"]),
            models.Index(fields=["country", "-last_seen"]),
        ]

    def __str__(self):
        return f"Client {self.client_id} ({self.device_type or 'unknown'})"


class Session(models.Model):
    """One visit session = lifecycle of a WebSocket connection or HTTP request."""

    class Source(models.TextChoices):
        WEBSOCKET = "websocket", "WebSocket"
        HTTP = "http", "HTTP"

    session_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="sessions")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.WEBSOCKET)

    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # Aggregated stats (updated on each ping)
    page_count = models.PositiveIntegerField(default=0)
    active_time = models.PositiveIntegerField(default=0, help_text="Seconds of active time")
    total_scrolls = models.PositiveIntegerField(default=0)
    spm = models.FloatField(default=0, help_text="Scrolls per minute")
    pages = models.JSONField(default=list, blank=True, help_text='[{"path": "/...", "ts": "HH:MM:SS"}]')
    last_ping_at = models.DateTimeField(null=True, blank=True)

    # Referrer of the first page
    referrer = models.URLField(max_length=2000, blank=True, default="")
    referrer_domain = models.CharField(max_length=253, blank=True, default="")

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["-started_at"]),
            models.Index(fields=["client", "-started_at"]),
        ]

    def __str__(self):
        return f"Session {self.session_id} ({self.started_at:%Y-%m-%d %H:%M})"


class Activity(models.Model):
    """Individual action within a session."""

    class ActivityType(models.TextChoices):
        PAGE_VIEW = "page_view", "Page View"
        SCROLL = "scroll", "Scroll"
        CLICK = "click", "Click"
        HEARTBEAT = "heartbeat", "Heartbeat"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="activities")

    type = models.CharField(max_length=20, choices=ActivityType.choices)
    path = models.CharField(max_length=2000)
    view_name = models.CharField(max_length=100, blank=True, default="")
    article = models.ForeignKey(
        "feed.Article",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    category = models.ForeignKey(
        "feed.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["session", "-timestamp"]),
            models.Index(fields=["type", "-timestamp"]),
            models.Index(fields=["article", "-timestamp"]),
            models.Index(fields=["path", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.type} {self.path} @ {self.timestamp:%H:%M:%S}"
