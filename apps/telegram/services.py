import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils import timezone

from apps.digest.models import Digest, DigestItem

from .models import SentItem, TelegramChannel, TelegramPost

logger = logging.getLogger(__name__)


def md_to_telegram_html(text: str) -> str:
    """Convert simple Markdown to Telegram-compatible HTML."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"^[-*+] ", "\u2022 ", text, flags=re.MULTILINE)
    return text.strip()

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
        # Section hashtag
        hashtag = ""
        if item.section:
            hashtag = f"#{item.section.slug.replace('-', '_')}"

        # Source links (unique domains, up to 3)
        sources = ""
        seen_domains = set()
        links = []
        for a in item.articles.all():
            domain = urlparse(a.url).netloc.replace("www.", "")
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            name = domain.split(".")[0].capitalize()
            links.append(f'<a href="{a.url}">{name}</a>')
            if len(links) >= 3:
                break
        if links:
            sources = "\n\n" + " \u2022 ".join(links)

        # Clickable headline linking to the website
        site_url = settings.SITE_URL
        if site_url:
            story_url = f"{site_url}/{lang}/story/{item.id}/"
            title = f'<b><a href="{story_url}">{topic}</a></b>'
        else:
            title = f"<b>{topic}</b>"

        lines = [
            title,
            "",
            md_to_telegram_html(summary),
        ]
        if sources:
            lines.append(sources)
        if hashtag:
            lines.append(f"\n{hashtag}")

        return "\n".join(lines)

    DIGEST_TITLE = {
        "uk": "Дайджест",
        "ru": "Дайджест",
        "en": "News Digest",
    }

    def _format_header(self, digest: Digest) -> str:
        lang = self.channel.language.code
        headline = digest.get_headline(lang) or digest.get_headline("en")
        date_str = digest.date.strftime("%d.%m.%Y")
        title = self.DIGEST_TITLE.get(lang, "News Digest")

        header = f"\U0001f4f0 <b>{title} {date_str}</b>"
        if headline:
            header += f"\n\n<i>{headline}</i>"
        header += "\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        return header

    # ── Publishing ────────────────────────────────────────────

    PLACEHOLDER = Path(__file__).resolve().parent.parent / "core" / "static" / "news" / "img" / "placeholder.webp"

    def send_item(self, item: DigestItem) -> None:
        """Format and send a single digest item, with image fallback to placeholder."""
        text = self._format_item(item)

        if self.channel.include_images:
            image_path = None
            if item.image and item.image.image:
                image_path = Path(settings.MEDIA_ROOT) / str(item.image.image)
                if not image_path.exists():
                    image_path = None

            if image_path is None:
                image_path = self.PLACEHOLDER

            try:
                self.send_photo(image_path, text)
                return
            except Exception:
                logger.debug("Image send failed for item %s, falling back to text", item.pk)

        self.send_message(text)

    def publish_digest(self, digest: Digest) -> TelegramPost:
        """Post the digest's top items to the Telegram channel."""
        items = (
            DigestItem.objects
            .filter(digest=digest)
            .select_related("section", "image")
            .prefetch_related("translations", "translations__language", "articles")
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
            posted = 0
            for item in items:
                self.send_item(item)
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


def publish_next_items() -> int:
    """Send the next unsent item to each active channel. Returns total items sent."""
    today = timezone.localdate()
    channels = TelegramChannel.objects.filter(is_active=True).select_related("language")
    total = 0

    for channel in channels:
        already_sent = SentItem.objects.filter(
            channel=channel,
            item__digest__date=today,
        ).values_list("item_id", flat=True)

        item = (
            DigestItem.objects
            .filter(digest__date=today)
            .exclude(id__in=already_sent)
            .select_related("section", "image")
            .prefetch_related("translations", "translations__language", "articles")
            .order_by("-importance", "-freshness")
            .first()
        )

        if not item:
            logger.info("No unsent items for %s on %s", channel, today)
            continue

        service = TelegramService(channel)
        try:
            service.send_item(item)
            SentItem.objects.create(channel=channel, item=item)
            total += 1
            logger.info("Sent item #%d to %s", item.pk, channel)
        except Exception as e:
            logger.exception("Failed sending item #%d to %s: %s", item.pk, channel, e)

    return total


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
