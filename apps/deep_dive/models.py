from django.db import models


class DeepDive(models.Model):
    item = models.ForeignKey("digest.DigestItem", on_delete=models.CASCADE, related_name="deep_dives")
    title = models.CharField(max_length=500)
    subtitle = models.TextField(blank=True, default="")
    content = models.TextField()  # markdown
    search_queries = models.JSONField(default=list)
    chunks_used = models.PositiveIntegerField(default=0)
    generation_time_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Deep Dive"
        verbose_name_plural = "Deep Dives"


    def __str__(self):
        return f"Deep Dive: {self.title[:80]}"


class DeepDiveSource(models.Model):
    deep_dive = models.ForeignKey(DeepDive, on_delete=models.CASCADE, related_name="sources")
    article = models.ForeignKey("feeds.Article", on_delete=models.CASCADE)
    relevance = models.FloatField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]


    def __str__(self):
        return f"Source {self.order}: {self.article.title[:60]}"

    @property
    def relevance_pct(self):
        return round(self.relevance * 100)
