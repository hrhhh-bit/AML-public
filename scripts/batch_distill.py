#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage-3 Part B: 14 篇黄金研报批量蒸馏与知识库扩容批处理调度器。

职责
----
1. 从 ``data/raw_reports/manifest.csv`` 读取 ``has_fund_flow == 1`` 的 14 篇
   黄金研报（数量必须恰好为 14，否则拒绝执行）；
2. 按既有滑动窗口分块（:class:`~aml_rag.distiller.TextChunker`）与反思自愈
   机制（:class:`~aml_rag.distiller.MotifDistiller`）逐篇蒸馏，单篇反思重试
   上限 3 次；
3. 重试耗尽仍未通过 Kahn 无环 / 守恒门禁的分块执行**物理丢弃**并记入隔离
   日志 ``quarantine_log.json``；
4. 经“方向 A”流向原型分桶 + VF2 三要件同构判定（拓扑同构 + 边动作基 Σ
   相同 + 流向原型相同）去重后合入知识库；
5. 全流程遥测四大经验指标（合法率 / 因果对齐 / 零噪声扫描 / 模式饱和度）；
6. 扩容完成后对融合知识库执行账本公理穿透审计，通过后以**原子替换**方式
   更新 ``data/distilled_kb.json``（仅 ``--live`` 模式）。

双模运行（API 安全契约）
------------------------
- ``--dry-run``：离线自检。使用确定性 Mock LLM 跑通全流程调度、流向原型
  分桶、Schema 反序列化与落盘；零网络依赖、零 Token 消耗，**绝不触碰**
  生产知识库 ``data/distilled_kb.json``。
- ``--live``：正式生产。实际调用 ``deepseek-flash`` 端点对 14 篇黄金研报
  批量蒸馏；API Key 严禁硬编码，客户端严格通过
  ``os.environ.get("DEEPSEEK_API_KEY")`` 读取凭证。

基准防线冻结
------------
执行前必须存在 ``data/distilled_kb_v1.json`` 基准备份，且其 SHA-256 与
当前生产知识库一致，否则终止执行。

用法
----
    python scripts/batch_distill.py --dry-run
    python scripts/batch_distill.py --live
    python scripts/batch_distill.py --live --temperature 0.1 --timeout 180
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
TOOLS = PROJECT_ROOT / "tools"
for _extra in (str(PROJECT_ROOT), str(SRC), str(TOOLS)):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

from aml_agent import DEFAULT_MODEL, LLMClient  # noqa: E402
from aml_rag import (  # noqa: E402
    MotifDistiller,
    MotifKnowledgeBase,
    TextChunker,
    edge_action_basis,
    motif_topology_issues,
    node_flow_prototypes,
    vf2_isomorphism_key,
    zero_noise_audit,
)
from aml_rag.schema import TopologicalMotif  # noqa: E402
from tools.crawler.extractor import analyze_fund_flow_evidence  # noqa: E402

DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "raw_reports" / "manifest.csv"
RAW_REPORTS_DIR = PROJECT_ROOT / "data" / "raw_reports"
PRODUCTION_KB = PROJECT_ROOT / "data" / "distilled_kb.json"
BASELINE_BACKUP = PROJECT_ROOT / "data" / "distilled_kb_v1.json"
DEFAULT_OUT_DIR = PROJECT_ROOT / "experiments" / "phase3_batch_distillation"
DRY_RUN_OUT_DIR = DEFAULT_OUT_DIR / "dry_run"

EXPECTED_GOLDEN_COUNT = 14      # PRISMA 定标：黄金研报必须恰好 14 篇
MAX_REFLECTION_RETRIES = 3      # 单篇反思重试上限
DEFAULT_TEMPERATURE = 0.1
MIN_CHECK1_RATE = 0.90          # Check 1 合法率硬门禁


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def sha256_hex(path: Path) -> str:
    """计算文件的 SHA-256 十六进制摘要（大写）。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _dump(obj: Any, path: Path) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def load_golden_reports(manifest_path: Path) -> list[dict[str, str]]:
    """读取 manifest 中 ``has_fund_flow == 1`` 的黄金研报（必须恰好 14 篇）。"""
    with manifest_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    golden = [
        row for row in rows if str(row.get("has_fund_flow", "")).strip() == "1"
    ]
    if len(golden) != EXPECTED_GOLDEN_COUNT:
        raise RuntimeError(
            f"黄金研报数量异常：期望 {EXPECTED_GOLDEN_COUNT}，实际 {len(golden)}。"
            "拒绝执行（PRISMA 定标防线）。"
        )
    return golden


def enforce_baseline_freeze(kb_path: Path, backup_path: Path) -> str:
    """基准防线冻结：备份必须存在且哈希与当前生产知识库一致。"""
    if not backup_path.exists():
        raise RuntimeError(
            f"基准备份缺失：{backup_path} —— 禁止在无冻结基线的情况下执行扩容。"
        )
    backup_sha = sha256_hex(backup_path)
    if sha256_hex(kb_path) != backup_sha:
        raise RuntimeError(
            "生产知识库与冻结基线哈希不一致，终止执行（基准防线红线）。"
        )
    return backup_sha


# ---------------------------------------------------------------------------
# 离线 Mock LLM（--dry-run 专用：零网络、零 Token）
# ---------------------------------------------------------------------------
def _motif_dict(motif_id: str, kind: str) -> dict[str, Any]:
    """按种类构造合规（或不合规）的抽象 Motif 载荷。"""
    if kind == "peeling_bridge":  # 跨链逃逸 + 非对称剥皮（复合跨链 Motif）
        return {
            "motif_id": motif_id,
            "pattern_type": "Chain_Hopping",
            "description": (
                "Cross-chain escape via a bridge primitive followed by "
                "asymmetric peeled dispersal toward the final target wallet"
            ),
            "preconditions": {"min_level": 1},
            "nodes": [
                {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
                {"temp_id": "CC", "role": "Cross_Chain", "chain": "Chain_B", "level": 1},
                {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_B", "level": 2},
                {"temp_id": "M", "role": "Intermediate", "chain": "Chain_B", "level": 3},
                {"temp_id": "P", "role": "Intermediate", "chain": "Chain_B", "level": 3},
                {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 4},
            ],
            "edges": [
                {"source": "S", "target": "CC", "operation": "Bridge"},
                {"source": "CC", "target": "I1", "operation": "Transfer"},
                {"source": "I1", "target": "M", "operation": "Transfer", "flow_share": 0.85},
                {"source": "I1", "target": "P", "operation": "Transfer", "flow_share": 0.15},
                {"source": "M", "target": "T", "operation": "Transfer"},
                {"source": "P", "target": "T", "operation": "Transfer"},
            ],
            "post_state_effect": {"branch_increment": 1, "chain_transition": True,
                                  "target_chain": "Chain_B"},
            "tags": ["dry_run", "cross_chain", "peeling"],
        }
    if kind == "uniform_merge":  # 均等分流 + 汇聚
        return {
            "motif_id": motif_id,
            "pattern_type": "Multi_Layering_Split",
            "description": "Uniform fan-out into twin intermediates then consolidation into one target",
            "preconditions": {"min_level": 1},
            "nodes": [
                {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
                {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_A", "level": 1},
                {"temp_id": "I2", "role": "Intermediate", "chain": "Chain_A", "level": 1},
                {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 2},
            ],
            "edges": [
                {"source": "S", "target": "I1", "operation": "Split", "flow_share": 0.5},
                {"source": "S", "target": "I2", "operation": "Split", "flow_share": 0.5},
                {"source": "I1", "target": "T", "operation": "Merge"},
                {"source": "I2", "target": "T", "operation": "Merge"},
            ],
            "post_state_effect": {"branch_increment": -1},
            "tags": ["dry_run", "uniform_split"],
        }
    if kind == "disproportionate":  # 非对称阶梯分流
        return {
            "motif_id": motif_id,
            "pattern_type": "Multi_Layering_Split",
            "description": "Disproportionate laddered split into a dominant and a minor branch",
            "preconditions": {"min_level": 1},
            "nodes": [
                {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
                {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_A", "level": 1},
                {"temp_id": "I2", "role": "Intermediate", "chain": "Chain_A", "level": 1},
                {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 2},
            ],
            "edges": [
                {"source": "S", "target": "I1", "operation": "Split", "flow_share": 0.6},
                {"source": "S", "target": "I2", "operation": "Split", "flow_share": 0.4},
                {"source": "I1", "target": "T", "operation": "Merge"},
                {"source": "I2", "target": "T", "operation": "Merge"},
            ],
            "post_state_effect": {"branch_increment": -1},
            "tags": ["dry_run", "disproportionate_split"],
        }
    if kind == "pure_peeling":  # 单链剥皮
        return {
            "motif_id": motif_id,
            "pattern_type": "Peeling_Chain",
            "description": "Single-chain peel with a dominant main branch and a minor peeled branch",
            "preconditions": {"min_level": 0},
            "nodes": [
                {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
                {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_A", "level": 1},
                {"temp_id": "M", "role": "Intermediate", "chain": "Chain_A", "level": 2},
                {"temp_id": "P", "role": "Intermediate", "chain": "Chain_A", "level": 2},
                {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 3},
            ],
            "edges": [
                {"source": "S", "target": "I1", "operation": "Transfer"},
                {"source": "I1", "target": "M", "operation": "Transfer", "flow_share": 0.8},
                {"source": "I1", "target": "P", "operation": "Transfer", "flow_share": 0.2},
                {"source": "M", "target": "T", "operation": "Transfer"},
                {"source": "P", "target": "T", "operation": "Transfer"},
            ],
            "post_state_effect": {"branch_increment": 0},
            "tags": ["dry_run", "peeling"],
        }
    if kind == "invalid_conservation":  # 故意违反流出守恒（0.6 + 0.2 != 1.0）
        return {
            "motif_id": motif_id,
            "pattern_type": "Multi_Layering_Split",
            "description": "Invalid outflow conservation probe",
            "nodes": [
                {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
                {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_A", "level": 1},
                {"temp_id": "I2", "role": "Intermediate", "chain": "Chain_A", "level": 1},
            ],
            "edges": [
                {"source": "S", "target": "I1", "operation": "Split", "flow_share": 0.6},
                {"source": "S", "target": "I2", "operation": "Split", "flow_share": 0.2},
            ],
            "post_state_effect": {},
            "tags": ["dry_run", "invalid"],
        }
    raise ValueError(f"unknown mock motif kind: {kind}")


def _kinds_for(report_index: int) -> list[str]:
    if report_index % 3 == 0:
        return ["peeling_bridge", "disproportionate"]
    if report_index % 3 == 1:
        return ["uniform_merge", "peeling_bridge"]
    return ["pure_peeling", "uniform_merge"]


class OfflineMockLLM:
    """确定性离线 Mock LLM：零网络、零 Token。

    行为脚本（覆盖全流程分支）：
    - 正常研报：首次尝试返回守恒违规载荷 -> 触发反思自愈 -> 修复后返回
      合法 Motif 组（同构分桶去重由此自然发生）；
    - report_index == 11：首个分块永久返回守恒违规载荷 -> 重试耗尽 ->
      物理丢弃并记入隔离日志；
    - report_index == 12：首个分块永久返回不可解析垃圾 -> 解析失败 ->
      物理丢弃并记入隔离日志。
    """

    def __init__(self, report_index: int, report_id: str) -> None:
        self._report_index = report_index
        self._report_id = report_id
        self._chunk = 0
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        is_repair = "PREVIOUS MISTAKE" in prompt
        if not is_repair:
            self._chunk += 1
        chunk_no = self._chunk
        r = self._report_index

        # 隔离场景 A：守恒门禁永久拦截（仅首个分块，重试 4 次耗尽）
        if r == 11 and chunk_no == 1:
            return json.dumps([_motif_dict("QUARANTINE_CONSERVATION", "invalid_conservation")])
        # 隔离场景 B：JSON 解析永久失败（仅首个分块）
        if r == 12 and chunk_no == 1:
            return "### not a json array at all ["

        # 正常研报：首次尝试故意出错（校验反思自愈路径）
        if not is_repair:
            return json.dumps([_motif_dict("SEED_INVALID", "invalid_conservation")])

        payload = [
            _motif_dict(f"{self._report_id}__c{chunk_no:02d}__{kind}", kind)
            for kind in _kinds_for(r)
        ]
        return json.dumps(payload)


# ---------------------------------------------------------------------------
# 主流水线
# ---------------------------------------------------------------------------
def _build_live_client(
    model: str | None,
    temperature: float,
    base_url: str | None,
    timeout: float,
) -> LLMClient:
    """--live 客户端：密钥严禁硬编码，严格经环境变量读取。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少 DEEPSEEK_API_KEY 环境变量。API Key 严禁硬编码，请先设置：\n"
            "    PowerShell:  $env:DEEPSEEK_API_KEY='<your-key>'\n"
            "    Bash:        export DEEPSEEK_API_KEY='<your-key>'"
        )
    return LLMClient(
        api_key=api_key,
        base_url=base_url,
        model=model or DEFAULT_MODEL,
        temperature=temperature,
        timeout=timeout,
    )


def run_pipeline(
    mode: str,
    *,
    manifest_path: Path | None = None,
    raw_dir: Path | None = None,
    kb_path: Path | None = None,
    backup_path: Path | None = None,
    out_dir: Path | None = None,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    base_url: str | None = None,
    timeout: float = 120.0,
    mock_factory: Callable[[int, str], Any] = OfflineMockLLM,
) -> dict[str, Any]:
    """执行 14 篇黄金研报批量蒸馏 + 知识库扩容（双模）。

    :param mode: ``"dry-run"``（离线自检）或 ``"live"``（真实调用）。
    """
    assert mode in {"dry-run", "live"}, mode
    manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST
    raw_dir = Path(raw_dir) if raw_dir else RAW_REPORTS_DIR
    kb_path = Path(kb_path) if kb_path else PRODUCTION_KB
    backup_path = Path(backup_path) if backup_path else BASELINE_BACKUP
    if out_dir is None:
        out_dir = DRY_RUN_OUT_DIR if mode == "dry-run" else DEFAULT_OUT_DIR
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 基准防线冻结 ----------------------------------------------------
    backup_sha = enforce_baseline_freeze(kb_path, backup_path)
    golden = load_golden_reports(manifest_path)
    kb = MotifKnowledgeBase.load(kb_path)
    base_count = len(kb)

    model_name = model or DEFAULT_MODEL
    started = datetime.now(timezone.utc).isoformat()

    # ---- 遥测容器 --------------------------------------------------------
    saturation_curve: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    report_entries: list[dict[str, Any]] = []
    check2_rows: list[dict[str, Any]] = []
    added_motifs: list[TopologicalMotif] = []
    all_extracted: list[TopologicalMotif] = []
    call_stats = {"calls": 0, "repairs": 0}
    live_clients: list[LLMClient] = []
    total_chunks = 0
    passed_chunks = 0
    total_elapsed_s = 0.0

    # ---- 逐篇蒸馏 --------------------------------------------------------
    for index, row in enumerate(golden):
        report_id = row["report_id"]
        report_file = raw_dir / row["filename"]
        if not report_file.exists():
            raise RuntimeError(f"黄金研报正文缺失：{report_file}")

        report_text = report_file.read_text(encoding="utf-8")
        if mode == "live":
            client = _build_live_client(model, temperature, base_url, timeout)
            live_clients.append(client)
            raw_llm: Callable[[str], str] = client
        else:
            raw_llm = mock_factory(index, report_id)

        def instrumented(prompt: str, _llm: Callable[[str], str] = raw_llm) -> str:
            call_stats["calls"] += 1
            if "PREVIOUS MISTAKE" in prompt:
                call_stats["repairs"] += 1
            return _llm(prompt)

        distiller = MotifDistiller(
            instrumented,
            chunker=TextChunker(),
            max_repair_retries=MAX_REFLECTION_RETRIES,
        )
        t0 = time.perf_counter()
        result = distiller.distill(report_text)
        elapsed_s = time.perf_counter() - t0
        total_elapsed_s += elapsed_s

        extracted = len(result.motifs)
        failures = result.failures
        total_chunks += result.chunks
        passed_chunks += result.chunks - len(failures)

        # Check 1 的局部值与隔离日志（物理丢弃）
        for failure in failures:
            quarantine.append(
                {
                    "report_id": report_id,
                    "chunk_index": failure.chunk_index,
                    "attempts": failure.attempts,
                    "error": failure.error,
                    "disposition": "physically discarded",
                }
            )

        # 同构去重合并（VF2 三要件）
        ingest = kb.merge_motifs(result.motifs)
        deduplicated = len(ingest.duplicate_ids) + len(ingest.isomorphic_skips)
        net_added = len(ingest.added)
        added_motifs.extend(
            kb.get(mid) for mid in ingest.added
        )
        all_extracted.extend(result.motifs)

        # Check 2：抽取路径与原始研报资金流的对齐跳数
        evidence = analyze_fund_flow_evidence(report_text)
        motif_hops = [len(m.edges) for m in result.motifs]
        mean_hops = (sum(motif_hops) / len(motif_hops)) if motif_hops else 0.0
        check2_rows.append(
            {
                "report_id": report_id,
                "source_hop_count": evidence["hop_count"],
                "source_flow_markers": evidence["markers"][:8],
                "extracted_motif_edge_counts": motif_hops,
                "alignment_hops": round(
                    min(evidence["hop_count"], mean_hops), 2
                ) if motif_hops else 0.0,
            }
        )

        # Check 3：单篇零噪声扫描（全库必须为 0）
        noise = zero_noise_audit(result.motifs)

        saturation_curve.append(
            {
                "report_id": report_id,
                "extracted": extracted,
                "deduplicated": deduplicated,
                "net_added": net_added,
                "cumulative_total": len(kb),
            }
        )
        report_entries.append(
            {
                "report_id": report_id,
                "vendor": row.get("vendor", ""),
                "filename": row.get("filename", ""),
                "chunks": result.chunks,
                "extracted": extracted,
                "deduplicated": deduplicated,
                "net_added": net_added,
                "failed_chunks": len(failures),
                "noise_residues": noise.residue_count,
                "elapsed_s": round(elapsed_s, 3),
            }
        )

    # ---- 四重检验全流程遥测 ----------------------------------------------
    check1_rate = round(passed_chunks / total_chunks, 4) if total_chunks else 0.0
    check1 = {
        "candidate_chunks": total_chunks,
        "passed_chunks": passed_chunks,
        "pass_rate": check1_rate,
        "threshold": MIN_CHECK1_RATE,
        "passed": check1_rate >= MIN_CHECK1_RATE,
        "reflection_repairs": call_stats["repairs"],
        "reflection_retry_mean": round(
            call_stats["repairs"] / total_chunks, 4
        ) if total_chunks else 0.0,
        "llm_calls": call_stats["calls"],
    }

    check3_extracted = zero_noise_audit(all_extracted)
    check3_kb = zero_noise_audit(list(kb))
    check3 = {
        "extracted_residues": check3_extracted.residue_count,
        "kb_residues": check3_kb.residue_count,
        "violations": check3_kb.violations,
        "passed": check3_extracted.residue_count == 0 and check3_kb.residue_count == 0,
    }

    # ---- 全库穿透审计（账本公理） ----------------------------------------
    ledger_issues: dict[str, list[str]] = {}
    for m in kb:
        issues = motif_topology_issues(m)
        if issues:
            ledger_issues[m.motif_id] = issues
    audit_clean = not ledger_issues

    # ---- 落盘与原子提升 --------------------------------------------------
    if mode == "live":
        if not (audit_clean and check3["passed"]):
            raise RuntimeError(
                "全库穿透审计或零噪声扫描未通过，禁止原子替换生产知识库。"
                f" ledger_issues={ledger_issues} noise={check3}"
            )
        kb.save(kb_path)  # 原子替换（临时文件 + replace）
    else:
        kb.save(out_dir / "distilled_kb_preview.json")  # 仅预览，不触碰生产

    # ---- 交付产物 --------------------------------------------------------
    commit = _git_commit()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    meta_config = (
        f"model={model_name}\n"
        f"temperature={temperature}\n"
        f"mode={mode}\n"
        f"timestamp={timestamp}\n"
        f"git_commit={commit}\n"
        f"baseline_backup={backup_path.name}\n"
        f"baseline_sha256={backup_sha}\n"
        f"golden_report_count={len(golden)}\n"
        "report_ids=\n"
        + "\n".join(f"  - {r['report_id']}" for r in golden)
        + "\n"
    )

    # 样例沉淀：优先选取含 Bridge 原语的新增复杂跨链 Motif（2~3 个）
    bridge_added = [
        m for m in added_motifs
        if any(e.operation.value == "Bridge" for e in m.edges)
    ]
    sample_pool = bridge_added + [m for m in added_motifs if m not in bridge_added]
    sample_motifs = []
    seen_sample_ids: set[str] = set()
    for m in sample_pool:
        if len(sample_motifs) >= 3 or m.motif_id in seen_sample_ids:
            continue
        seen_sample_ids.add(m.motif_id)
        sample_motifs.append(
            {
                **m.model_dump(mode="json"),
                "flow_prototype_profile": {
                    nid: proto.value
                    for nid, proto in node_flow_prototypes(m).items()
                },
                "edge_action_basis": list(edge_action_basis(m)),
            }
        )

    artifacts = {
        "meta_config.txt": meta_config,
        "distillation_report.json": {},
        "saturation_curve.json": saturation_curve,
        "sample_extracted_motifs.json": sample_motifs,
        "quarantine_log.json": quarantine,
    }
    token_summary: dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_latency_ms": 0.0,
        "total_calls": call_stats["calls"],
    }
    if mode == "live":
        for client in live_clients:
            snap = client.metrics.snapshot()
            token_summary["prompt_tokens"] += snap.get("prompt_tokens", 0)
            token_summary["completion_tokens"] += snap.get("completion_tokens", 0)
            token_summary["total_latency_ms"] += snap.get("total_latency_ms", 0.0)
    token_summary["total_latency_ms"] = round(token_summary["total_latency_ms"], 2)

    report: dict[str, Any] = {
        "mode": mode,
        "model": model_name,
        "temperature": temperature,
        "timestamp": timestamp,
        "git_commit": commit,
        "baseline_sha256": backup_sha,
        "golden_report_ids": [r["report_id"] for r in golden],
        "base_motif_count": base_count,
        "final_motif_count": len(kb),
        "net_added": len(kb) - base_count,
        "check1_legality": check1,
        "check2_causal_alignment": check2_rows,
        "check3_zero_noise": check3,
        "check4_saturation": saturation_curve,
        "ledger_audit": {"clean": audit_clean, "issues": ledger_issues},
        "quarantine_count": len(quarantine),
        "per_report": report_entries,
        "token_and_latency": token_summary,
        "total_elapsed_s": round(total_elapsed_s, 3),
        "production_kb_updated": mode == "live",
    }
    artifacts["distillation_report.json"] = report

    artifact_sha: dict[str, str] = {}
    for name, payload in artifacts.items():
        path = out_dir / name
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            _dump(payload, path)
        artifact_sha[name] = sha256_hex(path)
    report["artifact_sha256"] = artifact_sha
    report["out_dir"] = str(out_dir)
    # 摘要追加后回写 report（含自身哈希无法包含自身，记录其余产物即可）
    _dump(report, out_dir / "distillation_report.json")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="14 篇黄金研报批量蒸馏与知识库扩容（双模调度器）"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="离线自检（零网络零 Token）")
    group.add_argument("--live", action="store_true", help="正式生产：真实调用 deepseek-flash")
    parser.add_argument("--out-dir", default=None, help="产物输出目录（覆盖默认）")
    parser.add_argument("--model", default=None, help=f"模型名（默认 {DEFAULT_MODEL}）")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE,
                        help="采样温度（默认 0.1）")
    parser.add_argument("--base-url", default=None, help="API Base URL 覆盖")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP 超时(s)")
    args = parser.parse_args()

    mode = "live" if args.live else "dry-run"
    if mode == "live":
        # 提前校验密钥契约（严禁硬编码），避免蒸馏中途才失败
        _build_live_client(args.model, args.temperature, args.base_url, args.timeout)

    out_dir = Path(args.out_dir) if args.out_dir else None
    report = run_pipeline(
        mode,
        out_dir=out_dir,
        model=args.model,
        temperature=args.temperature,
        base_url=args.base_url,
        timeout=args.timeout,
    )

    print("\n== 批量蒸馏验收总结 ==")
    print(
        f"mode={report['mode']} model={report['model']} "
        f"temperature={report['temperature']}"
    )
    print(
        f"final_motif_count={report['final_motif_count']} "
        f"(base={report['base_motif_count']}, net_added={report['net_added']})"
    )
    c1 = report["check1_legality"]
    print(
        f"Check1 合法率: {c1['pass_rate']*100:.2f}% ({c1['passed_chunks']}/"
        f"{c1['candidate_chunks']}) 阈值>={MIN_CHECK1_RATE*100:.0f}% "
        f"-> {'PASS' if c1['passed'] else 'FAIL'}"
    )
    c3 = report["check3_zero_noise"]
    print(
        f"Check3 零噪声: extracted={c3['extracted_residues']} "
        f"kb={c3['kb_residues']} -> {'PASS' if c3['passed'] else 'FAIL'}"
    )
    print(
        f"Check4 饱和度曲线: {len(report['check4_saturation'])} 篇；"
        f"隔离丢弃 {report['quarantine_count']} 个分块"
    )
    print(
        f"账本公理穿透审计: {'CLEAN' if report['ledger_audit']['clean'] else report['ledger_audit']['issues']}"
    )
    print(f"生产知识库已原子更新: {report['production_kb_updated']}")
    print(f"产物目录: {report['out_dir']}")
    print("产物 SHA-256:")
    for name, digest in report["artifact_sha256"].items():
        print(f"  {name}: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
