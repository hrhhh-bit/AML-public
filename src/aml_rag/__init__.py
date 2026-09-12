"""aml_rag — Module 1: AML Topological Prior Knowledge Base & Dual-Track RAG.

Stage-1 prior knowledge engine for the Cross-Chain AML Behavioral Graph
Generation framework.  Provides:

- Pydantic v2 data contracts (:mod:`aml_rag.schema`)
- Curated seed motifs (:mod:`aml_rag.mock_data`)
- Knowledge base storage (:mod:`aml_rag.storage`)
- LLM distillation pipeline (:mod:`aml_rag.extractor`)
- Dual-track retriever (:mod:`aml_rag.retriever`)
- Agent prompt compression (:mod:`aml_rag.context_builder`)
"""

from __future__ import annotations

from .context_builder import PromptContextCompressor
from .extractor import (
    DISTILLATION_SYSTEM_PROMPT,
    DistillationError,
    DistillationParseError,
    MotifExtractor,
)
from .mock_data import SEED_MOTIFS, build_seed_motifs
from .retriever import (
    DeterministicHashEmbedder,
    DualTrackMotifRetriever,
    RetrievalResult,
    cosine_similarity,
)
from .schema import (
    AbstractEdge,
    AbstractNode,
    CurrentState,
    MotifConstraints,
    NodeRole,
    OperationType,
    PatternType,
    PostStateEffect,
    Preconditions,
    QueryContext,
    TopologicalMotif,
)
from .storage import MotifKnowledgeBase, build_default_knowledge_base

__version__ = "0.1.0"

__all__ = [
    # schema
    "NodeRole",
    "OperationType",
    "PatternType",
    "AbstractNode",
    "AbstractEdge",
    "Preconditions",
    "PostStateEffect",
    "MotifConstraints",
    "TopologicalMotif",
    "CurrentState",
    "QueryContext",
    # data
    "build_seed_motifs",
    "SEED_MOTIFS",
    # storage
    "MotifKnowledgeBase",
    "build_default_knowledge_base",
    # extractor
    "DISTILLATION_SYSTEM_PROMPT",
    "DistillationError",
    "DistillationParseError",
    "MotifExtractor",
    # retriever
    "DeterministicHashEmbedder",
    "DualTrackMotifRetriever",
    "RetrievalResult",
    "cosine_similarity",
    # context builder
    "PromptContextCompressor",
    "__version__",
]
