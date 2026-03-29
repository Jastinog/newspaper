import asyncio
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from apps.analytics.services import SessionService

logger = logging.getLogger(__name__)

# In-progress research generations: (item_id, language) -> {event, url, error, waiters}
_generations = {}


class SiteConsumer(AsyncWebsocketConsumer):
    """Single WebSocket endpoint for the entire site.

    Handles analytics tracking and research generation over one /ws/ connection.
    Action routing via ACTIONS dict — each action maps to a handler method.

    Protocol (dot-namespaced)
    --------
    Client -> Server:
        {"action": "analytics.init",       "client_id": "uuid", "referrer": "..."}
        {"action": "analytics.page_view",  "path": "/...", "referrer": "..."}
        {"action": "analytics.activity",   "type": "scroll|click", "path": "/...", "meta": {...}}
        {"action": "analytics.heartbeat",  "active_time": 120, "has_interaction": true}
        {"action": "research.generate",    "item_id": 123}

    Server -> Client:
        {"type": "analytics.session",      "session_id": "uuid"}
        {"type": "research.state",         "ready": [...], "generating": [...]}
        {"type": "research.generating",    "item_id": 123}
        {"type": "research.progress",      "item_id": 123, "step": 1, ...}
        {"type": "research.ready",         "item_id": 123, "url": "..."}
        {"type": "research.error",         "item_id": 123, "message": "..."}
    """

    ACTIONS = {
        # Analytics
        "analytics.init": "_on_analytics_init",
        "analytics.page_view": "_on_analytics_page_view",
        "analytics.activity": "_on_analytics_activity",
        "analytics.heartbeat": "_on_analytics_heartbeat",
        # Research
        "research.generate": "_on_research_generate",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.analytics = None

    # ── Lifecycle ───────────────────────────────────

    async def connect(self):
        await self.accept()
        self.analytics = SessionService(self.scope)
        state = await self._research_state()
        await self.send(json.dumps({
            "type": "research.state",
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

    # ── Research actions ───────────────────────────

    async def _on_research_generate(self, data):
        item_id = data.get("item_id")
        language = data.get("language", "en")
        if not item_id:
            return

        gen_key = (item_id, language)
        lang_obj = await self._resolve_language(language)

        url = await self._research_url(item_id, lang_obj)
        if url:
            await self.send(json.dumps({
                "type": "research.ready",
                "item_id": item_id,
                "url": url,
            }))
            return

        await self.send(json.dumps({
            "type": "research.generating",
            "item_id": item_id,
        }))

        if gen_key not in _generations:
            _generations[gen_key] = {
                "event": asyncio.Event(),
                "url": None,
                "error": None,
                "waiters": set(),
            }
            asyncio.create_task(self._run_research(item_id, language, lang_obj, gen_key))

        _generations[gen_key]["waiters"].add(self)
        asyncio.create_task(self._await_research(item_id, gen_key))

    async def _run_research(self, item_id, language, lang_obj, gen_key):
        gen = _generations[gen_key]
        loop = asyncio.get_running_loop()

        def progress_callback(step, total, step_id, label, detail=None):
            msg = json.dumps({
                "type": "research.progress",
                "item_id": item_id,
                "step": step,
                "total_steps": total,
                "step_id": step_id,
                "label": label,
                "detail": detail,
            })
            asyncio.run_coroutine_threadsafe(
                self._broadcast_progress(gen_key, msg), loop
            )

        try:
            gen["url"] = await self._do_research_generate(item_id, language, lang_obj, progress_callback)
        except Exception as e:
            logger.exception("Research generation failed for item %s [%s]", item_id, language)
            gen["error"] = str(e)
        finally:
            gen["event"].set()
            await asyncio.sleep(5)
            _generations.pop(gen_key, None)

    async def _broadcast_progress(self, gen_key, msg):
        gen = _generations.get(gen_key)
        if not gen:
            return
        for consumer in list(gen["waiters"]):
            try:
                await consumer.send(msg)
            except Exception:
                pass

    async def _await_research(self, item_id, gen_key):
        gen = _generations.get(gen_key)
        if not gen:
            return
        try:
            await asyncio.wait_for(gen["event"].wait(), timeout=300)
        except asyncio.TimeoutError:
            await self.send(json.dumps({
                "type": "research.error",
                "item_id": item_id,
                "message": "Generation timed out",
            }))
            return

        if gen["url"]:
            await self.send(json.dumps({
                "type": "research.ready",
                "item_id": item_id,
                "url": gen["url"],
            }))
        else:
            await self.send(json.dumps({
                "type": "research.error",
                "item_id": item_id,
                "message": gen.get("error", "Unknown error"),
            }))

    # ── Research DB helpers ────────────────────────

    @database_sync_to_async
    def _research_state(self):
        from apps.research.models import Research
        from apps.digest.models import Digest, DigestItem

        digest_ids = list(Digest.objects.order_by("-date").values_list("id", flat=True)[:3])
        if not digest_ids:
            return {"ready": [], "generating": []}

        item_ids = set(
            DigestItem.objects.filter(digest_id__in=digest_ids)
            .values_list("id", flat=True)
        )
        ready = list(
            Research.objects.filter(item_id__in=item_ids)
            .values_list("item_id", flat=True)
        )
        generating = [iid for iid, _lang in _generations if iid in item_ids]
        return {"ready": ready, "generating": generating}

    @database_sync_to_async
    def _resolve_language(self, language):
        from apps.core.models import Language
        return Language.get_by_code(language)

    @database_sync_to_async
    def _research_url(self, item_id, lang_obj):
        from apps.research.models import Research

        if Research.objects.filter(item_id=item_id, language=lang_obj).exists():
            return f"/research/{item_id}/"
        return None

    @database_sync_to_async
    def _do_research_generate(self, item_id, language, lang_obj, progress_callback=None):
        from apps.research.models import Research
        from apps.digest.models import DigestItem
        from apps.research.services import ResearchService

        if Research.objects.filter(item_id=item_id, language=lang_obj).exists():
            return f"/research/{item_id}/"

        item = DigestItem.objects.select_related("digest").get(pk=item_id)
        ResearchService().generate(item, language=language, progress_callback=progress_callback)
        return f"/research/{item_id}/"
