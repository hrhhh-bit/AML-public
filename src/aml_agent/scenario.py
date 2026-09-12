"""Scenario encapsulation for the Stage-1 planner agent.

:class:`ScenarioSpec` bundles everything a planning run needs: the high-level
laundering scenario (fed into the RAG ``QueryContext.scenario``), the fixed
tactic goal (``QueryContext.tactic_goal``), environment hyper-parameters and —
optionally — structural success criteria (:class:`ScenarioGoals`) used to
evaluate the generated graph.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aml_rag.schema import NodeRole, OperationType

__all__ = ["ScaleTier", "ScenarioGoals", "ScenarioSpec"]


class ScaleTier(str, Enum):
    """Macro fund-volume tier guiding intended topology complexity.

    Stage-1 uses this ONLY as an intent hint (chain length, branching,
    cross-chain hops). It never participates in any balance arithmetic —
    that belongs to Stage-2.
    """

    RETAIL = "Retail"
    MEDIUM = "Medium"
    WHALE = "Whale"
    STATE_SPONSORED = "State_Sponsored"

    def complexity_guidance(self) -> str:
        """Natural-language complexity hint injected into planner prompts."""
        return {
            ScaleTier.RETAIL: (
                "small retail-scale funds: keep the topology short and simple "
                "(short linear chains, low branching, no cross-chain hops)"
            ),
            ScaleTier.MEDIUM: (
                "medium-scale funds: moderate layering (a few splits and "
                "merges, at most one cross-chain hop)"
            ),
            ScaleTier.WHALE: (
                "whale-scale funds: deep obfuscation (multiple split/merge "
                "cycles, multi-chain hopping through aggregators)"
            ),
            ScaleTier.STATE_SPONSORED: (
                "state-sponsored scale: maximal layering (very deep chains, "
                "heavy cross-chain hopping, nested split-merge structures)"
            ),
        }[self]


class ScenarioGoals(BaseModel):
    """Structural success criteria evaluated against the finished graph.

    All non-null fields must be satisfied for the trajectory to count as a
    success. ``None`` = no requirement.
    """

    model_config = ConfigDict(extra="forbid")

    min_level: int | None = Field(
        default=None, ge=1, description="Graph must reach at least this DAG level."
    )
    required_roles: tuple[NodeRole, ...] = Field(
        default=(), description="Node roles that must appear in the graph."
    )
    required_operations: tuple[OperationType, ...] = Field(
        default=(), description="Edge operations that must appear in the graph."
    )

    def unmet_reasons(
        self, *, max_level: int, roles: set[str], operations: set[str]
    ) -> list[str]:
        """Human-readable list of unsatisfied goals (empty = all satisfied)."""
        reasons: list[str] = []
        if self.min_level is not None and max_level < self.min_level:
            reasons.append(f"max_level {max_level} < required {self.min_level}")
        missing_roles = {r.value for r in self.required_roles} - roles
        if missing_roles:
            reasons.append(f"missing roles: {sorted(missing_roles)}")
        missing_ops = {o.value for o in self.required_operations} - operations
        if missing_ops:
            reasons.append(f"missing operations: {sorted(missing_ops)}")
        return reasons


class ScenarioSpec(BaseModel):
    """Full task description for one planning run."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    scenario: str = Field(
        min_length=1, description="High-level laundering scenario description."
    )
    tactic_goal: str = Field(
        min_length=1, description="Fixed tactic goal (v1: constant per run)."
    )
    seed_chain: str = "Chain_A"
    initial_role: NodeRole = NodeRole.SOURCE
    d_max: int = Field(default=4, ge=1, description="Branching factor cap.")
    max_level: int = Field(default=8, ge=1, description="DAG depth cap L_max.")
    max_steps: int = Field(
        default=64,
        ge=1,
        description="Environment-level trajectory length cap (the PRIMARY "
        "limit; the planner itself does not add a separate cap).",
    )
    scale_tier: ScaleTier = Field(
        default=ScaleTier.MEDIUM,
        description="Macro fund-volume tier: intent hint for topology "
        "complexity only; never used in balance arithmetic.",
    )
    estimated_value_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Optional macro baseline valuation (USD). Static metadata "
        "passed through to Stage-2; MUST NOT take part in any Stage-1 "
        "balance calculation or deduction.",
    )
    goals: ScenarioGoals | None = Field(
        default=None, description="Structural success criteria (None = "
        "environment termination alone counts as success)."
    )

    @model_validator(mode="after")
    def _check_bounds(self) -> "ScenarioSpec":
        if self.max_level < 1:
            raise ValueError("max_level must be >= 1")
        return self
