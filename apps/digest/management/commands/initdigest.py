"""Seed digest sections, embeddings, translations, and config.

Idempotent: safe to run multiple times. Uses get_or_create on slug.
Generates embeddings for any SectionEmbedding entries missing vectors.
Resets DigestConfig to model defaults on every run.
"""

from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.core.services.ai import EmbeddingClient
from apps.core.services.ai.embeddings import BATCH_SIZE
from apps.digest.models import (
    DEFAULT_PROMPT_ANALYSIS, DEFAULT_PROMPT_GENERATION,
    DEFAULT_PROMPT_HEADLINE, DEFAULT_PROMPT_TRANSLATION,
    DigestConfig, DigestSection, DigestSectionTranslation, SectionEmbedding,
)
from apps.digest.sections import LANGUAGES, SECTIONS

# Canonical defaults for DigestConfig — single source of truth.
# Numeric defaults live on the model fields; prompts live here
# because they are excluded from field.default to keep migrations clean.
CONFIG_DEFAULTS = {
    "system_prompt_analysis": DEFAULT_PROMPT_ANALYSIS,
    "system_prompt_generation": DEFAULT_PROMPT_GENERATION,
    "system_prompt_headline": DEFAULT_PROMPT_HEADLINE,
    "system_prompt_translation": DEFAULT_PROMPT_TRANSLATION,
}


class Command(BaseCommand):
    help = "Seed digest sections, embeddings, translations, and config (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-embed",
            action="store_true",
            help="Skip embedding generation (create section structure only)",
        )

    def handle(self, *args, **options):
        self._sync_config()
        languages = self._sync_languages()
        self._sync_sections(languages)
        self._generate_embeddings(skip=options["no_embed"])

    def _sync_config(self):
        """Reset DigestConfig to canonical defaults (model fields + prompt constants)."""
        config = DigestConfig.get()
        updated = []

        # Numeric/simple defaults from model field definitions
        for field in config._meta.get_fields():
            if field.name in ("id", "pk") or field.name in CONFIG_DEFAULTS:
                continue
            if not hasattr(field, "default") or field.default is None:
                continue
            default = field.default() if callable(field.default) else field.default
            if getattr(config, field.name, None) != default:
                setattr(config, field.name, default)
                updated.append(field.name)

        # Prompt defaults from constants (not stored on model fields)
        for field_name, default in CONFIG_DEFAULTS.items():
            if getattr(config, field_name, None) != default:
                setattr(config, field_name, default)
                updated.append(field_name)

        if updated:
            config.save()
            self.stdout.write(f"DigestConfig: reset {len(updated)} fields: {', '.join(updated)}")
        else:
            self.stdout.write("DigestConfig: OK (all defaults current)")

    def _sync_languages(self):
        languages = {}
        for code, name, default in LANGUAGES:
            lang, _ = Language.objects.get_or_create(code=code, defaults={"name": name})
            if default and not lang.is_default:
                lang.is_default = True
                lang.save(update_fields=["is_default"])
            languages[code] = lang
        return languages

    def _sync_sections(self, languages):
        total_new = 0
        for data in SECTIONS:
            section, created = DigestSection.objects.get_or_create(
                slug=data["slug"],
                defaults={"order": data["order"], "description": data["description"]},
            )

            for lang_code, name in data["translations"].items():
                DigestSectionTranslation.objects.get_or_create(
                    section=section, language=languages[lang_code],
                    defaults={"name": name},
                )

            for desc in data["embeddings"]:
                _, emb_created = SectionEmbedding.objects.get_or_create(
                    section=section, description=desc,
                )
                if emb_created:
                    total_new += 1

            status = "created" if created else "exists"
            self.stdout.write(f"  [{section.order}] {data['translations']['en']}: {status}")

        self.stdout.write(f"Sections: {len(SECTIONS)}, new embeddings: {total_new}")

    def _generate_embeddings(self, skip=False):
        if skip:
            self.stdout.write("Skipping embedding generation (--no-embed)")
            return

        pending = list(SectionEmbedding.objects.filter(embedding__isnull=True))
        if not pending:
            self.stdout.write("All embeddings already generated.")
            return

        self.stdout.write(f"Generating {len(pending)} embeddings...")
        client = EmbeddingClient()

        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i:i + BATCH_SIZE]
            vectors, tokens = client.embed_batch([e.description for e in batch])
            for emb_obj, vector in zip(batch, vectors):
                emb_obj.embedding = vector
                emb_obj.save(update_fields=["embedding"])
            self.stdout.write(f"  Batch {i // BATCH_SIZE + 1}: {len(batch)} embeddings, {tokens} tokens")

        self.stdout.write(self.style.SUCCESS(f"Done! {len(pending)} embeddings generated."))
