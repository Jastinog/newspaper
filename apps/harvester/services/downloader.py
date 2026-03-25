import hashlib
import io
import logging
import random
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone as django_tz
from PIL import Image

from apps.feed.models import ArticleImage
from .http import get_domain, random_headers
from .throttle import acquire_domain, release_domain

logger = logging.getLogger(__name__)

TIMEOUT = 20
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB
MIN_DIMENSION = 100  # skip tracking pixels
DOWNLOAD_BATCH_SIZE = 10


def articles_with_downloaded_rss_image():
    """Article IDs that already have a usable RSS image (OG is a fallback)."""
    return (
        ArticleImage.objects
        .filter(source__slug="rss-image", downloaded=True)
        .exclude(image="")
        .values_list("article_id", flat=True)
    )


def download_and_resize(source_url: str) -> tuple[bytes, int, int] | None:
    """Download image, resize if needed, convert to WebP.

    Returns (webp_bytes, width, height) or None on failure.
    """
    try:
        resp = requests.get(source_url, timeout=TIMEOUT, headers=random_headers(), stream=True)
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
        max_width = getattr(settings, "IMAGE_MAX_WIDTH", 800)
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


def _unique_filename() -> str:
    return f"{uuid.uuid4().hex}.webp"


def save_image_result(img_id: int, result) -> bool:
    """Save a download result to the database.

    Handles deduplication by content hash: if an identical image already
    exists on disk, reuses the file path instead of writing a new copy.

    Returns True if the image was saved successfully, False otherwise.
    """
    if result is None:
        ArticleImage.objects.filter(id=img_id).update(downloaded=True)
        return False

    webp_bytes, width, height = result
    content_hash = hashlib.sha256(webp_bytes).hexdigest()

    existing = (
        ArticleImage.objects
        .filter(content_hash=content_hash)
        .exclude(image="")
        .first()
    )

    try:
        img_obj = ArticleImage.objects.get(id=img_id)
        img_obj.width = width
        img_obj.height = height
        img_obj.file_size = len(webp_bytes)
        img_obj.content_hash = content_hash
        img_obj.downloaded = True

        if existing:
            img_obj.image.name = existing.image.name
            img_obj.save()
        else:
            img_obj.image.save(_unique_filename(), ContentFile(webp_bytes), save=True)

        return True
    except Exception as e:
        logger.warning("Failed to save image %s: %s", img_id, e)
        ArticleImage.objects.filter(id=img_id).update(downloaded=True)
        return False


class ImageDownloader:
    """Download and resize article images locally.

    Uses per-domain throttling: at most one concurrent request per domain,
    with a cooldown of DOMAIN_DELAY seconds between requests to the same domain.
    """

    def __init__(self, workers: int = 20, days: int = 30, stdout=None):
        self.workers = workers
        self.days = days
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def download_new(self, batch_size: int = 0) -> tuple[int, int, int]:
        """Download images not yet attempted.

        Uses domain-based scheduling to avoid hammering any single host.
        Returns (processed, downloaded, skipped).
        """
        cutoff = django_tz.now() - timedelta(days=self.days)
        qs = (
            ArticleImage.objects.filter(
                downloaded=False,
                article__published__gte=cutoff,
            ).filter(
                Q(source__slug="rss-image")
                | Q(source__slug="og-image", article__pipeline__content_extracted_at__isnull=False)
            ).exclude(
                Q(source__slug="og-image", article_id__in=articles_with_downloaded_rss_image())
            ).values_list("id", "source_url")
            .order_by("?")
        )
        if batch_size:
            qs = qs[:batch_size]
        pending = list(qs)

        if not pending:
            self._write("No images to download.\n")
            return 0, 0, 0

        # Group by domain
        domain_queues: dict[str, deque] = defaultdict(deque)
        for img_id, url in pending:
            domain = get_domain(url)
            domain_queues[domain].append((img_id, url))

        domains = list(domain_queues.keys())
        random.shuffle(domains)
        self._write(f"Downloading {len(pending)} images from {len(domains)} domains...\n")

        downloaded = 0
        skipped = 0
        done_count = 0
        in_flight: dict = {}  # future -> (img_id, domain)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while domain_queues or in_flight:
                # Submit new tasks for domains we can acquire
                random.shuffle(domains)
                for domain in domains:
                    if len(in_flight) >= self.workers:
                        break
                    if domain not in domain_queues:
                        continue
                    if not acquire_domain(domain):
                        continue
                    img_id, url = domain_queues[domain].popleft()
                    if not domain_queues[domain]:
                        del domain_queues[domain]
                    future = pool.submit(download_and_resize, url)
                    in_flight[future] = (img_id, domain)

                # Collect finished results (non-blocking)
                finished = [f for f in in_flight if f.done()]
                for future in finished:
                    img_id, domain = in_flight.pop(future)
                    release_domain(domain)

                    result = future.result()
                    if result is None:
                        skipped += 1
                    if save_image_result(img_id, result):
                        downloaded += 1
                    done_count += 1

                    if done_count % 200 == 0:
                        self._write(
                            f"  {done_count}/{len(pending)} processed "
                            f"({downloaded} ok)\n"
                        )

                # If nothing finished, sleep briefly to avoid busy-waiting
                if not finished:
                    time.sleep(0.1)

        self._write(f"Done: {downloaded}/{len(pending)} images downloaded, {skipped} skipped\n")
        return len(pending), downloaded, skipped
