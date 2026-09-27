"""Stage-3 Part A unit tests: pluggable embedding providers & two-stage retriever.

Covers:

1. Unified provider contract (embed_query / embed_texts / embed / similarity)
   and the in-memory cache lifecycle.
2. Discrete provider exact parity with the legacy hash algorithm
   (regression check against the pre-refactor implementation).
3. Dense provider lazy loading + defensive degradation when
   ``sentence-transformers`` is absent / fails to load (pure-CPU / CI safe,
   millisecond-level, fully offline).
4. Provider factory and backend introspection.
5. Retriever upgrades: Stage-1 coarse screen (``coarse_k``), hard gate never
   bypassed, backward compatibility with legacy duck-typed embedders, and
   cross-call caching.
6. Stage-1 red line: motif embedding texts contain zero micro noise
   (no addresses / tickers / amounts / timestamps).
"""

from __future__ import annotations

import hashlib
import math
import random
import re
import sys
import types
from typing import Callable

import pytest

import aml_rag.embedding as emb_mod
from aml_rag import (
    AbstractEdge,
    AbstractNode,
    CurrentState,
    DenseEmbeddingProvider,
    DeterministicHashEmbedder,
    DiscreteEmbeddingProvider,
    DualTrackMotifRetriever,
    EmbeddingProvider,
    MotifKnowledgeBase,
    NodeRole,
    OperationType,
    PatternType,
    Preconditions,
    QueryContext,
    TopologicalMotif,
    build_default_knowledge_base,
    build_seed_motifs,
    cosine_similarity,
    make_embedding_provider,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _state(
    level: int,
    chain: str = "Chain_A",
    roles: tuple[NodeRole, ...] = (NodeRole.SOURCE,),
) -> CurrentState:
    return CurrentState(
        current_level=level,
        current_chain=chain,
        active_nodes=[
            AbstractNode(temp_id=f"N{i}", role=role, chain=chain, level=level)
            for i, role in enumerate(roles)
        ],
    )


class CountingProvider(EmbeddingProvider):
    """Provider that counts raw vector computations (caching still active)."""

    def __init__(
        self,
        vector_for: Callable[[str], list[float]],
        *,
        cache_size: int | None = 4096,
    ) -> None:
        super().__init__(cache_size=cache_size)
        self.vector_for = vector_for
        self.computations = 0

    def _embed_uncached(self, texts: list[str]) -> list[list[float]]:
        self.computations += len(texts)
        return [self.vector_for(t) for t in texts]


class LegacyStubEmbedder:
    """Duck-typed legacy backend exposing only ``embed(texts)``."""

    def __init__(self, vector_for: Callable[[str], list[float]]) -> None:
        self.vector_for = vector_for

    def embed(self, texts: list[str]) -> list[list[float]]:  # type: ignore[override]
        return [self.vector_for(t) for t in texts]


def _legacy_hash_embed(text: str, dim: int = 256, fan_out: int = 3, seed: int = 20260829) -> list[float]:
    """Inline copy of the pre-refactor hash algorithm (regression oracle)."""
    word = re.compile(r"[a-z0-9_]+")
    cjk = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
    tokens: list[str] = []
    for m in word.finditer(text.lower()):
        token = m.group()
        chars = cjk.findall(token)
        tokens.extend(chars) if chars else tokens.append(token)
    vec = [0.0] * dim
    for token in tokens:
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
# 1. Unified contract & discrete baseline
# ---------------------------------------------------------------------------
class TestProviderContract:
    def test_single_batch_embed_and_similarity_consistent(self) -> None:
        provider: EmbeddingProvider = DiscreteEmbeddingProvider()
        q = provider.embed_query("bridge to another chain")
        batch = provider.embed_texts(["bridge to another chain"])
        assert q == batch[0]
        # legacy alias stays available
        assert provider.embed(["a", "b"]) == provider.embed_texts(["a", "b"])
        # provider.similarity delegates to cosine
        a = provider.embed_query("swap via a liquidity pool")
        b = provider.embed_query("swap via a liquidity pool")
        assert provider.similarity(a, b) == pytest.approx(1.0, abs=1e-9)
        assert provider.similarity(a, b) == pytest.approx(
            cosine_similarity(a, b), abs=1e-12
        )

    def test_backend_label(self) -> None:
        assert DiscreteEmbeddingProvider().backend == "discrete_hash"
        assert DeterministicHashEmbedder().backend == "DeterministicHashEmbedder"

    def test_discrete_matches_legacy_hash_algorithm(self) -> None:
        samples = [
            "bridge swap layering",
            "cross chain hop to another chain",
            "跨链 跳板 layering",
            "Rapid linear peeled transfers along a single chain",
        ]
        expected = [_legacy_hash_embed(t) for t in samples]
        assert DiscreteEmbeddingProvider().embed_texts(samples) == expected
        assert DeterministicHashEmbedder().embed_texts(samples) == expected

    def test_hash_embedder_positional_signature_backward_compat(self) -> None:
        emb = DeterministicHashEmbedder(64, 2, 42)
        vec = emb.embed(["x"])[0]
        assert len(vec) == 64
        assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0)

    def test_vectors_are_l2_normalised_and_stable(self) -> None:
        for provider in (DiscreteEmbeddingProvider(), DeterministicHashEmbedder()):
            v1 = provider.embed_query("same text")
            v2 = provider.embed_query("same text")
            assert v1 == v2
            assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, abs_tol=1e-9)

    def test_cosine_similarity_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])

    def test_cosine_zero_vector_returns_zero(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# 2. In-memory cache lifecycle
# ---------------------------------------------------------------------------
class TestProviderCache:
    def test_repeats_served_from_cache(self) -> None:
        provider = CountingProvider(lambda t: [1.0, float(len(t)) % 3])
        provider.embed_texts(["a", "b", "a", "b"])
        # in-batch duplicates are computed exactly once
        assert provider.computations == 2
        stats = provider.cache_stats()
        assert stats["size"] == 2
        # second batch: everything served from cache
        provider.embed_texts(["a", "b"])
        assert provider.computations == 2
        assert provider.cache_stats()["hits"] == 2

    def test_clear_cache_forces_recompute(self) -> None:
        provider = CountingProvider(lambda t: [1.0, 0.0])
        provider.embed_query("hello")
        first = provider.computations
        provider.embed_query("hello")
        assert provider.computations == first  # cache hit, no new compute
        provider.clear_cache()
        provider.embed_query("hello")
        assert provider.computations == first + 1

    def test_capacity_evicts_oldest(self) -> None:
        provider = CountingProvider(lambda t: [float(ord(t[0]))], cache_size=2)
        for text in ["a", "b", "c"]:
            provider.embed_query(text)
        assert provider.cache_stats()["size"] == 2
        # "a" was evicted -> recomputed on next access
        before = provider.computations
        provider.embed_query("a")
        assert provider.computations == before + 1

    def test_unbounded_cache_with_none(self) -> None:
        provider = CountingProvider(lambda t: [1.0], cache_size=None)
        for text in ["a", "b", "c", "d", "e"]:
            provider.embed_query(text)
        assert provider.cache_stats()["size"] == 5

    def test_cache_disabled_with_zero(self) -> None:
        provider = CountingProvider(lambda t: [1.0], cache_size=0)
        provider.embed_query("a")
        provider.embed_query("a")
        assert provider.computations == 2

    def test_invalid_cache_size_rejected(self) -> None:
        with pytest.raises(ValueError):
            DiscreteEmbeddingProvider(cache_size=-1)


# ---------------------------------------------------------------------------
# 3. Dense provider: lazy load & defensive degradation
# ---------------------------------------------------------------------------
class TestDenseProvider:
    def _stub_st_module(self, monkeypatch, fail: bool = False) -> None:
        stub = types.ModuleType("sentence_transformers")

        class FakeSentenceTransformer:
            def __init__(self, model_name: str, **kwargs: object) -> None:
                if fail:
                    raise RuntimeError("no network in CI")
                self.model_name = model_name
                self.kwargs = kwargs

            def encode(
                self,
                texts: list[str],
                normalize_embeddings: bool = True,
                show_progress_bar: bool = False,
                convert_to_numpy: bool = True,
            ) -> list[list[float]]:
                assert normalize_embeddings and not show_progress_bar
                return [[float(len(t)) % 7, 2.0, 1.0] for t in texts]

        stub.SentenceTransformer = FakeSentenceTransformer
        monkeypatch.setitem(sys.modules, "sentence_transformers", stub)
        monkeypatch.setattr(
            emb_mod, "is_sentence_transformers_available", lambda: True
        )

    def test_lazy_load_and_model_usage(self, monkeypatch) -> None:
        self._stub_st_module(monkeypatch)
        provider = DenseEmbeddingProvider(model_name="test-model")
        # construction must not load anything
        assert provider.backend == "unloaded:test-model"
        assert not provider.degraded

        vecs = provider.embed_texts(["aa", "bbbb"])
        assert provider.backend == "sentence_transformers:test-model"
        assert not provider.degraded
        assert provider.load_error is None
        assert vecs == [[2.0, 2.0, 1.0], [4.0, 2.0, 1.0]]
        # cached: subsequent call hits the in-memory cache
        assert provider.embed_query("aa") == [2.0, 2.0, 1.0]
        assert provider.cache_stats()["hits"] == 1

    def test_degrades_to_discrete_hash_when_package_missing(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            emb_mod, "is_sentence_transformers_available", lambda: False
        )
        provider = DenseEmbeddingProvider(model_name="all-MiniLM-L6-v2")
        reference = DiscreteEmbeddingProvider()
        with pytest.warns(RuntimeWarning, match="degraded"):
            vecs = provider.embed_texts(["a", "b"])
        assert provider.backend == "hash_fallback"
        assert provider.degraded
        assert provider.load_error is not None
        assert vecs == reference.embed_texts(["a", "b"])
        # warning is emitted only once
        import warnings

        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            provider.embed_texts(["a", "b", "c"])
        assert not [w for w in record if issubclass(w.category, RuntimeWarning)]

    def test_degrades_on_model_load_failure(self, monkeypatch) -> None:
        self._stub_st_module(monkeypatch, fail=True)
        provider = DenseEmbeddingProvider()
        with pytest.warns(RuntimeWarning):
            vecs = provider.embed_query("hello")
        assert provider.degraded
        assert provider.backend == "hash_fallback"
        assert "RuntimeError" in (provider.load_error or "")
        # service continuity: vectors still valid & normalised
        assert len(vecs) == 256
        assert math.isclose(math.sqrt(sum(x * x for x in vecs)), 1.0, abs_tol=1e-9)

    def test_ranks_identically_to_discrete_when_degraded(self, monkeypatch) -> None:
        monkeypatch.setattr(
            emb_mod, "is_sentence_transformers_available", lambda: False
        )
        kb = build_default_knowledge_base()
        dense_retriever = DualTrackMotifRetriever(
            kb, embedder=DenseEmbeddingProvider(), top_k=50
        )
        discrete_retriever = DualTrackMotifRetriever(
            kb, embedder=DiscreteEmbeddingProvider(), top_k=50
        )
        state = _state(0)
        query = QueryContext(scenario="swap and bridge", tactic_goal="hop chains")
        with pytest.warns(RuntimeWarning, match="degraded"):
            dense_ids = [
                r.motif_id for r in dense_retriever.retrieve(state, query)
            ]
        discrete_ids = [r.motif_id for r in discrete_retriever.retrieve(state, query)]
        assert dense_ids == discrete_ids


# ---------------------------------------------------------------------------
# 4. Factory
# ---------------------------------------------------------------------------
class TestFactory:
    def test_kinds(self) -> None:
        assert isinstance(make_embedding_provider("discrete"), DiscreteEmbeddingProvider)
        assert isinstance(make_embedding_provider("dense"), DenseEmbeddingProvider)
        assert isinstance(make_embedding_provider("auto"), DenseEmbeddingProvider)
        assert isinstance(make_embedding_provider(), DenseEmbeddingProvider)

    def test_kwargs_forwarded(self) -> None:
        dense = make_embedding_provider("dense", model_name="bge-small-en-v1.5")
        assert isinstance(dense, DenseEmbeddingProvider)
        assert dense.model_name == "bge-small-en-v1.5"
        discrete = make_embedding_provider("discrete", dim=128)
        assert len(discrete.embed_query("hello")) == 128

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValueError):
            make_embedding_provider("quantum")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. Retriever upgrades (two-stage pipeline, zero breaking change)
# ---------------------------------------------------------------------------
class TestRetrieverTwoStage:
    def test_legacy_duck_typed_embedder_still_works(self) -> None:
        # only `.embed(texts)` available (pre-refactor contract)
        kb = build_default_knowledge_base()
        retriever = DualTrackMotifRetriever(
            kb, embedder=LegacyStubEmbedder(lambda t: [1.0, 0.0]), top_k=50
        )
        results = retriever.retrieve(_state(0), QueryContext(scenario="s", tactic_goal="g"))
        assert results, "legacy embedder contract must remain supported"

    def test_coarse_k_caps_stage1_candidates(self) -> None:
        kb = build_default_knowledge_base()
        query = QueryContext(
            scenario="launder exploit proceeds",
            tactic_goal="swap to a stable asset then bridge off-chain",
        )
        emb = DeterministicHashEmbedder()
        sims = {
            m.motif_id: cosine_similarity(
                emb.embed_query(query.embedding_text),
                emb.embed_query(m.semantic_text()),
            )
            for m in kb
        }
        top4 = {mid for mid, _ in sorted(sims.items(), key=lambda kv: (-kv[1], kv[0]))[:4]}

        retriever = DualTrackMotifRetriever(
            kb, embedder=DeterministicHashEmbedder(), coarse_k=4, top_k=50
        )
        results = retriever.retrieve(_state(0), query)
        assert 0 < len(results) <= 4
        assert {r.motif_id for r in results} <= top4
        # semantic order preserved inside the coarse window
        combined = [(r.motif_id, r.combined_score) for r in results]
        assert combined == sorted(combined, key=lambda kv: -kv[1])

    def test_coarse_k_none_matches_legacy_behaviour(self) -> None:
        kb = build_default_knowledge_base()
        state, query = _state(0), QueryContext(scenario="cold start", tactic_goal="begin")
        legacy = DualTrackMotifRetriever(kb, top_k=50)
        upgraded = DualTrackMotifRetriever(kb, coarse_k=None, top_k=50)
        assert [r.motif_id for r in legacy.retrieve(state, query)] == [
            r.motif_id for r in upgraded.retrieve(state, query)
        ]
        # instance default caps the coarse window...
        capped = DualTrackMotifRetriever(kb, coarse_k=2, top_k=50)
        assert len(capped.retrieve(state, query)) <= 2
        # ...and a per-call override can widen it back (unlimited)
        overridden = capped.retrieve(state, query, coarse_k=1000)
        assert [r.motif_id for r in overridden] == [
            r.motif_id for r in legacy.retrieve(state, query)
        ]

    def test_coarse_screen_never_bypasses_hard_gate(self) -> None:
        blocked = TopologicalMotif(
            motif_id="Blocked_Semantic_Winner",
            pattern_type=PatternType.PEELING_CHAIN,
            description="semantic favourite but gate-violating",
            preconditions=Preconditions(min_level=9),
            nodes=[
                AbstractNode(temp_id="S", role=NodeRole.SOURCE, chain="Chain_A", level=0),
                AbstractNode(temp_id="T", role=NodeRole.TARGET, chain="Chain_A", level=1),
            ],
            edges=[AbstractEdge(source="S", target="T", operation=OperationType.TRANSFER)],
        )
        passing = TopologicalMotif(
            motif_id="Passing_Not_Coarse",
            pattern_type=PatternType.PEELING_CHAIN,
            description="unconstrained candidate outside the coarse window",
            nodes=[
                AbstractNode(temp_id="S", role=NodeRole.SOURCE, chain="Chain_A", level=0),
                AbstractNode(temp_id="T", role=NodeRole.TARGET, chain="Chain_A", level=1),
            ],
            edges=[AbstractEdge(source="S", target="T", operation=OperationType.TRANSFER)],
        )
        kb = MotifKnowledgeBase([blocked, passing])

        def vector_for(text: str) -> list[float]:
            return [1.0, 0.0] if "semantic favourite" in text else [0.0, 1.0]

        embedder = LegacyStubEmbedder(vector_for)
        retriever = DualTrackMotifRetriever(
            kb, embedder=embedder, coarse_k=1, strict=True, top_k=50
        )
        # query text must match the BLOCKED motif vector
        query = QueryContext(scenario="semantic favourite match", tactic_goal="g")
        assert retriever.retrieve(_state(0), query) == []
        # soft fallback (strict=False) admits the blocked motif with rule 0
        soft = retriever.retrieve(_state(0), query, strict=False)
        assert [r.motif_id for r in soft] == ["Blocked_Semantic_Winner"]
        assert soft[0].rule_score == 0.0

    def test_invalid_coarse_k_rejected(self) -> None:
        kb = build_default_knowledge_base()
        with pytest.raises(ValueError):
            DualTrackMotifRetriever(kb, coarse_k=0)
        retriever = DualTrackMotifRetriever(kb)
        with pytest.raises(ValueError):
            retriever.retrieve(_state(0), QueryContext(scenario="s", tactic_goal="g"), coarse_k=0)

    def test_provider_cache_reused_across_calls(self) -> None:
        provider = CountingProvider(lambda t: [1.0, float(len(t)) % 3])
        retriever = DualTrackMotifRetriever(
            build_default_knowledge_base(), embedder=provider, top_k=5
        )
        state, query = _state(0), QueryContext(scenario="s", tactic_goal="g")
        retriever.retrieve(state, query)
        first = provider.computations
        assert first > 0
        retriever.retrieve(state, query)
        assert provider.computations == first  # fully served from caches

    def test_invalidate_cache_clears_provider_cache(self) -> None:
        provider = CountingProvider(lambda t: [1.0, float(len(t)) % 3])
        retriever = DualTrackMotifRetriever(
            build_default_knowledge_base(), embedder=provider, top_k=5
        )
        state, query = _state(0), QueryContext(scenario="s", tactic_goal="g")
        retriever.retrieve(state, query)
        first = provider.computations
        retriever.invalidate_cache()
        retriever.retrieve(state, query)
        assert provider.computations > first


# ---------------------------------------------------------------------------
# 6. Stage-1 red line: zero micro-numerical noise in embedded texts
# ---------------------------------------------------------------------------
class TestMicroNoiseRedLine:
    _ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{8,}")
    # topological descriptors like "N-to-1" are not micro amounts
    _AMOUNT_RE = re.compile(r"(?<!to-)\b\d+(?:\.\d+)?\b")
    _TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
    _BANNED_TICKERS = frozenset(
        {"USDC", "USDT", "DAI", "ETH", "BTC", "WBTC", "SOL", "BNB", "AVAX", "MATIC", "XMR"}
    )

    @pytest.mark.parametrize("motif", build_seed_motifs(), ids=lambda m: m.motif_id)
    def test_semantic_text_free_of_micro_noise(self, motif: TopologicalMotif) -> None:
        text = motif.semantic_text()
        assert not self._ADDRESS_RE.search(text), f"wallet address in: {text}"
        assert not self._TIMESTAMP_RE.search(text), f"timestamp in: {text}"
        assert not self._AMOUNT_RE.search(text), f"micro amount in: {text}"
        words = set(re.findall(r"[A-Za-z]+", text))
        assert not (words & self._BANNED_TICKERS), f"token ticker in: {text}"

    def test_query_embedding_text_contract(self) -> None:
        # QueryContext flattens scenario + tactic goal only (no extra fields).
        query = QueryContext(scenario="layer funds", tactic_goal="split then merge")
        assert query.embedding_text == "layer funds\nsplit then merge"
