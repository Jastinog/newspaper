"""Local, torch-free sentence embedder.

Runs a BGE sentence-transformers model (pre-exported to ONNX on the Hub)
directly via onnxruntime — no optimum, no torch, no GPU, no OpenAI.
`transformers` is used only for the tokenizer. The model is loaded once per
process (lazy singleton) and reused across the harvester's worker threads;
onnxruntime is capped to a couple of threads so an embedding burst never
starves the other services on the shared host.

Mirrors the topic classifier (`apps/feed/services/classify/classifier.py`),
which already proved this pattern in production.
"""

import logging
import os
import threading

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
# Relative path (within the Hub repo) to the pre-exported ONNX weights.
ONNX_PATH = "onnx/model.onnx"
# Cap CPU so embedding never monopolises the shared server.
ORT_THREADS = int(os.environ.get("EMBED_ORT_THREADS", "2"))
# Output dimensionality of the model above (kept in sync with the VectorField).
DIM = 384
# BGE recommends prefixing *queries* (not documents) with this instruction.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
# Max tokens per forward pass; the model's own limit is 512.
MAX_TOKENS = 512


class LocalEmbedder:
    """Lazy singleton wrapping the ONNX sentence-embedding model."""

    _instance: "LocalEmbedder | None" = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "LocalEmbedder":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        # Imported lazily so the app boots even before the extra deps land.
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer

        try:
            onnx_path = hf_hub_download(MODEL_NAME, ONNX_PATH)
        except Exception as exc:
            raise RuntimeError(f"No ONNX weights found for {MODEL_NAME}") from exc

        logger.info("Loading embed model %s (onnxruntime, %d threads)…", MODEL_NAME, ORT_THREADS)
        so = ort.SessionOptions()
        so.intra_op_num_threads = ORT_THREADS
        so.inter_op_num_threads = 1
        # This is a long-lived daemon: the default CPU arena grows to the peak
        # working set and never returns it to the OS, so an occasional big batch
        # permanently inflates RSS. Disable the arena (and mem-pattern planning)
        # to trade a little inference speed for a much lower steady-state RSS.
        so.enable_cpu_mem_arena = False
        so.enable_mem_pattern = False
        self.session = ort.InferenceSession(onnx_path, so, providers=["CPUExecutionProvider"])
        self._input_names = {i.name for i in self.session.get_inputs()}

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        logger.info("Embed model ready (dim=%d)", DIM)

    def embed(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        """Embed a batch of texts → float32 array of shape (len(texts), DIM),
        L2-normalized (so a dot product equals cosine similarity).

        Set `is_query=True` for search queries to prepend BGE's instruction;
        leave it False for stored documents/chunks."""
        if not texts:
            return np.empty((0, DIM), dtype=np.float32)

        if is_query:
            texts = [QUERY_PREFIX + t for t in texts]

        enc = self.tokenizer(
            texts,
            truncation=True,
            max_length=MAX_TOKENS,
            padding=True,
            return_tensors="np",
        )
        feed = {k: v for k, v in enc.items() if k in self._input_names}
        last_hidden = self.session.run(None, feed)[0]  # (batch, seq, DIM)

        # BGE uses CLS pooling: the first token's hidden state.
        cls = last_hidden[:, 0].astype(np.float32)
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return cls / norms

    def embed_one(self, text: str, is_query: bool = False) -> list[float]:
        """Embed a single text → plain Python list (ready for pgvector)."""
        return self.embed([text], is_query=is_query)[0].tolist()
