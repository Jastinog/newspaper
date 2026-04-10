import re

import markdown
import nh3
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

ALLOWED_TAGS = {
    "p", "br", "strong", "em", "a", "ul", "ol", "li",
    "blockquote", "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "table", "thead", "tbody", "tr", "th", "td",
}
ALLOWED_ATTRS = {"a": {"href", "title"}}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}

_MD_SYNTAX = re.compile(r"[\*_#\[\]\(\)>`~|]|^-\s", re.MULTILINE)


@register.filter(name="plain")
def plain_filter(value):
    """Strip Markdown syntax for use in plain-text contexts (snippets, meta tags)."""
    if not value:
        return ""
    return _MD_SYNTAX.sub("", value).strip()


@register.filter(name="markdown")
def markdown_filter(value):
    if not value:
        return ""
    html = markdown.markdown(value, extensions=["nl2br", "sane_lists"])
    return mark_safe(nh3.clean(
        html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS,
        url_schemes=ALLOWED_URL_SCHEMES,
    ))
