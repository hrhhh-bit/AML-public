"""Stage-1 阶段性展示脚本：逐阶段生成可见产物（提示词 / 检索报告 / 决策图）。

运行方式（项目根目录）:

    python demo/showcase_stage1.py                # 输出到 artifacts/showcase_<时间戳>/
    python demo/showcase_stage1.py --out my_dir   # 指定输出目录

生成产物一览:

    00_知识库总览.md         12 个种子 Motif 的表格 + Mermaid 子图
    01_蒸馏管线/             LLM 蒸馏提示词 + mock 回复 + Pydantic 校验后的 Motif JSON
    02_双轨检索.md           Track-1 硬门全量判决表 + Track-2 语义打分 Top-3
    03_先验提示词压缩.md      MOT 压缩后的 Agent 先验上下文块（JSON + Mermaid）
    04_决策循环/             每一步的完整规划提示词 / 动作 JSON / 完整轨迹 JSON
    05_最终行为图.md         决策图 Mermaid + 统计表 + 图 JSON
    README.md               产物索引

脚本完全确定性（脚本化 mock LLM），不依赖任何外部 API，可离线复现。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 直接执行本脚本时，把 src/ 加入搜索路径（pytest 已通过 pyproject 配置好）
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aml_agent import PlannerAgent, ScenarioGoals, ScenarioSpec  # noqa: E402
from aml_env import BehavioralEnvironment  # noqa: E402
from aml_rag import (  # noqa: E402
    DualTrackMotifRetriever,
    MotifExtractor,
    PromptContextCompressor,
    QueryContext,
    build_default_knowledge_base,
)
from aml_rag.schema import NodeRole, OperationType  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 确定性脚本化 LLM（与 tests/test_planner.py 同一轨迹，逐步记录提示词）
# ---------------------------------------------------------------------------
class ScriptedLLM:
    """确定性 LLM 桩：按序弹出回复，并完整记录每次收到的提示词。"""

    def __init__(self, replies: list[str], default: str = "not-json") -> None:
        self._replies = list(replies)
        self._default = default
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
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


# Transfer -> Split(2) -> Merge -> Bridge -> Transfer -> Terminate
FULL_SCRIPT: list[str] = [
    _json_action("Transfer", ["node_0"], "Intermediate", "Chain_A"),
    _json_action("Split", ["node_1"], "Intermediate", "Chain_A", num_children=2),
    _json_action("Merge", ["node_2", "node_3"], "Aggregator", "Chain_A"),
    _json_action("Bridge", ["node_4"], "Cross_Chain", "Chain_B"),
    _json_action("Transfer", ["node_5"], "Target", "Chain_B"),
    _json_action(None, []),
]

# ---------------------------------------------------------------------------
# Stage-1 蒸馏管线的样例输入（含噪声，用于演示"零微观数字噪音"剥离）
# ---------------------------------------------------------------------------
RAW_REPORT: str = """\
Case #AML-2026-014 "Rapid Peel"
On 2026-07-11, wallet 0x7a2f...d9 received 412 ETH (approx. USD 1.1M) from the
exploit. Within 9 minutes the funds moved through three freshly funded
intermediate wallets (0xb1c4..., 0x9f02..., 0x33d8...), each hop keeping the
balance under 50 ETH with ~0.002 ETH gas, all on the same chain. The final hop
landed in a high-risk exchange deposit address.
"""

MOCK_LLM_REPLY: str = """\
Here is the distilled motif:

```json
[
  {
    "motif_id": "Rapid_Peeling_Single_Chain",
    "pattern_type": "Peeling_Chain",
    "description": "Rapid linear peeled transfers along a single chain through three fresh intermediates before the final target.",
    "preconditions": {
      "min_level": 0,
      "allowed_node_roles": ["Source", "Intermediate"],
      "max_active_branches": 1
    },
    "nodes": [
      {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
      {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_A", "level": 1},
      {"temp_id": "I2", "role": "Intermediate", "chain": "Chain_A", "level": 2},
      {"temp_id": "I3", "role": "Intermediate", "chain": "Chain_A", "level": 3},
      {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 4}
    ],
    "edges": [
      {"source": "S", "target": "I1", "operation": "Transfer"},
      {"source": "I1", "target": "I2", "operation": "Transfer"},
      {"source": "I2", "target": "I3", "operation": "Transfer"},
      {"source": "I3", "target": "T", "operation": "Transfer"}
    ],
    "post_state_effect": {
      "branch_increment": 0,
      "chain_transition": false,
      "next_recommended_roles": ["Intermediate", "Target"]
    },
    "tags": ["peeling", "linear", "single_chain"]
  }
]
```
This matches the Peeling_Chain typology.
"""


# ---------------------------------------------------------------------------
# 展示场景规格（带结构化成功判据，最终轨迹会全部满足）
# ---------------------------------------------------------------------------
def build_scenario() -> ScenarioSpec:
    return ScenarioSpec(
        name="showcase-跨链分层归集",
        scenario="launder proceeds of a DeFi exploit via layering, "
        "cross-chain hopping and aggregation",
        tactic_goal="layer on Chain_A, bridge to Chain_B, integrate into a target",
        d_max=4,
        max_level=8,
        max_steps=64,
        goals=ScenarioGoals(
            min_level=4,
            required_roles=(
                NodeRole.CROSS_CHAIN,
                NodeRole.AGGREGATOR,
                NodeRole.TARGET,
            ),
            required_operations=(
                OperationType.BRIDGE,
                OperationType.SPLIT,
                OperationType.MERGE,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _j(obj: object) -> str:
    """中文友好的 JSON 缩进序列化。"""
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _pre_summary(motif) -> str:
    pre = motif.preconditions
    roles = ",".join(r.value for r in pre.allowed_node_roles) if pre.allowed_node_roles else "∅"
    chains = ",".join(pre.required_chains) if pre.required_chains else "∅"
    max_b = pre.max_active_branches if pre.max_active_branches is not None else "∅"
    return f"min_level={pre.min_level} · roles=[{roles}] · chains=[{chains}] · max_branches={max_b}"


def _post_summary(motif) -> str:
    post = motif.post_state_effect
    nxt = ",".join(r.value for r in post.next_recommended_roles) or "∅"
    chain = f" → {post.target_chain}" if post.target_chain else ""
    return (
        f"branch_inc={post.branch_increment} · "
        f"chain_transition={post.chain_transition}{chain} · next=[{nxt}]"
    )


def _md(md: str, path: Path) -> Path:
    path.write_text(md, encoding="utf-8")
    return path


def _txt(text: str, path: Path) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Stage 0 · 先验知识库总览
# ---------------------------------------------------------------------------
def build_stage0(kb, out_dir: Path) -> list[Path]:
    motifs = list(kb)
    rows = []
    for i, m in enumerate(motifs, start=1):
        lo, hi = m.level_span()
        rows.append(
            f"| {i} | `{m.motif_id}` | {m.pattern_type.value} | "
            f"{len(m.nodes)} | {len(m.edges)} | L{lo}–L{hi} | "
            f"{_pre_summary(m)} | {_post_summary(m)} |"
        )
    table = "\n".join(
        [
            "| # | motif_id | pattern_type | 节点 | 边 | 层级跨度 | 前置条件 | 状态效应 |",
            "|---|---|---|---|---|---|---|---|",
            *rows,
        ]
    )

    sections = [
        "# Stage 0 · 先验知识库总览（12 个种子 Motif）",
        "",
        "> 设计理念：**零微观数字噪音** —— 无地址、无金额、无 Gas、无时间戳，"
        "只有抽象角色、链标签、DAG 层级与抽象操作；所有 Motif 在构造期通过 "
        "Pydantic 校验（Kahn 判环、level 严格递增、分支度 ≤ d_max）。",
        "",
        table,
        "",
    ]
    for i, m in enumerate(motifs, start=1):
        sections.extend(
            [
                f"## {i}. {m.motif_id}",
                "",
                f"> {m.description}",
                "",
                f"- **前置条件**: {_pre_summary(m)}",
                f"- **状态效应**: {_post_summary(m)}",
                "",
                "```mermaid",
                PromptContextCompressor.to_mermaid(m, f"m{i}"),
                "```",
                "",
            ]
        )
    return [_md("\n".join(sections), out_dir / "00_知识库总览.md")]


# ---------------------------------------------------------------------------
# Stage 1 · LLM 蒸馏管线
# ---------------------------------------------------------------------------
def build_stage1(out_dir: Path) -> list[Path]:
    sub = out_dir / "01_蒸馏管线"
    sub.mkdir(parents=True, exist_ok=True)

    extractor = MotifExtractor(llm=lambda prompt: MOCK_LLM_REPLY)
    prompt = extractor.build_prompt(RAW_REPORT)
    motifs = extractor.extract(RAW_REPORT)

    files = [
        _txt(prompt, sub / "distillation_prompt.txt"),
        _txt(MOCK_LLM_REPLY, sub / "mock_llm_reply.txt"),
        _txt(_j([m.model_dump(mode="json") for m in motifs]), sub / "parsed_motif.json"),
    ]
    # 蒸馏后的 Motif 直接渲染成 Mermaid，方便对比"噪音 → 拓扑"
    mermaid = "\n\n".join(
        PromptContextCompressor.to_mermaid(m, f"d{i}") for i, m in enumerate(motifs, 1)
    )
    files.append(
        _md(
            "\n".join(
                [
                    "# Stage 1 · LLM 蒸馏管线（真实研报 → 拓扑 Motif）",
                    "",
                    "## 输入：含微观噪音的原始研报（地址/金额/Gas 全部存在）",
                    "",
                    "```text",
                    RAW_REPORT.strip(),
                    "```",
                    "",
                    "## 处理：严格蒸馏提示词（9 条硬约束 + 内嵌 JSON Schema）",
                    "",
                    f"完整提示词见 `distillation_prompt.txt`（共 {len(prompt)} 字符）。",
                    "",
                    "## 输出：mock LLM 回复（带 markdown 围栏与解说噪音，测试解析鲁棒性）",
                    "",
                    "见 `mock_llm_reply.txt`；解析后通过 Pydantic 构造期校验，"
                    f"产出 {len(motifs)} 个合法 DAG Motif：",
                    "",
                    "```mermaid",
                    mermaid,
                    "```",
                    "",
                    "## 校验后的 Motif JSON",
                    "",
                    f"见 `parsed_motif.json`（注意：地址 `0x7a2f...`、金额 `412 ETH`、"
                    "Gas `0.002 ETH` 等微观噪音已被完全剥离）。",
                    "",
                ]
            ),
            sub / "README.md",
        )
    )
    return files


# ---------------------------------------------------------------------------
# Stage 2 · 双轨检索（硬规则门 + 语义打分）
# ---------------------------------------------------------------------------
def build_stage2(
    retriever: DualTrackMotifRetriever,
    state,
    query: QueryContext,
    out_dir: Path,
) -> Path:
    # Track 1: 全量硬门判决表
    gate_rows = []
    for m in retriever.knowledge_base:
        passed, rule_score, reasons = retriever.hard_gate(m, state)
        verdict = "✅ PASS" if passed else "❌ FAIL"
        gate_rows.append(
            f"| `{m.motif_id}` | {verdict} | {rule_score:.2f} | "
            f"{'; '.join(reasons) or '无约束'} |"
        )
    gate_table = "\n".join(
        [
            "| motif_id | 判决 | rule_score | 判决理由 |",
            "|---|---|---|---|",
            *gate_rows,
        ]
    )

    # Track 2: 幸存者语义排序
    results = retriever.retrieve(state, query, top_k=3)
    rank_rows = []
    for rank, r in enumerate(results, start=1):
        rank_rows.append(
            f"| {rank} | `{r.motif_id}` | {r.pattern_type.value} | "
            f"{r.rule_score:.3f} | {r.semantic_score:.3f} | "
            f"{r.combined_score:.4f} | {'; '.join(r.gate_reasons)} |"
        )
    rank_table = "\n".join(
        [
            "| rank | motif_id | pattern | rule | semantic | combined | 门控理由 |",
            "|---|---|---|---|---|---|---|",
            *rank_rows,
        ]
    )

    md = "\n".join(
        [
            "# Stage 2 · 双轨检索（State_0 演示）",
            "",
            "## 当前状态 State_0（环境重置后的快照）",
            "",
            "```json",
            _j(state),
            "```",
            "",
            "## Track 1 · 硬规则门全量判决（12 个 Motif）",
            "",
            "违反前置条件（min_level / 角色 / 链 / 活跃分支数）的候选被**一票否决**，"
            "不进入语义轨：",
            "",
            gate_table,
            "",
            "## Track 2 · 语义打分 Top-3（strict=True 幸存者排序）",
            "",
            f"融合得分：`Score = α·cos(e_context, e_motif) + (1-α)·RuleSat`，α={retriever.alpha}",
            "",
            rank_table,
            "",
        ]
    )
    return _md(md, out_dir / "02_双轨检索.md")


# ---------------------------------------------------------------------------
# Stage 3 · MOT 提示词压缩（先验上下文块）
# ---------------------------------------------------------------------------
def build_stage3(
    compressor: PromptContextCompressor,
    state,
    query: QueryContext,
    results,
    out_dir: Path,
) -> Path:
    prior = compressor.build_agent_prompt(state, query, results)
    md = "\n".join(
        [
            "# Stage 3 · MOT 提示词压缩（Agent 先验上下文块）",
            "",
            "> 机制：双轨检索 Top-3 → 冗余子路径消除（edge-signature 支配关系）→ "
            "Token 高效 JSON + Mermaid DAG → 作为 `<RAG_PRIOR>` 注入规划提示词。",
            "",
            f"`PromptContextCompressor`（max_motifs={compressor.max_motifs}，"
            f"format={compressor.output_format}）对 State_0 的输出：",
            "",
            "````text",
            prior,
            "````",
            "",
            "- 节点压缩为 4 键 dict（`id/role/chain/lvl`），边压缩为 MOT 三元组 "
            "`[source, target, operation]`；",
            "- 每个 Motif 附带 `score` 与 `rank`，并渲染为 Mermaid DAG，"
            "让 LLM 一眼读取拓扑方向；",
            "- 被更大候选完全支配的子路径会被剔除，节省上下文 Token。",
            "",
        ]
    )
    return _md(md, out_dir / "03_先验提示词压缩.md")


# ---------------------------------------------------------------------------
# Stage 4 · Agent 决策循环（逐步提示词 + 动作 + 完整轨迹）
# ---------------------------------------------------------------------------
def build_stage4(llm: ScriptedLLM, traj, out_dir: Path) -> list[Path]:
    sub = out_dir / "04_决策循环"
    sub.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    offset = 0
    for step in traj.steps:
        idx = step.step_index
        # 该步第一次尝试收到的完整规划提示词
        prompt = llm.prompts[offset]
        offset += step.llm_calls
        files.append(_txt(prompt, sub / f"step_{idx:02d}_prompt.txt"))
        files.append(_txt(_j(step.action), sub / f"step_{idx:02d}_action.json"))

    files.append(_txt(_j(traj), sub / "trajectory.json"))

    rows = []
    for step in traj.steps:
        a = step.action
        if a.operation is None:
            action_desc = "**Terminate**（控制动作）"
        else:
            action_desc = (
                f"`{a.operation.value}`({','.join(a.parent_ids)}) "
                f"→ {a.target_role.value} @ {a.target_chain}"
            )
            if a.parameters:
                action_desc += f" {a.parameters}"
        prior = ", ".join(
            f"{mid}({score})"
            for mid, score in zip(step.prior_motif_ids, step.prior_scores)
        )
        rows.append(
            f"| {step.step_index} | {action_desc} | {prior or '—'} | "
            f"{'⚠️ soft' if step.prior_soft_fallback else ''} | "
            f"{step.llm_calls} | {'; '.join(step.retry_reasons) or '—'} | "
            f"{step.result.reward} |"
        )
    table = "\n".join(
        [
            "| step | 动作 | RAG 先验 Motif（分数） | 软回退 | LLM 调用 | 重试原因 | reward |",
            "|---|---|---|---|---|---|---|",
            *rows,
        ]
    )

    md = "\n".join(
        [
            "# Stage 4 · Agent 决策循环（perceive → retrieve → plan → act）",
            "",
            f"场景：`{traj.scenario_name}` · 终止方式：`{traj.terminated_by}` · "
            f"success={traj.success} · total_reward={traj.total_reward} · "
            f"LLM 总调用 {traj.total_llm_calls} 次",
            "",
            table,
            "",
            "## 逐步产物",
            "",
        ]
    )
    for step in traj.steps:
        idx = step.step_index
        md += (
            f"- `step_{idx:02d}_prompt.txt` — 第 {idx} 步完整规划提示词"
            "（场景 + 当前状态 + 压缩后的 RAG 先验 + 输出 Schema）\n"
            f"- `step_{idx:02d}_action.json` — 第 {idx} 步 Agent 动作\n"
        )
    md += "\n- `trajectory.json` — 完整轨迹审计（prior_motif_ids / retry_reasons / llm_calls 留痕）\n"
    files.append(_md(md, sub / "README.md"))
    return files


# ---------------------------------------------------------------------------
# Stage 5 · 最终行为图（决策图）
# ---------------------------------------------------------------------------
def build_stage5(traj, out_dir: Path) -> list[Path]:
    graph = traj.graph
    meta = graph["meta"]
    meta_rows = [
        f"| 指标 | 值 |",
        f"|---|---|",
        f"| 节点数 | {meta['node_count']} |",
        f"| 边数 | {meta['edge_count']} |",
        f"| 规划步数 | {meta['steps']} |",
        f"| 最大层级 | {meta['max_level']} |",
        f"| 分支度上限 d_max | {meta['d_max']} |",
        f"| 层级上限 L_max | {meta['L_max']} |",
        f"| 终止方式 | {meta['terminated_by']} |",
        f"| 起始链 | {meta['seed_chain']} · {meta['initial_role']} |",
    ]
    edge_rows = [
        f"| `{e['source']}` → `{e['target']}` | {e['operation']} |"
        for e in graph["edges"]
    ]
    edge_table = "\n".join(
        ["| 边 | 操作 |", "|---|---|", *edge_rows]
    )

    md = "\n".join(
        [
            "# Stage 5 · 最终行为图 G_b（决策图）",
            "",
            f"场景 `{traj.scenario_name}`：success={traj.success}，"
            f"终止方式 `{traj.terminated_by}`，"
            f"未满足目标：{list(traj.unmet_goals) or '无（全部达成）'}。",
            "",
            "## 图统计",
            "",
            "\n".join(meta_rows),
            "",
            "## 决策图（Mermaid flowchart）",
            "",
            "```mermaid",
            traj.mermaid,
            "```",
            "",
            "## 边清单",
            "",
            edge_table,
            "",
            "完整图 JSON 见 `graph.json`（供 Stage-2 条件图扩散模型消费）。",
            "",
        ]
    )
    return [
        _md(md, out_dir / "05_最终行为图.md"),
        _txt(_j(graph), out_dir / "graph.json"),
    ]


# ---------------------------------------------------------------------------
# 汇总与主流程
# ---------------------------------------------------------------------------
def _write_index(out_dir: Path, files: list[Path]) -> Path:
    rels = sorted({str(f.relative_to(out_dir)).replace("\\", "/") for f in files})
    items = "\n".join(f"- [{r}]({r})" for r in rels)
    md = "\n".join(
        [
            "# Stage-1 阶段性展示产物索引",
            "",
            "> 由 `demo/showcase_stage1.py` 生成（确定性脚本化 LLM，离线可复现）。",
            "",
            items,
            "",
        ]
    )
    return _md(md, out_dir / "README.md")


def build_all_artifacts(out_dir: Path):
    """生成全部阶段产物，返回 (轨迹, 产物文件列表)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []

    kb = build_default_knowledge_base()
    retriever = DualTrackMotifRetriever(kb, top_k=3)
    compressor = PromptContextCompressor(max_motifs=3)

    files += build_stage0(kb, out_dir)
    files += build_stage1(out_dir)

    env = BehavioralEnvironment()
    state0 = env.reset()
    spec = build_scenario()
    query = QueryContext(scenario=spec.scenario, tactic_goal=spec.tactic_goal)

    results = retriever.retrieve(state0, query, top_k=3)
    files.append(build_stage2(retriever, state0, query, out_dir))
    files.append(build_stage3(compressor, state0, query, results, out_dir))

    llm = ScriptedLLM(FULL_SCRIPT)
    agent = PlannerAgent(env, retriever, llm, top_k=3, compressor=compressor)
    traj = agent.plan(spec)

    files += build_stage4(llm, traj, out_dir)
    files += build_stage5(traj, out_dir)
    files.append(_write_index(out_dir, files))
    return traj, files


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage-1 阶段性展示产物生成器")
    parser.add_argument(
        "--out",
        default=None,
        help="输出目录（默认 artifacts/showcase_<时间戳>/）",
    )
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else PROJECT_ROOT / "artifacts" / f"showcase_{stamp}"

    traj, files = build_all_artifacts(out_dir)

    print("=" * 64)
    print("Stage-1 阶段性展示产物生成完毕")
    print(f"  轨迹: success={traj.success}  终止方式={traj.terminated_by}")
    print(f"  reward={traj.total_reward}  LLM 调用={traj.total_llm_calls}")
    print(f"  输出目录: {out_dir}")
    print("-" * 64)
    for f in sorted(files):
        print(f"  - {f.relative_to(out_dir)}")
    print("=" * 64)


if __name__ == "__main__":
    main()
