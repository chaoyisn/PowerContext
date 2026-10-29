"""Embedding providers.

Three interchangeable backends, selected by ``RF_EMBEDDING_PROVIDER``:

* ``minilm``  - pyseekdb's built-in all-MiniLM-L6-v2 ONNX model (384-d, real semantics,
                downloads ~86MB once and caches locally).
* ``hashing`` - deterministic offline char-n-gram hashing. Zero download, language agnostic,
                reproducible across machines. Lexical rather than semantic.
* ``openai``  - any OpenAI-compatible ``/embeddings`` endpoint.

Vectors are always computed by ResearchFlow and handed to seekdb explicitly, so the
collection is created with ``embedding_function=None`` and behaviour is identical for
every provider.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from ..config import Settings
from ..logging_setup import get_logger

logger = get_logger(__name__)

_ASCII_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

EmbedFn = Callable[[Sequence[str]], list[list[float]]]


def _hash_unit(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = _ASCII_WORD.findall(lowered)
    cjk_chars = [ch for ch in lowered if _CJK.match(ch)]
    tokens.extend(cjk_chars)
    tokens.extend(a + b for a, b in zip(cjk_chars, cjk_chars[1:]))
    return tokens


def hashing_embed(texts: Sequence[str], dimension: int = 384) -> list[list[float]]:
    """Deterministic signed feature-hashing embedding."""
    vectors: list[list[float]] = []
    for text in texts:
        acc = np.zeros(dimension, dtype=np.float64)
        for token in _tokens(text):
            digest = _hash_unit(token)
            bucket = digest % dimension
            sign = 1.0 if (digest >> 63) & 1 == 0 else -1.0
            acc[bucket] += sign
        norm = float(np.linalg.norm(acc))
        if norm > 0:
            acc /= norm
        else:
            acc[0] = 1.0
        vectors.append(acc.astype(np.float32).tolist())
    return vectors


@dataclass
class EmbeddingBackend:
    provider: str
    dimension: int
    embed: EmbedFn
    note: str = ""


class _MiniLMBackend:
    """Lazily initialises pyseekdb's ONNX model once, then reuses it (thread-safe)."""

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension
        self._fn = None
        self._lock = threading.Lock()

    def _ensure(self):
        with self._lock:
            if self._fn is None:
                from pyseekdb import DefaultEmbeddingFunction

                fn = DefaultEmbeddingFunction()
                probe = fn(["researchflow warmup"])
                if len(probe[0]) != self._dimension:
                    raise ValueError(
                        f"all-MiniLM-L6-v2 produced {len(probe[0])}-d vectors, "
                        f"expected {self._dimension}"
                    )
                self._fn = fn
            return self._fn

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        fn = self._ensure()
        return [list(map(float, v)) for v in fn(list(texts))]


_MULTILINGUAL_MODEL_URL = (
    "https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2/"
    "resolve/main/onnx/model_quantized.onnx"
)
_MULTILINGUAL_TOKENIZER_URL = (
    "https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2/"
    "resolve/main/tokenizer.json"
)
_MULTILINGUAL_MAX_TOKENS = 128


class _MultilingualBackend:
    """paraphrase-multilingual-MiniLM-L12-v2 via ONNX Runtime (384-d, 50+ languages).

    Optional enhancement: all-MiniLM-L6-v2 uses an English WordPiece vocabulary, so a Chinese
    query against English text scores poorly. This model closes that gap. It is downloaded
    once (~120 MB quantized) into the data directory and never blocks startup, because
    ``build_embedding_backend`` falls back to ``hashing`` when it cannot initialise.
    """

    def __init__(self, directory: Path, dimension: int) -> None:
        import httpx
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory.mkdir(parents=True, exist_ok=True)
        model_path = directory / "model_quantized.onnx"
        tokenizer_path = directory / "tokenizer.json"
        for target, url in ((model_path, _MULTILINGUAL_MODEL_URL), (tokenizer_path, _MULTILINGUAL_TOKENIZER_URL)):
            if not target.exists() or target.stat().st_size == 0:
                logger.info("downloading multilingual embedding asset", fields={"url": url})
                with httpx.Client(timeout=600.0, follow_redirects=True) as client:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        with target.open("wb") as handle:
                            for chunk in response.iter_bytes():
                                handle.write(chunk)

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=_MULTILINGUAL_MAX_TOKENS)
        pad_id = self._tokenizer.token_to_id("[PAD]")
        self._tokenizer.enable_padding(pad_id=pad_id if pad_id is not None else 0, pad_token="[PAD]")
        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._input_names = {inp.name for inp in self._session.get_inputs()}
        self._dimension = dimension
        probe = self(["multilingual warmup 多语预热"])
        if len(probe[0]) != dimension:
            raise ValueError(
                f"multilingual model produced {len(probe[0])}-d vectors, expected {dimension}"
            )

    @property
    def dimension(self) -> int:
        return self._dimension

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        encoded = self._tokenizer.encode_batch([t or " " for t in texts])
        ids = [e.ids for e in encoded]
        mask = [e.attention_mask for e in encoded]
        feeds: dict[str, list[list[int]]] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = [[0] * len(row) for row in ids]
        (hidden,) = self._session.run(None, feeds)
        array = np.asarray(hidden, dtype=np.float32)
        weights = np.asarray(mask, dtype=np.float32)[..., None]
        summed = (array * weights).sum(axis=1)
        counts = np.maximum(weights.sum(axis=1), 1e-9)
        pooled = summed / counts
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        pooled = pooled / np.maximum(norms, 1e-9)
        return [row.astype(np.float32).tolist() for row in pooled]


def _openai_backend(settings: Settings) -> EmbedFn:
    from openai import OpenAI

    if not settings.embedding_model:
        raise ValueError("RF_EMBEDDING_MODEL is required when RF_EMBEDDING_PROVIDER=openai")
    client = OpenAI(
        api_key=settings.embedding_api_key or None,
        base_url=settings.embedding_base_url or None,
        timeout=60.0,
    )
    model = settings.embedding_model

    def embed(texts: Sequence[str]) -> list[list[float]]:
        response = client.embeddings.create(model=model, input=list(texts))
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(map(float, item.embedding)) for item in ordered]

    return embed


def build_embedding_backend(settings: Settings) -> EmbeddingBackend:
    """Build the configured provider, falling back to ``hashing`` if it cannot initialise."""
    requested = settings.embedding_provider
    dimension = settings.embedding_dimension

    if requested == "hashing":
        return EmbeddingBackend("hashing", dimension, lambda texts: hashing_embed(texts, dimension))

    if requested == "openai":
        try:
            fn = _openai_backend(settings)
            fn(["researchflow warmup"])
            return EmbeddingBackend("openai", dimension, fn, note=f"model={settings.embedding_model}")
        except Exception as exc:
            logger.warning(
                "openai embedding provider unavailable, falling back to hashing",
                fields={"error": f"{type(exc).__name__}: {exc}"},
            )
            return EmbeddingBackend(
                "hashing", dimension, lambda texts: hashing_embed(texts, dimension),
                note=f"fallback from openai: {type(exc).__name__}",
            )

    if requested == "multilingual":
        directory = (
            Path(settings.embedding_multilingual_dir)
            if settings.embedding_multilingual_dir
            else settings.data_path / "models" / "multilingual-minilm-l12-v2"
        )
        try:
            backend = _MultilingualBackend(directory, dimension)
            return EmbeddingBackend(
                "multilingual", dimension, backend,
                note="paraphrase-multilingual-MiniLM-L12-v2 ONNX (quantized)",
            )
        except Exception as exc:
            logger.warning(
                "multilingual embedding provider unavailable, falling back to hashing",
                fields={"error": f"{type(exc).__name__}: {exc}"},
            )
            return EmbeddingBackend(
                "hashing", dimension, lambda texts: hashing_embed(texts, dimension),
                note=f"fallback from multilingual: {type(exc).__name__}",
            )

    # minilm
    try:
        backend = _MiniLMBackend(dimension)
        backend(["researchflow warmup"])
        return EmbeddingBackend("minilm", dimension, backend, note="all-MiniLM-L6-v2 ONNX")
    except Exception as exc:
        logger.warning(
            "minilm embedding provider unavailable, falling back to hashing",
            fields={"error": f"{type(exc).__name__}: {exc}"},
        )
        return EmbeddingBackend(
            "hashing", dimension, lambda texts: hashing_embed(texts, dimension),
            note=f"fallback from minilm: {type(exc).__name__}",
        )
