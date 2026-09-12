"""aml_agent — Stage-1 RAG-enhanced planner agent.

Decision layer that closes the loop between the prior knowledge engine
(:mod:`aml_rag`) and the behavioural graph environment (:mod:`aml_env`):

- :class:`ScenarioSpec` / :class:`ScenarioGoals`: task encapsulation;
- :mod:`aml_agent.prompts`: zero-shot planning prompt templates;
- :class:`PlannerAgent`: perceive -> retrieve -> plan -> act -> reflect loop
  with bounded retries and audit-ready :class:`Trajectory` records;
- :class:`Planner`: unified protocol for future ablation baselines.
"""

from __future__ import annotations

from .planner import (
    LLMCallable,
    Planner,
    PlannerAgent,
    Trajectory,
    TrajectoryStep,
    parse_action_reply,
    strip_code_fences,
)
from .prompts import PLANNER_SYSTEM_PROMPT, build_planner_prompt
from .scenario import ScenarioGoals, ScenarioSpec

__version__ = "0.1.0"

__all__ = [
    "ScenarioSpec",
    "ScenarioGoals",
    "Planner",
    "PlannerAgent",
    "Trajectory",
    "TrajectoryStep",
    "LLMCallable",
    "build_planner_prompt",
    "PLANNER_SYSTEM_PROMPT",
    "parse_action_reply",
    "strip_code_fences",
    "__version__",
]
