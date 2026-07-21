from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.digest.models import DigestSection
from apps.feed.models import Article, Category


class StaticSitemap(Sitemap):
    i18n = True
    alternates = True
    priority = 1.0
    changefreq = "hourly"

    def items(self):
        return ["index", "feeds_list", "articles_list"]

    def location(self, item):
        return reverse(item)

    def lastmod(self, item):
        if item == "index":
            latest = (
                Article.objects
                .filter(published__isnull=False)
                .order_by("-published")
                .only("published")
                .first()
            )
            return latest.published if latest else None
        return None


class CategorySitemap(Sitemap):
    i18n = True
    alternates = True
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


class SectionSitemap(Sitemap):
    i18n = True
    alternates = True
    priority = 0.7
    changefreq = "daily"

    def items(self):
        return DigestSection.objects.filter(enabled=True)

    def lastmod(self, obj):
        latest = (
            Article.objects
            .filter(section=obj, published__isnull=False)
            .order_by("-published")
            .only("published")
            .first()
        )
        return latest.published if latest else None


class ArticleSitemap(Sitemap):
    i18n = True
    alternates = True
    limit = 5000
    priority = 0.5
    changefreq = "monthly"

    def items(self):
        return (
            Article.objects
            .filter(published__isnull=False)
            .exclude(slug="")
            .exclude(image="")
            .order_by("-published")
            .only("pk", "slug", "published")
        )

    def lastmod(self, obj):
        return obj.published


sitemaps = {
    "static": StaticSitemap,
    "categories": CategorySitemap,
    "sections": SectionSitemap,
    "articles": ArticleSitemap,
}
