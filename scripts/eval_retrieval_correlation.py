#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/eval_retrieval_correlation.py
----------------------------------------------------------------------
阶段 3（Part A）学术对比评测：Dense 稠密嵌入 vs Discrete 离散基线
双轨检索候选排序相关性（Spearman's ρ 与 p-value）。

核心原则：
- **只读只度量流**：知识库以只读方式加载，评测前后校验 SHA-256，
  绝不写入、追加或污染生产物理资产 `distilled_kb.json`；
- **无微观噪声红线**：全部评测 Query 均为抽象语义描述，不含真实钱包
  地址、代币符号、微观金额、Gas 费或时间戳；
- **环境友好**：无外网/无 GPU 环境下 Dense Provider 自动降级为离散
  哈希保底引擎并如实标注 backend；本脚本零第三方统计依赖（Spearman
  与 t 近似 p-value 为纯 Python 实现）。

用法:
    python scripts/eval_retrieval_correlation.py \
        [--kb experiments/phase2_distillation_empirical/distilled_kb.json] \
        [--out experiments/phase3_dense_retrieval/dense_vs_discrete_correlation.json] \
        [--alpha 0.5] [--top-k 18] [--min-depth 6] \
        [--model-name all-MiniLM-L6-v2]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aml_rag import (  # noqa: E402
    AbstractNode,
    CurrentState,
    DenseEmbeddingProvider,
    DiscreteEmbeddingProvider,
    DualTrackMotifRetriever,
    MotifKnowledgeBase,
    NodeRole,
    QueryContext,
)

#: 生产物理知识库（只读加载，评测后校验未被污染）。
DEFAULT_KB_PATH = (
    PROJECT_ROOT / "experiments" / "phase2_distillation_empirical" / "distilled_kb.json"
)
#: 实验资产归档目录（阶段 3 Part A 专用）。
DEFAULT_OUT_PATH = (
    PROJECT_ROOT
    / "experiments"
    / "phase3_dense_retrieval"
    / "dense_vs_discrete_correlation.json"
)
#: 硬门禁幸存者数低于该阈值时，改用 soft fallback 全量排序以获取更深的
#: 排序样本（门禁本身不因此失效——报告会如实记录两种语料来源）。
MIN_RANK_DEPTH = 6

# ---------------------------------------------------------------------------
# 纯 Python 统计工具（零第三方依赖）
# ---------------------------------------------------------------------------
def rankdata(values: list[float]) -> list[float]:
    """Average ranks (tie-corrected), 1-based."""
    n = len(values)
    order = sorted(range(n), key=lambda i: (values[i], i))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx == 0.0 or vy == 0.0:
        return 1.0 if vx == 0.0 and vy == 0.0 else 0.0
    return cov / math.sqrt(vx * vy)


def spearman_rho(x: list[float], y: list[float]) -> float:
    """Spearman 等级相关系数 ρ（并列值取平均秩）。"""
    if len(x) < 2 or len(x) != len(y):
        raise ValueError("spearman_rho needs two equal-length series (n >= 2)")
    return _pearson(rankdata(x), rankdata(y))


def _log_gamma(x: float) -> float:
    """ln Γ(x) — Lanczos approximation (Numerical Recipes style)."""
    coeffs = [
        0.99999999999980993,
        676.5203681218851,
        -1259.1392167224028,
        771.32342877765313,
        -176.61502916214059,
        12.507343278686905,
        -0.13857109526572012,
        9.9843695780195716e-6,
        1.5056327351493116e-7,
    ]
    if x < 0.5:
        return math.log(math.pi / math.sin(math.pi * x)) - _log_gamma(1.0 - x)
    x -= 1.0
    a = coeffs[0]
    t = x + 7.0 + 0.5
    for i, c in enumerate(coeffs[1:], start=1):
        a += c / (x + i)
    return 0.5 * math.log(2.0 * math.pi) + (x + 0.5) * math.log(t) - t + math.log(a)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta I_x(a, b)."""
    max_iter = 200
    eps = 3e-14
    fp_min = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fp_min:
        d = fp_min
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fp_min:
            d = fp_min
        c = 1.0 + aa / c
        if abs(c) < fp_min:
            c = fp_min
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fp_min:
            d = fp_min
        c = 1.0 + aa / c
        if abs(c) < fp_min:
            c = fp_min
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        a * math.log(x)
        + b * math.log(1.0 - x)
        + _log_gamma(a + b)
        - _log_gamma(a)
        - _log_gamma(b)
    )
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def spearman_p_value(rho: float, n: int) -> float | None:
    """双尾 p-value：Student-t 近似 (t = ρ√((n−2)/(1−ρ²)), df = n−2)。"""
    if n < 3:
        return None
    if abs(rho) >= 1.0 - 1e-12:
        return 0.0
    t = rho * math.sqrt((n - 2) / (1.0 - rho * rho))
    df = n - 2
    return 2.0 * 0.5 * _regularized_beta(df / (df + t * t), df / 2.0, 0.5)


# ---------------------------------------------------------------------------
# 基准查询集（抽象反洗钱语义，零微观噪声）
# ---------------------------------------------------------------------------
BENCHMARK_QUERIES: list[dict[str, Any]] = [
    {
        "query_id": "cross_chain_hop",
        "scenario": "Operator moves proceeds across multiple chains to escape monitoring.",
        "tactic_goal": "bridge assets through several chains before consolidation",
        "state": {"level": 2, "chain": "Chain_A", "roles": ["Asset_Conversion"]},
    },
    {
        "query_id": "large_split_fanout",
        "scenario": "Bulk funds need fragmentation into many small parallel streams.",
        "tactic_goal": "split into many branches across successive layers",
        "state": {"level": 1, "chain": "Chain_A", "roles": ["Intermediate"]},
    },
    {
        "query_id": "dex_swap_obfuscation",
        "scenario": "Proceeds routed through liquidity pools to break origin traceability.",
        "tactic_goal": "swap through a decentralized exchange pool",
        "state": {"level": 0, "chain": "Chain_A", "roles": ["Source"]},
    },
    {
        "query_id": "iterative_peeling",
        "scenario": "Small rapid transfers through fresh single-use intermediaries.",
        "tactic_goal": "peel value along a linear chain of hops",
        "state": {"level": 0, "chain": "Chain_A", "roles": ["Source"]},
    },
    {
        "query_id": "mixer_anonymization",
        "scenario": "Many sources pooled and mixed then redistributed to hide linkage.",
        "tactic_goal": "merge streams then split into anonymised withdrawals",
        "state": {"level": 2, "chain": "Chain_A", "roles": ["Aggregator"]},
    },
    {
        "query_id": "many_to_one_consolidation",
        "scenario": "Scattered inflows from many accounts converge into a few exit points.",
        "tactic_goal": "consolidate streams into a single target",
        "state": {"level": 2, "chain": "Chain_A", "roles": ["Aggregator"]},
    },
    {
        "query_id": "bridge_round_trip",
        "scenario": "Assets leave and return through bridges to launder between chains.",
        "tactic_goal": "round-trip bridge movement with an intermediary stop",
        "state": {"level": 3, "chain": "Chain_A", "roles": ["Cross_Chain"]},
    },
    {
        "query_id": "multi_swap_layering",
        "scenario": "Repeated same-chain conversions to blur the audit trail.",
        "tactic_goal": "sequence of swaps across conversion nodes",
        "state": {"level": 1, "chain": "Chain_A", "roles": ["Asset_Conversion"]},
    },
]


def _build_state(spec: dict[str, Any]) -> CurrentState:
    roles = [NodeRole(r) for r in spec["roles"]]
    chain, level = spec["chain"], int(spec["level"])
    return CurrentState(
        current_level=level,
        current_chain=chain,
        active_nodes=[
            AbstractNode(temp_id=f"N{i}", role=r, chain=chain, level=level)
            for i, r in enumerate(roles)
        ],
    )


def _run_query(
    kb: MotifKnowledgeBase,
    query_spec: dict[str, Any],
    dense_retriever: DualTrackMotifRetriever,
    discrete_retriever: DualTrackMotifRetriever,
    top_k: int,
    min_depth: int,
) -> dict[str, Any]:
    state = _build_state(query_spec["state"])
    query = QueryContext(
        scenario=query_spec["scenario"], tactic_goal=query_spec["tactic_goal"]
    )

    dense_strict = dense_retriever.retrieve(state, query, top_k=top_k)
    disc_strict = discrete_retriever.retrieve(state, query, top_k=top_k)
    strict_n = len(dense_strict)

    corpus = "strict_gate"
    if strict_n < min_depth:
        # 硬门禁幸存者不足：改用 soft fallback 采集更深的全量排序样本。
        # 注意：这不会放宽评测口径中“门禁”本身的有效性，仅扩充相关样本。
        corpus = "soft_fallback"
        dense_rank = dense_retriever.retrieve(state, query, top_k=top_k, strict=False)
        disc_rank = discrete_retriever.retrieve(state, query, top_k=top_k, strict=False)
    else:
        dense_rank, disc_rank = dense_strict, disc_strict

    dense_ids = [r.motif_id for r in dense_rank]
    disc_ids = [r.motif_id for r in disc_rank]
    dense_scores = {r.motif_id: r.combined_score for r in dense_rank}
    disc_scores = {r.motif_id: r.combined_score for r in disc_rank}

    # 门禁结果与嵌入后端无关，两模式候选集一致；取交集以防御性对齐。
    common = [mid for mid in dense_ids if mid in disc_scores]
    n = len(common)
    rho = spearman_rho(
        [dense_scores[mid] for mid in common], [disc_scores[mid] for mid in common]
    ) if n >= 2 else None
    p_value = spearman_p_value(rho, n) if rho is not None else None

    def _margin(ids: list[str], scores: dict[str, float]) -> float | None:
        if len(ids) < 2:
            return None
        return round(scores[ids[0]] - scores[ids[1]], 4)

    return {
        "query_id": query_spec["query_id"],
        "scenario": query_spec["scenario"],
        "tactic_goal": query_spec["tactic_goal"],
        "state": query_spec["state"],
        "strict_gate_survivors": strict_n,
        "corpus": corpus,
        "n": n,
        "spearman_rho": round(rho, 6) if rho is not None else None,
        "p_value": round(p_value, 6) if p_value is not None else None,
        "top1_agree": bool(dense_ids and dense_ids[0] == disc_ids[0]),
        "dense_ranking": dense_ids,
        "discrete_ranking": disc_ids,
        "dense_top1_margin": _margin(dense_ids, dense_scores),
        "discrete_top1_margin": _margin(disc_ids, disc_scores),
    }


def _print_table(query_rows: list[dict[str, Any]]) -> None:
    header = (
        f"{'query':28s} {'n':>3s} {'corpus':13s} {'rho':>8s} {'p':>9s} "
        f"{'top1_agree':>10s} {'dense_top1':24s} {'disc_top1':24s}"
    )
    print(header)
    print("-" * len(header))
    for row in query_rows:
        rho = f"{row['spearman_rho']:.4f}" if row["spearman_rho"] is not None else "n/a"
        p = f"{row['p_value']:.4g}" if row["p_value"] is not None else "n/a"
        dense_top1 = row["dense_ranking"][0] if row["dense_ranking"] else "-"
        disc_top1 = row["discrete_ranking"][0] if row["discrete_ranking"] else "-"
        print(
            f"{row['query_id']:28s} {row['n']:3d} {row['corpus']:13s} "
            f"{rho:>8s} {p:>9s} {str(row['top1_agree']):>10s} "
            f"{dense_top1:24s} {disc_top1:24s}"
        )


def main() -> int:
    # 脚本自行感知并如实报告降级状态（见控制台 [!] 提示），无需重复告警。
    warnings.filterwarnings(
        "ignore",
        message=r"DenseEmbeddingProvider.*degraded",
        category=RuntimeWarning,
    )

    parser = argparse.ArgumentParser(
        description="阶段3(Part A) Dense vs Discrete 双轨检索排序相关性评测"
    )
    parser.add_argument("--kb", default=str(DEFAULT_KB_PATH), help="知识库 JSON 路径（只读）")
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH), help="评测报告 JSON 输出路径")
    parser.add_argument("--alpha", type=float, default=0.5, help="语义轨融合权重 α")
    parser.add_argument("--top-k", type=int, default=18, help="每个 Query 的候选召回上限")
    parser.add_argument("--min-depth", type=int, default=MIN_RANK_DEPTH, help="门禁幸存者阈值")
    parser.add_argument("--coarse-k", type=int, default=None, help="粗排窗口大小（默认不限）")
    parser.add_argument("--model-name", default="all-MiniLM-L6-v2", help="Dense 模型名")
    args = parser.parse_args()

    if not 0.0 <= args.alpha <= 1.0:
        print("[-] 错误：alpha 必须在 [0, 1] 区间内")
        return 1

    kb_path = Path(args.kb)
    if not kb_path.exists():
        print(f"[-] 错误：找不到知识库文件 {kb_path}")
        return 1

    # ---- 只读加载 + 前后 SHA-256 校验（污染防护） -------------------------
    sha_before = hashlib.sha256(kb_path.read_bytes()).hexdigest()
    kb = MotifKnowledgeBase.load(kb_path)

    # ---- 双模态 Provider 与检索器（对称配置） ------------------------------
    dense_provider = DenseEmbeddingProvider(model_name=args.model_name)
    discrete_provider = DiscreteEmbeddingProvider()
    dense_retriever = DualTrackMotifRetriever(
        kb, embedder=dense_provider, alpha=args.alpha, top_k=args.top_k, coarse_k=args.coarse_k
    )
    discrete_retriever = DualTrackMotifRetriever(
        kb,
        embedder=discrete_provider,
        alpha=args.alpha,
        top_k=args.top_k,
        coarse_k=args.coarse_k,
    )

    print(
        f"== 阶段3(Part A) 检索排序相关性评测 | alpha={args.alpha:.2f} "
        f"| top_k={args.top_k} | coarse_k={args.coarse_k} | kb={len(kb)} motifs =="
    )

    # ---- 逐 Query 采集双模式排序 ------------------------------------------
    query_rows: list[dict[str, Any]] = []
    for spec in BENCHMARK_QUERIES:
        row = _run_query(
            kb, spec, dense_retriever, discrete_retriever, args.top_k, args.min_depth
        )
        query_rows.append(row)

    # ---- 摘要统计 ----------------------------------------------------------
    rhos = [r["spearman_rho"] for r in query_rows if r["spearman_rho"] is not None]
    pvals = [r["p_value"] for r in query_rows if r["p_value"] is not None]
    top1_agreements = sum(1 for r in query_rows if r["top1_agree"])
    corpora = {}
    for r in query_rows:
        corpora[r["corpus"]] = corpora.get(r["corpus"], 0) + 1

    sha_after = hashlib.sha256(kb_path.read_bytes()).hexdigest()
    read_only_verified = sha_before == sha_after

    note = ""
    if dense_provider.degraded:
        note = (
            "dense backend degraded to discrete hash fallback (sentence-transformers "
            "not installed); observed rho ~ 1.0 is expected — install 'aml-rag[dense]' "
            "to benchmark the real pre-trained model."
        )

    report: dict[str, Any] = {
        "experiment": "phase3_partA_dense_vs_discrete_retrieval_correlation",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "alpha": args.alpha,
            "top_k": args.top_k,
            "min_rank_depth": args.min_depth,
            "coarse_k": args.coarse_k,
            "dense_model_name": args.model_name,
            "dense_backend": dense_provider.backend,
            "discrete_backend": discrete_provider.backend,
        },
        "kb_source": {
            "path": str(kb_path),
            "n_motifs": len(kb),
            "sha256": sha_before,
        },
        "queries": query_rows,
        "summary": {
            "n_queries": len(query_rows),
            "mean_rho": round(sum(rhos) / len(rhos), 6) if rhos else None,
            "min_rho": round(min(rhos), 6) if rhos else None,
            "max_rho": round(max(rhos), 6) if rhos else None,
            "n_significant_p_lt_005": sum(1 for p in pvals if p < 0.05),
            "top1_agreement_rate": round(top1_agreements / len(query_rows), 4),
            "corpora_used": corpora,
            "kb_read_only_verified": read_only_verified,
            "note": note,
        },
    }

    # ---- 控制台易读汇总表 --------------------------------------------------
    _print_table(query_rows)
    print("-" * 76)
    print(
        f"summary: mean_rho={report['summary']['mean_rho']} "
        f"top1_agree={top1_agreements}/{len(query_rows)} "
        f"corpora={corpora} "
        f"dense_backend={dense_provider.backend}"
    )
    print(f"kb read-only verified={read_only_verified} (sha256 unchanged)")
    if note:
        print(f"[!] {note}")

    # ---- 实验资产落位 ------------------------------------------------------
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[+] 量化分析报告已归档 -> {out_path.resolve()}")
    if not read_only_verified:
        print("[-] 严重告警：知识库 SHA-256 前后不一致，评测流可能污染了生产资产！")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
