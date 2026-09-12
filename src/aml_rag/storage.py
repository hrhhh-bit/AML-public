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
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .schema import TopologicalMotif

__all__ = ["MotifKnowledgeBase", "build_default_knowledge_base"]


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
