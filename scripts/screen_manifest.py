"""PRISMA 资格准入自动化辅助核验流水线（has_fund_flow 定标）。

职责
----
对 ``data/raw_reports/manifest.csv`` 中的全部研报正文执行资格准入判定：

* **合格（打标 1）**：正文明确包含黑客/洗钱者**获利后**的链上资金轨迹（≥2 跳），
  包括单链内 TRANSFER、SWAP、SPLIT、MERGE、进混币器，或跨链 BRIDGE。
* **排除（打标 0）**：纯代码漏洞原理剖析（资金停留于初始获利地址无变动）、
  宏观合规政策、社工钓鱼案例、产品/导航页。

产出（两阶段安全写回，均满足 RFC 4180 / UTF-8）：

1. 回填 ``manifest.csv`` 的 ``has_fund_flow`` 列（``0`` / ``1``，无空值）；
2. 伴生输出 ``data/raw_reports/eligibility_audit.json`` 学术证据审计台账；
3. 控制台打印各厂商判定分布汇总表。

判定引擎（双层）

* **Tier-1 启发式（默认、离线）**：复用 ``tools/crawler.extractor.analyze_fund_flow_evidence``
  的标记证据，叠加本模块维护的高精度「资金轨迹事件」正则（TRANSFER / SWAP /
  BRIDGE / SPLIT / MERGE / 混币器 / 获利地址分布拆分），事件数 ≥2 即准入。
* **Tier-2 LLM 复核（``--llm``，可选）**：逐篇调用项目既有
  ``src.aml_agent.client.LLMClient``（OpenAI 兼容，DeepSeek 系模型）返回结构化
  JSON 判定；单篇失败时自动回退启发式并记录错误。

用法
----
    python scripts/screen_manifest.py            # 启发式判定 + 写回 CSV/审计 JSON
    python scripts/screen_manifest.py --dry-run  # 离线演练：只计算与汇报，不落盘
    python scripts/screen_manifest.py --llm      # 启用 LLM 复核（需 DEEPSEEK_API_KEY）

依赖
----
仅标准库 + 项目内模块（``tools/crawler/extractor.py``、``src/aml_agent/client.py``），
离线 ``--dry-run`` 零网络请求。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _extra in (str(PROJECT_ROOT), str(PROJECT_ROOT / "src")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

from tools.crawler.extractor import analyze_fund_flow_evidence  # noqa: E402
from tools.crawler.manifest import MANIFEST_HEADERS  # noqa: E402

DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "raw_reports" / "manifest.csv"
DEFAULT_AUDIT = PROJECT_ROOT / "data" / "raw_reports" / "eligibility_audit.json"

MIN_HOPS = 2  # I1 硬门禁：获利后链上资金轨迹 ≥ 2 跳

# ---------------------------------------------------------------------------
# 资金轨迹事件正则（高精度，逐篇人工校准）
# ---------------------------------------------------------------------------
_ADDR = r"(?:0x[0-9a-fA-F]{8,}|bc1[0-9a-zA-Z]{8,}|T[0-9a-zA-Z]{8,})"
_CHAIN = (
    r"(?:Ethereum|Solana|Bitcoin|BSC|BNB Chain|TRON|Tron|Arbitrum|Hyperliquid|"
    r"Rootstock|Liquid|Polygon|Heco)"
)
_ASSET = (
    r"(?:[A-Z][A-Z0-9]{1,11}\b|ETH|BTC|BNB|USDT|USDC|DAI|wstETH|rsETH|WETH|XMR|"
    r"TRX|GYD|USR|FLOW|aEthrsETH|PAT|KMNO)"
)
_DET = r"(?:(?:the|its|an?|their|his|her|this|that)\s+)?"
_DEST = (
    rf"(?:Tornado Cash|Railgun|FixedFloat|KuCoin|cce\.cash|{_ADDR}|OTC|CEX|"
    r"centralized exchange|mixer|block builder|downstream address\w*|exchange|"
    r"profit recipient|fund-?transfer address\w*|fund-?holding address\w*|\w+ bot)"
)

# SWAP / 兑换：动词 + (for|into|to) + 资产符号（排除 Solidity 类型转换噪音）
_SWAP_RE = re.compile(
    rf"(?i)(swapped|exchanged|converted|sold)\s+[^.\n]{{0,80}}?(?:for|into|to)\s+"
    rf"(?!(?:uint|int|bytes|address|string|bool|struct)\b)({_ASSET})"
)

# TRANSFER / 转移：移动动词 + (to|into) + 具体目的地（地址 / 混币器 / 交易所 / bot…）
_TRANS_RE = re.compile(
    rf"(?i)(sent|transferred|moved|deposited|paid|forwarded|routed|funneled|"
    rf"dispersed|went|reached)\s+[^.\n]{{0,80}}?(?:to|into)\s+{_DET}({_DEST})"
)

# BRIDGE / 跨链：桥接方向 / cross-chain to / peg-out 类（排除"cross-chain bridges"
# 等泛化名词罗列）
_BRIDGE_RE = re.compile(
    rf"(?i)(?:bridged\s+[^.\n]{{0,80}}?\s+(?:to|from)\s+[^.\n]{{0,40}}?"
    rf"(?:{_CHAIN}|{_ADDR})"
    rf"|cross-chain(?:ed)?\s+[^.\n]{{0,50}}?\s+to\s+(?:the\s+)?"
    rf"(?:TRON|Tron|Ethereum|{_ADDR})"
    rf"|peg-?out\w*|pegged out|sendtomainchain|"
    rf"redeemed\s+[^.\n]{{0,60}}?for\s+[^.\n]{{0,40}}?(?:BTC|Bitcoin))"
)

# SPLIT / 拆分（须与资金对象共现，排除"split into steps"等攻击步骤噪音）
_SPLIT_RE = re.compile(
    rf"(?i)(?:split\s+(?:the\s+)?(?:funds|assets|proceeds|tokens|amounts|them|"
    rf"usdt|eth|btc|balances)\s+(?:into|across|among)"
    rf"|split\s+(?:into|across|among)\s+(?:\d+\s+)?(?:wallets|addresses|parts)"
    rf"|dispersed\s+across"
    rf"|in\s+(?:batches|\d+\s+transactions)"
    rf"|divided\s+(?:into|across)\s+(?:\d+\s+)?(?:wallets|addresses|parts))"
)

# MERGE / 聚合（须与资金对象共现，排除"aggregated price"等预言机噪音）
_MERGE_RE = re.compile(
    rf"(?i)(?:consolidat\w+\s+(?:the\s+)?(?:funds|assets|proceeds|tokens|amounts|"
    rf"them|usdt|eth|btc|usd|balances)|collected\s+together)"
)

# 混币器：Tornado / Railgun / mixer 存款
_MIXER_RE = re.compile(
    r"(?i)(Tornado Cash|Railgun|deposited[^.\n]{0,60}?(?:mixer|Tornado))"
)

# Fund Flow 小节中的"地址持币"行（用于拆分分布判定）
_HOLD_RE = re.compile(rf"(?i)({_ADDR})[^.]{{0,60}}?(?:holds?|held|is held|holding)")

# 资金停留静态证据（用于 0 标理由与证据链）
_STATIC_RE = re.compile(
    rf"(?i)(?:held\s+(?:in|at)\s+[^.\n]{{0,80}}|remaining\s+[^.\n]{{0,80}}?"
    rf"(?:remains|held)|monitoring\s+(?:this|the(?:se)?)\s+wallet[^.\n]{{0,40}})"
)

_FLOW_KIND_LABELS = {
    "trans": "TRANSFER",
    "bridge": "BRIDGE",
    "split": "SPLIT",
    "merge": "MERGE",
    "mixer": "MIXER",
    "swap": "SWAP",
    "dist": "SPLIT",
}


# ---------------------------------------------------------------------------
# 证据抽取
# ---------------------------------------------------------------------------
def _fund_flow_section(text: str) -> str:
    """截取 ``Fund Flow`` 标题至下一标题/文末的小节（无则返回空串）。"""
    match = re.search(r"(?i)^\s*fund flow\s*$", text, re.M)
    if not match:
        return ""
    segment = text[match.end():]
    cut = re.search(r"(?i)^#+\s|\n[A-Z][A-Za-z ]{4,50}\n(?=\n)", segment, re.M)
    return segment[: cut.start()] if cut else segment


def _snippet(match: re.Match[str], width: int = 100) -> str:
    text = match.string
    end = min(len(text), match.end() + 25)
    return re.sub(r"\s+", " ", text[match.start():end]).strip()[:width]


def extract_flow_events(text: str) -> dict[str, Any]:
    """抽取获利后资金轨迹事件（种类计数 + 证据片段 + 拆分分布 + 静态证据）。"""
    counts: dict[str, int] = {}
    snippets: dict[str, list[str]] = {}
    for kind, pattern in (
        ("trans", _TRANS_RE),
        ("bridge", _BRIDGE_RE),
        ("split", _SPLIT_RE),
        ("merge", _MERGE_RE),
        ("mixer", _MIXER_RE),
        ("swap", _SWAP_RE),
    ):
        matches = list(pattern.finditer(text))
        counts[kind] = len(matches)
        seen: set[str] = set()
        for match in matches[:6]:
            snip = _snippet(match)
            if snip and snip.lower() not in seen:
                seen.add(snip.lower())
                snippets.setdefault(kind, []).append(snip)

    # 拆分分布：Fund Flow 小节中获利资金分布至 ≥3 个地址，
    # 或 ≥2 个地址且资产形态发生转换 —— 记 SPLIT + TRANSFER（合计 2 跳）
    section = _fund_flow_section(text)
    dist, hold_addrs = 0, []
    if section:
        holds = _HOLD_RE.findall(section)
        hold_addrs = sorted({addr.lower() for addr in holds})
        assets = re.findall(r"(?i)\b(wstUSR|ETH|BTC|USDT|USDC|DAI|WETH|rsETH|BNB|XMR)\b", section)
        if len(hold_addrs) >= 3 or (
            len(hold_addrs) >= 2
            and len({asset.upper() for asset in assets}) >= 2
        ):
            dist = 1
            if hold_addrs:
                snippets.setdefault("dist", []).append(
                    f"Proceeds split across {len(hold_addrs)} addresses: "
                    + ", ".join(hold_addrs[:4])
                )

    statics: list[str] = []
    for match in _STATIC_RE.finditer(text):
        snip = _snippet(match)
        if snip and snip not in statics:
            statics.append(snip)

    return {
        "counts": counts,
        "snippets": snippets,
        "dist": dist,
        "hold_addrs": hold_addrs,
        "statics": statics,
    }


def count_hops(events: dict[str, Any]) -> int:
    """事件数 → 近似跳数：SWAP 需与 ≥1 个其它事件共现才计 1 跳。"""
    counts = events["counts"]
    base = (
        counts["trans"]
        + counts["bridge"]
        + counts["split"]
        + counts["merge"]
        + counts["mixer"]
        + 2 * events["dist"]
    )
    if counts["swap"] and base >= 1:
        base += 1
    return base


def build_evidence_chain(events: dict[str, Any], include_swap: bool) -> str:
    """由已检出事件片段拼接可审计的证据链（0 标只保留贡献跳数的事件）。"""
    kinds = ["trans", "bridge", "split", "merge", "mixer", "dist"]
    if include_swap:
        kinds.append("swap")
    parts: list[str] = []
    seen: set[str] = set()
    for kind in kinds:
        for snip in events["snippets"].get(kind, []):
            key = snip.lower()
            if key not in seen and len(" -> ".join(parts)) < 280:
                seen.add(key)
                parts.append(snip)
    if parts:
        return " -> ".join(parts[:6])
    if events["statics"]:
        return events["statics"][0]
    return "无获利后资金轨迹（正文未检出 ≥2 跳证据）"


def heuristic_judge(text: str) -> dict[str, Any]:
    """Tier-1 启发式判定：返回结构化判定结果。"""
    legacy = analyze_fund_flow_evidence(text)
    events = extract_flow_events(text)
    hops = count_hops(events)
    verdict = 1 if hops >= MIN_HOPS else 0

    counts = events["counts"]
    base = (
        counts["trans"]
        + counts["bridge"]
        + counts["split"]
        + counts["merge"]
        + counts["mixer"]
        + 2 * events["dist"]
    )
    include_swap = counts["swap"] > 0 and base >= 1
    kinds = sorted(
        {
            _FLOW_KIND_LABELS[kind]
            for kind, count in counts.items()
            if count > 0 and (kind != "swap" or include_swap)
        }
    )
    if events["dist"]:
        kinds.append("SPLIT")
    kinds = sorted(set(kinds))

    if verdict == 1:
        reason = (
            f"检出获利后链上资金轨迹 {hops}+ 跳"
            + (f"（{'/'.join(kinds)}）" if kinds else "")
            + f"，满足 I1 准入规则（≥{MIN_HOPS} 跳）"
        )
    elif hops == 0:
        reason = (
            "正文未检出获利后链上资金轨迹"
            "（纯代码漏洞剖析/宏观合规/社工通报/产品介绍类），"
            f"不满足 I1 准入规则（≥{MIN_HOPS} 跳）"
        )
    else:
        reason = (
            f"仅检出 {hops} 跳资金动作，获利后轨迹不足 {MIN_HOPS} 跳"
            "（资金停留于初始获利地址或单跳变现），"
            f"不满足 I1 准入规则（≥{MIN_HOPS} 跳）"
        )

    return {
        "has_fund_flow": verdict,
        "hops_detected": min(hops, 10),
        "evidence_chain": build_evidence_chain(events, include_swap),
        "reason": reason,
        "markers": legacy["markers"],
        "method": "heuristic",
    }


# ---------------------------------------------------------------------------
# Tier-2 LLM 复核（可选）
# ---------------------------------------------------------------------------
_LLM_SYSTEM_GATE = (
    "You are a blockchain security researcher screening reports for AML fund-flow patterns.\n"
    "CRITICAL RULE: We ONLY care about the POST-EXPLOIT money laundering trail (after the exploit is finished and profit is locked).\n"
    "STRICTLY EXCLUDE the following as hops:\n"
    "1. Exploit execution steps / contract calls (e.g. flashloans, repaying flashloans, attack contract -> helper contract -> withdraw);\n"
    "2. Static balance snapshots (e.g., 'address A holds X tokens' without a concrete transfer transaction);\n"
    "3. Macro academic surveys without specific transaction/hop graphs.\n"
    "QUALIFY (=1) ONLY if the hacker/launderer actively moves the stolen funds across AT LEAST 2 on-chain hops "
    "(e.g., Transfer to new EOA, Swap via DEX, Bridge to another chain, or Deposit into Mixer/Tornado/Railgun)."
)

_LLM_OUTPUT_CONTRACT = (
    'Reply with ONLY one JSON object with keys: '
    '{"thinking": "Step 1: What was the exploit? Step 2: Did funds move AFTER the exploit finished? Step 3: Are there >=2 post-exploit hops?", '
    '"has_fund_flow": 0 or 1, "hops_detected": int, '
    '"evidence_chain": "short hop chain or explanation of why excluded", '
    '"reason": "concise verdict reason"}.'
)


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    """宽容解析 LLM 返回的 JSON（剥除围栏、截取首个平衡对象）。"""
    text = re.sub(r"```(?:json)?", "", raw).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_str:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_str = False
            continue
        if char == '"':
            in_str = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                verdict = payload.get("has_fund_flow")
                if verdict not in (0, 1, "0", "1"):
                    return None
                try:
                    hops = int(payload.get("hops_detected", 0))
                except (TypeError, ValueError):
                    hops = 0
                return {
                    "has_fund_flow": int(verdict),
                    "hops_detected": max(0, min(hops, 10)),
                    "evidence_chain": str(payload.get("evidence_chain") or "")[:400],
                    "reason": str(payload.get("reason") or "")[:400],
                }
    return None


def llm_judge(title: str, text: str, client: Any) -> dict[str, Any] | None:
    """Tier-2 LLM 复核；返回 None 表示失败（由调用方回退启发式）。"""
    window = text[:35000].strip()
    prompt = (
        f"{_LLM_SYSTEM_GATE}\n\n"
        f"Report title: {title}\n\n"
        f"Report text:\n{window}\n\n"
        f"{_LLM_OUTPUT_CONTRACT}"
    )
    raw = client.chat(prompt)
    result = _parse_llm_json(raw)
    if result is None:
        return None
    result["method"] = "llm"
    return result


def _build_client(args: argparse.Namespace) -> Any:
    from src.aml_agent.client import LLMClient  # 延迟导入，离线路径零依赖

    return LLMClient(model=args.model or None, timeout=args.timeout)


# ---------------------------------------------------------------------------
# CSV / 审计台账读写（RFC 4180：UTF-8、CRLF、QUOTE_MINIMAL；原子替换）
# ---------------------------------------------------------------------------
def load_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """按原始顺序读取 manifest（保留原表头文本，跳过空白行）。"""
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError(f"manifest 为空: {path}")
    headers = rows[0]
    records = [
        dict(zip(headers, row))
        for row in rows[1:]
        if any(field.strip() for field in row)
    ]
    return headers, records


def write_manifest(path: Path, headers: list[str], records: list[dict[str, str]]) -> None:
    """整体重写 manifest（QUOTE_MINIMAL / CRLF），临时文件 + 原子替换。"""
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=headers,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\r\n",
        )
        writer.writeheader()
        for record in records:
            writer.writerow(record)
    os.replace(temp, path)


def write_audit(path: Path, audit: dict[str, Any]) -> None:
    """原子写回审计台账 JSON（UTF-8 无转义，缩进 2）。"""
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temp, path)


# ---------------------------------------------------------------------------
# 汇总汇报
# ---------------------------------------------------------------------------
def render_summary(
    records: list[dict[str, str]], audit: dict[str, Any]
) -> tuple[str, dict[str, tuple[int, int]]]:
    """按厂商统计判定分布并生成控制台汇总表。"""
    vendors: dict[str, tuple[int, int]] = {}
    for record in records:
        vendor = record["vendor"] or "(unknown)"
        qualified, total = vendors.get(vendor, (0, 0))
        entry = audit.get(record["report_id"], {})
        qualified += 1 if entry.get("has_fund_flow") == 1 else 0
        vendors[vendor] = (qualified, total + 1)

    lines = ["=" * 72]
    lines.append("PRISMA 资格准入核验汇总（has_fund_flow 定标）")
    lines.append("-" * 72)
    lines.append(f"{'厂商':<12}{'合格':>6}{'总数':>8}{'合格率':>10}")
    lines.append("-" * 72)
    for vendor, (qualified, total) in sorted(vendors.items()):
        rate = f"{qualified / total * 100:.0f}%" if total else "-"
        lines.append(f"{vendor:<12}{qualified:>6}{total:>8}{rate:>10}")
    lines.append("-" * 72)
    all_qualified = sum(q for q, _ in vendors.values())
    all_total = sum(t for _, t in vendors.values())
    all_rate = f"{all_qualified / all_total * 100:.0f}%" if all_total else "-"
    lines.append(
        f"{'合计':<12}{all_qualified:>6}{all_total:>8}{all_rate:>10}"
    )
    lines.append("=" * 72)
    return "\n".join(lines), vendors


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(
    *,
    manifest_path: Path,
    audit_path: Path,
    dry_run: bool,
    use_llm: bool,
    model: str | None,
    timeout: float,
    verbose: bool,
) -> int:
    headers, records = load_manifest(manifest_path)
    expected = list(MANIFEST_HEADERS)
    if headers != expected:
        raise SystemExit(
            f"manifest 表头与 Schema 不符: {headers}（期望 {expected}）"
        )
    if not records:
        raise SystemExit("manifest 无数据记录")

    reports_dir = manifest_path.parent
    client = _build_client(
        argparse.Namespace(model=model, timeout=timeout)
    ) if use_llm else None
    if use_llm and client is not None and not client.api_key:
        raise SystemExit(
            "--llm 需要 DEEPSEEK_API_KEY（或 OPENAI_API_KEY）环境变量；"
            "未配置时请使用离线启发式模式（去掉 --llm）"
        )

    audit: dict[str, Any] = {}
    llm_ok = llm_fallback = 0
    for record in records:
        report_id = record["report_id"]
        filename = record["filename"]
        body_path = reports_dir / filename if filename else None
        if not body_path or not body_path.exists():
            raise SystemExit(f"正文缺失，中止写回以保护台账: {filename or report_id}")
        text = body_path.read_text(encoding="utf-8", errors="replace")

        heuristic = heuristic_judge(text)
        verdict = heuristic

        if client is not None:
            llm_result = None
            try:
                llm_result = llm_judge(record["title"], text, client)
            except Exception as exc:  # noqa: BLE001 - 单篇失败回退启发式
                llm_result = None
                heuristic["llm_error"] = str(exc)[:200]
            if llm_result is None:
                heuristic.setdefault("llm_error", "LLM 未返回有效 JSON")
                verdict = heuristic
                llm_fallback += 1
            else:
                # ====== 核心微调：双层引擎智能互补 (Logical OR) ======
                h_val = heuristic.get("has_fund_flow", 0)
                l_val = llm_result.get("has_fund_flow", 0)

                if l_val == 1:
                    # 1. LLM 确认有后置资金流：优先采纳 LLM 的自然语言证据链
                    verdict = llm_result
                elif h_val == 1:
                    # 2. 正则确凿抓到了 >=2 跳，但 LLM 漏读了：以启发式为主判 1，避免漏杀
                    verdict = heuristic
                    verdict["method"] = "heuristic_salvaged"
                    verdict["llm_doubt"] = llm_result.get("reason", "")
                else:
                    # 3. 两者一致认为无资金流：采纳判 0
                    verdict = llm_result

                llm_ok += 1

        entry = dict(verdict)
        entry.setdefault("markers", heuristic["markers"])
        entry["vendor"] = record["vendor"]
        entry["title"] = record["title"][:120]
        audit[report_id] = entry
        record["has_fund_flow"] = str(entry["has_fund_flow"])

    # 验收门禁：56 条全部填 0/1，无空值
    empties = [r["report_id"] for r in records if r["has_fund_flow"] not in ("0", "1")]
    if empties:
        raise SystemExit(f"has_fund_flow 存在未填充记录: {empties}")

    summary, vendors = render_summary(records, audit)
    print(summary)
    if verbose:
        print()
        for record in records:
            entry = audit[record["report_id"]]
            flag = "1" if entry["has_fund_flow"] == 1 else "0"
            print(
                f"[{flag}] {record['report_id']:<20} hops={entry['hops_detected']:<3}"
                f" | {entry['evidence_chain'][:130]}"
            )

    if dry_run:
        print("\n[dry-run] 未写回 manifest.csv / eligibility_audit.json。")
        return 0

    write_manifest(manifest_path, headers, records)
    write_audit(audit_path, audit)
    print(f"\n已写回 has_fund_flow 定标 -> {manifest_path}")
    print(f"已输出评审证据台账   -> {audit_path}")
    if client is not None:
        print(f"LLM 复核: 采纳 {llm_ok} 篇 / 回退启发式 {llm_fallback} 篇")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PRISMA 资格准入辅助核验：判定 manifest 各研报是否含 ≥2 跳获利后资金轨迹"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅计算判定与汇总，不写回 CSV / 审计 JSON",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="启用 LLM 复核（需 DEEPSEEK_API_KEY，单篇失败自动回退启发式）",
    )
    parser.add_argument("--model", default=None, help="LLM 模型名（默认 deepseek-flash）")
    parser.add_argument("--timeout", type=float, default=60.0, help="LLM 超时（秒）")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="manifest.csv 路径（默认 data/raw_reports/manifest.csv）",
    )
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=DEFAULT_AUDIT,
        help="eligibility_audit.json 输出路径",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="逐篇打印判定明细"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(
        manifest_path=args.manifest,
        audit_path=args.audit_out,
        dry_run=args.dry_run,
        use_llm=args.llm,
        model=args.model,
        timeout=args.timeout,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
