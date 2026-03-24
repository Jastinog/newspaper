from django.db import models


class APIUsage(models.Model):
    class Service(models.TextChoices):
        DIGEST = "digest", "Digest Generation"
        DEEP_DIVE = "deep_dive", "Deep Dive"
        EMBEDDING = "embedding", "Article Embedding"

    class APIType(models.TextChoices):
        CHAT = "chat", "Chat Completion"
        EMBEDDING = "embedding", "Embedding"

    service = models.CharField(max_length=20, choices=Service.choices)
    api_type = models.CharField(max_length=20, choices=APIType.choices)
    model = models.CharField(max_length=100)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    digest = models.ForeignKey(
        "digest.Digest", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="api_usages",
    )
    deep_dive = models.ForeignKey(
        "deep_dive.DeepDive", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="api_usages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API Usage"
        verbose_name_plural = "API Usage"


    def __str__(self):
        return f"{self.service}/{self.api_type} — {self.total_tokens} tokens (${self.cost_usd})"
