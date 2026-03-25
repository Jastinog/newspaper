from django.core.management.base import BaseCommand

from apps.harvester.services.updater import ArticleEmbedder


class Command(BaseCommand):
    help = "Embed unembedded articles: chunk, embed, save"

    def handle(self, *args, **options):
        embedder = ArticleEmbedder(stdout=self.stdout)
        articles, chunks, tokens = embedder.embed_new()

        self.stdout.write(self.style.SUCCESS(
            f"Embedded {articles} articles, {chunks} chunks, {tokens} tokens"
        ))
