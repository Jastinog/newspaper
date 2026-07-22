from django.db import models
from pgvector.django import VectorField

from apps.core.services.utils import get_translated_field


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

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("section_detail", kwargs={"slug": self.slug})


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
