"""Local, torch-free zero-shot topic classifier.

Runs a DeBERTa NLI model (pre-exported to ONNX on the Hub) directly via
onnxruntime — no optimum, no torch, no GPU. `transformers` is used only for the
tokenizer/config. The model is loaded once per process (lazy singleton) and
reused across the harvester's worker threads; onnxruntime is capped to a couple
of threads so a classification burst never starves the other services on the
shared host.
"""

import logging
import os
import threading

import numpy as np

from .taxonomy import (
    CANDIDATE_LABELS,
    HYPOTHESIS_TEMPLATE,
    LABEL_TO_SLUG,
    STORE_FLOOR,
)
from .text_clean import build_premise

logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("TOPIC_MODEL", "MoritzLaurer/deberta-v3-base-zeroshot-v2.0")
# Relative path (within the Hub repo) to the pre-exported ONNX weights.
ONNX_PATH = "onnx/model.onnx"
# Cap CPU so classification never monopolises the shared server.
ORT_THREADS = int(os.environ.get("TOPIC_ORT_THREADS", "2"))
# Truncate the article body fed to the model — the lead is enough to classify.
MAX_CONTENT_CHARS = 600


class TopicClassifier:
    """Lazy singleton wrapping the ONNX NLI model."""

    _instance: "TopicClassifier | None" = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "TopicClassifier":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        # Imported lazily so the app boots even before the extra deps land.
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoConfig, AutoTokenizer

        try:
            onnx_path = hf_hub_download(MODEL_NAME, ONNX_PATH)
        except Exception as exc:
            raise RuntimeError(f"No ONNX weights found for {MODEL_NAME}") from exc

        logger.info("Loading topic model %s (onnxruntime, %d threads)…", MODEL_NAME, ORT_THREADS)
        so = ort.SessionOptions()
        so.intra_op_num_threads = ORT_THREADS
        so.inter_op_num_threads = 1
        self.session = ort.InferenceSession(onnx_path, so, providers=["CPUExecutionProvider"])
        self._input_names = {i.name for i in self.session.get_inputs()}

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        config = AutoConfig.from_pretrained(MODEL_NAME)
        label2id = {k.lower(): v for k, v in config.label2id.items()}
        self.entail_id = label2id.get("entailment", 0)
        self.n_classes = len(config.label2id)
        self.hypotheses = [HYPOTHESIS_TEMPLATE.format(l) for l in CANDIDATE_LABELS]
        logger.info("Topic model ready (classes=%d, entail_id=%s)", self.n_classes, self.entail_id)

    def classify(self, title: str, content: str = "") -> list[tuple[str, float]]:
        """Return [(topic_slug, score), …] for topics scoring >= STORE_FLOOR,
        highest first. Multi-label: each topic scored independently."""
        premise = build_premise(title, content, MAX_CONTENT_CHARS)
        if not premise:
            return []

        # One premise vs every hypothesis, in a single batched forward pass.
        enc = self.tokenizer(
            [premise] * len(self.hypotheses),
            self.hypotheses,
            truncation="only_first",
            max_length=512,
            padding=True,
            return_tensors="np",
        )
        feed = {k: v for k, v in enc.items() if k in self._input_names}
        logits = self.session.run(None, feed)[0]  # (n_labels, n_nli_classes)

        probs = self._entailment_probs(logits)
        scored = [
            (LABEL_TO_SLUG[label], float(p))
            for label, p in zip(CANDIDATE_LABELS, probs)
            if p >= STORE_FLOOR
        ]
        scored.sort(key=lambda x: -x[1])
        return scored

    def _entailment_probs(self, logits):
        """Per-label entailment probability. Binary NLI heads (entail/not) → the
        two-way softmax; single-logit heads → sigmoid; 3-way → softmax over the
        entail/contradiction pair (matching HF's zero-shot pipeline)."""
        if logits.shape[1] == 1:
            return 1.0 / (1.0 + np.exp(-logits[:, 0]))
        if logits.shape[1] == 2:
            other_id = 1 - self.entail_id
        else:
            other_id = 0 if self.entail_id != 0 else 2
        pair = np.stack([logits[:, other_id], logits[:, self.entail_id]], axis=1)
        pair = pair - pair.max(axis=1, keepdims=True)
        exp = np.exp(pair)
        return exp[:, 1] / exp.sum(axis=1)
