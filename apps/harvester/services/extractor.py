import logging
import re

import requests
from markdownify import markdownify as md
from readability import Document

logger = logging.getLogger(__name__)

TIMEOUT = 20
MAX_CONTENT_IMAGES = 3


# Error categories
ERR_TIMEOUT = "timeout"
ERR_HTTP_403 = "http_403"
ERR_HTTP_404 = "http_404"
ERR_HTTP_4XX = "http_4xx"
ERR_HTTP_5XX = "http_5xx"
ERR_TOO_SHORT = "too_short"
ERR_CONNECTION = "connection"
ERR_READABILITY = "readability"
ERR_OTHER = "other"


def _classify_error(error: Exception) -> tuple[str, str]:
    msg = str(error)

    if isinstance(error, requests.exceptions.Timeout):
        return ERR_TIMEOUT, msg
    if isinstance(error, requests.exceptions.ConnectionError):
        return ERR_CONNECTION, msg
    if isinstance(error, requests.exceptions.HTTPError):
        code = error.response.status_code if error.response is not None else 0
        if code == 403:
            return ERR_HTTP_403, f"{code} Forbidden"
        if code == 404:
            return ERR_HTTP_404, f"{code} Not Found"
        if 400 <= code < 500:
            return ERR_HTTP_4XX, f"{code} {msg}"
        if code >= 500:
            return ERR_HTTP_5XX, f"{code} {msg}"
        return ERR_OTHER, msg

    if "readability" in msg.lower() or "lxml" in msg.lower() or "parse" in msg.lower():
        return ERR_READABILITY, msg

    return ERR_OTHER, msg


def _html_to_markdown(html: str) -> str:
    text = md(
        html,
        heading_style="atx",
        bullets="-",
        escape_misc=True,
        strip=["img", "script", "style", "iframe"],
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_for_xml(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def _extract_og_image(html: str) -> str:
    match = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if match:
        return match.group(1)
    match = re.search(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        html, re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return ""


def _extract_content_images(html_content: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE):
        url = match.group(1)
        if url in seen or url.startswith("data:"):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= MAX_CONTENT_IMAGES:
            break
    return urls


def fetch_and_extract(article_id: int, url: str) -> tuple[int, str, str, list[str], str | None, str | None]:
    """Download page and extract main content.

    Returns (article_id, clean_text, og_image, content_images, error_category, error_message).
    """
    from .http import random_headers

    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=random_headers())
        resp.raise_for_status()

        html = _clean_for_xml(resp.text).strip()
        if not html:
            return article_id, "", "", [], ERR_TOO_SHORT, "Empty response body"

        og_image = _extract_og_image(html)

        doc = Document(html)
        html_content = doc.summary(html_partial=True)
        content_images = _extract_content_images(html_content)
        clean_text = _html_to_markdown(html_content)

        if len(clean_text) < 50:
            return article_id, "", og_image, content_images, ERR_TOO_SHORT, f"Content too short ({len(clean_text)} chars)"

        return article_id, clean_text, og_image, content_images, None, None
    except Exception as e:
        category, message = _classify_error(e)
        return article_id, "", "", [], category, message
