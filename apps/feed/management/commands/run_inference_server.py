"""HTTP inference service: serves the BGE embedder + DeBERTa zero-shot classifier
over a tiny JSON API so a harvester on another host can offload this CPU/RAM-heavy
work here. Dependency-free (stdlib http.server); the model code is the exact same
lazy singletons the in-process path uses, so versions stay in sync via git.

Binds to localhost only — it is meant to sit behind an SSH tunnel — and requires
a shared secret (`INFERENCE_SERVICE_SECRET`) on every request. It never touches
the database.

    POST /embed     {"texts": [...], "is_query": false} -> {"vectors": [[...], ...]}
    POST /classify  {"title": "...", "content": "..."}   -> {"topics": [["slug", 0.9], ...]}
    GET  /health                                          -> {"ok": true}
"""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

SECRET = os.environ.get("INFERENCE_SERVICE_SECRET", "")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive across a client's many calls

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not SECRET or self.headers.get("X-Inference-Secret") != SECRET:
            self._send(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "bad request"})
            return
        try:
            if self.path == "/embed":
                self._send(200, {"vectors": self._embed(payload)})
            elif self.path == "/classify":
                self._send(200, {"topics": self._classify(payload)})
            else:
                self._send(404, {"error": "not found"})
        except Exception:
            logger.exception("inference request failed")
            self._send(500, {"error": "inference failed"})

    @staticmethod
    def _embed(payload):
        from apps.feed.services.embed.embedder import LocalEmbedder

        texts = payload.get("texts", [])
        if not texts:
            return []
        arr = LocalEmbedder.instance().embed(texts, is_query=bool(payload.get("is_query", False)))
        return [v.tolist() for v in arr]

    @staticmethod
    def _classify(payload):
        from apps.feed.services.classify.classifier import TopicClassifier

        scored = TopicClassifier.instance().classify(
            payload.get("title", ""), payload.get("content", ""),
        )
        return [[slug, score] for slug, score in scored]

    def log_message(self, format, *args):  # keep journald quiet; errors are logged above
        pass


class Command(BaseCommand):
    help = "Run the ONNX inference HTTP service (embed + classify) for remote harvesters."
    requires_system_checks = []  # never touches the DB; skip app/migration checks

    def add_arguments(self, parser):
        parser.add_argument("--host", default=os.environ.get("INFERENCE_BIND_HOST", "127.0.0.1"))
        parser.add_argument(
            "--port", type=int, default=int(os.environ.get("INFERENCE_BIND_PORT", "8031")),
        )

    def handle(self, *args, **opts):
        if not SECRET:
            raise SystemExit("INFERENCE_SERVICE_SECRET is not set — refusing to start.")

        # Warm both models at boot so the first client request isn't slow.
        from apps.feed.services.classify.classifier import TopicClassifier
        from apps.feed.services.embed.embedder import LocalEmbedder

        self.stdout.write("Loading models…")
        LocalEmbedder.instance()
        TopicClassifier.instance()

        host, port = opts["host"], opts["port"]
        server = ThreadingHTTPServer((host, port), _Handler)
        self.stdout.write(self.style.SUCCESS(f"Inference service listening on {host}:{port}"))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
