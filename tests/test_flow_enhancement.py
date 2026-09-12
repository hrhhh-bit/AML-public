"""Tests for the scale-tier & flow-share enhancement.

Covers the acceptance criteria of the architecture evolution task:

1. backward compatibility (the full existing suite stays green);
2. flow-conservation gate interception with standardised reflection text;
3. purity audit: exported results contain only normalised ratios — no
   addresses / timestamps.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from aml_agent import (
    PlannerAgent,
    ScaleTier,
    ScenarioSpec,
    audit_export_purity,
    build_planner_prompt,
    build_strategy_narrative,
)
from aml_env import AgentAction, BehavioralEnvironment
from aml_rag import (
    PromptContextCompressor,
    RetrievalResult,
    build_default_knowledge_base,
)
from aml_rag.mock_data import SEED_MOTIFS
from aml_rag.schema import (
    FLOW_TOLERANCE,
    AbstractEdge,
    NodeRole,
    OperationType,
    TopologicalMotif,
)
from aml_rag.retriever import DualTrackMotifRetriever

SRC = NodeRole.SOURCE
INT = NodeRole.INTERMEDIATE
AGG = NodeRole.AGGREGATOR
CC = NodeRole.CROSS_CHAIN
TGT = NodeRole.TARGET

TRANSFER = OperationType.TRANSFER
SPLIT = OperationType.SPLIT
MERGE = OperationType.MERGE
BRIDGE = OperationType.BRIDGE


def _split_action(num_children: int, shares: list[float] | None) -> AgentAction:
    params: dict[str, object] = {"num_children": num_children}
    if shares is not None:
        params["flow_shares"] = shares
    return AgentAction(
        operation=SPLIT,
        parent_ids=["node_0"],
        target_role=INT,
        target_chain="Chain_A",
        parameters=params,
    )


# ---------------------------------------------------------------------------
# 1. edge contract: flow_share defaults & bounds
# ---------------------------------------------------------------------------
def test_edge_flow_share_default_is_one() -> None:
    edge = AbstractEdge(source="a", target="b", operation=TRANSFER)
    assert edge.flow_share == 1.0


@pytest.mark.parametrize("bad", [0.0, -0.5, 1.2, 2.0])
def test_edge_flow_share_rejects_out_of_range(bad: float) -> None:
    with pytest.raises(ValidationError):
        AbstractEdge(source="a", target="b", operation=TRANSFER, flow_share=bad)


# ---------------------------------------------------------------------------
# 2. seed motifs carry conserving flow archetypes
# ---------------------------------------------------------------------------
def test_seed_motifs_respect_flow_conservation() -> None:
    for motif in SEED_MOTIFS:
        split_groups: dict[str, list[AbstractEdge]] = {}
        merge_groups: dict[str, list[AbstractEdge]] = {}
        for e in motif.edges:
            if e.operation == SPLIT:
                split_groups.setdefault(e.source, []).append(e)
            elif e.operation == MERGE:
                merge_groups.setdefault(e.target, []).append(e)
        for nid, group in split_groups.items():
            assert abs(sum(e.flow_share for e in group) - 1.0) <= FLOW_TOLERANCE, (
                f"{motif.motif_id} node {nid} split shares unconserved"
            )
        for nid, group in merge_groups.items():
            assert abs(sum(e.flow_share for e in group) - 1.0) <= FLOW_TOLERANCE, (
                f"{motif.motif_id} node {nid} merge shares unconserved"
            )


def test_archetypes_are_behaviourally_distinct() -> None:
    obfuscation = next(
        m for m in SEED_MOTIFS if m.motif_id == "Multi_Split_Obfuscation"
    )
    mixer = next(
        m for m in SEED_MOTIFS if m.motif_id == "Mixer_Anonymization_Split_Merge"
    )
    obf_split = sorted(
        e.flow_share for e in obfuscation.edges if e.operation == SPLIT
    )
    mixer_split = sorted(
        e.flow_share for e in mixer.edges if e.operation == SPLIT
    )
    # asymmetric trunk+peel archetype vs. equal-slice archetype
    assert obf_split != mixer_split
    assert max(obf_split) > 0.5 and min(obf_split) < 0.2


# ---------------------------------------------------------------------------
# 3. hard verifier: flow conservation gate
# ---------------------------------------------------------------------------
def test_verifier_rejects_unconserved_split_with_standard_text() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    result = env.step(_split_action(2, [0.6, 0.5]))  # sum = 1.1

    assert result.reward == -1.0
    assert result.done is False
    error = result.info["error"]
    assert "flow conservation violated" in error
    assert "sum(flow_shares)=1.1000" in error
    assert "1.0" in error and "0.01" in error  # tolerance stated for reflection


def test_verifier_rejects_malformed_shares() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()

    wrong_len = env.step(_split_action(2, [0.7]))
    assert "exactly 2 entries" in wrong_len.info["error"]

    out_of_range = env.step(_split_action(2, [1.2, -0.2]))
    assert "in (0.0, 1.0]" in out_of_range.info["error"]

    non_numeric = env.step(
        AgentAction(
            operation=SPLIT,
            parent_ids=["node_0"],
            target_role=INT,
            target_chain="Chain_A",
            parameters={"num_children": 2, "flow_shares": ["a", "b"]},
        )
    )
    assert "must be numeric" in non_numeric.info["error"]


def test_verifier_allows_missing_shares_and_conserving_shares() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    ok_missing = env.step(_split_action(2, None))  # environment fallback
    assert ok_missing.info["accepted"] is True

    env.reset()
    ok_conserved = env.step(_split_action(2, [0.4, 0.6]))
    assert ok_conserved.info["accepted"] is True


def test_verifier_checks_merge_shares_when_provided() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    env.step(_split_action(2, [0.5, 0.5]))  # node_1, node_2

    bad = env.step(
        AgentAction(
            operation=MERGE,
            parent_ids=["node_1", "node_2"],
            target_role=AGG,
            target_chain="Chain_A",
            parameters={"flow_shares": [0.8, 0.8]},
        )
    )
    assert "flow conservation violated" in bad.info["error"]


# ---------------------------------------------------------------------------
# 4. environment: share writing, fallback, export
# ---------------------------------------------------------------------------
def test_environment_equal_split_fallback() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    env.step(_split_action(2, None))
    export = env.export_behavioral_graph()
    split_edges = [e for e in export["edges"] if e["operation"] == "Split"]
    assert [e["flow_share"] for e in split_edges] == [0.5, 0.5]
    assert "0.50" in env.render_mermaid()  # ratio visible on edge labels


def test_environment_writes_provided_shares() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    env.step(_split_action(2, [0.7, 0.3]))
    export = env.export_behavioral_graph()
    shares = sorted(
        e["flow_share"] for e in export["edges"] if e["operation"] == "Split"
    )
    assert shares == [0.3, 0.7]


# ---------------------------------------------------------------------------
# 5. context builder presents flow ratios
# ---------------------------------------------------------------------------
def test_context_builder_presents_flow_ratios() -> None:
    mixer = next(
        m for m in SEED_MOTIFS if m.motif_id == "Mixer_Anonymization_Split_Merge"
    )
    payload = PromptContextCompressor().to_compact_json(mixer)
    split_rows = [row for row in payload["edges"] if row[2] == "Split"]
    assert split_rows == [["AC", "I1", "Split", 0.5], ["AC", "I2", "Split", 0.5]]
    mermaid = PromptContextCompressor().to_mermaid(mixer)
    assert "Split 0.50" in mermaid


# ---------------------------------------------------------------------------
# 6. prompts: conservation rules & scale tier guidance
# ---------------------------------------------------------------------------
def test_prompt_contains_conservation_and_tier_blocks() -> None:
    env = BehavioralEnvironment()
    spec = ScenarioSpec(
        name="whale-case",
        scenario="launder whale funds",
        tactic_goal="deep obfuscation",
        scale_tier=ScaleTier.WHALE,
        estimated_value_usd=50_000_000.0,
    )
    state = env.reset()
    prompt = build_planner_prompt(spec, state, "prior")

    assert "Flow conservation" in prompt
    assert "flow_shares" in prompt
    assert "<SCALE_TIER>" in prompt
    assert "whale-scale" in prompt


def test_scale_tier_guidance_variants() -> None:
    for tier in ScaleTier:
        assert tier.complexity_guidance()


# ---------------------------------------------------------------------------
# 7. planner: archetype injection / equal-split fallback
# ---------------------------------------------------------------------------
def _result_for(motif: TopologicalMotif) -> RetrievalResult:
    return RetrievalResult(
        motif_id=motif.motif_id,
        pattern_type=motif.pattern_type,
        description=motif.description,
        motif=motif,
        rule_score=1.0,
        semantic_score=1.0,
        combined_score=1.0,
    )


def test_planner_injects_motif_archetype_shares() -> None:
    mixer = next(
        m for m in SEED_MOTIFS if m.motif_id == "Mixer_Anonymization_Split_Merge"
    )
    multi = next(
        m for m in SEED_MOTIFS if m.motif_id == "Multi_Split_Obfuscation"
    )
    results = [_result_for(mixer), _result_for(multi)]

    assert PlannerAgent._split_prototype(results, 2) == [0.5, 0.5]
    assert PlannerAgent._split_prototype(results, 3) == [0.6, 0.25, 0.15]
    assert PlannerAgent._split_prototype(results, 4) is None

    action = _split_action(2, None)
    enriched = PlannerAgent._enrich_flow_shares(action, results)
    assert enriched.parameters["flow_shares"] == [0.5, 0.5]

    # agent-provided shares are never overridden
    keep = _split_action(2, [0.9, 0.1])
    enriched = PlannerAgent._enrich_flow_shares(keep, results)
    assert enriched.parameters["flow_shares"] == [0.9, 0.1]


# ---------------------------------------------------------------------------
# 8. strategy narrative & purity audit
# ---------------------------------------------------------------------------
class ScriptedLLM:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)

    def __call__(self, _prompt: str) -> str:
        return self._replies.pop(0) if self._replies else "garbage"


def _ja(op: str | None, parents: list[str], role: str | None = None,
        chain: str | None = None, **params: object) -> str:
    d: dict[str, object] = {"operation": op}
    if op is not None:
        d.update({"parent_ids": parents, "target_role": role,
                  "target_chain": chain})
        if params:
            d["parameters"] = params
    return json.dumps(d)


def _run_full_trajectory(spec: ScenarioSpec):
    script = [
        _ja("Transfer", ["node_0"], "Intermediate", "Chain_A"),
        _ja("Split", ["node_1"], "Intermediate", "Chain_A", num_children=2),
        _ja("Merge", ["node_2", "node_3"], "Aggregator", "Chain_A"),
        _ja("Bridge", ["node_4"], "Cross_Chain", "Chain_B"),
        _ja("Transfer", ["node_5"], "Target", "Chain_B"),
        _ja(None, []),
    ]
    env = BehavioralEnvironment()
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    return PlannerAgent(env, retriever, ScriptedLLM(script)).plan(spec)


def test_strategy_narrative_generated_and_persisted() -> None:
    spec = ScenarioSpec(
        name="flow-demo",
        scenario="launder proceeds",
        tactic_goal="layer and hop chains",
        scale_tier=ScaleTier.WHALE,
        estimated_value_usd=12_000_000.0,
    )
    traj = _run_full_trajectory(spec)

    narrative = traj.strategy_narrative
    assert narrative, "narrative must not be empty"
    assert "Whale-scale" in narrative
    assert "fan-out splits" in narrative
    assert "Chain_A -> Chain_B" in narrative
    assert "target sink" in narrative
    # persisted into exported graph metadata for Stage-2 consumers
    assert traj.graph["meta"]["strategy_narrative"] == narrative
    assert traj.graph["meta"]["scale_tier"] == "Whale"
    assert traj.graph["meta"]["estimated_value_usd"] == 12_000_000.0


def test_purity_audit_passes_on_clean_export_and_catches_violations() -> None:
    spec = ScenarioSpec(name="purity", scenario="s", tactic_goal="g")
    traj = _run_full_trajectory(spec)

    assert audit_export_purity(traj.graph) == []

    polluted = json.loads(json.dumps(traj.graph))
    polluted["meta"]["injected"] = "0x1234567890abcdef1234567890abcdef"
    assert audit_export_purity(polluted) != []

    polluted2 = json.loads(json.dumps(traj.graph))
    polluted2["meta"]["ts"] = 1726502400000
    assert audit_export_purity(polluted2) != []


def test_full_trajectory_still_succeeds_with_flow_enhancement() -> None:
    spec = ScenarioSpec(name="flow", scenario="s", tactic_goal="g")
    traj = _run_full_trajectory(spec)
    assert traj.success is True
    assert traj.failed is False
    assert traj.terminated_by == "agent_terminate"
    # every edge exported with a normalised share
    for edge in traj.graph["edges"]:
        assert 0.0 < edge["flow_share"] <= 1.0
    split_shares = [
        e["flow_share"] for e in traj.graph["edges"] if e["operation"] == "Split"
    ]
    assert abs(sum(split_shares) - 1.0) <= FLOW_TOLERANCE
