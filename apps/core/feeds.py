from django.conf import settings
from django.contrib.syndication.views import Feed
from django.utils.feedgenerator import Enclosure
from django.utils.translation import gettext_lazy as _

from apps.feed.models import Article
from apps.feed.templatetags.markdown_extras import teaser_filter


class LatestArticlesFeed(Feed):
    """RSS feed of the latest news articles (the day-less replacement for the
    old daily-digest feed)."""

    link = "/"
    description = _("Latest news from 100+ RSS sources worldwide")

    def title(self):
        return f"Newspaper — {_('Latest News')}"

    def items(self):
        return (
            Article.objects
            .filter(status=Article.Status.COMPLETED, published__isnull=False)
            .exclude(slug="")
            .exclude(image="")
            .select_related("feed", "feed__category")
            .order_by("-published")[:50]
        )

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return teaser_filter(item.content) if item.content else ""

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.published

    def item_categories(self, item):
        if item.feed and item.feed.category:
            return [item.feed.category.name]
        return []

    def item_enclosures(self, item):
        if item.image:
            url = f"{settings.SITE_URL}{item.image.url}"
            return [Enclosure(url, "0", "image/jpeg")]
        return []
