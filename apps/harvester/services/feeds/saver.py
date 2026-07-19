from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Greatest
from django.utils.text import slugify

from apps.feed.models import Article, Feed
from apps.harvester.retention import ARTICLE_RETENTION_DAYS
from .entry import FeedEntry


class _Candidate(NamedTuple):
    url: str
    title: str
    published: datetime
    content: str
    image_url: str


class ArticleSaver:
    """Turn parsed RSS entries into new Article rows.

    Skips entries that are too old, already stored (by URL or by title),
    or have no content at parse time.
    """

    @classmethod
    def save(cls, feed_id: int, entries) -> tuple[int, list[int]]:
        """Save new articles from parsed RSS entries. Returns (count, article_ids)."""
        if not entries:
            return 0, []

        candidates, max_entry_pub = cls._collect_candidates(feed_id, entries)
        cls._advance_high_water_mark(feed_id, max_entry_pub)

        if not candidates:
            return 0, []

        to_insert = cls._filter_new(candidates)
        if not to_insert:
            return 0, []

        return cls._insert(feed_id, candidates, to_insert)

    @classmethod
    def _collect_candidates(cls, feed_id, entries) -> tuple[list[_Candidate], datetime | None]:
        retention_cutoff = datetime.now(timezone.utc) - timedelta(days=ARTICLE_RETENTION_DAYS)
        hwm = (
            Feed.objects.only("last_entry_published")
            .get(pk=feed_id).last_entry_published
        )

        candidates: list[_Candidate] = []
        max_entry_pub = None
        for raw in entries:
            entry = FeedEntry(raw)
            link = entry.link
            if not link:
                continue
            published = entry.published
            if not published:
                continue
            if max_entry_pub is None or published > max_entry_pub:
                max_entry_pub = published
            if hwm is not None and published <= hwm:
                continue
            if published < retention_cutoff:
                continue
            candidates.append(_Candidate(
                url=link[:2000],
                title=entry.title[:1000],
                published=published,
                content=entry.text,
                image_url=entry.image_url[:2000],
            ))
        return candidates, max_entry_pub

    @staticmethod
    def _advance_high_water_mark(feed_id, max_entry_pub) -> None:
        if max_entry_pub is None:
            return
        Feed.objects.filter(pk=feed_id).update(
            last_entry_published=Greatest("last_entry_published", max_entry_pub),
        )

    @staticmethod
    def _filter_new(candidates: list[_Candidate]) -> list[_Candidate]:
        candidate_urls = [c.url for c in candidates]
        candidate_titles = [c.title for c in candidates if c.title]

        # One round-trip covers both dedup checks: any article matching a
        # candidate URL or title contributes to the respective set.
        existing = Article.objects.filter(
            Q(url__in=candidate_urls) | Q(title__in=candidate_titles)
        ).values_list("url", "title")
        existing_urls = {url for url, _ in existing}
        existing_titles = {title for _, title in existing}

        to_insert: list[_Candidate] = []
        seen_titles: set[str] = set()
        for c in candidates:
            if c.url in existing_urls:
                continue
            if not c.content:  # no body at parse time — skip
                continue
            if c.title:  # skip anything we already have (or saw this batch) under the same headline
                if c.title in existing_titles or c.title in seen_titles:
                    continue
                seen_titles.add(c.title)
            to_insert.append(c)
        return to_insert

    @staticmethod
    def _insert(feed_id, candidates, to_insert) -> tuple[int, list[int]]:
        candidate_urls = [c.url for c in candidates]
        articles = [
            Article(
                feed_id=feed_id,
                title=c.title,
                slug=slugify(c.title, allow_unicode=True)[:300],
                url=c.url,
                published=c.published,
                content=c.content,
                image_url=c.image_url,
                status=Article.Status.PENDING,
            )
            for c in to_insert
        ]
        with transaction.atomic():
            Article.objects.bulk_create(articles, ignore_conflicts=True)
            by_url = dict(
                Article.objects.filter(url__in=candidate_urls)
                .values_list("url", "id")
            )

        article_ids = [by_url[c.url] for c in to_insert if c.url in by_url]
        return len(article_ids), article_ids
