from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Article, Category, DeepDive, Digest


class StaticSitemap(Sitemap):
    """Homepage."""

    priority = 1.0
    changefreq = "hourly"

    def items(self):
        return ["index"]

    def location(self, item):
        return reverse(item)

    def lastmod(self, item):
        digest = Digest.objects.order_by("-created_at").only("created_at").first()
        return digest.created_at if digest else None


class DigestSitemap(Sitemap):
    """Daily digest pages — one URL per date."""

    priority = 0.9
    changefreq = "daily"

    def items(self):
        # One URL per date; use English digests as canonical source of dates
        return (
            Digest.objects
            .filter(language="en")
            .order_by("-date")
            .only("date", "created_at")
        )

    def location(self, obj):
        return reverse("digest_by_date", kwargs={"date": obj.date.isoformat()})

    def lastmod(self, obj):
        return obj.created_at


class CategorySitemap(Sitemap):
    """News categories."""

    priority = 0.7
    changefreq = "daily"

    def items(self):
        return Category.objects.all()

    def lastmod(self, obj):
        latest = (
            Article.objects
            .filter(feed__category=obj, published__isnull=False)
            .order_by("-published")
            .only("published")
            .first()
        )
        return latest.published if latest else None


class DeepDiveSitemap(Sitemap):
    """Deep dive analytical articles."""

    priority = 0.6
    changefreq = "never"

    def items(self):
        return DeepDive.objects.order_by("-created_at").only("item_id", "created_at")

    def location(self, obj):
        return reverse("deep_dive", kwargs={"item_id": obj.item_id})

    def lastmod(self, obj):
        return obj.created_at


class ArticleSitemap(Sitemap):
    """News articles with slugs."""

    limit = 5000
    priority = 0.5
    changefreq = "monthly"

    def items(self):
        return (
            Article.objects
            .filter(published__isnull=False)
            .exclude(slug="")
            .order_by("-published")
            .only("pk", "slug", "published")
        )

    def lastmod(self, obj):
        return obj.published


sitemaps = {
    "static": StaticSitemap,
    "digests": DigestSitemap,
    "categories": CategorySitemap,
    "deep-dives": DeepDiveSitemap,
    "articles": ArticleSitemap,
}
