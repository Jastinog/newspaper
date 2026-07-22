"""Classify a single article and persist its topics."""

import logging

from django.db import transaction

from apps.feed.models import ArticleTopic, Topic
from apps.feed.services.inference import client as inference

from .classifier import TopicClassifier

logger = logging.getLogger(__name__)


def classify_article(article_id: int, title: str, content: str = "") -> int:
    """Run the classifier for one article and store its ArticleTopic rows.

    Returns the number of topics assigned. Replaces any existing topics for the
    article, so it is safe to re-run. Raises if the classifier can't run — the
    caller decides how to handle a model failure (the harvester stage swallows
    it so the pipeline never stalls)."""
    if inference.remote_enabled():
        scored = inference.classify(title, content)
    else:
        scored = TopicClassifier.instance().classify(title, content)
    if not scored:
        return 0

    slug_to_topic = {t.slug: t for t in Topic.objects.filter(slug__in=[s for s, _ in scored])}
    rows = [
        ArticleTopic(article_id=article_id, topic=slug_to_topic[slug], score=score)
        for slug, score in scored
        if slug in slug_to_topic
    ]

    with transaction.atomic():
        ArticleTopic.objects.filter(article_id=article_id).delete()
        ArticleTopic.objects.bulk_create(rows)

    return len(rows)
