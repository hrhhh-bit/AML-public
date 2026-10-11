"""Centralised hyper-parameter configuration (Stage-3 Part C).

Option A: **YAML + dataclass** unified configuration system.

Three logical domains mirroring the codebase's hard-coded constants
(audited from source, Zero-Delta defaults):

- :class:`RetrievalConfig` — dual-track retrieval domain
  (``DualTrackMotifRetriever`` / ``aml_rag.embedding``).
- :class:`TopologyConfig` — topology axiom domain
  (``MotifConstraints`` / ``FLOW_TOLERANCE`` / ``BehavioralEnvironment`` /
  ``HardVerifier`` / ``RewardConfig``).
- :class:`AgentConfig` — planning-agent domain
  (``PlannerAgent`` / ``LLMClient`` / ``PromptContextCompressor``).

:class:`AMLConfig` aggregates the three domains and supports non-intrusive
loading from a YAML file (``AMLConfig.load_yaml``).  Component constructors
accept an optional ``config=`` keyword; when omitted they transparently
resolve the default configuration via :func:`load_default_config` — which
returns in-memory defaults identical to the legacy hard-coded values
(no file IO, no behaviour change), unless the ``AML_CONFIG_PATH``
environment variable points at a YAML override file.

Field names are verbatim mirrors of the audited source symbols — no
invented names, no silent drift.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

try:  # PyYAML is the only optional dependency of this module
    import yaml  # type: ignore[import-not-found]

    _HAS_YAML = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_YAML = False

__all__ = [
    "AML_CONFIG_PATH_ENV",
    "RetrievalConfig",
    "TopologyConfig",
    "AgentConfig",
    "AMLConfig",
    "load_default_config",
    "yaml_is_available",
]

#: Environment variable pointing at a YAML file used as the transparent
#: default when constructors receive ``config=None``.
AML_CONFIG_PATH_ENV: str = "AML_CONFIG_PATH"

#: Valid macro node roles (mirrors :class:`aml_rag.schema.NodeRole` values;
#: kept as plain strings so this module never upward-depends on schema).
_VALID_INITIAL_ROLES: frozenset[str] = frozenset(
    {
        "Source",
        "Intermediate",
        "Asset_Conversion",
        "Cross_Chain",
        "Aggregator",
        "Target",
    }
)


def yaml_is_available() -> bool:
    """Return True when the ``PyYAML`` package is importable."""
    return _HAS_YAML


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _build_from_section(cls: type[Any], section: Any) -> Any:
    """Construct a config dataclass from a raw mapping.

    Unknown keys raise ``ValueError`` (typo protection); missing keys fall
    back to the dataclass field defaults.
    """
    section = section or {}
    if not isinstance(section, dict):
        raise ValueError(f"{cls.__name__}: section must be a mapping, got {type(section).__name__}")
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(section) - known)
    if unknown:
        raise ValueError(
            f"{cls.__name__}: unknown configuration key(s) {unknown}; "
            f"valid keys are {sorted(known)}"
        )
    return cls(**{f.name: section[f.name] for f in fields(cls) if f.name in section})


# ---------------------------------------------------------------------------
# Retrieval domain
# ---------------------------------------------------------------------------
@dataclass
class RetrievalConfig:
    """Dual-track retrieval hyper-parameters.

    Every default equals the audited source default (Zero-Delta):
    ``DualTrackMotifRetriever.__init__`` / ``embedding.DEFAULT_DENSE_MODEL``.
    """

    alpha: float = 0.5
    """Weight of the semantic track; (1 - alpha) = rule-score weight."""
    top_k: int = 5
    """Default number of results returned per retrieval."""
    strict: bool = True
    """Hard precondition gate mode (False = soft fallback)."""
    cache_embeddings: bool = True
    """Cache per-motif vectors keyed by ``motif_id``."""
    coarse_k: int | None = None
    """Stage-1 dense pre-screen window; None = keep every candidate."""
    dense_model_name: str = "all-MiniLM-L6-v2"
    """Default pre-trained dense model (``DEFAULT_DENSE_MODEL``)."""

    def __post_init__(self) -> None:
        _require(0.0 <= self.alpha <= 1.0, "retrieval.alpha must be in [0, 1]")
        _require(self.top_k >= 1, "retrieval.top_k must be >= 1")
        _require(
            self.coarse_k is None or self.coarse_k >= 1,
            "retrieval.coarse_k must be >= 1 or null",
        )
        _require(bool(self.dense_model_name), "retrieval.dense_model_name must be non-empty")


# ---------------------------------------------------------------------------
# Topology axiom domain
# ---------------------------------------------------------------------------
@dataclass
class TopologyConfig:
    """Hard structural axioms of the behavioural graph environment.

    Defaults mirror ``MotifConstraints``, ``FLOW_TOLERANCE``,
    ``BehavioralEnvironment.__init__`` and ``RewardConfig``.
    """

    d_max: int = 4
    """Maximum out-degree / branching factor (``max_branching_factor``)."""
    min_level_bound: int = 2
    """Global step interval lower bound L_min."""
    max_level_bound: int = 8
    """Maximum graph depth L_max (``max_level_bound``)."""
    require_acyclic: bool = True
    """Motif DAG must be acyclic."""
    flow_tolerance: float = 0.01
    """Normalised flow-conservation tolerance (``FLOW_TOLERANCE``)."""
    max_steps: int = 64
    """Environment step budget (``BehavioralEnvironment.max_steps``)."""
    seed_chain: str = "Chain_A"
    """Initial abstract chain label."""
    initial_role: str = "Source"
    """Initial frontier node role (a ``NodeRole`` value)."""
    reward_legal: float = 0.0
    """Reward for a legal step (``RewardConfig.legal``)."""
    reward_illegal: float = -1.0
    """Reward for an illegal step (``RewardConfig.illegal``)."""
    reward_terminate: float = 1.0
    """Reward for successful termination (``RewardConfig.terminate``)."""

    def __post_init__(self) -> None:
        _require(self.d_max >= 1, "topology.d_max must be >= 1")
        _require(self.min_level_bound >= 1, "topology.min_level_bound must be >= 1")
        _require(self.max_level_bound >= 1, "topology.max_level_bound must be >= 1")
        _require(
            self.min_level_bound <= self.max_level_bound,
            "topology.min_level_bound must be <= max_level_bound",
        )
        _require(self.flow_tolerance > 0.0, "topology.flow_tolerance must be > 0")
        _require(self.max_steps >= 1, "topology.max_steps must be >= 1")
        _require(bool(self.seed_chain), "topology.seed_chain must be non-empty")
        _require(
            self.initial_role in _VALID_INITIAL_ROLES,
            f"topology.initial_role must be one of {sorted(_VALID_INITIAL_ROLES)}",
        )


# ---------------------------------------------------------------------------
# Planning agent domain
# ---------------------------------------------------------------------------
@dataclass
class AgentConfig:
    """Planner / LLM-client / prompt-compressor hyper-parameters.

    Defaults mirror ``PlannerAgent.__init__``, ``aml_agent.client`` module
    constants and ``PromptContextCompressor.__init__``.
    """

    planner_top_k: int = 3
    """RAG candidates injected per planning step (``PlannerAgent.top_k``)."""
    planner_max_retries: int = 3
    """Reflection retry cap (``PlannerAgent.max_retries``)."""
    temperature: float = 0.1
    """LLM sampling temperature (``DEFAULT_TEMPERATURE``)."""
    default_model: str = "deepseek-flash"
    """Default model name (``DEFAULT_MODEL``)."""
    base_url: str = "https://api.deepseek.com"
    """Default API base URL (``DEFAULT_BASE_URL``)."""
    timeout: float = 60.0
    """Network timeout in seconds (``LLMClient.timeout``)."""
    llm_max_retries: int = 3
    """HTTP/network retry budget (``LLMClient.max_retries``)."""
    backoff_base: float = 2.0
    """Exponential backoff base (``LLMClient.backoff_base``)."""
    compressor_max_motifs: int = 5
    """Prompt-compressor motif cap (``PromptContextCompressor.max_motifs``)."""
    compressor_output_format: str = "hybrid"
    """Compressor output format: 'json' | 'mermaid' | 'hybrid'."""
    compressor_include_scores: bool = True
    """Annotate compressed motifs with retrieval scores."""
    compressor_token_budget_hint: int | None = None
    """Optional token budget for prompt trimming."""

    def __post_init__(self) -> None:
        _require(self.planner_top_k >= 1, "agent.planner_top_k must be >= 1")
        _require(
            self.planner_max_retries >= 0,
            "agent.planner_max_retries must be >= 0",
        )
        _require(self.timeout > 0.0, "agent.timeout must be > 0")
        _require(self.llm_max_retries >= 0, "agent.llm_max_retries must be >= 0")
        _require(self.backoff_base >= 1.0, "agent.backoff_base must be >= 1.0")
        _require(self.compressor_max_motifs >= 1, "agent.compressor_max_motifs must be >= 1")
        _require(
            self.compressor_output_format in ("json", "mermaid", "hybrid"),
            "agent.compressor_output_format must be one of json/mermaid/hybrid",
        )


# ---------------------------------------------------------------------------
# Aggregate configuration
# ---------------------------------------------------------------------------
@dataclass
class AMLConfig:
    """Unified, strongly-typed configuration root (three logical domains)."""

    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    topology: TopologyConfig = field(default_factory=TopologyConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

    # ------------------------------------------------------------------ load
    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AMLConfig":
        """Build an :class:`AMLConfig` from a raw mapping.

        ``{"retrieval": {...}, "topology": {...}, "agent": {...}}`` —
        each section optional (missing keys keep Zero-Delta defaults);
        unknown keys inside any section raise ``ValueError``.
        """
        data = data or {}
        if not isinstance(data, dict):
            raise ValueError(f"AMLConfig: expected a mapping, got {type(data).__name__}")
        unknown = sorted(set(data) - {"retrieval", "topology", "agent"})
        if unknown:
            raise ValueError(
                f"AMLConfig: unknown top-level key(s) {unknown}; "
                "valid sections are ['retrieval', 'topology', 'agent']"
            )
        return cls(
            retrieval=_build_from_section(RetrievalConfig, data.get("retrieval")),
            topology=_build_from_section(TopologyConfig, data.get("topology")),
            agent=_build_from_section(AgentConfig, data.get("agent")),
        )

    @classmethod
    def load_yaml(cls, path: str | os.PathLike[str]) -> "AMLConfig":
        """Load an :class:`AMLConfig` from a YAML file (non-intrusive read).

        Raises ``RuntimeError`` when PyYAML is unavailable and ``ValueError``
        on malformed content / unknown keys.
        """
        if not _HAS_YAML:
            raise RuntimeError(
                "PyYAML is required to load configuration files "
                "(pip install pyyaml)"
            )
        yaml_path = Path(path)
        with yaml_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if raw is None:
            raw = {}
        return cls.from_dict(raw)

    # ------------------------------------------------------------------ dump
    def to_dict(self) -> dict[str, Any]:
        """Round-trippable plain-dict representation (``asdict``)."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Transparent default resolution for dependency-injection constructors
# ---------------------------------------------------------------------------
def load_default_config(config: AMLConfig | None = None) -> AMLConfig:
    """Resolve the effective configuration for a DI constructor.

    Resolution order:

    1. an explicit :class:`AMLConfig` instance (returned unchanged);
    2. the YAML file referenced by ``AML_CONFIG_PATH`` (when set);
    3. in-memory :class:`AMLConfig` defaults — identical to the legacy
       hard-coded values, so ``config=None`` is always Zero-Delta.

    No file IO happens unless ``AML_CONFIG_PATH`` is explicitly set.
    """
    if config is not None:
        return config
    env_path = os.getenv(AML_CONFIG_PATH_ENV)
    if env_path:
        return AMLConfig.load_yaml(env_path)
    return AMLConfig()
