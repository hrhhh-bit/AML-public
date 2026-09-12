"""Phase-0 架构演进防御性穿透与反思闭环测试套件。

针对 Stage-1 宏观尺度（ScaleTier）、流向权重（flow_share）、守恒门禁与
策略叙述改造，执行三个维度的穿透性验证，防止"假绿灯"与"静默兜底掩盖拦截
风险"：

1. **分流守恒门禁穿透与兜底边界**：非法比例必须被拦截且零副作用，工程浮点
   容差边界正确，漏传字段正确兜底但绝不篡改显式非法值。
2. **端到端反思纠错重试闭环**：Verifier 拦截报错回传决策上下文，引导 Agent
   修正动作；重试上限触发终止熔断，严禁死循环。
3. **Stage-2 导出契约与微观纯净度审计**：导出图零微观数字噪音，并完备保留
   Stage-2 所需的高层条件与元数据。

Mock 纪律：除 LLM 文本输出用脚本化桩模拟外，Planner / HardVerifier /
BehavioralEnvironment / ContextBuilder / Narrative 审计全部使用真实代码。
"""

from __future__ import annotations

import json
import re

import pytest

from aml_agent import (
    PlannerAgent,
    ScaleTier,
    ScenarioGoals,
    ScenarioSpec,
    audit_export_purity,
    build_planner_prompt,
    build_strategy_narrative,
)
from aml_env import AgentAction, BehavioralEnvironment, HardVerifier
from aml_rag import (
    DualTrackMotifRetriever,
    PromptContextCompressor,
    QueryContext,
    RetrievalResult,
    SEED_MOTIFS,
    build_default_knowledge_base,
)
from aml_rag.schema import (
    FLOW_TOLERANCE,
    AbstractEdge,
    AbstractNode,
    MotifConstraints,
    NodeRole,
    OperationType,
)

# ---------------------------------------------------------------------------
# 常量与正则（穿透扫描用）
# ---------------------------------------------------------------------------
SRC = NodeRole.SOURCE
INT = NodeRole.INTERMEDIATE
AGG = NodeRole.AGGREGATOR
CC = NodeRole.CROSS_CHAIN
TGT = NodeRole.TARGET

TRANSFER = OperationType.TRANSFER
SPLIT = OperationType.SPLIT
MERGE = OperationType.MERGE
BRIDGE = OperationType.BRIDGE

# 40 位以太坊/比特币风格地址（任务指定强约束）
_ADDR40_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
# 更宽松的地址启发式（8+ hex），与 narrative.audit_export_purity 保持一致
_ADDR_ANY_RE = re.compile(r"0x[a-fA-F0-9]{8,}")
# 13 位毫秒级时间戳
_MS_TS_RE = re.compile(r"\b1[3-9]\d{11}\b")
# 微观噪声词汇：具体代币单位 / Gas / 时间戳
_BANNED_TOKENS = ("ETH", "USDT", "USDC", "BTC", "gas", "Gwei", "wei", "timestamp")


# ---------------------------------------------------------------------------
# 工具与桩
# ---------------------------------------------------------------------------
class RecordingLLM:
    """脚本化 LLM 桩：按序弹出回复，并完整记录每次收到的提示词。"""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return self._replies.pop(0) if self._replies else "garbage"


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


def _split_action(num_children: int, shares: list[float] | None) -> AgentAction:
    params: dict[str, object] = {"num_children": num_children}
    if shares is not None:
        params["flow_shares"] = shares
    return AgentAction(
        operation=SPLIT,
        parent_ids=["node_0"],
        target_role=INT,
        target_chain="Chain_A",
        parameters=params,
    )


def _minimal_graph() -> tuple[dict[str, AbstractNode], list[AbstractEdge], set[str]]:
    """构造一个最小合法状态，供 HardVerifier 直接穿透验证。"""
    nodes = {"node_0": AbstractNode(temp_id="node_0", role=SRC, chain="Chain_A", level=0)}
    return nodes, [], {"node_0"}


def _result_for(motif) -> RetrievalResult:
    return RetrievalResult(
        motif_id=motif.motif_id,
        pattern_type=motif.pattern_type,
        description=motif.description,
        motif=motif,
        rule_score=1.0,
        semantic_score=1.0,
        combined_score=1.0,
    )


def _iter_strings(obj: object):
    """递归产出对象中的所有字符串（含 dict 键与值）。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                yield key
            yield from _iter_strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_strings(item)
    elif isinstance(obj, str):
        yield obj


def _iter_numbers(obj: object):
    """递归产出对象中的所有数值（不含 bool）。"""
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_numbers(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_numbers(item)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield obj


# ---------------------------------------------------------------------------
# 维度一：分流守恒门禁穿透与兜底边界测试
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "shares, sum_substr",
    [([0.6, 0.6], "1.2"), ([0.3, 0.3], "0.6")],
    ids=["over-1.2", "under-0.6"],
)
def test_verifier_rejects_explicit_unconserved_split(shares, sum_substr) -> None:
    """显式非法分流必须被 HardVerifier 拦截，并给出标准反思文本。"""
    nodes, edges, frontier = _minimal_graph()
    action = _split_action(2, shares)

    ok, reason = HardVerifier(MotifConstraints()).validate(
        nodes=nodes, edges=edges, frontier=frontier, action=action
    )

    # HardVerifier 判定非法（validate 返回 (is_valid, reason) 二元组）
    assert ok is False
    assert reason is not None
    # 标准反思文本：违规总和 + 容差 + 修复建议
    assert "flow conservation violated" in reason
    assert sum_substr in reason          # 违规总和（如 1.2 / 0.6）
    assert "tolerance" in reason and "0.01" in reason  # 容差 ±0.01
    assert "Rebalance" in reason         # 修复建议


def test_illegal_flow_action_has_zero_side_effects() -> None:
    """非法动作执行后，环境图状态必须零副作用（出度与边集合保持原样）。"""
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    before = env.export_behavioral_graph()
    before_outdeg = {e["source"] for e in before["edges"]}

    result = env.step(_split_action(2, [0.6, 0.6]))

    assert result.info["accepted"] is False
    assert result.reward == -1.0
    assert result.done is False
    # 图未被改动：节点/边/步数/前沿一致
    after = env.export_behavioral_graph()
    assert after == before
    assert env.step_count == 0
    assert env.frontier == {"node_0"}
    assert env.done is False
    assert {e["source"] for e in after["edges"]} == before_outdeg


@pytest.mark.parametrize(
    "num_children, shares, expect_accepted",
    [
        (3, [0.333, 0.333, 0.334], True),   # 和 1.000 放行
        (2, [0.505, 0.504], True),          # 和 1.009 放行（容差内）
        (2, [0.51, 0.51], False),           # 和 1.02 拦截（超容差）
    ],
    ids=["sum-1.000-pass", "sum-1.009-pass", "sum-1.02-block"],
)
def test_flow_tolerance_boundaries(num_children, shares, expect_accepted) -> None:
    """工程浮点容差（1.0 ± 0.01）边界上的表现。"""
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    result = env.step(_split_action(num_children, shares))
    assert result.info.get("accepted") is expect_accepted
    if not expect_accepted:
        assert "flow conservation violated" in result.info["error"]


def test_planner_backfills_missing_shares_with_equal_split() -> None:
    """漏传 flow_shares 时，Planner 应回填等分份额且守恒。"""
    action = _split_action(2, None)  # 无 flow_shares 键
    enriched = PlannerAgent._enrich_flow_shares(action, [])

    assert "flow_shares" in enriched.parameters
    shares = enriched.parameters["flow_shares"]
    assert shares == [0.5, 0.5]
    assert abs(sum(shares) - 1.0) <= FLOW_TOLERANCE


def test_planner_backfills_missing_shares_from_rag_archetype() -> None:
    """漏传 flow_shares 时，Planner 应优先从 RAG 模式原型继承。"""
    multi = next(m for m in SEED_MOTIFS if m.motif_id == "Multi_Split_Obfuscation")
    results = [_result_for(multi)]
    action = _split_action(3, None)

    enriched = PlannerAgent._enrich_flow_shares(action, results)

    proto = PlannerAgent._split_prototype(results, 3)
    assert enriched.parameters["flow_shares"] == proto
    assert proto == [0.6, 0.25, 0.15]  # 文档化的非对称主/剥皮原型
    assert abs(sum(proto) - 1.0) <= FLOW_TOLERANCE


def test_planner_never_overrides_explicit_shares_even_illegal() -> None:
    """Planner 绝不能覆盖/篡改 Agent 显式给出的非法数值，必须原样送检。"""
    action = _split_action(2, [0.7, 0.7])  # 显式非法（和 1.4）

    enriched = PlannerAgent._enrich_flow_shares(action, [])

    # 未被篡改，原样保留
    assert enriched.parameters["flow_shares"] == [0.7, 0.7]

    # 原样送往 HardVerifier 接受拦截（而非静默归一化）
    env = BehavioralEnvironment()
    env.reset()
    result = env.step(enriched)
    assert result.info["accepted"] is False
    assert "flow conservation violated" in result.info["error"]


def test_full_run_split_without_shares_gets_conserving_fallback() -> None:
    """端到端：LLM 漏传比例时，Planner 兜底注入，导出分流边守恒。"""
    script = [
        _json_action("Split", ["node_0"], "Intermediate", "Chain_A", num_children=2),
        _json_action(None, []),
    ]
    env = BehavioralEnvironment()
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    traj = PlannerAgent(env, retriever, RecordingLLM(script)).plan(
        ScenarioSpec(name="fallback", scenario="s", tactic_goal="g")
    )

    assert traj.success is True
    split_shares = [
        e["flow_share"] for e in traj.graph["edges"] if e["operation"] == "Split"
    ]
    assert len(split_shares) == 2
    assert all(0.0 < s <= 1.0 for s in split_shares)
    assert abs(sum(split_shares) - 1.0) <= FLOW_TOLERANCE


# ---------------------------------------------------------------------------
# 维度二：端到端反思纠错重试闭环测试
# ---------------------------------------------------------------------------
def test_reflection_loop_corrects_flow_violation() -> None:
    """模拟两阶段纠错闭环：违规 → 拦截回传 → 修正 → 恢复推进。"""
    replies = [
        # Round 1：守恒违规（和 1.4）
        _json_action(
            "Split", ["node_0"], "Intermediate", "Chain_A",
            num_children=2, flow_shares=[0.7, 0.7],
        ),
        # Round 2：收到报错后修正（和 1.0）
        _json_action(
            "Split", ["node_0"], "Intermediate", "Chain_A",
            num_children=2, flow_shares=[0.7, 0.3],
        ),
        # 收尾
        _json_action(None, []),
    ]
    llm = RecordingLLM(replies)
    env = BehavioralEnvironment()
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    agent = PlannerAgent(env, retriever, llm, max_retries=3)

    traj = agent.plan(ScenarioSpec(name="reflection", scenario="s", tactic_goal="g"))

    # --- 中间态：重试计数器 +1（1 次违规 + 1 次修正 = 2 次 LLM 调用）---
    step0 = traj.steps[0]
    assert step0.llm_calls == 2
    assert len(step0.retry_reasons) == 1
    assert "flow conservation violated" in step0.retry_reasons[0]

    # --- 报错被注入 Round-2 提示词（Reflection Context）---
    round2_prompt = llm.prompts[1]
    assert "<PREVIOUS_MISTAKE>" in round2_prompt
    assert "flow conservation violated" in round2_prompt
    assert "1.4000" in round2_prompt  # 违规总和原样回传

    # --- 修正动作通过 Verifier，环境完成状态转移，图成功扩展 ---
    assert step0.result.info["accepted"] is True
    split_shares = sorted(
        e["flow_share"] for e in traj.graph["edges"] if e["operation"] == "Split"
    )
    assert split_shares == [0.3, 0.7]

    # --- 决策循环恢复正常并干净收尾 ---
    assert traj.success is True
    assert traj.failed is False
    assert traj.terminated_by == "agent_terminate"


def test_retry_exhaustion_triggers_safe_termination() -> None:
    """连续 3 次非法动作后触发终止熔断，标记失败轨迹，严禁死循环。"""
    illegal = _json_action(
        "Split", ["node_0"], "Intermediate", "Chain_A",
        num_children=2, flow_shares=[0.7, 0.7],
    )
    llm = RecordingLLM([illegal] * 3)  # 连续 3 次非法
    env = BehavioralEnvironment()
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    agent = PlannerAgent(env, retriever, llm, max_retries=2)  # 1 + 2 = 3 次尝试

    traj = agent.plan(ScenarioSpec(name="fuse", scenario="s", tactic_goal="g"))

    # 第 3 次失败后熔断：标记失败轨迹 + 终止方式明确
    assert traj.failed is True
    assert traj.success is False
    assert traj.terminated_by == "retry_exhausted_terminate"

    # 严禁死循环：恰好 3 次调用，无第 4 次
    assert llm.calls == 3
    assert traj.total_llm_calls == 3
    step = traj.steps[0]
    assert step.llm_calls == 3
    assert len(step.retry_reasons) == 3
    assert all("flow conservation violated" in r for r in step.retry_reasons)

    # 拦截贯穿始终：非法动作全程未污染图
    assert traj.graph["meta"]["node_count"] == 1
    assert traj.graph["meta"]["edge_count"] == 0


def test_real_context_builder_feeds_planner_prompt() -> None:
    """真实 ContextBuilder（MOT 压缩器）产出先验块并注入规划提示词。"""
    env = BehavioralEnvironment()
    state = env.reset()
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    query = QueryContext(scenario="launder whale funds", tactic_goal="deep layering")
    results = retriever.retrieve(state, query, top_k=3)

    prior = PromptContextCompressor(max_motifs=3).build_agent_prompt(state, query, results)
    spec = ScenarioSpec(
        name="cb", scenario="launder whale funds", tactic_goal="deep layering",
        scale_tier=ScaleTier.WHALE,
    )
    prompt = build_planner_prompt(spec, state, prior)

    assert "[AML-PRIOR-CONTEXT]" in prompt   # 真实压缩器头部
    assert "<RAG_PRIOR>" in prompt
    assert "<MOTIFS>" in prompt


# ---------------------------------------------------------------------------
# 维度三：Stage-2 导出契约与微观纯净度穿透审计
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def whale_traj():
    """模块级：完整图生成闭环（初始 → 终局 Sink），Whale 尺度。"""
    spec = ScenarioSpec(
        name="whale-purity",
        scenario="launder whale-scale proceeds of a bridge exploit",
        tactic_goal="asymmetric split, merge, then bridge to a second chain",
        scale_tier=ScaleTier.WHALE,
        estimated_value_usd=25_000_000.0,
        goals=ScenarioGoals(
            min_level=4,
            required_roles=(CC, AGG, TGT),
            required_operations=(SPLIT, MERGE, BRIDGE),
        ),
    )
    script = [
        _json_action("Transfer", ["node_0"], "Intermediate", "Chain_A"),
        _json_action(
            "Split", ["node_1"], "Intermediate", "Chain_A",
            num_children=2, flow_shares=[0.7, 0.3],
        ),
        _json_action("Merge", ["node_2", "node_3"], "Aggregator", "Chain_A"),
        _json_action("Bridge", ["node_4"], "Cross_Chain", "Chain_B"),
        _json_action("Transfer", ["node_5"], "Target", "Chain_B"),
        _json_action(None, []),
    ]
    env = BehavioralEnvironment()
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    return PlannerAgent(env, retriever, RecordingLLM(script)).plan(spec)


def test_end_to_end_purity_audit_clean(whale_traj) -> None:
    """导出图必须零微观数字噪音；内置审计与递归扫描均无违规。"""
    export = whale_traj.graph

    # 内置审计：无违规项
    assert audit_export_purity(export) == []

    # 节点纯净度：ID / 属性不含任何地址形态
    for node in export["nodes"]:
        assert not _ADDR40_RE.fullmatch(node["id"])
        assert not _ADDR_ANY_RE.search(node["id"])
        assert not _ADDR_ANY_RE.search(node["role"])
        assert not _ADDR_ANY_RE.search(node["chain"])

    # 递归扫描（键 + 值）：无地址 / 无代币单位 / 无 Gas / 无时间戳
    for text in _iter_strings(export):
        assert not _ADDR_ANY_RE.search(text), f"address-like string: {text!r}"
        assert not _MS_TS_RE.search(text), f"timestamp-like string: {text!r}"
        assert not any(tok in text for tok in _BANNED_TOKENS), (
            f"micro-noise token in: {text!r}"
        )

    # 数值域：无 13 位毫秒级时间戳
    for num in _iter_numbers(export):
        assert not (1_300_000_000_000 <= num <= 1_999_999_999_999), (
            f"millisecond timestamp int: {num}"
        )

    # 边属性合法性：flow_share 必须是浮点且 0.0 < share <= 1.0
    for edge in export["edges"]:
        share = edge["flow_share"]
        assert isinstance(share, float)
        assert 0.0 < share <= 1.0


def test_stage2_metadata_contract(whale_traj) -> None:
    """Stage-2 元数据契约完备性：scale_tier / 估值 / 策略叙述。"""
    meta = whale_traj.graph["meta"]

    # scale_tier 为合法枚举值字符串
    assert meta["scale_tier"] == "Whale"
    assert ScaleTier(meta["scale_tier"]) is ScaleTier.WHALE

    # estimated_value_usd 正确透传
    assert meta["estimated_value_usd"] == 25_000_000.0

    # strategy_narrative 非空，且由结构派生、紧扣实际执行的模式
    narrative = meta["strategy_narrative"]
    assert narrative and isinstance(narrative, str)
    assert "Whale-scale" in narrative          # 尺度
    assert "fan-out splits" in narrative       # 实际执行了 Split
    assert "converging merges" in narrative    # 实际执行了 Merge
    assert "Chain_A -> Chain_B" in narrative   # 实际执行了跨链 Bridge
    assert "target sink" in narrative          # 实际终局为 Target Sink

    # 与轨迹上的叙述一致，且由 build_strategy_narrative 真实派生
    assert whale_traj.strategy_narrative == narrative
    assert build_strategy_narrative(whale_traj) == narrative
