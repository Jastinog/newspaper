from django.db import models
from pgvector.django import VectorField


class Digest(models.Model):
    date = models.DateField()
    language = models.CharField(max_length=5, default="en", db_index=True)
    headline = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        unique_together = [("date", "language")]


    def __str__(self):
        return f"Digest {self.date}"


class DigestSection(models.Model):
    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=300)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]


    def __str__(self):
        return f"{self.digest.date} — {self.title}"


class DigestItem(models.Model):
    section = models.ForeignKey(DigestSection, on_delete=models.CASCADE, related_name="items")
    topic = models.CharField(max_length=500)
    summary = models.TextField()
    order = models.PositiveIntegerField(default=0)
    importance = models.PositiveSmallIntegerField(default=0)
    freshness = models.FloatField(default=0, db_index=True)
    image = models.ForeignKey(
        "feeds.ArticleImage", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="digest_items",
    )
    articles = models.ManyToManyField("feeds.Article", blank=True, related_name="digest_items")

    class Meta:
        ordering = ["-freshness", "order"]


    def __str__(self):
        return self.topic

    @property
    def best_image_url(self):
        if self.image and self.image.image:
            return self.image.image.url
        return ""


class DigestTopic(models.Model):
    """Configurable digest topic/rubric — managed via admin."""
    name_en = models.CharField(max_length=200)
    name_ru = models.CharField(max_length=200, blank=True, default="")
    name_uk = models.CharField(max_length=200, blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]


    def __str__(self):
        return self.name_en

    def get_name(self, lang: str) -> str:
        return getattr(self, f"name_{lang}", None) or self.name_en


class TopicEmbedding(models.Model):
    """Search embeddings for a digest topic (multiple per topic for different angles)."""
    topic = models.ForeignKey(DigestTopic, on_delete=models.CASCADE, related_name="embeddings")
    description = models.TextField(help_text="Search query describing this angle of the topic")
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["topic__order"]


    def __str__(self):
        return f"{self.topic.name_en}: {self.description[:60]}"
