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

    def save_item(self, digest: Digest, section, story: dict,
                  by_lang: dict, common_data: dict,
                  refined: list, default_lang, target_langs=None) -> DigestItem:
        """Create a single DigestItem with all translations, pipeline, and linked articles.

        Args:
            by_lang: {"en": {"topic": str, "summary": str}, "ru": {...}, ...}
            common_data: {"importance": int, "article_ids": [int]}
        """
        try:
            importance = max(0, min(9, int(common_data.get("importance", 0))))
        except (TypeError, ValueError):
            importance = 0

        item = DigestItem.objects.create(
            digest=digest, section=section, importance=importance,
        )

        translations = []
        all_languages = [default_lang] + list(target_langs or [])
        for lang in all_languages:
            lang_data = by_lang.get(lang.code, {})
            if lang_data:
                translations.append(DigestItemTranslation(
                    item=item, language=lang,
                    topic=lang_data.get("topic", ""),
                    summary=lang_data.get("summary", ""),
                ))
        if translations:
            DigestItemTranslation.objects.bulk_create(translations)

        self.link_articles(item, common_data.get("article_ids", []))

        ItemPipeline.objects.create(
            item=item,
            story_label=story.get("label", ""),
            article_ids=story.get("article_ids", []),
            search_queries=story.get("search_queries", []),
            refined_articles=refined,
            analyzed_at=timezone.now(),
            refined_at=timezone.now(),
            generated_at=timezone.now(),
            translated_at=timezone.now(),
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
            used_image_ids = set()
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
                    valid_ids = self.link_articles(item, item_data.get("article_ids", []))
                    image_id = self.assign_image(item, used_image_ids, valid_ids)
                    if image_id:
                        used_image_ids.add(image_id)
                    order += 1

        item_count = digest.items.count()
        logger.info("Saved digest %s: %d items", digest.date, item_count)
        return digest

    def link_articles(self, item: DigestItem, raw_article_ids: list) -> list[int]:
        """Link articles to an item and set freshness. Returns validated article IDs."""
        valid_ids = list(
            Article.objects.filter(id__in=raw_article_ids).values_list("id", flat=True)
        )
        if not valid_ids:
            return []

        item.articles.set(valid_ids)

        ArticleUse.objects.bulk_create(
            [ArticleUse(article_id=aid, item=item) for aid in valid_ids],
            ignore_conflicts=True,
        )

        newest_published = (
            Article.objects
            .filter(id__in=valid_ids, published__isnull=False)
            .aggregate(newest=Max("published"))["newest"]
        )

        if newest_published:
            item.freshness = newest_published.timestamp()
            item.save(update_fields=["freshness"])

        return valid_ids

    def assign_image(self, item: DigestItem, used_image_ids: set | None = None,
                     article_ids: list[int] | None = None) -> int | None:
        """Pick the best unused image for the item. Returns the chosen image ID or None."""
        if article_ids is None:
            article_ids = list(item.articles.values_list("id", flat=True))
        if not article_ids:
            return None

        qs = (
            ArticleImage.objects
            .filter(article_id__in=article_ids, downloaded=True)
            .exclude(image="")
            .order_by("-is_primary", "-article__published")
        )
        if used_image_ids:
            qs = qs.exclude(id__in=used_image_ids)

        local_image = qs.first()
        if local_image:
            item.image = local_image
            item.save(update_fields=["image"])
            return local_image.id
        return None

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
