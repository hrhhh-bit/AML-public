"""Stage-1 single-sample smoke test against a real LLM (deepseek-flash).

Runs one full decision loop over a Whale cross-chain scenario, live-printing
each step (action, RAG hit, verifier reflection, latency, tokens), then
exports ``smoke_graph.json``, runs the purity audit and prints the
structure-derived strategy narrative.

Usage:
    python scripts/smoke_deepseek.py [--model deepseek-flash] [--out smoke_graph.json]

Environment:
    DEEPSEEK_API_KEY   (or OPENAI_API_KEY) — required
    DEEPSEEK_BASE_URL  — optional, default https://api.deepseek.com
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    TrajectoryStep,
    audit_export_purity,
)
from aml_env import BehavioralEnvironment  # noqa: E402
from aml_rag import DualTrackMotifRetriever, build_default_knowledge_base  # noqa: E402
from aml_rag.schema import NodeRole, OperationType  # noqa: E402


def _fmt_action(step: TrajectoryStep) -> str:
    op = step.action.operation.value if step.action.operation else "Terminate"
    shares = step.action.parameters.get("flow_shares")
    extra = f" flow_shares={shares}" if shares else ""
    return f"{op}{extra}"


def _print_step(step: TrajectoryStep, client: LLMClient) -> None:
    call = client.last_call
    latency = f"{call.latency_ms:.0f}ms" if call else "n/a"
    tokens = (
        f"{call.prompt_tokens}/{call.completion_tokens}"
        if call
        else "n/a/n/a"
    )
    prior = step.prior_motif_ids or ("(soft-fallback)" if step.prior_soft_fallback else ())
    print(
        f"[step {step.step_index}] action={_fmt_action(step):28s} "
        f"prior={prior} "
        f"retries={len(step.retry_reasons)} "
        f"latency={latency:>7s} tok(in/out)={tokens}"
    )
    for reason in step.retry_reasons:
        print(f"    ↳ verifier/parse reflection: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-sample Stage-1 smoke run")
    parser.add_argument("--model", default=None, help="Model name (default: deepseek-flash)")
    parser.add_argument("--base-url", default=None, help="API base URL override")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout (s)")
    parser.add_argument("--out", default="smoke_graph.json", help="Output graph path")
    args = parser.parse_args()

    client = LLMClient(model=args.model, base_url=args.base_url, timeout=args.timeout)
    env = BehavioralEnvironment()
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())

    spec = ScenarioSpec(
        name="smoke-whale-cross-chain",
        scenario=(
            "A whale-scale operator consolidates proceeds from several DeFi "
            "exploits and must obscure the trail across multiple chains before "
            "cashing out."
        ),
        tactic_goal="layer, split, hop chains and integrate to a target",
        scale_tier=ScaleTier.WHALE,
        estimated_value_usd=2_000_000.0,
        goals=ScenarioGoals(
            min_level=4,
            required_roles=(NodeRole.TARGET,),
            required_operations=(OperationType.BRIDGE,),
        ),
    )

    print(f"== Stage-1 smoke run | model={client.model} | base={client.base_url} ==")
    planner = PlannerAgent(env, retriever, client, step_callback=lambda s: _print_step(s, client))
    trajectory = planner.plan(spec)

    print("\n-- summary -------------------------------------------------------")
    print(f"success={trajectory.success} failed={trajectory.failed} "
          f"terminated_by={trajectory.terminated_by}")
    print(f"steps={len(trajectory.steps)} reward={trajectory.total_reward} "
          f"llm_calls={trajectory.total_llm_calls}")
    print(f"llm_metrics={trajectory.llm_metrics}")
    print(f"strategy_narrative={trajectory.strategy_narrative}")
    print(f"purity_issues={audit_export_purity(trajectory.graph)}")

    out = Path(args.out)
    out.write_text(
        json.dumps(trajectory.graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nGraph exported -> {out.resolve()}")
    return 0 if trajectory.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
