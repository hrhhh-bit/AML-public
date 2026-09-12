"""Tests for the Stage-1 planner agent (decision loop + trajectory audit).

Covers:
1. full successful trajectory driven by a scripted LLM;
2. reflection retry after a verifier refusal, then success;
3. retry exhaustion -> safe fallback terminate + failed flag;
4. strict reply parsing (fences / naked JSON / garbage);
5. structural goals success determination;
6. RAG prior visibility across steps;
7. planner prompt block structure.
"""

from __future__ import annotations

import json

import pytest

from aml_agent import (
    PlannerAgent,
    ScenarioGoals,
    ScenarioSpec,
    build_planner_prompt,
    parse_action_reply,
    strip_code_fences,
)
from aml_env import AgentAction, BehavioralEnvironment
from aml_rag import DualTrackMotifRetriever, build_default_knowledge_base
from aml_rag.schema import NodeRole, OperationType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class ScriptedLLM:
    """Deterministic LLM stub: pops replies in order, falls back to a default."""

    def __init__(self, replies: list[str], default: str = "not-json") -> None:
        self._replies = list(replies)
        self._default = default
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return self._replies.pop(0) if self._replies else self._default


def _json_action(
    op: str | None,
    parents: list[str],
    role: str | None = None,
    chain: str | None = None,
    **params: object,
) -> str:
    d: dict[str, object] = {"operation": op}
    if op is not None:
        d["parent_ids"] = parents
        d["target_role"] = role
        d["target_chain"] = chain
        if params:
            d["parameters"] = params
    return json.dumps(d)


FULL_SCRIPT = [
    _json_action("Transfer", ["node_0"], "Intermediate", "Chain_A"),
    _json_action("Split", ["node_1"], "Intermediate", "Chain_A", num_children=2),
    _json_action("Merge", ["node_2", "node_3"], "Aggregator", "Chain_A"),
    _json_action("Bridge", ["node_4"], "Cross_Chain", "Chain_B"),
    _json_action("Transfer", ["node_5"], "Target", "Chain_B"),
    _json_action(None, []),
]


def _setup(max_steps: int = 64, **env_kw: object) -> tuple[
    BehavioralEnvironment, DualTrackMotifRetriever, ScenarioSpec
]:
    env = BehavioralEnvironment(max_steps=max_steps, **env_kw)
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    spec = ScenarioSpec(
        name="unit-scenario",
        scenario="launder proceeds of a DeFi exploit",
        tactic_goal="layer, hop chains and integrate to a target",
        max_steps=max_steps,
        d_max=env.constraints.max_branching_factor,
        max_level=env.constraints.max_level_bound,
    )
    return env, retriever, spec


# ---------------------------------------------------------------------------
# 1. full successful trajectory
# ---------------------------------------------------------------------------
def test_scripted_llm_full_successful_trajectory() -> None:
    env, retriever, spec = _setup()
    llm = ScriptedLLM(FULL_SCRIPT)
    agent = PlannerAgent(env, retriever, llm)

    traj = agent.plan(spec)

    assert traj.terminated_by == "agent_terminate"
    assert traj.success is True
    assert traj.failed is False
    assert len(traj.steps) == 6
    assert traj.total_reward == 1.0  # only the terminate step rewards
    assert traj.total_llm_calls == 6
    assert traj.graph["meta"]["node_count"] == 7
    assert traj.graph["meta"]["edge_count"] == 7
    assert "flowchart LR" in traj.mermaid
    for step in traj.steps:
        assert step.prior_motif_ids, "RAG prior must be visible every step"
    # late-stage branching pressure empties the hard gate -> soft fallback
    assert any(step.prior_soft_fallback for step in traj.steps)


# ---------------------------------------------------------------------------
# 2. reflection retry after refusal
# ---------------------------------------------------------------------------
def test_retry_after_rejection_then_success() -> None:
    env, retriever, spec = _setup(max_steps=1)
    llm = ScriptedLLM(
        [
            _json_action("Transfer", ["node_0"], "Intermediate", "Chain_C"),  # illegal
            _json_action("Transfer", ["node_0"], "Intermediate", "Chain_A"),  # fixed
        ]
    )
    traj = PlannerAgent(env, retriever, llm).plan(spec)

    assert len(traj.steps) == 1
    step = traj.steps[0]
    assert len(step.retry_reasons) == 1
    assert "chain change not allowed" in step.retry_reasons[0]
    assert step.llm_calls == 2
    assert traj.terminated_by == "max_steps_reached"
    assert traj.success is True  # goals=None: termination alone counts


# ---------------------------------------------------------------------------
# 3. retry exhaustion -> safe fallback terminate
# ---------------------------------------------------------------------------
def test_retry_exhausted_terminates_safely_and_marks_failure() -> None:
    env, retriever, spec = _setup()
    llm = ScriptedLLM([], default="total garbage")  # never parses
    agent = PlannerAgent(env, retriever, llm, max_retries=3)

    traj = agent.plan(spec)

    assert traj.failed is True
    assert traj.success is False
    assert traj.terminated_by == "retry_exhausted_terminate"
    assert env.done is True
    assert len(traj.steps) == 1
    last = traj.steps[0]
    assert last.action.operation is None  # safe fallback terminate
    assert len(last.retry_reasons) == 4  # 1 initial + 3 retries
    assert last.llm_calls == 4
    assert all("unparseable reply" in r for r in last.retry_reasons)


# ---------------------------------------------------------------------------
# 4. strict reply parsing
# ---------------------------------------------------------------------------
def test_parse_action_reply_fenced_naked_and_garbage() -> None:
    payload = _json_action("Transfer", ["node_0"], "Intermediate", "Chain_A")

    fenced = f"```json\n{payload}\n```"
    action, err = parse_action_reply(fenced)
    assert action is not None and err is None
    assert action.operation == OperationType.TRANSFER
    assert action.target_role == NodeRole.INTERMEDIATE

    action, err = parse_action_reply(payload)  # naked JSON
    assert action is not None and err is None

    action, err = parse_action_reply("I am a helpful assistant, here you go: ...")
    assert action is None and err is not None

    action, err = parse_action_reply('{"operation": "Teleport"}')  # schema violation
    assert action is None and "schema violation" in (err or "")


def test_strip_code_fences_behaviour() -> None:
    assert strip_code_fences("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert strip_code_fences('prefix text {"a": 1} suffix') == '{"a": 1}'


# ---------------------------------------------------------------------------
# 5. structural goals evaluation
# ---------------------------------------------------------------------------
def test_goals_satisfied_trajectory_succeeds() -> None:
    env, retriever, spec = _setup()
    spec = spec.model_copy(
        update={
            "goals": ScenarioGoals(
                min_level=4,
                required_roles=(NodeRole.TARGET,),
                required_operations=(OperationType.BRIDGE,),
            )
        }
    )
    traj = PlannerAgent(env, retriever, ScriptedLLM(FULL_SCRIPT)).plan(spec)

    assert traj.success is True
    assert traj.unmet_goals == ()


def test_early_terminate_with_unmet_goals_fails_softly() -> None:
    env, retriever, spec = _setup()
    spec = spec.model_copy(
        update={"goals": ScenarioGoals(min_level=3, required_roles=(NodeRole.TARGET,))}
    )
    llm = ScriptedLLM([_json_action(None, [])])  # terminate immediately
    traj = PlannerAgent(env, retriever, llm).plan(spec)

    assert traj.terminated_by == "agent_terminate"
    assert traj.failed is False
    assert traj.success is False
    assert any("max_level" in reason for reason in traj.unmet_goals)
    assert any("Target" in reason for reason in traj.unmet_goals)


# ---------------------------------------------------------------------------
# 6. RAG prior visibility
# ---------------------------------------------------------------------------
def test_rag_prior_motifs_change_with_state() -> None:
    env, retriever, spec = _setup()
    traj = PlannerAgent(env, retriever, ScriptedLLM(FULL_SCRIPT)).plan(spec)

    cold = set(traj.steps[0].prior_motif_ids)
    assert cold == {"Peeling_Chain_Single_Chain", "DEX_Liquidity_Pool_Swap"}
    assert set(traj.steps[1].prior_motif_ids) != cold


# ---------------------------------------------------------------------------
# 7. prompt structure & guards
# ---------------------------------------------------------------------------
def test_build_planner_prompt_contains_required_blocks() -> None:
    env, retriever, spec = _setup()
    state = env.reset()
    prompt = build_planner_prompt(spec, state, "prior-block")

    for tag in ("<SCENARIO>", "<CURRENT_STATE>", "<RAG_PRIOR>",
                "<OUTPUT_FORMAT>", "<ENV_BOUNDS>"):
        assert tag in prompt
    assert "PREVIOUS_MISTAKE" not in prompt
    assert "prior-block" in prompt

    retry_prompt = build_planner_prompt(
        spec, state, "prior-block", retry_error="chain change not allowed"
    )
    assert "<PREVIOUS_MISTAKE>" in retry_prompt
    assert "chain change not allowed" in retry_prompt


def test_planner_requires_llm() -> None:
    env, retriever, spec = _setup()
    agent = PlannerAgent(env, retriever, llm=None)
    with pytest.raises(RuntimeError):
        agent.plan(spec)
