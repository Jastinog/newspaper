import io
import logging
import uuid

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image

from apps.feed.models import Article
from .http import random_headers

logger = logging.getLogger(__name__)

TIMEOUT = 20
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MIN_DIMENSION = 100  # skip tracking pixels


def download_and_resize(source_url: str) -> bytes | None:
    """Download image, resize if needed, convert to WebP. Returns bytes or None."""
    try:
        resp = requests.get(source_url, timeout=TIMEOUT, headers=random_headers(), stream=True)
        resp.raise_for_status()

        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_FILE_SIZE:
            resp.close()
            return None

        chunks = []
        size = 0
        for chunk in resp.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_FILE_SIZE:
                resp.close()
                return None
            chunks.append(chunk)
        data = b"".join(chunks)

        img = Image.open(io.BytesIO(data))

        if getattr(img, "is_animated", False):
            return None

        if img.width < MIN_DIMENSION or img.height < MIN_DIMENSION:
            return None

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        max_width = getattr(settings, "IMAGE_MAX_WIDTH", 800)
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)

        quality = getattr(settings, "IMAGE_QUALITY", 85)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality)
        return buf.getvalue()

    except Exception as e:
        logger.debug("Failed to download %s: %s", source_url, e)
        return None


def download_article_image(article_id: int, source_url: str) -> bool:
    """Download image for an article and save to Article.image. Returns True on success."""
    webp_bytes = download_and_resize(source_url)
    if webp_bytes is None:
        return False

    try:
        article = Article.objects.get(id=article_id)
        article.image.save(f"{uuid.uuid4().hex}.webp", ContentFile(webp_bytes), save=True)
        return True
    except Exception as e:
        logger.warning("Failed to save image for article %s: %s", article_id, e)
        return False
