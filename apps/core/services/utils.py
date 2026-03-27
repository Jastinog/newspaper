import re


def sanitize_text(s: str) -> str:
    """Remove control characters except newline/tab, and strip surrogate chars."""
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
    # Remove Unicode surrogates that break JSON serialization
    s = re.sub(r'[\ud800-\udfff]', '', s)
    return s


def get_translated_field(translations, field: str, language, fallback=""):
    """Look up a translated field from a prefetched translations set.

    Works with prefetched querysets (iterates in Python, no extra queries).
    Falls back to the default language, then to the provided fallback value.
    """
    lang_code = language if isinstance(language, str) else language.code

    for t in translations:
        if t.language.code == lang_code:
            return getattr(t, field)

    for t in translations:
        if t.language.is_default:
            return getattr(t, field)

    return fallback


def get_article_image_url(article) -> str:
    """Get the best image URL from a prefetched article. Checks primary first, then fallback."""
    primary = None
    fallback = None
    for img in article.images.all():
        if img.image:
            if img.is_primary:
                return img.image.url
            if fallback is None:
                fallback = img.image.url
    return fallback or ""


def deduplicate_queries(queries: list[str], limit: int) -> list[str]:
    """Deduplicate queries case-insensitively, preserving order, up to limit."""
    seen = set()
    unique = []
    for q in queries:
        key = q.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:limit]
