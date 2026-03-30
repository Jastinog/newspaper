import re

from django import template

from apps.core.services.utils import get_article_image_url

register = template.Library()


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


@register.filter
def strip_markdown(value):
    """Strip markdown formatting, returning plain text."""
    if not value:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"^[-*+] ", "", text, flags=re.MULTILINE)
    return text.strip()


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
