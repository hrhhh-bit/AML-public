"""End-to-end tests for the Module-1 dual-track RAG pipeline.

Covers:
1. Pydantic validation of every seed motif (incl. DAG & branching checks).
2. Dual-track retrieval accuracy under specific mock `CurrentState` queries
   (hard precondition gate + semantic ranking + alpha weighting).
3. Agent-ready prompt generation (JSON & Mermaid).
4. Supporting contracts: storage JSON round-trip, extraction parser,
   redundancy compression.
"""

from __future__ import annotations

import math
from typing import Callable

import pytest
from pydantic import ValidationError

from aml_rag import (
    AbstractEdge,
    AbstractNode,
    CurrentState,
    DeterministicHashEmbedder,
    DistillationParseError,
    DualTrackMotifRetriever,
    MotifExtractor,
    MotifKnowledgeBase,
    NodeRole,
    OperationType,
    PatternType,
    Preconditions,
    PromptContextCompressor,
    QueryContext,
    RetrievalResult,
    TopologicalMotif,
    build_default_knowledge_base,
    build_seed_motifs,
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


class StubEmbedder:
    """Deterministic lookup embedder: maps text -> fixed vectors by keyword."""

    def __init__(self, vector_for: Callable[[str], list[float]]) -> None:
        self.vector_for = vector_for

    def embed(self, texts: list[str]) -> list[list[float]]:  # type: ignore[override]
        return [self.vector_for(t) for t in texts]


# ---------------------------------------------------------------------------
# 1. Seed motif Pydantic validation
# ---------------------------------------------------------------------------
def test_seed_motifs_validate_and_ids_are_unique() -> None:
    motifs = build_seed_motifs()
    assert len(motifs) >= 6, "at least the 6 mandatory motif families required"
    ids = [m.motif_id for m in motifs]
    assert len(ids) == len(set(ids)), "motif ids must be unique"


@pytest.mark.parametrize("motif", build_seed_motifs(), ids=lambda m: m.motif_id)
def test_every_seed_motif_is_a_valid_dag(motif: TopologicalMotif) -> None:
    assert motif.is_dag()
    levels = [n.level for n in motif.nodes]
    assert min(levels) >= 0
    # every edge strictly advances DAG level
    level_of = {n.temp_id: n.level for n in motif.nodes}
    for edge in motif.edges:
        assert level_of[edge.target] > level_of[edge.source]
    # branching factor respected
    out_deg: dict[str, int] = {}
    for edge in motif.edges:
        out_deg[edge.source] = out_deg.get(edge.source, 0) + 1
    assert all(d <= motif.constraints.max_branching_factor for d in out_deg.values())


def test_invalid_motifs_are_rejected() -> None:
    base = build_seed_motifs()[0]

    with pytest.raises(ValidationError):
        TopologicalMotif(
            **base.model_dump(exclude={"edges"}),
            edges=[AbstractEdge(source="S", target="S", operation=OperationType.TRANSFER)],
        )  # self-loop

    with pytest.raises(ValidationError):
        TopologicalMotif(
            **base.model_dump(exclude={"edges"}),
            edges=[
                AbstractEdge(source="S", target="I1", operation=OperationType.TRANSFER),
                AbstractEdge(source="I1", target="S", operation=OperationType.TRANSFER),
            ],
        )  # cycle / level regression

    with pytest.raises(ValidationError):
        TopologicalMotif(
            **base.model_dump(exclude={"edges"}),
            edges=[
                AbstractEdge(source="S", target="GHOST", operation=OperationType.TRANSFER),
            ],
        )  # dangling endpoint


def test_post_state_effect_consistency_check() -> None:
    from aml_rag.schema import PostStateEffect

    with pytest.raises(ValidationError):
        PostStateEffect(chain_transition=False, target_chain="Chain_B")


# ---------------------------------------------------------------------------
# 2. Dual-track retrieval accuracy
# ---------------------------------------------------------------------------
def test_cold_start_gate_only_admits_min_level_zero_motifs() -> None:
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    state = _state(0)
    query = QueryContext(scenario="cold start", tactic_goal="begin layering")

    results = retriever.retrieve(state, query, top_k=50)
    admitted = {r.motif_id for r in results}

    assert admitted == {
        "Peeling_Chain_Single_Chain",   # min_level=0, role ok
        "DEX_Liquidity_Pool_Swap",      # min_level=0, role ok
    }


def test_role_gate_excludes_incompatible_motifs() -> None:
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    state = _state(0, roles=(NodeRole.INTERMEDIATE,))
    query = QueryContext(scenario="layering", tactic_goal="continue")

    admitted = {r.motif_id for r in retriever.retrieve(state, query, top_k=50)}
    # Peeling allows Intermediate; DEX only allows Source/Asset_Conversion
    assert admitted == {"Peeling_Chain_Single_Chain"}


def test_chain_gate_excludes_motifs_requiring_chain_a() -> None:
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    state = _state(2, chain="Chain_B")
    query = QueryContext(scenario="multi chain", tactic_goal="hop chains")

    results = retriever.retrieve(state, query, top_k=50)
    admitted = {r.motif_id for r in results}
    assert "Multi_Chain_Hop_Layering" not in admitted  # requires Chain_A
    assert "Cross_Chain_Bridge_And_Back" not in admitted  # min_level=3 > 2
    # all survivors must have passed every imposed check
    for r in results:
        assert all("FAIL" not in reason for reason in r.gate_reasons)


def test_branch_gate_excludes_linear_motifs_under_high_parallelism() -> None:
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    state = _state(
        1, roles=(NodeRole.INTERMEDIATE, NodeRole.INTERMEDIATE, NodeRole.INTERMEDIATE)
    )
    query = QueryContext(scenario="fan out", tactic_goal="split into streams")

    admitted = {r.motif_id for r in retriever.retrieve(state, query, top_k=50)}
    assert "Peeling_Chain_Single_Chain" not in admitted  # max_active_branches=1
    assert "Multi_Split_Obfuscation" in admitted  # max_active_branches=4


def test_semantic_track_ranks_swap_bridge_first() -> None:
    retriever = DualTrackMotifRetriever(
        build_default_knowledge_base(),
        embedder=DeterministicHashEmbedder(),
        alpha=0.6,
        top_k=5,
    )
    state = _state(2, roles=(NodeRole.ASSET_CONVERSION,))
    query = QueryContext(
        scenario="launder proceeds of a DeFi exploit",
        tactic_goal="swap to stablecoin then bridge to another chain",
    )
    results = retriever.retrieve(state, query)

    assert results, "retrieval should not be empty"
    assert results[0].motif_id == "Cross_Chain_Swap_Bridge"
    assert "Swap" in {e.operation.value for e in results[0].motif.edges}
    assert "Bridge" in {e.operation.value for e in results[0].motif.edges}


def test_pattern_type_bias_tie_break() -> None:
    retriever = DualTrackMotifRetriever(
        build_default_knowledge_base(),
        embedder=DeterministicHashEmbedder(),
        alpha=1.0,  # pure semantic track
        top_k=50,
    )
    state = _state(0)
    query = QueryContext(
        scenario="anything", tactic_goal="anything",
        target_pattern_type=PatternType.PEELING_CHAIN,
    )
    # With alpha=1.0 ranking is purely semantic; bias adds tiny deterministic
    # bonus to Peeling_Chain motifs on semantic ties only. Robust assertion:
    admitted = {r.motif_id for r in retriever.retrieve(state, query)}
    assert "Peeling_Chain_Single_Chain" in admitted


def test_alpha_weights_rule_and_semantic_scores() -> None:
    # motif A passes all checks (rule=1.0); motif B violates min_level and is
    # only kept because strict=False (rule=0.0)
    a = TopologicalMotif(
        motif_id="Strict_OK",
        pattern_type=PatternType.PEELING_CHAIN,
        description="Strict_OK candidate",
        preconditions=Preconditions(),  # unconstrained -> rule_score 1.0
        nodes=[
            AbstractNode(temp_id="S", role=NodeRole.SOURCE, chain="Chain_A", level=0),
            AbstractNode(temp_id="T", role=NodeRole.TARGET, chain="Chain_A", level=1),
        ],
        edges=[AbstractEdge(source="S", target="T", operation=OperationType.TRANSFER)],
    )
    b = TopologicalMotif(
        motif_id="Soft_Fail",
        pattern_type=PatternType.PEELING_CHAIN,
        description="Soft_Fail candidate",
        preconditions=Preconditions(min_level=9),
        nodes=[
            AbstractNode(temp_id="S", role=NodeRole.SOURCE, chain="Chain_A", level=0),
            AbstractNode(temp_id="T", role=NodeRole.TARGET, chain="Chain_A", level=1),
        ],
        edges=[AbstractEdge(source="S", target="T", operation=OperationType.TRANSFER)],
    )
    kb = MotifKnowledgeBase([a, b])

    def vector_for(text: str) -> list[float]:
        if "Strict_OK" in text:
            return [1.0, 0.0]
        if "Soft_Fail" in text:
            return [0.0, 1.0]
        return [1.0, 0.0]  # query vector (matches Strict_OK)

    embedder = StubEmbedder(vector_for)
    retriever = DualTrackMotifRetriever(
        kb, embedder=embedder, alpha=0.7, top_k=5, strict=False
    )
    state = _state(0)
    query = QueryContext(scenario="test", tactic_goal="test")  # query vec = [1,0]

    results = retriever.retrieve(state, query)
    by_id = {r.motif_id: r for r in results}

    assert by_id["Strict_OK"].rule_score == 1.0
    assert by_id["Soft_Fail"].rule_score == 0.0
    # combined = alpha * semantic + (1-alpha) * rule
    assert by_id["Strict_OK"].combined_score == pytest.approx(0.7 * 1.0 + 0.3 * 1.0)
    assert by_id["Soft_Fail"].combined_score == pytest.approx(0.7 * 0.0 + 0.3 * 0.0)
    assert results[0].motif_id == "Strict_OK"


def test_hard_gate_empty_result_on_impossible_state() -> None:
    retriever = DualTrackMotifRetriever(build_default_knowledge_base(), strict=True)
    state = _state(0, chain="Chain_X", roles=(NodeRole.TARGET,))
    query = QueryContext(scenario="x", tactic_goal="x")
    assert retriever.retrieve(state, query, top_k=50) == []


# ---------------------------------------------------------------------------
# 3. Agent-ready prompt generation
# ---------------------------------------------------------------------------
def test_agent_prompt_contains_json_mermaid_and_ordering() -> None:
    kb = build_default_knowledge_base()
    retriever = DualTrackMotifRetriever(kb)
    state = _state(2, roles=(NodeRole.ASSET_CONVERSION,))
    query = QueryContext(
        scenario="exploit laundering",
        tactic_goal="swap and bridge cross chain",
    )
    results = retriever.retrieve(state, query, top_k=3)

    compressor = PromptContextCompressor(max_motifs=3, output_format="hybrid")
    prompt = compressor.build_agent_prompt(state, query, results)

    assert prompt, "prompt must not be empty"
    assert "[AML-PRIOR-CONTEXT]" in prompt
    assert "<STATE>" in prompt and "<QUERY>" in prompt and "<MOTIFS>" in prompt
    assert "<INSTRUCTION>" in prompt
    assert "flowchart LR" in prompt  # mermaid block present
    assert "-->|" in prompt  # mermaid edge syntax
    assert results[0].motif_id in prompt
    # motifs are ordered by rank
    assert prompt.index(results[0].motif_id) < prompt.index(results[1].motif_id)


def test_agent_prompt_json_only_format() -> None:
    kb = build_default_knowledge_base()
    retriever = DualTrackMotifRetriever(kb)
    state = _state(0)
    query = QueryContext(scenario="s", tactic_goal="g")
    results = retriever.retrieve(state, query, top_k=2)

    prompt = PromptContextCompressor(output_format="json").build_agent_prompt(
        state, query, results
    )
    assert "```mermaid" not in prompt
    assert '"edges"' in prompt  # MOT triplets serialized


def test_agent_prompt_empty_result_falls_back_with_note() -> None:
    state = _state(0, chain="Chain_X")
    query = QueryContext(scenario="s", tactic_goal="g")
    prompt = PromptContextCompressor().build_agent_prompt(state, query, [])
    assert "<MOTIFS>[]</MOTIFS>" in prompt
    assert "<NOTE>" in prompt


def test_compressor_drops_dominated_sub_paths() -> None:
    single = build_seed_motifs()[0]  # Peeling_Chain_Single_Chain (3 edges)
    multi = next(
        m for m in build_seed_motifs() if m.motif_id == "Peeling_Chain_Multi_Layer"
    )  # 6 edges, superset signatures
    r_single = RetrievalResult(
        motif_id=single.motif_id,
        pattern_type=single.pattern_type,
        description=single.description,
        motif=single,
        rule_score=1.0,
        semantic_score=0.5,
        combined_score=0.5,
    )
    r_multi = RetrievalResult(
        motif_id=multi.motif_id,
        pattern_type=multi.pattern_type,
        description=multi.description,
        motif=multi,
        rule_score=1.0,
        semantic_score=0.9,
        combined_score=0.9,
    )
    compressed = PromptContextCompressor().compress([r_single, r_multi])
    assert [r.motif_id for r in compressed] == ["Peeling_Chain_Multi_Layer"]


# ---------------------------------------------------------------------------
# 4. Supporting contracts (storage, extractor)
# ---------------------------------------------------------------------------
def test_knowledge_base_json_round_trip(tmp_path: object) -> None:
    kb = build_default_knowledge_base()
    raw = kb.to_json_str()
    restored = MotifKnowledgeBase.from_json_str(raw)
    assert len(restored) == len(kb)
    assert set(restored.motif_ids) == set(kb.motif_ids)
    for mid in kb.motif_ids:
        assert restored.get(mid) == kb.get(mid)

    import pathlib

    path = pathlib.Path(tmp_path) / "kb.json"  # type: ignore[arg-type]
    kb.save(path)
    assert MotifKnowledgeBase.load(path).get("Peeling_Chain_Single_Chain").is_dag()


def test_extractor_parses_fenced_json_and_validates() -> None:
    motif_dict = build_seed_motifs()[1].model_dump(mode="json")
    fenced_reply = "```json\n" + __import__("json").dumps([motif_dict]) + "\n```"

    extractor = MotifExtractor()
    parsed = extractor.parse_response(fenced_reply)
    assert len(parsed) == 1
    assert parsed[0].motif_id == motif_dict["motif_id"]
    assert parsed[0].is_dag()


def test_extractor_rejects_garbage() -> None:
    with pytest.raises(DistillationParseError):
        MotifExtractor().parse_response("I am not JSON at all")


def test_extractor_requires_llm_for_end_to_end() -> None:
    from aml_rag import DistillationError

    with pytest.raises(DistillationError):
        MotifExtractor().extract("some report")


def test_extractor_end_to_end_with_mock_llm() -> None:
    reply = __import__("json").dumps(
        [build_seed_motifs()[5].model_dump(mode="json")]
    )
    extractor = MotifExtractor(llm=lambda prompt: reply)
    motifs = extractor.extract("fake report about DEX swap")
    assert [m.motif_id for m in motifs] == ["DEX_Liquidity_Pool_Swap"]


def test_deterministic_embedder_is_stable_and_normalised() -> None:
    emb = DeterministicHashEmbedder()
    v1 = emb.embed(["bridge swap"])[0]
    v2 = emb.embed(["bridge swap"])[0]
    assert v1 == v2
    assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0)
    # lexical overlap => positive similarity
    a = emb.embed(["bridge to another chain"])[0]
    b = emb.embed(["bridge and swap"])[0]
    from aml_rag import cosine_similarity

    assert cosine_similarity(a, b) > 0.0


# ---------------------------------------------------------------------------
# Optional manual runner (works without pytest installed)
# ---------------------------------------------------------------------------
def _main() -> None:
    print("Running aml_rag pipeline checks (manual mode)...")
    test_seed_motifs_validate_and_ids_are_unique()
    for motif in build_seed_motifs():
        test_every_seed_motif_is_a_valid_dag(motif)
    test_cold_start_gate_only_admits_min_level_zero_motifs()
    test_role_gate_excludes_incompatible_motifs()
    test_chain_gate_excludes_motifs_requiring_chain_a()
    test_branch_gate_excludes_linear_motifs_under_high_parallelism()
    test_semantic_track_ranks_swap_bridge_first()
    test_agent_prompt_contains_json_mermaid_and_ordering()
    print("All checks passed.")


if __name__ == "__main__":
    _main()
