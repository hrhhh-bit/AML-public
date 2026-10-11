"""轻量冒烟脚本（scripts/smoke_distill_handbook_ledger.py）的验收逻辑测试。

离线锁定两条链路（不触发任何真实 API）：

1. 门禁日志生成器对合规 / 违规 Motif 的 PASS / REJECT 输出；
2. MotifDistiller 在强化规则 8/9 门禁下的反射修复（repair）链路：
   - LLM 首轮产出违规 Motif（跨链 Transfer / 单出边漏损）被拦截后，
     收到 PREVIOUS MISTAKE 反馈并修复为合规拓扑 -> 最终放行；
   - LLM 顽固输出违规拓扑 -> 修复预算耗尽，记录 failure。

同时断言冒烟脚本默认资产路径指向研报样本与生产知识库（零读写语义）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "smoke_distill_handbook_ledger.py"

_spec = importlib.util.spec_from_file_location("smoke_distill_handbook_ledger", SCRIPT)
assert _spec is not None and _spec.loader is not None
smoke_mod = importlib.util.module_from_spec(_spec)
sys.modules["smoke_distill_handbook_ledger"] = smoke_mod
_spec.loader.exec_module(smoke_mod)

from aml_rag import (  # noqa: E402
    AbstractEdge,
    AbstractNode,
    MotifDistiller,
    TextChunker,
    TopologicalMotif,
    motif_topology_issues,
)

SRC = "Source"
TGT = "Target"


def _clean_bridge_motif() -> TopologicalMotif:
    return TopologicalMotif(
        motif_id="probe_bridge",
        pattern_type="Chain_Hopping",
        description="bridge hop probe",
        nodes=[
            AbstractNode(temp_id="S", role="Source", chain="Chain_A", level=0),
            AbstractNode(temp_id="T", role="Target", chain="Chain_B", level=1),
        ],
        edges=[AbstractEdge(source="S", target="T", operation="Bridge")],
    )


def _bad_cross_chain_dict() -> dict:
    return {
        "motif_id": "bad_cross_hop",
        "pattern_type": "Chain_Hopping",
        "description": "cross chain hop via an ordinary transfer",
        "nodes": [
            {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 1},
        ],
        "edges": [{"source": "S", "target": "T", "operation": "Transfer"}],
    }


def _bad_leak_dict() -> dict:
    return {
        "motif_id": "bad_leak",
        "pattern_type": "Peeling_Chain",
        "description": "single out-edge leaks 40% of the flow",
        "nodes": [
            {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 1},
        ],
        "edges": [{"source": "S", "target": "T", "operation": "Transfer", "flow_share": 0.6}],
    }


def _good_dict() -> dict:
    return {
        "motif_id": "good_bridge",
        "pattern_type": "Chain_Hopping",
        "description": "bridge hop done right",
        "nodes": [
            {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
            {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 1},
        ],
        "edges": [{"source": "S", "target": "T", "operation": "Bridge"}],
    }


class _ScriptedLLM:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._replies.pop(0) if self._replies else "garbage"


class TestGateLog:
    def test_clean_motif_logs_pass(self) -> None:
        lines = smoke_mod._fmt_gate_log(_clean_bridge_motif())
        joined = "\n".join(lines)
        assert "公理1" in joined and "Bridge" in joined
        assert "公理2" in joined
        assert "PASS" in joined

    def test_injected_cross_chain_transfer_logs_reject(self) -> None:
        motif = _clean_bridge_motif()
        motif.edges.append(
            AbstractEdge(source="S", target="T", operation="Transfer", flow_share=0.5)
        )
        lines = smoke_mod._fmt_gate_log(motif)
        joined = "\n".join(lines)
        assert "REJECT" in joined
        assert "cross_chain_non_bridge" in joined
        assert "outflow_conservation" in joined

    def test_issues_empty_for_clean_motif(self) -> None:
        assert motif_topology_issues(_clean_bridge_motif()) == []


class TestDistillerRepairChain:
    def _distiller(self, replies: list[str]):
        llm = _ScriptedLLM(replies)
        distiller = MotifDistiller(
            llm, chunker=TextChunker(max_chars=10_000_000)
        )
        result = distiller.distill("one segment")
        return llm, result

    def test_cross_chain_violation_repaired_by_llm_then_passed(self) -> None:
        llm, result = self._distiller(
            [json.dumps([_bad_cross_chain_dict()]), json.dumps([_good_dict()])]
        )
        assert result.failures == []
        assert [m.motif_id for m in result.motifs] == ["good_bridge"]
        # 修复重试 prompt 必须携带门禁拒绝反馈
        assert "PREVIOUS MISTAKE" in llm.prompts[-1]
        assert "cross-chain ledger invariant" in llm.prompts[-1]

    def test_single_out_leak_violation_repaired_then_passed(self) -> None:
        llm, result = self._distiller(
            [json.dumps([_bad_leak_dict()]), json.dumps([_good_dict()])]
        )
        assert result.failures == []
        assert [m.motif_id for m in result.motifs] == ["good_bridge"]
        assert "out-flow conservation" in llm.prompts[-1]

    def test_persistent_violation_exhausts_repair_budget(self) -> None:
        _, result = self._distiller([json.dumps([_bad_cross_chain_dict()])] * 3)
        assert result.motifs == []
        assert len(result.failures) == 1
        assert result.failures[0].attempts == 3
        assert "cross-chain ledger invariant" in result.failures[0].error


class TestAssetConventions:
    def test_default_report_points_to_handbook_sample(self) -> None:
        assert smoke_mod.DEFAULT_REPORT.name == "Crypto-Asset-Tracing-Handbook"
        assert smoke_mod.DEFAULT_REPORT.exists()

    def test_production_kb_path_never_written_by_script(self) -> None:
        # 脚本仅引用该常量用于提示，源代码中不存在对该路径的写调用
        src = SCRIPT.read_text(encoding="utf-8")
        assert "PRODUCTION_KB.write" not in src
        assert "distilled_kb.json" in src  # 仅出现在常量与提示字符串
