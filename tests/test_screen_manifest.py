"""scripts/screen_manifest.py —— PRISMA 资格准入核验流水线测试套件。

覆盖维度：

1. 启发式判定硬门禁：≥2 跳获利后资金轨迹打标 1，纯漏洞/静态持有/宏观合规打标 0；
2. 全流水线（临时台账）写回：has_fund_flow 全量填充、RFC 4180（CRLF/QUOTE_MINIMAL）、
   审计 JSON 56 键齐全、dry-run 零落盘；
3. LLM JSON 宽容解析（围栏/非法负载/字段缺失）；
4. 防御性门禁：表头不符 / 正文缺失时中止且不产生半成品写回。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import scripts.screen_manifest as screen

# ---------------------------------------------------------------------------
# 样本正文
# ---------------------------------------------------------------------------
POS_SWAP_MIXER = (
    "The protocol was exploited for $1.2M. After the exploit, the attacker "
    "swapped the stolen USDC for 500 ETH and then deposited the ETH into "
    "Tornado Cash in 10 transactions."
)

POS_BRIDGE_SPLIT = (
    "The attacker drained the vault. The proceeds were bridged from BSC to "
    "Ethereum via Mayan, then split into 3 wallets: 0x1111111111111111111111111111111111111111, "
    "0x2222222222222222222222222222222222222222 and 0x3333333333333333333333333333333333333333. "
    "Part of the funds was later deposited into Railgun."
)

NEG_CODE_ONLY = (
    "The root cause is an unchecked uint128 cast in _convertToETH. "
    "uint128 absBalance = uint128(balance.abs()); "
    "The attacker then withdrew the profit from the Escrow contract."
)

NEG_STATIC_HOLD = (
    "This incident leads to the reward tokens transferred to the attacker, "
    "and then it was used to swap for BNB. The attacker's funds were initially "
    "held in this wallet: 0xB63F. We are actively monitoring this wallet for "
    "any movement."
)

NEG_MACRO = (
    "Regulators continue to tighten AML requirements. Exchanges must screen "
    "cross-chain bridges, mixers and P2P transfers under the FATF travel rule."
)


# ---------------------------------------------------------------------------
# 1. 启发式判定
# ---------------------------------------------------------------------------
class TestHeuristicJudge:
    def test_qualifies_swap_plus_mixer(self):
        result = screen.heuristic_judge(POS_SWAP_MIXER)
        assert result["has_fund_flow"] == 1
        assert result["hops_detected"] >= 2
        assert "Tornado" in result["evidence_chain"]
        assert "I1" in result["reason"]

    def test_qualifies_bridge_split_mixer(self):
        result = screen.heuristic_judge(POS_BRIDGE_SPLIT)
        assert result["has_fund_flow"] == 1
        assert "bridged" in result["evidence_chain"].lower()

    def test_excludes_pure_code_analysis(self):
        result = screen.heuristic_judge(NEG_CODE_ONLY)
        assert result["has_fund_flow"] == 0
        assert result["hops_detected"] == 0

    def test_excludes_static_hold(self):
        result = screen.heuristic_judge(NEG_STATIC_HOLD)
        assert result["has_fund_flow"] == 0
        assert "monitor" in result["evidence_chain"].lower()

    def test_excludes_macro_compliance(self):
        result = screen.heuristic_judge(NEG_MACRO)
        assert result["has_fund_flow"] == 0


# ---------------------------------------------------------------------------
# 2. 全流水线写回（临时台账）
# ---------------------------------------------------------------------------
def _make_world(tmp_path: Path) -> tuple[Path, Path]:
    """构建含 3 篇研报的临时台账（与生产一致：正文与 manifest 同目录，CRLF 字节）。"""
    reports = tmp_path  # 与生产 data/raw_reports 布局一致
    manifest = tmp_path / "manifest.csv"
    header = "report_id,vendor,title,publish_date,matched_kw,url,filename,has_fund_flow"
    rows = [
        'rep_x_001,XCorp,"Report A",2026-01-01,"fund flow",'
        "https://x.local/a,rep_x_001.txt,",
        "rep_x_002,XCorp,Report B,2026-01-02,\"fund flow\","
        "https://x.local/b,rep_x_002.txt,",
        "rep_x_003,XCorp,Report C,2026-01-03,attack,"
        "https://x.local/c,rep_x_003.txt,",
    ]
    content = header + "\r\n" + "\r\n".join(rows) + "\r\n"
    manifest.write_bytes(content.encode("utf-8"))
    (reports / "rep_x_001.txt").write_text(POS_SWAP_MIXER, encoding="utf-8")
    (reports / "rep_x_002.txt").write_text(NEG_STATIC_HOLD, encoding="utf-8")
    (reports / "rep_x_003.txt").write_text(POS_BRIDGE_SPLIT, encoding="utf-8")
    return manifest, reports


class TestPipeline:
    def test_writeback_fills_all_rows_and_audit(self, tmp_path):
        manifest, _ = _make_world(tmp_path)
        audit_path = tmp_path / "eligibility_audit.json"
        code = screen.run(
            manifest_path=manifest,
            audit_path=audit_path,
            dry_run=False,
            use_llm=False,
            model=None,
            timeout=60.0,
            verbose=False,
        )
        assert code == 0

        raw = manifest.read_bytes()
        assert raw.count(b"\r\n") == 4  # 表头 + 3 条记录全部 CRLF
        assert raw.replace(b"\r\n", b"").count(b"\n") == 0

        records = list(csv.DictReader(manifest.open(encoding="utf-8", newline="")))
        assert len(records) == 3
        flags = {r["report_id"]: r["has_fund_flow"] for r in records}
        assert flags == {"rep_x_001": "1", "rep_x_002": "0", "rep_x_003": "1"}
        assert all(v in ("0", "1") for v in flags.values())

        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert set(audit) == {"rep_x_001", "rep_x_002", "rep_x_003"}
        for entry in audit.values():
            assert {"has_fund_flow", "hops_detected", "evidence_chain", "reason"} <= set(entry)

    def test_dry_run_does_not_write(self, tmp_path):
        manifest, _ = _make_world(tmp_path)
        audit_path = tmp_path / "eligibility_audit.json"
        before = manifest.read_bytes()
        code = screen.run(
            manifest_path=manifest,
            audit_path=audit_path,
            dry_run=True,
            use_llm=False,
            model=None,
            timeout=60.0,
            verbose=False,
        )
        assert code == 0
        assert manifest.read_bytes() == before  # 台账字节级不变
        assert not audit_path.exists()

    def test_missing_body_aborts_without_partial_write(self, tmp_path):
        manifest, reports = _make_world(tmp_path)
        (reports / "rep_x_002.txt").unlink()
        before = manifest.read_bytes()
        with pytest.raises(SystemExit):
            screen.run(
                manifest_path=manifest,
                audit_path=tmp_path / "audit.json",
                dry_run=False,
                use_llm=False,
                model=None,
                timeout=60.0,
                verbose=False,
            )
        assert manifest.read_bytes() == before  # 中止后台账保持原样
        assert not (tmp_path / "audit.json").exists()

    def test_header_mismatch_rejected(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("id,name,other\n1,a,b\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            screen.run(
                manifest_path=bad,
                audit_path=tmp_path / "audit.json",
                dry_run=True,
                use_llm=False,
                model=None,
                timeout=60.0,
                verbose=False,
            )


# ---------------------------------------------------------------------------
# 3. LLM JSON 宽容解析
# ---------------------------------------------------------------------------
class TestParseLLMJson:
    def test_plain_json(self):
        parsed = screen._parse_llm_json(
            '{"has_fund_flow": 1, "hops_detected": 3, '
            '"evidence_chain": "A -> B -> C", "reason": "ok"}'
        )
        assert parsed is not None
        assert parsed["has_fund_flow"] == 1
        assert parsed["hops_detected"] == 3

    def test_markdown_fence(self):
        parsed = screen._parse_llm_json(
            "```json\n{\"has_fund_flow\": 0, \"hops_detected\": 0, "
            "\"evidence_chain\": \"\", \"reason\": \"pure code analysis\"}\n```"
        )
        assert parsed is not None
        assert parsed["has_fund_flow"] == 0

    def test_string_flag_coerced(self):
        parsed = screen._parse_llm_json(
            '{"has_fund_flow": "1", "hops_detected": "2", '
            '"evidence_chain": "x", "reason": "y"}'
        )
        assert parsed is not None
        assert parsed["has_fund_flow"] == 1
        assert parsed["hops_detected"] == 2

    def test_invalid_payloads_rejected(self):
        assert screen._parse_llm_json("no json here") is None
        assert screen._parse_llm_json("{}") is None
        assert screen._parse_llm_json(
            '{"has_fund_flow": 2, "hops_detected": 1, "evidence_chain": "", "reason": ""}'
        ) is None
        assert screen._parse_llm_json(
            '{"has_fund_flow": 1, "hops_detected": "abc", "evidence_chain": "", "reason": ""}'
        ) is not None  # hops 非整数时归零，仍接受判定
