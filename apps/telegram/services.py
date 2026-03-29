import logging
from pathlib import Path

import requests
from django.conf import settings
from django.utils import timezone

from apps.digest.models import Digest, DigestItem

from .models import TelegramChannel, TelegramPost

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


class TelegramService:
    """Formats and sends digest items to Telegram channels."""

    def __init__(self, channel: TelegramChannel):
        self.channel = channel
        self.api_url = TELEGRAM_API.format(token=channel.effective_bot_token)

    def _call(self, method: str, data: dict, files: dict | None = None) -> dict:
        url = f"{self.api_url}/{method}"
        resp = requests.post(url, data=data, files=files, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API error: {result}")
        return result

    def send_message(self, text: str, **kwargs) -> dict:
        data = {
            "chat_id": self.channel.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            **kwargs,
        }
        return self._call("sendMessage", data)

    def send_photo(self, image_path: Path, caption: str) -> dict:
        data = {
            "chat_id": self.channel.chat_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        with open(image_path, "rb") as f:
            return self._call("sendPhoto", data, files={"photo": f})

    # ── Formatting ────────────────────────────────────────────

    def _format_item(self, item: DigestItem) -> str:
        lang = self.channel.language.code
        topic = item.get_topic(lang) or item.get_topic("en")
        summary = item.get_summary(lang) or item.get_summary("en")
        importance = item.importance

        # Importance indicator
        if importance >= 7:
            icon = "\U0001f534"  # red circle
        elif importance >= 5:
            icon = "\U0001f7e0"  # orange circle
        else:
            icon = "\U0001f535"  # blue circle

        return f"{icon} <b>{topic}</b>\n{summary}"

    def _format_header(self, digest: Digest) -> str:
        lang = self.channel.language.code
        headline = digest.get_headline(lang) or digest.get_headline("en")
        date_str = digest.date.strftime("%d.%m.%Y")
        header = f"\U0001f4f0 <b>{date_str}</b>"
        if headline:
            header += f"\n\n{headline}"
        return header

    # ── Publishing ────────────────────────────────────────────

    def publish_digest(self, digest: Digest) -> TelegramPost:
        """Post the digest's top items to the Telegram channel."""
        items = (
            DigestItem.objects
            .filter(digest=digest)
            .select_related("section", "image")
            .prefetch_related("translations", "translations__language")
            .order_by("-importance", "-freshness")
            [: self.channel.top_n]
        )

        if not items:
            logger.warning("No items in digest %s, skipping channel %s", digest.date, self.channel)
            return TelegramPost.objects.create(
                channel=self.channel,
                digest=digest,
                status=TelegramPost.Status.FAILED,
                error_message="No digest items found",
            )

        try:
            # Send header
            self.send_message(self._format_header(digest))

            posted = 0
            for item in items:
                text = self._format_item(item)

                # Try sending with image
                if self.channel.include_images and item.image and item.image.image:
                    image_path = Path(settings.MEDIA_ROOT) / str(item.image.image)
                    if image_path.exists():
                        try:
                            self.send_photo(image_path, text)
                            posted += 1
                            continue
                        except Exception:
                            logger.debug("Image send failed for item %s, falling back to text", item.pk)

                self.send_message(text)
                posted += 1

            return TelegramPost.objects.create(
                channel=self.channel,
                digest=digest,
                status=TelegramPost.Status.SUCCESS,
                items_posted=posted,
            )

        except Exception as e:
            logger.exception("Failed posting to channel %s", self.channel)
            return TelegramPost.objects.create(
                channel=self.channel,
                digest=digest,
                status=TelegramPost.Status.FAILED,
                error_message=str(e)[:500],
            )


def publish_to_all_channels(digest: Digest | None = None) -> list[TelegramPost]:
    """Publish digest to all active Telegram channels whose post_time has arrived."""
    if digest is None:
        today = timezone.localdate()
        digest = Digest.objects.filter(date=today, stage=Digest.Stage.DONE).first()
        if not digest:
            logger.info("No completed digest for %s", today)
            return []

    now = timezone.localtime()
    channels = TelegramChannel.objects.filter(is_active=True).select_related("language")
    results = []

    for channel in channels:
        # Only post if scheduled time has passed
        if now.time() < channel.post_time:
            continue

        # Skip if already posted
        if TelegramPost.objects.filter(channel=channel, digest=digest, status=TelegramPost.Status.SUCCESS).exists():
            logger.info("Already posted to %s for %s", channel, digest.date)
            continue

        service = TelegramService(channel)
        post = service.publish_digest(digest)
        results.append(post)
        logger.info("Posted to %s: %s (%d items)", channel, post.status, post.items_posted)

    return results
