"""Pluggable embedding providers (Stage-3 Part A).

Unified, object-oriented embedding architecture for the dual-track retriever:

- :class:`EmbeddingProvider` — abstract contract covering single-query
  embedding (:meth:`EmbeddingProvider.embed_query`), batch embedding
  (:meth:`EmbeddingProvider.embed_texts`) and vector similarity
  (:meth:`EmbeddingProvider.similarity`), with a lightweight in-memory
  cache keyed by exact text so repeated texts inside one planning life-cycle
  never re-trigger expensive computation.
- :class:`DenseEmbeddingProvider` — pre-trained dense vectors via
  ``sentence-transformers`` (default ``all-MiniLM-L6-v2``).  The model is
  loaded *lazily* (first embed call, never at construction) and degrades
  defensively to the discrete hash engine when the package is missing, the
  download fails, or the environment is CPU-only / offline.  No commercial
  API key is ever required or hard-coded.
- :class:`DiscreteEmbeddingProvider` — the legacy deterministic lexical /
  hash baseline, wrapped behind the same contract as the control-group
  benchmark and as the guaranteed lightweight fallback.
- :class:`DeterministicHashEmbedder` — the zero-dependency hash engine
  (kept here as the canonical home; re-exported by ``aml_rag.retriever`` for
  backwards compatibility).

Design rule (red line): embedded texts never contain wallet addresses, token
tickers, micro amounts, gas fees or timestamps — the corpus itself is built
from abstract roles / chains / operations only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import random
import re
import warnings
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Literal

__all__ = [
    "DEFAULT_DENSE_MODEL",
    "EmbeddingProvider",
    "cosine_similarity",
    "DeterministicHashEmbedder",
    "DiscreteEmbeddingProvider",
    "DenseEmbeddingProvider",
    "make_embedding_provider",
    "is_sentence_transformers_available",
    "ProviderKind",
]

#: Default lightweight open-source pre-trained model for the dense provider.
DEFAULT_DENSE_MODEL: str = "all-MiniLM-L6-v2"

ProviderKind = Literal["dense", "discrete", "auto"]


def is_sentence_transformers_available() -> bool:
    """Return True when the ``sentence-transformers`` package is importable.

    Uses ``importlib.util.find_spec`` — no heavy import is performed here.
    """
    return importlib.util.find_spec("sentence_transformers") is not None


# ---------------------------------------------------------------------------
# Vector math (canonical implementation shared by every provider)
# ---------------------------------------------------------------------------
def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-length dense vectors."""
    if len(a) != len(b):
        raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# ---------------------------------------------------------------------------
# Discrete lexical / hash engine core (shared by hash & discrete providers)
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _tokenize(text: str) -> list[str]:
    """Tokenise for hashing: latin words as whole tokens, CJK char by char."""
    lowered = text.lower()
    tokens: list[str] = []
    for match in _WORD_RE.finditer(lowered):
        token = match.group()
        cjk = _CJK_RE.findall(token)
        if cjk:
            tokens.extend(cjk)
        else:
            tokens.append(token)
    return tokens


def _hash_embed_one(text: str, dim: int, fan_out: int, seed: int) -> list[float]:
    """Bag-of-hashed-tokens vector for one text (L2-normalised).

    Identical to the legacy :class:`DeterministicHashEmbedder` algorithm:
    BLAKE2b-hashed tokens scatter ``fan_out`` unit increments into ``dim``
    sparse dimensions, then the result is L2-normalised.
    """
    vec = [0.0] * dim
    for token in _tokenize(text):
        digest = hashlib.blake2b(
            token.encode("utf-8"), digest_size=16, person=b"aml-rag-m1"
        ).digest()
        rng = random.Random(int.from_bytes(digest, "big") ^ seed)
        for _ in range(fan_out):
            vec[rng.randrange(dim)] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# Unified abstract contract
# ---------------------------------------------------------------------------
class EmbeddingProvider(ABC):
    """Unified pluggable embedding contract with in-memory caching.

    Subclasses implement :meth:`_embed_uncached`; the public API
    (:meth:`embed_query` / :meth:`embed_texts` / :meth:`similarity`) plus the
    cache machinery is provided by this base class.  The legacy ``embed``
    name is kept as an alias of ``embed_texts`` so old-style callers keep
    working unchanged.
    """

    def __init__(self, *, cache_size: int | None = 4096) -> None:
        """Args:
        cache_size: max cached vectors (LRU-style, insertion ordered).
            ``None`` = unbounded, ``0`` = caching disabled.
        """
        if cache_size is not None and cache_size < 0:
            raise ValueError("cache_size must be >= 0 or None")
        self._cache: dict[str, list[float]] = {}
        self._cache_size = cache_size
        self._cache_hits = 0
        self._cache_misses = 0

    # ------------------------------------------------------------ identity
    @property
    def backend(self) -> str:
        """Human-readable backend label for experiment reports."""
        return type(self).__name__

    # ------------------------------------------------------ abstract hook
    @abstractmethod
    def _embed_uncached(self, texts: Sequence[str]) -> list[list[float]]:
        """Compute raw vectors for unseen texts (subclass implementation)."""

    # ---------------------------------------------------------- public API
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text into one dense vector (cached)."""
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts (row-major), serving cache hits first.

        In-batch duplicates are computed exactly once (they are deduplicated
        against each other before the uncached embedding hook runs) and are
        subsequently served from the cache.
        """
        texts = list(texts)
        vectors: list[list[float]] = []
        missing_idx: list[int] = []
        missing_texts: list[str] = []
        for i, text in enumerate(texts):
            cached = self._cache.get(text)
            if cached is not None:
                self._cache_hits += 1
                vectors.append(cached)
            else:
                self._cache_misses += 1
                missing_idx.append(i)
                missing_texts.append(text)
                vectors.append([])  # placeholder, filled below
        if missing_texts:
            unique = list(dict.fromkeys(missing_texts))  # order-preserving dedupe
            by_text = dict(zip(unique, self._embed_uncached(unique)))
            for idx, text in zip(missing_idx, missing_texts):
                vec = by_text[text]
                self._cache[text] = vec
                vectors[idx] = vec
            self._evict_over_capacity()
        return vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Legacy-compatible alias of :meth:`embed_texts` (batch)."""
        return self.embed_texts(texts)

    def similarity(self, a: Sequence[float], b: Sequence[float]) -> float:
        """Cosine similarity between two vectors (the default metric)."""
        return cosine_similarity(a, b)

    # ------------------------------------------------------------- caching
    def clear_cache(self) -> None:
        """Drop all cached vectors (e.g. after knowledge-base mutation)."""
        self._cache.clear()

    def cache_stats(self) -> dict[str, Any]:
        """Lightweight cache telemetry: ``{size, hits, misses}``."""
        return {
            "size": len(self._cache),
            "hits": self._cache_hits,
            "misses": self._cache_misses,
        }

    def _evict_over_capacity(self) -> None:
        if self._cache_size is None:
            return
        while len(self._cache) > self._cache_size:
            oldest = next(iter(self._cache))
            del self._cache[oldest]


# ---------------------------------------------------------------------------
# Deterministic hash embedder (legacy engine, now a first-class provider)
# ---------------------------------------------------------------------------
class DeterministicHashEmbedder(EmbeddingProvider):
    """Deterministic bag-of-hashed-tokens embedder (zero dependencies).

    Tokens are hashed (BLAKE2b) into a fixed number of sparse dimensions and
    the result is L2-normalised.  Identical text always produces identical
    vectors, and lexically overlapping texts produce correlated vectors —
    enough to exercise and test the semantic track without any ML stack.
    """

    def __init__(
        self,
        dim: int = 256,
        fan_out: int = 3,
        seed: int = 20260829,
        *,
        cache_size: int | None = 4096,
    ) -> None:
        if dim < 1:
            raise ValueError("dim must be >= 1")
        if fan_out < 1:
            raise ValueError("fan_out must be >= 1")
        super().__init__(cache_size=cache_size)
        self.dim = dim
        self.fan_out = fan_out
        self.seed = seed

    def _embed_uncached(self, texts: Sequence[str]) -> list[list[float]]:
        return [_hash_embed_one(t, self.dim, self.fan_out, self.seed) for t in texts]


# ---------------------------------------------------------------------------
# Discrete lexical/hash baseline provider (control group)
# ---------------------------------------------------------------------------
class DiscreteEmbeddingProvider(EmbeddingProvider):
    """Discrete lexical / hash baseline wrapped behind the unified contract.

    This is the control-group benchmark for the dense semantic track and the
    guaranteed fallback for resource-constrained (pure CPU / offline) runs.
    Vector semantics are identical to :class:`DeterministicHashEmbedder`.
    """

    def __init__(
        self,
        *,
        dim: int = 256,
        fan_out: int = 3,
        seed: int = 20260829,
        cache_size: int | None = 4096,
    ) -> None:
        super().__init__(cache_size=cache_size)
        self._dim = dim
        self._fan_out = fan_out
        self._seed = seed

    @property
    def backend(self) -> str:
        return "discrete_hash"

    def _embed_uncached(self, texts: Sequence[str]) -> list[list[float]]:
        return [_hash_embed_one(t, self._dim, self._fan_out, self._seed) for t in texts]


# ---------------------------------------------------------------------------
# Dense pre-trained provider (lazy + defensive degradation)
# ---------------------------------------------------------------------------
class DenseEmbeddingProvider(EmbeddingProvider):
    """Pre-trained dense embedding provider (``sentence-transformers``).

    - **Lazy**: the model is loaded on the first embed call, never at
      construction time (construction is always cheap and offline-safe).
    - **Defensive**: when ``sentence-transformers`` is unavailable or the
      model fails to load (no network / no GPU / CI), the provider degrades
      to the discrete hash engine and keeps serving vectors; the effective
      backend is exposed via :attr:`backend` / :attr:`degraded`.
    - **Key-free**: no commercial API key involved at any point.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_DENSE_MODEL,
        *,
        fallback: EmbeddingProvider | None = None,
        device: str | None = None,
        cache_size: int | None = 4096,
    ) -> None:
        super().__init__(cache_size=cache_size)
        self.model_name = model_name
        self._device = device
        self._fallback = fallback
        self._model: Any = None
        self._load_error: str | None = None
        self._load_attempted = False
        self._warned_fallback = False

    # ------------------------------------------------------------ identity
    @property
    def backend(self) -> str:
        """Effective backend label: unloaded / sentence_transformers / fallback."""
        if self._model is not None:
            return f"sentence_transformers:{self.model_name}"
        if self._load_attempted:
            return "hash_fallback"
        return f"unloaded:{self.model_name}"

    @property
    def degraded(self) -> bool:
        """True when the dense backend is known-unusable (load failed / absent).

        Note: ``False`` before the lazy load has been attempted.
        """
        return self._load_attempted and self._model is None

    @property
    def load_error(self) -> str | None:
        """Reason of the last (failed or not attempted) model load."""
        return self._load_error

    # ------------------------------------------------------------- loading
    def _ensure_loaded(self) -> bool:
        """Lazily load the model once; return True when a dense backend is live."""
        if self._model is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True
        if not is_sentence_transformers_available():
            self._load_error = "sentence-transformers is not installed"
            return False
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]  # noqa: E501

            kwargs: dict[str, Any] = {}
            if self._device is not None:
                kwargs["device"] = self._device
            self._model = SentenceTransformer(self.model_name, **kwargs)
        except Exception as exc:  # pragma: no cover - environment dependent
            self._load_error = f"{type(exc).__name__}: {exc}"
            self._model = None
        return self._model is not None

    # -------------------------------------------------------------- embed
    def _embed_uncached(self, texts: Sequence[str]) -> list[list[float]]:
        if not self._ensure_loaded():
            if self._fallback is None:
                self._fallback = DiscreteEmbeddingProvider(cache_size=0)
                if not self._warned_fallback:
                    warnings.warn(
                        f"DenseEmbeddingProvider({self.model_name!r}) degraded to "
                        f"discrete hash fallback ({self._load_error}); ranking "
                        "quality is reduced. Install sentence-transformers "
                        "(pip install 'aml-rag[dense]') for real dense vectors.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    self._warned_fallback = True
            return self._fallback.embed_texts(list(texts))
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [list(map(float, vec)) for vec in vectors]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def make_embedding_provider(
    kind: ProviderKind = "auto", **kwargs: Any
) -> EmbeddingProvider:
    """Build a provider by kind.

    - ``"dense"``: :class:`DenseEmbeddingProvider` (degrades to hash
      fallback automatically when the ML stack is missing);
    - ``"discrete"``: :class:`DiscreteEmbeddingProvider` (control baseline);
    - ``"auto"`` (default): prefers dense, degrades via the same defensive
      mechanism — i.e. a :class:`DenseEmbeddingProvider` instance.
    """
    if kind == "dense":
        return DenseEmbeddingProvider(**kwargs)
    if kind == "discrete":
        return DiscreteEmbeddingProvider(**kwargs)
    if kind == "auto":
        return DenseEmbeddingProvider(**kwargs)
    raise ValueError(
        f"Unknown provider kind: {kind!r} (expected 'dense' | 'discrete' | 'auto')"
    )
