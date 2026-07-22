"""Seed digest sections, translations, and their embedding seeds.

Idempotent: safe to run multiple times. Uses get_or_create on slug.
Section data is loaded from JSON fixtures in apps/digest/fixtures/sections/.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.digest.models import (
    DigestSection,
    DigestSectionTranslation,
    SectionEmbedding,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "sections"


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
    help = "Seed digest sections, translations, and embeddings (idempotent)"

    def handle(self, *args, **options):
        languages = self._sync_languages()
        sections = _load_sections()
        self._sync_sections(languages, sections)
        self._sync_embeddings(sections)

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

        for data in sections:
            slug = data["slug"]
            fixture_slugs.add(slug)

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

            for lang_code, name in data["translations"].items():
                trans, t_created = DigestSectionTranslation.objects.get_or_create(
                    section=section, language=languages[lang_code],
                    defaults={"name": name},
                )
                if not t_created and trans.name != name:
                    trans.name = name
                    trans.save(update_fields=["name"])

            status = "created" if created else "updated"
            self.stdout.write(f"  [{section.order:>2}] {data['translations']['en']}: {status}")

        stale = DigestSection.objects.filter(enabled=True).exclude(slug__in=fixture_slugs)
        if stale.exists():
            names = list(stale.values_list("slug", flat=True))
            stale.update(enabled=False)
            self.stdout.write(
                self.style.WARNING(f"  Disabled {len(names)} stale sections: {', '.join(names)}")
            )

        self.stdout.write(f"Sections: {len(sections)} active")

    def _sync_embeddings(self, sections):
        """Embed each section's fixture seed phrases locally and store the vectors.

        Idempotent: a section is (re)embedded only when its stored seed-text set
        differs from the fixture — so re-running is cheap and never reloads the
        model unnecessarily. Seeds are embedded as *queries* (BGE's search-side
        instruction), since they are matched against stored document chunks.
        """
        # Only sections that actually ship seed phrases.
        wanted = {
            data["slug"]: data.get("embeddings", [])
            for data in sections
            if data.get("embeddings")
        }
        if not wanted:
            self.stdout.write("Embeddings: no seeds in fixtures — skipped")
            return

        sections_by_slug = {
            s.slug: s
            for s in DigestSection.objects.filter(slug__in=wanted.keys())
        }

        # Decide which sections need recomputing before loading the model.
        to_embed = {}
        for slug, seeds in wanted.items():
            section = sections_by_slug.get(slug)
            if not section:
                continue
            stored = set(
                SectionEmbedding.objects.filter(section=section)
                .values_list("text", flat=True)
            )
            if stored != set(seeds):
                to_embed[slug] = (section, seeds)

        if not to_embed:
            total = SectionEmbedding.objects.count()
            self.stdout.write(f"Embeddings: OK (all current, {total} seeds)")
            return

        # Import lazily so the command only pays the model-load cost when needed.
        from apps.feed.services.embed import LocalEmbedder

        embedder = LocalEmbedder.instance()
        created = 0
        for slug, (section, seeds) in to_embed.items():
            vectors = embedder.embed(seeds, is_query=True)
            SectionEmbedding.objects.filter(section=section).delete()
            SectionEmbedding.objects.bulk_create([
                SectionEmbedding(
                    section=section, text=text, embedding=vectors[i].tolist(),
                )
                for i, text in enumerate(seeds)
            ])
            created += len(seeds)
            self.stdout.write(f"  [{slug}] embedded {len(seeds)} seeds")

        self.stdout.write(f"Embeddings: {created} seeds across {len(to_embed)} sections")
