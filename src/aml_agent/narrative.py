"""Structure-derived strategy narrative & purity audit (no free-form LLM).

The narrative is assembled by **template mapping only** from facts that were
actually executed and verified in the graph — pattern sequence (from the
trajectory steps), cross-chain hop path (from node/edge metadata) and final
sink structure.  No LLM generation, hence no hallucination.

:func:`audit_export_purity` enforces the zero-micro-noise rule on exported
graphs: relative flow shares are allowed, wallet addresses / timestamps are
not.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from aml_rag.schema import OperationType

if TYPE_CHECKING:  # pragma: no cover - avoids circular import with planner
    from .planner import Trajectory

__all__ = ["build_strategy_narrative", "audit_export_purity"]

_OP_PHRASE: dict[OperationType, str] = {
    OperationType.TRANSFER: "direct transfers",
    OperationType.SWAP: "asset swaps",
    OperationType.BRIDGE: "cross-chain bridge hops",
    OperationType.SPLIT: "fan-out splits",
    OperationType.MERGE: "converging merges",
}

_ROLE_PHRASE: dict[str, str] = {
    "Target": "final target sinks",
    "Aggregator": "aggregators",
    "Cross_Chain": "cross-chain bridges",
}

_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{8,}")
_MS_TS_RE = re.compile(r"\b1[3-9]\d{11}\b")  # 13-digit millisecond timestamps


def _chain_path(graph: dict[str, Any]) -> list[str]:
    """Ordered, de-duplicated chain labels from node levels (A -> B -> C)."""
    nodes = sorted(graph.get("nodes", []), key=lambda n: (n["level"], n["id"]))
    seen: list[str] = []
    for node in nodes:
        chain = node["chain"]
        if not seen or seen[-1] != chain:
            seen.append(chain)
    return seen


def _pattern_sequence(steps: list[Any]) -> list[str]:
    phrases: list[str] = []
    for step in steps:
        op = step.action.operation
        if op is None:
            continue
        phrases.append(_OP_PHRASE.get(op, op.value))
    # compact consecutive duplicates
    compact: list[str] = []
    for phrase in phrases:
        if not compact or compact[-1] != phrase:
            compact.append(phrase)
    return compact


def build_strategy_narrative(trajectory: "Trajectory") -> str:
    """Derive a factual strategy statement from the executed trajectory."""
    graph = trajectory.graph
    steps = trajectory.steps

    sequence = _pattern_sequence(steps)
    chain_path = _chain_path(graph)
    tier = graph.get("meta", {}).get("scale_tier", "unspecified")
    node_roles = {n["role"] for n in graph.get("nodes", [])}
    sinks = sum(1 for n in graph.get("nodes", []) if n["role"] == "Target")

    parts: list[str] = [
        f"{tier}-scale laundering topology",
    ]
    if sequence:
        parts.append(
            "the executed pattern sequence was " + ", ".join(sequence)
        )
    if len(chain_path) > 1:
        parts.append(
            "funds traversed chains in the order " + " -> ".join(chain_path)
        )
    elif chain_path:
        parts.append(f"funds stayed on a single chain ({chain_path[0]})")
    if sinks:
        parts.append(f"settling into {sinks} final target sink(s)")
    if "Cross_Chain" in node_roles:
        parts.append("with cross-chain obfuscation")

    narrative = "; ".join(parts) + "."
    return narrative[0].upper() + narrative[1:]


def audit_export_purity(export: dict[str, Any]) -> list[str]:
    """Return purity violations found in an exported graph payload.

    Allowed: normalised relative flow shares and macro metadata. Forbidden:
    wallet-address-like hex strings and millisecond-timestamp-like numbers.
    """
    text = json.dumps(export, ensure_ascii=False)
    issues: list[str] = []
    if _ADDRESS_RE.search(text):
        issues.append("wallet-address-like hex pattern detected")
    if _MS_TS_RE.search(text):
        issues.append("millisecond-timestamp-like integer detected")
    return issues
