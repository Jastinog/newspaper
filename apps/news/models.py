from django.db import models
from django.urls import reverse
from django.utils.text import slugify


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
    content = models.TextField(blank=True, default="")
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
        return reverse("article_detail", kwargs={"pk": self.pk, "slug": self.slug})


class ArticleChunk(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    chunk_text = models.TextField()
    embedding = models.BinaryField()
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["article"])]
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
    summary = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    articles = models.ManyToManyField(Article, blank=True, related_name="digest_sections")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.digest.date} — {self.title}"
