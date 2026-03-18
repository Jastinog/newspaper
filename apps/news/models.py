from django.db import models
from django.urls import reverse
from django.utils.text import slugify
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
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000, unique=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="feeds",
    )
    last_fetched = models.DateTimeField(null=True, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "title"]

    def __str__(self):
        return self.title


class Article(models.Model):
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name="articles")
    title = models.CharField(max_length=1000)
    slug = models.SlugField(max_length=300, blank=True, default="")
    url = models.URLField(max_length=2000, unique=True)
    rss_content = models.TextField(blank=True, default="")
    content = models.TextField(blank=True, default="")
    content_fetched = models.BooleanField(default=False, db_index=True)
    extract_error = models.CharField(max_length=500, blank=True, default="")
    published = models.DateTimeField(null=True, blank=True, db_index=True)
    read = models.BooleanField(default=False, db_index=True)
    starred = models.BooleanField(default=False, db_index=True)
    summary = models.TextField(blank=True, default="")
    embedded = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-published"]
        indexes = [
            models.Index(fields=["feed", "published"]),
        ]

    def __str__(self):
        return self.title or "(no title)"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:300]
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


class Digest(models.Model):
    date = models.DateField(unique=True)
    headline = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

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
    articles = models.ManyToManyField(Article, blank=True, related_name="digest_items")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.topic


class DeepDive(models.Model):
    item = models.ForeignKey(DigestItem, on_delete=models.CASCADE, related_name="deep_dives")
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
        "Digest", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="api_usages",
    )
    deep_dive = models.ForeignKey(
        "DeepDive", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="api_usages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API Usage"
        verbose_name_plural = "API Usage"

    def __str__(self):
        return f"{self.service}/{self.api_type} — {self.total_tokens} tokens (${self.cost_usd})"


class DeepDiveSource(models.Model):
    deep_dive = models.ForeignKey(DeepDive, on_delete=models.CASCADE, related_name="sources")
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    relevance = models.FloatField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"Source {self.order}: {self.article.title[:60]}"

    @property
    def relevance_pct(self):
        return round(self.relevance * 100)
