from django.db import models
from pgvector.django import VectorField

from apps.core.services.utils import get_translated_field


# ── Default prompts (used as defaults for DigestConfig fields) ───


DEFAULT_PROMPT_PLANNER = (
    "You are the editor-in-chief of a multilingual news digest. You receive articles "
    "published in the last 24 hours. Plan today's complete edition.\n\n"
    "Available sections:\n{sections}\n\n"
    "MANDATORY TARGET: Produce {items_per_section} stories for EACH of the {section_count} sections. "
    "Total target: {items_per_section} × {section_count} = {total} stories.\n\n"
    "For each story provide:\n"
    '- "label": brief story label (3-6 words, English)\n'
    '- "section": section slug from the list above\n'
    '- "article_ids": array of article IDs covering this story (1-3 articles)\n'
    '- "angle": one sentence — what the journalist should focus on when writing the summary\n\n'
    "Critical rules:\n"
    "- Produce many distinct stories — do NOT over-group. Only merge articles when they "
    "cover the EXACT same event (same people, same event, same day). Different angles "
    "on the same topic = DIFFERENT stories.\n"
    "- Every single-article story counts — do not discard articles just because "
    "they are the only source. A minor local story is still a story.\n"
    "- Each article can appear in at most one story\n"
    "- One real-world event = ONE story in ONE section. If the same news could fit "
    "multiple sections (e.g. an AI cybersecurity breach fits both ai-ml and "
    "cybersecurity-privacy), pick the single most specific section and group ALL "
    "related articles under that one story. Never split the same event across sections.\n"
    "- Only skip articles that are obvious spam, empty titles, or exact duplicates\n"
    "- Fill every section that has any relevant articles\n"
    "- Quantity matters: aim for the full target of {total} stories\n\n"
    'Return JSON: {{"stories": [...]}}'
)

DEFAULT_PROMPT_WRITER = (
    "You are a multilingual news journalist who writes natively in each language — "
    "not translating, but thinking and composing directly in the target language.\n\n"
    "Editorial guidance: {angle}\n\n"
    "Write about this story using the articles provided.\n\n"
    "For EACH language ({languages}):\n"
    '- "topic": catchy headline (4-8 words). Each language must feel native — '
    "use idiomatic word order, phrasing, and style natural to that language's journalism. "
    "Do NOT write in English first and translate.\n"
    '- "summary": ONE paragraph, 3-5 sentences max. Lead with what happened, '
    "add why it matters, close with what's next. Write as a local journalist would. "
    "Use **bold** for key names and numbers. No headings, no bullet lists.\n\n"
    "Language-specific rules:\n"
    "- English: sharp, punchy Anglo-American news style\n"
    "- Russian: natural Russian journalistic style, avoid calques from English\n"
    "- Ukrainian: native Ukrainian phrasing, not russisms or anglicisms\n"
    "- For any other language: write as a native journalist from that region would\n\n"
    "Keep technical terms and acronyms in Latin form (AI, NASA, GPT, OpenAI, etc.).\n\n"
    "CRITICAL: You MUST return ALL requested languages. Every language key MUST be present "
    "with non-empty \"topic\" and \"summary\".\n\n"
    'Return JSON: {{"en": {{"topic": ..., "summary": ...}}, "ru": {{...}}, ...}}'
)


# ── Configuration ────────────────────────────────────────────────


class DigestConfig(models.Model):
    """Singleton storing all digest pipeline settings and prompts."""

    # ── LLM Model ───────────────────────────────────────────────
    chat_model = models.CharField(
        max_length=100, default="gpt-4.1-mini",
        help_text="Default OpenAI model (used by writer)",
    )
    planner_model = models.CharField(
        max_length=100, default="gpt-4.1",
        help_text="OpenAI model for the planner step (needs to produce many items, use full-size)",
    )
    temperature = models.FloatField(
        default=0.3,
        help_text="LLM temperature (0 = deterministic, 1 = creative)",
    )
    max_tokens_generation = models.PositiveIntegerField(
        default=4000, help_text="Max tokens for item generation response (includes all languages)",
    )
    hours_lookback = models.PositiveIntegerField(
        default=24, help_text="Collect articles published within this many hours",
    )

    # ── Embedding digest ─────────────────────────────────────
    embed_score_floor = models.FloatField(
        default=0.5,
        help_text="Minimum cosine score between an article and a section's "
                  "embedding seeds for the article to be included in that section.",
    )

    # ── Edition Settings ─────────────────────────────────────
    edition_items_per_section = models.PositiveIntegerField(
        default=10, help_text="Target stories per section",
    )
    edition_max_workers = models.PositiveIntegerField(
        default=20, help_text="Max parallel writer threads",
    )
    edition_article_card_tokens = models.PositiveIntegerField(
        default=50, help_text="Max snippet length (tokens) per article in planner context",
    )
    edition_article_body_tokens = models.PositiveIntegerField(
        default=2000, help_text="Full content length (tokens) for writer per article",
    )
    edition_max_articles_per_story = models.PositiveIntegerField(
        default=5, help_text="Max articles sent to writer per story",
    )
    edition_writer_budget_tokens = models.PositiveIntegerField(
        default=6000, help_text="Hard cap on total article content tokens per write call",
    )
    edition_planner_budget_tokens = models.PositiveIntegerField(
        default=100000,
        help_text="Total token budget for planner context. "
                  "Max articles is derived as budget // (article_card_tokens + overhead).",
    )

    # ── System Prompts (defaults managed by initdigest) ────────
    system_prompt_planner = models.TextField(
        default="",
        help_text="Editor-in-chief prompt. Variables: {sections}, {items_per_section}, {section_count}, {total}",
    )
    system_prompt_writer = models.TextField(
        default="",
        help_text="Journalist prompt. Variables: {angle}, {languages}",
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
    """One embedding seed for a section: a short descriptive phrase and its
    locally-computed vector.

    A section carries many of these (see the `embeddings` arrays in the section
    fixtures). The embedding digest treats each seed as a search *query* against
    the article-chunk vectors and assigns each article to the single section
    whose seeds it matches best — no OpenAI, no generated summaries.
    """

    section = models.ForeignKey(
        DigestSection, on_delete=models.CASCADE, related_name="embeddings",
    )
    text = models.TextField()
    embedding = VectorField(dimensions=384)

    class Meta:
        unique_together = [("section", "text")]

    def __str__(self):
        return f"{self.section.slug}: {self.text[:60]}"


# ── Digest ───────────────────────────────────────────────────────


class Digest(models.Model):
    """One digest per date. Language-specific content in DigestTranslation."""

    class Stage(models.IntegerChoices):
        PENDING = 0, "Pending"
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


# ── Digest Run (telemetry) ──────────────────────────────────────


class DigestRun(models.Model):
    """Per-digest generation run telemetry."""

    digest = models.OneToOneField(Digest, on_delete=models.CASCADE, related_name="run")
    model = models.CharField(max_length=100, default="")
    items_per_section = models.PositiveIntegerField(default=5)

    # Timing
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    # Collect step
    articles_collected = models.PositiveIntegerField(default=0)

    # Plan step
    stories_planned = models.PositiveIntegerField(default=0)
    plan_duration_ms = models.PositiveIntegerField(default=0)
    plan_input_tokens = models.PositiveIntegerField(default=0)
    plan_output_tokens = models.PositiveIntegerField(default=0)
    plan_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    # Write step (aggregate across all parallel writes)
    items_generated = models.PositiveIntegerField(default=0)
    items_failed = models.PositiveIntegerField(default=0)
    write_duration_ms = models.PositiveIntegerField(default=0)
    write_input_tokens = models.PositiveIntegerField(default=0)
    write_output_tokens = models.PositiveIntegerField(default=0)
    write_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    # Total
    total_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    class Meta:
        verbose_name = "Digest Run"

    def __str__(self):
        return f"Run for {self.digest.date} ({self.model})"


# ── Digest Items ─────────────────────────────────────────────────


class DigestItem(models.Model):
    """Single news story in digest. Language-specific text in DigestItemTranslation."""

    # Length of the article-teaser fallback used when an item has no written
    # summary (embedding digest). Consumers may re-truncate shorter.
    FALLBACK_SUMMARY_CHARS = 400

    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="items", null=True)
    section = models.ForeignKey(DigestSection, on_delete=models.PROTECT, related_name="items", null=True)
    order = models.PositiveIntegerField(default=0)
    freshness = models.FloatField(default=0, db_index=True)
    # Best cosine score between the item's article and the section's embedding
    # seeds. Drives within-section ordering for the embedding digest (0 for
    # legacy LLM-written items).
    match_score = models.FloatField(default=0, db_index=True)
    articles = models.ManyToManyField("feed.Article", blank=True, related_name="digest_items")

    class Meta:
        ordering = ["section__order", "-match_score", "-freshness", "order"]
        indexes = [
            models.Index(fields=["digest", "-freshness"]),
        ]

    def __str__(self):
        return self.get_topic("en") or f"Item #{self.pk}"

    def _primary_article(self):
        """The single article backing this item (prefetch-safe)."""
        arts = list(self.articles.all())
        return arts[0] if arts else None

    @property
    def best_image_url(self):
        for art in self.articles.all():
            if art.image:
                return art.image.url
        return ""

    def get_topic(self, language):
        """Localized topic, falling back to the linked article's title.

        The embedding digest links a single article and writes no translations,
        so the fallback lets every consumer (digest view, story page, RSS,
        Telegram) render article-backed text with no further changes."""
        val = get_translated_field(self.translations.all(), "topic", language)
        if val:
            return val
        art = self._primary_article()
        return art.title if art else ""

    def get_summary(self, language):
        """Localized summary, falling back to a clean teaser of the article."""
        val = get_translated_field(self.translations.all(), "summary", language)
        if val:
            return val
        art = self._primary_article()
        if not art or not art.content:
            return ""
        from apps.feed.templatetags.markdown_extras import teaser_filter
        return teaser_filter(art.content)[:self.FALLBACK_SUMMARY_CHARS]


class DigestItemTranslation(models.Model):
    item = models.ForeignKey(DigestItem, on_delete=models.CASCADE, related_name="translations")
    language = models.ForeignKey("core.Language", on_delete=models.CASCADE, related_name="item_translations")
    topic = models.CharField(max_length=500)
    summary = models.TextField()

    class Meta:
        unique_together = [("item", "language")]

    def __str__(self):
        return f"{self.topic} [{self.language.code}]"


# ── Item Pipeline (per-item telemetry) ────────────────────────


class ItemPipeline(models.Model):
    """Per-item pipeline state and telemetry."""

    item = models.OneToOneField(DigestItem, on_delete=models.CASCADE, related_name="pipeline")

    # Intermediate data
    story_label = models.CharField(max_length=200, default="")
    article_ids = models.JSONField(default=list)
    search_queries = models.JSONField(default=list)
    refined_articles = models.JSONField(default=list)

    # Timestamps
    analyzed_at = models.DateTimeField(null=True, blank=True)
    refined_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    translated_at = models.DateTimeField(null=True, blank=True)

    # Telemetry
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    generation_ms = models.PositiveIntegerField(default=0)
    articles_in_context = models.PositiveIntegerField(default=0)
    context_tokens = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Pipeline: {self.story_label or self.item_id}"
