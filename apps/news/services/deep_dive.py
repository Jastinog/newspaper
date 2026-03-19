import json
import logging
import re
import time

from apps.news.models import APIUsage, ArticleChunk, DeepDive, DeepDiveSource, DigestItem
from apps.news.services.embeddings import MODEL as EMBEDDING_MODEL
from apps.news.services.embeddings import EmbeddingClient
from apps.news.services.openai_client import MODEL_MINI, OpenAIClient, calculate_cost, fix_truncated_json
from apps.news.services.search import SimilaritySearch

logger = logging.getLogger(__name__)


class QueryGenerator:
    """Generate diverse search queries from a digest section's title and summary."""

    def __init__(self, client: OpenAIClient = None):
        self.client = client or OpenAIClient()

    def _extract_entities(self, summary: str) -> list[str]:
        """Extract **bold phrases** from markdown summary as entity queries."""
        matches = re.findall(r'\*\*(.+?)\*\*', summary)
        # Take up to 3 unique entities
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
        """Use LLM to generate diverse search queries focused on a specific topic.

        Returns (queries, usage_dict).
        """
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
        """Generate 6-9 diverse search queries from a specific topic + section context.

        Returns (queries, chat_usage_dict).
        """
        # The topic itself is always the first query
        all_queries = [topic]
        # Extract entities from summary for extra context
        entities = self._extract_entities(summary)
        all_queries.extend(entities)
        # LLM generates diverse queries focused on the specific topic
        llm_queries, chat_usage = self._generate_llm_queries(topic, summary)
        all_queries.extend(llm_queries)
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for q in all_queries:
            q_lower = q.lower().strip()
            if q_lower not in seen:
                seen.add(q_lower)
                unique.append(q)
        return unique[:9], chat_usage


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
            "- Structure: introduction → key facts → analysis → context → conclusions\n"
            "- Don't invent facts — use only information from the provided fragments\n"
            "- Don't reference 'fragments' or 'sources' in the text — write as a cohesive article\n"
            "- Focus specifically on the indicated topic, don't diverge to others\n\n"
            "Response format — ONLY JSON, no markdown fences:\n"
            '{"title": "article title", "subtitle": "short subtitle (1 sentence)", '
            '"content": "markdown article text"}'
        ),
        "ru": (
            "Ты — аналитик новостей. На основе предоставленных фрагментов статей "
            "синтезируй глубокую аналитическую статью на русском языке о КОНКРЕТНОЙ теме.\n\n"
            "Правила:\n"
            "- Объём: 800-1500 слов\n"
            "- Используй markdown с подзаголовками (## секции)\n"
            "- Пиши аналитически: не просто пересказывай, а анализируй причины, последствия, контекст\n"
            "- Структура: введение → ключевые факты → анализ → контекст → выводы\n"
            "- Не выдумывай факты — используй только информацию из предоставленных фрагментов\n"
            "- Не ссылайся на 'фрагменты' или 'источники' в тексте — пиши как целостную статью\n"
            "- Фокусируйся именно на указанной теме, не отвлекайся на другие\n\n"
            "Формат ответа — ТОЛЬКО JSON, без markdown-ограды:\n"
            '{"title": "заголовок статьи", "subtitle": "короткий подзаголовок (1 предложение)", '
            '"content": "markdown текст статьи"}'
        ),
        "uk": (
            "Ти — аналітик новин. На основі наданих фрагментів статей "
            "синтезуй глибоку аналітичну статтю українською мовою про КОНКРЕТНУ тему.\n\n"
            "Правила:\n"
            "- Обсяг: 800-1500 слів\n"
            "- Використовуй markdown з підзаголовками (## секції)\n"
            "- Пиши аналітично: не просто переказуй, а аналізуй причини, наслідки, контекст\n"
            "- Структура: вступ → ключові факти → аналіз → контекст → висновки\n"
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
        """Generate an analytical article about a specific topic from relevant chunks.

        Args:
            topic: The specific news topic (bold phrase from bullet)
            section_title: Parent section title for context
            chunks_by_article: {article_title: [chunk_texts]}
            language: Target language code (en, ru, uk)

        Returns:
            {"title": str, "subtitle": str, "content": str}  (content is markdown)
        """
        # Build context from chunks
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
            # Fallback: use raw content as markdown
            return {
                "title": topic,
                "subtitle": "",
                "content": content,
                "usage": usage,
            }


class DeepDiveService:
    """Orchestrates the full deep-dive pipeline: queries → embed → search → synthesize → save."""

    def __init__(self):
        self.query_gen = QueryGenerator()
        self.embedder = EmbeddingClient()
        self.search = SimilaritySearch(days=30)
        self.synthesizer = ArticleSynthesizer()

    def generate(self, item: DigestItem) -> DeepDive:
        """Generate a deep dive for a DigestItem."""
        start = time.time()

        # 1. Generate search queries from item's topic and summary
        queries, query_gen_usage = self.query_gen.generate(item.topic, item.section.title, item.summary)
        logger.info("Generated %d search queries for '%s'", len(queries), item.topic)

        if not queries:
            raise RuntimeError(f"No queries generated for: {item.topic}")

        # 2. Embed queries
        query_embeddings, embed_tokens = self.embedder.embed_batch(queries)

        # 3. Multi-query similarity search
        search_results = self.search.multi_query_search(
            query_embeddings,
            top_k_per_query=15,
            final_top_k=20,
        )
        logger.info("Found %d relevant chunks", len(search_results))

        if not search_results:
            raise RuntimeError(f"No relevant chunks found for: {item.topic}")

        # 4. Load chunk texts and group by article
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
        language = getattr(item.section.digest, "language", "uk")
        result = self.synthesizer.synthesize(item.topic, item.section.title, chunks_by_article, language=language)

        elapsed_ms = int((time.time() - start) * 1000)

        # 6. Save DeepDive
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

        # 8. Log API usage for all 3 calls
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
