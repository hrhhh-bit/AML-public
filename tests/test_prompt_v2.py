"""Offline Mock tests for Prompt v2 (two-phase entity-grounded contract).

No network access: every test uses static JSON payloads or scripted stubs.
Covers the Prompt v2 assembly, attention-anchor injection, two-phase
parsing/flattening, grounded-chains boundary validation, and the
PromptV2Distiller reflection-repair loop.
"""

from __future__ import annotations

import json

from aml_rag import (
    CAMPAIGN_DIRECTIVE,
    MAX_EDGE_COUNT,
    MIN_EDGE_COUNT,
    SINGLE_PASS_MAX_CHARS,
    PromptV2Distiller,
    TextChunker,
    TopologicalMotif,
    annotate_stage_boundaries,
    build_v2_prompt,
    build_v2_schema_json,
    format_attention_anchor,
    parse_v2_response,
    scrub_micro_noise,
    scrub_motif_metadata,
    validate_grounded_chains,
    zero_noise_audit,
)


def _motif_dict(motif_id: str = "M1", chain: str = "Chain_A",
                pattern: str = "Peeling_Chain", edge_count: int = 3) -> dict:
    """A minimal campaign-level motif (default: 3 Transfer hops)."""
    nodes = [
        {"temp_id": "S", "role": "Source", "chain": chain, "level": 0},
        {"temp_id": "I1", "role": "Intermediate", "chain": chain, "level": 1},
        {"temp_id": "I2", "role": "Intermediate", "chain": chain, "level": 2},
        {"temp_id": "T", "role": "Target", "chain": chain, "level": 3},
    ]
    edges = [
        {"source": "S", "target": "I1", "operation": "Transfer"},
        {"source": "I1", "target": "I2", "operation": "Transfer"},
        {"source": "I2", "target": "T", "operation": "Transfer"},
    ]
    if edge_count < 3:
        # trim to a trivial 1-edge or 2-edge micro-fragment for the drop tests
        nodes = nodes[: edge_count + 1]
        edges = [
            {"source": nodes[i]["temp_id"], "target": nodes[i + 1]["temp_id"],
             "operation": "Transfer"}
            for i in range(edge_count)
        ]
    return {
        "motif_id": motif_id,
        "pattern_type": pattern,
        "description": "abstract multi-hop campaign motif",
        "preconditions": {"min_level": 0},
        "nodes": nodes,
        "edges": edges,
        "post_state_effect": {},
    }


def _wrap(grounded: list[str], phase_a: list[dict],
          phase_b: list[dict]) -> str:
    return json.dumps(
        {
            "grounded_chains": grounded,
            "phase_a_inflow_motifs": phase_a,
            "phase_b_outflow_motifs": phase_b,
        }
    )


class ScriptedLLM:
    def __init__(self, replies: list[str], default: str = "garbage") -> None:
        self._replies = list(replies)
        self._default = default
        self.calls = 0

    def __call__(self, _prompt: str) -> str:
        self.calls += 1
        return self._replies.pop(0) if self._replies else self._default


# ---------------------------------------------------------------------------
# 1. Prompt v2 assembly
# ---------------------------------------------------------------------------
def test_build_v2_prompt_contains_contract_parts() -> None:
    prompt = build_v2_prompt("some report segment")
    assert "grounded_chains" in prompt
    assert "phase_a_inflow_motifs" in prompt
    assert "phase_b_outflow_motifs" in prompt
    assert "REJECTED: Hallucinated Intermediate Relay Chain/Node" in prompt
    assert "REJECTED: Micro-fragment / Trivial Transfer" in prompt
    assert "MACRO CAMPAIGN TOPOLOGY MANDATE" in prompt
    assert "MINIMUM EDGE COUNT" in prompt
    assert "CAUSAL FIDELITY" in prompt
    assert "PARALLEL FLOW UNIFICATION" not in prompt
    assert "CONSOLIDATION UNIFICATION" not in prompt
    assert "DENSITY EXPECTATION" not in prompt
    assert "single_chain_peeling_split" in prompt
    assert "cross_chain_swap_bridge" in prompt
    assert "otc_cash_out_fanout" in prompt
    assert "### TARGET JSON SCHEMA ###" in prompt
    assert "### REPORT SEGMENT ###" in prompt
    assert "some report segment" in prompt


def test_build_v2_schema_json_requires_three_keys() -> None:
    schema = json.loads(build_v2_schema_json())
    assert schema["type"] == "object"
    assert set(schema["required"]) == {
        "grounded_chains",
        "phase_a_inflow_motifs",
        "phase_b_outflow_motifs",
    }
    assert "items" in schema["properties"]["phase_a_inflow_motifs"]


def test_build_v2_prompt_injects_attention_anchor() -> None:
    anchor = format_attention_anchor(
        {"evidence_chain": "0x1... -> 0x2...", "hops_detected": 3,
         "markers": ["fund flow"]}
    )
    assert anchor is not None and "ATTENTION ANCHOR" in anchor
    # v2.2 剥离微观跳数链路：不再注入逐跳 evidence_chain 地址链
    assert "evidence_chain" not in anchor
    assert "hops_detected: 3" in anchor
    assert "flow_markers: fund flow" in anchor
    prompt = build_v2_prompt("text", attention_anchor=anchor)
    assert "ATTENTION ANCHOR" in prompt
    assert "evidence_chain" not in prompt
    # no anchor -> no telemetry block
    assert "ATTENTION ANCHOR" not in build_v2_prompt("text")


def test_build_v2_prompt_retry_includes_previous_mistake() -> None:
    assert "PREVIOUS MISTAKE" not in build_v2_prompt("text")
    assert "PREVIOUS MISTAKE" in build_v2_prompt("text", retry_error="bad")


def test_format_attention_anchor_empty_entry_is_none() -> None:
    assert format_attention_anchor(None) is None
    assert format_attention_anchor({}) is None
    assert format_attention_anchor({"hops_detected": 0}) is not None


# ---------------------------------------------------------------------------
# 2. Two-phase parsing & grounded-chains boundary
# ---------------------------------------------------------------------------
def test_parse_v2_response_flattens_both_phases_with_markers() -> None:
    raw = _wrap(
        ["Chain_A"],
        [_motif_dict("inflow_A", pattern="Integration_Merge")],
        [_motif_dict("outflow_B", pattern="Multi_Layering_Split")],
    )
    parsed = parse_v2_response(raw)
    assert parsed.error is None
    assert [(pm.phase, pm.motif.motif_id) for pm in parsed.phase_motifs] == [
        ("phase_a_inflow", "inflow_A"),
        ("phase_b_outflow", "outflow_B"),
    ]
    assert all(isinstance(pm.motif, TopologicalMotif) for pm in parsed.phase_motifs)


def test_parse_v2_response_requires_grounded_chains() -> None:
    raw = json.dumps(
        {"phase_a_inflow_motifs": [], "phase_b_outflow_motifs": []}
    )
    parsed = parse_v2_response(raw)
    assert parsed.error is not None and "grounded_chains" in parsed.error


def test_parse_v2_response_rejects_ungrounded_chain() -> None:
    raw = _wrap(
        ["Chain_A", "Chain_B"],
        [_motif_dict("ghost", chain="Chain_C")],
        [],
    )
    parsed = parse_v2_response(raw)
    assert parsed.error is not None
    assert "grounded_chains boundary" in parsed.error
    assert "Chain_C" in parsed.error


def test_parse_v2_response_tolerates_fences_and_prose() -> None:
    reply = "Sure:\n```json\n" + _wrap(["Chain_A"], [_motif_dict()], []) + "\n```"
    parsed = parse_v2_response(reply)
    assert parsed.error is None
    assert len(parsed.phase_motifs) == 1


def test_parse_v2_response_drops_micro_fragments() -> None:
    # one campaign motif (3 edges) + one trivial 1-edge fragment
    raw = _wrap(
        ["Chain_A"],
        [_motif_dict("campaign")],
        [_motif_dict("micro", edge_count=1)],
    )
    parsed = parse_v2_response(raw)
    assert parsed.error is None
    assert [pm.motif.motif_id for pm in parsed.phase_motifs] == ["campaign"]
    assert [pm.motif.motif_id for pm in parsed.dropped_micro_fragments] == ["micro"]
    assert parsed.dropped_micro_fragments[0].phase == "phase_b_outflow"


def test_min_edge_count_constant_is_three() -> None:
    assert MIN_EDGE_COUNT == 3


def test_parse_v2_response_rejects_disconnected_motif() -> None:
    payload = _motif_dict("two_islands")
    payload["nodes"] = [
        {"temp_id": "A", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "B", "role": "Target", "chain": "Chain_A", "level": 1},
        {"temp_id": "C", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "D", "role": "Target", "chain": "Chain_A", "level": 1},
    ]
    payload["edges"] = [
        {"source": "A", "target": "B", "operation": "Transfer", "flow_share": 1.0},
        {"source": "C", "target": "D", "operation": "Transfer", "flow_share": 1.0},
    ]
    parsed = parse_v2_response(_wrap(["Chain_A"], [payload], []))
    assert parsed.error is not None and "weakly connected" in parsed.error


def test_parse_v2_response_quarantines_oversize_motif() -> None:
    count = 34  # 33 edges > MAX_EDGE_COUNT
    nodes = [
        {"temp_id": f"N{i}", "role": "Intermediate", "chain": "Chain_A", "level": i}
        for i in range(count)
    ]
    nodes[0]["role"] = "Source"
    nodes[-1]["role"] = "Target"
    edges = [
        {
            "source": f"N{i}",
            "target": f"N{i + 1}",
            "operation": "Transfer",
            "flow_share": 1.0,
        }
        for i in range(count - 1)
    ]
    payload = _motif_dict("long_chain")
    payload["nodes"] = nodes
    payload["edges"] = edges
    parsed = parse_v2_response(_wrap(["Chain_A"], [payload], []))
    assert parsed.error is None
    assert parsed.phase_motifs == []
    assert [pm.motif.motif_id for pm in parsed.quarantined_oversize] == ["long_chain"]


# ---------------------------------------------------------------------------
# 2b. Token scrubber (post-processing micro-noise self-healing)
# ---------------------------------------------------------------------------
def test_scrub_micro_noise_maps_stable_and_native_symbols() -> None:
    assert scrub_micro_noise(
        "Swaps ETH via DEX and transfers USDT to mixer"
    ) == "Swaps native_asset via DEX and transfers stablecoin_asset to mixer"
    assert scrub_micro_noise("BTC and WBTC") == "native_asset and native_asset"
    assert scrub_micro_noise("USDC/DAI") == "stablecoin_asset/stablecoin_asset"
    # non-token text is untouched
    assert scrub_micro_noise("bridged to another chain") == "bridged to another chain"
    # empty / missing text is safe
    assert scrub_micro_noise("") == ""


def test_token_scrubber_neutralises_symbols_and_passes_zero_noise() -> None:
    payload = _motif_dict("dex_swap_then_bridge_exit")
    payload["description"] = "Swaps ETH via DEX and transfers USDT to mixer"
    payload["tags"] = ["ETH", "bridge", "USDC"]
    raw = _wrap(["Chain_A"], [payload], [])

    parsed = parse_v2_response(raw)
    assert parsed.error is None
    motif = parsed.phase_motifs[0].motif
    # symbols neutralised in description
    assert "ETH" not in motif.description
    assert "USDT" not in motif.description
    assert "native_asset" in motif.description
    assert "stablecoin_asset" in motif.description
    # symbols neutralised in tags
    assert "native_asset" in motif.tags
    assert "stablecoin_asset" in motif.tags
    assert "ETH" not in motif.tags and "USDC" not in motif.tags

    audit = zero_noise_audit([motif])
    assert audit.residue_count == 0
    assert audit.violations == {}


def test_scrub_micro_noise_maps_chain_names() -> None:
    assert scrub_micro_noise("bridged to Tron") == "bridged to chain"
    assert scrub_micro_noise("Ethereum to Solana") == "chain to chain"
    # the generic word 'chain' is untouched
    assert scrub_micro_noise("bridged to another chain") == "bridged to another chain"


def test_scrub_motif_metadata_neutralises_chain_names_in_id() -> None:
    motif = TopologicalMotif(**_motif_dict("cross_chain_swap_bridge_to_tron_otc"))
    scrubbed = scrub_motif_metadata(motif)
    assert "tron" not in scrubbed.motif_id.lower()
    assert "chain" in scrubbed.motif_id


def test_scrub_preserves_cross_chain_bridge_edges() -> None:
    payload = _motif_dict("cross_chain_swap_bridge_to_tron_otc")
    payload["nodes"] = [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 1},
    ]
    payload["edges"] = [
        {"source": "S", "target": "T", "operation": "Bridge", "flow_share": 1.0},
    ]
    motif = TopologicalMotif(**payload)
    scrubbed = scrub_motif_metadata(motif)
    # metadata chain name neutralised...
    assert "tron" not in scrubbed.motif_id.lower()
    # ...but graph structure / cross-chain BRIDGE operator stay intact
    assert scrubbed.edges[0].operation.value == "Bridge"
    assert scrubbed.nodes[0].chain == "Chain_A"
    assert scrubbed.nodes[1].chain == "Chain_B"


def _bottleneck_motif_dict() -> dict:
    """Two sources merge into AGG, which then splits to two targets."""
    return {
        "motif_id": "sandglass_campaign",
        "pattern_type": "Integration_Merge",
        "description": "Two inflows merge into an aggregator which splits to two sinks",
        "preconditions": {"min_level": 0},
        "nodes": [
            {"temp_id": "S1", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "S2", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "AGG", "role": "Aggregator", "chain": "Chain_A", "level": 1},
            {"temp_id": "T1", "role": "Target", "chain": "Chain_A", "level": 2},
            {"temp_id": "T2", "role": "Target", "chain": "Chain_A", "level": 2},
        ],
        "edges": [
            {"source": "S1", "target": "AGG", "operation": "Merge", "flow_share": 1.0},
            {"source": "S2", "target": "AGG", "operation": "Merge", "flow_share": 1.0},
            {"source": "AGG", "target": "T1", "operation": "Split", "flow_share": 0.5},
            {"source": "AGG", "target": "T2", "operation": "Split", "flow_share": 0.5},
        ],
        "post_state_effect": {},
    }


def test_stage_boundary_nodes_detect_sandglass_bottleneck() -> None:
    motif = TopologicalMotif(**_bottleneck_motif_dict())
    assert motif.stage_boundary_nodes() == ["AGG"]


def test_annotate_stage_boundaries_adds_tag() -> None:
    motif = TopologicalMotif(**_bottleneck_motif_dict())
    annotated = annotate_stage_boundaries(motif)
    assert "stage_boundary:AGG" in annotated.tags


def test_annotate_stage_boundaries_noop_without_bottleneck() -> None:
    motif = TopologicalMotif(**_motif_dict())  # linear chain, no bottleneck
    assert annotate_stage_boundaries(motif).tags == ()


def test_parse_v2_response_annotates_stage_boundaries() -> None:
    raw = _wrap(["Chain_A"], [_bottleneck_motif_dict()], [])
    parsed = parse_v2_response(raw)
    assert parsed.error is None
    motif = parsed.phase_motifs[0].motif
    assert "stage_boundary:AGG" in motif.tags


def test_zero_noise_audit_flags_chain_name() -> None:
    payload = _motif_dict()
    payload["description"] = "bridged to Tron"
    motif = TopologicalMotif(**payload)
    audit = zero_noise_audit([motif])
    assert "chain_name" in audit.violations.get(motif.motif_id, [])


def test_build_v2_prompt_injects_survey_note() -> None:
    prompt = build_v2_prompt("chunk", survey_note="SURVEY MODE: test directive")
    assert "SURVEY MODE" in prompt
    assert "test directive" in prompt


def test_validate_grounded_chains_reports_offenders() -> None:
    motif = TopologicalMotif(**_motif_dict(chain="Chain_C"))
    issues = validate_grounded_chains(["Chain_A", "Chain_B"], [motif])
    assert any("Chain_C" in issue for issue in issues)
    # a motif on a grounded chain is clean
    ok = TopologicalMotif(**_motif_dict(chain="Chain_A"))
    assert validate_grounded_chains(["Chain_A"], [ok]) == []


# ---------------------------------------------------------------------------
# 3. PromptV2Distiller end-to-end + reflection repair
# ---------------------------------------------------------------------------
def _distiller(llm) -> PromptV2Distiller:
    return PromptV2Distiller(llm, chunker=TextChunker(max_chars=10_000_000))


def test_prompt_v2_distiller_end_to_end() -> None:
    llm = ScriptedLLM([_wrap(["Chain_A"], [_motif_dict()], [])])
    result = _distiller(llm).distill("## Peel\nsome text")
    assert len(result.motifs) == 1
    assert result.failures == []
    assert result.chunks == 1


def test_prompt_v2_distiller_reflection_repair() -> None:
    llm = ScriptedLLM(
        ["not json at all", _wrap(["Chain_A"], [_motif_dict()], [])]
    )
    result = _distiller(llm).distill("text")
    assert len(result.motifs) == 1
    assert llm.calls == 2
    assert result.failures == []


def test_prompt_v2_distiller_boundary_violation_repair() -> None:
    bad = _wrap(["Chain_A", "Chain_B"], [_motif_dict("ghost", chain="Chain_C")], [])
    good = _wrap(["Chain_A"], [_motif_dict()], [])
    llm = ScriptedLLM([bad, good])
    result = _distiller(llm).distill("text")
    assert len(result.motifs) == 1
    assert llm.calls == 2
    assert result.failures == []


def test_prompt_v2_distiller_repair_exhaustion_records_failure() -> None:
    llm = ScriptedLLM(["garbage"] * 3)
    result = _distiller(llm).distill("text")
    assert result.motifs == []
    assert len(result.failures) == 1
    assert result.failures[0].attempts == 3


def test_prompt_v2_distiller_drops_micro_fragments() -> None:
    # model returns one campaign motif + one trivial 1-edge fragment
    raw = _wrap(
        ["Chain_A"],
        [_motif_dict("campaign")],
        [_motif_dict("micro", edge_count=1)],
    )
    result = _distiller(ScriptedLLM([raw])).distill("text")
    assert [m.motif_id for m in result.motifs] == ["campaign"]
    assert [pm.motif.motif_id for pm in result.dropped_micro_fragments] == ["micro"]
    assert result.failures == []


def test_prompt_v2_distiller_survey_mode_focuses_and_injects_directive() -> None:
    survey = (
        "We analyzed the token ecosystem across thousands of tokens.\n\n"
        "Table 1: aggregate statistics\n\n"
        "Below, we will examine a specific rug pull case in detail.\n\n"
        "The token was deployed and used to fabricate volume.\n\n"
        "These Twitter and Telegram groups are used to acquire victims.\n\n"
        "Conclusion about the ecosystem."
    )
    captured: list[str] = []

    def llm(prompt: str) -> str:
        captured.append(prompt)
        return _wrap(["Chain_A"], [_motif_dict()], [])

    result = _distiller(llm).distill(survey)
    assert len(result.motifs) == 1
    assert all("SURVEY MODE" in p for p in captured)
    assert all("Telegram groups" not in p for p in captured)


def test_prompt_v2_distiller_survey_single_pass_bypasses_chunker() -> None:
    case_body = "The token was deployed and used to fabricate volume. " * 12
    survey = (
        "We analyzed the token ecosystem across thousands of tokens.\n\n"
        "Table 1: aggregate statistics\n\n"
        "Below, we will examine a specific rug pull case in detail.\n\n"
        + case_body
        + "\n\nThese Twitter and Telegram groups are used to acquire victims."
    )
    captured: list[str] = []

    def llm(prompt: str) -> str:
        captured.append(prompt)
        return _wrap(["Chain_A"], [_motif_dict()], [])

    # small chunker would split the focused text into >1 chunk normally;
    # the survey single-pass bypass must win and emit exactly ONE chunk.
    distiller = PromptV2Distiller(llm, chunker=TextChunker(max_chars=200))
    result = distiller.distill(survey)
    assert result.chunks == 1
    assert len(captured) == 1
    assert len(result.motifs) == 1
    assert all("UNIFIED CAMPAIGN DAG" in p for p in captured)


def test_prompt_v2_distiller_incident_single_pass_and_campaign_directive() -> None:
    # incident-type report (NOT a survey): should still single-pass when short
    # enough, and receive the unified campaign DAG directive (not SURVEY MODE).
    incident = (
        "The attacker drained funds across multiple chains.\n\n"
        "Funds were consolidated and then fanned out to OTC platforms."
    )
    captured: list[str] = []

    def llm(prompt: str) -> str:
        captured.append(prompt)
        return _wrap(["Chain_A"], [_motif_dict()], [])

    distiller = PromptV2Distiller(llm, chunker=TextChunker(max_chars=200))
    result = distiller.distill(incident)
    assert result.chunks == 1
    assert len(result.motifs) == 1
    # unified campaign directive present, survey-specific note absent
    assert all("UNIFIED CAMPAIGN DAG" in p for p in captured)
    assert all("SURVEY MODE" not in p for p in captured)
