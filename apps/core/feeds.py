from datetime import datetime, time, timezone

from django.conf import settings
from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Enclosure
from django.utils.translation import get_language, gettext_lazy as _

from apps.digest.models import Digest, DigestItem


class DigestFeed(Feed):
    """RSS feed for daily digest stories, language-aware."""

    link = "/"
    description = _("Daily AI-curated news digest from 100+ RSS sources worldwide")

    def title(self):
        return f"Newspaper — {_('Daily News Digest')}"

    def items(self):
        lang = get_language() or "en"
        digests = Digest.objects.filter(stage=Digest.Stage.DONE).order_by("-date")[:7]
        digest_ids = [d.pk for d in digests]

        items = (
            DigestItem.objects
            .filter(digest_id__in=digest_ids)
            .select_related("digest", "section")
            .prefetch_related(
                "translations", "translations__language",
                "section__translations", "section__translations__language",
            )
            .order_by("-digest__date", "-freshness")
        )

        # Filter out items without translation for current language
        result = []
        for item in items:
            item._lang = lang
            topic = item.get_topic(lang)
            summary = item.get_summary(lang)
            if topic and summary:
                item._cached_topic = topic
                item._cached_summary = summary
                result.append(item)
        return result

    def item_title(self, item):
        return item._cached_topic

    def item_description(self, item):
        return item._cached_summary

    def item_link(self, item):
        return reverse("story_detail", args=[item.pk])

    def item_pubdate(self, item):
        if item.digest:
            return datetime.combine(item.digest.date, time.min, tzinfo=timezone.utc)
        return None

    def item_categories(self, item):
        if item.section:
            name = item.section.get_name(item._lang)
            if name:
                return [name]
        return []

    def item_enclosures(self, item):
        if item.best_image_url:
            url = f"{settings.SITE_URL}{item.best_image_url}"
            return [Enclosure(url, "0", "image/jpeg")]
        return []
