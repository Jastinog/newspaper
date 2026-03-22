import hashlib
import io
import logging
import random
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlparse

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
DOMAIN_DELAY = 8.0  # seconds between requests to same domain

HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "image/webp,image/avif,image/apng,image/*,*/*;q=0.8",
}


def _get_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


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


class ImageDownloader:
    """Download and resize article images locally.

    Uses per-domain throttling: at most one concurrent request per domain,
    with a cooldown of DOMAIN_DELAY seconds between requests to the same domain.
    """

    def __init__(self, workers: int = 10, days: int = 7, stdout=None):
        self.workers = workers
        self.days = days
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def _save_result(self, img_id: int, result, downloaded_count: int) -> int:
        """Save download result to DB. Returns updated downloaded_count."""
        if result is None:
            ArticleImage.objects.filter(id=img_id).update(downloaded=True)
            return downloaded_count

        webp_bytes, width, height = result
        content_hash = hashlib.sha256(webp_bytes).hexdigest()

        # Check for existing image with same content
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
                # Reuse existing file, no new write
                img_obj.image.name = existing.image.name
                img_obj.save()
            else:
                img_obj.image.save(_unique_filename(), ContentFile(webp_bytes), save=True)

            return downloaded_count + 1
        except Exception as e:
            logger.warning("Failed to save image %s: %s", img_id, e)
            ArticleImage.objects.filter(id=img_id).update(downloaded=True)
            return downloaded_count

    def download_new(self) -> tuple[int, int]:
        """Download images not yet attempted.

        Uses domain-based scheduling to avoid hammering any single host.
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

        # Group by domain
        domain_queues: dict[str, deque] = defaultdict(deque)
        for img_id, url in pending:
            domain = _get_domain(url)
            domain_queues[domain].append((img_id, url))

        domains = list(domain_queues.keys())
        random.shuffle(domains)
        self._write(f"Downloading {len(pending)} images from {len(domains)} domains...\n")

        downloaded = 0
        done_count = 0

        domain_last_req: dict[str, float] = {}
        active_domains: set[str] = set()
        in_flight: dict = {}  # future -> (img_id, domain)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while domain_queues or in_flight:
                # Submit new tasks for eligible domains
                now = time.monotonic()
                eligible = [
                    d for d in domains
                    if d in domain_queues
                    and d not in active_domains
                    and now - domain_last_req.get(d, 0) >= DOMAIN_DELAY
                ]
                random.shuffle(eligible)

                for domain in eligible[:self.workers - len(in_flight)]:
                    img_id, url = domain_queues[domain].popleft()
                    if not domain_queues[domain]:
                        del domain_queues[domain]
                    active_domains.add(domain)
                    future = pool.submit(_download_and_resize, url)
                    in_flight[future] = (img_id, domain)

                # Collect finished results (non-blocking)
                finished = [f for f in in_flight if f.done()]
                for future in finished:
                    img_id, domain = in_flight.pop(future)
                    active_domains.discard(domain)
                    domain_last_req[domain] = time.monotonic()

                    downloaded = self._save_result(img_id, future.result(), downloaded)
                    done_count += 1

                    if done_count % 200 == 0:
                        self._write(
                            f"  {done_count}/{len(pending)} processed "
                            f"({downloaded} ok)\n"
                        )

                # If nothing finished, sleep briefly to avoid busy-waiting
                if not finished:
                    time.sleep(0.1)

        self._write(f"Done: {downloaded}/{len(pending)} images downloaded\n")
        return len(pending), downloaded
