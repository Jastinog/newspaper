import json
import logging

from apps.core.services.ai import OpenAIClient, fix_truncated_json
from apps.digest.models import DigestConfig

logger = logging.getLogger(__name__)


class ItemTranslator:
    """Translates digest items and headlines to target languages."""

    def __init__(self, client: OpenAIClient = None, config: DigestConfig = None):
        self.client = client or OpenAIClient()
        self.config = config or DigestConfig.get()

    def translate_item(self, topic: str, summary: str, language_name: str) -> tuple[dict, dict]:
        """Translate a single item's topic and summary to one language.

        Returns:
            ({"topic": str, "summary": str}, usage)
        """
        cfg = self.config
        system = cfg.system_prompt_translation.format(language=language_name)
        user = (
            f"Topic: {topic}\n\n"
            f"Summary: {summary}"
        )

        content, usage = self.client.chat(
            system=system,
            user=user,
            model=cfg.chat_model,
            max_tokens=cfg.max_tokens_translation,
            temperature=cfg.temperature,
            response_format={"type": "json_object"},
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            logger.warning("Failed to parse translation to %s, using empty", language_name)
            data = {"topic": topic, "summary": summary}

        return data, usage

    def translate_item_multilang(self, topic: str, summary: str,
                                 languages: list[tuple[str, str]]) -> tuple[dict, dict]:
        """Translate a single item to all target languages in one API call.

        Args:
            topic: English topic
            summary: English summary
            languages: [(language_code, language_name), ...]

        Returns:
            ({language_code: {"topic": str, "summary": str}, ...}, usage)
        """
        if not languages:
            return {}, {}

        cfg = self.config
        lang_names = [name for _, name in languages]
        lang_list = ", ".join(lang_names)

        system = (
            f"You are a professional translator. Translate the following news item "
            f"to each of these languages: {lang_list}.\n"
            "Maintain journalistic style, factual accuracy, and nuance. "
            "Adapt idioms and cultural references naturally. "
            "Do not add or remove information.\n\n"
            'Return JSON with key "translations" containing an array of objects, '
            "one per language in the same order, each with: "
            '"language", "topic", "summary".'
        )
        user = f"Topic: {topic}\n\nSummary: {summary}"

        max_tokens = cfg.max_tokens_translation * len(languages)

        content, usage = self.client.chat(
            system=system,
            user=user,
            model=cfg.chat_model,
            max_tokens=max_tokens,
            temperature=cfg.temperature,
            response_format={"type": "json_object"},
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
            translations = data.get("translations", [])
        except json.JSONDecodeError:
            logger.warning("Multilang translation failed to parse")
            translations = []

        result = {}
        if len(translations) == len(languages):
            for (code, _), t in zip(languages, translations):
                result[code] = {
                    "topic": t.get("topic", "") or topic,
                    "summary": t.get("summary", "") or summary,
                }
        else:
            # Fallback: translate individually per language
            if translations:
                logger.warning("Multilang translation count mismatch (%d vs %d), using individual",
                               len(translations), len(languages))
            total_usage = dict(usage)
            for code, name in languages:
                t_data, t_usage = self.translate_item(topic, summary, name)
                result[code] = t_data
                for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    total_usage[k] = total_usage.get(k, 0) + t_usage.get(k, 0)
            return result, total_usage

        return result, usage

    def translate_headline(self, headline: str, language_name: str) -> tuple[str, dict]:
        """Translate a headline to the target language.

        Returns:
            (translated_headline, usage)
        """
        if not headline:
            return "", {}

        cfg = self.config
        system = (
            f"Translate the following news headline from English to {language_name}. "
            "Maintain journalistic tone. Output ONLY the translated text, no JSON."
        )

        content, usage = self.client.chat(
            system=system,
            user=headline,
            model=cfg.chat_model,
            max_tokens=cfg.max_tokens_translation,
            temperature=cfg.temperature,
        )

        return content.strip().strip('"'), usage
