import logging

from django.db.models import Max
from django.utils import timezone

from apps.core.models import Language
from apps.feed.models import Article
from apps.digest.models import (
    ArticleUse, Digest, DigestItem, DigestItemTranslation, ItemPipeline,
)

logger = logging.getLogger(__name__)


class DigestSaver:
    """Saves digest data to database."""

    def save_item(self, digest: Digest, section, story: dict,
                  by_lang: dict, article_ids: list,
                  default_lang, target_langs=None) -> DigestItem:
        """Create a single DigestItem with all translations, pipeline, and linked articles.

        Args:
            by_lang: {"en": {"topic": str, "summary": str}, "ru": {...}, ...}
            article_ids: list of Article IDs to link to this item
        """
        item = DigestItem.objects.create(digest=digest, section=section)

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

        self.link_articles(item, article_ids)

        now = timezone.now()
        ItemPipeline.objects.create(
            item=item,
            story_label=story.get("label", ""),
            article_ids=story.get("article_ids", []),
            generated_at=now,
        )
        return item

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

    def assign_image(self, item: DigestItem, used_article_ids: set | None = None,
                     article_ids: list[int] | None = None) -> int | None:
        """Pick the cover article with a downloaded image. Returns the chosen Article ID or None."""
        if article_ids is None:
            article_ids = list(item.articles.values_list("id", flat=True))
        if not article_ids:
            return None

        qs = (
            Article.objects
            .filter(id__in=article_ids)
            .exclude(image="")
            .order_by("-published")
        )
        if used_article_ids:
            qs = qs.exclude(id__in=used_article_ids)

        cover = qs.first()
        if cover:
            item.cover_article = cover
            item.save(update_fields=["cover_article"])
            return cover.id
        return None

    def save_translations(self, digest: Digest, language: Language,
                          item_translations: list):
        """Save translations for an existing digest."""
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

    @staticmethod
    def invalidate_index_cache():
        """Clear cached index pages so the new digest is served immediately."""
        from django.conf import settings
        from django.core.cache import cache
        for lang_code, _ in settings.LANGUAGES:
            cache.delete(f"index:{lang_code}:latest")
