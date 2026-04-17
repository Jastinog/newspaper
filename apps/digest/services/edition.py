import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone as tz

from django.db import close_old_connections
from django.utils import timezone

from apps.billing.models import APIUsage
from apps.billing.services import record_digest_usage
from apps.core.models import Language
from apps.core.services.ai import OpenAIClient, calculate_cost, trim_to_tokens
from apps.core.services.utils import sanitize_text
from apps.digest.models import (
    Digest, DigestConfig, DigestRun, DigestSection, ItemPipeline,
)
from apps.feed.models import Article

from .planner import EditionPlanner
from .saver import DigestSaver
from .writer import StoryWriter, build_writer_schema

logger = logging.getLogger(__name__)


class EditionService:
    """Edition pipeline: collect (SQL) -> plan (one LLM) -> write (parallel LLM) -> save."""

    def __init__(self, config: DigestConfig = None):
        self.config = config or DigestConfig.get()
        self.client = OpenAIClient()
        self.planner = EditionPlanner(client=self.client, config=self.config)
        self.writer = StoryWriter(client=self.client, config=self.config)
        self.saver = DigestSaver()

    def run(self, digest_date: date = None, languages: list[str] = None,
            items_per_section: int = None, on_event=None) -> Digest:
        emit = on_event or (lambda *a, **kw: None)
        cfg = self.config
        digest_date = digest_date or date.today()

        default_lang = Language.default()
        if not default_lang:
            raise RuntimeError("No default language. Run initdigest first.")

        target_langs = list(
            Language.active_targets().filter(code__in=languages) if languages
            else Language.active_targets()
        )
        all_langs = [(default_lang.code, default_lang.name)]
        all_langs.extend((lang.code, lang.name) for lang in target_langs)

        ips = items_per_section or cfg.edition_items_per_section

        # Clean slate
        Digest.objects.filter(date=digest_date).delete()
        digest = Digest.objects.create(date=digest_date)

        run = DigestRun.objects.create(
            digest=digest, model=cfg.chat_model,
            items_per_section=ips,
            started_at=timezone.now(),
        )

        # ── Step 1: Collect ──────────────────────────────────────
        cards, articles_by_id = self._collect(cfg, digest_date, emit)
        run.articles_collected = len(cards)
        run.save(update_fields=["articles_collected"])

        if not cards:
            raise RuntimeError("No articles found. Check harvester pipeline.")

        # ── Step 2: Plan ─────────────────────────────────────────
        sections = list(
            DigestSection.objects.filter(enabled=True)
            .prefetch_related("translations")
        )

        t0 = time.monotonic()
        stories, plan_usage = self.planner.plan(
            cards, sections, items_per_section=ips, on_event=emit,
        )
        plan_ms = int((time.monotonic() - t0) * 1000)

        plan_in = plan_usage.get("prompt_tokens", 0)
        plan_out = plan_usage.get("completion_tokens", 0)

        run.stories_planned = len(stories)
        run.plan_duration_ms = plan_ms
        run.plan_input_tokens = plan_in
        run.plan_output_tokens = plan_out
        run.plan_cost_usd = calculate_cost(cfg.planner_model, plan_in, plan_out)
        run.save(update_fields=[
            "stories_planned", "plan_duration_ms",
            "plan_input_tokens", "plan_output_tokens", "plan_cost_usd",
        ])

        record_digest_usage(plan_usage, step=APIUsage.Step.PLAN,
                            api_type=APIUsage.APIType.CHAT,
                            model=cfg.planner_model, digest=digest)

        emit("plan", stories=len(stories), duration_ms=plan_ms,
             tokens=plan_usage.get("total_tokens", 0),
             cost=float(run.plan_cost_usd))

        if not stories:
            raise RuntimeError("Planner returned no stories.")

        section_map = {s.slug: s for s in sections}

        # ── Step 3: Write (parallel) ─────────────────────────────
        # Build schema once for all writer calls (same languages every time)
        writer_schema = build_writer_schema([code for code, _ in all_langs])

        t0 = time.monotonic()
        results = self._write_parallel(
            digest, stories, articles_by_id, section_map,
            default_lang, target_langs, all_langs, writer_schema, cfg, emit,
        )
        write_ms = int((time.monotonic() - t0) * 1000)

        total_write_in = sum(r["input_tokens"] for r in results)
        total_write_out = sum(r["output_tokens"] for r in results)
        generated = sum(1 for r in results if r["success"])
        failed = sum(1 for r in results if not r["success"])

        run.items_generated = generated
        run.items_failed = failed
        run.write_duration_ms = write_ms
        run.write_input_tokens = total_write_in
        run.write_output_tokens = total_write_out
        run.write_cost_usd = calculate_cost(cfg.chat_model, total_write_in, total_write_out)
        run.total_cost_usd = run.plan_cost_usd + run.write_cost_usd
        run.completed_at = timezone.now()
        run.save()

        if generated == 0:
            raise RuntimeError("No items generated.")

        digest.stage = Digest.Stage.DONE
        digest.save(update_fields=["stage"])

        self.saver.invalidate_index_cache()

        emit("done", items=generated, failed=failed,
             total_cost=float(run.total_cost_usd))
        logger.info("Edition %s complete: %d items, $%.4f",
                     digest.date, generated, run.total_cost_usd)
        return digest

    # ── Step 1: Collect ─────────────────────────────────────────

    def _collect(self, cfg, digest_date, emit) -> tuple[list[dict], dict]:
        """Collect articles via round-robin across feeds.

        Adaptive snippet sizing: adjusts snippet length so all collected
        articles fit within the planner token budget.
        """
        end_of_day = datetime.combine(digest_date, datetime.max.time(), tzinfo=tz.utc)
        cutoff = end_of_day - timedelta(hours=cfg.hours_lookback)

        # Defer content — only ordered articles need it for snippets
        qs = (
            Article.objects
            .select_related("feed")
            .defer("content")
            .filter(
                published__gte=cutoff,
                published__lte=end_of_day,
                feed__enabled=True,
            )
            .exclude(content="")
            .filter(used_in_digest=False, status=Article.Status.COMPLETED)
            .order_by("-published")
        )

        # Group by feed (lightweight — no content loaded yet)
        by_feed: dict[int, list] = {}
        total_count = 0
        for a in qs:
            by_feed.setdefault(a.feed_id, []).append(a)
            total_count += 1

        if not by_feed:
            emit("collect", articles=0, snippet_tokens=0, feeds=0, total=0)
            return [], {}

        # Round-robin: layer by layer across feeds
        max_articles = cfg.edition_max_planner_articles
        ordered_ids = []
        feed_lists = list(by_feed.values())
        layer = 0
        while feed_lists and len(ordered_ids) < max_articles:
            remaining = []
            for articles in feed_lists:
                if len(ordered_ids) >= max_articles:
                    break
                if layer < len(articles):
                    ordered_ids.append(articles[layer].id)
                    if layer + 1 < len(articles):
                        remaining.append(articles)
            feed_lists = remaining
            layer += 1

        # Fetch full content only for the ordered articles
        ordered_articles = {
            a.id: a
            for a in Article.objects
            .select_related("feed")
            .filter(id__in=ordered_ids)
        }

        # Adaptive snippet to fit within budget
        article_count = len(ordered_ids)
        budget = cfg.edition_planner_budget_tokens
        overhead_per_card = 25
        available = budget - (article_count * overhead_per_card)
        snippet_tokens = min(cfg.edition_article_card_tokens, available // article_count) if available > 0 else 0

        # Build cards in round-robin order
        cards = []
        for aid in ordered_ids:
            a = ordered_articles.get(aid)
            if not a:
                continue
            snippet = ""
            if snippet_tokens > 0 and a.content:
                snippet = trim_to_tokens(sanitize_text(a.content), snippet_tokens)
            cards.append({
                "id": a.id,
                "title": a.title,
                "feed": a.feed.title if a.feed else "",
                "published": a.published.strftime("%Y-%m-%d %H:%M") if a.published else "",
                "snippet": snippet,
            })

        emit("collect", articles=len(cards), snippet_tokens=snippet_tokens,
             feeds=len(by_feed), total=total_count)
        logger.info("Collected %d/%d articles from %d feeds (snippet=%d tokens)",
                     len(cards), total_count, len(by_feed), snippet_tokens)
        return cards, ordered_articles

    # ── Step 3: Write (parallel) ────────────────────────────────

    def _write_parallel(self, digest, stories, articles_by_id, section_map,
                        default_lang, target_langs, all_langs, writer_schema,
                        cfg, emit) -> list[dict]:
        """Write all stories in parallel using ThreadPoolExecutor."""
        emit_lock = threading.Lock()
        cost_lock = threading.Lock()
        running_in = [0]
        running_out = [0]
        results = []

        def _emit(*args, **kwargs):
            with emit_lock:
                emit(*args, **kwargs)

        def write_one(idx, story):
            close_old_connections()
            t0 = time.monotonic()
            try:
                section = section_map.get(story.get("section"))
                if not section:
                    _emit("write_skip", index=idx,
                          label=story.get("label", "?"), reason="bad section")
                    return {"success": False, "input_tokens": 0, "output_tokens": 0}

                by_lang, usage = self.writer.write(
                    story, articles_by_id, all_langs, schema=writer_schema,
                )

                gen_ms = int((time.monotonic() - t0) * 1000)

                default_data = by_lang.get(default_lang.code, {})
                if not default_data.get("topic") or not default_data.get("summary"):
                    _emit("write_skip", index=idx,
                          label=story.get("label", "?"), reason="empty")
                    return {"success": False, "input_tokens": 0, "output_tokens": 0}

                article_ids = story.get("article_ids", [])[:cfg.edition_max_articles_per_story]

                item = self.saver.save_item(
                    digest, section, story, by_lang, article_ids,
                    default_lang, target_langs,
                )

                # Update ItemPipeline with per-item telemetry
                input_tok = usage.get("prompt_tokens", 0)
                output_tok = usage.get("completion_tokens", 0)
                cost = calculate_cost(cfg.chat_model, input_tok, output_tok)

                ItemPipeline.objects.filter(item=item).update(
                    input_tokens=input_tok,
                    output_tokens=output_tok,
                    cost_usd=cost,
                    generation_ms=gen_ms,
                    articles_in_context=len(article_ids),
                )

                record_digest_usage(usage, step=APIUsage.Step.GENERATE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=cfg.chat_model, digest=digest, item=item)

                with cost_lock:
                    running_in[0] += input_tok
                    running_out[0] += output_tok
                    running_cost = calculate_cost(cfg.chat_model, running_in[0], running_out[0])

                _emit("write_item", index=idx,
                      label=story.get("label", "?"),
                      section=story.get("section", "?"),
                      tokens=input_tok + output_tok,
                      cost=cost,
                      running_cost=running_cost)

                return {
                    "success": True,
                    "input_tokens": input_tok,
                    "output_tokens": output_tok,
                }
            except Exception:
                logger.exception("Write failed for story %d: %s",
                                 idx, story.get("label", "?"))
                _emit("write_skip", index=idx,
                      label=story.get("label", "?"), reason="error")
                return {"success": False, "input_tokens": 0, "output_tokens": 0}
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=cfg.edition_max_workers) as executor:
            futures = {
                executor.submit(write_one, i, story): i
                for i, story in enumerate(stories, 1)
            }
            for future in as_completed(futures):
                results.append(future.result())

        return results
