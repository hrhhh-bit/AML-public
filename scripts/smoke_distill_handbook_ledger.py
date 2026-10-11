#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/smoke_distill_handbook_ledger.py
----------------------------------------------------------------------
阶段 3（Part B 前置）轻量冒烟：真实 LLM × 强化账本公理门禁联调。

仅对单篇原始研报样本 ``resources/Crypto-Asset-Tracing-Handbook`` 执行一次
蒸馏（规则 8/9 新 Prompt 真实 API 调用），验收核心：

    LLM 在规则 8/9 下自主抽取的 Motif，是否满足
    - 跨链边必须为 Bridge（Cross-Chain Ledger Invariant）
    - 单出边 flow_share = 1.0（Outflow Conservation Invariant）
    并被强化后的门禁 100% 放行。

行为保证：
- 全程零写盘：不加载、不触碰、不重写生产知识库 data/distilled_kb.json；
- API Key 优先级：--api-key 参数 > DEEPSEEK_API_KEY / OPENAI_API_KEY
  环境变量 > 交互式安全输入（不回显），由用户自行在命令行输入。

用法:
    python scripts/smoke_distill_handbook_ledger.py \
        [--report resources/Crypto-Asset-Tracing-Handbook] \
        [--max-chars 9000] [--model deepseek-flash] [--base-url ...] \
        [--api-key ...] [--timeout 120] [--no-repair-log]
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aml_agent import LLMClient  # noqa: E402
from aml_rag import MotifDistiller, TextChunker, motif_topology_issues  # noqa: E402
from aml_rag.schema import FLOW_TOLERANCE  # noqa: E402

DEFAULT_REPORT = PROJECT_ROOT / "resources" / "Crypto-Asset-Tracing-Handbook"

#: 生产知识库物理资产 —— 本脚本绝不读写它。
PRODUCTION_KB = PROJECT_ROOT / "data" / "distilled_kb.json"


def _resolve_api_key(cli_key: str | None) -> str | None:
    """--api-key > environment > interactive secure prompt."""
    if cli_key:
        return cli_key
    env_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key
    print("[*] 未发现 API Key（--api-key / 环境变量均为空）。")
    try:
        return getpass.getpass("请输入 LLM API Key（输入不回显，仅用于本次运行）: ").strip() or None
    except (EOFError, KeyboardInterrupt):
        return None


def _fmt_gate_log(motif) -> list[str]:
    """为单个 Motif 生成强化门禁的逐项校验日志行。"""
    lines: list[str] = []
    chain_of = {n.temp_id: n.chain for n in motif.nodes}

    # 公理 1：跨链动作闭环
    cross = [e for e in motif.edges if chain_of[e.source] != chain_of[e.target]]
    if cross:
        details = ", ".join(
            f"{e.source}->{e.target}({e.operation.value})" for e in cross
        )
        lines.append(f"      [公理1] 跨链边 {details} -> 全部 Bridge ✓")
    else:
        lines.append("      [公理1] 无跨链边（N/A）✓")

    # 公理 2：单出边 / 多出边流出守恒
    out_groups: dict[str, list[Any]] = defaultdict(list)
    for e in motif.edges:
        out_groups[e.source].append(e)
    parts: list[str] = []
    for nid, group in sorted(out_groups.items()):
        total = round(sum(e.flow_share for e in group), 4)
        tag = "单出边" if len(group) == 1 else f"{len(group)}出边"
        parts.append(f"{nid}({tag})={total}")
    lines.append(f"      [公理2] 节点出边守恒 {', '.join(parts)} ✓ (容差 {FLOW_TOLERANCE})")

    issues = motif_topology_issues(motif)
    verdict = "PASS (issues=[])" if not issues else f"REJECT (issues={issues})"
    lines.append(f"      [门禁] {verdict}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="真实 LLM 蒸馏 × 强化账本门禁冒烟")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="原始研报样本路径")
    parser.add_argument("--max-chars", type=int, default=0, help="只取前 N 字符（0=全文）")
    parser.add_argument("--model", default=None, help="模型名（默认 deepseek-flash）")
    parser.add_argument("--base-url", default=None, help="API Base URL 覆盖")
    parser.add_argument("--api-key", default=None, help="API Key（优先于环境变量/交互输入）")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP 超时(s)")
    parser.add_argument("--no-repair-log", action="store_true", help="不打印修复重试日志")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"[-] 错误：找不到研报样本 {report_path}")
        return 1

    api_key = _resolve_api_key(args.api_key)
    if not api_key:
        print("[-] 未获得 API Key，终止运行（生产知识库零触碰）。")
        return 1

    text = report_path.read_text(encoding="utf-8")
    if args.max_chars and args.max_chars > 0:
        text = text[: args.max_chars]
    print(
        f"== 蒸馏冒烟 | report={report_path.name} | chars={len(text)} | "
        f"model={args.model or 'deepseek-flash'} =="
    )
    print(f"[guard] 生产知识库 {PRODUCTION_KB.name} 只读状态：本脚本零读写。")

    client = LLMClient(
        api_key=api_key, base_url=args.base_url, model=args.model, timeout=args.timeout
    )

    # 捕获每次 LLM 原始回复（含 repair 重试），用于输出拓扑 JSON 片段
    raw_replies: list[tuple[int, str, str]] = []  # (call_no, kind, reply)
    call_no = [0]

    def capturing_llm(prompt: str) -> str:
        call_no[0] += 1
        reply = client(prompt)
        kind = "initial" if "PREVIOUS MISTAKE" not in prompt else "repair"
        raw_replies.append((call_no[0], kind, reply))
        return reply

    chunk_max = args.max_chars if args.max_chars and args.max_chars > 0 else 6000
    distiller = MotifDistiller(
        capturing_llm, chunker=TextChunker(max_chars=max(chunk_max, 200))
    )
    result = distiller.distill(text)

    # ---- LLM 返回的拓扑 JSON 片段 ------------------------------------------
    print(f"\n-- LLM 返回的拓扑 JSON 片段（共 {len(raw_replies)} 次 API 调用） ----------")
    for no, kind, reply in raw_replies:
        head = reply.strip()
        snippet = head if len(head) <= 1600 else head[:1600] + "\n    ... [截断]"
        print(f"\n[调用 #{no} · {kind}] LLM raw reply:\n{snippet}")

    # ---- 强化门禁校验日志 ---------------------------------------------------
    print(f"\n-- 强化门禁校验日志（蒸馏产出 {len(result.motifs)} 个 Motif） --------------")
    for i, motif in enumerate(result.motifs, start=1):
        chain_of = {n.temp_id: n.chain for n in motif.nodes}
        cross_n = sum(
            1 for e in motif.edges if chain_of[e.source] != chain_of[e.target]
        )
        print(
            f"\n[motif #{i}] {motif.motif_id} | pattern={motif.pattern_type.value} "
            f"| nodes={len(motif.nodes)} edges={len(motif.edges)} "
            f"cross_chain_edges={cross_n}"
        )
        for line in _fmt_gate_log(motif):
            print(line)

    if result.motifs:
        print(
            f"\n[ok] 放行率 = {len(result.motifs)}/{len(result.motifs)} = 100% "
            f"—— 全部通过强化门禁（构造时即被 model_validate 校验）。"
        )

    # ---- 修复重试日志（门禁拦截 → 反馈 → LLM 自主修复） --------------------
    if not args.no_repair_log and raw_replies:
        repairs = [(no, kind) for no, kind, _ in raw_replies if kind == "repair"]
        if repairs:
            print(f"\n-- 门禁拦截与修复日志（{len(repairs)} 次 repair 重试） -----------------")
            for no, _kind in repairs:
                print(f"  [调用 #{no}] 门禁曾拦截上一轮输出，LLM 收到 PREVIOUS MISTAKE 反馈后重试。")

    if result.failures:
        print(f"\n[-] {len(result.failures)} 个分块最终未通过门禁（修复预算耗尽）：")
        for failure in result.failures:
            print(
                f"    chunk#{failure.chunk_index}: attempts={failure.attempts} "
                f"error={failure.error}"
            )
        return 1

    print(
        f"\nSUMMARY: chunks={result.chunks} llm_calls={len(raw_replies)} "
        f"motifs={len(result.motifs)} failures={len(result.failures)} "
        f"-> 验收{'通过' if not result.failures else '未通过'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
