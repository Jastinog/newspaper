import asyncio
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

# Track in-progress generations: item_id -> {event, url, error}
_generations = {}


class DigestConsumer(AsyncWebsocketConsumer):
    """Single WebSocket per user on the digest page.

    Protocol:
        Server -> Client on connect:
            {"type": "init", "ready_ids": [item_id, ...]}

        Client -> Server:
            {"action": "generate", "item_id": 123}

        Server -> Client:
            {"type": "generating", "item_id": 123}
            {"type": "ready", "item_id": 123, "url": "/deep-dive/123/"}
            {"type": "error", "item_id": 123, "message": "..."}
    """

    async def connect(self):
        await self.accept()
        ready_ids = await self._get_ready_ids()
        await self.send(json.dumps({"type": "init", "ready_ids": ready_ids}))

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        if data.get("action") != "generate":
            return

        item_id = data.get("item_id")
        if not item_id:
            return

        # Already generated?
        url = await self._get_deep_dive_url(item_id)
        if url:
            await self.send(json.dumps({"type": "ready", "item_id": item_id, "url": url}))
            return

        await self.send(json.dumps({"type": "generating", "item_id": item_id}))

        # Start generation if not already running
        if item_id not in _generations:
            _generations[item_id] = {
                "event": asyncio.Event(),
                "url": None,
                "error": None,
            }
            asyncio.create_task(self._run_generation(item_id))

        # Wait for result in background (doesn't block receive)
        asyncio.create_task(self._wait_and_notify(item_id))

    async def _run_generation(self, item_id):
        """Run deep dive generation in a thread, then signal waiters."""
        gen = _generations[item_id]
        try:
            url = await self._do_generate(item_id)
            gen["url"] = url
        except Exception as e:
            logger.exception("Deep dive generation failed for item %s", item_id)
            gen["error"] = str(e)
        finally:
            gen["event"].set()
            # Clean up after waiters have had time to read the result
            await asyncio.sleep(5)
            _generations.pop(item_id, None)

    async def _wait_and_notify(self, item_id):
        """Wait for generation to finish and send result to this consumer."""
        gen = _generations.get(item_id)
        if not gen:
            return

        try:
            await asyncio.wait_for(gen["event"].wait(), timeout=300)
        except asyncio.TimeoutError:
            await self.send(json.dumps({
                "type": "error",
                "item_id": item_id,
                "message": "Generation timed out",
            }))
            return

        if gen["url"]:
            await self.send(json.dumps({
                "type": "ready",
                "item_id": item_id,
                "url": gen["url"],
            }))
        else:
            await self.send(json.dumps({
                "type": "error",
                "item_id": item_id,
                "message": gen.get("error", "Unknown error"),
            }))

    # ── DB helpers ──────────────────────────────────────────

    @database_sync_to_async
    def _get_ready_ids(self):
        from apps.news.models import DeepDive, Digest

        digest = Digest.objects.order_by("-date").first()
        if not digest:
            return []
        item_ids = list(
            digest.sections.values_list("items__id", flat=True)
        )
        return list(
            DeepDive.objects.filter(item_id__in=item_ids)
            .values_list("item_id", flat=True)
        )

    @database_sync_to_async
    def _get_deep_dive_url(self, item_id):
        from apps.news.models import DeepDive

        if DeepDive.objects.filter(item_id=item_id).exists():
            return f"/deep-dive/{item_id}/"
        return None

    @database_sync_to_async
    def _do_generate(self, item_id):
        from apps.news.models import DeepDive, DigestItem
        from apps.news.services.deep_dive import DeepDiveService

        # Double-check: may have been created while queued
        if DeepDive.objects.filter(item_id=item_id).exists():
            return f"/deep-dive/{item_id}/"

        item = DigestItem.objects.select_related("section__digest").get(pk=item_id)
        DeepDiveService().generate(item)
        return f"/deep-dive/{item_id}/"
