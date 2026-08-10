"""Local embedding provider with sqlite-vec / BGE support and offline fallback."""

import hashlib
import json
import math
import re

from app.config import config

_model_cache: dict[str, object] = {}
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _normalize_text(text: str) -> str:
    return re.sub(r"[\s_\-—:：,，.。;；!！?？()（）\[\]【】]+", "", (text or "").lower())


def _char_ngrams(text: str, max_n: int = 3) -> list[str]:
    compact = _normalize_text(text)
    grams: list[str] = []
    for n in range(1, max_n + 1):
        grams.extend(compact[i:i + n] for i in range(len(compact) - n + 1))
    return grams or [compact]


def _hash_vec(text: str, dim: int | None = None) -> list[float]:
    dim = dim or config.EMBEDDING_DIM
    vec = [0.0] * dim
    for gram in _char_ngrams(text):
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % dim
        vec[index] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _load_model():
    if config.EMBEDDING_PROVIDER == "ngram":
        return None
    cached = _model_cache.get(config.EMBEDDING_MODEL)
    if cached is not None:
        return cached
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    try:
        model = SentenceTransformer(config.EMBEDDING_MODEL)
    except Exception:
        return None
    _model_cache[config.EMBEDDING_MODEL] = model
    return model


def embed_text(text: str) -> list[float]:
    """Embed a single text; prefers BGE when installed, falls back to n-grams."""
    model = _load_model()
    if model is not None:
        vector = model.encode([text], normalize_embeddings=True)[0]
        return [float(v) for v in vector]
    return _hash_vec(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = _load_model()
    if model is not None and texts:
        vectors = model.encode(texts, normalize_embeddings=True)
        return [[float(v) for v in row] for row in vectors]
    return [embed_text(text) for text in texts]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def encode_embedding(vector: list[float]) -> bytes:
    return json.dumps(vector, separators=(",", ":")).encode("utf-8")


def decode_embedding(blob: bytes | str | None) -> list[float]:
    if blob is None:
        return []
    try:
        if isinstance(blob, (bytes, bytearray)):
            text = bytes(blob).decode("utf-8")
        else:
            text = blob
        parsed = json.loads(text)
        return [float(v) for v in parsed] if isinstance(parsed, list) else []
    except Exception:
        return []
