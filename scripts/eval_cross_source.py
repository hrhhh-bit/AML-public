#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/eval_cross_source.py
----------------------------------------------------------------------
真实研报跨源一致性经验检验脚本（Check 2 专项实证）
对齐 CertiK 与 Zerion 针对 2022 Nomad Bridge 事件的真实报告，
量化评估边算子签名 Jaccard 相似度与微观噪声纯净度。
----------------------------------------------------------------------
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

from aml_agent import LLMClient  # noqa: E402
from aml_rag import (  # noqa: E402
    MotifDistiller,
    cross_source_consistency,
    topology_validity,
    zero_noise_audit,
)


def _dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Nomad Bridge 真实研报跨源一致性检验")
    parser.add_argument(
        "--file-a",
        default=str(PROJECT_ROOT / "resources" / "cross_source_test" / "nomad_certik.txt"),
        help="源 A 文件路径 (CertiK 官方博客)",
    )
    parser.add_argument(
        "--file-b",
        default=str(PROJECT_ROOT / "resources" / "cross_source_test" / "nomad_zerion.txt"),
        help="源 B 文件路径 (Zerion 追踪报告)",
    )
    parser.add_argument("--name-a", default="CertiK", help="机构标识 A")
    parser.add_argument("--name-b", default="Zerion", help="机构标识 B")
    parser.add_argument(
        "--out-file",
        default=str(
            PROJECT_ROOT
            / "experiments"
            / "phase2_distillation_empirical"
            / "cross_source_consistency_nomad.json"
        ),
        help="结果归档路径",
    )
    parser.add_argument("--model", default=None, help="模型名称 (默认 deepseek-flash)")
    parser.add_argument("--base-url", default=None, help="API Base URL 覆盖")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP 超时时间(s)")
    args = parser.parse_args()

    path_a = Path(args.file_a)
    path_b = Path(args.file_b)

    if not path_a.exists():
        print(f"[-] 错误：找不到源文件 A: {path_a}")
        return 1
    if not path_b.exists():
        print(f"[-] 错误：找不到源文件 B: {path_b}")
        return 1

    text_a = path_a.read_text(encoding="utf-8")
    text_b = path_b.read_text(encoding="utf-8")

    # 1. 初始化客户端与 Distiller
    client = LLMClient(model=args.model, base_url=args.base_url, timeout=args.timeout)
    distiller = MotifDistiller(client)

    print(f"== 启动 Nomad Bridge 跨源经验检验 (model={client.model}) ==")
    print(f"  源 A [{args.name_a}]: {path_a}")
    print(f"  源 B [{args.name_b}]: {path_b}")

    # 2. 依次蒸馏两份研报
    print(f"\n[+] 正在蒸馏源 A ({args.name_a})...")
    res_a = distiller.distill(text_a)
    print(f"    -> chunks={res_a.chunks}, motifs={len(res_a.motifs)}, failures={len(res_a.failures)}")

    print(f"[+] 正在蒸馏源 B ({args.name_b})...")
    res_b = distiller.distill(text_b)
    print(f"    -> chunks={res_b.chunks}, motifs={len(res_b.motifs)}, failures={len(res_b.failures)}")

    # 3. 核心检验二：跨源一致性 (Jaccard 拓扑边签名相似度)
    print("\n[+] 正在计算跨源一致性 (Check 2)...")
    consistency = cross_source_consistency({args.name_a: res_a.motifs, args.name_b: res_b.motifs})

    # 4. 连带检验：微观噪声绝对净化 (Check 3) 与 拓扑合法率 (Check 1)
    noise_a = zero_noise_audit(res_a.motifs)
    noise_b = zero_noise_audit(res_b.motifs)
    validity_a = topology_validity(res_a.motifs)
    validity_b = topology_validity(res_b.motifs)

    # 5. 组装量化报告
    report: dict[str, Any] = {
        "sources": {
            args.name_a: {"path": str(path_a), "chunks": res_a.chunks, "motifs": len(res_a.motifs)},
            args.name_b: {"path": str(path_b), "chunks": res_b.chunks, "motifs": len(res_b.motifs)},
        },
        "check2_cross_source_consistency": consistency.model_dump(),
        "zero_noise_audit": {
            f"{args.name_a}_residue_count": noise_a.residue_count,
            f"{args.name_b}_residue_count": noise_b.residue_count,
            "all_passed": (noise_a.residue_count == 0 and noise_b.residue_count == 0),
        },
        "topology_validity": {
            f"{args.name_a}_valid_rate": validity_a.valid_rate,
            f"{args.name_b}_valid_rate": validity_b.valid_rate,
        },
    }

    # 6. 控制台打印与持久化
    print("\n== 跨源实证量化报告 ==")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    out_file = Path(args.out_file)
    _dump(report, out_file)
    print(f"\n[+] 检验凭据已成功安全归档至: {out_file}")
    print("[*] 提示：distilled_kb.json 知识库未受任何变动与污染。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())