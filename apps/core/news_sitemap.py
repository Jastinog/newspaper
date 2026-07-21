from datetime import timedelta
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone, translation

from apps.feed.models import Article

PUBLICATION_NAME = "Newspaper"

# Google News sitemaps must only include articles published in the last 2 days
NEWS_MAX_AGE_DAYS = 2


def news_sitemap(request):
    cutoff = timezone.now() - timedelta(days=NEWS_MAX_AGE_DAYS)
    lang_code = settings.LANGUAGE_CODE

    articles = (
        Article.objects
        .filter(status=Article.Status.COMPLETED, published__gte=cutoff)
        .exclude(slug="")
        .order_by("-published")[:1000]
    )

    pub_name = escape(PUBLICATION_NAME)
    url_entries = []

    for article in articles:
        with translation.override(lang_code):
            loc = request.build_absolute_uri(article.get_absolute_url())
        pub_date = article.published.date().isoformat()

        url_entries.append(
            f"  <url>\n"
            f"    <loc>{escape(loc)}</loc>\n"
            f"    <news:news>\n"
            f"      <news:publication>\n"
            f"        <news:name>{pub_name}</news:name>\n"
            f"        <news:language>{lang_code}</news:language>\n"
            f"      </news:publication>\n"
            f"      <news:publication_date>{pub_date}</news:publication_date>\n"
            f"      <news:title>{escape(article.title)}</news:title>\n"
            f"    </news:news>\n"
            f"  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n'
        + "\n".join(url_entries)
        + "\n</urlset>\n"
    )

    return HttpResponse(xml, content_type="application/xml")
