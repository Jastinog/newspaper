"""Pick a single image URL for an article. RSS is default; OG/content is fallback."""
import re

_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def pick_from_rss_entry(entry) -> str:
    """Extract best image URL from a feedparser entry."""
    for attr in ("media_content", "media_thumbnail"):
        for m in getattr(entry, attr, None) or []:
            if url := m.get("url", ""):
                return url

    for enc in getattr(entry, "enclosures", []):
        url = enc.get("href", "") or enc.get("url", "")
        if not url:
            continue
        if "image" in enc.get("type", "") or url.lower().endswith(_IMAGE_EXTS):
            return url

    for field in ("summary", "description", "content"):
        val = getattr(entry, field, None)
        if isinstance(val, list):
            val = val[0].get("value", "") if val else ""
        if val and (m := _IMG_RE.search(str(val))):
            return m.group(1)

    return ""


def pick_from_extraction(og_image: str, content_images: list[str]) -> str:
    """Fallback: OG image first, then first inline content <img>."""
    return og_image or (content_images[0] if content_images else "")


def resolve(rss_image: str, og_image: str, content_images: list[str]) -> str:
    """RSS > OG > first content image."""
    return rss_image or pick_from_extraction(og_image, content_images)
