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

from .config import (
    AML_CONFIG_PATH_ENV,
    AgentConfig,
    AMLConfig,
    RetrievalConfig,
    TopologyConfig,
    load_default_config,
    yaml_is_available,
)
from .context_builder import PromptContextCompressor
from .distiller import (
    DISTILLATION_SYSTEM_PROMPT_V2,
    DistillationFailure,
    DistillationPromptBuilder,
    DistillationResult,
    MotifDistiller,
    TextChunker,
    detect_survey_report,
    focus_survey_case_narrative,
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
from .prompt_v2 import (
    ATTENTION_ANCHOR_HEADER,
    CAMPAIGN_DIRECTIVE,
    DISTILLATION_PROMPT_V2,
    MAX_EDGE_COUNT,
    MIN_EDGE_COUNT,
    PHASE_A,
    PHASE_B,
    SINGLE_PASS_MAX_CHARS,
    SURVEY_DIRECTIVE,
    ParsedV2Payload,
    PhaseMotif,
    PromptV2Distiller,
    TwoPhaseDistillResult,
    annotate_stage_boundaries,
    build_v2_prompt,
    build_v2_schema_json,
    format_attention_anchor,
    parse_v2_response,
    scrub_micro_noise,
    scrub_motif_metadata,
    validate_grounded_chains,
)
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
    "detect_survey_report",
    "focus_survey_case_narrative",
    "DistillationPromptBuilder",
    "MotifDistiller",
    "DistillationResult",
    "DistillationFailure",
    # prompt v2 (two-phase entity-grounded contract)
    "DISTILLATION_PROMPT_V2",
    "ATTENTION_ANCHOR_HEADER",
    "SURVEY_DIRECTIVE",
    "CAMPAIGN_DIRECTIVE",
    "PHASE_A",
    "PHASE_B",
    "MIN_EDGE_COUNT",
    "MAX_EDGE_COUNT",
    "SINGLE_PASS_MAX_CHARS",
    "PhaseMotif",
    "ParsedV2Payload",
    "TwoPhaseDistillResult",
    "PromptV2Distiller",
    "build_v2_prompt",
    "build_v2_schema_json",
    "format_attention_anchor",
    "parse_v2_response",
    "scrub_micro_noise",
    "scrub_motif_metadata",
    "annotate_stage_boundaries",
    "validate_grounded_chains",
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
    # config (Stage-3 Part C)
    "AMLConfig",
    "RetrievalConfig",
    "TopologyConfig",
    "AgentConfig",
    "load_default_config",
    "yaml_is_available",
    "AML_CONFIG_PATH_ENV",
    "__version__",
]
