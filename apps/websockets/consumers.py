import asyncio
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from apps.analytics.services import SessionService

logger = logging.getLogger(__name__)

# In-progress deep dive generations: item_id -> {event, url, error, waiters}
_generations = {}


class SiteConsumer(AsyncWebsocketConsumer):
    """Single WebSocket endpoint for the entire site.

    Handles analytics tracking and deep dive generation over one /ws/ connection.
    Action routing via ACTIONS dict — each action maps to a handler method.

    Protocol (dot-namespaced)
    --------
    Client -> Server:
        {"action": "analytics.init",       "client_id": "uuid", "referrer": "..."}
        {"action": "analytics.page_view",  "path": "/...", "referrer": "..."}
        {"action": "analytics.activity",   "type": "scroll|click", "path": "/...", "meta": {...}}
        {"action": "analytics.heartbeat",  "active_time": 120, "has_interaction": true}
        {"action": "deep_dive.generate",   "item_id": 123}

    Server -> Client:
        {"type": "analytics.session",      "session_id": "uuid"}
        {"type": "deep_dive.state",        "ready": [...], "generating": [...]}
        {"type": "deep_dive.generating",   "item_id": 123}
        {"type": "deep_dive.progress",     "item_id": 123, "step": 1, ...}
        {"type": "deep_dive.ready",        "item_id": 123, "url": "..."}
        {"type": "deep_dive.error",        "item_id": 123, "message": "..."}
    """

    ACTIONS = {
        # Analytics
        "analytics.init": "_on_analytics_init",
        "analytics.page_view": "_on_analytics_page_view",
        "analytics.activity": "_on_analytics_activity",
        "analytics.heartbeat": "_on_analytics_heartbeat",
        # Deep Dive
        "deep_dive.generate": "_on_deep_dive_generate",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.analytics = None

    # ── Lifecycle ───────────────────────────────────

    async def connect(self):
        await self.accept()
        self.analytics = SessionService(self.scope)
        state = await self._deep_dive_state()
        await self.send(json.dumps({
            "type": "deep_dive.state",
            "ready": state["ready"],
            "generating": state["generating"],
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

    async def disconnect(self, code):
        for gen in _generations.values():
            gen["waiters"].discard(self)
        if self.analytics and self.analytics.is_active:
            await database_sync_to_async(self.analytics.close)()

    # ── Analytics actions ───────────────────────────

    async def _on_analytics_init(self, data):
        client, session = await database_sync_to_async(self.analytics.open)(
            raw_client_id=data.get("client_id", ""),
            referrer=data.get("referrer", ""),
        )
        # Record the initial page view atomically with session creation
        path = data.get("path", "")
        if path:
            await database_sync_to_async(self.analytics.page_view)(
                path=path,
                referrer=data.get("referrer", ""),
            )
        await self.send(json.dumps({
            "type": "analytics.session",
            "session_id": str(session.session_id),
        }))

    async def _on_analytics_page_view(self, data):
        await database_sync_to_async(self.analytics.page_view)(
            path=data.get("path", ""),
            referrer=data.get("referrer", ""),
        )

    async def _on_analytics_activity(self, data):
        meta = data.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        await database_sync_to_async(self.analytics.activity)(
            activity_type=data.get("type", ""),
            path=data.get("path", ""),
            meta=meta,
        )

    async def _on_analytics_heartbeat(self, data):
        await database_sync_to_async(self.analytics.heartbeat)(
            active_time=int(data.get("active_time", 0)),
            has_interaction=bool(data.get("has_interaction", False)),
        )

    # ── Deep Dive actions ───────────────────────────

    async def _on_deep_dive_generate(self, data):
        item_id = data.get("item_id")
        if not item_id:
            return

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

        if item_id not in _generations:
            _generations[item_id] = {
                "event": asyncio.Event(),
                "url": None,
                "error": None,
                "waiters": set(),
            }
            asyncio.create_task(self._run_deep_dive(item_id))

        _generations[item_id]["waiters"].add(self)
        asyncio.create_task(self._await_deep_dive(item_id))

    async def _run_deep_dive(self, item_id):
        gen = _generations[item_id]
        loop = asyncio.get_running_loop()

        def progress_callback(step, total, step_id, label, detail=None):
            msg = json.dumps({
                "type": "deep_dive.progress",
                "item_id": item_id,
                "step": step,
                "total_steps": total,
                "step_id": step_id,
                "label": label,
                "detail": detail,
            })
            asyncio.run_coroutine_threadsafe(
                self._broadcast_progress(item_id, msg), loop
            )

        try:
            gen["url"] = await self._do_deep_dive_generate(item_id, progress_callback)
        except Exception as e:
            logger.exception("Deep dive failed for item %s", item_id)
            gen["error"] = str(e)
        finally:
            gen["event"].set()
            await asyncio.sleep(5)
            _generations.pop(item_id, None)

    async def _broadcast_progress(self, item_id, msg):
        gen = _generations.get(item_id)
        if not gen:
            return
        for consumer in list(gen["waiters"]):
            try:
                await consumer.send(msg)
            except Exception:
                pass

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

    # ── Deep Dive DB helpers ────────────────────────

    @database_sync_to_async
    def _deep_dive_state(self):
        from apps.deep_dive.models import DeepDive
        from apps.digest.models import Digest, DigestItem

        digest_ids = list(Digest.objects.order_by("-date").values_list("id", flat=True)[:3])
        if not digest_ids:
            return {"ready": [], "generating": []}

        item_ids = set(
            DigestItem.objects.filter(section__digest_id__in=digest_ids)
            .values_list("id", flat=True)
        )
        ready = list(
            DeepDive.objects.filter(item_id__in=item_ids)
            .values_list("item_id", flat=True)
        )
        generating = [iid for iid in _generations if iid in item_ids]
        return {"ready": ready, "generating": generating}

    @database_sync_to_async
    def _deep_dive_url(self, item_id):
        from apps.deep_dive.models import DeepDive

        if DeepDive.objects.filter(item_id=item_id).exists():
            return f"/deep-dive/{item_id}/"
        return None

    @database_sync_to_async
    def _do_deep_dive_generate(self, item_id, progress_callback=None):
        from apps.deep_dive.models import DeepDive
        from apps.digest.models import DigestItem
        from apps.deep_dive.services import DeepDiveService

        if DeepDive.objects.filter(item_id=item_id).exists():
            return f"/deep-dive/{item_id}/"

        item = DigestItem.objects.select_related("section__digest").get(pk=item_id)
        DeepDiveService().generate(item, progress_callback=progress_callback)
        return f"/deep-dive/{item_id}/"
