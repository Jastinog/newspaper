import logging
import re
from typing import NamedTuple

import requests
from markdownify import markdownify as md
from readability import Document

from apps.core.services.utils import sanitize_text
from ..http import BrowserHeaders
from .errors import ErrorClassifier

logger = logging.getLogger(__name__)


class ExtractionResult(NamedTuple):
    article_id: int
    content: str
    og_image: str
    content_images: list[str]
    error_category: str | None
    error_message: str | None


class ContentExtractor:
    """Download an article page and extract its main content as Markdown."""

    TIMEOUT = 20
    MAX_CONTENT_IMAGES = 3
    MIN_CONTENT_LENGTH = 50

    @classmethod
    def extract(cls, article_id: int, url: str) -> ExtractionResult:
        """Download the page at `url` and extract main content, image, and inline images."""
        try:
            resp = requests.get(url, timeout=cls.TIMEOUT, headers=BrowserHeaders.random())
            resp.raise_for_status()

            html = sanitize_text(resp.text).strip()
            if not html:
                return ExtractionResult(
                    article_id, "", "", [], ErrorClassifier.TOO_SHORT, "Empty response body",
                )

            og_image = cls._extract_og_image(html)

            doc = Document(html)
            html_content = doc.summary(html_partial=True)
            content_images = cls._extract_content_images(html_content)
            clean_text = cls._html_to_markdown(html_content)

            if len(clean_text) < cls.MIN_CONTENT_LENGTH:
                return ExtractionResult(
                    article_id, "", og_image, content_images,
                    ErrorClassifier.TOO_SHORT, f"Content too short ({len(clean_text)} chars)",
                )

            return ExtractionResult(article_id, clean_text, og_image, content_images, None, None)
        except Exception as e:
            category, message = ErrorClassifier.classify(e)
            return ExtractionResult(article_id, "", "", [], category, message)

    @classmethod
    def _html_to_markdown(cls, html: str) -> str:
        text = md(
            html,
            heading_style="atx",
            bullets="-",
            escape_misc=True,
            strip=["img", "script", "style", "iframe"],
        )
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
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

    @classmethod
    def _extract_content_images(cls, html_content: str) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE):
            url = match.group(1)
            if url in seen or url.startswith("data:"):
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= cls.MAX_CONTENT_IMAGES:
                break
        return urls
