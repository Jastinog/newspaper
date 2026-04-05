"""Seed digest sections, embeddings, translations, and config.

Idempotent: safe to run multiple times. Uses get_or_create on slug.
Generates embeddings for any SectionEmbedding entries missing vectors.
Resets DigestConfig to model defaults on every run.

Section data is loaded from JSON fixtures in apps/digest/fixtures/sections/.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.core.services.ai import EmbeddingClient
from apps.core.services.ai.embeddings import BATCH_SIZE
from apps.digest.models import (
    DEFAULT_PROMPT_ANALYSIS,
    DEFAULT_PROMPT_GENERATION,
    DEFAULT_PROMPT_TRANSLATION,
    DigestConfig,
    DigestSection,
    DigestSectionTranslation,
    SectionEmbedding,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "sections"

# Canonical defaults for DigestConfig — single source of truth.
# Numeric defaults live on the model fields; prompts live here
# because they are excluded from field.default to keep migrations clean.
CONFIG_DEFAULTS = {
    "system_prompt_analysis": DEFAULT_PROMPT_ANALYSIS,
    "system_prompt_generation": DEFAULT_PROMPT_GENERATION,
    "system_prompt_translation": DEFAULT_PROMPT_TRANSLATION,
}


def _load_languages() -> list[dict]:
    with open(FIXTURES_DIR / "_languages.json") as f:
        return json.load(f)


def _load_sections() -> list[dict]:
    sections = []
    for path in sorted(FIXTURES_DIR.glob("[0-9]*.json")):
        with open(path) as f:
            sections.append(json.load(f))
    return sections


class Command(BaseCommand):
    help = "Seed digest sections, embeddings, translations, and config (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-embed",
            action="store_true",
            help="Skip embedding generation (create section structure only)",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Force-reset all config including operator-customized prompts",
        )

    def handle(self, *args, **options):
        self._sync_config(force=options["reset"])
        languages = self._sync_languages()
        sections = _load_sections()
        self._sync_sections(languages, sections)
        self._generate_embeddings(skip=options["no_embed"])

    def _sync_config(self, force=False):
        """Reset DigestConfig to canonical defaults.

        By default preserves operator-customized prompts.
        With force=True, resets everything including prompts.
        """
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

        # Prompt defaults: fill empty or force-reset all
        for field_name, default in CONFIG_DEFAULTS.items():
            current = getattr(config, field_name, "")
            if not current or (force and current != default):
                setattr(config, field_name, default)
                updated.append(field_name)

        if updated:
            config.save()
            self.stdout.write(f"DigestConfig: reset {len(updated)} fields: {', '.join(updated)}")
        else:
            self.stdout.write("DigestConfig: OK (all defaults current)")

    def _sync_languages(self):
        languages = {}
        for entry in _load_languages():
            lang, _ = Language.objects.get_or_create(
                code=entry["code"], defaults={"name": entry["name"]},
            )
            if entry.get("default") and not lang.is_default:
                lang.is_default = True
                lang.save(update_fields=["is_default"])
            languages[entry["code"]] = lang
        return languages

    def _sync_sections(self, languages, sections):
        fixture_slugs = set()
        total_new_emb = 0

        for data in sections:
            slug = data["slug"]
            fixture_slugs.add(slug)

            # Create or update section metadata
            section, created = DigestSection.objects.get_or_create(
                slug=slug,
                defaults={
                    "order": data["order"],
                    "description": data["description"],
                    "enabled": True,
                },
            )
            if not created:
                desired = {
                    "order": data["order"],
                    "description": data["description"],
                    "enabled": True,
                }
                changed = [
                    field for field, value in desired.items()
                    if getattr(section, field) != value
                ]
                if changed:
                    for field in changed:
                        setattr(section, field, desired[field])
                    section.save(update_fields=changed)

            # Upsert translations
            for lang_code, name in data["translations"].items():
                trans, t_created = DigestSectionTranslation.objects.get_or_create(
                    section=section, language=languages[lang_code],
                    defaults={"name": name},
                )
                if not t_created and trans.name != name:
                    trans.name = name
                    trans.save(update_fields=["name"])

            # Replace embeddings: delete old, bulk-create new
            old_count = section.embeddings.count()
            section.embeddings.all().delete()
            SectionEmbedding.objects.bulk_create([
                SectionEmbedding(section=section, description=desc)
                for desc in data["embeddings"]
            ])
            total_new_emb += len(data["embeddings"])

            status = "created" if created else f"updated (had {old_count} emb)"
            self.stdout.write(f"  [{section.order:>2}] {data['translations']['en']}: {status}")

        # Disable sections not in fixtures (preserve data, stop matching)
        stale = DigestSection.objects.filter(enabled=True).exclude(slug__in=fixture_slugs)
        if stale.exists():
            names = list(stale.values_list("slug", flat=True))
            stale.update(enabled=False)
            self.stdout.write(
                self.style.WARNING(f"  Disabled {len(names)} stale sections: {', '.join(names)}")
            )

        self.stdout.write(f"Sections: {len(sections)} active, {total_new_emb} embeddings to generate")

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
            SectionEmbedding.objects.bulk_update(batch, ["embedding"])
            self.stdout.write(f"  Batch {i // BATCH_SIZE + 1}: {len(batch)} embeddings, {tokens} tokens")

        self.stdout.write(self.style.SUCCESS(f"Done! {len(pending)} embeddings generated."))
