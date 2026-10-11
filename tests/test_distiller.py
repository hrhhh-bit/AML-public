"""Offline tests for the distillation pipeline & four empirical checks.

No network access: the LLM is a scripted stub.  Covers chunking, reflection
repair, the four checks, and safe ingest.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from aml_rag import (
    MotifDistiller,
    TextChunker,
    TopologicalMotif,
    build_default_knowledge_base,
    cross_source_consistency,
    saturation_analysis,
    topology_validity,
    zero_noise_audit,
)
from aml_rag.schema import AbstractEdge, OperationType


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _motif_dict(motif_id: str = "M1", pattern: str = "Peeling_Chain",
                tiers: list[str] | None = None) -> dict:
    d: dict = {
        "motif_id": motif_id,
        "pattern_type": pattern,
        "description": "linear peeling transfers",
        "preconditions": {"min_level": 0},
        "nodes": [
            {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "I", "role": "Intermediate", "chain": "Chain_A", "level": 1},
            {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 2},
        ],
        "edges": [
            {"source": "S", "target": "I", "operation": "Transfer"},
            {"source": "I", "target": "T", "operation": "Transfer"},
        ],
        "post_state_effect": {},
    }
    if tiers is not None:
        d["applicable_scale_tiers"] = tiers
    return d


def _split_motif_dict(motif_id: str = "SP1") -> dict:
    return {
        "motif_id": motif_id,
        "pattern_type": "Multi_Layering_Split",
        "description": "one-to-two fan out",
        "preconditions": {"min_level": 1},
        "nodes": [
            {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_A", "level": 1},
            {"temp_id": "I2", "role": "Intermediate", "chain": "Chain_A", "level": 1},
        ],
        "edges": [
            {"source": "S", "target": "I1", "operation": "Split", "flow_share": 0.5},
            {"source": "S", "target": "I2", "operation": "Split", "flow_share": 0.5},
        ],
        "post_state_effect": {},
    }


class ScriptedLLM:
    def __init__(self, replies: list[str], default: str = "garbage") -> None:
        self._replies = list(replies)
        self._default = default
        self.calls = 0

    def __call__(self, _prompt: str) -> str:
        self.calls += 1
        return self._replies.pop(0) if self._replies else self._default


def _distiller(llm, **kwargs) -> MotifDistiller:
    # huge max_chars => the whole input is a single chunk for determinism
    return MotifDistiller(llm, chunker=TextChunker(max_chars=10_000_000), **kwargs)


# ---------------------------------------------------------------------------
# chunker
# ---------------------------------------------------------------------------
def test_chunker_splits_on_headings() -> None:
    text = "intro paragraph\n\n## A\nbody a\n\n## B\nbody b\n"
    chunks = TextChunker(max_chars=10_000).chunk(text)
    assert len(chunks) == 3  # intro + A + B


def test_chunker_slides_long_sections() -> None:
    long_para = "word " * 400  # ~2000 chars
    chunks = TextChunker(max_chars=600, overlap_chars=0).chunk(
        "## Section\n" + long_para
    )
    assert len(chunks) > 1
    assert all(len(c) <= 700 for c in chunks)


# ---------------------------------------------------------------------------
# distillation + reflection repair
# ---------------------------------------------------------------------------
def test_distill_single_chunk_success() -> None:
    llm = ScriptedLLM([json.dumps([_motif_dict()])])
    result = _distiller(llm).distill("## Peel Chain\nsome text")
    assert len(result.motifs) == 1
    assert result.motifs[0].is_dag()
    assert result.failures == []


def test_distill_fenced_reply_with_prose() -> None:
    reply = "Sure, here it is:\n```json\n" + json.dumps([_motif_dict()]) + "\n```"
    llm = ScriptedLLM([reply])
    result = _distiller(llm).distill("text")
    assert len(result.motifs) == 1


def test_distill_reflection_repair_recovers() -> None:
    llm = ScriptedLLM(["not json at all", json.dumps([_motif_dict()])])
    result = _distiller(llm).distill("text")
    assert len(result.motifs) == 1
    assert llm.calls == 2
    assert result.failures == []


def test_distill_topology_error_triggers_repair() -> None:
    bad = _motif_dict()
    bad["edges"] = [{"source": "S", "target": "S", "operation": "Transfer"}]
    llm = ScriptedLLM([json.dumps([bad]), json.dumps([_motif_dict()])])
    result = _distiller(llm).distill("text")
    assert len(result.motifs) == 1
    assert llm.calls == 2


def test_distill_repair_exhaustion_records_failure() -> None:
    llm = ScriptedLLM(["garbage"] * 3)  # 1 initial + 2 retries
    result = _distiller(llm).distill("text")
    assert result.motifs == []
    assert len(result.failures) == 1
    assert result.failures[0].attempts == 3


def test_scale_tier_association_field() -> None:
    motif = TopologicalMotif(**_motif_dict(tiers=["Whale"]))
    assert motif.applicable_scale_tiers == ("Whale",)
    with pytest.raises(ValidationError):
        TopologicalMotif(**_motif_dict(tiers=["Huge"]))


# ---------------------------------------------------------------------------
# check 1: topology validity
# ---------------------------------------------------------------------------
def test_topology_validity_rates() -> None:
    good = TopologicalMotif(**_motif_dict("V1"))
    report = topology_validity([good])
    assert report.valid_rate == 1.0

    corrupted = TopologicalMotif(**_motif_dict("V2"))
    corrupted.edges.append(
        AbstractEdge(source="S", target="S", operation=OperationType.TRANSFER)
    )
    report = topology_validity([good, corrupted])
    assert report.valid_rate == 0.5
    assert "V2" in report.invalid_motifs


# ---------------------------------------------------------------------------
# check 2: cross-source consistency
# ---------------------------------------------------------------------------
def test_cross_source_consistency_converges_on_same_topology() -> None:
    a = TopologicalMotif(**_motif_dict("A"))
    b = TopologicalMotif(**_motif_dict("B"))
    report = cross_source_consistency({"src1": [a], "src2": [b]})
    assert report.overall_consistency == 1.0

    split = TopologicalMotif(**_split_motif_dict())
    report = cross_source_consistency({"src1": [a], "src2": [split]})
    assert report.overall_consistency < 1.0


def _bridge_motif_dict(motif_id: str = "BR") -> dict:
    return {
        "motif_id": motif_id,
        "pattern_type": "Chain_Hopping",
        "description": "bridge hop to another chain",
        "preconditions": {"min_level": 2},
        "nodes": [
            {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "CC", "role": "Cross_Chain", "chain": "Chain_B", "level": 1},
            {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 2},
        ],
        "edges": [
            {"source": "S", "target": "CC", "operation": "Bridge"},
            {"source": "CC", "target": "T", "operation": "Transfer"},
        ],
        "post_state_effect": {},
    }


def _merge_motif_dict(motif_id: str = "MG") -> dict:
    return {
        "motif_id": motif_id,
        "pattern_type": "Integration_Merge",
        "description": "many-to-one consolidation into recovery address",
        "preconditions": {"min_level": 2},
        "nodes": [
            {"temp_id": "S1", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "S2", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "AGG", "role": "Aggregator", "chain": "Chain_A", "level": 1},
            {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 2},
        ],
        "edges": [
            {"source": "S1", "target": "AGG", "operation": "Merge"},
            {"source": "S2", "target": "AGG", "operation": "Merge"},
            {"source": "AGG", "target": "T", "operation": "Transfer"},
        ],
        "post_state_effect": {},
    }


def test_cross_source_dual_track_global_operator_alignment() -> None:
    """Nomad-like case: pattern labels drift but operators converge."""
    certik = [
        TopologicalMotif(**_bridge_motif_dict("C1")),   # Chain_Hopping
        TopologicalMotif(**_split_motif_dict("C2")),    # Multi_Layering_Split
    ]
    # Zerion diluted into different labels but same core operators
    zerion = [
        TopologicalMotif(**_merge_motif_dict("Z1")),    # Integration_Merge
        TopologicalMotif(**_bridge_motif_dict("Z2")),   # Chain_Hopping
    ]
    report = cross_source_consistency({"CertiK": certik, "Zerion": zerion})

    # pattern-strict is penalised by label drift
    assert report.pattern_strict_jaccard < report.global_topology_jaccard
    # global operator sets overlap: CertiK {Bridge,Transfer,Split}, Zerion {Merge,Bridge,Transfer}
    assert report.global_topology_jaccard > 0.0
    assert report.overall_consistency == report.global_topology_jaccard
    assert "Bridge" in report.global_operator_sets["CertiK"]
    assert "Merge" in report.global_operator_sets["Zerion"]
    # node-role diagnostic dimension is populated
    assert "Source" in report.global_role_sets["CertiK"]
    assert "Aggregator" in report.global_role_sets["Zerion"]


def test_cross_source_global_jaccard_reaches_convergence() -> None:
    """Rich operator overlap (Bridge/Swap/Split/Transfer) -> Jaccard >= 0.5."""
    swap_motif = TopologicalMotif(**_motif_dict("SW", pattern="Token_Obfuscation"))
    certik = [
        TopologicalMotif(**_bridge_motif_dict("C1")),
        TopologicalMotif(**_split_motif_dict("C2")),
    ]
    zerion = [
        TopologicalMotif(**_bridge_motif_dict("Z1")),
        TopologicalMotif(**_split_motif_dict("Z2")),
        swap_motif,
    ]
    report = cross_source_consistency({"CertiK": certik, "Zerion": zerion})
    assert report.global_topology_jaccard >= 0.5


# ---------------------------------------------------------------------------
# check 3: zero-noise audit
# ---------------------------------------------------------------------------
def test_zero_noise_audit_clean_and_polluted() -> None:
    clean = [TopologicalMotif(**_motif_dict("C"))]
    assert zero_noise_audit(clean).residue_count == 0

    polluted = _motif_dict("P")
    polluted["description"] = (
        "sent 0x1234567890abcdef1234567890abcdef via USDT for 1000 USD at gas 20"
    )
    audit = zero_noise_audit([TopologicalMotif(**polluted)])
    assert audit.residue_count > 0
    assert "P" in audit.violations


# ---------------------------------------------------------------------------
# check 4: saturation analysis
# ---------------------------------------------------------------------------
def test_saturation_analysis_marginal_decay() -> None:
    m1 = TopologicalMotif(**_motif_dict("M1"))
    m2_dup = TopologicalMotif(**_motif_dict("M2"))  # isomorphic to M1
    m3_new = TopologicalMotif(**_split_motif_dict("M3"))  # distinct topology
    points = saturation_analysis([[m1], [m2_dup], [m3_new]])
    assert [p.marginal_new for p in points] == [1, 0, 1]
    assert [p.cumulative_unique for p in points] == [1, 1, 2]


# ---------------------------------------------------------------------------
# safe ingest
# ---------------------------------------------------------------------------
def test_merge_motifs_deduplicates_ids_and_isomorphs() -> None:
    kb = build_default_knowledge_base()
    base = len(kb)

    new = TopologicalMotif(**_motif_dict("Distilled_1"))
    report = kb.merge_motifs([new])
    assert report.added == ["Distilled_1"]
    assert len(kb) == base + 1

    # duplicate id -> skipped
    assert kb.merge_motifs([new]).duplicate_ids == ["Distilled_1"]

    # isomorphic (different id, same flow-aware signature) -> skipped
    dup = TopologicalMotif(**_motif_dict("Distilled_2"))
    report = kb.merge_motifs([dup])
    assert report.isomorphic_skips == ["Distilled_2"]
    assert len(kb) == base + 1
