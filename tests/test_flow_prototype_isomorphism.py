"""Stage-3 Part B：方向 A 流向原型分桶 + VF2 三要件同构判定单元测试。

核心验收：
1. 流向原型离散分桶（PEELING / UNIFORM_SPLIT / DISPROPORTIONATE_SPLIT /
   SINGLE / NONE），禁止纯浮点差值比对；
2. Peeling 与 Uniform Split 在拓扑与边动作基完全一致时仍能被正确区分；
3. VF2 判定准则：拓扑同构 + 边动作基 Σ 相同 + 流向原型相同，三者同时
   满足才判定为同构去重；
4. 同桶内不同浮点取值（如 0.8/0.2 与 0.85/0.15）判为同构去重。
"""

from __future__ import annotations

import pytest

from aml_rag import (
    FlowPrototype,
    MotifKnowledgeBase,
    classify_flow_prototype,
    edge_action_basis,
    node_flow_prototypes,
    vf2_isomorphism_key,
)
from aml_rag.schema import (
    AbstractEdge,
    AbstractNode,
    NodeRole,
    OperationType,
    PatternType,
    TopologicalMotif,
)

SRC = NodeRole.SOURCE
INT = NodeRole.INTERMEDIATE
CC = NodeRole.CROSS_CHAIN
TGT = NodeRole.TARGET

TRANSFER = OperationType.TRANSFER
SWAP = OperationType.SWAP
BRIDGE = OperationType.BRIDGE
SPLIT = OperationType.SPLIT
MERGE = OperationType.MERGE


def _node(tid: str, role: NodeRole, chain: str, level: int) -> AbstractNode:
    return AbstractNode(temp_id=tid, role=role, chain=chain, level=level)


def _edge(source: str, target: str, op: OperationType, share: float = 1.0) -> AbstractEdge:
    return AbstractEdge(source=source, target=target, operation=op, flow_share=share)


# ---------------------------------------------------------------------------
# 分桶判定：流向原型离散分桶
# ---------------------------------------------------------------------------
class TestFlowPrototypeClassification:
    @pytest.mark.parametrize(
        ("shares", "expected"),
        [
            ((), FlowPrototype.NONE),                       # 无出边（终点）
            ((1.0,), FlowPrototype.SINGLE),                 # 单出边恒为 1.0
            ((0.8, 0.2), FlowPrototype.PEELING),            # 主干 0.8 >= 0.75
            ((0.75, 0.25), FlowPrototype.PEELING),          # 边界含等号
            ((0.85, 0.15), FlowPrototype.PEELING),
            ((0.76, 0.12, 0.12), FlowPrototype.PEELING),    # 主干 + 双侧枝
            ((0.5, 0.5), FlowPrototype.UNIFORM_SPLIT),      # 均等分流
            ((0.48, 0.52), FlowPrototype.UNIFORM_SPLIT),    # 极差 0.04 < 0.15
            ((0.4, 0.3, 0.3), FlowPrototype.UNIFORM_SPLIT), # 极差 0.1 < 0.15
            ((0.6, 0.4), FlowPrototype.DISPROPORTIONATE_SPLIT),   # 极差 0.2
            ((0.7, 0.3), FlowPrototype.DISPROPORTIONATE_SPLIT),   # 主干 < 0.75
            ((0.6, 0.2, 0.2), FlowPrototype.DISPROPORTIONATE_SPLIT),
        ],
    )
    def test_buckets(self, shares, expected) -> None:
        edges = [
            _edge("a", f"b{i}", SPLIT, share) for i, share in enumerate(shares)
        ]
        assert classify_flow_prototype(edges) is expected

    def test_single_out_edge_is_always_single(self) -> None:
        for op in (TRANSFER, SWAP, BRIDGE, MERGE):
            assert classify_flow_prototype([_edge("a", "b", op, 1.0)]) is FlowPrototype.SINGLE


# ---------------------------------------------------------------------------
# 分桶差异：Peeling vs Uniform Split 必须可区分
# ---------------------------------------------------------------------------
def _peel_motif(motif_id: str, peel_share: float) -> TopologicalMotif:
    """主干剥皮链：I1 出边 [peel_share, 1 - peel_share]。"""
    return TopologicalMotif(
        motif_id=motif_id,
        pattern_type=PatternType.PEELING_CHAIN,
        description="peeling chain probe",
        nodes=[
            _node("S", SRC, "Chain_A", 0),
            _node("I1", INT, "Chain_A", 1),
            _node("I2", INT, "Chain_A", 2),
            _node("P", INT, "Chain_A", 2),
            _node("T", TGT, "Chain_A", 3),
        ],
        edges=[
            _edge("S", "I1", TRANSFER),
            _edge("I1", "I2", TRANSFER, peel_share),
            _edge("I1", "P", TRANSFER, round(1.0 - peel_share, 4)),
            _edge("I2", "T", TRANSFER),
            _edge("P", "T", TRANSFER),
        ],
    )


def _uniform_split_motif(motif_id: str) -> TopologicalMotif:
    """均等分流：S 出边 [0.5, 0.5]，拓扑与剥皮链结构同型（同节点角色序列）。"""
    return TopologicalMotif(
        motif_id=motif_id,
        pattern_type=PatternType.PEELING_CHAIN,
        description="uniform split probe",
        nodes=[
            _node("S", SRC, "Chain_A", 0),
            _node("I1", INT, "Chain_A", 1),
            _node("I2", INT, "Chain_A", 2),
            _node("P", INT, "Chain_A", 2),
            _node("T", TGT, "Chain_A", 3),
        ],
        edges=[
            _edge("S", "I1", TRANSFER),
            _edge("I1", "I2", TRANSFER, 0.5),
            _edge("I1", "P", TRANSFER, 0.5),
            _edge("I2", "T", TRANSFER),
            _edge("P", "T", TRANSFER),
        ],
    )


class TestPeelingVsUniformSplit:
    def test_prototypes_differ_at_split_node(self) -> None:
        peel = _peel_motif("P1", 0.8)
        uniform = _uniform_split_motif("U1")
        protos_peel = node_flow_prototypes(peel)
        protos_uniform = node_flow_prototypes(uniform)
        assert protos_peel["I1"] is FlowPrototype.PEELING
        assert protos_uniform["I1"] is FlowPrototype.UNIFORM_SPLIT

    def test_same_topology_same_sigma_but_different_proto_are_distinct(self) -> None:
        peel = _peel_motif("P1", 0.8)
        uniform = _uniform_split_motif("U1")
        # 拓扑与边动作基完全一致
        assert _topo_key(peel) == _topo_key(uniform)
        assert edge_action_basis(peel) == edge_action_basis(uniform)
        # 但流向原型不同 -> VF2 键不同 -> 两者都入库
        assert vf2_isomorphism_key(peel) != vf2_isomorphism_key(uniform)
        kb = MotifKnowledgeBase()
        report = kb.merge_motifs([peel, uniform])
        assert sorted(report.added) == ["P1", "U1"]
        assert len(kb) == 2

    def test_same_bucket_different_floats_deduplicate(self) -> None:
        kb = MotifKnowledgeBase([_peel_motif("P1", 0.8)])
        report = kb.merge_motifs([_peel_motif("P2", 0.85)])  # 同桶 PEELING
        assert report.isomorphic_skips == ["P2"]
        assert report.added == []
        assert len(kb) == 1


# ---------------------------------------------------------------------------
# VF2 三要件：拓扑 / 边动作基 Σ / 流向原型
# ---------------------------------------------------------------------------
def _topo_key(motif: TopologicalMotif) -> tuple:
    return vf2_isomorphism_key(motif)[0]


class TestVf2ThreePartCriterion:
    def test_relabeled_nodes_share_key(self) -> None:
        """temp_id 重标不影响同构判定（纯拓扑 + 属性比对）。"""
        a = _peel_motif("A", 0.8)
        relabeled = TopologicalMotif(
            motif_id="B",
            pattern_type=PatternType.PEELING_CHAIN,
            description="peeling chain probe",
            nodes=[
                _node("n0", SRC, "Chain_A", 0),
                _node("n1", INT, "Chain_A", 1),
                _node("n2", INT, "Chain_A", 2),
                _node("n3", INT, "Chain_A", 2),
                _node("n4", TGT, "Chain_A", 3),
            ],
            edges=[
                _edge("n0", "n1", TRANSFER),
                _edge("n1", "n2", TRANSFER, 0.8),
                _edge("n1", "n3", TRANSFER, 0.2),
                _edge("n2", "n4", TRANSFER),
                _edge("n3", "n4", TRANSFER),
            ],
        )
        assert vf2_isomorphism_key(a) == vf2_isomorphism_key(relabeled)

    def test_same_topology_but_different_sigma_are_distinct(self) -> None:
        """拓扑相同但边动作基 Σ 不同 -> 判为不同。"""
        a = _peel_motif("A", 0.8)
        b = TopologicalMotif(
            motif_id="B",
            pattern_type=PatternType.PEELING_CHAIN,
            description="peeling chain probe",
            nodes=[
                _node("S", SRC, "Chain_A", 0),
                _node("I1", INT, "Chain_A", 1),
                _node("I2", INT, "Chain_A", 2),
                _node("P", INT, "Chain_A", 2),
                _node("T", TGT, "Chain_A", 3),
            ],
            edges=[
                _edge("S", "I1", TRANSFER),
                _edge("I1", "I2", SWAP, 0.8),  # Transfer -> Swap：Σ 变化
                _edge("I1", "P", TRANSFER, 0.2),
                _edge("I2", "T", TRANSFER),
                _edge("P", "T", TRANSFER),
            ],
        )
        assert _topo_key(a) == _topo_key(b)
        assert edge_action_basis(a) != edge_action_basis(b)
        assert vf2_isomorphism_key(a) != vf2_isomorphism_key(b)

    def test_merge_honors_all_three_components(self) -> None:
        kb = MotifKnowledgeBase()
        a = _peel_motif("A", 0.8)          # PEELING
        b = _peel_motif("B", 0.85)         # 同桶 -> 跳过
        c = _uniform_split_motif("C")      # 同拓扑同 Σ、原型不同 -> 入库
        report = kb.merge_motifs([a, b, c])
        assert report.added == ["A", "C"]
        assert report.isomorphic_skips == ["B"]
        assert len(kb) == 2

    def test_cross_chain_bridge_motif_key_is_stable(self) -> None:
        """跨链 BRIDGE 原语 motif 的 VF2 键可计算且稳定。"""
        m = TopologicalMotif(
            motif_id="X",
            pattern_type=PatternType.CHAIN_HOPPING,
            description="bridge escape",
            nodes=[
                _node("S", SRC, "Chain_A", 0),
                _node("CC", CC, "Chain_B", 1),
                _node("T", TGT, "Chain_B", 2),
            ],
            edges=[
                _edge("S", "CC", BRIDGE),
                _edge("CC", "T", TRANSFER),
            ],
        )
        assert vf2_isomorphism_key(m) == vf2_isomorphism_key(
            m.model_copy(update={"motif_id": "X2"})
        )

    def test_duplicate_ids_still_skipped_first(self) -> None:
        kb = MotifKnowledgeBase([_peel_motif("A", 0.8)])
        report = kb.merge_motifs([_peel_motif("A", 0.5)])  # id 冲突优先
        assert report.duplicate_ids == ["A"]
        assert report.isomorphic_skips == []
