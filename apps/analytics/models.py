from django.db import models


class PageView(models.Model):
    # Request info
    path = models.CharField(max_length=2000)
    view_name = models.CharField(max_length=100, blank=True, default="")
    article = models.ForeignKey(
        "news.Article",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_views",
    )
    category = models.ForeignKey(
        "news.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_views",
    )

    # Visitor (privacy-safe)
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    session_hash = models.CharField(max_length=64, blank=True, default="")

    # User-Agent
    user_agent = models.CharField(max_length=500, blank=True, default="")
    is_bot = models.BooleanField(default=False)
    device_type = models.CharField(max_length=20, blank=True, default="")
    browser = models.CharField(max_length=50, blank=True, default="")
    os = models.CharField(max_length=50, blank=True, default="")

    # Referrer
    referrer = models.URLField(max_length=2000, blank=True, default="")
    referrer_domain = models.CharField(max_length=253, blank=True, default="")

    # Geo
    country = models.CharField(max_length=2, blank=True, default="")
    country_name = models.CharField(max_length=100, blank=True, default="")
    city = models.CharField(max_length=200, blank=True, default="")

    # Time
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp", "is_bot"]),
            models.Index(fields=["view_name", "timestamp"]),
            models.Index(fields=["article", "timestamp"]),
            models.Index(fields=["referrer_domain", "timestamp"]),
            models.Index(fields=["country", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.path} @ {self.timestamp:%Y-%m-%d %H:%M}"
