"""Scenario encapsulation for the Stage-1 planner agent.

:class:`ScenarioSpec` bundles everything a planning run needs: the high-level
laundering scenario (fed into the RAG ``QueryContext.scenario``), the fixed
tactic goal (``QueryContext.tactic_goal``), environment hyper-parameters and —
optionally — structural success criteria (:class:`ScenarioGoals`) used to
evaluate the generated graph.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aml_rag.schema import NodeRole, OperationType

__all__ = ["ScenarioGoals", "ScenarioSpec"]


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
    goals: ScenarioGoals | None = Field(
        default=None, description="Structural success criteria (None = "
        "environment termination alone counts as success)."
    )

    @model_validator(mode="after")
    def _check_bounds(self) -> "ScenarioSpec":
        if self.max_level < 1:
            raise ValueError("max_level must be >= 1")
        return self
