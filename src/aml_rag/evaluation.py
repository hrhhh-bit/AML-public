"""Empirical verification suite for distilled motifs (four checks).

1. Topology validity rate — Kahn acyclicity, branching cap, flow conservation.
2. Cross-source consistency — operator/edge signature coverage between
   different text sources, quantifying convergence (anti-hallucination).
3. Zero-noise audit — deep static scan for wallet addresses, gas, token
   symbols, amounts and timestamps (hard target: 0 residues).
4. Saturation analysis — marginal new non-isomorphic motifs as report
   segments accumulate (diminishing-returns trend data).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .schema import (
    FLOW_TOLERANCE,
    AbstractEdge,
    TopologicalMotif,
)

__all__ = [
    "TopologyValidityReport",
    "CrossSourceReport",
    "CrossSourceConsistencyEvaluator",
    "NoiseAuditReport",
    "SaturationPoint",
    "topology_validity",
    "cross_source_consistency",
    "zero_noise_audit",
    "saturation_analysis",
    "motif_topology_issues",
]


# ---------------------------------------------------------------------------
# Check 1: topology validity
# ---------------------------------------------------------------------------
class TopologyValidityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    valid: int
    valid_rate: float
    invalid_motifs: dict[str, list[str]] = Field(default_factory=dict)


def motif_topology_issues(motif: TopologicalMotif) -> list[str]:
    """Return the list of structural violations of one motif ([] = valid).

    Covers syntax-level checks (acyclicity, branching) plus the Stage-3
    Part-B physical ledger invariants:

    - ``cross_chain_non_bridge:{src}->{tgt}`` — a cross-chain edge that is
      not a Bridge primitive (ledger state cannot leap chains otherwise);
    - ``outflow_conservation:{nid}`` — the out-edge flow_shares of a node
      do not sum to 1.0 (single out-edges MUST be exactly 1.0).
    """
    issues: list[str] = []
    if not motif.is_dag():
        issues.append("not_acyclic")

    out_degree: Counter[str] = Counter(e.source for e in motif.edges)
    for nid, degree in out_degree.items():
        if degree > motif.constraints.max_branching_factor:
            issues.append(f"branching_exceeded:{nid}={degree}")
            break

    # cross-chain ledger invariant (case-robust Bridge check)
    chain_of = {n.temp_id: n.chain for n in motif.nodes}
    for edge in motif.edges:
        if (
            chain_of[edge.source] != chain_of[edge.target]
            and edge.operation.value.lower() != "bridge"
        ):
            issues.append(f"cross_chain_non_bridge:{edge.source}->{edge.target}")

    # out-flow conservation: every node's out-edge shares must sum to 1.0
    out_groups: dict[str, list[AbstractEdge]] = {}
    for edge in motif.edges:
        out_groups.setdefault(edge.source, []).append(edge)
    for nid, group in out_groups.items():
        if abs(sum(e.flow_share for e in group) - 1.0) > FLOW_TOLERANCE:
            issues.append(f"outflow_conservation:{nid}")
    return issues


def topology_validity(motifs: Sequence[TopologicalMotif]) -> TopologyValidityReport:
    valid = 0
    invalid_map: dict[str, list[str]] = {}
    for motif in motifs:
        issues = motif_topology_issues(motif)
        if issues:
            invalid_map[motif.motif_id] = issues
        else:
            valid += 1
    total = len(motifs)
    return TopologyValidityReport(
        total=total,
        valid=valid,
        valid_rate=round(valid / total, 4) if total else 0.0,
        invalid_motifs=invalid_map,
    )


# ---------------------------------------------------------------------------
# Check 2: cross-source consistency (dual-track)
# ---------------------------------------------------------------------------
class CrossSourceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_names: list[str] = Field(default_factory=list)
    overall_consistency: float = Field(
        default=0.0,
        description="Primary convergence metric = global_topology_jaccard "
        "(pattern-agnostic operator-set overlap across sources).",
    )
    pattern_strict_jaccard: float = Field(
        default=0.0,
        description="Mean Jaccard within shared pattern_type buckets "
        "(strict label agreement; label drift penalises this track).",
    )
    global_topology_jaccard: float = Field(
        default=0.0,
        description="Jaccard of the union of edge operators per source, "
        "ignoring pattern labels — robust to prose dilution.",
    )
    per_pattern: dict[str, float] = Field(default_factory=dict)
    global_operator_sets: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Per-source sorted edge-operator lists (canonical enum "
        "values: Bridge/Swap/Split/Merge/Transfer — case-consistent).",
    )
    global_role_sets: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Per-source sorted node-role lists (diagnostic dimension; "
            "does not feed the primary Jaccard)."
        ),
    )


def _jaccard(a: set[Any], b: set[Any]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _global_operator_set(motifs: Sequence[TopologicalMotif]) -> set[str]:
    """Union of edge operation values across all motifs of one source.

    Uses the canonical ``OperationType`` enum values, so cross-source set
    intersection is case-consistent by construction (no ad-hoc casing).
    """
    return {e.operation.value for motif in motifs for e in motif.edges}


def _global_role_set(motifs: Sequence[TopologicalMotif]) -> set[str]:
    """Union of node role values across all motifs of one source (diagnostic)."""
    return {n.role.value for motif in motifs for n in motif.nodes}


class CrossSourceConsistencyEvaluator:
    """Dual-track cross-source consistency quantifier.

    Track 1 — ``pattern_strict_jaccard``: edge-signature Jaccard **within
    shared pattern_type buckets** (both sources must agree on the label).
    Track 2 — ``global_topology_jaccard``: Jaccard of the union of edge
    operators per source, ignoring local pattern labels.  This is robust when
    one source's prose (refund narratives, ads) dilutes the pattern_type but
    the underlying fund-flow operators still converge.
    """

    def evaluate(
        self, source_sets: Mapping[str, Sequence[TopologicalMotif]]
    ) -> CrossSourceReport:
        names = list(source_sets.keys())
        per_pattern, pattern_strict = self._pattern_strict(source_sets)
        global_jaccard, operator_sets = self._global_topology(source_sets)
        role_sets = {
            name: _global_role_set(motifs) for name, motifs in source_sets.items()
        }
        return CrossSourceReport(
            source_names=names,
            overall_consistency=global_jaccard,
            pattern_strict_jaccard=pattern_strict,
            global_topology_jaccard=global_jaccard,
            per_pattern=per_pattern,
            global_operator_sets={n: sorted(s) for n, s in operator_sets.items()},
            global_role_sets={n: sorted(s) for n, s in role_sets.items()},
        )

    @staticmethod
    def _pattern_strict(
        source_sets: Mapping[str, Sequence[TopologicalMotif]],
    ) -> tuple[dict[str, float], float]:
        # pattern_type -> {source -> union of edge signatures}
        by_pattern: dict[str, dict[str, set[tuple]]] = {}
        for source, motifs in source_sets.items():
            for motif in motifs:
                bucket = by_pattern.setdefault(motif.pattern_type.value, {})
                bucket.setdefault(source, set()).update(motif.edge_signature_set())

        per_pattern: dict[str, float] = {}
        for pattern, source_sigs in by_pattern.items():
            if len(source_sigs) < 2:
                per_pattern[pattern] = 0.0  # pattern seen in only one source
                continue
            sigs = list(source_sigs.values())
            scores = [
                _jaccard(sigs[i], sigs[j])
                for i in range(len(sigs))
                for j in range(i + 1, len(sigs))
            ]
            per_pattern[pattern] = round(sum(scores) / len(scores), 4) if scores else 0.0

        strict = round(sum(per_pattern.values()) / len(per_pattern), 4) if per_pattern else 0.0
        return per_pattern, strict

    @staticmethod
    def _global_topology(
        source_sets: Mapping[str, Sequence[TopologicalMotif]],
    ) -> tuple[float, dict[str, set[str]]]:
        operator_sets = {
            name: _global_operator_set(motifs) for name, motifs in source_sets.items()
        }
        sigs = list(operator_sets.values())
        if len(sigs) < 2:
            return 0.0, operator_sets
        scores = [
            _jaccard(sigs[i], sigs[j])
            for i in range(len(sigs))
            for j in range(i + 1, len(sigs))
        ]
        jaccard = round(sum(scores) / len(scores), 4) if scores else 0.0
        return jaccard, operator_sets


def cross_source_consistency(
    source_sets: Mapping[str, Sequence[TopologicalMotif]],
) -> CrossSourceReport:
    """Convenience wrapper: dual-track cross-source consistency report."""
    return CrossSourceConsistencyEvaluator().evaluate(source_sets)


# ---------------------------------------------------------------------------
# Check 3: zero-noise audit
# ---------------------------------------------------------------------------
class NoiseAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    violations: dict[str, list[str]] = Field(default_factory=dict)
    residue_count: int = 0

    @property
    def clean_rate(self) -> float:
        return round(
            (self.total - len(self.violations)) / self.total, 4
        ) if self.total else 1.0


_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{8,}")
_GAS_RE = re.compile(r"\bgas\b", re.IGNORECASE)
_TOKEN_RE = re.compile(
    r"\b(USDT|USDC|ETH|BTC|XMR|XRP|SOL|DAI|WBTC|WETH|BNB)\b", re.IGNORECASE
)
#: Concrete L1/L2 chain names (must be abstract Chain_A/B/C, never Ethereum/Tron).
_CHAIN_NAME_RE = re.compile(
    r"\b(ETHEREUM|TRON|SOLANA|ARBITRUM|OPTIMISM|POLYGON|AVALANCHE|FANTOM|BSC)\b",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"(\$\s*\d[\d,\.]*|\b\d[\d,\.]*\s*(USDT|USDC|ETH|BTC|USD)\b)")
_MS_TS_RE = re.compile(r"\b1[3-9]\d{11}\b")  # 13-digit millisecond timestamps
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def zero_noise_audit(motifs: Sequence[TopologicalMotif]) -> NoiseAuditReport:
    """Deep static scan of every motif field for micro-numerical noise."""
    violations: dict[str, list[str]] = {}
    for motif in motifs:
        text = motif.model_dump_json(exclude_none=True)
        found: list[str] = []
        if _ADDRESS_RE.search(text):
            found.append("wallet_address")
        if _GAS_RE.search(text):
            found.append("gas_reference")
        if _TOKEN_RE.search(text):
            found.append("token_symbol")
        if _CHAIN_NAME_RE.search(text):
            found.append("chain_name")
        if _AMOUNT_RE.search(text):
            found.append("explicit_amount")
        if _MS_TS_RE.search(text) or _DATE_RE.search(text):
            found.append("timestamp")
        if found:
            violations[motif.motif_id] = found
    return NoiseAuditReport(
        total=len(motifs),
        violations=violations,
        residue_count=sum(len(v) for v in violations.values()),
    )


# ---------------------------------------------------------------------------
# Check 4: saturation analysis
# ---------------------------------------------------------------------------
class SaturationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_index: int
    marginal_new: int
    cumulative_unique: int


def saturation_analysis(
    chunk_motifs: Sequence[Sequence[TopologicalMotif]],
) -> list[SaturationPoint]:
    """Marginal new non-isomorphic motifs as report segments accumulate.

    Two motifs are considered isomorphic when their flow-aware signatures
    match exactly; only new signatures advance the cumulative count.
    """
    seen: set[frozenset] = set()
    cumulative = 0
    points: list[SaturationPoint] = []
    for index, motifs in enumerate(chunk_motifs):
        marginal = 0
        for motif in motifs:
            signature = frozenset(motif.flow_signature_set())
            if signature and signature not in seen:
                seen.add(signature)
                marginal += 1
                cumulative += 1
        points.append(
            SaturationPoint(
                chunk_index=index,
                marginal_new=marginal,
                cumulative_unique=cumulative,
            )
        )
    return points
