"""Two-stage hierarchical motif retriever (Stage-3 Part A).

Implements the dual-track retrieval strategy with a pluggable dense
semantic front-end:

**Stage 1 — Coarse dense-semantic pre-ranking**
    The query and every motif's flattened text are encoded by the injected
    embedding provider (:class:`aml_rag.embedding.EmbeddingProvider`), then
    candidates are pre-ranked by cosine similarity.

**Stage 2 — Fine topological hard gate + fused weighting**
    The hard precondition gate (``min_level``, active node roles, chain
    compatibility, active branch count) rejects candidates whose
    :class:`Preconditions` are violated by the current
    :class:`CurrentState`.  Violations are *fatal* for the candidate in
    strict mode; survivors are scored by the fused formula:

.. math::
    Score(g_{motif} | State_t) =
        \\alpha \\cdot \\cos(e_{context}, e_{motif})
        + (1 - \\alpha) \\cdot \\text{RuleSat}(State_t, g_{motif}^{pre})

where :math:`\\text{RuleSat}` is the fraction of imposed precondition checks
satisfied (always 1.0 for survivors of the hard gate; it only differs when
``strict=False`` soft fallback is active).

Zero-breaking change: the public constructor / ``retrieve`` signatures are
unchanged from the legacy implementation.  By default (``coarse_k=None``)
the coarse screen keeps every candidate, reproducing the classic
gate-then-rank behaviour *exactly*; ``coarse_k`` optionally caps the dense
pre-screen to the top-N semantic candidates before the hard gate runs.

Embeddings are pluggable: ``sentence-transformers`` dense models, the
discrete lexical/hash baseline, or any duck-typed object exposing
``embed_query``/``embed_texts`` (or the legacy ``embed`` batch method).
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from .config import AMLConfig, load_default_config
from .embedding import (  # canonical home; re-exported for backwards compat
    DeterministicHashEmbedder,
    EmbeddingProvider,
    cosine_similarity,
)
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
#: Sentinel distinguishing "parameter not passed" from an explicit ``None``
#: (e.g. ``coarse_k=None`` must keep meaning "no pre-screen", even when a
#: config supplies a non-null default).
_UNSET = object()


class DualTrackMotifRetriever:
    """Rule-gated + semantic-ranked motif retriever (no GNNs involved)."""

    def __init__(
        self,
        knowledge_base: MotifKnowledgeBase,
        embedder: EmbeddingProvider | None = None,
        *,
        config: AMLConfig | None = None,
        alpha: float = _UNSET,
        top_k: int = _UNSET,
        strict: bool = _UNSET,
        cache_embeddings: bool = _UNSET,
        coarse_k: int | None = _UNSET,
    ) -> None:
        """Args:
        knowledge_base: source of candidate motifs.
        embedder: embedding backend; defaults to DeterministicHashEmbedder.
            Any pluggable :class:`aml_rag.embedding.EmbeddingProvider` (dense
            or discrete) works, as do legacy duck-typed objects exposing
            ``embed(texts)``.
        config: optional :class:`aml_rag.config.AMLConfig` supplying the
            retrieval-domain defaults.  When omitted (or ``None``) the
            transparent default config is used, whose values equal the
            legacy hard-coded defaults — Zero-Delta, no behaviour change.
            Explicit keyword arguments always take precedence over the
            config values.
        alpha: weight of the semantic score (1-alpha = rule score weight).
        top_k: default number of results to return.
        strict: when True, motifs failing the hard gate are excluded entirely;
                when False, they survive with ``rule_score`` reflecting the
                fraction of satisfied checks (soft fallback, e.g. for
                cold-start debugging).
        cache_embeddings: cache per-motif vectors keyed by motif_id.
        coarse_k: optional size of the Stage-1 dense semantic pre-screen
            (top-N candidates by similarity reach the hard gate).  ``None``
            (default) keeps every candidate — the legacy gate-then-rank
            behaviour, preserved exactly for zero-breaking compatibility.
        """
        cfg = load_default_config(config)
        rc = cfg.retrieval
        alpha = rc.alpha if alpha is _UNSET else alpha
        top_k = rc.top_k if top_k is _UNSET else top_k
        strict = rc.strict if strict is _UNSET else strict
        cache_embeddings = (
            rc.cache_embeddings if cache_embeddings is _UNSET else cache_embeddings
        )
        coarse_k = rc.coarse_k if coarse_k is _UNSET else coarse_k
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be in [0, 1]")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if coarse_k is not None and coarse_k < 1:
            raise ValueError("coarse_k must be >= 1 or None")
        self.knowledge_base = knowledge_base
        self.embedder: EmbeddingProvider = embedder or DeterministicHashEmbedder()
        self.alpha = alpha
        self.top_k = top_k
        self.strict = strict
        self.cache_embeddings = cache_embeddings
        self.coarse_k = coarse_k
        self._motif_vec_cache: dict[str, list[float]] = {}

    # ------------------------------------------- embedding backend adapters
    def _embed_query(self, text: str) -> list[float]:
        """Embed one query text via the provider (rich API preferred)."""
        fn = getattr(self.embedder, "embed_query", None)
        if callable(fn):
            return fn(text)
        return self.embedder.embed([text])[0]  # legacy duck-typed backend

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch via the provider (rich API preferred)."""
        fn = getattr(self.embedder, "embed_texts", None)
        if callable(fn):
            return fn(texts)
        return self.embedder.embed(texts)  # legacy duck-typed backend

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
            embedded = self._embed_batch(pending_texts)
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
        coarse_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Run the two-stage hierarchical pipeline; return the top-K motifs.

        Stage 1 (coarse): dense semantic pre-ranking of every candidate
        motif against the query via the injected embedding provider.
        Stage 2 (fine): topological hard gate over the pre-ranked candidates
        followed by fused weighting ``alpha * sim + (1-alpha) * rule``.

        ``strict`` overrides the instance default per call (soft fallback
        for the planner's prior guarantee); ``coarse_k`` overrides the
        instance default and caps the Stage-1 screen (``None`` = keep all,
        the legacy behaviour). Semantic ties (and pattern bias from
        ``query.target_pattern_type``) are resolved deterministically.
        """
        k = top_k or self.top_k
        ck = coarse_k if coarse_k is not None else self.coarse_k
        if ck is not None and ck < 1:
            raise ValueError("coarse_k must be >= 1 or None")

        # ---- Stage 1: coarse dense-semantic pre-ranking -------------------
        all_motifs = list(self.knowledge_base)
        query_vec = self._embed_query(query.embedding_text)
        motif_vecs = self._motif_vectors(all_motifs)
        sim_by_id = {
            m.motif_id: cosine_similarity(query_vec, mv)
            for m, mv in zip(all_motifs, motif_vecs)
        }
        # deterministic pre-rank: similarity desc -> motif_id asc
        pre_ranked = sorted(all_motifs, key=lambda m: (-sim_by_id[m.motif_id], m.motif_id))
        candidates = pre_ranked if ck is None else pre_ranked[:ck]

        # ---- Stage 2: topological hard gate + fused weighting ------------
        gated: list[tuple[TopologicalMotif, float, list[str]]] = []
        for motif in candidates:
            passed, rule_score, reasons = self.hard_gate(motif, state, strict=strict)
            if passed:
                gated.append((motif, rule_score, reasons))

        results: list[RetrievalResult] = []
        for motif, rule_score, reasons in gated:
            sem = sim_by_id[motif.motif_id]
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
        """Drop cached motif vectors (call after mutating the knowledge base).

        Also clears the embedding provider's internal text cache so stale
        vectors can never survive a knowledge-base mutation.
        """
        self._motif_vec_cache.clear()
        clear = getattr(self.embedder, "clear_cache", None)
        if callable(clear):
            clear()
