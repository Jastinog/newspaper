from datetime import date

from django.db.models import Max

from apps.news.models import Article, Digest, DigestItem, DigestSection


def _localized(value, lang: str) -> str:
    """Extract a localized string from a multilingual dict or plain value."""
    if isinstance(value, dict):
        return value.get(lang, value.get("en", ""))
    return str(value)


class DigestSaver:
    """Saves multilingual digest from parallel topic results."""

    def save(
        self,
        digest_date: date,
        topic_results: list[dict],
        headlines: dict,
        languages: list[str],
        valid_article_ids: set,
    ) -> list[Digest]:
        """Create Digest records for each language from topic results."""
        digests = []
        sorted_results = sorted(topic_results, key=lambda r: r["topic"].order)

        for lang in languages:
            Digest.objects.filter(date=digest_date, language=lang).delete()

            digest = Digest.objects.create(
                date=digest_date,
                language=lang,
                headline=headlines.get(lang, ""),
            )

            for topic_result in sorted_results:
                topic = topic_result["topic"]
                section = DigestSection.objects.create(
                    digest=digest,
                    title=topic.get_name(lang),
                    order=topic.order,
                )

                for j, item_data in enumerate(topic_result.get("items", [])):
                    try:
                        importance = max(0, min(9, int(item_data.get("importance", 0))))
                    except (TypeError, ValueError):
                        importance = 0

                    item = DigestItem.objects.create(
                        section=section,
                        topic=_localized(item_data.get("topic", {}), lang),
                        summary=_localized(item_data.get("summary", {}), lang),
                        order=j,
                        importance=importance,
                    )

                    raw_ids = item_data.get("article_ids", [])
                    linked_ids = [aid for aid in raw_ids if aid in valid_article_ids]
                    if linked_ids:
                        item.articles.set(linked_ids)
                        newest = (
                            Article.objects
                            .filter(id__in=linked_ids, published__isnull=False)
                            .aggregate(newest=Max("published"))["newest"]
                        )
                        if newest:
                            item.freshness = newest.timestamp()
                            item.save(update_fields=["freshness"])

            digests.append(digest)

        return digests
