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
from aml_rag.retriever import DualTrackMotifRetriever, RetrievalResult
from aml_rag.schema import OperationType

from .narrative import build_strategy_narrative
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

#: Strips any ```lang ... ``` fence (json, python, plain, ...).
_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*(.*?)\s*```", re.DOTALL)
#: Removes trailing commas before a closing brace/bracket (LLM format noise).
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


# ---------------------------------------------------------------------------
# Reply parsing (local implementation — aml_rag public API stays untouched)
# ---------------------------------------------------------------------------
def _strip_all_fences(text: str) -> str:
    """Repeatedly remove markdown code fences until stable."""
    prev: str | None = None
    while prev != text:
        prev = text
        text = _FENCE_RE.sub(r"\1", text)
    return text.strip()


def _extract_outermost_json(text: str) -> str:
    """Extract the outermost JSON object/array via bracket-stack matching.

    Robust against chain-of-thought preambles and trailing prose: only the
    balanced top-level ``{...}`` (or ``[...]``) block is kept.
    """
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escaped = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            return text[start : end + 1]
    return text  # no balanced block found; let json.loads produce the error


def strip_code_fences(raw: str) -> str:
    """Remove markdown fences / prose and keep the outermost JSON chunk."""
    return _extract_outermost_json(_strip_all_fences(raw))


def _load_json(text: str) -> tuple[Any | None, str | None]:
    """Load JSON with a trailing-comma repair fallback.

    Returns ``(payload, error)`` — ``error`` is a standardised, human-readable
    syntax message for the reflection loop.
    """
    try:
        return json.loads(text), None
    except json.JSONDecodeError as first_exc:
        repaired = _TRAILING_COMMA_RE.sub(r"\1", text)
        try:
            return json.loads(repaired), None
        except json.JSONDecodeError as second_exc:
            return None, (
                f"invalid JSON after cleanup: {second_exc.msg} at "
                f"line {second_exc.lineno} col {second_exc.colno}"
            )


def parse_action_reply(raw: str) -> tuple[AgentAction | None, str | None]:
    """Robustly parse an LLM reply into an AgentAction.

    Tolerates markdown fences, chain-of-thought preamble/postamble, trailing
    commas and a single-element JSON array wrapper.  Returns
    ``(action, error)``: ``action`` is None on failure and ``error`` carries a
    standardised reason for the retry feedback loop.
    """
    cleaned = strip_code_fences(raw)
    payload, json_error = _load_json(cleaned)
    if json_error is not None:
        return None, json_error
    if isinstance(payload, list):
        if not payload:
            return None, "reply contained an empty JSON array"
        payload = payload[0]
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
    strategy_narrative: str = Field(
        default="",
        description="Structure-derived strategy statement (template-mapped "
        "from the executed trajectory; never free-form LLM text).",
    )
    total_reward: float = 0.0
    total_llm_calls: int = 0
    llm_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Aggregated LLM telemetry (tokens / latency) captured "
        "from the LLM callable, when it exposes a metrics snapshot.",
    )
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
        step_callback: Callable[[TrajectoryStep], None] | None = None,
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
        self._step_callback = step_callback

    def _notify_step(self, step: TrajectoryStep) -> None:
        """Invoke the optional per-step callback (live logging / telemetry)."""
        if self._step_callback is not None:
            self._step_callback(step)

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
                # flow-share defaults: motif archetype first, else equal split
                action = self._enrich_flow_shares(action, results)
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
                step_obj = TrajectoryStep(
                    step_index=len(steps),
                    action=AgentAction(operation=None),
                    result=fallback,
                    prior_motif_ids=prior_ids,
                    prior_scores=prior_scores,
                    retry_reasons=tuple(retry_reasons),
                    prior_soft_fallback=soft_fallback,
                    llm_calls=llm_calls,
                )
                steps.append(step_obj)
                self._notify_step(step_obj)
                failed = True
                terminated_by = "retry_exhausted_terminate"
                break

            step_obj = TrajectoryStep(
                step_index=len(steps),
                action=final_action,
                result=final_result,
                prior_motif_ids=prior_ids,
                prior_scores=prior_scores,
                retry_reasons=tuple(retry_reasons),
                prior_soft_fallback=soft_fallback,
                llm_calls=llm_calls,
            )
            steps.append(step_obj)
            self._notify_step(step_obj)
            if final_result.done:
                terminated_by = final_result.info.get("terminated_by")
                break

        terminated_by = terminated_by or env.termination_reason
        success, unmet = self._evaluate_success(spec, terminated_by, failed)

        graph = env.export_behavioral_graph()
        graph["meta"]["scale_tier"] = spec.scale_tier.value
        if spec.estimated_value_usd is not None:
            graph["meta"]["estimated_value_usd"] = spec.estimated_value_usd

        # optional LLM telemetry (duck-typed: the callable may expose metrics)
        llm_metrics: dict[str, Any] = {}
        metrics_obj = getattr(self._llm, "metrics", None)
        snapshot_fn = getattr(metrics_obj, "snapshot", None)
        if callable(snapshot_fn):
            llm_metrics = snapshot_fn()

        trajectory = Trajectory(
            scenario_name=spec.name,
            steps=steps,
            terminated_by=terminated_by,
            success=success,
            failed=failed,
            unmet_goals=tuple(unmet),
            total_reward=round(sum(s.result.reward for s in steps), 4),
            total_llm_calls=total_llm_calls,
            llm_metrics=llm_metrics,
            graph=graph,
            mermaid=env.render_mermaid(),
        )
        # structure-derived narrative persisted both on the trajectory and
        # inside the exported graph metadata (Stage-2 consumer)
        narrative = build_strategy_narrative(trajectory)
        trajectory.strategy_narrative = narrative
        trajectory.graph["meta"]["strategy_narrative"] = narrative
        return trajectory

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

    # ------------------------------------------------- flow-share defaults
    @staticmethod
    def _split_prototype(
        results: list["RetrievalResult"], num_children: int
    ) -> list[float] | None:
        """Extract a Split flow-share archetype from the RAG prior.

        Returns the shares of the first motif whose Split out-edge group has
        exactly ``num_children`` entries; None when no prototype matches.
        """
        for result in results:
            groups: dict[str, list[float]] = {}
            for edge in result.motif.edges:
                if edge.operation == OperationType.SPLIT:
                    groups.setdefault(edge.source, []).append(edge.flow_share)
            for shares in groups.values():
                if len(shares) == num_children:
                    return [float(s) for s in shares]
        return None

    @staticmethod
    def _enrich_flow_shares(
        action: AgentAction, results: list["RetrievalResult"]
    ) -> AgentAction:
        """Backfill missing flow shares: motif archetype first, equal split last.

        Guarantees edge attributes are never empty while never overriding an
        agent-provided (and verifier-checked) ratio set.
        """
        if action.operation is None or "flow_shares" in action.parameters:
            return action
        if action.operation == OperationType.SPLIT:
            num_children = int(action.parameters.get("num_children", 2))
            prototype = PlannerAgent._split_prototype(results, num_children)
            action.parameters["flow_shares"] = (
                prototype if prototype is not None
                else [1.0 / num_children] * num_children
            )
        return action

    # ------------------------------------------------------------ properties
    @property
    def llm(self) -> LLMCallable | None:
        return self._llm

    @llm.setter
    def llm(self, fn: LLMCallable | None) -> None:
        self._llm = fn
