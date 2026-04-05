from django.db import models
from pgvector.django import VectorField

from apps.core.services.utils import get_translated_field


# ── Default prompts (used as defaults for DigestConfig fields) ───


DEFAULT_PROMPT_ANALYSIS = (
    "You are a news analyst. Given articles from the \"{section}\" digest section, "
    "identify {min}-{max} distinct news stories.\n\n"
    "For each story provide:\n"
    "- \"label\": brief story label (2-5 words, English)\n"
    "- \"article_ids\": array of article IDs covering this story\n"
    "- \"search_queries\": 2-3 search queries to find the most relevant articles "
    "about this specific story\n\n"
    "Return JSON with key \"stories\" containing an array of story objects."
)

DEFAULT_PROMPT_GENERATION = (
    "You are a sharp, engaging news writer. Write a punchy news item that reads like "
    "it was written by a top journalist — vivid, human, not robotic or dry.\n\n"
    "Provide for EACH language ({languages}):\n"
    '- "topic": catchy, attention-grabbing headline (4-8 words) — use active verbs, '
    "hint at impact or surprise. No generic clickbait.\n"
    '- "summary": ONE paragraph, 3-5 sentences max. Lead with what happened, '
    "add why it matters, close with what's next. Write naturally — as a person would "
    "tell a friend about this news. Use **bold** for key names and numbers. "
    "No headings, no bullet lists.\n\n"
    "Also provide:\n"
    '- "importance": integer 1-9 (1-3=minor, 4-5=notable, 6=significant, 7-9=major/breaking)\n\n'
    "For non-English languages: adapt naturally, not literal translation. "
    "Keep technical terms and acronyms in Latin form (AI, NASA, GPT, OpenAI, etc.).\n\n"
    'Return JSON: {{"en": {{"topic": ..., "summary": ...}}, "ru": {{...}}, ..., '
    '"importance": N}}'
)

DEFAULT_PROMPT_TRANSLATION = (
    "You are a professional translator. Translate the following news item "
    "from English to {language}.\n"
    "Maintain journalistic style, factual accuracy, and nuance. "
    "Adapt idioms and cultural references naturally. "
    "Do not add or remove information.\n"
    "Preserve all Markdown formatting (**bold**, etc.) and paragraph structure "
    "(blank lines between paragraphs) exactly as-is.\n"
    "Keep technical terms, abbreviations, and proper nouns in their original Latin form "
    "(e.g. AGI, AI, NASA, OpenAI, GPT, CERN — do NOT transliterate to Cyrillic).\n\n"
    "Provide:\n"
    '- "topic": translated headline \u2014 keep the catchy, attention-grabbing tone\n'
    '- "summary": translated summary (keep Markdown and paragraph breaks)\n\n'
    "Return JSON."
)


# ── Configuration ────────────────────────────────────────────────


class DigestConfig(models.Model):
    """Singleton storing all digest pipeline settings and prompts."""

    # ── LLM Model ───────────────────────────────────────────────
    chat_model = models.CharField(
        max_length=100, default="gpt-4.1-mini",
        help_text="OpenAI model for analysis, generation, and translation",
    )
    temperature = models.FloatField(
        default=0.3,
        help_text="LLM temperature (0 = deterministic, 1 = creative)",
    )

    # ── Token Limits ──────────────────────────────────────────
    max_tokens_analysis = models.PositiveIntegerField(
        default=2000, help_text="Max tokens for story analysis response",
    )
    max_tokens_generation = models.PositiveIntegerField(
        default=2500, help_text="Max tokens for item generation response (includes all languages)",
    )
    max_tokens_translation = models.PositiveIntegerField(
        default=1000, help_text="Max tokens for translation response",
    )

    # ── Article Collection ────────────────────────────────────
    hours_lookback = models.PositiveIntegerField(
        default=36, help_text="Collect articles published within this many hours",
    )
    articles_per_section = models.PositiveIntegerField(
        default=20, help_text="Max articles to collect per section",
    )
    similarity_threshold = models.FloatField(
        default=0.25,
        help_text="Cosine distance threshold (0.25 = similarity >= 0.75)",
    )
    chunks_per_query = models.PositiveIntegerField(
        default=60, help_text="Max article chunks per embedding query",
    )
    article_snippet_tokens = models.PositiveIntegerField(
        default=80, help_text="Snippet length (tokens) sent to analyzer per article",
    )

    # ── Story Refinement ──────────────────────────────────────
    context_trim_tokens = models.PositiveIntegerField(
        default=250, help_text="Article content length (tokens) sent to generator per article (~1000 chars)",
    )
    refine_search_top_k = models.PositiveIntegerField(
        default=10, help_text="Additional articles to find per refine query",
    )
    max_articles_per_story = models.PositiveIntegerField(
        default=3, help_text="Max articles sent to generator per story",
    )

    # ── Generation ────────────────────────────────────────────
    items_per_section_min = models.PositiveIntegerField(
        default=10, help_text="Min stories the analyzer should identify per section",
    )
    items_per_section_max = models.PositiveIntegerField(
        default=15, help_text="Max stories the analyzer should identify per section",
    )
    max_workers = models.PositiveIntegerField(
        default=5, help_text="Max parallel workers (for batch mode)",
    )

    # ── System Prompts (defaults managed by initdigest) ────────
    system_prompt_analysis = models.TextField(
        default="",
        help_text="Prompt for identifying stories from articles. Variables: {section}, {min}, {max}",
    )
    system_prompt_generation = models.TextField(
        default="",
        help_text="Prompt for generating topic/summary/importance from articles",
    )
    system_prompt_translation = models.TextField(
        default="",
        help_text="Prompt for translating items. Variable: {language}",
    )

    class Meta:
        verbose_name = "Digest Configuration"
        verbose_name_plural = "Digest Configuration"

    def __str__(self):
        return "Digest Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ── Sections ─────────────────────────────────────────────────────


class DigestSection(models.Model):
    """Configurable digest section (rubric) — managed via admin."""

    slug = models.SlugField(max_length=100, unique=True, default="")
    description = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    system_prompt_override = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.get_name("en")

    def get_name(self, language):
        """Get section name for a Language instance or code string. Prefetch-safe."""
        return get_translated_field(self.translations.all(), "name", language, fallback=self.slug)


class DigestSectionTranslation(models.Model):
    section = models.ForeignKey(DigestSection, on_delete=models.CASCADE, related_name="translations")
    language = models.ForeignKey("core.Language", on_delete=models.CASCADE, related_name="section_translations")
    name = models.CharField(max_length=200)

    class Meta:
        unique_together = [("section", "language")]

    def __str__(self):
        return f"{self.section.slug} [{self.language.code}]: {self.name}"


class SectionEmbedding(models.Model):
    """Search embeddings for a digest section (multiple per section for different angles)."""

    section = models.ForeignKey(DigestSection, on_delete=models.CASCADE, related_name="embeddings")
    description = models.TextField(help_text="Search query describing this angle of the section")
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["section__order"]

    def __str__(self):
        return f"{self.section.slug}: {self.description[:60]}"


# ── Digest ───────────────────────────────────────────────────────


class Digest(models.Model):
    """One digest per date. Language-specific content in DigestTranslation."""

    class Stage(models.IntegerChoices):
        PENDING = 0, "Pending"
        ANALYZED = 1, "Analyzed"
        REFINED = 2, "Refined"
        GENERATED = 3, "Generated"
        SAVED = 4, "Saved"
        DONE = 5, "Done"

    date = models.DateField(unique=True)
    stage = models.IntegerField(choices=Stage.choices, default=Stage.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["stage", "-date"]),
        ]

    def __str__(self):
        return f"Digest {self.date}"


class DigestTranslation(models.Model):
    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="translations")
    language = models.ForeignKey("core.Language", on_delete=models.CASCADE, related_name="digest_translations")

    class Meta:
        unique_together = [("digest", "language")]

    def __str__(self):
        return f"Digest {self.digest.date} [{self.language.code}]"


# ── Digest Items ─────────────────────────────────────────────────


class DigestItem(models.Model):
    """Single news story in digest. Language-specific text in DigestItemTranslation."""

    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="items", null=True)
    section = models.ForeignKey(DigestSection, on_delete=models.CASCADE, related_name="items", null=True)
    order = models.PositiveIntegerField(default=0)
    importance = models.PositiveSmallIntegerField(default=0)
    freshness = models.FloatField(default=0, db_index=True)
    image = models.ForeignKey(
        "feed.ArticleImage", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="digest_items",
    )
    articles = models.ManyToManyField("feed.Article", blank=True, related_name="digest_items")

    class Meta:
        ordering = ["section__order", "-freshness", "order"]
        indexes = [
            models.Index(fields=["digest", "-freshness"]),
        ]

    def __str__(self):
        return self.get_topic("en") or f"Item #{self.pk}"

    @property
    def best_image_url(self):
        if self.image and self.image.image:
            return self.image.image.url
        return ""

    def get_topic(self, language):
        """Get topic text for a language. Prefetch-safe."""
        return get_translated_field(self.translations.all(), "topic", language)

    def get_summary(self, language):
        """Get summary text for a language. Prefetch-safe."""
        return get_translated_field(self.translations.all(), "summary", language)


class DigestItemTranslation(models.Model):
    item = models.ForeignKey(DigestItem, on_delete=models.CASCADE, related_name="translations")
    language = models.ForeignKey("core.Language", on_delete=models.CASCADE, related_name="item_translations")
    topic = models.CharField(max_length=500)
    summary = models.TextField()

    class Meta:
        unique_together = [("item", "language")]

    def __str__(self):
        return f"{self.topic} [{self.language.code}]"


# ── Item Pipeline (per-item stage tracking) ────────────────────


class ItemPipeline(models.Model):
    """Per-item pipeline state (cf. ArticlePipeline in feed app).

    Each timestamp is NULL until that stage completes.
    Intermediate data is stored as JSON for resume capability.
    """

    item = models.OneToOneField(DigestItem, on_delete=models.CASCADE, related_name="pipeline")

    # Intermediate data
    story_label = models.CharField(max_length=200, default="")
    article_ids = models.JSONField(default=list)
    search_queries = models.JSONField(default=list)
    refined_articles = models.JSONField(default=list)

    # Stage timestamps (NULL = pending, timestamp = done)
    analyzed_at = models.DateTimeField(null=True, blank=True)
    refined_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    translated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Pipeline: {self.story_label or self.item_id}"


# ── Article Usage Tracking ──────────────────────────────────────


class ArticleUse(models.Model):
    """Tracks which articles have been used in digest items.

    CASCADE from DigestItem ensures re-runs (delete+recreate digest)
    automatically free articles for reuse.
    """

    article = models.OneToOneField(
        "feed.Article", on_delete=models.CASCADE, related_name="digest_uses",
    )
    item = models.ForeignKey(
        DigestItem, on_delete=models.CASCADE, related_name="article_uses",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Article {self.article_id} -> Item {self.item_id}"
