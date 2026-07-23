import logging
import re
from typing import NamedTuple

import requests
import trafilatura
from markdownify import markdownify as md
from readability import Document

from apps.core.services.utils import sanitize_text
from ..http import BrowserHeaders
from .errors import ErrorClassifier

logger = logging.getLogger(__name__)

# Boilerplate lines that survive content extraction: social/newsletter CTAs,
# affiliate disclosures, and comment-widget prompts. A line is dropped if any
# pattern matches anywhere in it (markdown link text is matched as-is). Kept
# conservative — these target phrasing that never appears in real article prose.
_BOILERPLATE_LINE_RE = re.compile(
    r"""
      \bFTC:                                              # affiliate disclosure
    | affiliate\s+links?
    | \bFollow\s+(?:us|[\w.'’\- ]{1,40}?)\s+on\s+
        (?:Google\s+News|Twitter|Facebook|Instagram|X|LinkedIn|Threads|WhatsApp|YouTube)\b
    | add\s+us\s+as\s+a\s+preferred\s+source
    | You\s+must\s+confirm\s+your\s+public\s+display\s+name
    | Please\s+log\s?out\s+and\s+then\s+log\s?in\s+again
    | (?:Sign\s+up|Subscribe)\b[^\n]{0,60}?\bnewsletter\b
    | ^\s*Advertisement\s*$
    | ^\s*Share\s+(?:this|on|via)\b
    | ^\s*(?:Read|Related)\s+(?:more|stories|articles)\b[:\s]
    """,
    re.IGNORECASE | re.VERBOSE,
)


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

            # readability scopes the main-content block; we still use it for inline
            # images and as a fallback body when trafilatura comes back empty.
            doc = Document(html)
            html_content = doc.summary(html_partial=True)
            content_images = cls._extract_content_images(html_content)

            clean_text = cls._extract_with_trafilatura(html)
            if len(clean_text) < cls.MIN_CONTENT_LENGTH:
                clean_text = cls._html_to_markdown(html_content)

            clean_text = cls._strip_boilerplate(clean_text)

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
    def _extract_with_trafilatura(cls, html: str) -> str:
        """Main-content body as Markdown, with boilerplate (nav, share, related,
        comments) removed. Returns "" if trafilatura finds no usable content."""
        try:
            text = trafilatura.extract(
                html,
                output_format="markdown",
                include_comments=False,
                include_images=False,
                favor_precision=True,
            )
        except Exception:
            return ""
        return cls._collapse_blank_lines(text or "")

    @classmethod
    def _strip_boilerplate(cls, text: str) -> str:
        """Drop boilerplate lines (social/newsletter CTAs, affiliate disclosures,
        comment-widget prompts) that both extractors let slip into the body."""
        if not text:
            return text
        lines = [ln for ln in text.split("\n") if not _BOILERPLATE_LINE_RE.search(ln)]
        return cls._collapse_blank_lines("\n".join(lines))

    @classmethod
    def _html_to_markdown(cls, html: str) -> str:
        text = md(
            html,
            heading_style="atx",
            bullets="-",
            escape_misc=True,
            strip=["img", "script", "style", "iframe"],
        )
        return cls._collapse_blank_lines(text)

    @staticmethod
    def _collapse_blank_lines(text: str) -> str:
        """Squash runs of 3+ newlines to a paragraph break and trim the ends."""
        return re.sub(r"\n{3,}", "\n\n", text).strip()

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
