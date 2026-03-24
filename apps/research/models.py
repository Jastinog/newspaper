from django.db import models


class Research(models.Model):
    item = models.ForeignKey("digest.DigestItem", on_delete=models.CASCADE, related_name="researches")
    title = models.CharField(max_length=500)
    subtitle = models.TextField(blank=True, default="")
    content = models.TextField()  # markdown
    search_queries = models.JSONField(default=list)
    chunks_used = models.PositiveIntegerField(default=0)
    generation_time_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Research"
        verbose_name_plural = "Researches"

    def __str__(self):
        return f"Research: {self.title[:80]}"


class ResearchSource(models.Model):
    research = models.ForeignKey(Research, on_delete=models.CASCADE, related_name="sources")
    article = models.ForeignKey("feed.Article", on_delete=models.CASCADE)
    relevance = models.FloatField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"Source {self.order}: {self.article.title[:60]}"

    @property
    def relevance_pct(self):
        return round(self.relevance * 100)
