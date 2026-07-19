import re
from datetime import datetime, timezone
from html import unescape

from ..images import ImagePicker


class FeedEntry:
    """A single parsed RSS entry, exposing the fields we persist as an Article."""

    _TAG_RE = re.compile(r"<[^>]+>")
    _WS_RE = re.compile(r"\s+")

    def __init__(self, entry):
        self._entry = entry

    @property
    def link(self) -> str:
        return (getattr(self._entry, "link", "") or "").strip()

    @property
    def title(self) -> str:
        return getattr(self._entry, "title", "") or ""

    @property
    def image_url(self) -> str:
        return ImagePicker.from_rss_entry(self._entry)

    @property
    def published(self) -> datetime | None:
        for date_field in ("published_parsed", "updated_parsed"):
            parsed_time = getattr(self._entry, date_field, None)
            if parsed_time:
                try:
                    return datetime(*parsed_time[:6], tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass
        return None

    @property
    def text(self) -> str:
        for field in ("summary", "description", "content"):
            val = getattr(self._entry, field, None)
            if isinstance(val, list):
                val = val[0].get("value", "") if val else ""
            if val:
                return self._strip_html(str(val))
        return ""

    @classmethod
    def _strip_html(cls, text: str) -> str:
        text = cls._TAG_RE.sub("", text)
        text = unescape(text)
        text = cls._WS_RE.sub(" ", text)
        return text.strip()
