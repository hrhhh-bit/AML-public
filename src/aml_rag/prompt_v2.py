"""Prompt v2: entity-grounded, two-phase distillation contract.

Stage-3 Task 2 — the prompt is upgraded from a flat motif array to a
three-part wrapper that closes two gaps the flat contract left open:

1. **Entity grounding closure** — the output must declare ``grounded_chains``
   (the abstract chain labels actually evidenced in the report).  Any motif
   node using a chain outside that set is rejected as a hallucinated
   intermediate relay chain/node, so the distiller can no longer invent
   ghost hops.
2. **Two-phase explicit slots** — ``phase_a_inflow_motifs`` (fan-in /
   consolidation / first-hop / cross-chain entry) and
   ``phase_b_outflow_motifs`` (fan-out / dispersal / DEX swap / OTC
   cash-out) are kept apart, with the phase marker preserved for downstream
   analytics.

The module reuses the physical-ledger axiom guards already implemented in
:mod:`aml_rag.schema` (Kahn acyclicity, out-flow conservation, cross-chain
Bridge-only) and simply adds the grounded-chains boundary check on top.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .distiller import (
    DistillationFailure,
    TextChunker,
    detect_survey_report,
    focus_survey_case_narrative,
)
from .json_utils import load_json_robust, strip_code_fences
from .schema import TopologicalMotif

__all__ = [
    "DISTILLATION_PROMPT_V2",
    "ATTENTION_ANCHOR_HEADER",
    "SURVEY_DIRECTIVE",
    "CAMPAIGN_DIRECTIVE",
    "PHASE_A",
    "PHASE_B",
    "MIN_EDGE_COUNT",
    "MAX_EDGE_COUNT",
    "SINGLE_PASS_MAX_CHARS",
    "PhaseMotif",
    "ParsedV2Payload",
    "TwoPhaseDistillResult",
    "PromptV2Distiller",
    "build_v2_prompt",
    "build_v2_schema_json",
    "format_attention_anchor",
    "parse_v2_response",
    "scrub_micro_noise",
    "scrub_motif_metadata",
    "annotate_stage_boundaries",
    "validate_grounded_chains",
]

LLMCallable = Callable[[str], str]

#: JSON keys of the two-phase wrapper.
PHASE_A = "phase_a_inflow_motifs"
PHASE_B = "phase_b_outflow_motifs"

#: Phase markers carried through parsing (kept separate from the JSON keys).
PHASE_A_TAG = "phase_a_inflow"
PHASE_B_TAG = "phase_b_outflow"

#: Cardinality lower bound: a legal campaign-level motif MUST have >= 3 edges.
MIN_EDGE_COUNT = 3

#: Cardinality upper bound (soft): motifs beyond this are quarantined as
#: suspected node-explosion / ghost-relay inflation, never silently ingested.
#: A multi-chain incident (several origin chains + downstream mules + a
#: cross-chain branch) legitimately reaches 25-30 edges; true node explosion
#: is 40+.  32 keeps those apart.
MAX_EDGE_COUNT = 32

#: Single-pass bypass threshold: report text (post survey-focus) at or below
#: this many characters is fed to the LLM as ONE context (no TextChunker
#: splits).  Applies to BOTH macro surveys and incident write-ups: chunking a
#: short report manufactures cross-chunk echo / twin motifs.
SINGLE_PASS_MAX_CHARS = 40_000

ATTENTION_ANCHOR_HEADER = "=== VERIFIED FUND-FLOW TELEMETRY (ATTENTION ANCHOR) ==="
ATTENTION_ANCHOR_FOOTER = "=== END ATTENTION ANCHOR ==="

#: Unified campaign DAG contract — applies to EVERY report (survey or incident).
#: Drives the LLM to emit one causally-connected end-to-end campaign graph
#: rather than per-stage / per-address fragments, which the downstream
#: PromptContextCompressor's dominance pruning already prefers.
CAMPAIGN_DIRECTIVE = (
    "UNIFIED CAMPAIGN DAG: extract the fund-flow as ONE causally-connected "
    "end-to-end campaign DAG covering the full loop (inflow -> manipulation / "
    "transformation -> cash-out). Place it in the phase matching its dominant "
    "direction and leave the other phase EMPTY ([]). Only if the report "
    "genuinely describes MULTIPLE orthogonal campaigns, output at most 3 such "
    "DAGs — each must be a full causal closure, never a per-stage or "
    "per-address fragment.\n"
    "INTERMEDIATE FIDELITY: when funds pass through downstream mule / relay "
    "addresses before reaching OTC / cash-out points, KEEP those intermediate "
    "nodes explicitly in the DAG (e.g. Source -> mules -> OTC). NEVER collapse "
    "a mule layer into a direct Source -> OTC edge just to shrink the graph. "
    "Every node must carry a discrete tactical action (Swap / Bridge / Split / "
    "Transfer), never an empty hop.\n"
    "CONNECTEDNESS: every motif MUST be one weakly-connected component — no "
    "isolated islands or disconnected fragments pasted into a single motif.\n"
    "FLOW CONSERVATION AT EVERY DEPTH: for multi-layer splits, EVERY node's "
    "out-edge flow_share must sum to exactly 1.0 (tolerance 0.01) at each "
    "level independently. Do not omit, round or drift flow_share on deep "
    "splits; single out-edges always carry 1.0."
)

#: Survey-mode directive = survey-specific genre guard + the shared unified
#: campaign DAG contract.  Prevents macro industry surveys from being distilled
#: chunk-by-chunk into per-table/per-stage fragments.
SURVEY_DIRECTIVE = (
    "SURVEY MODE: this segment comes from a macro industry survey, not a "
    "single-incident trace. Aggregate statistics, table/figure distributions, "
    "channel analyses and methodology are background context — NEVER emit a "
    "motif per table, figure or statistic.\n"
    + CAMPAIGN_DIRECTIVE
)


# ---------------------------------------------------------------------------
# Token scrubber (post-processing micro-noise self-healing)
# ---------------------------------------------------------------------------
#: Stablecoin symbols -> dimensionless ``stablecoin_asset``.
_STABLECOIN_SYMBOLS: frozenset[str] = frozenset(
    {"USDT", "USDC", "DAI", "USDE", "TUSD", "FDUSD", "BUSD", "USDD", "FRAX"}
)

#: Native / L1 token symbols -> dimensionless ``native_asset``.
_NATIVE_SYMBOLS: frozenset[str] = frozenset(
    {
        "ETH", "WETH", "BTC", "WBTC", "BNB", "SOL", "XRP", "XMR", "TRX",
        "MATIC", "POL", "AVAX", "LTC", "BCH", "DOGE",
    }
)

#: Concrete L1/L2 chain names -> dimensionless ``chain``.  These leak into
#: ``motif_id``/``description``/``tags`` (e.g. ``..._to_tron_otc``) and must be
#: neutralised just like token symbols.
_CHAIN_NAME_SYMBOLS: frozenset[str] = frozenset(
    {
        "ETHEREUM", "TRON", "SOLANA", "ARBITRUM", "OPTIMISM",
        "POLYGON", "AVALANCHE", "FANTOM", "BSC",
    }
)

#: Superset of ``zero_noise_audit``'s token vocabulary, mapped to generic terms.
_TOKEN_SYMBOL_MAP: dict[str, str] = {
    **{sym: "stablecoin_asset" for sym in _STABLECOIN_SYMBOLS},
    **{sym: "native_asset" for sym in _NATIVE_SYMBOLS},
}

#: Word-boundary matcher (case-insensitive) — identical semantics to the
#: ``\b(...)\b`` rule used by ``zero_noise_audit``, so the scrubber removes
#: exactly the token literals the scanner would flag.
_TOKEN_SCRUB_RE = re.compile(
    r"\b(" + "|".join(sorted(_TOKEN_SYMBOL_MAP, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

#: Concrete chain names matcher.  Unlike token symbols, chain names frequently
#: appear snake_case-embedded inside ``motif_id`` (e.g. ``..._to_tron_otc``),
#: where ``\b`` boundaries fail because ``_`` is a word character.  Alphanumeric
#: lookarounds are used instead so both ``bridged to Tron`` and
#: ``..._to_tron_otc`` are neutralised.
_CHAIN_NAME_SCRUB_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    + "|".join(sorted(_CHAIN_NAME_SYMBOLS, key=len, reverse=True))
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _token_replacement(match: re.Match[str]) -> str:
    return _TOKEN_SYMBOL_MAP[match.group(1).upper()]


def scrub_micro_noise(text: str) -> str:
    """Neutralise concrete token symbols and chain names in ``text``.

    Pure function: rewrites token literals (e.g. ``ETH`` -> ``native_asset``,
    ``USDT`` -> ``stablecoin_asset``) and concrete chain names (e.g. ``Tron``,
    ``Ethereum`` -> ``chain``); never touches graph structure, node ids, edge
    operations or ``flow_share`` weights.
    """
    if not text:
        return text
    text = _TOKEN_SCRUB_RE.sub(_token_replacement, text)
    return _CHAIN_NAME_SCRUB_RE.sub("chain", text)


def scrub_motif_metadata(motif: TopologicalMotif) -> TopologicalMotif:
    """Return a copy of ``motif`` with token symbols scrubbed from metadata.

    Scrubs ``description``, ``tags`` and ``motif_id`` (the motif name) — the
    natural-language fields that feed ``zero_noise_audit`` — while leaving
    ``nodes`` / ``edges`` (graph structure) untouched.
    """
    scrubbed_id = scrub_micro_noise(motif.motif_id)
    if not scrubbed_id.strip("_"):
        scrubbed_id = "scrubbed_motif"
    return motif.model_copy(
        update={
            "motif_id": scrubbed_id,
            "description": scrub_micro_noise(motif.description),
            "tags": tuple(scrub_micro_noise(tag) for tag in motif.tags),
        }
    )


def annotate_stage_boundaries(motif: TopologicalMotif) -> TopologicalMotif:
    """Tag sandglass-bottleneck nodes as ``stage_boundary:<temp_id>``.

    Zero-schema-change annotation: a unified campaign DAG keeps its causal
    closure, but its natural Inflow/Outflow seam (nodes with in-degree >= 2
    AND out-degree >= 2, e.g. a fund-holding aggregator) is surfaced as a
    ``tags`` entry for downstream consumers and future cut-vertex splitting.
    """
    boundaries = motif.stage_boundary_nodes()
    if not boundaries:
        return motif
    tags = list(motif.tags)
    for nid in boundaries:
        tag = f"stage_boundary:{nid}"
        if tag not in tags:
            tags.append(tag)
    return motif.model_copy(update={"tags": tuple(tags)})

#: Schema for one topological motif (reused verbatim inside the v2 wrapper).
_MOTIF_SCHEMA: dict[str, Any] = TopologicalMotif.model_json_schema()


def build_v2_schema() -> dict[str, Any]:
    """Return the two-phase wrapper JSON schema (Pydantic-ready dict)."""
    return {
        "title": "TwoPhaseDistillationPayload",
        "type": "object",
        "required": [PHASE_A, PHASE_B, "grounded_chains"],
        "additionalProperties": False,
        "properties": {
            "grounded_chains": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
                "description": (
                    "Abstract chain labels actually grounded in the report "
                    "evidence (e.g. ['Chain_A', 'Chain_B']). Every `chain` "
                    "used by ANY node in EITHER phase MUST appear here; the "
                    "number of distinct chains used by the motifs must NEVER "
                    "exceed the number of chains declared here."
                ),
            },
            PHASE_A: {
                "type": "array",
                "items": _MOTIF_SCHEMA,
                "description": (
                    "Fan-in / consolidation / first-hop / cross-chain ENTRY "
                    "motifs (funds flowing INTO the laundering structure)."
                ),
            },
            PHASE_B: {
                "type": "array",
                "items": _MOTIF_SCHEMA,
                "description": (
                    "Fan-out / dispersal / DEX swap / OTC cash-out / EXIT "
                    "motifs (funds leaving the structure toward sinks)."
                ),
            },
        },
    }


def build_v2_schema_json() -> str:
    """Compact JSON serialisation of the v2 wrapper schema."""
    return json.dumps(build_v2_schema(), ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Prompt v2 system prompt (offline static definition)
# ---------------------------------------------------------------------------
DISTILLATION_PROMPT_V2: str = """\
You are a crypto AML topological knowledge distiller.

Your input is a segment of a security tracing report describing money
laundering behaviour. Convert it into abstract topological motifs ONLY,
organised into TWO phases and grounded to the chains actually evidenced.

## HARD CONSTRAINTS (axioms)
1. ZERO micro-numerical noise: NEVER output wallet addresses (0x... / bc1...
   / T...), exact amounts, gas fees, timestamps, tx hashes or token symbols.
2. PURE topological abstraction: abstract roles, chains, DAG levels and
   operations only. Chain labels MUST be abstract: Chain_A, Chain_B, ...
3. Node roles MUST be: Source, Intermediate, Asset_Conversion, Cross_Chain,
   Aggregator, Target.
4. Edge operations MUST be: Transfer, Swap, Bridge, Split, Merge.
5. Node `level` MUST strictly increase along every edge (DAG topological
   order, sources at level 0).
6. `pattern_type` MUST be one of: Peeling_Chain, Chain_Hopping,
   Multi_Layering_Split, Token_Obfuscation, Integration_Merge.
7. FLOW ARCHETYPE normalisation: `flow_share` is ALWAYS the local OUT-degree
   distribution ratio of its SOURCE node; for EVERY node the out-edge shares
   must sum to exactly 1.0 (tolerance 0.01). Single out-edges MUST carry
   1.0; Split out-edges must sum to 1.0. NEVER write a downstream merge
   target's IN-FLOW weight onto an upstream edge.
8. CROSS-CHAIN ledger law: any edge whose source and target live on
   DIFFERENT chains MUST use the Bridge operation. Transfer / Swap / Split /
   Merge can never cross chains.
9. ASSET_CONVERSION contract: an Asset_Conversion node must carry exactly one
   adjacent Swap edge (never Transfer on BOTH sides).
10. Every motif MUST carry meaningful `preconditions` (min_level,
    allowed_node_roles, required_chains, max_active_branches) and a
    `post_state_effect` (branch_increment, chain_transition, target_chain,
    next_recommended_roles).

## ENTITY GROUNDING INVARIANT (grounded_chains)
- Output a top-level `grounded_chains` list naming ONLY the abstract chain
  labels actually evidenced in the report.
- Every `chain` value used by ANY node in BOTH phases MUST appear in
  `grounded_chains`. The number of distinct chain labels used by the motifs
  must NEVER exceed the number of chains declared in `grounded_chains`.
- NEVER invent an intermediate relay chain or ghost node just to make the
  graph look bigger. A direct consolidation (funds merge straight into an
  aggregator) is correct; a fake "CC_A -> CC_B" relay is hallucination.

## TWO-PHASE CONTRACT
- `phase_a_inflow_motifs`: Fan-in / consolidation / first-hop / cross-chain
  ENTRY motifs (funds flowing INTO the laundering structure).
- `phase_b_outflow_motifs`: Fan-out / dispersal / DEX swap / OTC cash-out /
  EXIT motifs (funds leaving the structure toward sinks).
- Put every extracted motif in exactly one phase; leave an empty array []
  when a phase has no motifs.

## MACRO CAMPAIGN TOPOLOGY MANDATE
- MINIMUM EDGE COUNT: each motif MUST have at least 3 edges
  (len(edges) >= 3). Isolated 1-edge transfers or 2-edge simple hops are
  STRICTLY FORBIDDEN.
- CAUSAL FIDELITY: extract each actually-evidenced laundering stage as one
  motif that closes its causal loop (entry -> transformation -> exit).
  Never inflate hop counts, never insert ghost relay nodes or chains, and
  never split one logical flow into per-address fragments.
- CRITICAL: Do NOT mention concrete token symbols (e.g., USDT, ETH, BTC)
  even in descriptions or tags. Always use generic terms like
  'native_asset', 'stablecoin', or 'token'.

## BEHAVIOURAL NORMALISATION
IGNORE marketing prose, tooling ads, white-hat refund narratives and
post-mortem digressions. Extract ONLY the core fund-flow topology actually
described and normalise it to the standard operators:

- "assets moved across blockchains via a bridge"           -> Bridge edge
  (pattern_type: Chain_Hopping, phase_a inflow entry).
- "funds fanned out / many addresses drained it"           -> Split edges
  (pattern_type: Multi_Layering_Split, phase_b outflow).
- "funds consolidated into one recovery / aggregator addr" -> Merge edges
  (pattern_type: Integration_Merge, phase_a inflow).
- "several tokens swapped into one token via a DEX"        -> Swap edge
  (pattern_type: Token_Obfuscation, phase_b outflow).
- "linear chain of small rapid hops, peeling a fraction"   -> Transfer edges
  (pattern_type: Peeling_Chain, phase_b outflow).
- "sold via OTC / P2P desk, cashed out to fiat"            -> Transfer into
  the OTC acceptor address (pattern_type: Integration_Merge, phase_b).

## NEGATIVE EXAMPLE (rejected — hallucinated intermediate relay chain)
The report only evidences TWO chains (Chain_A -> Chain_B). The following
answer invents a ghost chain "Chain_C" and ghost relay nodes "CC_A"/"CC_B"
that the report never mentions:

[REJECTED: Hallucinated Intermediate Relay Chain/Node]
{
  "grounded_chains": ["Chain_A", "Chain_B"],
  "phase_a_inflow_motifs": [
    {
      "motif_id": "bad_ghost_relay",
      "pattern_type": "Chain_Hopping",
      "description": "bridge then bounce through an invented relay chain",
      "nodes": [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "CC_A", "role": "Cross_Chain", "chain": "Chain_C", "level": 1},
        {"temp_id": "CC_B", "role": "Cross_Chain", "chain": "Chain_C", "level": 2},
        {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 3}
      ],
      "edges": [
        {"source": "S", "target": "CC_A", "operation": "Bridge"},
        {"source": "CC_A", "target": "CC_B", "operation": "Bridge"},
        {"source": "CC_B", "target": "T", "operation": "Bridge"}
      ]
    }
  ],
  "phase_b_outflow_motifs": []
}
WHY REJECTED: "Chain_C" is used by the motif but is absent from
`grounded_chains`. Direct consolidation into the evidenced chains is fine;
inventing relay chains is not.

## NEGATIVE EXAMPLE (rejected — micro-fragment / trivial transfer)
The report describes a single deposit of stolen funds into one exchange. The
following answer emits that one hop as a standalone motif:

[REJECTED: Micro-fragment / Trivial Transfer]
{
  "grounded_chains": ["Chain_A"],
  "phase_a_inflow_motifs": [],
  "phase_b_outflow_motifs": [
    {
      "motif_id": "bad_single_transfer",
      "pattern_type": "Peeling_Chain",
      "description": "one isolated transfer hop into an exchange",
      "nodes": [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 1}
      ],
      "edges": [{"source": "S", "target": "T", "operation": "Transfer"}]
    }
  ]
}
WHY REJECTED: only 1 edge (< 3). Fold this branch into the unified fan-out
DAG (or the consolidation DAG) instead of emitting it as a standalone motif.

## THREE GOLDEN FEW-SHOT EXAMPLES (from the calibrated 18-motif gold KB)

### Few-shot 1 — single-chain multi-layer peeling split (phase_b outflow)
{
  "grounded_chains": ["Chain_A"],
  "phase_a_inflow_motifs": [],
  "phase_b_outflow_motifs": [
    {
      "motif_id": "single_chain_peeling_split",
      "pattern_type": "Peeling_Chain",
      "description": "Peeled dispersal along a single chain with a dominant trunk and a minor peeled branch before final collection.",
      "preconditions": {"min_level": 0, "allowed_node_roles": ["Source", "Intermediate"], "max_active_branches": 2},
      "nodes": [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_A", "level": 1},
        {"temp_id": "M", "role": "Intermediate", "chain": "Chain_A", "level": 2},
        {"temp_id": "P", "role": "Intermediate", "chain": "Chain_A", "level": 2},
        {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 3}
      ],
      "edges": [
        {"source": "S", "target": "I1", "operation": "Transfer", "flow_share": 1.0},
        {"source": "I1", "target": "M", "operation": "Transfer", "flow_share": 0.8},
        {"source": "I1", "target": "P", "operation": "Transfer", "flow_share": 0.2},
        {"source": "M", "target": "T", "operation": "Transfer", "flow_share": 1.0},
        {"source": "P", "target": "T", "operation": "Transfer", "flow_share": 1.0}
      ],
      "post_state_effect": {"branch_increment": 0, "chain_transition": false, "next_recommended_roles": ["Target"]}
    }
  ]
}

### Few-shot 2 — standard cross-chain swap-bridge (phase_a inflow entry)
{
  "grounded_chains": ["Chain_A", "Chain_B"],
  "phase_a_inflow_motifs": [
    {
      "motif_id": "cross_chain_swap_bridge",
      "pattern_type": "Chain_Hopping",
      "description": "Swap volatile assets into a stablecoin on the origin chain, then bridge the proceeds to a target chain before final transfer to the destination wallet.",
      "preconditions": {"min_level": 1, "allowed_node_roles": ["Source", "Asset_Conversion"], "max_active_branches": 2},
      "nodes": [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "AC", "role": "Asset_Conversion", "chain": "Chain_A", "level": 1},
        {"temp_id": "I", "role": "Intermediate", "chain": "Chain_A", "level": 2},
        {"temp_id": "CC", "role": "Cross_Chain", "chain": "Chain_B", "level": 3},
        {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 4}
      ],
      "edges": [
        {"source": "S", "target": "AC", "operation": "Swap", "flow_share": 1.0},
        {"source": "AC", "target": "I", "operation": "Transfer", "flow_share": 1.0},
        {"source": "I", "target": "CC", "operation": "Bridge", "flow_share": 1.0},
        {"source": "CC", "target": "T", "operation": "Transfer", "flow_share": 1.0}
      ],
      "post_state_effect": {"branch_increment": 0, "chain_transition": true, "target_chain": "Chain_B", "next_recommended_roles": ["Cross_Chain", "Target"]}
    }
  ],
  "phase_b_outflow_motifs": []
}

### Few-shot 3 — multi-chain consolidation + OTC cash-out (both phases)
{
  "grounded_chains": ["Chain_A", "Chain_B"],
  "phase_a_inflow_motifs": [
    {
      "motif_id": "multi_chain_consolidation",
      "pattern_type": "Integration_Merge",
      "description": "Two source streams merge into an aggregator on the origin chain, then bridge to the target chain.",
      "preconditions": {"min_level": 2, "allowed_node_roles": ["Source", "Intermediate", "Aggregator", "Cross_Chain"], "max_active_branches": 2},
      "nodes": [
        {"temp_id": "S1", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "S2", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "AGG", "role": "Aggregator", "chain": "Chain_A", "level": 1},
        {"temp_id": "CC", "role": "Cross_Chain", "chain": "Chain_B", "level": 2}
      ],
      "edges": [
        {"source": "S1", "target": "AGG", "operation": "Merge", "flow_share": 1.0},
        {"source": "S2", "target": "AGG", "operation": "Merge", "flow_share": 1.0},
        {"source": "AGG", "target": "CC", "operation": "Bridge", "flow_share": 1.0}
      ],
      "post_state_effect": {"branch_increment": -1, "chain_transition": true, "target_chain": "Chain_B", "next_recommended_roles": ["Cross_Chain"]}
    }
  ],
  "phase_b_outflow_motifs": [
    {
      "motif_id": "otc_cash_out_fanout",
      "pattern_type": "Multi_Layering_Split",
      "description": "Consolidated funds are fanned out into three target-chain OTC/P2P acceptor deposit addresses for off-chain cash-out.",
      "preconditions": {"min_level": 2, "allowed_node_roles": ["Cross_Chain", "Intermediate", "Target"], "max_active_branches": 3},
      "nodes": [
        {"temp_id": "CC", "role": "Cross_Chain", "chain": "Chain_B", "level": 0},
        {"temp_id": "T1", "role": "Target", "chain": "Chain_B", "level": 1},
        {"temp_id": "T2", "role": "Target", "chain": "Chain_B", "level": 1},
        {"temp_id": "T3", "role": "Target", "chain": "Chain_B", "level": 1}
      ],
      "edges": [
        {"source": "CC", "target": "T1", "operation": "Split", "flow_share": 0.34},
        {"source": "CC", "target": "T2", "operation": "Split", "flow_share": 0.33},
        {"source": "CC", "target": "T3", "operation": "Split", "flow_share": 0.33}
      ],
      "post_state_effect": {"branch_increment": 2, "chain_transition": false, "next_recommended_roles": ["Target"]}
    }
  ]
}

OUTPUT FORMAT:
Respond with ONLY a valid JSON object conforming to the provided schema.
No markdown fences, no prose, no commentary.
"""


# ---------------------------------------------------------------------------
# Attention anchor (fund-flow telemetry signpost)
# ---------------------------------------------------------------------------
def format_attention_anchor(entry: dict[str, Any] | None) -> str | None:
    """Render an ``eligibility_audit.json`` entry into an attention-anchor block.

    The anchor is a signpost ONLY — the report body remains the single source
    of truth.  Returns ``None`` when the entry carries no telemetry.  Prompt
    v2.2 keeps only macro-level telemetry: ``hops_detected`` (hop-count order
    of magnitude) and ``flow_markers`` (semantic keywords).  The per-hop
    ``evidence_chain`` address walk is deliberately stripped to avoid
    micro-level induction that caused action-role drift and ghost hops.
    """
    if not entry:
        return None
    hops = entry.get("hops_detected")
    markers = entry.get("markers") or []
    if hops is None and not markers:
        return None

    lines = [ATTENTION_ANCHOR_HEADER]
    if hops is not None:
        lines.append(f"hops_detected: {hops}")
    if markers:
        lines.append(f"flow_markers: {', '.join(str(m) for m in markers)}")
    lines.append(
        "This anchor is a signpost ONLY — the report body remains the single "
        "source of truth. Do NOT invent chains/relays beyond the evidence."
    )
    lines.append(ATTENTION_ANCHOR_FOOTER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------
def build_v2_prompt(
    chunk_text: str,
    *,
    attention_anchor: str | None = None,
    directive: str | None = None,
    survey_note: str | None = None,
    retry_error: str | None = None,
) -> str:
    """Assemble the full Prompt v2 for one report segment.

    ``directive`` is the genre/contract note (survey or unified campaign DAG);
    ``survey_note`` is kept as a backwards-compatible alias.
    """
    note = directive if directive is not None else survey_note
    blocks: list[str] = [DISTILLATION_PROMPT_V2]
    if attention_anchor:
        blocks.extend(["", attention_anchor])
    if note:
        blocks.extend(["", note])
    blocks.extend(
        [
            "",
            "### TARGET JSON SCHEMA ###",
            build_v2_schema_json(),
            "",
            "### REPORT SEGMENT ###",
            chunk_text.strip(),
        ]
    )
    if retry_error:
        blocks.extend(
            [
                "",
                "### PREVIOUS MISTAKE ###",
                f"Your previous output was rejected for: {retry_error}",
                "Fix the issue and output a corrected JSON object.",
            ]
        )
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Two-phase parse + axiom guards
# ---------------------------------------------------------------------------
@dataclass
class PhaseMotif:
    """A parsed motif with its two-phase slot marker preserved."""

    phase: str
    motif: TopologicalMotif


@dataclass
class ParsedV2Payload:
    """Outcome of parsing one two-phase wrapper reply.

    ``phase_motifs`` only contains motifs that pass the cardinality bounds
    (``MIN_EDGE_COUNT <= len(edges) <= MAX_EDGE_COUNT``).  Micro-fragments
    (< lower bound) are surfaced in ``dropped_micro_fragments``; suspected
    node-explosion graphs (> upper bound) are surfaced in
    ``quarantined_oversize``.  Neither ever reaches the knowledge-grammar path.
    """

    phase_motifs: list[PhaseMotif] = field(default_factory=list)
    dropped_micro_fragments: list[PhaseMotif] = field(default_factory=list)
    quarantined_oversize: list[PhaseMotif] = field(default_factory=list)
    error: str | None = None


@dataclass
class TwoPhaseDistillResult:
    """Flattened two-phase distillation outcome."""

    motifs: list[TopologicalMotif] = field(default_factory=list)
    phase_motifs: list[PhaseMotif] = field(default_factory=list)
    dropped_micro_fragments: list[PhaseMotif] = field(default_factory=list)
    quarantined_oversize: list[PhaseMotif] = field(default_factory=list)
    chunk_motifs: list[list[TopologicalMotif]] = field(default_factory=list)
    failures: list[DistillationFailure] = field(default_factory=list)
    chunks: int = 0


def validate_grounded_chains(
    grounded_chains: Sequence[str], motifs: Sequence[TopologicalMotif]
) -> list[str]:
    """Return boundary violations: every motif chain must be grounded.

    Enforces the entity-grounding invariant — ``used_chains ⊆ grounded_chains``
    (hence ``len(used_chains) <= len(grounded_chains)`` for a duplicate-free
    ``grounded_chains`` list).
    """
    allowed = set(grounded_chains)
    issues: list[str] = []
    for motif in motifs:
        used = {node.chain for node in motif.nodes}
        extra = sorted(used - allowed)
        if extra:
            issues.append(
                f"{motif.motif_id}: chains {extra} are not grounded "
                f"(grounded_chains={sorted(allowed)})"
            )
    return issues


def parse_v2_response(raw: str) -> ParsedV2Payload:
    """Parse an LLM reply in the two-phase wrapper format.

    Returns a :class:`ParsedV2Payload`.  The parser:
      1. extracts + loads the wrapper JSON (fence/prose tolerant);
      2. validates ``grounded_chains``;
      3. validates every motif in BOTH phases via :class:`TopologicalMotif`
         (which embeds the Kahn / conservation / cross-chain axiom guards);
      4. enforces the grounded-chains boundary check;
      5. applies the cardinality lower bound — motifs with
         ``len(edges) < MIN_EDGE_COUNT`` are discarded as micro-fragments and
         never flow into axiom validation or isomorphism de-duplication.
    """
    cleaned = strip_code_fences(raw)
    payload, json_error = load_json_robust(cleaned)
    if json_error is not None:
        return ParsedV2Payload(error=json_error)
    if not isinstance(payload, dict):
        return ParsedV2Payload(
            error=f"expected a two-phase JSON object, got {type(payload).__name__}"
        )

    grounded_chains = payload.get("grounded_chains")
    if (
        not isinstance(grounded_chains, list)
        or not grounded_chains
        or not all(isinstance(c, str) and c.strip() for c in grounded_chains)
    ):
        return ParsedV2Payload(
            error="`grounded_chains` must be a non-empty list of abstract chain labels"
        )

    phase_motifs: list[PhaseMotif] = []
    for phase_key, phase_tag in ((PHASE_A, PHASE_A_TAG), (PHASE_B, PHASE_B_TAG)):
        items = payload.get(phase_key, [])
        if not isinstance(items, list):
            return ParsedV2Payload(
                error=f"`{phase_key}` must be a JSON array of motifs"
            )
        for index, item in enumerate(items):
            try:
                motif = TopologicalMotif.model_validate(item)
            except Exception as exc:  # noqa: BLE001 - per-item schema/topology error
                return ParsedV2Payload(
                    error=f"{phase_key}[{index}] invalid: {exc}"
                )
            # Post-processing normalisation: scrub token symbols from
            # natural-language metadata, then tag sandglass-bottleneck nodes
            # (stage_boundary:<temp_id>) so a unified campaign DAG keeps its
            # causal closure while surfacing its Inflow/Outflow seam.
            phase_motifs.append(
                PhaseMotif(
                    phase=phase_tag,
                    motif=annotate_stage_boundaries(scrub_motif_metadata(motif)),
                )
            )

    # Causal coherence: a motif must be one weakly-connected component.
    # A "unified campaign DAG" that is actually several disconnected islands
    # pasted together is rejected and sent back for reflection repair.
    disconnected = [
        pm.motif.motif_id for pm in phase_motifs if not pm.motif.is_weakly_connected()
    ]
    if disconnected:
        return ParsedV2Payload(
            error="motif must be weakly connected (single causal component): "
            + ", ".join(disconnected)
        )

    boundary_issues = validate_grounded_chains(
        grounded_chains, [pm.motif for pm in phase_motifs]
    )
    if boundary_issues:
        return ParsedV2Payload(
            error="grounded_chains boundary violated: " + "; ".join(boundary_issues)
        )

    # Cardinality bounds: discard trivial 1-2 edge micro-fragments and
    # quarantine suspected node-explosion graphs (> MAX_EDGE_COUNT).
    kept: list[PhaseMotif] = []
    dropped: list[PhaseMotif] = []
    oversize: list[PhaseMotif] = []
    for pm in phase_motifs:
        edge_count = len(pm.motif.edges)
        if edge_count < MIN_EDGE_COUNT:
            dropped.append(pm)
        elif edge_count > MAX_EDGE_COUNT:
            oversize.append(pm)
        else:
            kept.append(pm)

    return ParsedV2Payload(
        phase_motifs=kept,
        dropped_micro_fragments=dropped,
        quarantined_oversize=oversize,
    )


class PromptV2Distiller:
    """Drives Prompt v2 distillation with defensive parsing + reflection repair."""

    def __init__(
        self,
        llm: LLMCallable,
        *,
        chunker: TextChunker | None = None,
        max_repair_retries: int = 2,
        enable_single_pass: bool = True,
    ) -> None:
        self._llm = llm
        self._chunker = chunker or TextChunker()
        self._max_repair_retries = max_repair_retries
        self._enable_single_pass = enable_single_pass

    # ----------------------------------------------------------------- distill
    def distill(
        self, text: str, *, attention_anchor: str | None = None
    ) -> TwoPhaseDistillResult:
        """Distill ``text`` into flattened motifs (two-phase contract).

        Macro industry surveys are detected and trimmed to their deep-dive
        case narrative; every report (survey or incident) then receives the
        unified campaign DAG directive.  Any report at or below
        ``SINGLE_PASS_MAX_CHARS`` is fed as ONE context (single-pass) to
        eliminate cross-chunk echo / twin motifs.
        """
        is_survey = detect_survey_report(text)
        source_text = focus_survey_case_narrative(text) if is_survey else text
        directive = SURVEY_DIRECTIVE if is_survey else CAMPAIGN_DIRECTIVE
        if self._enable_single_pass and len(source_text) <= SINGLE_PASS_MAX_CHARS:
            chunks = [source_text]
        else:
            chunks = self._chunker.chunk(source_text)
        for chunk in chunks:
            assert isinstance(chunk, str) and chunk.strip()
        result = TwoPhaseDistillResult(chunks=len(chunks))
        for index, chunk in enumerate(chunks):
            parsed, failure = self._distill_chunk(
                index, chunk, attention_anchor, directive
            )
            chunk_motifs = [pm.motif for pm in parsed.phase_motifs]
            result.chunk_motifs.append(chunk_motifs)
            result.phase_motifs.extend(parsed.phase_motifs)
            result.motifs.extend(chunk_motifs)
            result.dropped_micro_fragments.extend(parsed.dropped_micro_fragments)
            result.quarantined_oversize.extend(parsed.quarantined_oversize)
            if failure is not None:
                result.failures.append(failure)
        return result

    # -- single chunk with reflection repair --------------------------------
    def _distill_chunk(
        self,
        index: int,
        chunk_text: str,
        attention_anchor: str | None,
        directive: str | None = None,
    ) -> tuple[ParsedV2Payload, DistillationFailure | None]:
        retry_error: str | None = None
        for _ in range(1 + self._max_repair_retries):
            prompt = build_v2_prompt(
                chunk_text,
                attention_anchor=attention_anchor,
                directive=directive,
                retry_error=retry_error,
            )
            reply = self._llm(prompt)

            parsed = parse_v2_response(reply)
            if parsed.error is not None:
                retry_error = parsed.error
                continue

            return parsed, None

        failure = DistillationFailure(
            chunk_index=index,
            error=retry_error or "unknown error",
            attempts=1 + self._max_repair_retries,
        )
        return ParsedV2Payload(), failure
