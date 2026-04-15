"""Seed digest sections, translations, and config.

Idempotent: safe to run multiple times. Uses get_or_create on slug.
Section data is loaded from JSON fixtures in apps/digest/fixtures/sections/.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.digest.models import (
    DEFAULT_PROMPT_PLANNER,
    DEFAULT_PROMPT_WRITER,
    DigestConfig,
    DigestSection,
    DigestSectionTranslation,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "sections"

CONFIG_DEFAULTS = {
    "system_prompt_planner": DEFAULT_PROMPT_PLANNER,
    "system_prompt_writer": DEFAULT_PROMPT_WRITER,
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
    help = "Seed digest sections, translations, and config (idempotent)"

    def add_arguments(self, parser):
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

    def _sync_config(self, force=False):
        config = DigestConfig.get()
        updated = []

        for field in config._meta.get_fields():
            if field.name in ("id", "pk") or field.name in CONFIG_DEFAULTS:
                continue
            if not hasattr(field, "default") or field.default is None:
                continue
            default = field.default() if callable(field.default) else field.default
            if getattr(config, field.name, None) != default:
                setattr(config, field.name, default)
                updated.append(field.name)

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
