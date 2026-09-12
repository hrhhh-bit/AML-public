"""Stage-1 planner agent: the decision loop between RAG prior and environment.

:class:`PlannerAgent` closes the loop already defined by ``aml_rag`` and
``aml_env``:

    perceive (env snapshot) -> retrieve prior (dual-track RAG) -> compress
    (prompt builder) -> plan (LLM -> AgentAction) -> act (env.step) ->
    reflect (refusal feedback, bounded retries) -> record (Trajectory).

Design decisions (agreed):

- LLM injected as ``Callable[[str], str]`` (same style as the extractor);
- fixed ``tactic_goal`` per run (v1);
- strict Pydantic parsing of the reply; failures are fed back for retry
  (no magical repair);
- at most ``1 + max_retries`` attempts per step; on exhaustion the planner
  emits a safe terminate and marks the trajectory as failed;
- the environment's ``max_steps`` is the PRIMARY trajectory-length limit —
  the planner adds no separate cap;
- the unified :class:`Planner` protocol is defined here so future baselines
  (e.g. a rule-based planner) can be plugged in for ablation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aml_env import AgentAction, BehavioralEnvironment, StepResult
from aml_rag import PromptContextCompressor, QueryContext
from aml_rag.retriever import DualTrackMotifRetriever

from .prompts import build_planner_prompt
from .scenario import ScenarioSpec

__all__ = [
    "LLMCallable",
    "Planner",
    "TrajectoryStep",
    "Trajectory",
    "PlannerAgent",
    "strip_code_fences",
    "parse_action_reply",
]

LLMCallable = Callable[[str], str]

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


# ---------------------------------------------------------------------------
# Reply parsing (local implementation — aml_rag public API stays untouched)
# ---------------------------------------------------------------------------
def strip_code_fences(raw: str) -> str:
    """Remove markdown fences and keep the largest JSON-looking chunk."""
    text = raw.strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    ends = [text.rfind("]"), text.rfind("}")]
    if starts and ends and max(ends) > min(starts):
        return text[min(starts) : max(ends) + 1]
    return text


def parse_action_reply(raw: str) -> tuple[AgentAction | None, str | None]:
    """Strictly parse an LLM reply into an AgentAction.

    Returns ``(action, error)``: ``action`` is None on failure and ``error``
    carries a human-readable reason for the retry feedback loop.
    """
    cleaned = strip_code_fences(raw)
    try:
        payload: Any = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON ({exc.msg} at line {exc.lineno})"
    try:
        return AgentAction.model_validate(payload), None
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", ()))
        return None, f"schema violation at '{loc or '?'}': {first.get('msg', '')}"


# ---------------------------------------------------------------------------
# Trajectory records (ablation-grade audit data)
# ---------------------------------------------------------------------------
class TrajectoryStep(BaseModel):
    """One executed planning step with full audit trail."""

    model_config = ConfigDict(extra="forbid")

    step_index: int
    action: AgentAction
    result: StepResult
    prior_motif_ids: tuple[str, ...] = Field(
        default=(), description="Motifs injected by the RAG prior this step."
    )
    prior_scores: tuple[float, ...] = Field(
        default=(), description="Combined scores aligned with prior_motif_ids."
    )
    retry_reasons: tuple[str, ...] = Field(
        default=(), description="Refusal/parse reasons of failed attempts."
    )
    prior_soft_fallback: bool = Field(
        default=False,
        description="True when the hard gate admitted no motif and retrieval "
        "fell back to soft (strict=False) scoring for the prior guarantee.",
    )
    llm_calls: int = Field(default=1, ge=1)


class Trajectory(BaseModel):
    """Complete outcome of one planning run."""

    model_config = ConfigDict(extra="forbid")

    scenario_name: str
    steps: list[TrajectoryStep] = Field(default_factory=list)
    terminated_by: str | None = None
    success: bool = False
    failed: bool = Field(
        default=False, description="True when retries were exhausted."
    )
    unmet_goals: tuple[str, ...] = Field(default=())
    total_reward: float = 0.0
    total_llm_calls: int = 0
    graph: dict[str, Any] = Field(default_factory=dict)
    mermaid: str = ""


class Planner(Protocol):
    """Unified planning protocol for ablation baselines."""

    def plan(self, spec: ScenarioSpec) -> Trajectory: ...


# ---------------------------------------------------------------------------
# Planner agent
# ---------------------------------------------------------------------------
class PlannerAgent:
    """RAG-enhanced LLM planning loop over :class:`BehavioralEnvironment`."""

    def __init__(
        self,
        environment: BehavioralEnvironment,
        retriever: DualTrackMotifRetriever,
        llm: LLMCallable | None = None,
        *,
        compressor: PromptContextCompressor | None = None,
        top_k: int = 3,
        max_retries: int = 3,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._environment = environment
        self._retriever = retriever
        self._llm = llm
        self._compressor = compressor or PromptContextCompressor()
        self._top_k = top_k
        self._max_retries = max_retries

    # ---------------------------------------------------------------- plan
    def plan(self, spec: ScenarioSpec) -> Trajectory:
        """Run one full planning episode; returns the audit-ready trajectory."""
        if self._llm is None:
            raise RuntimeError(
                "No LLM callable configured. Inject one via "
                "PlannerAgent(llm=...) before calling plan()."
            )
        env = self._environment
        env.reset()

        steps: list[TrajectoryStep] = []
        total_llm_calls = 0
        terminated_by: str | None = None
        failed = False

        while not env.done:
            state = env.snapshot()
            query = QueryContext(
                scenario=spec.scenario, tactic_goal=spec.tactic_goal
            )
            results = self._retriever.retrieve(state, query, top_k=self._top_k)
            soft_fallback = False
            if not results:
                # prior guarantee: hard gate admits nothing (e.g. high
                # branching pressure) -> soft retrieval with rule scores
                results = self._retriever.retrieve(
                    state, query, top_k=self._top_k, strict=False
                )
                soft_fallback = True
            prior = self._compressor.build_agent_prompt(state, query, results)

            retry_reasons: list[str] = []
            llm_calls = 0
            final_action: AgentAction | None = None
            final_result: StepResult | None = None

            for _attempt in range(1 + self._max_retries):
                prompt = build_planner_prompt(
                    spec,
                    state,
                    prior,
                    retry_error=retry_reasons[-1] if retry_reasons else None,
                )
                llm_calls += 1
                action, parse_error = parse_action_reply(self._llm(prompt))
                if action is None:
                    retry_reasons.append(f"unparseable reply: {parse_error}")
                    continue
                result = env.step(action)
                if not result.info.get("accepted") and not result.done:
                    retry_reasons.append(str(result.info.get("error", "rejected")))
                    continue
                final_action, final_result = action, result
                break

            total_llm_calls += llm_calls
            prior_ids = tuple(r.motif_id for r in results)
            prior_scores = tuple(round(r.combined_score, 4) for r in results)

            if final_result is None:
                # retries exhausted -> safe fallback terminate
                fallback = env.step(AgentAction(operation=None))
                steps.append(
                    TrajectoryStep(
                        step_index=len(steps),
                        action=AgentAction(operation=None),
                        result=fallback,
                        prior_motif_ids=prior_ids,
                        prior_scores=prior_scores,
                        retry_reasons=tuple(retry_reasons),
                        prior_soft_fallback=soft_fallback,
                        llm_calls=llm_calls,
                    )
                )
                failed = True
                terminated_by = "retry_exhausted_terminate"
                break

            steps.append(
                TrajectoryStep(
                    step_index=len(steps),
                    action=final_action,
                    result=final_result,
                    prior_motif_ids=prior_ids,
                    prior_scores=prior_scores,
                    retry_reasons=tuple(retry_reasons),
                    prior_soft_fallback=soft_fallback,
                    llm_calls=llm_calls,
                )
            )
            if final_result.done:
                terminated_by = final_result.info.get("terminated_by")
                break

        terminated_by = terminated_by or env.termination_reason
        success, unmet = self._evaluate_success(spec, terminated_by, failed)

        return Trajectory(
            scenario_name=spec.name,
            steps=steps,
            terminated_by=terminated_by,
            success=success,
            failed=failed,
            unmet_goals=tuple(unmet),
            total_reward=round(sum(s.result.reward for s in steps), 4),
            total_llm_calls=total_llm_calls,
            graph=env.export_behavioral_graph(),
            mermaid=env.render_mermaid(),
        )

    # ------------------------------------------------------------- evaluate
    def _evaluate_success(
        self, spec: ScenarioSpec, terminated_by: str | None, failed: bool
    ) -> tuple[bool, list[str]]:
        if failed:
            return False, ["planner failed: retries exhausted"]
        if terminated_by is None:
            return False, ["trajectory did not terminate"]
        if spec.goals is None:
            return True, []
        export = self._environment.export_behavioral_graph()
        unmet = spec.goals.unmet_reasons(
            max_level=export["meta"]["max_level"],
            roles={n["role"] for n in export["nodes"]},
            operations={e["operation"] for e in export["edges"]},
        )
        return (not unmet), unmet

    # ------------------------------------------------------------ properties
    @property
    def llm(self) -> LLMCallable | None:
        return self._llm

    @llm.setter
    def llm(self, fn: LLMCallable | None) -> None:
        self._llm = fn
