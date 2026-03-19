import asyncio
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

# In-progress deep dive generations: item_id -> {event, url, error}
_generations = {}


class SiteConsumer(AsyncWebsocketConsumer):
    """Main WebSocket endpoint for the site.

    Single connection at /ws/ handles all real-time features via actions.

    Protocol
    --------
    Client -> Server:
        {"action": "deep_dive.generate", "item_id": 123}

    Server -> Client:
        {"type": "init", "deep_dives": {"ready": [1,2], "generating": [3]}}
        {"type": "deep_dive.generating", "item_id": 123}
        {"type": "deep_dive.ready",      "item_id": 123, "url": "/deep-dive/123/"}
        {"type": "deep_dive.error",      "item_id": 123, "message": "..."}
    """

    ACTIONS = {
        "deep_dive.generate": "_on_deep_dive_generate",
    }

    # ── Lifecycle ──────────────────────────────────────

    async def connect(self):
        await self.accept()
        await self.send(json.dumps({
            "type": "init",
            "deep_dives": await self._deep_dive_state(),
        }))

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            return

        handler_name = self.ACTIONS.get(data.get("action"))
        if handler_name:
            await getattr(self, handler_name)(data)

    # ── Deep Dive actions ──────────────────────────────

    async def _on_deep_dive_generate(self, data):
        item_id = data.get("item_id")
        if not item_id:
            return

        # Already exists — instant response
        url = await self._deep_dive_url(item_id)
        if url:
            await self.send(json.dumps({
                "type": "deep_dive.ready",
                "item_id": item_id,
                "url": url,
            }))
            return

        await self.send(json.dumps({
            "type": "deep_dive.generating",
            "item_id": item_id,
        }))

        # Start generation if nobody else is doing it
        if item_id not in _generations:
            _generations[item_id] = {
                "event": asyncio.Event(),
                "url": None,
                "error": None,
            }
            asyncio.create_task(self._run_deep_dive(item_id))

        # Wait for result in a non-blocking task
        asyncio.create_task(self._await_deep_dive(item_id))

    async def _run_deep_dive(self, item_id):
        gen = _generations[item_id]
        try:
            gen["url"] = await self._do_deep_dive_generate(item_id)
        except Exception as e:
            logger.exception("Deep dive failed for item %s", item_id)
            gen["error"] = str(e)
        finally:
            gen["event"].set()
            await asyncio.sleep(5)  # let waiters read the result
            _generations.pop(item_id, None)

    async def _await_deep_dive(self, item_id):
        gen = _generations.get(item_id)
        if not gen:
            return
        try:
            await asyncio.wait_for(gen["event"].wait(), timeout=300)
        except asyncio.TimeoutError:
            await self.send(json.dumps({
                "type": "deep_dive.error",
                "item_id": item_id,
                "message": "Generation timed out",
            }))
            return

        if gen["url"]:
            await self.send(json.dumps({
                "type": "deep_dive.ready",
                "item_id": item_id,
                "url": gen["url"],
            }))
        else:
            await self.send(json.dumps({
                "type": "deep_dive.error",
                "item_id": item_id,
                "message": gen.get("error", "Unknown error"),
            }))

    # ── DB helpers ─────────────────────────────────────

    @database_sync_to_async
    def _deep_dive_state(self):
        from apps.news.models import DeepDive, Digest

        # Return state for the most recent digest of each language
        digests = Digest.objects.order_by("-date")[:3]
        if not digests:
            return {"ready": [], "generating": []}

        item_ids = set()
        for digest in digests:
            item_ids.update(
                digest.sections.values_list("items__id", flat=True)
            )
        ready = list(
            DeepDive.objects.filter(item_id__in=item_ids)
            .values_list("item_id", flat=True)
        )
        generating = [
            iid for iid in _generations if iid in item_ids
        ]
        return {"ready": ready, "generating": generating}

    @database_sync_to_async
    def _deep_dive_url(self, item_id):
        from apps.news.models import DeepDive

        if DeepDive.objects.filter(item_id=item_id).exists():
            return f"/deep-dive/{item_id}/"
        return None

    @database_sync_to_async
    def _do_deep_dive_generate(self, item_id):
        from apps.news.models import DeepDive, DigestItem
        from apps.news.services.deep_dive import DeepDiveService

        if DeepDive.objects.filter(item_id=item_id).exists():
            return f"/deep-dive/{item_id}/"

        item = DigestItem.objects.select_related("section__digest").get(pk=item_id)
        DeepDiveService().generate(item)
        return f"/deep-dive/{item_id}/"
