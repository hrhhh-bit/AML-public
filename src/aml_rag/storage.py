"""Motif knowledge base storage (in-memory / JSON / vector-ready).

:class:`MotifKnowledgeBase` is the single source of truth for motif records
used by the dual-track retriever.  It is deliberately backend-agnostic:

- **In-memory**: a dict keyed by ``motif_id`` with O(1) lookup.
- **JSON persistence**: round-trippable via ``save`` / ``load``.
- **Vector-ready**: exposes :meth:`MotifKnowledgeBase.semantic_texts`, the
  flattened text corpus that any embedding backend (OpenAI, sentence-
  transformers or the built-in deterministic mock) can encode.
"""

from __future__ import annotations

import json
from collections import Counter
from enum import Enum
from itertools import permutations, product
from math import factorial
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .schema import AbstractEdge, TopologicalMotif

__all__ = [
    "MotifKnowledgeBase",
    "IngestReport",
    "build_default_knowledge_base",
    "FlowPrototype",
    "PEELING_MAIN_MIN",
    "PEELING_SIDE_MAX",
    "UNIFORM_SPREAD_TOLERANCE",
    "classify_flow_prototype",
    "node_flow_prototypes",
    "edge_action_basis",
    "vf2_isomorphism_key",
]


# ---------------------------------------------------------------------------
# 方向 A：宏观流向原型（离散原型分桶）
# ---------------------------------------------------------------------------
#: PEELING 主干边最低流向占比（含等号）。
PEELING_MAIN_MIN: float = 0.75
#: PEELING 侧枝边最高流向占比（含等号）。
PEELING_SIDE_MAX: float = 0.25
#: UNIFORM_SPLIT 边权极差判定阈值（|边权差值| < 0.15）。
UNIFORM_SPREAD_TOLERANCE: float = 0.15
#: 同构判定置换枚举预算上限（超出即回退确定性编码，防御病态大图）。
_MAX_ISO_PERMUTATIONS: int = 200_000


class FlowPrototype(str, Enum):
    """宏观流向原型（方向 A）：边属性比对禁止纯浮点差值，必须分桶判定。"""

    #: 单出边节点：flow_share 恒为 1.0（账本守恒公理）。
    SINGLE = "SINGLE"
    #: 剥皮：主干边 flow_share >= 0.75，侧枝 <= 0.25。
    PEELING = "PEELING"
    #: 均等分流：多出边流向近似均等（|边权差值| < 0.15）。
    UNIFORM_SPLIT = "UNIFORM_SPLIT"
    #: 非对称阶梯分流：其余所有多出边分布。
    DISPROPORTIONATE_SPLIT = "DISPROPORTIONATE_SPLIT"
    #: 无出边节点（终点）：不存在流向分布。
    NONE = "NONE"


def classify_flow_prototype(out_edges: Sequence[AbstractEdge]) -> FlowPrototype:
    """将单个节点的出边组分桶为宏观流向原型。

    判定顺序（均为离散阈值，不使用纯浮点差值比对）：

    1. 无出边 -> :attr:`FlowPrototype.NONE`；
    2. 单出边 -> :attr:`FlowPrototype.SINGLE`（恒为 1.0）；
    3. 极差 < 0.15 -> :attr:`FlowPrototype.UNIFORM_SPLIT`；
    4. 主干 >= 0.75 且全部侧枝 <= 0.25 -> :attr:`FlowPrototype.PEELING`；
    5. 其余 -> :attr:`FlowPrototype.DISPROPORTIONATE_SPLIT`。
    """
    if not out_edges:
        return FlowPrototype.NONE
    shares = sorted(e.flow_share for e in out_edges)
    if len(shares) == 1:
        return FlowPrototype.SINGLE
    span = shares[-1] - shares[0]
    if span < UNIFORM_SPREAD_TOLERANCE:
        return FlowPrototype.UNIFORM_SPLIT
    if shares[-1] >= PEELING_MAIN_MIN and all(
        s <= PEELING_SIDE_MAX for s in shares[:-1]
    ):
        return FlowPrototype.PEELING
    return FlowPrototype.DISPROPORTIONATE_SPLIT


def node_flow_prototypes(motif: TopologicalMotif) -> dict[str, FlowPrototype]:
    """返回 motif 内每个节点 ``temp_id -> FlowPrototype`` 的分桶映射。"""
    out_groups: dict[str, list[AbstractEdge]] = {}
    for edge in motif.edges:
        out_groups.setdefault(edge.source, []).append(edge)
    protos = {n.temp_id: FlowPrototype.NONE for n in motif.nodes}
    for nid, group in out_groups.items():
        protos[nid] = classify_flow_prototype(group)
    return protos


def edge_action_basis(motif: TopologicalMotif) -> tuple[str, ...]:
    """边动作基 Σ：motif 全部边操作的多重集合（升序）。"""
    return tuple(sorted(e.operation.value for e in motif.edges))


def _canonical_adjacency(motif: TopologicalMotif) -> tuple[Any, ...]:
    """角色标注图的最小规范化邻接编码（拓扑同构判定）。

    对角色分组内的全部置换穷举取字典序最小编码 —— 与角色标注图上的
    VF2 同构判定等价；置换组合数超出预算时回退为确定性排序编码。
    """
    nodes = list(motif.nodes)
    n = len(nodes)
    idx_of = {node.temp_id: i for i, node in enumerate(nodes)}
    role_groups: dict[str, list[int]] = {}
    for i, node in enumerate(nodes):
        role_groups.setdefault(node.role.value, []).append(i)

    out_adj: dict[int, list[int]] = {i: [] for i in range(n)}
    in_adj: dict[int, list[int]] = {i: [] for i in range(n)}
    for edge in motif.edges:
        s, t = idx_of[edge.source], idx_of[edge.target]
        out_adj[s].append(t)
        in_adj[t].append(s)

    def encode(order: list[int]) -> tuple[Any, ...]:
        entries = []
        for i in order:
            entries.append(
                (
                    nodes[i].role.value,
                    len(in_adj[i]),
                    len(out_adj[i]),
                    tuple(sorted(nodes[j].role.value for j in in_adj[i])),
                    tuple(
                        sorted(
                            (nodes[j].role.value, len(out_adj[j]))
                            for j in out_adj[i]
                        )
                    ),
                )
            )
        return tuple(sorted(entries))

    groups = list(role_groups.values())
    budget = 1
    for group in groups:
        budget *= factorial(len(group))
        if budget > _MAX_ISO_PERMUTATIONS:
            return encode(list(range(n)))  # 防御性回退：确定性但非全枚举
    best: tuple[Any, ...] | None = None
    for combo in product(*(permutations(group) for group in groups)):
        order = [i for part in combo for i in part]
        key = encode(order)
        if best is None or key < best:
            best = key
    assert best is not None  # 角色分组非空时 product 至少产生一个组合
    return best


def _canonical_flow_profile(
    motif: TopologicalMotif,
    role_of: Mapping[str, str],
    proto_of: Mapping[str, FlowPrototype],
) -> tuple[Any, ...]:
    """节点流向原型的规范画像：按 (role, 入度, 出度, 原型桶) 排序。"""
    indeg: Counter[str] = Counter()
    outdeg: Counter[str] = Counter()
    for edge in motif.edges:
        indeg[edge.target] += 1
        outdeg[edge.source] += 1
    entries = sorted(
        (
            role_of[n.temp_id],
            indeg[n.temp_id],
            outdeg[n.temp_id],
            proto_of.get(n.temp_id, FlowPrototype.NONE).value,
        )
        for n in motif.nodes
    )
    return tuple(entries)


def vf2_isomorphism_key(motif: TopologicalMotif) -> tuple[Any, ...]:
    """VF2 判定准则三要件合一的规范化同构键。

    两 motif 被判为同构去重的充要条件（三者同时满足）：

    1. **拓扑同构**：角色标注图的最小规范化邻接编码一致；
    2. **边动作基 Σ 相同**：全部边操作的多重集合一致；
    3. **流向原型相同**：各节点的宏观流向原型分桶画像一致
       （PEELING / UNIFORM_SPLIT / DISPROPORTIONATE_SPLIT / SINGLE，
       禁止纯浮点差值比对）。

    返回 ``(topology, sigma, flow_profile)`` 三元组，可哈希。
    """
    role_of = {n.temp_id: n.role.value for n in motif.nodes}
    return (
        _canonical_adjacency(motif),
        edge_action_basis(motif),
        _canonical_flow_profile(motif, role_of, node_flow_prototypes(motif)),
    )


class IngestReport(BaseModel):
    """Outcome of merging distilled motifs into a knowledge base."""

    model_config = ConfigDict(extra="forbid")

    added: list[str] = Field(default_factory=list)
    duplicate_ids: list[str] = Field(
        default_factory=list, description="motif_id already present in the KB."
    )
    isomorphic_skips: list[str] = Field(
        default_factory=list,
        description="Flow-aware signatures already present (non-new topology).",
    )

    @property
    def total_added(self) -> int:
        return len(self.added)

    @property
    def total_skipped(self) -> int:
        return len(self.duplicate_ids) + len(self.isomorphic_skips)


class MotifKnowledgeBase:
    """Thread-safe-by-convention motif registry with JSON persistence."""

    def __init__(self, motifs: Iterable[TopologicalMotif] = ()) -> None:
        self._motifs: dict[str, TopologicalMotif] = {}
        self.add_many(motifs)

    # ------------------------------------------------------------------ CRUD
    def add(self, motif: TopologicalMotif) -> None:
        """Insert or replace a motif (validated unique id inside KB)."""
        if motif.motif_id in self._motifs:
            raise KeyError(
                f"Motif id '{motif.motif_id}' already exists in the knowledge base."
            )
        self._motifs[motif.motif_id] = motif

    def add_many(self, motifs: Iterable[TopologicalMotif]) -> None:
        for motif in motifs:
            self.add(motif)

    def merge_motifs(
        self,
        motifs: Iterable[TopologicalMotif],
        *,
        dedupe_isomorphic: bool = True,
    ) -> IngestReport:
        """Safely merge distilled motifs, de-duplicating ids & isomorphic shapes.

        Isomorphism is judged by the VF2 three-part criterion
        (:func:`vf2_isomorphism_key`): topology + edge action basis Σ +
        discrete flow prototypes.  Returns an :class:`IngestReport`
        describing what was added vs skipped.  Existing records are never
        overwritten.
        """
        report = IngestReport()
        existing_keys: set[tuple[Any, ...]] = {
            vf2_isomorphism_key(m) for m in self._motifs.values()
        }
        for motif in motifs:
            if motif.motif_id in self._motifs:
                report.duplicate_ids.append(motif.motif_id)
                continue
            if dedupe_isomorphic:
                key = vf2_isomorphism_key(motif)
                if key in existing_keys:
                    report.isomorphic_skips.append(motif.motif_id)
                    continue
                existing_keys.add(key)
            self._motifs[motif.motif_id] = motif
            report.added.append(motif.motif_id)
        return report

    def get(self, motif_id: str) -> TopologicalMotif:
        try:
            return self._motifs[motif_id]
        except KeyError as exc:  # provide a friendlier message
            raise KeyError(f"Unknown motif id: '{motif_id}'") from exc

    def remove(self, motif_id: str) -> None:
        del self._motifs[motif_id]

    def clear(self) -> None:
        self._motifs.clear()

    # ------------------------------------------------------------ accessors
    def __len__(self) -> int:
        return len(self._motifs)

    def __iter__(self) -> Iterator[TopologicalMotif]:
        return iter(self._motifs.values())

    def __contains__(self, motif_id: str) -> bool:
        return motif_id in self._motifs

    @property
    def motif_ids(self) -> list[str]:
        """Stable (insertion-ordered) list of motif identifiers."""
        return list(self._motifs.keys())

    def semantic_texts(self) -> dict[str, str]:
        """Vector-ready corpus: ``{motif_id: flatten_text}``."""
        return {mid: m.semantic_text() for mid, m in self._motifs.items()}

    # ------------------------------------------------------------- JSON I/O
    def to_json_str(self, *, indent: int | None = 2) -> str:
        """Serialize the whole KB into a JSON string (schema-compliant)."""
        payload: list[dict[str, Any]] = [
            m.model_dump(mode="json") for m in self._motifs.values()
        ]
        return json.dumps(payload, indent=indent, ensure_ascii=False)

    def save(self, path: str | Path) -> None:
        """Persist to a UTF-8 JSON file (atomic-ish write via temp file)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(self.to_json_str(), encoding="utf-8")
        tmp.replace(target)

    @classmethod
    def from_json_str(cls, raw: str) -> "MotifKnowledgeBase":
        """Rebuild a KB from JSON produced by :meth:`to_json_str`."""
        payload: Any = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("Knowledge base JSON must be a list of motifs.")
        motifs = [TopologicalMotif.model_validate(item) for item in payload]
        return cls(motifs)

    @classmethod
    def load(cls, path: str | Path) -> "MotifKnowledgeBase":
        """Load a KB from a UTF-8 JSON file."""
        return cls.from_json_str(Path(path).read_text(encoding="utf-8"))

    # ------------------------------------------------------------ internals
    def as_mapping(self) -> Mapping[str, TopologicalMotif]:
        """Read-only view over the internal registry."""
        return self._motifs


def build_default_knowledge_base() -> MotifKnowledgeBase:
    """Factory: KB seeded with the production motif set (:mod:`mock_data`)."""
    from .mock_data import SEED_MOTIFS  # local import avoids circularity

    return MotifKnowledgeBase(SEED_MOTIFS)
