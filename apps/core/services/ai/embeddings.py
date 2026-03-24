import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"
BATCH_SIZE = 20
API_URL = "https://api.openai.com/v1/embeddings"


class EmbeddingError(Exception):
    pass


class EmbeddingClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise EmbeddingError("OPENAI_API_KEY is not set")

    def embed_batch(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """Call OpenAI Embeddings API with retry. Returns (embeddings, total_tokens)."""
        payload = {
            "model": MODEL,
            "input": texts,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_err = ""
        for attempt in range(3):
            if attempt > 0:
                time.sleep(2 ** attempt)  # 2s, 4s

            try:
                resp = requests.post(API_URL, json=payload, headers=headers, timeout=120)
            except requests.RequestException as e:
                last_err = f"Request failed: {e}"
                continue

            if resp.ok:
                data = resp.json()
                # Sort by index to preserve order
                items = sorted(data["data"], key=lambda d: d["index"])
                embeddings = [d["embedding"] for d in items]
                total_tokens = data.get("usage", {}).get("total_tokens", 0)
                return embeddings, total_tokens

            last_err = f"OpenAI Embeddings API error {resp.status_code}: {resp.text[:500]}"

            # Don't retry auth errors
            if resp.status_code in (401, 403):
                raise EmbeddingError(last_err)

            # Retry on 429 and 5xx only; other 4xx are permanent
            if resp.status_code != 429 and resp.status_code < 500:
                raise EmbeddingError(last_err)

        raise EmbeddingError(f"{last_err} (after 3 attempts)")
