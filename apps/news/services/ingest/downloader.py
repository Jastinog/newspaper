import hashlib
import io
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone as django_tz
from PIL import Image

from apps.news.models import ArticleImage
from apps.news.services.ingest.http import BROWSER_UA

logger = logging.getLogger(__name__)

TIMEOUT = 20
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB
MIN_DIMENSION = 100  # skip tracking pixels

HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "image/webp,image/avif,image/apng,image/*,*/*;q=0.8",
}


def _download_and_resize(source_url: str) -> tuple[bytes, int, int] | None:
    """Download image, resize if needed, convert to WebP.

    Returns (webp_bytes, width, height) or None on failure.
    """
    try:
        resp = requests.get(source_url, timeout=TIMEOUT, headers=HEADERS, stream=True)
        resp.raise_for_status()

        # Check Content-Length before downloading full body
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_FILE_SIZE:
            resp.close()
            logger.debug("Skipping %s: too large (%s bytes)", source_url, content_length)
            return None

        # Stream in chunks to enforce size limit without buffering unbounded data
        chunks = []
        size = 0
        for chunk in resp.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_FILE_SIZE:
                resp.close()
                logger.debug("Skipping %s: too large (>%d bytes)", source_url, MAX_FILE_SIZE)
                return None
            chunks.append(chunk)
        data = b"".join(chunks)

        img = Image.open(io.BytesIO(data))

        # Skip animated GIFs
        if getattr(img, "is_animated", False):
            logger.debug("Skipping %s: animated image", source_url)
            return None

        # Skip tiny images (tracking pixels, icons)
        if img.width < MIN_DIMENSION or img.height < MIN_DIMENSION:
            logger.debug("Skipping %s: too small (%dx%d)", source_url, img.width, img.height)
            return None

        # Convert to RGB if needed (e.g. RGBA, palette)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Resize if wider than max
        max_width = getattr(settings, "IMAGE_MAX_WIDTH", 1200)
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)

        # Save as WebP
        quality = getattr(settings, "IMAGE_QUALITY", 85)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality)
        webp_bytes = buf.getvalue()

        return webp_bytes, img.width, img.height

    except Exception as e:
        logger.debug("Failed to download %s: %s", source_url, e)
        return None


def _stable_filename(source_url: str) -> str:
    """Generate a stable filename from the source URL."""
    url_hash = hashlib.md5(source_url.encode()).hexdigest()[:12]
    return f"img_{url_hash}.webp"


class ImageDownloader:
    """Download and resize article images locally."""

    def __init__(self, workers: int = 10, days: int = 7, stdout=None):
        self.workers = workers
        self.days = days
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def download_new(self) -> tuple[int, int]:
        """Download images not yet attempted.

        Returns (processed, downloaded).
        """
        cutoff = django_tz.now() - timedelta(days=self.days)
        pending = list(
            ArticleImage.objects.filter(
                downloaded=False,
                article__published__gte=cutoff,
            ).values_list("id", "source_url")
        )

        if not pending:
            self._write("No images to download.\n")
            return 0, 0

        self._write(f"Downloading {len(pending)} images...\n")

        downloaded = 0

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(_download_and_resize, url): (img_id, url)
                for img_id, url in pending
            }

            for future in as_completed(futures):
                img_id, source_url = futures[future]
                result = future.result()

                if result is not None:
                    webp_bytes, width, height = result
                    filename = _stable_filename(source_url)

                    try:
                        img_obj = ArticleImage.objects.get(id=img_id)
                        img_obj.width = width
                        img_obj.height = height
                        img_obj.file_size = len(webp_bytes)
                        img_obj.downloaded = True
                        img_obj.image.save(filename, ContentFile(webp_bytes), save=True)
                        downloaded += 1
                    except Exception as e:
                        logger.warning("Failed to save image %s: %s", img_id, e)
                        ArticleImage.objects.filter(id=img_id).update(downloaded=True)
                else:
                    # Mark as attempted so we don't retry
                    ArticleImage.objects.filter(id=img_id).update(downloaded=True)

        self._write(f"Done: {downloaded}/{len(pending)} images downloaded\n")
        return len(pending), downloaded
