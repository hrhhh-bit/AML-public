"""Module 1 core data contracts (Tri-Layer Knowledge Schema).

Implements the abstract topological ontology for the Cross-Chain AML
Behavioral Graph Generation framework:

- **Tactic Layer**: high-level AML strategy (:class:`PatternType`).
- **Motif Subgraph Layer**: canonical DAG patterns
  (:class:`TopologicalMotif` composed of :class:`AbstractNode` /
  :class:`AbstractEdge`).
- **Constraint Layer**: hard structural limits (:class:`MotifConstraints`),
  trigger preconditions (:class:`Preconditions`) and expected
  post-state transitions (:class:`PostStateEffect`).

Design rule: **zero micro-numerical noise** — no wallet addresses, no exact
amounts, no gas fees, no timestamps. Only abstract roles, chains, DAG levels
and abstract operations are modelled.
"""

from __future__ import annotations

from collections import Counter, deque
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterator

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

__all__ = [
    "NodeRole",
    "OperationType",
    "PatternType",
    "AbstractNode",
    "AbstractEdge",
    "Preconditions",
    "PostStateEffect",
    "MotifConstraints",
    "TopologicalMotif",
    "CurrentState",
    "QueryContext",
    "FLOW_TOLERANCE",
]

#: Engineering tolerance for normalised flow-conservation checks.
FLOW_TOLERANCE: float = 0.01


# ---------------------------------------------------------------------------
# Enumerations (abstract vocabularies)
# ---------------------------------------------------------------------------
class NodeRole(str, Enum):
    """Abstract node roles of the behavioral graph :math:`V_{abstract}`."""

    SOURCE = "Source"
    INTERMEDIATE = "Intermediate"
    ASSET_CONVERSION = "Asset_Conversion"
    CROSS_CHAIN = "Cross_Chain"
    AGGREGATOR = "Aggregator"
    TARGET = "Target"


class OperationType(str, Enum):
    """Abstract edge operations :math:`E_{abstract}`."""

    TRANSFER = "Transfer"
    SWAP = "Swap"
    BRIDGE = "Bridge"
    SPLIT = "Split"
    MERGE = "Merge"


class PatternType(str, Enum):
    """High-level AML tactic vocabularies (Tactic Layer)."""

    PEELING_CHAIN = "Peeling_Chain"
    CHAIN_HOPPING = "Chain_Hopping"
    MULTI_LAYERING_SPLIT = "Multi_Layering_Split"
    TOKEN_OBFUSCATION = "Token_Obfuscation"
    INTEGRATION_MERGE = "Integration_Merge"


# ---------------------------------------------------------------------------
# Motif subgraph primitives
# ---------------------------------------------------------------------------
class AbstractNode(BaseModel):
    """A single abstract vertex of a motif. Frozen so it can be hashed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    temp_id: str = Field(min_length=1, description="Motif-local node identifier, e.g. 'S', 'AC1'.")
    role: NodeRole
    chain: str = Field(min_length=1, description="Abstract chain label, e.g. 'Chain_A'.")
    level: int = Field(ge=0, description="DAG step level (0 = source level).")

    def __repr__(self) -> str:  # compact, token-efficient debug representation
        return (
            f"{type(self).__name__}({self.temp_id!r}, {self.role.value}, "
            f"{self.chain!r}, L{self.level})"
        )


class AbstractEdge(BaseModel):
    """A directed abstract operation edge between two motif-local nodes.

    ``flow_share`` is the normalised relative flow carried by this edge
    (backward compatible default ``1.0``). It lets the knowledge base
    distinguish geometrically identical sub-graphs behaviourally — e.g. a
    Peeling Chain with asymmetric main/strip ratios vs. an equal-slice
    Layering Split. Pure relative prior: no absolute amounts allowed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    operation: OperationType
    flow_share: float = Field(
        default=1.0,
        gt=0.0,
        le=1.0,
        description="Normalised flow share in (0.0, 1.0]; relative prior only.",
    )

    def signature(self) -> tuple[str, str, str]:
        """Role/operation signature used for cross-motif path de-duplication."""
        return (self.source, self.target, self.operation.value)


# ---------------------------------------------------------------------------
# Tactic layer: trigger preconditions & post-state effects
# ---------------------------------------------------------------------------
class Preconditions(BaseModel):
    """Hard trigger conditions of a motif.

    ``None``-valued fields mean *unconstrained*.  A motif is applicable only
    when the current :class:`CurrentState` satisfies **all** non-null fields.
    """

    model_config = ConfigDict(extra="forbid")

    min_level: int = Field(
        default=0,
        ge=0,
        description="Minimum global DAG level required to trigger the motif.",
    )
    allowed_node_roles: list[NodeRole] | None = Field(
        default=None,
        description="Applicable active node roles: at least one current "
        "active role must overlap this set (multi-role frontiers are the "
        "norm). None = no restriction.",
    )
    required_chains: list[str] | None = Field(
        default=None,
        description="Current chain must belong to this set. None = no restriction.",
    )
    max_active_branches: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of active (frontier) nodes allowed. "
        "None = no restriction.",
    )

    @field_validator("allowed_node_roles", "required_chains")
    @classmethod
    def _reject_empty_lists_as_constraints(
        cls, v: list[Any] | None
    ) -> list[Any] | None:
        """Normalise ``[]`` to ``None``: an empty list must mean unconstrained."""
        return v or None

    @property
    def is_unconstrained(self) -> bool:
        return (
            self.min_level == 0
            and self.allowed_node_roles is None
            and self.required_chains is None
            and self.max_active_branches is None
        )

    def n_checks(self) -> int:
        """Number of hard checks this precondition actually imposes."""
        return (
            int(self.min_level > 0)
            + int(self.allowed_node_roles is not None)
            + int(self.required_chains is not None)
            + int(self.max_active_branches is not None)
        )


class PostStateEffect(BaseModel):
    """Expected state transition after applying the motif."""

    model_config = ConfigDict(extra="forbid")

    branch_increment: int = Field(
        default=0,
        description="Net change in active branch count after expansion. "
        "Positive = branching (split), negative = convergence (merge).",
    )
    chain_transition: bool = Field(
        default=False,
        description="Whether the motif triggers a cross-chain state transition.",
    )
    target_chain: str | None = Field(
        default=None,
        description="Target chain after transition (recommended when "
        "chain_transition=True).",
    )
    next_recommended_roles: tuple[NodeRole, ...] = Field(
        default=(),
        description="Recommended node roles for the next agent action.",
    )

    @model_validator(mode="after")
    def _check_target_chain_consistency(self) -> "PostStateEffect":
        if not self.chain_transition and self.target_chain is not None:
            raise ValueError(
                "`target_chain` was provided but `chain_transition` is False."
            )
        return self


class MotifConstraints(BaseModel):
    """Constraint Layer: hard structural limits for DAG generation."""

    model_config = ConfigDict(extra="forbid")

    max_branching_factor: int = Field(
        default=4,
        ge=1,
        description="Maximum out-degree (branching factor) :math:`d_{max}` "
        "enforced inside the motif.",
    )
    min_level_bound: int = Field(
        default=2,
        ge=1,
        description="Global step interval lower bound :math:`L_{min}`.",
    )
    max_level_bound: int = Field(
        default=8,
        ge=1,
        description="Global step interval upper bound :math:`L_{max}`.",
    )
    require_acyclic: bool = Field(
        default=True,
        description="Whether the motif DAG must be acyclic (always True in "
        "production; exists for schema completeness).",
    )

    @model_validator(mode="after")
    def _check_step_interval(self) -> "MotifConstraints":
        if self.min_level_bound > self.max_level_bound:
            raise ValueError("min_level_bound must be <= max_level_bound.")
        return self


# ---------------------------------------------------------------------------
# Topological motif (Motif Subgraph Layer)
# ---------------------------------------------------------------------------
class TopologicalMotif(BaseModel):
    """Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.

    Structural invariants are validated at construction time:

    1. every edge endpoint references an existing ``temp_id``;
    2. ``temp_id`` values are unique and self-loops are forbidden;
    3. every edge advances strictly to a higher DAG level (guarantees a
       topological order, hence DAG-acyclicity is enforced by a Kahn check);
    4. no node out-degree exceeds ``constraints.max_branching_factor``.
    """

    model_config = ConfigDict(extra="forbid")

    motif_id: str = Field(min_length=1, description="Globally unique motif identifier.")
    pattern_type: PatternType
    description: str = Field(
        min_length=1,
        description="Human-readable abstract description (no micro numbers).",
    )
    preconditions: Preconditions = Field(default_factory=Preconditions)
    nodes: list[AbstractNode] = Field(min_length=1)
    edges: list[AbstractEdge] = Field(default_factory=list)
    post_state_effect: PostStateEffect = Field(default_factory=PostStateEffect)
    constraints: MotifConstraints = Field(default_factory=MotifConstraints)
    tags: tuple[str, ...] = Field(
        default=(),
        description="Optional semantic tags used by the dense retriever.",
    )

    # -- structural validation ----------------------------------------------
    @model_validator(mode="after")
    def _validate_topology(self) -> "TopologicalMotif":
        nodes = self.nodes
        edges = self.edges

        # 1) unique temp ids
        ids = [n.temp_id for n in nodes]
        dup = {i for i, c in Counter(ids).items() if c > 1}
        if dup:
            raise ValueError(f"Duplicate temp_id(s) in motif '{self.motif_id}': {sorted(dup)}")
        id_set = set(ids)

        # 2) endpoints exist & no self-loops
        for e in edges:
            if e.source not in id_set:
                raise ValueError(
                    f"Motif '{self.motif_id}': edge source '{e.source}' not in nodes."
                )
            if e.target not in id_set:
                raise ValueError(
                    f"Motif '{self.motif_id}': edge target '{e.target}' not in nodes."
                )
            if e.source == e.target:
                raise ValueError(
                    f"Motif '{self.motif_id}': self-loop on node '{e.source}'."
                )

        # 3) strict level progression
        level_of = {n.temp_id: n.level for n in nodes}
        for e in edges:
            if level_of[e.source] >= level_of[e.target]:
                raise ValueError(
                    f"Motif '{self.motif_id}': edge {e.source}->{e.target} does not "
                    f"advance DAG level ({level_of[e.source]} >= {level_of[e.target]})."
                )

        # 4) acyclicity (independent Kahn-style check, defence in depth)
        if self.constraints.require_acyclic and not self.is_dag():
            raise ValueError(f"Motif '{self.motif_id}': graph is not a DAG.")

        # 5) branching factor cap
        out_degree: Counter[str] = Counter(e.source for e in edges)
        for nid, deg in out_degree.items():
            if deg > self.constraints.max_branching_factor:
                raise ValueError(
                    f"Motif '{self.motif_id}': node '{nid}' out-degree {deg} exceeds "
                    f"max_branching_factor={self.constraints.max_branching_factor}."
                )

        # 6) motif-level flow conservation (relative priors must be physical)
        split_groups: dict[str, list[AbstractEdge]] = {}
        merge_groups: dict[str, list[AbstractEdge]] = {}
        for e in edges:
            if e.operation == OperationType.SPLIT:
                split_groups.setdefault(e.source, []).append(e)
            elif e.operation == OperationType.MERGE:
                merge_groups.setdefault(e.target, []).append(e)
        for nid, group in split_groups.items():
            total = sum(e.flow_share for e in group)
            if abs(total - 1.0) > FLOW_TOLERANCE:
                raise ValueError(
                    f"Motif '{self.motif_id}': Split out-edges of node '{nid}' "
                    f"violate flow conservation (sum={total:.4f}, tolerance "
                    f"{FLOW_TOLERANCE})."
                )
        for nid, group in merge_groups.items():
            total = sum(e.flow_share for e in group)
            if abs(total - 1.0) > FLOW_TOLERANCE:
                raise ValueError(
                    f"Motif '{self.motif_id}': Merge in-edges of node '{nid}' "
                    f"violate flow conservation (sum={total:.4f}, tolerance "
                    f"{FLOW_TOLERANCE})."
                )

        return self

    # -- topology helpers ----------------------------------------------------
    def is_dag(self) -> bool:
        """Return True iff the motif is acyclic (Kahn's algorithm)."""
        indeg: dict[str, int] = {n.temp_id: 0 for n in self.nodes}
        adj: dict[str, list[str]] = {n.temp_id: [] for n in self.nodes}
        for e in self.edges:
            adj[e.source].append(e.target)
            indeg[e.target] += 1
        queue = deque(nid for nid, d in indeg.items() if d == 0)
        visited = 0
        while queue:
            nid = queue.popleft()
            visited += 1
            for nxt in adj[nid]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        return visited == len(self.nodes)

    def topological_order(self) -> list[AbstractNode]:
        """Return nodes ordered by (level, temp_id) — an execution sequence."""
        return sorted(self.nodes, key=lambda n: (n.level, n.temp_id))

    def level_span(self) -> tuple[int, int]:
        """(min_level, max_level) occupied by this motif."""
        levels = [n.level for n in self.nodes]
        return (min(levels), max(levels))

    def max_level(self) -> int:
        return max(n.level for n in self.nodes)

    def semantic_text(self) -> str:
        """Flatten the motif into a dense text used for vector embedding."""
        role_tokens = " ".join(n.role.value for n in self.nodes)
        op_tokens = " ".join(e.operation.value for e in self.edges)
        parts: list[str] = [
            self.description,
            self.pattern_type.value,
            role_tokens,
            op_tokens,
            *self.tags,
        ]
        return " ".join(parts)

    def edge_signature_set(self) -> set[tuple[str, str, str]]:
        """Canonical (source-role, target-role, operation) signatures.

        Used by the prompt compressor to detect redundant paths *across*
        motifs (MOT-style merging): two edges from different motifs sharing
        the same role/operation signature are considered duplicated.
        """
        role_of = {n.temp_id: n.role.value for n in self.nodes}
        return {
            (role_of[e.source], role_of[e.target], e.operation.value)
            for e in self.edges
        }


# ---------------------------------------------------------------------------
# Runtime state & query context (Agent/Environment interface)
# ---------------------------------------------------------------------------
class CurrentState(BaseModel):
    """Current DAG state :math:`State_t` exported by the Stage-1 Environment."""

    model_config = ConfigDict(extra="forbid")

    current_level: int = Field(ge=0, description="Current global DAG level L.")
    current_chain: str = Field(min_length=1, description="Active chain label.")
    active_nodes: list[AbstractNode] = Field(
        default_factory=list,
        description="Frontier nodes awaiting expansion (role/chain/level only).",
    )
    graph_history: list[AbstractEdge] = Field(
        default_factory=list,
        description="Edges already committed to the behavioural graph G_b.",
    )

    @property
    def active_roles(self) -> set[NodeRole]:
        return {n.role for n in self.active_nodes}

    @property
    def active_branches(self) -> int:
        """Number of frontier nodes (branch-count proxy for the hard gate)."""
        return len(self.active_nodes)


class QueryContext(BaseModel):
    """Semantic side of a retrieval request (Stage-1 agent intent)."""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(min_length=1, description="High-level laundering scenario.")
    tactic_goal: str = Field(min_length=1, description="Immediate tactic goal.")
    target_pattern_type: PatternType | None = Field(
        default=None,
        description="Optional explicit tactic bias (e.g. user-specified pattern).",
    )

    @property
    def embedding_text(self) -> str:
        return f"{self.scenario}\n{self.tactic_goal}"


# ---------------------------------------------------------------------------
# Small utilities shared across the package
# ---------------------------------------------------------------------------
def iter_dag_edges_in_execution_order(motif: TopologicalMotif) -> Iterator[AbstractEdge]:
    """Yield motif edges sorted by (source.level, target.level, operation).

    This mirrors the execution sequence of the DAG and is reused by the
    context builder to keep prompts deterministic.
    """
    level_of = {n.temp_id: n.level for n in motif.nodes}
    for e in sorted(
        motif.edges,
        key=lambda e: (
            level_of[e.source],
            level_of[e.target],
            e.operation.value,
        ),
    ):
        yield e
