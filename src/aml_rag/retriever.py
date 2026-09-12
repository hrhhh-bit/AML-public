"""Dual-track motif retriever.

Implements the two-stage retrieval strategy required by the data contract:

**Track 1 — Hard rule / precondition gate**
    Rejects any candidate whose :class:`Preconditions` are violated by the
    current :class:`CurrentState` (``min_level``, active node roles, chain
    compatibility, active branch count).  Violations are *fatal* for the
    candidate: it never reaches Track 2.

**Track 2 — Dense semantic matching**
    Encodes ``QueryContext`` (scenario + tactic goal) and each surviving
    motif's flattened text, then ranks by cosine similarity.

Final score (per the background doc):

.. math::
    Score(g_{motif} | State_t) =
        \\alpha \\cdot \\cos(e_{context}, e_{motif})
        + (1 - \\alpha) \\cdot \\text{RuleSat}(State_t, g_{motif}^{pre})

where :math:`\\text{RuleSat}` is the fraction of imposed precondition checks
satisfied (always 1.0 for survivors of the hard gate; it only differs when
``strict=False`` soft fallback is active).

Embeddings are pluggable: OpenAI, sentence-transformers, or the bundled
:class:`DeterministicHashEmbedder` (zero-dependency deterministic mock).
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field

from .schema import CurrentState, PatternType, QueryContext, TopologicalMotif
from .storage import MotifKnowledgeBase

__all__ = [
    "EmbeddingProvider",
    "DeterministicHashEmbedder",
    "RetrievalResult",
    "DualTrackMotifRetriever",
    "cosine_similarity",
]


# ---------------------------------------------------------------------------
# Embedding backends
# ---------------------------------------------------------------------------
class EmbeddingProvider(Protocol):
    """Minimal embedding contract: text batch -> dense vectors (row-major)."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class DeterministicHashEmbedder:
    """Deterministic bag-of-hashed-tokens embedder (mock, zero dependencies).

    Tokens are hashed (BLAKE2b) into a fixed number of sparse dimensions and
    the result is L2-normalised.  Identical text always produces identical
    vectors, and lexically overlapping texts produce correlated vectors —
    enough to exercise and test the semantic track without any ML stack.
    """

    def __init__(self, dim: int = 256, fan_out: int = 3, seed: int = 20260829) -> None:
        if dim < 1:
            raise ValueError("dim must be >= 1")
        if fan_out < 1:
            raise ValueError("fan_out must be >= 1")
        self.dim = dim
        self.fan_out = fan_out
        self.seed = seed

    # -- tokenisation -------------------------------------------------------
    _WORD_RE = re.compile(r"[a-z0-9_]+")
    _CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

    @classmethod
    def _tokenize(cls, text: str) -> list[str]:
        lowered = text.lower()
        tokens: list[str] = []
        for match in cls._WORD_RE.finditer(lowered):
            token = match.group()
            cjk = cls._CJK_RE.findall(token)
            if cjk:
                tokens.extend(cjk)  # CJK: character-level tokens
            else:
                tokens.append(token)
        return tokens

    # -- embedding ----------------------------------------------------------
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in self._tokenize(text):
                digest = hashlib.blake2b(
                    token.encode("utf-8"), digest_size=16, person=b"aml-rag-m1"
                ).digest()
                rng = random.Random(int.from_bytes(digest, "big") ^ self.seed)
                for _ in range(self.fan_out):
                    vec[rng.randrange(self.dim)] += 1.0
            vectors.append(self._l2_normalise(vec))
        return vectors

    @staticmethod
    def _l2_normalise(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return vec
        return [x / norm for x in vec]


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
# Retrieval result record
# ---------------------------------------------------------------------------
class RetrievalResult(BaseModel):
    """One scored candidate produced by the dual-track retriever."""

    model_config = {"arbitrary_types_allowed": False}

    motif_id: str
    pattern_type: PatternType
    description: str
    motif: TopologicalMotif
    rule_score: float = Field(ge=0.0, le=1.0)
    semantic_score: float = Field(ge=0.0, le=1.0)
    combined_score: float = Field(ge=0.0, le=1.0)
    gate_reasons: tuple[str, ...] = Field(
        default=(), description="Human-readable hard-gate verdicts."
    )


# ---------------------------------------------------------------------------
# Dual-track retriever
# ---------------------------------------------------------------------------
class DualTrackMotifRetriever:
    """Rule-gated + semantic-ranked motif retriever (no GNNs involved)."""

    def __init__(
        self,
        knowledge_base: MotifKnowledgeBase,
        embedder: EmbeddingProvider | None = None,
        *,
        alpha: float = 0.5,
        top_k: int = 5,
        strict: bool = True,
        cache_embeddings: bool = True,
    ) -> None:
        """Args:
        knowledge_base: source of candidate motifs.
        embedder: embedding backend; defaults to DeterministicHashEmbedder.
        alpha: weight of the semantic score (1-alpha = rule score weight).
        top_k: default number of results to return.
        strict: when True, motifs failing the hard gate are excluded entirely;
                when False, they survive with ``rule_score`` reflecting the
                fraction of satisfied checks (soft fallback, e.g. for
                cold-start debugging).
        cache_embeddings: cache per-motif vectors keyed by motif_id.
        """
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be in [0, 1]")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        self.knowledge_base = knowledge_base
        self.embedder: EmbeddingProvider = embedder or DeterministicHashEmbedder()
        self.alpha = alpha
        self.top_k = top_k
        self.strict = strict
        self.cache_embeddings = cache_embeddings
        self._motif_vec_cache: dict[str, list[float]] = {}

    # ------------------------------------------------------- Track 1: gate
    def hard_gate(
        self,
        motif: TopologicalMotif,
        state: CurrentState,
        *,
        strict: bool | None = None,
    ) -> tuple[bool, float, list[str]]:
        """Evaluate the precondition gate.

        Returns ``(passed, rule_satisfaction, reasons)`` where
        ``rule_satisfaction`` is the fraction of imposed checks satisfied.
        ``strict`` overrides the instance default per call (the planner uses
        ``strict=False`` as a prior-guarantee soft fallback).
        """
        strict = self.strict if strict is None else strict
        pre = motif.preconditions
        n_checks = pre.n_checks()
        satisfied = 0
        reasons: list[str] = []

        if pre.min_level > 0:
            ok = state.current_level >= pre.min_level
            satisfied += int(ok)
            reasons.append(
                f"min_level: {'ok' if ok else 'FAIL'}"
                f"({state.current_level}{'>=' if ok else '<'}{pre.min_level})"
            )
            if not ok and strict:
                return False, 0.0, reasons

        if pre.allowed_node_roles is not None:
            allowed = set(pre.allowed_node_roles)
            active = state.active_roles
            # Empty frontier -> no role evidence yet, treated as satisfied.
            # OVERLAP semantics (not strict subset): multi-role frontiers are
            # the norm once aggregators / cross-chain nodes coexist with
            # intermediates, so a motif is applicable when at least one
            # active role belongs to the allowed set.
            ok = not active or bool(active & allowed)
            satisfied += int(ok)
            reasons.append(
                f"roles: {'ok' if ok else 'FAIL'}"
                f"(active={sorted(r.value for r in active)} "
                f"allowed={sorted(r.value for r in allowed)})"
            )
            if not ok and strict:
                return False, 0.0, reasons

        if pre.required_chains is not None:
            ok = state.current_chain in pre.required_chains
            satisfied += int(ok)
            reasons.append(
                f"chains: {'ok' if ok else 'FAIL'}"
                f"(current={state.current_chain} "
                f"required={sorted(pre.required_chains)})"
            )
            if not ok and strict:
                return False, 0.0, reasons

        if pre.max_active_branches is not None:
            ok = state.active_branches <= pre.max_active_branches
            satisfied += int(ok)
            reasons.append(
                f"branches: {'ok' if ok else 'FAIL'}"
                f"(active={state.active_branches} "
                f"max={pre.max_active_branches})"
            )
            if not ok and strict:
                return False, 0.0, reasons

        rule_score = satisfied / n_checks if n_checks > 0 else 1.0
        return True, rule_score, reasons

    # ------------------------------------------------------- Track 2: rank
    def _motif_vectors(self, motifs: list[TopologicalMotif]) -> list[list[float]]:
        """Return one vector per motif, using cached values when available."""
        result: list[list[float]] = []
        pending_idx: list[int] = []
        pending_texts: list[str] = []
        for i, motif in enumerate(motifs):
            cached = self._motif_vec_cache.get(motif.motif_id)
            result.append(cached if cached is not None else [])
            if cached is None:
                pending_idx.append(i)
                pending_texts.append(motif.semantic_text())
        if pending_idx:
            embedded = self.embedder.embed(pending_texts)
            for i, vec in zip(pending_idx, embedded):
                result[i] = vec
                if self.cache_embeddings:
                    self._motif_vec_cache[motifs[i].motif_id] = vec
        return result

    # ------------------------------------------------------------- pipeline
    def retrieve(
        self,
        state: CurrentState,
        query: QueryContext,
        *,
        top_k: int | None = None,
        strict: bool | None = None,
    ) -> list[RetrievalResult]:
        """Run both tracks and return the top-K ranked motifs.

        ``strict`` overrides the instance default per call (soft fallback for
        the planner's prior guarantee). Semantic ties (and pattern bias from
        ``query.target_pattern_type``) are resolved deterministically.
        """
        k = top_k or self.top_k

        # ---- Track 1: hard gate over all candidates ----------------------
        gated: list[tuple[TopologicalMotif, float, list[str]]] = []
        for motif in self.knowledge_base:
            passed, rule_score, reasons = self.hard_gate(motif, state, strict=strict)
            if passed:
                gated.append((motif, rule_score, reasons))

        # ---- Track 2: semantic scoring -----------------------------------
        query_vec = self.embedder.embed([query.embedding_text])[0]
        motif_vecs = self._motif_vectors([m for m, _, _ in gated])
        semantic_scores = [cosine_similarity(query_vec, mv) for mv in motif_vecs]

        results: list[RetrievalResult] = []
        for (motif, rule_score, reasons), sem in zip(gated, semantic_scores):
            # optional pattern-type bias: small deterministic tie-break bonus
            bias = 1e-6 if query.target_pattern_type is not None and \
                motif.pattern_type == query.target_pattern_type else 0.0
            combined = self.alpha * sem + (1 - self.alpha) * rule_score + bias
            results.append(
                RetrievalResult(
                    motif_id=motif.motif_id,
                    pattern_type=motif.pattern_type,
                    description=motif.description,
                    motif=motif,
                    rule_score=rule_score,
                    semantic_score=sem,
                    combined_score=min(combined, 1.0),
                    gate_reasons=tuple(reasons),
                )
            )

        # stable ordering: combined desc -> semantic desc -> motif_id asc
        results.sort(
            key=lambda r: (-r.combined_score, -r.semantic_score, r.motif_id)
        )
        return results[:k]

    def invalidate_cache(self) -> None:
        """Drop cached motif vectors (call after mutating the knowledge base)."""
        self._motif_vec_cache.clear()
