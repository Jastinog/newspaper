import logging
from datetime import date

from django.db.models import Max

from apps.core.models import Language
from apps.feed.models import Article, ArticleImage
from apps.digest.models import (
    Digest, DigestItem, DigestItemTranslation, DigestTranslation,
)

logger = logging.getLogger(__name__)


class DigestSaver:
    """Saves digest data to database."""

    def save(self, digest_date: date, section_items: list, headline: str) -> Digest:
        """Create or replace digest for the given date.

        Args:
            digest_date: The date of the digest
            section_items: [(DigestSection, [item_data_dict])] where each item_data has
                         topic, summary, importance, article_ids
            headline: Headline text in default language

        Returns:
            The created Digest instance
        """
        default_lang = Language.default()
        if not default_lang:
            raise RuntimeError("No default language set. Run initnews first.")

        # Delete existing digest for this date
        Digest.objects.filter(date=digest_date).delete()

        # Create digest
        digest = Digest.objects.create(date=digest_date)

        # Save headline translation
        if headline:
            DigestTranslation.objects.create(
                digest=digest,
                language=default_lang,
                headline=headline,
            )

        # Collect all valid article IDs for validation
        all_article_ids = set()
        for _, items in section_items:
            for item_data in items:
                all_article_ids.update(item_data.get("article_ids", []))

        valid_article_ids = set(
            Article.objects.filter(id__in=all_article_ids).values_list("id", flat=True)
        )

        # Save items grouped by section
        order = 0
        for section, items in section_items:
            for item_data in items:
                try:
                    importance = max(0, min(9, int(item_data.get("importance", 0))))
                except (TypeError, ValueError):
                    importance = 0

                item = DigestItem.objects.create(
                    digest=digest,
                    section=section,
                    order=order,
                    importance=importance,
                )

                # Save default language translation
                DigestItemTranslation.objects.create(
                    item=item,
                    language=default_lang,
                    topic=item_data.get("topic", ""),
                    summary=item_data.get("summary", ""),
                )

                # Link articles
                raw_ids = item_data.get("article_ids", [])
                linked_ids = [aid for aid in raw_ids if aid in valid_article_ids]
                if linked_ids:
                    item.articles.set(linked_ids)

                    # Pick the best image
                    local_image = (
                        ArticleImage.objects
                        .filter(article_id__in=linked_ids, downloaded=True)
                        .exclude(image="")
                        .select_related("article")
                        .order_by("-is_primary", "-article__published")
                        .first()
                    )

                    # Set freshness from newest article
                    newest_published = (
                        Article.objects
                        .filter(id__in=linked_ids, published__isnull=False)
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

                order += 1

        item_count = digest.items.count()
        logger.info("Saved digest %s: %d items", digest_date, item_count)
        return digest

    def save_translations(self, digest: Digest, language: Language,
                          item_translations: list, headline: str):
        """Save translations for an existing digest.

        Args:
            digest: The Digest to add translations to
            language: Target Language
            item_translations: [(DigestItem, {"topic": str, "summary": str})]
            headline: Translated headline
        """
        # Save headline
        if headline:
            DigestTranslation.objects.update_or_create(
                digest=digest,
                language=language,
                defaults={"headline": headline},
            )

        # Save item translations
        for item, translated in item_translations:
            DigestItemTranslation.objects.update_or_create(
                item=item,
                language=language,
                defaults={
                    "topic": translated.get("topic", ""),
                    "summary": translated.get("summary", ""),
                },
            )

        logger.info("Saved %s translations for digest %s: %d items",
                     language.code, digest.date, len(item_translations))
