import json
import logging
import os
import re
import time

import requests

from .embeddings import MODEL as EMBEDDING_MODEL

logger = logging.getLogger(__name__)

MODEL_MINI = "gpt-4.1-mini"

# Pricing per 1M tokens (USD)
GPT41_MINI_INPUT_PRICE = 0.40
GPT41_MINI_OUTPUT_PRICE = 1.60
EMBEDDING_PRICE = 0.02


def calculate_cost(model, prompt_tokens, completion_tokens=0):
    """Calculate cost in USD based on model and token counts."""
    if model == MODEL_MINI:
        return (prompt_tokens * GPT41_MINI_INPUT_PRICE + completion_tokens * GPT41_MINI_OUTPUT_PRICE) / 1_000_000
    if model == EMBEDDING_MODEL:
        return (prompt_tokens + completion_tokens) * EMBEDDING_PRICE / 1_000_000
    return 0


class OpenAIError(Exception):
    pass


class OpenAIClient:
    """Thin wrapper around the OpenAI Chat Completions API."""

    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise OpenAIError("OPENAI_API_KEY is not set")

    def chat(self, *, system, user, model=MODEL_MINI, max_tokens=8000, temperature=0.3):
        """Send a chat completion request with retries for transient errors."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_err = ""
        for attempt in range(3):
            if attempt > 0:
                time.sleep(2 ** attempt)

            try:
                resp = requests.post(
                    self.API_URL, json=payload, headers=headers, timeout=120,
                )
            except requests.RequestException as e:
                last_err = f"Request failed: {e}"
                continue

            if resp.ok:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})
                return content, usage

            last_err = f"OpenAI API error {resp.status_code}: {resp.text[:500]}"
            # Don't retry auth errors or client errors (except 429)
            if resp.status_code != 429 and resp.status_code < 500:
                raise OpenAIError(last_err)

        raise OpenAIError(f"{last_err} (after 3 attempts)")


def fix_truncated_json(s: str) -> str:
    """Attempt to fix truncated JSON from GPT (e.g. when max_tokens cuts off)."""
    s = s.strip()
    # Strip markdown fences
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)

    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        pass

    # Track nesting to close open brackets
    stack = []
    in_str = False
    prev_escape = False

    for ch in s:
        if in_str:
            if ch == '"' and not prev_escape:
                in_str = False
            prev_escape = ch == '\\' and not prev_escape
            continue
        prev_escape = False
        if ch == '"':
            in_str = True
        elif ch in ('{', '['):
            stack.append(ch)
        elif ch in ('}', ']'):
            if stack:
                stack.pop()

    # If ended inside a string, truncate to last quote
    if in_str:
        pos = s.rfind('"')
        if pos > 0:
            s = s[:pos] + '"'
            # Recount stack
            stack = []
            in_str = False
            prev_escape = False
            for ch in s:
                if in_str:
                    if ch == '"' and not prev_escape:
                        in_str = False
                    prev_escape = ch == '\\' and not prev_escape
                    continue
                prev_escape = False
                if ch == '"':
                    in_str = True
                elif ch in ('{', '['):
                    stack.append(ch)
                elif ch in ('}', ']'):
                    if stack:
                        stack.pop()

    # Remove trailing comma
    s = s.rstrip()
    if s.endswith(','):
        s = s[:-1]

    # Close open brackets in reverse order
    for opener in reversed(stack):
        s += '}' if opener == '{' else ']'

    return s
