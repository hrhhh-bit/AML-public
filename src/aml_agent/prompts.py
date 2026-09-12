"""Planner prompt templates for the Stage-1 decision agent.

Renders one planning prompt per decision round from:

- the scenario (fixed per run, v1);
- the current :class:`aml_rag.schema.CurrentState` snapshot;
- the compressed RAG prior block produced by
  :class:`aml_rag.context_builder.PromptContextCompressor`;
- optionally, the refusal reason of the previous attempt (retry loop).

Zero-shot by design: the rules section replaces few-shot examples, keeping
prompt length controllable.
"""

from __future__ import annotations

import json

from aml_env import AgentAction
from aml_rag.schema import CurrentState

from .scenario import ScenarioSpec

__all__ = ["PLANNER_SYSTEM_PROMPT", "build_planner_prompt"]

PLANNER_SYSTEM_PROMPT: str = """\
You are the Stage-1 planning agent of a Cross-Chain AML Behavioural Graph
Generation framework. You iteratively extend an abstract money-laundering
behavioural graph G_b that MUST remain a DAG. Follow the rules below exactly.

## Abstract action space
- "Transfer": extend ONE frontier node by one child on the SAME chain.
- "Swap": extend ONE frontier node by one Asset_Conversion child on the SAME chain.
- "Bridge": extend ONE frontier node by one child on a DIFFERENT chain
  (the ONLY action allowed to change chain).
- "Split": extend ONE frontier node into N children on the SAME chain, with
  parameters {"num_children": N}, 2 <= N <= d_max.
- "Merge": combine >= 2 frontier nodes into one child; the parents MUST share
  the same chain AND the same level; child stays on that same chain.
- Terminate: {"operation": null} — no parent_ids / target fields needed.

## Hard constraints (violations are rejected and reported back to you)
- parent_ids must all exist in the CURRENT STATE's active_nodes.
- new node level = max(parent levels) + 1 and must not exceed L_max.
- every node's out-degree must not exceed d_max (saturated nodes leave the
  active frontier automatically).
- only Bridge may change chain.

## Flow conservation (branching / merging actions)
- For Split you MUST provide parameters {"flow_shares": [...]} with exactly
  one normalised share per child; shares must be in (0, 1] and sum to 1.0
  (tolerance 0.01). The environment rejects non-conserving shares.
- Prefer the archetype ratios shown in the RAG prior (edge 4th element /
  Mermaid labels). NEVER invent meaningless complex decimals — when in doubt
  split equally.
- Merge may also carry flow_shares; same normalisation rule applies if given.

## Scale tier guidance
- The <ENV_BOUNDS> section states the current macro fund-volume tier.
  Use it only to shape topology complexity (chain length, branching,
  cross-chain hops). Never perform balance arithmetic — amounts belong to a
  downstream stage.

## Termination guidance
- Output {"operation": null} once the scenario goal is reached, or when all
  active frontier nodes are Target sinks.
- The environment may also stop automatically (max level / max steps).

## Purity rule
- NEVER output wallet addresses, exact amounts, gas fees or timestamps.
- Only abstract roles, chains, levels and operations.
"""


def _state_json(state: CurrentState) -> str:
    """Compact state rendering (MOT-style triplets for history edges)."""
    return json.dumps(
        {
            "current_level": state.current_level,
            "current_chain": state.current_chain,
            "active_nodes": [
                {
                    "id": n.temp_id,
                    "role": n.role.value,
                    "chain": n.chain,
                    "lvl": n.level,
                }
                for n in state.active_nodes
            ],
            "history_edges": [
                [e.source, e.target, e.operation.value] for e in state.graph_history
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _goals_text(spec: ScenarioSpec) -> str:
    goals = spec.goals
    if goals is None:
        return (
            "No explicit structural goals. Terminate when the graph is "
            "complete (e.g. all frontier nodes are Target sinks)."
        )
    parts: list[str] = []
    if goals.min_level is not None:
        parts.append(f"reach at least DAG level {goals.min_level}")
    if goals.required_roles:
        parts.append(
            "include roles: " + ", ".join(r.value for r in goals.required_roles)
        )
    if goals.required_operations:
        parts.append(
            "include operations: "
            + ", ".join(o.value for o in goals.required_operations)
        )
    return "Structural goals: " + "; ".join(parts) + "."


def build_planner_prompt(
    spec: ScenarioSpec,
    state: CurrentState,
    prior_prompt: str,
    *,
    retry_error: str | None = None,
) -> str:
    """Render one full planning prompt.

    Args:
        spec: the scenario (rules, goals, environment bounds).
        state: current environment snapshot.
        prior_prompt: compressed RAG prior block (may be empty).
        retry_error: refusal/parse reason of the previous attempt, if any.
    """
    action_schema = json.dumps(
        AgentAction.model_json_schema(), ensure_ascii=False, separators=(",", ":")
    )
    blocks: list[str] = [
        PLANNER_SYSTEM_PROMPT,
        "",
        f"<SCENARIO> {spec.scenario}",
        f"<TACTIC_GOAL> {spec.tactic_goal}",
        f"<GOALS> {_goals_text(spec)}",
        f"<SCALE_TIER> {spec.scale_tier.value}: "
        f"{spec.scale_tier.complexity_guidance()}",
        f"<ENV_BOUNDS> d_max={spec.d_max}, L_max={spec.max_level}, "
        f"max_steps={spec.max_steps}, seed_chain={spec.seed_chain}",
        "",
        "<CURRENT_STATE>",
        _state_json(state),
        "</CURRENT_STATE>",
        "",
        "<RAG_PRIOR>",
        prior_prompt.strip() or "(no prior motifs available)",
        "</RAG_PRIOR>",
    ]
    if retry_error:
        blocks.extend(
            [
                "",
                "<PREVIOUS_MISTAKE>",
                f"Your last action was rejected for: {retry_error}",
                "Fix the violation and output a corrected action JSON.",
                "</PREVIOUS_MISTAKE>",
            ]
        )
    blocks.extend(
        [
            "",
            "<OUTPUT_FORMAT>",
            "Reply with exactly ONE JSON object matching this schema, and "
            "nothing else (no markdown fences, no prose):",
            action_schema,
            "</OUTPUT_FORMAT>",
        ]
    )
    return "\n".join(blocks)
