"""Topology hard-constraint verifier for the behavioural graph environment.

:class:`HardVerifier` is a **pure, side-effect-free** gate that runs before
every environment transition.  It only enforces *structural* invariants
(derived from :class:`aml_rag.schema.MotifConstraints`); soft financial
semantics (role-compatibility, tactic plausibility) are deliberately left to
the RAG prior + LLM planner layer.

Guarantees:

1. parents are non-empty (except for the terminate control action) and all
   belong to the current active frontier;
2. per-node out-degree can never exceed :math:`d_{max}` (branching cap);
3. child level is strictly ``max(parent_levels) + 1``, capped by
   :math:`L_{max}` — which, together with rule 2, makes self-loops and back
   edges structurally impossible;
4. chain changes are only allowed for ``Bridge`` actions; ``Merge`` parents
   must share the same chain and level.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from aml_rag.schema import (
    FLOW_TOLERANCE,
    AbstractEdge,
    AbstractNode,
    MotifConstraints,
    OperationType,
)

if TYPE_CHECKING:  # pragma: no cover - avoids circular import at runtime
    from .environment import AgentAction

__all__ = ["HardVerifier"]


class HardVerifier:
    """Zero-tolerance structural gate for agent actions."""

    def __init__(self, constraints: MotifConstraints | None = None) -> None:
        self.constraints: MotifConstraints = constraints or MotifConstraints()

    # ------------------------------------------------------------------
    def validate(
        self,
        *,
        nodes: Mapping[str, AbstractNode],
        edges: Sequence[AbstractEdge],
        frontier: set[str],
        action: "AgentAction",
    ) -> tuple[bool, str | None]:
        """Validate ``action`` against the current graph snapshot.

        Returns ``(ok, reason)`` — ``reason`` is the human-readable refusal
        message when ``ok`` is False (to be fed back to the planner agent).
        """
        # --- terminate is a control action, not a topology action ---------
        if action.operation is None:
            return True, None

        # --- parents must be non-empty -------------------------------------
        if not action.parent_ids:
            return False, "action has no parent_ids"

        # --- per-operation arity -------------------------------------------
        op = action.operation
        if op == OperationType.MERGE and len(action.parent_ids) < 2:
            return False, f"Merge requires >= 2 parents, got {len(action.parent_ids)}"
        if op != OperationType.MERGE and len(action.parent_ids) != 1:
            return False, (
                f"{op.value} requires exactly 1 parent, "
                f"got {len(action.parent_ids)}"
            )

        # --- every parent must exist and belong to the frontier ------------
        for pid in action.parent_ids:
            if pid not in nodes:
                return False, f"parent node '{pid}' does not exist"
            if pid not in frontier:
                return False, f"parent node '{pid}' is not in the active frontier"

        parents = [nodes[pid] for pid in action.parent_ids]

        # --- split fan-out parameter ---------------------------------------
        new_edges_per_parent: dict[str, int] = {pid: 1 for pid in action.parent_ids}
        if op == OperationType.SPLIT:
            num_children = int(action.parameters.get("num_children", 2))
            dmax = self.constraints.max_branching_factor
            if not (2 <= num_children <= dmax):
                return False, (
                    f"Split num_children={num_children} out of range "
                    f"[2, {dmax}]"
                )
            new_edges_per_parent[action.parent_ids[0]] = num_children

        # --- flow conservation gate (branching / merging actions) ----------
        gate_error = self._check_flow_conservation(action, op, new_edges_per_parent)
        if gate_error is not None:
            return False, gate_error

        # --- branching cap d_max (current out-degree + new edges) ----------
        outdeg = Counter(e.source for e in edges)
        for pid, inc in new_edges_per_parent.items():
            if outdeg.get(pid, 0) + inc > self.constraints.max_branching_factor:
                return False, (
                    f"node '{pid}' would exceed max out-degree "
                    f"({outdeg.get(pid, 0)} + {inc} > "
                    f"{self.constraints.max_branching_factor})"
                )

        # --- merge parents must share chain & level ------------------------
        if op == OperationType.MERGE:
            first = parents[0]
            if any(p.chain != first.chain for p in parents[1:]):
                return False, "Merge parents must share the same chain"
            if any(p.level != first.level for p in parents[1:]):
                return False, "Merge parents must share the same level"

        # --- chain conservation: only Bridge may change chain --------------
        if op != OperationType.BRIDGE:
            if any(p.chain != action.target_chain for p in parents):
                return False, (
                    f"chain change not allowed for {op.value} "
                    "(only Bridge may change chain)"
                )

        # --- level monotonicity & depth cap --------------------------------
        new_level = max(p.level for p in parents) + 1
        if new_level > self.constraints.max_level_bound:
            return False, (
                f"new level {new_level} exceeds max_level_bound "
                f"{self.constraints.max_level_bound}"
            )

        return True, None

    # ------------------------------------------------------------------
    @staticmethod
    def _check_flow_conservation(
        action: "AgentAction",
        op: OperationType,
        new_edges_per_parent: dict[str, int],
    ) -> str | None:
        """Flow conservation gate for branching/merging actions.

        When ``flow_shares`` is provided it MUST be a normalised, well-formed
        list summing to 1.0 within :data:`aml_rag.schema.FLOW_TOLERANCE`.
        Returns a standardised reflection message on violation; ``None`` when
        the action is clean. Missing shares are NOT rejected here — the
        environment falls back to equal/unit defaults.
        """
        if op not in (OperationType.SPLIT, OperationType.MERGE):
            return None
        shares_raw = action.parameters.get("flow_shares")
        if shares_raw is None:
            return None  # environment-side fallback (equal split / unit merge)
        n_edges = (
            int(action.parameters.get("num_children", 2))
            if op == OperationType.SPLIT
            else len(action.parent_ids)
        )
        if not isinstance(shares_raw, (list, tuple)) or len(shares_raw) != n_edges:
            return (
                f"flow conservation: flow_shares must be a list of exactly "
                f"{n_edges} entries for {op.value}, got {shares_raw!r}"
            )
        try:
            values = [float(v) for v in shares_raw]
        except (TypeError, ValueError):
            return f"flow conservation: flow_shares must be numeric, got {shares_raw!r}"
        if any(not (0.0 < v <= 1.0) for v in values):
            return (
                f"flow conservation: every share must be in (0.0, 1.0], "
                f"got {values}"
            )
        total = sum(values)
        if abs(total - 1.0) > FLOW_TOLERANCE:
            return (
                f"flow conservation violated: sum(flow_shares)={total:.4f} "
                f"!= 1.0 (tolerance {FLOW_TOLERANCE}). Rebalance the shares "
                f"so they sum to exactly 1.0."
            )
        return None
