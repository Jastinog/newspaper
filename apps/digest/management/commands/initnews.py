"""Seed digest sections, embeddings, translations, and config.

Idempotent: safe to run multiple times. Uses get_or_create on slug.
Generates embeddings for any SectionEmbedding entries missing vectors.
"""

from django.core.management.base import BaseCommand

from apps.core.models import Language
from apps.core.services.ai import EmbeddingClient
from apps.digest.models import (
    DigestConfig, DigestSection, DigestSectionTranslation, SectionEmbedding,
)
from apps.digest.sections import LANGUAGES, SECTIONS


class Command(BaseCommand):
    help = "Seed digest sections, embeddings, translations, and config (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-embed",
            action="store_true",
            help="Skip embedding generation (create section structure only)",
        )

    def handle(self, *args, **options):
        DigestConfig.get()
        self.stdout.write("DigestConfig: OK")

        languages = {}
        for code, name, default in LANGUAGES:
            lang, _ = Language.objects.get_or_create(code=code, defaults={"name": name})
            if default and not lang.is_default:
                lang.is_default = True
                lang.save(update_fields=["is_default"])
            languages[code] = lang

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

        if options["no_embed"]:
            self.stdout.write("Skipping embedding generation (--no-embed)")
            return

        pending = list(SectionEmbedding.objects.filter(embedding__isnull=True))
        if not pending:
            self.stdout.write("All embeddings already generated.")
            return

        self.stdout.write(f"Generating {len(pending)} embeddings...")
        client = EmbeddingClient()
        batch_size = 20

        for i in range(0, len(pending), batch_size):
            batch = pending[i:i + batch_size]
            vectors, tokens = client.embed_batch([e.description for e in batch])
            for emb_obj, vector in zip(batch, vectors):
                emb_obj.embedding = vector
                emb_obj.save(update_fields=["embedding"])
            self.stdout.write(f"  Batch {i // batch_size + 1}: {len(batch)} embeddings, {tokens} tokens")

        self.stdout.write(self.style.SUCCESS(f"Done! {len(pending)} embeddings generated."))
