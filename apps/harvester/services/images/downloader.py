import io
import logging
import uuid

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image

from apps.feed.models import Article
from ..http import BrowserHeaders

logger = logging.getLogger(__name__)


class ImageDownloader:
    """Download an article image and store it as WebP on the Article.

    Produces two renditions: the full-size `image` (IMAGE_MAX_WIDTH, for the
    article detail hero) and a lighter `thumbnail` (IMAGE_THUMB_WIDTH, for the
    card grid). Both are downscale-only — smaller sources are kept as-is.
    """

    TIMEOUT = 20
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    MIN_DIMENSION = 100  # skip tracking pixels

    @staticmethod
    def _encode_webp(img, max_width: int, quality: int) -> bytes:
        """Downscale `img` to at most `max_width` and return WebP bytes."""
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality)
        return buf.getvalue()

    @classmethod
    def encode_thumbnail(cls, img) -> bytes:
        """Encode a PIL image as the card thumbnail WebP rendition.

        The single home for the thumbnail recipe (mode-normalize + settings +
        encode), shared by the download path and the backfill command.
        """
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return cls._encode_webp(
            img,
            getattr(settings, "IMAGE_THUMB_WIDTH", 512),
            getattr(settings, "IMAGE_THUMB_QUALITY", 80),
        )

    @classmethod
    def download_renditions(cls, source_url: str) -> tuple[bytes, bytes] | None:
        """Download an image and return (full_webp, thumb_webp), or None on failure."""
        try:
            resp = requests.get(
                source_url, timeout=cls.TIMEOUT,
                headers=BrowserHeaders.random(), stream=True,
            )
            resp.raise_for_status()

            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > cls.MAX_FILE_SIZE:
                resp.close()
                return None

            chunks = []
            size = 0
            for chunk in resp.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > cls.MAX_FILE_SIZE:
                    resp.close()
                    return None
                chunks.append(chunk)
            data = b"".join(chunks)

            img = Image.open(io.BytesIO(data))

            if getattr(img, "is_animated", False):
                return None

            if img.width < cls.MIN_DIMENSION or img.height < cls.MIN_DIMENSION:
                return None

            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            full = cls._encode_webp(
                img,
                getattr(settings, "IMAGE_MAX_WIDTH", 800),
                getattr(settings, "IMAGE_QUALITY", 85),
            )
            thumb = cls.encode_thumbnail(img)
            return full, thumb

        except Exception as e:
            logger.debug("Failed to download %s: %s", source_url, e)
            return None

    @classmethod
    def download_to_article(cls, article_id: int, source_url: str) -> bool:
        """Download an image and save both renditions to the Article. True on success."""
        renditions = cls.download_renditions(source_url)
        if renditions is None:
            return False
        full_bytes, thumb_bytes = renditions

        try:
            article = Article.objects.get(id=article_id)
            name = uuid.uuid4().hex
            article.image.save(f"{name}.webp", ContentFile(full_bytes), save=False)
            article.thumbnail.save(f"{name}.webp", ContentFile(thumb_bytes), save=False)
            article.save(update_fields=["image", "thumbnail"])
            return True
        except Exception as e:
            logger.warning("Failed to save image for article %s: %s", article_id, e)
            return False
