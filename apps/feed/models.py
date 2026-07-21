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


class Topic(models.Model):
    """A content-level topic (Politics, Technology, Sport…). Unlike Category —
    which is fixed per source — an Article is assigned Topics from its own text
    by the classifier, so one article can carry several (multi-label)."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("topic_detail", kwargs={"slug": self.slug})


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


class HiddenFeed(models.Model):
    """A source a curator has hidden from the home feed.

    The site currently has a single curator (the owner), so hiding is global —
    the presence of a row excludes this feed's articles from the home feed for
    every visitor. It does not stop harvesting or hide the source from other
    surfaces (its own page, search, etc.). Delete the row (in the admin) to unhide.
    """

    feed = models.OneToOneField(Feed, on_delete=models.CASCADE, related_name="hidden")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"hidden: {self.feed.title}"


class Article(models.Model):
    class Status(models.IntegerChoices):
        PENDING = 0, "Pending"
        EXTRACTED = 1, "Extracted"
        COMPLETED = 2, "Completed"  # terminal: fetched, extracted, image done

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
    used_in_digest = models.BooleanField(default=False, db_index=True)

    topics = models.ManyToManyField(
        Topic, through="ArticleTopic", related_name="articles", blank=True,
    )
    # Enrichment flag: set once the classifier has run (or been skipped) for this
    # article. Kept separate from `status` so classification never gates the
    # article's terminal state — a completed article shows even if untagged.
    classified = models.BooleanField(default=False, db_index=True)
    # Enrichment flag: set once the local embedder has run (or been skipped) for
    # this article. Like `classified`, kept separate from `status` so embedding
    # never gates the article's terminal state.
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
            self.slug = slugify(self.title, allow_unicode=True)[:300]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        if self.slug:
            return reverse("article_detail", kwargs={"pk": self.pk, "slug": self.slug})
        return reverse("article_detail_redirect", kwargs={"pk": self.pk})


class ArticleTopic(models.Model):
    """One (article, topic) assignment with the classifier's confidence.

    We store every topic scoring above a low floor and decide the *display*
    threshold at query time, so sensitivity can be tuned without re-classifying.
    The article's primary topic is simply the row with the highest score.
    """

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="article_topics")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="article_topics")
    score = models.FloatField()

    class Meta:
        unique_together = [("article", "topic")]
        indexes = [
            models.Index(fields=["topic", "score"]),  # topic-detail: filter topic + score >= t
        ]

    def __str__(self):
        return f"{self.topic_id} @ {self.score:.2f} on article {self.article_id}"


class ArticleSummary(models.Model):
    """AI retelling of an article: the essence without fluff, staying close to the
    original, plus a short conclusion. Generated once per (article, language) on
    demand and cached here so we never spend tokens on the same pair twice."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="summaries")
    language = models.ForeignKey(
        "core.Language", on_delete=models.CASCADE, related_name="article_summaries", null=True
    )
    summary = models.TextField()
    conclusion = models.TextField(blank=True, default="")
    model = models.CharField(max_length=100)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("article", "language")]

    @classmethod
    def get_for(cls, article, language):
        """Return the summary for (article, language), or None. `article` may be a
        model instance or a pk; `language` a Language instance (None → no match)."""
        if not language:
            return None
        return cls.objects.filter(article=article, language=language).first()

    def __str__(self):
        code = self.language.code if self.language_id else "?"
        return f"{code} summary of article {self.article_id}"


class ArticleChunk(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    chunk_text = models.TextField()
    embedding = VectorField(dimensions=384)
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
