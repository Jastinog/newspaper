from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from pgvector.django import HnswIndex, VectorField


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("category_detail", kwargs={"slug": self.slug})


class Feed(models.Model):
    class Lean(models.TextChoices):
        LEFT = "left", _("Left")
        CENTER_LEFT = "center_left", _("Center-Left")
        CENTER = "center", _("Center")
        CENTER_RIGHT = "center_right", _("Center-Right")
        RIGHT = "right", _("Right")

    class Factuality(models.TextChoices):
        HIGH = "high", "High"
        MIXED = "mixed", "Mixed"
        LOW = "low", "Low"

    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000, unique=True)
    website = models.URLField(max_length=2000, blank=True, default="")
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="feeds",
    )
    country = models.ForeignKey(
        "location.Country", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="feeds",
    )
    language = models.ForeignKey(
        "core.Language", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="feeds",
    )
    reliability = models.PositiveSmallIntegerField(default=3)
    last_fetched = models.DateTimeField(null=True, blank=True)
    last_entry_published = models.DateTimeField(null=True, blank=True, db_index=True)
    enabled = models.BooleanField(default=True)
    lean = models.CharField(max_length=20, choices=Lean.choices, blank=True, default="", db_index=True)
    factuality = models.CharField(max_length=10, choices=Factuality.choices, blank=True, default="", db_index=True)

    class Meta:
        ordering = ["category", "title"]

    def __str__(self):
        return self.title


class Article(models.Model):
    class Status(models.IntegerChoices):
        PENDING = 0, "Pending"
        EXTRACTED = 1, "Extracted"
        COMPLETED = 2, "Completed"

    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name="articles")
    title = models.CharField(max_length=1000)
    slug = models.SlugField(max_length=300, blank=True, default="")
    url = models.URLField(max_length=2000, unique=True)
    content = models.TextField(blank=True, default="")
    published = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.PositiveSmallIntegerField(
        choices=Status.choices, default=Status.PENDING, db_index=True,
    )
    image_url = models.URLField(max_length=2000, blank=True, default="")
    image = models.ImageField(upload_to="articles/%Y/%m/", blank=True)

    class Meta:
        ordering = ["-published"]
        indexes = [
            models.Index(fields=["feed", "published"]),
        ]

    def __str__(self):
        return self.title or "(no title)"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)[:300]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        if self.slug:
            return reverse("article_detail", kwargs={"pk": self.pk, "slug": self.slug})
        return reverse("article_detail_redirect", kwargs={"pk": self.pk})


class ArticleChunk(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    chunk_text = models.TextField()
    embedding = VectorField(dimensions=1536)
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["article"]),
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]
        unique_together = [("article", "chunk_index")]

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.article_id}"
