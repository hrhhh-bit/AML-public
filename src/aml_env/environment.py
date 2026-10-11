"""Lightweight behavioural graph environment (Stage-1 state machine).

:class:`BehavioralEnvironment` incrementally builds the abstract money
laundering behavioural graph :math:`G_b = (V, E)` under hard topological
constraints.  It is the *native producer* of :class:`aml_rag.schema.CurrentState`
snapshots — every step yields a snapshot the dual-track retriever can consume
with zero adaptation.

Design decisions (agreed):

- ``AgentAction`` lives here (execution-layer cohesion);
- frontier nodes remain *re-usable* until their out-degree saturates at
  :math:`d_{max}` (branching cap keeps its original semantics);
- terminate is ``operation=None`` and goes through :meth:`step`;
- rewards: legal 0 / illegal -1 / successful termination +1;
- ``current_chain`` is the target chain of the last *successful* action;
- chains are abstract labels (``Chain_A/B/C``), matching the motif KB;
- ``Merge`` requires parents to share chain and level;
- ``max_steps`` defaults to 64; ``Split`` defaults to 2 children in
  :math:`[2, d_{max}]`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aml_rag.config import AMLConfig, load_default_config
from aml_rag.schema import (
    AbstractEdge,
    AbstractNode,
    CurrentState,
    MotifConstraints,
    NodeRole,
    OperationType,
)

from .verifier import HardVerifier

__all__ = [
    "AgentAction",
    "StepResult",
    "RewardConfig",
    "BehavioralEnvironment",
]


# ---------------------------------------------------------------------------
# Action / result payloads
# ---------------------------------------------------------------------------
class AgentAction(BaseModel):
    """Normalised action payload emitted by the Planner Agent.

    ``operation=None`` is the terminate control action (no node is created).
    """

    model_config = ConfigDict(extra="forbid")

    operation: OperationType | None
    parent_ids: list[str] = Field(default_factory=list)
    target_role: NodeRole | None = None
    target_chain: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_target_for_topology_actions(self) -> "AgentAction":
        if self.operation is not None:
            if not self.parent_ids:
                raise ValueError("topology actions require at least one parent_id")
            if self.target_role is None:
                raise ValueError("topology actions require target_role")
            if not self.target_chain:
                raise ValueError("topology actions require target_chain")
        return self


class StepResult(BaseModel):
    """Outcome of one environment transition."""

    model_config = ConfigDict(extra="forbid")

    state: CurrentState
    reward: float
    done: bool
    info: dict[str, Any] = Field(default_factory=dict)


class RewardConfig(BaseModel):
    """Sparse compliance rewards (agreed defaults)."""

    model_config = ConfigDict(extra="forbid")

    legal: float = 0.0
    illegal: float = -1.0
    terminate: float = 1.0


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
#: Sentinel distinguishing "parameter not passed" from explicit ``None``.
_UNSET = object()


class BehavioralEnvironment:
    """Incremental DAG builder for the abstract behavioural graph."""

    def __init__(
        self,
        *,
        d_max: int = _UNSET,
        max_level: int = _UNSET,
        max_steps: int = _UNSET,
        seed_chain: str = _UNSET,
        initial_role: NodeRole = _UNSET,
        rewards: RewardConfig | None = None,
        config: AMLConfig | None = None,
    ) -> None:
        """Args:
        d_max: maximum out-degree (branching factor) :math:`d_{max}`.
        max_level: maximum graph depth :math:`L_{max}`.
        max_steps: trajectory-length limit (primary limit for the planner).
        seed_chain: initial abstract chain label.
        initial_role: role of the seed (root) node.
        rewards: optional custom reward triple.
        config: optional :class:`aml_rag.config.AMLConfig` supplying the
            topology-domain defaults.  Omitted parameters fall back to the
            config values; with ``config=None`` the transparent defaults
            equal the legacy hard-coded values (Zero-Delta).  Explicit
            keyword arguments always take precedence over the config.
        """
        tc = load_default_config(config).topology
        d_max = tc.d_max if d_max is _UNSET else d_max
        max_level = tc.max_level_bound if max_level is _UNSET else max_level
        max_steps = tc.max_steps if max_steps is _UNSET else max_steps
        seed_chain = tc.seed_chain if seed_chain is _UNSET else seed_chain
        initial_role = (
            NodeRole(tc.initial_role) if initial_role is _UNSET else initial_role
        )
        self._constraints = MotifConstraints(
            max_branching_factor=d_max,
            max_level_bound=max_level,
            min_level_bound=tc.min_level_bound,
        )
        self._verifier = HardVerifier(self._constraints)
        self._max_steps = max_steps
        self._seed_chain = seed_chain
        self._initial_role = initial_role
        self._rewards = rewards or RewardConfig(
            legal=tc.reward_legal,
            illegal=tc.reward_illegal,
            terminate=tc.reward_terminate,
        )

        self._nodes: dict[str, AbstractNode] = {}
        self._edges: list[AbstractEdge] = []
        self._frontier: set[str] = set()
        self._outdeg: dict[str, int] = {}
        self._step: int = 0
        self._next_id: int = 0
        self._last_chain: str = seed_chain
        self._terminated: bool = False
        self._termination_reason: str | None = None

    # ------------------------------------------------------------- lifecycle
    def reset(self) -> CurrentState:
        """(Re)initialise the graph with a single root node at level 0."""
        self._nodes.clear()
        self._edges.clear()
        self._frontier.clear()
        self._outdeg.clear()
        self._step = 0
        self._next_id = 1
        self._last_chain = self._seed_chain
        self._terminated = False
        self._termination_reason = None

        root_id = "node_0"
        self._nodes[root_id] = AbstractNode(
            temp_id=root_id,
            role=self._initial_role,
            chain=self._seed_chain,
            level=0,
        )
        self._frontier.add(root_id)
        return self.snapshot()

    # ---------------------------------------------------------------- step
    def step(self, action: AgentAction) -> StepResult:
        """Execute one action. Illegal actions leave the graph untouched."""
        if self._terminated:
            return StepResult(
                state=self.snapshot(),
                reward=self._rewards.illegal,
                done=True,
                info={"error": "environment already terminated", "accepted": False},
            )

        ok, reason = self._verifier.validate(
            nodes=self._nodes,
            edges=self._edges,
            frontier=self._frontier,
            action=action,
        )
        if not ok:
            return StepResult(
                state=self.snapshot(),
                reward=self._rewards.illegal,
                done=False,
                info={"error": reason, "accepted": False},
            )

        # --- terminate (control action) ------------------------------------
        if action.operation is None:
            self._terminated = True
            self._termination_reason = "agent_terminate"
            return StepResult(
                state=self.snapshot(),
                reward=self._rewards.terminate,
                done=True,
                info={"accepted": True, "terminated_by": self._termination_reason},
            )

        # --- create children & edges ---------------------------------------
        assert action.target_role is not None and action.target_chain is not None
        op = action.operation

        parent_levels = [self._nodes[pid].level for pid in action.parent_ids]
        new_level = max(parent_levels) + 1

        # Split fans out into `num_children` new nodes; every other action
        # produces exactly one new node.
        num_children = (
            int(action.parameters.get("num_children", 2))
            if op == OperationType.SPLIT
            else 1
        )
        child_ids: list[str] = []
        for _ in range(num_children):
            cid = f"node_{self._next_id}"
            self._next_id += 1
            self._nodes[cid] = AbstractNode(
                temp_id=cid,
                role=action.target_role,
                chain=action.target_chain,
                level=new_level,
            )
            child_ids.append(cid)

        # per-edge flow shares: agent-provided, else equal/unit fallbacks
        shares: list[float]
        if op == OperationType.SPLIT:
            provided = action.parameters.get("flow_shares")
            shares = (
                [float(v) for v in provided]
                if provided is not None
                else [1.0 / num_children] * num_children  # equal-slice fallback
            )
        else:
            shares = [1.0] * len(child_ids)

        for pid in action.parent_ids:
            for cid, share in zip(child_ids, shares):
                self._edges.append(
                    AbstractEdge(
                        source=pid, target=cid, operation=op, flow_share=share
                    )
                )
                self._outdeg[pid] = self._outdeg.get(pid, 0) + 1

        # --- update frontier (saturated parents leave, children enter) -----
        for pid in action.parent_ids:
            if self._outdeg.get(pid, 0) >= self._constraints.max_branching_factor:
                self._frontier.discard(pid)
        for cid in child_ids:
            self._frontier.add(cid)

        self._last_chain = action.target_chain
        self._step += 1

        # --- termination check ---------------------------------------------
        done, reason = self._check_termination()
        self._terminated = done
        self._termination_reason = reason

        reward = self._rewards.terminate if done else self._rewards.legal
        info: dict[str, Any] = {"accepted": True, "node_id": child_ids}
        if done:
            info["terminated_by"] = reason
        return StepResult(state=self.snapshot(), reward=reward, done=done, info=info)

    # ----------------------------------------------------------- termination
    def _check_termination(self) -> tuple[bool, str | None]:
        if not self._frontier:
            return True, "frontier_empty"
        if all(self._nodes[nid].role == NodeRole.TARGET for nid in self._frontier):
            return True, "all_frontier_are_sinks"
        max_level = max(n.level for n in self._nodes.values())
        if max_level >= self._constraints.max_level_bound:
            return True, "max_level_reached"
        if self._step >= self._max_steps:
            return True, "max_steps_reached"
        return False, None

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> CurrentState:
        """Export the current state exactly as the RAG retriever expects it."""
        max_level = max((n.level for n in self._nodes.values()), default=0)
        frontier_nodes = sorted(
            (self._nodes[nid] for nid in self._frontier), key=lambda n: n.temp_id
        )
        return CurrentState(
            current_level=max_level,
            current_chain=self._last_chain,
            active_nodes=frontier_nodes,
            graph_history=list(self._edges),
        )

    # ----------------------------------------------------------------- export
    def export_behavioral_graph(self) -> dict[str, Any]:
        """Full graph topology for downstream Stage-2 consumers."""
        return {
            "meta": {
                "node_count": len(self._nodes),
                "edge_count": len(self._edges),
                "steps": self._step,
                "max_level": max((n.level for n in self._nodes.values()), default=0),
                "d_max": self._constraints.max_branching_factor,
                "L_max": self._constraints.max_level_bound,
                "terminated": self._terminated,
                "terminated_by": self._termination_reason,
                "seed_chain": self._seed_chain,
                "initial_role": self._initial_role.value,
            },
            "nodes": [
                {"id": n.temp_id, "role": n.role.value, "chain": n.chain, "level": n.level}
                for _, n in sorted(self._nodes.items(), key=lambda kv: kv[0])
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "operation": e.operation.value,
                    "flow_share": round(e.flow_share, 4),
                }
                for e in self._edges
            ],
        }

    def render_mermaid(self) -> str:
        """Render the current graph as a Mermaid ``flowchart LR`` string."""
        lines = ["flowchart LR"]
        for nid in sorted(self._nodes):
            node = self._nodes[nid]
            label = f"{node.role.value}<br/>{node.chain} · L{node.level}"
            lines.append(f'    {nid}["{label}"]')
        for edge in self._edges:
            op_label = edge.operation.value
            if edge.flow_share < 1.0:
                op_label += f" {edge.flow_share:.2f}"
            lines.append(
                f"    {edge.source} -->|{op_label}| {edge.target}"
            )
        return "\n".join(lines)

    # ----------------------------------------------------------- properties
    @property
    def frontier(self) -> set[str]:
        return set(self._frontier)

    @property
    def step_count(self) -> int:
        return self._step

    @property
    def done(self) -> bool:
        return self._terminated

    @property
    def termination_reason(self) -> str | None:
        return self._termination_reason

    @property
    def constraints(self) -> MotifConstraints:
        return self._constraints
