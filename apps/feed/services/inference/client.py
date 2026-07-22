"""HTTP client for the remote ONNX inference service (embed + classify).

The heavy BGE embedder and DeBERTa zero-shot classifier can be offloaded to a
separate host (see the `run_inference_server` management command) so they don't
consume RAM/CPU on the harvester's shared box. When `INFERENCE_SERVICE_URL` is
set, the harvester's document-embedding and classification calls go over HTTP to
that service; otherwise everything runs locally in-process, unchanged.

Search *query* embedding intentionally stays local (it's latency-sensitive and
lives in the web process), so this client is only wired into the background
harvester paths (`embed_article`, `classify_article`).
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

URL = os.environ.get("INFERENCE_SERVICE_URL", "").rstrip("/")
SECRET = os.environ.get("INFERENCE_SERVICE_SECRET", "")
TIMEOUT = float(os.environ.get("INFERENCE_SERVICE_TIMEOUT", "30"))
# Absorb transient tunnel/network blips so a single hiccup doesn't trip the
# enrichment stage's degraded latch (which would stall it until the next restart).
RETRIES = max(1, int(os.environ.get("INFERENCE_SERVICE_RETRIES", "3")))
BACKOFF = 0.5


def remote_enabled() -> bool:
    """True when a remote inference service is configured; else use local models."""
    return bool(URL)


def _post(path: str, payload: dict) -> dict:
    last_exc = None
    for attempt in range(RETRIES):
        try:
            resp = requests.post(
                f"{URL}{path}",
                json=payload,
                headers={"X-Inference-Secret": SECRET},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < RETRIES - 1:
                time.sleep(BACKOFF * (attempt + 1))
    raise RuntimeError(f"inference service {path} failed after {RETRIES} attempts") from last_exc


def embed(texts, is_query: bool = False) -> list[list[float]]:
    """Embed a batch of texts remotely → list of float vectors (one per text)."""
    if not texts:
        return []
    data = _post("/embed", {"texts": list(texts), "is_query": is_query})
    return data["vectors"]


def classify(title: str, content: str = "") -> list[tuple[str, float]]:
    """Classify one article remotely → [(topic_slug, score), …], highest first."""
    data = _post("/classify", {"title": title, "content": content})
    return [(slug, float(score)) for slug, score in data["topics"]]
