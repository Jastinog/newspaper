import asyncio
import json
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from apps.analytics.services import SessionService

logger = logging.getLogger(__name__)

# In-progress research generations: (item_id, language) -> {event, url, error, waiters}
_generations = {}

# In-progress article-summary generations: (article_id, language) -> {event, data, error, waiters}
_summaries = {}


class SiteConsumer(AsyncWebsocketConsumer):
    """Single WebSocket endpoint for the entire site.

    Handles analytics tracking and research generation over one /ws/ connection.
    Action routing via ACTIONS dict — each action maps to a handler method.

    Protocol (dot-namespaced)
    --------
    Client -> Server:
        {"action": "analytics.init",  "client_id": "uuid", "path": "/...", "referrer": "..."}
        {"action": "analytics.ping",  "scrolls": 5, "pages": ["/..."], "active_time": 120}
        {"action": "research.generate", "item_id": 123}

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
        "analytics.ping": "_on_analytics_ping",
        # Research
        "research.generate": "_on_research_generate",
        # Article summaries ("суть на русском")
        "summary.generate": "_on_summary_generate",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.analytics = None
        self._last_session_id = None

    # ── Lifecycle ───────────────────────────────────

    async def connect(self):
        await self.accept()
        self.analytics = SessionService(self.scope)
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        self.language = qs.get("lang", ["en"])[0]
        state = await self._research_state(self.language)
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
        for gen in _summaries.values():
            gen["waiters"].discard(self)
        if self.analytics and self.analytics.is_active:
            await database_sync_to_async(self.analytics.close)()

    # ── Analytics actions ───────────────────────────

    async def _on_analytics_init(self, data):
        client, session = await database_sync_to_async(self.analytics.open)(
            raw_client_id=data.get("client_id", ""),
            referrer=data.get("referrer", ""),
            path=data.get("path", ""),
        )
        self._last_session_id = str(session.session_id)
        await self.send(json.dumps({
            "type": "analytics.session",
            "session_id": self._last_session_id,
            "active_time": session.active_time,
        }))

    async def _on_analytics_ping(self, data):
        pages = data.get("pages", [])
        if not isinstance(pages, list):
            pages = []
        result = await database_sync_to_async(self.analytics.ping)(
            scrolls=int(data.get("scrolls", 0)),
            pages=pages,
            active_time=int(data.get("active_time", 0)),
        )
        # If a new session was created (5-min inactivity gap), notify client
        if result and str(result.session_id) != self._last_session_id:
            self._last_session_id = str(result.session_id)
            await self.send(json.dumps({
                "type": "analytics.session",
                "session_id": self._last_session_id,
            }))

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

    # ── Article summary actions ────────────────────

    async def _on_summary_generate(self, data):
        """Return a stored summary for the current language instantly, or generate
        one with progress. Summaries are per (article, language): a summary in one
        language does not satisfy a request for another.

        Server -> Client:
            {"type": "summary.generating", "article_id": 1}
            {"type": "summary.progress",   "article_id": 1, "step": 2, "total_steps": 3, "label": "…"}
            {"type": "summary.ready",      "article_id": 1, "summary": "…", "conclusion": "…", "cached": true}
            {"type": "summary.error",      "article_id": 1, "message": "…"}
        """
        try:
            article_id = int(data.get("article_id"))
        except (TypeError, ValueError):
            return

        language = data.get("language") or self.language or "en"
        gen_key = (article_id, language)

        # Serve an already-generated summary immediately — no API call, no rate limit.
        existing = await self._summary_get(article_id, language)
        if existing:
            await self.send(json.dumps({
                "type": "summary.ready",
                "article_id": article_id,
                "summary": existing["summary"],
                "conclusion": existing["conclusion"],
                "cached": True,
            }))
            return

        await self.send(json.dumps({"type": "summary.generating", "article_id": article_id}))

        # Coalesce concurrent requests for the same (article, language) behind one run.
        if gen_key not in _summaries:
            _summaries[gen_key] = {
                "event": asyncio.Event(),
                "data": None,
                "error": None,
                "waiters": set(),
            }
            asyncio.create_task(self._run_summary(article_id, language, gen_key))

        _summaries[gen_key]["waiters"].add(self)
        asyncio.create_task(self._await_summary(article_id, gen_key))

    async def _run_summary(self, article_id, language, gen_key):
        gen = _summaries[gen_key]
        loop = asyncio.get_running_loop()

        def progress_callback(step, total):
            msg = json.dumps({
                "type": "summary.progress",
                "article_id": article_id,
                "step": step,
                "total_steps": total,
            })
            asyncio.run_coroutine_threadsafe(
                self._broadcast_summary(gen_key, msg), loop
            )

        try:
            gen["data"] = await self._do_summary_generate(article_id, language, progress_callback)
        except Exception as e:
            logger.exception("Summary generation failed for article %s [%s]", article_id, language)
            gen["error"] = str(e)
        finally:
            gen["event"].set()
            await asyncio.sleep(5)
            _summaries.pop(gen_key, None)

    async def _broadcast_summary(self, gen_key, msg):
        gen = _summaries.get(gen_key)
        if not gen:
            return
        for consumer in list(gen["waiters"]):
            try:
                await consumer.send(msg)
            except Exception:
                pass

    async def _await_summary(self, article_id, gen_key):
        gen = _summaries.get(gen_key)
        if not gen:
            return
        try:
            await asyncio.wait_for(gen["event"].wait(), timeout=120)
        except asyncio.TimeoutError:
            await self.send(json.dumps({
                "type": "summary.error",
                "article_id": article_id,
                "message": "Время ожидания истекло",
            }))
            return

        if gen["data"]:
            await self.send(json.dumps({
                "type": "summary.ready",
                "article_id": article_id,
                "summary": gen["data"]["summary"],
                "conclusion": gen["data"]["conclusion"],
                "cached": False,
            }))
        else:
            await self.send(json.dumps({
                "type": "summary.error",
                "article_id": article_id,
                "message": gen.get("error") or "Не удалось сделать пересказ",
            }))

    # ── Article summary DB helpers ─────────────────

    @database_sync_to_async
    def _summary_get(self, article_id, language):
        from apps.core.models import Language
        from apps.feed.models import ArticleSummary

        s = ArticleSummary.get_for(article_id, Language.get_by_code_safe(language))
        if not s:
            return None
        return {"summary": s.summary, "conclusion": s.conclusion}

    @database_sync_to_async
    def _do_summary_generate(self, article_id, language, progress_callback=None):
        from apps.core.models import Language
        from apps.feed.models import Article, ArticleSummary
        from apps.feed.services.summarize import SummaryError, generate_summary, summary_rate_ok

        # A late request may find the summary already cached (another waiter won).
        lang_obj = Language.get_by_code_safe(language)
        existing = ArticleSummary.get_for(article_id, lang_obj)
        if existing:
            return {"summary": existing.summary, "conclusion": existing.conclusion}

        # A new summary is a paid API call — rate-limit before spending. The peer
        # key uses the real TCP peer only (never client-supplied forwarding headers).
        peer = self.scope.get("client", ["unknown"])[0] or "unknown"
        if not summary_rate_ok(peer):
            raise SummaryError("Слишком много запросов. Попробуйте позже.")

        try:
            article = Article.objects.get(pk=article_id)
        except Article.DoesNotExist:
            raise SummaryError("Статья не найдена.")

        summary = generate_summary(article, language=lang_obj, progress_callback=progress_callback)
        return {"summary": summary.summary, "conclusion": summary.conclusion}

    # ── Research DB helpers ────────────────────────

    @database_sync_to_async
    def _research_state(self, language="en"):
        from apps.research.models import Research
        from apps.core.models import Language
        from apps.digest.models import Digest, DigestItem

        digest_ids = list(Digest.objects.order_by("-date").values_list("id", flat=True)[:3])
        if not digest_ids:
            return {"ready": [], "generating": []}

        item_ids = set(
            DigestItem.objects.filter(digest_id__in=digest_ids)
            .values_list("id", flat=True)
        )
        lang_obj = Language.get_by_code(language)
        ready = list(
            Research.objects.filter(item_id__in=item_ids, language=lang_obj)
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
