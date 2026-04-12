# backend/memory/embeddings.py
# ============================================================
# NEXON Local Embeddings Engine
# Generates sentence embeddings locally — zero API calls.
# Uses a tiny model (all-MiniLM-L6-v2) via sentence-transformers
# OR falls back to TF-IDF if not installed.
#
# Install: pip install sentence-transformers
# ============================================================

import os
import json
import math
import hashlib
from typing import List, Dict, Optional, Tuple
from collections import Counter

# ── Try sentence-transformers first ─────────────────────────
_ST_AVAILABLE = False
_model = None

def _load_st_model():
    global _ST_AVAILABLE, _model
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer('all-MiniLM-L6-v2')
        _ST_AVAILABLE = True
        print("[Embeddings] sentence-transformers loaded ✓")
    except ImportError:
        print("[Embeddings] sentence-transformers not found — using TF-IDF fallback")
        _ST_AVAILABLE = False

_load_st_model()


# ── TF-IDF Fallback Embedder ────────────────────────────────

class TFIDFEmbedder:
    """
    Lightweight TF-IDF based embedder as fallback.
    Not as accurate as neural models but works fully offline
    with zero additional dependencies.
    """
    def __init__(self, vocab_size: int = 512):
        self.vocab_size = vocab_size
        self._vocab: Dict[str, int] = {}

    def _tokenize(self, text: str) -> List[str]:
        import re
        return re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())

    def _hash_token(self, token: str) -> int:
        """Hash token into vocab bucket."""
        return int(hashlib.md5(token.encode()).hexdigest(), 16) % self.vocab_size

    def encode(self, text: str) -> List[float]:
        """
        Encode text into a fixed-size TF-IDF-like vector.
        Fast, deterministic, no training needed.
        """
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.vocab_size

        vec = [0.0] * self.vocab_size
        counts = Counter(tokens)
        total  = len(tokens)

        for token, count in counts.items():
            tf  = count / total
            idx = self._hash_token(token)
            vec[idx] += tf

        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.encode(t) for t in texts]


_tfidf = TFIDFEmbedder()


# ── Public API ───────────────────────────────────────────────

def embed(text: str) -> List[float]:
    """
    Generate a vector embedding for a single text string.

    Args:
        text : Input text to embed.
    Returns:
        List of floats (384-dim for ST model, 512-dim for TF-IDF).
    """
    if not text or not text.strip():
        return [0.0] * (384 if _ST_AVAILABLE else 512)

    if _ST_AVAILABLE and _model:
        vec = _model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    else:
        return _tfidf.encode(text)


def embed_batch(texts: List[str]) -> List[List[float]]:
    """
    Embed a list of texts efficiently.

    Args:
        texts : List of input strings.
    Returns:
        List of embedding vectors.
    """
    if not texts:
        return []

    if _ST_AVAILABLE and _model:
        vecs = _model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vecs]
    else:
        return _tfidf.encode_batch(texts)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        a, b : Embedding vectors of equal length.
    Returns:
        Similarity score in [-1, 1]. Higher = more similar.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb   = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


def find_most_similar(
    query_vec : List[float],
    candidates: List[Tuple[str, List[float]]],
    top_k     : int = 5,
    threshold : float = 0.3
) -> List[Tuple[str, float]]:
    """
    Find the most similar texts to a query vector.

    Args:
        query_vec  : Query embedding vector.
        candidates : List of (text, embedding) tuples.
        top_k      : Maximum results to return.
        threshold  : Minimum similarity score.
    Returns:
        List of (text, score) tuples sorted by score descending.
    """
    scored = []
    for text, vec in candidates:
        score = cosine_similarity(query_vec, vec)
        if score >= threshold:
            scored.append((text, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def vec_to_json(vec: List[float]) -> str:
    """Serialize embedding vector to JSON string for SQLite storage."""
    return json.dumps(vec)


def json_to_vec(s: str) -> List[float]:
    """Deserialize embedding vector from JSON string."""
    try:
        return json.loads(s)
    except Exception:
        return []