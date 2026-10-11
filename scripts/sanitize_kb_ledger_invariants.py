#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/sanitize_kb_ledger_invariants.py
----------------------------------------------------------------------
阶段 3（Part B 前置）生产知识库账本公理原地规范化脚本。

对 `data/distilled_kb.json` 执行最小化、可复现、幂等的自洽清洗：

- R1 跨链账本动作闭环：源/目标节点 Chain 不一致的边，操作语义就地修正为
  标准跨链原语 ``Bridge``（大小写鲁棒判定，顺带把非规范大小写归一）；
- R2 单出边流出守恒：单出边节点被误填的入流权重一律纠正为 ``1.0``
  （``flow_share`` 严格 = 节点局部出边分配比例）；
- R3 多出边守恒体检：Split 等真实分配语义的节点出边组必须守恒，违反则
  中止报错，绝不擅自篡改语义比例。

流程保证：只读加载 -> 最小修正 -> 强化后 Schema 全量重构验证 ->
零微观噪声审计 -> 原子落盘（tmp + replace）。二次运行 0 修正（幂等）。

用法:
    python scripts/sanitize_kb_ledger_invariants.py [--kb data/distilled_kb.json] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aml_rag import MotifKnowledgeBase, zero_noise_audit  # noqa: E402
from aml_rag.schema import FLOW_TOLERANCE  # noqa: E402

DEFAULT_KB_PATH = PROJECT_ROOT / "data" / "distilled_kb.json"


def _fixes_for(motif: dict[str, Any]) -> tuple[list[str], bool]:
    """Apply R1/R2/R3 to one raw motif dict; returns (fix_log, fatal_error)."""
    fixes: list[str] = []
    nodes = motif["nodes"]
    edges = motif["edges"]
    chain_of = {n["temp_id"]: n["chain"] for n in nodes}

    # R1: cross-chain edges MUST be Bridge (case-robust, then canonicalised)
    for edge in edges:
        src_chain = chain_of[edge["source"]]
        tgt_chain = chain_of[edge["target"]]
        op = str(edge["operation"])
        if src_chain != tgt_chain:
            if op.lower() != "bridge":
                fixes.append(
                    f"R1 cross-chain {edge['source']}->{edge['target']} "
                    f"({src_chain}->{tgt_chain}): op '{op}' -> 'Bridge'"
                )
                edge["operation"] = "Bridge"
            elif op != "Bridge":
                fixes.append(
                    f"R1 case-normalise {edge['source']}->{edge['target']}: "
                    f"op '{op}' -> 'Bridge'"
                )
                edge["operation"] = "Bridge"

    # out-flow conservation per node
    out_groups: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        out_groups.setdefault(edge["source"], []).append(edge)

    for nid, group in out_groups.items():
        shares = [float(e.get("flow_share", 1.0)) for e in group]
        if len(group) == 1:
            # R2: single out-edge must forward 100% of the flow
            if abs(shares[0] - 1.0) > FLOW_TOLERANCE:
                fixes.append(
                    f"R2 single out-edge {nid}->{group[0]['target']}: "
                    f"flow_share {shares[0]} -> 1.0"
                )
                group[0]["flow_share"] = 1.0
        else:
            # R3: real distribution semantics (Split) must stay conserved
            if abs(sum(shares) - 1.0) > FLOW_TOLERANCE:
                return fixes, (
                    f"R3 fatal: motif '{motif['motif_id']}' node '{nid}' "
                    f"multi out-edges sum={sum(shares):.4f} violates "
                    f"conservation (tolerance {FLOW_TOLERANCE}) — manual review "
                    f"required, refusing to guess split semantics."
                )
    return fixes, False


def main() -> int:
    parser = argparse.ArgumentParser(description="生产知识库账本公理原地规范化")
    parser.add_argument("--kb", default=str(DEFAULT_KB_PATH), help="知识库 JSON 路径")
    parser.add_argument("--dry-run", action="store_true", help="只报告修正清单，不落盘")
    args = parser.parse_args()

    kb_path = Path(args.kb)
    if not kb_path.exists():
        print(f"[-] 错误：找不到知识库 {kb_path}")
        return 1

    sha_before = hashlib.sha256(kb_path.read_bytes()).hexdigest()
    payload: Any = json.loads(kb_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        print("[-] 错误：知识库 JSON 必须是 Motif 列表")
        return 1

    all_fixes: list[str] = []
    fatal: str | None = None
    for motif in payload:
        fixes, fatal = _fixes_for(motif)
        all_fixes.extend(fixes)
        if fatal:
            print(f"[-] {fatal}")
            return 1

    print(f"== 账本公理规范化 | kb={kb_path} | motifs={len(payload)} ==")
    if not all_fixes:
        print("[ok] 未发现违规条目：知识库已自洽，无需修正。")
    else:
        for fix in all_fixes:
            print(f"  [+fix] {fix}")

    # ---- 强化后 Schema 全量重构验证 + 零噪声审计 -------------------------
    canonical = json.dumps(payload, ensure_ascii=False, indent=2)
    kb = MotifKnowledgeBase.from_json_str(canonical)
    print(f"[ok] 强化门禁重构验证：{len(kb)} 个 Motif 全部通过 "
          f"（跨链动作公理 + 出边守恒公理）。")
    noise = zero_noise_audit(kb)
    if noise.residue_count != 0:
        print(f"[-] 严重告警：零噪声审计残留 {noise.residue_count} 处微观噪声！")
        return 1
    print(f"[ok] 零微观噪声审计：residue_count={noise.residue_count}。")

    if args.dry_run:
        print("[*] dry-run：未执行落盘。")
        return 0

    if all_fixes:
        tmp = kb_path.with_suffix(kb_path.suffix + ".tmp")
        tmp.write_text(canonical, encoding="utf-8")
        tmp.replace(kb_path)
        sha_after = hashlib.sha256(kb_path.read_bytes()).hexdigest()
        print(f"[+] 原子落盘完成：{kb_path.resolve()}")
        print(f"    sha256 before={sha_before}")
        print(f"    sha256 after ={sha_after}")
        if sha_before == sha_after:
            print("[-] 告警：落盘前后哈希一致（未发生任何变更）。")
    else:
        print("[*] 无需落盘：知识库已符合账本公理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
