import json
import logging
import re
import time

from apps.billing.models import APIUsage
from apps.core.models import Language
from apps.feed.models import ArticleChunk
from apps.research.models import Research, ResearchSource
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
    """Synthesize a research article from relevant chunks."""

    def __init__(self, client: OpenAIClient = None):
        self.client = client or OpenAIClient()

    SYSTEM_PROMPTS = {
        "en": (
            "You are an investigative journalist writing for a quality publication. "
            "Based on the provided article fragments, write a compelling research piece in English about the SPECIFIC topic.\n\n"
            "Writing style:\n"
            "- Write like a seasoned journalist, not a textbook — the reader should want to keep reading\n"
            "- Open with a vivid hook: a striking detail, a paradox, a key quote, or a scene that pulls the reader in\n"
            "- Build a narrative arc — don't just list facts, connect them into a story with tension and stakes\n"
            "- Show, don't tell: use concrete details, numbers, names, and specific examples\n"
            "- Ask the questions the reader is thinking, then answer them\n"
            "- Vary paragraph length and rhythm — mix short punchy sentences with longer explanatory ones\n"
            "- End with an insight or forward-looking thought that stays with the reader\n\n"
            "Rules:\n"
            "- Length: 800-1500 words\n"
            "- Use markdown with compelling subheadings (## sections) — subheadings should intrigue, not just label\n"
            "- Don't invent facts — use only information from the provided fragments\n"
            "- Don't reference 'fragments' or 'sources' in the text — write as a cohesive article\n"
            "- Focus specifically on the indicated topic, don't diverge to others\n\n"
            "Response format — ONLY JSON, no markdown fences:\n"
            '{"title": "article title", "subtitle": "short subtitle (1 sentence)", '
            '"content": "markdown article text"}'
        ),
        "ru": (
            "Ты — журналист-расследователь, пишущий для качественного издания. "
            "На основе предоставленных фрагментов статей напиши увлекательный материал-исследование на русском языке о КОНКРЕТНОЙ теме.\n\n"
            "Стиль письма:\n"
            "- Пиши как опытный журналист, а не как учебник — читатель должен хотеть читать дальше\n"
            "- Начни с яркого крючка: поразительная деталь, парадокс, ключевая цитата или сцена, которая затягивает\n"
            "- Строй нарратив — не просто перечисляй факты, а связывай их в историю с интригой и ставками\n"
            "- Показывай, а не рассказывай: конкретные детали, цифры, имена, живые примеры\n"
            "- Задавай вопросы, которые возникают у читателя, и тут же отвечай на них\n"
            "- Чередуй длину абзацев — короткие хлёсткие предложения с развёрнутыми пояснениями\n"
            "- Заверши мыслью или прогнозом, который останется с читателем\n\n"
            "Правила:\n"
            "- Объём: 800-1500 слов\n"
            "- Используй markdown с интригующими подзаголовками (## секции) — подзаголовки должны цеплять, а не просто обозначать тему\n"
            "- Не выдумывай факты — используй только информацию из предоставленных фрагментов\n"
            "- Не ссылайся на 'фрагменты' или 'источники' в тексте — пиши как целостную статью\n"
            "- Фокусируйся именно на указанной теме, не отвлекайся на другие\n\n"
            "Формат ответа — ТОЛЬКО JSON, без markdown-ограды:\n"
            '{"title": "заголовок статьи", "subtitle": "короткий подзаголовок (1 предложение)", '
            '"content": "markdown текст статьи"}'
        ),
        "uk": (
            "Ти — журналіст-розслідувач, що пише для якісного видання. "
            "На основі наданих фрагментів статей напиши захопливий матеріал-дослідження українською мовою про КОНКРЕТНУ тему.\n\n"
            "Стиль письма:\n"
            "- Пиши як досвідчений журналіст, а не як підручник — читач має хотіти читати далі\n"
            "- Почни з яскравого гачка: вражаюча деталь, парадокс, ключова цитата або сцена, що затягує\n"
            "- Будуй наратив — не просто перелічуй факти, а пов'язуй їх в історію з інтригою та ставками\n"
            "- Показуй, а не розповідай: конкретні деталі, цифри, імена, живі приклади\n"
            "- Став питання, які виникають у читача, і одразу відповідай на них\n"
            "- Чередуй довжину абзаців — короткі влучні речення з розгорнутими поясненнями\n"
            "- Заверши думкою або прогнозом, що залишиться з читачем\n\n"
            "Правила:\n"
            "- Обсяг: 800-1500 слів\n"
            "- Використовуй markdown з інтригуючими підзаголовками (## секції) — підзаголовки мають чіпляти, а не просто позначати тему\n"
            "- Не вигадуй факти — використовуй лише інформацію з наданих фрагментів\n"
            "- Не посилайся на 'фрагменти' чи 'джерела' в тексті — пиши як цілісну статтю\n"
            "- Фокусуйся саме на вказаній темі, не розпилюйся на інші\n\n"
            "Формат відповіді — ТІЛЬКИ JSON, без markdown-огорожі:\n"
            '{"title": "заголовок статті", "subtitle": "короткий підзаголовок (1 речення)", '
            '"content": "markdown текст статті"}'
        ),
    }

    USER_TEMPLATES = {
        "en": "Specific topic: {topic}\nDigest section: {section_title}\n\nFragments from relevant articles:\n\n{context}",
        "ru": "Конкретная тема: {topic}\nРаздел дайджеста: {section_title}\n\nФрагменты из релевантных статей:\n\n{context}",
        "uk": "Конкретна тема: {topic}\nРозділ дайджесту: {section_title}\n\nФрагменти з релевантних статей:\n\n{context}",
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
            temperature=0.7,
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


class ResearchService:
    """Orchestrates the full research pipeline: queries → embed → search → synthesize → save."""

    # Embeddings perform better with English queries regardless of output language
    QUERY_LANGUAGE = "en"

    STEPS = [
        (1, "queries", "Generating search queries…"),
        (2, "embedding", "Creating embeddings…"),
        (3, "search", "Searching relevant articles…"),
        (4, "grouping", "Grouping content…"),
        (5, "synthesis", "Synthesizing article…"),
        (6, "saving", "Saving result…"),
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

    def generate(self, item: DigestItem, language="en", progress_callback=None) -> Research:
        """Generate a research article for a DigestItem in the given language."""
        start = time.time()

        # 1. Generate search queries
        self._progress(progress_callback, 1, "queries", "Generating search queries…")
        item_topic = item.get_topic(self.QUERY_LANGUAGE)
        item_summary = item.get_summary(self.QUERY_LANGUAGE)
        section_name = item.section.get_name(self.QUERY_LANGUAGE) if item.section else ""
        queries, query_gen_usage = self.query_gen.generate(item_topic, section_name, item_summary)
        logger.info("Generated %d search queries for '%s'", len(queries), item_topic)

        if not queries:
            raise RuntimeError(f"No queries generated for: {item_topic}")

        # 2. Embed queries
        self._progress(progress_callback, 2, "embedding", "Creating embeddings…",
                        f"{len(queries)} queries")
        query_embeddings, embed_tokens = self.embedder.embed_batch(queries)

        # 3. Multi-query similarity search
        self._progress(progress_callback, 3, "search", "Searching relevant articles…")
        search_results = self.search.multi_query_search(
            query_embeddings,
            top_k_per_query=15,
            final_top_k=20,
        )
        logger.info("Found %d relevant chunks", len(search_results))

        if not search_results:
            raise RuntimeError(f"No relevant chunks found for: {item_topic}")

        # 4. Load chunk texts and group by article
        self._progress(progress_callback, 4, "grouping", "Grouping content…",
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
        self._progress(progress_callback, 5, "synthesis", "Synthesizing article…",
                        f"{len(chunks_by_article)} sources")
        result = self.synthesizer.synthesize(item_topic, section_name, chunks_by_article, language=language)

        elapsed_ms = int((time.time() - start) * 1000)

        # 6. Save Research
        self._progress(progress_callback, 6, "saving", "Saving result…")
        lang_obj = Language.get_by_code(language)
        dive = Research.objects.create(
            item=item,
            language=lang_obj,
            title=result["title"],
            subtitle=result["subtitle"],
            content=result["content"],
            search_queries=queries,
            chunks_used=len(search_results),
            generation_time_ms=elapsed_ms,
        )

        # 7. Save ResearchSources
        sources = []
        for order, article_id in enumerate(article_ids_seen):
            sources.append(ResearchSource(
                research=dive,
                article_id=article_id,
                relevance=article_scores.get(article_id, 0.0),
                order=order,
            ))
        ResearchSource.objects.bulk_create(sources)

        # 8. Log API usage
        synthesis_usage = result.get("usage", {})

        def _log_chat_usage(usage):
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            return APIUsage(
                service=APIUsage.Service.RESEARCH,
                api_type=APIUsage.APIType.CHAT,
                model=MODEL_MINI,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=usage.get("total_tokens", 0),
                cost_usd=calculate_cost(MODEL_MINI, pt, ct),
                research=dive,
            )

        usages = [
            _log_chat_usage(query_gen_usage),
            _log_chat_usage(synthesis_usage),
            APIUsage(
                service=APIUsage.Service.RESEARCH,
                api_type=APIUsage.APIType.EMBEDDING,
                model=EMBEDDING_MODEL,
                prompt_tokens=embed_tokens,
                completion_tokens=0,
                total_tokens=embed_tokens,
                cost_usd=calculate_cost(EMBEDDING_MODEL, embed_tokens),
                research=dive,
            ),
        ]
        APIUsage.objects.bulk_create(usages)

        logger.info(
            "Research generated for '%s': %d sources, %dms",
            item_topic, len(sources), elapsed_ms,
        )

        return dive
