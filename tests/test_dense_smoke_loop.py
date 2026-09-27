"""Stage-3 Part A: 真实端点冒烟脚本的离线等价复测。

``scripts/smoke_deepseek.py`` 需要真实 LLM 凭据；本测试以确定性脚本化 LLM
替代真实端点（其余部分——Whale 场景、PlannerAgent 决策闭环、双轨检索前置
注入——与冒烟脚本逐行一致），验证稠密检索的前置注入行为在决策闭环中完全
自洽：

1. Dense 模式下轨迹成功收敛，且每一步都注入非空 RAG 先验；
2. 注入的提示词包含先验上下文块（压缩器输出）；
3. Dense（本环境降级为离散哈希引擎）与 Discrete 双模式决策闭环逐步骤一致；
4. Provider 后端标识可被如实报告（实验审计需要）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = PROJECT_ROOT / "demo"
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

import showcase_stage1 as demo  # noqa: E402

from aml_agent import PlannerAgent, ScaleTier, ScenarioGoals, ScenarioSpec  # noqa: E402
from aml_env import BehavioralEnvironment  # noqa: E402
from aml_rag import (  # noqa: E402
    DenseEmbeddingProvider,
    DiscreteEmbeddingProvider,
    DualTrackMotifRetriever,
    build_default_knowledge_base,
)
from aml_rag.schema import NodeRole, OperationType  # noqa: E402


def _smoke_spec() -> ScenarioSpec:
    """与 scripts/smoke_deepseek.py 完全一致的 Whale 跨链场景。"""
    return ScenarioSpec(
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


def _run_loop(embedder, *, top_k: int = 3):
    env = BehavioralEnvironment()
    retriever = DualTrackMotifRetriever(
        build_default_knowledge_base(), embedder=embedder, top_k=top_k
    )
    llm = demo.ScriptedLLM(list(demo.FULL_SCRIPT))
    planner = PlannerAgent(env, retriever, llm)
    return planner.plan(_smoke_spec()), llm, retriever


class TestDenseSmokeLoop:
    def test_dense_decision_loop_succeeds_and_injects_priors(self) -> None:
        dense = DenseEmbeddingProvider()
        with pytest.warns(RuntimeWarning, match="degraded"):
            traj, llm, retriever = _run_loop(dense)

        assert traj.success is True, traj.unmet_goals
        assert traj.terminated_by == "agent_terminate"
        assert len(traj.steps) == 6
        # 每一步都必须注入非空 RAG 先验（稠密检索前置注入自洽）
        assert all(s.prior_motif_ids for s in traj.steps)
        assert all(s.prior_scores for s in traj.steps)
        # 每个规划提示词都携带压缩先验上下文块
        assert all("[AML-PRIOR-CONTEXT]" in p for p in llm.prompts)
        # 后端标识如实可见（实验审计需要）
        assert retriever.embedder.backend in {
            "hash_fallback",
            "sentence_transformers:all-MiniLM-L6-v2",
        }

    def test_dense_and_discrete_loops_are_stepwise_identical(self) -> None:
        dense = DenseEmbeddingProvider()
        with pytest.warns(RuntimeWarning, match="degraded"):
            traj_dense, _, _ = _run_loop(dense)
        traj_disc, _, _ = _run_loop(DiscreteEmbeddingProvider())

        def _ops(traj):
            return [
                s.action.operation.value if s.action.operation else "Terminate"
                for s in traj.steps
            ]

        assert _ops(traj_dense) == _ops(traj_disc)
        assert [s.prior_motif_ids for s in traj_dense.steps] == [
            s.prior_motif_ids for s in traj_disc.steps
        ]
        assert traj_dense.success == traj_disc.success is True

    def test_prior_prompts_reference_retrieved_motifs(self) -> None:
        dense = DenseEmbeddingProvider()
        with pytest.warns(RuntimeWarning, match="degraded"):
            traj, llm, _ = _run_loop(dense)
        for step, prompt in zip(traj.steps, llm.prompts):
            for motif_id in step.prior_motif_ids:
                assert motif_id in prompt
