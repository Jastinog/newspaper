import logging

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.models import Language
from apps.feed.models import Article, ArticleImage
from apps.digest.models import (
    ArticleUse, Digest, DigestItem, DigestItemTranslation, DigestTranslation, ItemPipeline,
)

logger = logging.getLogger(__name__)


class DigestSaver:
    """Saves digest data to database."""

    def save_item(self, digest: Digest, section, story: dict, item_data: dict,
                  refined: list, default_lang) -> DigestItem:
        """Create a single DigestItem with translation, pipeline, and linked articles."""
        try:
            importance = max(0, min(9, int(item_data.get("importance", 0))))
        except (TypeError, ValueError):
            importance = 0

        item = DigestItem.objects.create(
            digest=digest, section=section, importance=importance,
        )
        DigestItemTranslation.objects.create(
            item=item, language=default_lang,
            topic=item_data.get("topic", ""),
            summary=item_data.get("summary", ""),
        )
        self.link_articles(item, item_data.get("article_ids", []))

        ItemPipeline.objects.create(
            item=item,
            story_label=story.get("label", ""),
            article_ids=story.get("article_ids", []),
            search_queries=story.get("search_queries", []),
            refined_articles=refined,
            analyzed_at=timezone.now(),
            refined_at=timezone.now(),
            generated_at=timezone.now(),
        )
        return item

    def save(self, digest: Digest, section_items: list, headline: str) -> Digest:
        """Create items for an existing digest (atomic).

        Clears any existing items first (idempotent re-run).
        """
        default_lang = Language.default()
        if not default_lang:
            raise RuntimeError("No default language set. Run initdigest first.")

        with transaction.atomic():
            digest.items.all().delete()
            digest.translations.all().delete()

            if headline:
                DigestTranslation.objects.create(
                    digest=digest, language=default_lang, headline=headline,
                )

            order = 0
            for section, items in section_items:
                for item_data in items:
                    try:
                        importance = max(0, min(9, int(item_data.get("importance", 0))))
                    except (TypeError, ValueError):
                        importance = 0

                    item = DigestItem.objects.create(
                        digest=digest, section=section,
                        order=order, importance=importance,
                    )
                    DigestItemTranslation.objects.create(
                        item=item, language=default_lang,
                        topic=item_data.get("topic", ""),
                        summary=item_data.get("summary", ""),
                    )
                    self.link_articles(item, item_data.get("article_ids", []))
                    order += 1

        item_count = digest.items.count()
        logger.info("Saved digest %s: %d items", digest.date, item_count)
        return digest

    def link_articles(self, item: DigestItem, raw_article_ids: list):
        """Link articles to an item, set best image and freshness."""
        valid_ids = list(
            Article.objects.filter(id__in=raw_article_ids).values_list("id", flat=True)
        )
        if not valid_ids:
            return

        item.articles.set(valid_ids)

        ArticleUse.objects.bulk_create(
            [ArticleUse(article_id=aid, item=item) for aid in valid_ids],
            ignore_conflicts=True,
        )

        local_image = (
            ArticleImage.objects
            .filter(article_id__in=valid_ids, downloaded=True)
            .exclude(image="")
            .select_related("article")
            .order_by("-is_primary", "-article__published")
            .first()
        )

        newest_published = (
            Article.objects
            .filter(id__in=valid_ids, published__isnull=False)
            .aggregate(newest=Max("published"))["newest"]
        )

        update_fields = []
        if local_image:
            item.image = local_image
            update_fields.append("image")
        if newest_published:
            item.freshness = newest_published.timestamp()
            update_fields.append("freshness")
        if update_fields:
            item.save(update_fields=update_fields)

    def save_translations(self, digest: Digest, language: Language,
                          item_translations: list, headline: str):
        """Save translations for an existing digest."""
        if headline:
            DigestTranslation.objects.update_or_create(
                digest=digest, language=language,
                defaults={"headline": headline},
            )

        for item, translated in item_translations:
            DigestItemTranslation.objects.update_or_create(
                item=item, language=language,
                defaults={
                    "topic": translated.get("topic", ""),
                    "summary": translated.get("summary", ""),
                },
            )

        logger.info("Saved %s translations for digest %s: %d items",
                     language.code, digest.date, len(item_translations))
