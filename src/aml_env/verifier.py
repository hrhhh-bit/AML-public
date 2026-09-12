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

from aml_rag.schema import AbstractEdge, AbstractNode, MotifConstraints, OperationType

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
