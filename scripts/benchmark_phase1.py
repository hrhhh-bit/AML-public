"""Stage-1 small-scale baseline benchmark over 3 scenarios.

Runs N trajectories per scenario (default 3) against a real LLM and prints a
summary report with the plan's acceptance metrics:

- success rate (success=True share);
- flow-conservation first-try compliance vs. post-reflection recovery rate;
- average steps and average retries per step (acceptance line < 0.5);
- average prompt/completion tokens and per-step latency.

Usage:
    python scripts/benchmark_phase1.py [--runs 3] [--model deepseek-flash]
                                       [--out report.json]

Environment:
    DEEPSEEK_API_KEY  (or OPENAI_API_KEY) — required
    DEEPSEEK_BASE_URL — optional
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aml_agent import (  # noqa: E402
    LLMClient,
    PlannerAgent,
    ScaleTier,
    ScenarioGoals,
    ScenarioSpec,
    Trajectory,
)
from aml_env import BehavioralEnvironment  # noqa: E402
from aml_rag import DualTrackMotifRetriever, build_default_knowledge_base  # noqa: E402
from aml_rag.schema import NodeRole, OperationType  # noqa: E402


SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "retail_single_chain",
        "scenario": (
            "A retail-scale actor disperses modest proceeds across a handful of "
            "fresh intermediate wallets on one chain before cashing out."
        ),
        "tactic_goal": "disperse then consolidate on a single chain",
        "scale_tier": ScaleTier.RETAIL,
        "estimated_value_usd": 15_000.0,
        "goals": ScenarioGoals(min_level=3, required_roles=(NodeRole.TARGET,)),
    },
    {
        "name": "whale_cross_chain_mixing",
        "scenario": (
            "A whale-scale operator moves large proceeds through a mixer, splits "
            "them across chains and reintegrates before final cash-out."
        ),
        "tactic_goal": "mix, split, hop chains and integrate to a target",
        "scale_tier": ScaleTier.WHALE,
        "estimated_value_usd": 2_000_000.0,
        "goals": ScenarioGoals(
            min_level=5,
            required_roles=(NodeRole.TARGET, NodeRole.AGGREGATOR),
            required_operations=(OperationType.BRIDGE,),
        ),
    },
    {
        "name": "medium_peeling_split",
        "scenario": (
            "A medium-scale actor peels funds linearly then fans them out into "
            "several parallel streams before a final merge to the target."
        ),
        "tactic_goal": "peel, fan out and merge to a target",
        "scale_tier": ScaleTier.MEDIUM,
        "estimated_value_usd": 250_000.0,
        "goals": ScenarioGoals(
            min_level=3,
            required_roles=(NodeRole.TARGET,),
            required_operations=(OperationType.SPLIT,),
        ),
    },
]


def _run_one(scenario: dict[str, Any], client_kwargs: dict[str, Any]) -> Trajectory:
    client = LLMClient(**client_kwargs)
    env = BehavioralEnvironment()
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    spec = ScenarioSpec(
        name=scenario["name"],
        scenario=scenario["scenario"],
        tactic_goal=scenario["tactic_goal"],
        scale_tier=scenario["scale_tier"],
        estimated_value_usd=scenario["estimated_value_usd"],
        goals=scenario["goals"],
        max_steps=24,
    )
    return PlannerAgent(env, retriever, client, top_k=3, max_retries=3).plan(spec)


def _summarise(name: str, trajs: list[Trajectory]) -> dict[str, Any]:
    n = len(trajs)
    success = sum(1 for t in trajs if t.success)
    total_steps = sum(len(t.steps) for t in trajs)
    total_retries = sum(
        len(reason) for t in trajs for s in t.steps for reason in s.retry_reasons
    )

    # conservation-specific statistics
    violations = 0
    recovered = 0
    for t in trajs:
        for s in t.steps:
            cons_reasons = [r for r in s.retry_reasons if "flow conservation" in r]
            if cons_reasons:
                violations += 1
                if s.result.info.get("accepted"):
                    recovered += 1
    first_try_steps = sum(
        1 for t in trajs for s in t.steps if not s.retry_reasons
    )

    prompt_tokens = sum(t.llm_metrics.get("prompt_tokens", 0) for t in trajs)
    completion_tokens = sum(t.llm_metrics.get("completion_tokens", 0) for t in trajs)
    total_latency = sum(t.llm_metrics.get("total_latency_ms", 0.0) for t in trajs)
    total_calls = sum(t.llm_metrics.get("total_calls", 0) for t in trajs)

    return {
        "scenario": name,
        "runs": n,
        "success_rate": round(success / n, 4),
        "conservation_first_try_compliance": round(
            first_try_steps / total_steps, 4
        ) if total_steps else 0.0,
        "conservation_recovery_rate": round(
            recovered / violations, 4
        ) if violations else 1.0,
        "avg_steps": round(total_steps / n, 2),
        "avg_retries_per_step": round(total_retries / total_steps, 3)
        if total_steps else 0.0,
        "avg_prompt_tokens": round(prompt_tokens / n, 1),
        "avg_completion_tokens": round(completion_tokens / n, 1),
        "avg_latency_ms": round(total_latency / total_calls, 2) if total_calls else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage-1 small-scale baseline benchmark")
    parser.add_argument("--runs", type=int, default=3, help="Trajectories per scenario")
    parser.add_argument("--model", default=None, help="Model name (default: deepseek-flash)")
    parser.add_argument("--base-url", default=None, help="API base URL override")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout (s)")
    parser.add_argument("--out", default=None, help="Optional JSON report path")
    args = parser.parse_args()

    client_kwargs = dict(model=args.model, base_url=args.base_url, timeout=args.timeout)
    report: list[dict[str, Any]] = []

    for scenario in SCENARIOS:
        print(f"\n== scenario: {scenario['name']} ({args.runs} runs) ==")
        trajs = [_run_one(scenario, client_kwargs) for _ in range(args.runs)]
        summary = _summarise(scenario["name"], trajs)
        report.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    overall = {
        "success_rate": round(sum(r["success_rate"] for r in report) / len(report), 4),
        "avg_retries_per_step": round(
            sum(r["avg_retries_per_step"] for r in report) / len(report), 3
        ),
    }
    print("\n== overall ==")
    print(json.dumps(overall, ensure_ascii=False, indent=2))

    if args.out:
        Path(args.out).write_text(
            json.dumps({"per_scenario": report, "overall": overall},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nReport exported -> {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
