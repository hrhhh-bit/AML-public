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
from .distiller import (
    DISTILLATION_SYSTEM_PROMPT_V2,
    DistillationFailure,
    DistillationPromptBuilder,
    DistillationResult,
    MotifDistiller,
    TextChunker,
)
from .embedding import (
    DEFAULT_DENSE_MODEL,
    DenseEmbeddingProvider,
    DeterministicHashEmbedder,
    DiscreteEmbeddingProvider,
    EmbeddingProvider,
    cosine_similarity,
    is_sentence_transformers_available,
    make_embedding_provider,
)
from .evaluation import (
    CrossSourceConsistencyEvaluator,
    CrossSourceReport,
    NoiseAuditReport,
    SaturationPoint,
    TopologyValidityReport,
    cross_source_consistency,
    motif_topology_issues,
    saturation_analysis,
    topology_validity,
    zero_noise_audit,
)
from .extractor import (
    DISTILLATION_SYSTEM_PROMPT,
    DistillationError,
    DistillationParseError,
    MotifExtractor,
)
from .json_utils import (
    extract_json_list,
    extract_outermost_json,
    load_json_robust,
    strip_code_fences,
)
from .mock_data import SEED_MOTIFS, build_seed_motifs
from .retriever import (
    DualTrackMotifRetriever,
    RetrievalResult,
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
from .storage import (
    IngestReport,
    MotifKnowledgeBase,
    build_default_knowledge_base,
    FlowPrototype,
    classify_flow_prototype,
    edge_action_basis,
    node_flow_prototypes,
    vf2_isomorphism_key,
)

__version__ = "0.4.0"

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
    "IngestReport",
    "build_default_knowledge_base",
    # storage: flow prototypes & VF2 isomorphism (Direction A)
    "FlowPrototype",
    "classify_flow_prototype",
    "node_flow_prototypes",
    "edge_action_basis",
    "vf2_isomorphism_key",
    # extractor
    "DISTILLATION_SYSTEM_PROMPT",
    "DistillationError",
    "DistillationParseError",
    "MotifExtractor",
    # distiller
    "DISTILLATION_SYSTEM_PROMPT_V2",
    "TextChunker",
    "DistillationPromptBuilder",
    "MotifDistiller",
    "DistillationResult",
    "DistillationFailure",
    # evaluation
    "topology_validity",
    "motif_topology_issues",
    "cross_source_consistency",
    "CrossSourceConsistencyEvaluator",
    "zero_noise_audit",
    "saturation_analysis",
    "TopologyValidityReport",
    "CrossSourceReport",
    "NoiseAuditReport",
    "SaturationPoint",
    # json utils
    "strip_code_fences",
    "extract_outermost_json",
    "load_json_robust",
    "extract_json_list",
    # retriever
    "DualTrackMotifRetriever",
    "RetrievalResult",
    # embedding providers (Stage-3 Part A)
    "EmbeddingProvider",
    "DeterministicHashEmbedder",
    "DiscreteEmbeddingProvider",
    "DenseEmbeddingProvider",
    "make_embedding_provider",
    "is_sentence_transformers_available",
    "DEFAULT_DENSE_MODEL",
    "cosine_similarity",
    # context builder
    "PromptContextCompressor",
    "__version__",
]
