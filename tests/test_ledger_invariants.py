"""Stage-3 (Part B 前置): 拓扑物理账本公理双向回归测试。

覆盖强化后的两道硬门禁公理：

1. **跨账本动作闭环公理（Cross-Chain Ledger Invariant）**：跨 Chain 边必须
   显式使用 Bridge 原语；Transfer / Swap / Split / Merge 跨链穿越一律拦截。
2. **单出边流出守恒公理（Outflow Conservation Invariant）**：
   ``flow_share`` 严格为节点局部出边分配比例——单出边必须 = 1.0 ± 0.01；
   下游汇聚节点的入流权重禁止回写污染上游出边。

双向覆盖：
- 反例拦截（跨链普通转账、单出边漏损图、多出边失衡图）；
- 正例放行（合规 Bridge 跨链、merge 支流各 1.0、规范化后的全量生产知识库）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from aml_rag import (
    AbstractEdge,
    AbstractNode,
    MotifKnowledgeBase,
    NodeRole,
    OperationType,
    PatternType,
    TopologicalMotif,
    zero_noise_audit,
)
from aml_rag.evaluation import motif_topology_issues
from aml_rag.schema import FLOW_TOLERANCE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_KB = PROJECT_ROOT / "data" / "distilled_kb.json"

SRC = NodeRole.SOURCE
INT = NodeRole.INTERMEDIATE
CC = NodeRole.CROSS_CHAIN
AGG = NodeRole.AGGREGATOR
TGT = NodeRole.TARGET

TRANSFER = OperationType.TRANSFER
SWAP = OperationType.SWAP
BRIDGE = OperationType.BRIDGE
SPLIT = OperationType.SPLIT
MERGE = OperationType.MERGE


def _node(tid: str, role: NodeRole, chain: str, level: int) -> AbstractNode:
    return AbstractNode(temp_id=tid, role=role, chain=chain, level=level)


def _motif(motif_id: str, nodes: list[AbstractNode], edges: list[AbstractEdge]) -> TopologicalMotif:
    return TopologicalMotif(
        motif_id=motif_id,
        pattern_type=PatternType.CHAIN_HOPPING,
        description=f"ledger invariant probe {motif_id}",
        nodes=nodes,
        edges=edges,
    )


# ---------------------------------------------------------------------------
# 公理 1：跨账本动作闭环（Cross-Chain Ledger Invariant）
# ---------------------------------------------------------------------------
class TestCrossChainLedgerInvariant:
    def _cross_chain_nodes(self) -> list[AbstractNode]:
        return [
            _node("S", SRC, "Chain_A", 0),
            _node("T", TGT, "Chain_B", 1),
        ]

    @pytest.mark.parametrize(
        "operation",
        [TRANSFER, SWAP, SPLIT, MERGE],
        ids=["Transfer", "Swap", "Split", "Merge"],
    )
    def test_same_chain_operation_cannot_cross_chains(self, operation) -> None:
        edges = [AbstractEdge(source="S", target="T", operation=operation)]
        with pytest.raises(ValidationError, match="cross-chain ledger invariant"):
            _motif("XC_BAD", self._cross_chain_nodes(), edges)

    def test_bridge_crosses_chains_freely(self) -> None:
        edges = [AbstractEdge(source="S", target="T", operation=BRIDGE)]
        motif = _motif("XC_OK", self._cross_chain_nodes(), edges)
        assert motif.edges[0].operation == BRIDGE

    def test_case_insensitive_bridge_is_accepted(self) -> None:
        # 'bridge' / 'BRIDGE' resolve defensively via OperationType._missing_
        assert OperationType("bridge") is BRIDGE
        assert OperationType("BRIDGE") is BRIDGE
        assert OperationType("transfer") is TRANSFER

    def test_same_chain_transfer_still_allowed(self) -> None:
        nodes = [_node("S", SRC, "Chain_A", 0), _node("T", TGT, "Chain_A", 1)]
        motif = _motif(
            "SAME_OK", nodes, [AbstractEdge(source="S", target="T", operation=TRANSFER)]
        )
        assert motif.edges[0].operation == TRANSFER

    def test_invalid_operation_still_rejected(self) -> None:
        with pytest.raises(ValueError):
            OperationType("Teleport")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 公理 2：单出边流出守恒（Outflow Conservation Invariant）
# ---------------------------------------------------------------------------
class TestOutflowConservationInvariant:
    def _single_out_nodes(self, chain_b: bool = False) -> list[AbstractNode]:
        return [
            _node("S", SRC, "Chain_A", 0),
            _node("T", TGT, "Chain_B" if chain_b else "Chain_A", 1),
        ]

    def test_single_out_edge_below_one_rejected(self) -> None:
        # 漏损图：单出边只推进 60% 资金 —— 凭空蒸发 40%，必须拦截
        edges = [AbstractEdge(source="S", target="T", operation=TRANSFER, flow_share=0.6)]
        with pytest.raises(ValidationError, match="out-flow conservation"):
            _motif("LEAK", self._single_out_nodes(), edges)

    def test_single_out_edge_0_98_rejected_by_tolerance(self) -> None:
        # |0.98 - 1.0| = 0.02 > 0.01 容差：代数容差无模糊空间
        edges = [AbstractEdge(source="S", target="T", operation=TRANSFER, flow_share=0.98)]
        with pytest.raises(ValidationError, match="out-flow conservation"):
            _motif("LEAK_98", self._single_out_nodes(), edges)

    def test_single_out_edge_exactly_one_accepted(self) -> None:
        edges = [AbstractEdge(source="S", target="T", operation=TRANSFER, flow_share=1.0)]
        assert _motif("FULL", self._single_out_nodes(), edges).is_dag()

    def test_single_out_bridge_one_accepted(self) -> None:
        edges = [AbstractEdge(source="S", target="T", operation=BRIDGE, flow_share=1.0)]
        assert _motif("FULL_BRIDGE", self._single_out_nodes(chain_b=True), edges).is_dag()

    def test_merge_streams_each_forward_100_percent(self) -> None:
        # 汇聚拓扑正例：各支流为单出边 -> 全部 1.0；禁止写入下游入流权重
        nodes = [
            _node("S1", SRC, "Chain_A", 0),
            _node("S2", SRC, "Chain_A", 0),
            _node("AGG", AGG, "Chain_A", 1),
            _node("T", TGT, "Chain_A", 2),
        ]
        edges = [
            AbstractEdge(source="S1", target="AGG", operation=MERGE, flow_share=1.0),
            AbstractEdge(source="S2", target="AGG", operation=MERGE, flow_share=1.0),
            AbstractEdge(source="AGG", target="T", operation=TRANSFER),
        ]
        motif = _motif("MERGE_OK", nodes, edges)
        assert motif.is_dag()

    def test_merge_inflow_weight_writeback_rejected(self) -> None:
        # 反例：把下游汇聚入流权重 (0.5/0.5) 回写到上游单出边 —— 语义倒置
        nodes = [
            _node("S1", SRC, "Chain_A", 0),
            _node("S2", SRC, "Chain_A", 0),
            _node("AGG", AGG, "Chain_A", 1),
        ]
        edges = [
            AbstractEdge(source="S1", target="AGG", operation=MERGE, flow_share=0.5),
            AbstractEdge(source="S2", target="AGG", operation=MERGE, flow_share=0.5),
        ]
        with pytest.raises(ValidationError, match="out-flow conservation"):
            _motif("MERGE_BAD", nodes, edges)

    def test_split_group_still_must_conserve(self) -> None:
        nodes = [
            _node("S", SRC, "Chain_A", 0),
            _node("I1", INT, "Chain_A", 1),
            _node("I2", INT, "Chain_A", 1),
        ]
        conserved = [
            AbstractEdge(source="S", target="I1", operation=SPLIT, flow_share=0.6),
            AbstractEdge(source="S", target="I2", operation=SPLIT, flow_share=0.4),
        ]
        assert _motif("SPLIT_OK", nodes, conserved).is_dag()

        unbalanced = [
            AbstractEdge(source="S", target="I1", operation=SPLIT, flow_share=0.6),
            AbstractEdge(source="S", target="I2", operation=SPLIT, flow_share=0.5),
        ]
        with pytest.raises(ValidationError, match="out-flow conservation"):
            _motif("SPLIT_BAD", nodes, unbalanced)


# ---------------------------------------------------------------------------
# 审计函数（motif_topology_issues）同步检出两类公理破坏
# ---------------------------------------------------------------------------
class TestEvaluationIssueDetection:
    def test_cross_chain_non_bridge_issue_detected(self) -> None:
        nodes = [_node("S", SRC, "Chain_A", 0), _node("T", TGT, "Chain_B", 1)]
        # 合法实例注入违规边，模拟历史遗留违规资产进入审计流
        legacy = _motif("AUDIT_XC", nodes, [])
        legacy.edges.append(
            AbstractEdge(source="S", target="T", operation=TRANSFER, flow_share=1.0)
        )
        issues = motif_topology_issues(legacy)
        assert "cross_chain_non_bridge:S->T" in issues

    def test_outflow_conservation_issue_detected(self) -> None:
        nodes = [_node("S", SRC, "Chain_A", 0), _node("T", TGT, "Chain_A", 1)]
        legacy = _motif("AUDIT_FLOW", nodes, [])
        legacy.edges.append(
            AbstractEdge(source="S", target="T", operation=TRANSFER, flow_share=0.45)
        )
        issues = motif_topology_issues(legacy)
        assert "outflow_conservation:S" in issues

    def test_clean_motif_has_no_issues(self) -> None:
        nodes = [_node("S", SRC, "Chain_A", 0), _node("T", TGT, "Chain_A", 1)]
        motif = _motif(
            "AUDIT_OK", nodes, [AbstractEdge(source="S", target="T", operation=TRANSFER)]
        )
        assert motif_topology_issues(motif) == []


# ---------------------------------------------------------------------------
# 生产知识库全量静态验证（规范化后 100% 通行）
# ---------------------------------------------------------------------------
class TestProductionKnowledgeBase:
    def test_production_kb_loads_under_hardened_gate(self) -> None:
        kb = MotifKnowledgeBase.load(PRODUCTION_KB)
        assert len(kb) == 18, "production KB must keep all 18 motifs"

    def test_every_motif_satisfies_outflow_conservation(self) -> None:
        kb = MotifKnowledgeBase.load(PRODUCTION_KB)
        for motif in kb:
            out_groups: dict[str, list[AbstractEdge]] = {}
            for edge in motif.edges:
                out_groups.setdefault(edge.source, []).append(edge)
            for nid, group in out_groups.items():
                assert abs(sum(e.flow_share for e in group) - 1.0) <= FLOW_TOLERANCE, (
                    f"{motif.motif_id} node {nid} out-flow unconserved"
                )

    def test_every_cross_chain_edge_is_bridge(self) -> None:
        kb = MotifKnowledgeBase.load(PRODUCTION_KB)
        for motif in kb:
            chain_of = {n.temp_id: n.chain for n in motif.nodes}
            for edge in motif.edges:
                if chain_of[edge.source] != chain_of[edge.target]:
                    assert edge.operation == BRIDGE, (
                        f"{motif.motif_id} cross-chain edge "
                        f"{edge.source}->{edge.target} is not Bridge"
                    )

    def test_otc_p2p_cross_chain_edge_is_now_bridge(self) -> None:
        kb = MotifKnowledgeBase.load(PRODUCTION_KB)
        motif = kb.get("otc_p2p_integration_merge")
        edge = next(e for e in motif.edges if e.source == "AG" and e.target == "AC")
        assert edge.operation == BRIDGE

    def test_production_kb_zero_noise_and_topology_clean(self) -> None:
        kb = MotifKnowledgeBase.load(PRODUCTION_KB)
        assert zero_noise_audit(list(kb)).residue_count == 0
        for motif in kb:
            assert motif_topology_issues(motif) == []
