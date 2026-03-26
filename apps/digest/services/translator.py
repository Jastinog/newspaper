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
        """Translate a single item's topic and summary to the target language.

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
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            logger.warning("Failed to parse translation to %s, using empty", language_name)
            data = {"topic": topic, "summary": summary}

        return data, usage

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
