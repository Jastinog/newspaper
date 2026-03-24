import json
import logging
import re
import time

from apps.billing.models import APIUsage
from apps.feeds.models import ArticleChunk
from apps.deep_dive.models import DeepDive, DeepDiveSource
from apps.digest.models import DigestItem
from apps.core.services.ai import (
    EMBEDDING_MODEL, EmbeddingClient,
    MODEL_MINI, OpenAIClient, calculate_cost, fix_truncated_json,
)
from apps.core.services.utils import deduplicate_queries
from .search import SimilaritySearch

logger = logging.getLogger(__name__)


class QueryGenerator:
    """Generate diverse search queries from a digest section's title and summary."""

    def __init__(self, client: OpenAIClient = None):
        self.client = client or OpenAIClient()

    def _extract_entities(self, summary: str) -> list[str]:
        """Extract **bold phrases** from markdown summary as entity queries."""
        matches = re.findall(r'\*\*(.+?)\*\*', summary)
        seen = set()
        entities = []
        for m in matches:
            m_clean = m.strip().rstrip('—').strip()
            if m_clean.lower() not in seen and len(m_clean) > 2:
                seen.add(m_clean.lower())
                entities.append(m_clean)
                if len(entities) >= 3:
                    break
        return entities

    def _generate_llm_queries(self, topic: str, summary: str) -> tuple[list[str], dict]:
        """Use LLM to generate diverse search queries focused on a specific topic."""
        system = (
            "You generate search queries for a semantic search over a news article database. "
            "Given a specific news topic and its context, produce 4-6 diverse search queries that cover:\n"
            "- Key facts and events about this topic\n"
            "- Causes and reasons behind it\n"
            "- Consequences and implications\n"
            "- Broader context and background\n"
            "- Related events, actors, or organizations\n\n"
            "Output ONLY a JSON array of strings. No markdown fences."
        )
        user = f"Topic: {topic}\n\nContext:\n{summary[:1500]}"

        content, usage = self.client.chat(
            system=system,
            user=user,
            max_tokens=500,
            temperature=0.4,
        )

        fixed = fix_truncated_json(content)
        try:
            queries = json.loads(fixed)
            if isinstance(queries, list):
                return [q for q in queries if isinstance(q, str)][:6], usage
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM queries: %s", content[:200])

        return [], usage

    def generate(self, topic: str, section_title: str, summary: str) -> tuple[list[str], dict]:
        """Generate 6-9 diverse search queries from a specific topic + section context."""
        all_queries = [topic]
        entities = self._extract_entities(summary)
        all_queries.extend(entities)
        llm_queries, chat_usage = self._generate_llm_queries(topic, summary)
        all_queries.extend(llm_queries)
        return deduplicate_queries(all_queries, limit=9), chat_usage


class ArticleSynthesizer:
    """Synthesize a deep-dive analytical article from relevant chunks."""

    def __init__(self, client: OpenAIClient = None):
        self.client = client or OpenAIClient()

    SYSTEM_PROMPTS = {
        "en": (
            "You are a news analyst. Based on the provided article fragments, "
            "synthesize a deep analytical article in English about the SPECIFIC topic.\n\n"
            "Rules:\n"
            "- Length: 800-1500 words\n"
            "- Use markdown with subheadings (## sections)\n"
            "- Write analytically: don't just retell, analyze causes, consequences, context\n"
            "- Structure: introduction \u2192 key facts \u2192 analysis \u2192 context \u2192 conclusions\n"
            "- Don't invent facts \u2014 use only information from the provided fragments\n"
            "- Don't reference 'fragments' or 'sources' in the text \u2014 write as a cohesive article\n"
            "- Focus specifically on the indicated topic, don't diverge to others\n\n"
            "Response format \u2014 ONLY JSON, no markdown fences:\n"
            '{"title": "article title", "subtitle": "short subtitle (1 sentence)", '
            '"content": "markdown article text"}'
        ),
        "ru": (
            "\u0422\u044b \u2014 \u0430\u043d\u0430\u043b\u0438\u0442\u0438\u043a \u043d\u043e\u0432\u043e\u0441\u0442\u0435\u0439. \u041d\u0430 \u043e\u0441\u043d\u043e\u0432\u0435 \u043f\u0440\u0435\u0434\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u043e\u0432 \u0441\u0442\u0430\u0442\u0435\u0439 "
            "\u0441\u0438\u043d\u0442\u0435\u0437\u0438\u0440\u0443\u0439 \u0433\u043b\u0443\u0431\u043e\u043a\u0443\u044e \u0430\u043d\u0430\u043b\u0438\u0442\u0438\u0447\u0435\u0441\u043a\u0443\u044e \u0441\u0442\u0430\u0442\u044c\u044e \u043d\u0430 \u0440\u0443\u0441\u0441\u043a\u043e\u043c \u044f\u0437\u044b\u043a\u0435 \u043e \u041a\u041e\u041d\u041a\u0420\u0415\u0422\u041d\u041e\u0419 \u0442\u0435\u043c\u0435.\n\n"
            "\u041f\u0440\u0430\u0432\u0438\u043b\u0430:\n"
            "- \u041e\u0431\u044a\u0451\u043c: 800-1500 \u0441\u043b\u043e\u0432\n"
            "- \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 markdown \u0441 \u043f\u043e\u0434\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043a\u0430\u043c\u0438 (## \u0441\u0435\u043a\u0446\u0438\u0438)\n"
            "- \u041f\u0438\u0448\u0438 \u0430\u043d\u0430\u043b\u0438\u0442\u0438\u0447\u0435\u0441\u043a\u0438: \u043d\u0435 \u043f\u0440\u043e\u0441\u0442\u043e \u043f\u0435\u0440\u0435\u0441\u043a\u0430\u0437\u044b\u0432\u0430\u0439, \u0430 \u0430\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u0443\u0439 \u043f\u0440\u0438\u0447\u0438\u043d\u044b, \u043f\u043e\u0441\u043b\u0435\u0434\u0441\u0442\u0432\u0438\u044f, \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\n"
            "- \u0421\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0430: \u0432\u0432\u0435\u0434\u0435\u043d\u0438\u0435 \u2192 \u043a\u043b\u044e\u0447\u0435\u0432\u044b\u0435 \u0444\u0430\u043a\u0442\u044b \u2192 \u0430\u043d\u0430\u043b\u0438\u0437 \u2192 \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u2192 \u0432\u044b\u0432\u043e\u0434\u044b\n"
            "- \u041d\u0435 \u0432\u044b\u0434\u0443\u043c\u044b\u0432\u0430\u0439 \u0444\u0430\u043a\u0442\u044b \u2014 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 \u0442\u043e\u043b\u044c\u043a\u043e \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u044e \u0438\u0437 \u043f\u0440\u0435\u0434\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u043e\u0432\n"
            "- \u041d\u0435 \u0441\u0441\u044b\u043b\u0430\u0439\u0441\u044f \u043d\u0430 '\u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u044b' \u0438\u043b\u0438 '\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438' \u0432 \u0442\u0435\u043a\u0441\u0442\u0435 \u2014 \u043f\u0438\u0448\u0438 \u043a\u0430\u043a \u0446\u0435\u043b\u043e\u0441\u0442\u043d\u0443\u044e \u0441\u0442\u0430\u0442\u044c\u044e\n"
            "- \u0424\u043e\u043a\u0443\u0441\u0438\u0440\u0443\u0439\u0441\u044f \u0438\u043c\u0435\u043d\u043d\u043e \u043d\u0430 \u0443\u043a\u0430\u0437\u0430\u043d\u043d\u043e\u0439 \u0442\u0435\u043c\u0435, \u043d\u0435 \u043e\u0442\u0432\u043b\u0435\u043a\u0430\u0439\u0441\u044f \u043d\u0430 \u0434\u0440\u0443\u0433\u0438\u0435\n\n"
            "\u0424\u043e\u0440\u043c\u0430\u0442 \u043e\u0442\u0432\u0435\u0442\u0430 \u2014 \u0422\u041e\u041b\u042c\u041a\u041e JSON, \u0431\u0435\u0437 markdown-\u043e\u0433\u0440\u0430\u0434\u044b:\n"
            '{"title": "\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a \u0441\u0442\u0430\u0442\u044c\u0438", "subtitle": "\u043a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u043f\u043e\u0434\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a (1 \u043f\u0440\u0435\u0434\u043b\u043e\u0436\u0435\u043d\u0438\u0435)", '
            '"content": "markdown \u0442\u0435\u043a\u0441\u0442 \u0441\u0442\u0430\u0442\u044c\u0438"}'
        ),
        "uk": (
            "\u0422\u0438 \u2014 \u0430\u043d\u0430\u043b\u0456\u0442\u0438\u043a \u043d\u043e\u0432\u0438\u043d. \u041d\u0430 \u043e\u0441\u043d\u043e\u0432\u0456 \u043d\u0430\u0434\u0430\u043d\u0438\u0445 \u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u0456\u0432 \u0441\u0442\u0430\u0442\u0435\u0439 "
            "\u0441\u0438\u043d\u0442\u0435\u0437\u0443\u0439 \u0433\u043b\u0438\u0431\u043e\u043a\u0443 \u0430\u043d\u0430\u043b\u0456\u0442\u0438\u0447\u043d\u0443 \u0441\u0442\u0430\u0442\u0442\u044e \u0443\u043a\u0440\u0430\u0457\u043d\u0441\u044c\u043a\u043e\u044e \u043c\u043e\u0432\u043e\u044e \u043f\u0440\u043e \u041a\u041e\u041d\u041a\u0420\u0415\u0422\u041d\u0423 \u0442\u0435\u043c\u0443.\n\n"
            "\u041f\u0440\u0430\u0432\u0438\u043b\u0430:\n"
            "- \u041e\u0431\u0441\u044f\u0433: 800-1500 \u0441\u043b\u0456\u0432\n"
            "- \u0412\u0438\u043a\u043e\u0440\u0438\u0441\u0442\u043e\u0432\u0443\u0439 markdown \u0437 \u043f\u0456\u0434\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043a\u0430\u043c\u0438 (## \u0441\u0435\u043a\u0446\u0456\u0457)\n"
            "- \u041f\u0438\u0448\u0438 \u0430\u043d\u0430\u043b\u0456\u0442\u0438\u0447\u043d\u043e: \u043d\u0435 \u043f\u0440\u043e\u0441\u0442\u043e \u043f\u0435\u0440\u0435\u043a\u0430\u0437\u0443\u0439, \u0430 \u0430\u043d\u0430\u043b\u0456\u0437\u0443\u0439 \u043f\u0440\u0438\u0447\u0438\u043d\u0438, \u043d\u0430\u0441\u043b\u0456\u0434\u043a\u0438, \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\n"
            "- \u0421\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0430: \u0432\u0441\u0442\u0443\u043f \u2192 \u043a\u043b\u044e\u0447\u043e\u0432\u0456 \u0444\u0430\u043a\u0442\u0438 \u2192 \u0430\u043d\u0430\u043b\u0456\u0437 \u2192 \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u2192 \u0432\u0438\u0441\u043d\u043e\u0432\u043a\u0438\n"
            "- \u041d\u0435 \u0432\u0438\u0433\u0430\u0434\u0443\u0439 \u0444\u0430\u043a\u0442\u0438 \u2014 \u0432\u0438\u043a\u043e\u0440\u0438\u0441\u0442\u043e\u0432\u0443\u0439 \u043b\u0438\u0448\u0435 \u0456\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0456\u044e \u0437 \u043d\u0430\u0434\u0430\u043d\u0438\u0445 \u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u0456\u0432\n"
            "- \u041d\u0435 \u043f\u043e\u0441\u0438\u043b\u0430\u0439\u0441\u044f \u043d\u0430 '\u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u0438' \u0447\u0438 '\u0434\u0436\u0435\u0440\u0435\u043b\u0430' \u0432 \u0442\u0435\u043a\u0441\u0442\u0456 \u2014 \u043f\u0438\u0448\u0438 \u044f\u043a \u0446\u0456\u043b\u0456\u0441\u043d\u0443 \u0441\u0442\u0430\u0442\u0442\u044e\n"
            "- \u0424\u043e\u043a\u0443\u0441\u0443\u0439\u0441\u044f \u0441\u0430\u043c\u0435 \u043d\u0430 \u0432\u043a\u0430\u0437\u0430\u043d\u0456\u0439 \u0442\u0435\u043c\u0456, \u043d\u0435 \u0440\u043e\u0437\u043f\u0438\u043b\u044e\u0439\u0441\u044f \u043d\u0430 \u0456\u043d\u0448\u0456\n\n"
            "\u0424\u043e\u0440\u043c\u0430\u0442 \u0432\u0456\u0434\u043f\u043e\u0432\u0456\u0434\u0456 \u2014 \u0422\u0406\u041b\u042c\u041a\u0418 JSON, \u0431\u0435\u0437 markdown-\u043e\u0433\u043e\u0440\u043e\u0436\u0456:\n"
            '{"title": "\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a \u0441\u0442\u0430\u0442\u0442\u0456", "subtitle": "\u043a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u043f\u0456\u0434\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a (1 \u0440\u0435\u0447\u0435\u043d\u043d\u044f)", '
            '"content": "markdown \u0442\u0435\u043a\u0441\u0442 \u0441\u0442\u0430\u0442\u0442\u0456"}'
        ),
    }

    USER_TEMPLATES = {
        "en": "Specific topic: {topic}\nDigest section: {section_title}\n\nFragments from relevant articles:\n\n{context}",
        "ru": "\u041a\u043e\u043d\u043a\u0440\u0435\u0442\u043d\u0430\u044f \u0442\u0435\u043c\u0430: {topic}\n\u0420\u0430\u0437\u0434\u0435\u043b \u0434\u0430\u0439\u0434\u0436\u0435\u0441\u0442\u0430: {section_title}\n\n\u0424\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u044b \u0438\u0437 \u0440\u0435\u043b\u0435\u0432\u0430\u043d\u0442\u043d\u044b\u0445 \u0441\u0442\u0430\u0442\u0435\u0439:\n\n{context}",
        "uk": "\u041a\u043e\u043d\u043a\u0440\u0435\u0442\u043d\u0430 \u0442\u0435\u043c\u0430: {topic}\n\u0420\u043e\u0437\u0434\u0456\u043b \u0434\u0430\u0439\u0434\u0436\u0435\u0441\u0442\u0443: {section_title}\n\n\u0424\u0440\u0430\u0433\u043c\u0435\u043d\u0442\u0438 \u0437 \u0440\u0435\u043b\u0435\u0432\u0430\u043d\u0442\u043d\u0438\u0445 \u0441\u0442\u0430\u0442\u0435\u0439:\n\n{context}",
    }

    def synthesize(self, topic: str, section_title: str, chunks_by_article: dict, language: str = "uk") -> dict:
        """Generate an analytical article about a specific topic from relevant chunks."""
        context_parts = []
        for article_title, chunks in chunks_by_article.items():
            text = "\n".join(chunks)
            context_parts.append(f"### {article_title}\n{text}")

        context = "\n\n---\n\n".join(context_parts)

        system = self.SYSTEM_PROMPTS.get(language, self.SYSTEM_PROMPTS["en"])
        user_template = self.USER_TEMPLATES.get(language, self.USER_TEMPLATES["en"])
        user = user_template.format(topic=topic, section_title=section_title, context=context[:12000])

        content, usage = self.client.chat(
            system=system,
            user=user,
            max_tokens=4000,
            temperature=0.4,
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
            return {
                "title": data.get("title", topic),
                "subtitle": data.get("subtitle", ""),
                "content": data.get("content", ""),
                "usage": usage,
            }
        except json.JSONDecodeError:
            logger.error("Failed to parse synthesized article: %s", content[:300])
            return {
                "title": topic,
                "subtitle": "",
                "content": content,
                "usage": usage,
            }


class DeepDiveService:
    """Orchestrates the full deep-dive pipeline: queries \u2192 embed \u2192 search \u2192 synthesize \u2192 save."""

    STEPS = [
        (1, "queries", "Generating search queries\u2026"),
        (2, "embedding", "Creating embeddings\u2026"),
        (3, "search", "Searching relevant articles\u2026"),
        (4, "grouping", "Grouping content\u2026"),
        (5, "synthesis", "Synthesizing article\u2026"),
        (6, "saving", "Saving result\u2026"),
    ]
    TOTAL_STEPS = len(STEPS)

    def __init__(self):
        self.query_gen = QueryGenerator()
        self.embedder = EmbeddingClient()
        self.search = SimilaritySearch(days=30)
        self.synthesizer = ArticleSynthesizer()

    def _progress(self, callback, step_number, step_id, label, detail=None):
        if callback:
            callback(step_number, self.TOTAL_STEPS, step_id, label, detail)

    def generate(self, item: DigestItem, progress_callback=None) -> DeepDive:
        """Generate a deep dive for a DigestItem."""
        start = time.time()

        # 1. Generate search queries
        self._progress(progress_callback, 1, "queries", "Generating search queries\u2026")
        queries, query_gen_usage = self.query_gen.generate(item.topic, item.section.title, item.summary)
        logger.info("Generated %d search queries for '%s'", len(queries), item.topic)

        if not queries:
            raise RuntimeError(f"No queries generated for: {item.topic}")

        # 2. Embed queries
        self._progress(progress_callback, 2, "embedding", "Creating embeddings\u2026",
                        f"{len(queries)} queries")
        query_embeddings, embed_tokens = self.embedder.embed_batch(queries)

        # 3. Multi-query similarity search
        self._progress(progress_callback, 3, "search", "Searching relevant articles\u2026")
        search_results = self.search.multi_query_search(
            query_embeddings,
            top_k_per_query=15,
            final_top_k=20,
        )
        logger.info("Found %d relevant chunks", len(search_results))

        if not search_results:
            raise RuntimeError(f"No relevant chunks found for: {item.topic}")

        # 4. Load chunk texts and group by article
        self._progress(progress_callback, 4, "grouping", "Grouping content\u2026",
                        f"{len(search_results)} chunks")
        chunk_ids = [r[0] for r in search_results]
        chunks = ArticleChunk.objects.filter(id__in=chunk_ids).select_related("article")
        chunk_map = {c.id: c for c in chunks}

        article_ids_seen = []
        article_scores = {}
        chunks_by_article = {}

        for chunk_id, article_id, _, score in search_results:
            chunk = chunk_map.get(chunk_id)
            if not chunk:
                continue
            article_title = chunk.article.title
            if article_title not in chunks_by_article:
                chunks_by_article[article_title] = []
                article_ids_seen.append(article_id)
            chunks_by_article[article_title].append(chunk.chunk_text)
            if article_id not in article_scores or score > article_scores[article_id]:
                article_scores[article_id] = score

        # 5. Synthesize article
        self._progress(progress_callback, 5, "synthesis", "Synthesizing article\u2026",
                        f"{len(chunks_by_article)} sources")
        language = getattr(item.section.digest, "language", "uk")
        result = self.synthesizer.synthesize(item.topic, item.section.title, chunks_by_article, language=language)

        elapsed_ms = int((time.time() - start) * 1000)

        # 6. Save DeepDive
        self._progress(progress_callback, 6, "saving", "Saving result\u2026")
        dive = DeepDive.objects.create(
            item=item,
            title=result["title"],
            subtitle=result["subtitle"],
            content=result["content"],
            search_queries=queries,
            chunks_used=len(search_results),
            generation_time_ms=elapsed_ms,
        )

        # 7. Save DeepDiveSources
        sources = []
        for order, article_id in enumerate(article_ids_seen):
            sources.append(DeepDiveSource(
                deep_dive=dive,
                article_id=article_id,
                relevance=article_scores.get(article_id, 0.0),
                order=order,
            ))
        DeepDiveSource.objects.bulk_create(sources)

        # 8. Log API usage
        synthesis_usage = result.get("usage", {})

        def _log_chat_usage(usage):
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            return APIUsage(
                service=APIUsage.Service.DEEP_DIVE,
                api_type=APIUsage.APIType.CHAT,
                model=MODEL_MINI,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=usage.get("total_tokens", 0),
                cost_usd=calculate_cost(MODEL_MINI, pt, ct),
                deep_dive=dive,
            )

        usages = [
            _log_chat_usage(query_gen_usage),
            _log_chat_usage(synthesis_usage),
            APIUsage(
                service=APIUsage.Service.DEEP_DIVE,
                api_type=APIUsage.APIType.EMBEDDING,
                model=EMBEDDING_MODEL,
                prompt_tokens=embed_tokens,
                completion_tokens=0,
                total_tokens=embed_tokens,
                cost_usd=calculate_cost(EMBEDDING_MODEL, embed_tokens),
                deep_dive=dive,
            ),
        ]
        APIUsage.objects.bulk_create(usages)

        logger.info(
            "Deep dive generated for '%s': %d sources, %dms",
            item.topic, len(sources), elapsed_ms,
        )

        return dive
