from django import template

from apps.core.services.utils import get_article_image_url
from apps.feed.services.summary_guard import make_summary_token

register = template.Library()


@register.simple_tag
def summary_token(article_id):
    """Signed token embedded in an article card so the WS summary request can
    prove the card was rendered by us for this article."""
    return make_summary_token(article_id)


@register.filter
def truncatechars_word(value, length):
    """Truncate to at most `length` chars, breaking at the last word boundary."""
    if not value:
        return ""
    length = int(length)
    if len(value) <= length:
        return value
    truncated = value[:length].rsplit(" ", 1)[0]
    return truncated + "\u2026"


@register.inclusion_tag("news/_sources.html")
def sources_panel(item):
    """Provide article-level source data for the sources modal."""
    articles = []
    for article in item.articles.all():
        articles.append({
            "title": article.title,
            "url": article.url,
            "feed_title": article.feed.title,
            "feed_website": article.feed.website or article.feed.url,
            "image_url": get_article_image_url(article),
        })

    return {
        "total": len(articles),
        "source_articles": articles,
        "item_id": item.id,
    }
