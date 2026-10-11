"""Stage-3 Part C: unit tests for the centralised config system.

Covers the three acceptance pillars:

1. **Zero-Delta template**: ``config/default_config.yaml`` values must equal
   the audited legacy hard-coded defaults exactly (no behavioural drift).
2. **Loading & dynamic override**: ``AMLConfig.from_dict`` / ``load_yaml`` /
   ``to_dict`` round-trips, unknown-key typo protection, env-var transparent
   loading (``AML_CONFIG_PATH``).
3. **Dependency injection takes effect**: injecting ``config=`` into
   ``DualTrackMotifRetriever`` / ``HardVerifier`` / ``BehavioralEnvironment`` /
   ``PlannerAgent`` / ``LLMClient`` actually changes runtime behaviour, while
   explicit keyword arguments always win and ``config=None`` keeps the legacy
   defaults byte-for-byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_agent.client import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_TEMPERATURE, LLMClient
from aml_agent.planner import PlannerAgent
from aml_env import BehavioralEnvironment, HardVerifier
from aml_rag import (
    AMLConfig,
    AgentConfig,
    CurrentState,
    DualTrackMotifRetriever,
    MotifConstraints,
    QueryContext,
    RetrievalConfig,
    TopologyConfig,
    build_default_knowledge_base,
    load_default_config,
)
from aml_rag.config import AML_CONFIG_PATH_ENV, yaml_is_available

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YAML = PROJECT_ROOT / "config" / "default_config.yaml"


# ---------------------------------------------------------------------------
# 1. Zero-Delta defaults vs. audited source constants
# ---------------------------------------------------------------------------
class TestZeroDeltaDefaults:
    def test_retrieval_defaults(self) -> None:
        rc = RetrievalConfig()
        assert rc.alpha == 0.5
        assert rc.top_k == 5
        assert rc.strict is True
        assert rc.cache_embeddings is True
        assert rc.coarse_k is None
        assert rc.dense_model_name == "all-MiniLM-L6-v2"

    def test_topology_defaults(self) -> None:
        tc = TopologyConfig()
        assert tc.d_max == 4
        assert tc.min_level_bound == 2
        assert tc.max_level_bound == 8
        assert tc.require_acyclic is True
        assert tc.flow_tolerance == 0.01
        assert tc.max_steps == 64
        assert tc.seed_chain == "Chain_A"
        assert tc.initial_role == "Source"
        assert tc.reward_legal == 0.0
        assert tc.reward_illegal == -1.0
        assert tc.reward_terminate == 1.0

    def test_agent_defaults(self) -> None:
        ac = AgentConfig()
        assert ac.planner_top_k == 3
        assert ac.planner_max_retries == 3
        assert ac.temperature == DEFAULT_TEMPERATURE
        assert ac.default_model == DEFAULT_MODEL
        assert ac.base_url == DEFAULT_BASE_URL
        assert ac.timeout == 60.0
        assert ac.llm_max_retries == 3
        assert ac.backoff_base == 2.0
        assert ac.compressor_max_motifs == 5
        assert ac.compressor_output_format == "hybrid"
        assert ac.compressor_include_scores is True
        assert ac.compressor_token_budget_hint is None

    def test_legacy_components_use_same_defaults(self) -> None:
        # components built without config must reflect the audited defaults
        retriever = DualTrackMotifRetriever(build_default_knowledge_base())
        assert retriever.alpha == 0.5
        assert retriever.top_k == 5
        assert retriever.strict is True
        assert retriever.cache_embeddings is True
        assert retriever.coarse_k is None

        env = BehavioralEnvironment()
        assert env.constraints.max_branching_factor == 4
        assert env.constraints.max_level_bound == 8
        assert env.constraints.min_level_bound == 2
        assert env._max_steps == 64  # noqa: SLF001 - deliberate white-box check

        verifier = HardVerifier()
        assert verifier.constraints.max_branching_factor == 4
        assert verifier.constraints.require_acyclic is True


# ---------------------------------------------------------------------------
# 2. YAML template Zero-Delta + loading / override
# ---------------------------------------------------------------------------
class TestYamlLoading:
    def test_default_yaml_matches_builtin_defaults_exactly(self) -> None:
        """The shipped template must be 100% identical to in-memory defaults."""
        if not yaml_is_available():
            pytest.skip("PyYAML not installed")
        loaded = AMLConfig.load_yaml(DEFAULT_YAML)
        assert loaded == AMLConfig()

    def test_from_dict_partial_override(self) -> None:
        cfg = AMLConfig.from_dict(
            {
                "retrieval": {"alpha": 0.8, "top_k": 7},
                "topology": {"d_max": 3},
            }
        )
        assert cfg.retrieval.alpha == 0.8
        assert cfg.retrieval.top_k == 7
        assert cfg.retrieval.coarse_k is None  # untouched default
        assert cfg.topology.d_max == 3
        assert cfg.topology.max_level_bound == 8  # untouched default
        assert cfg.agent.planner_top_k == 3  # untouched default

    def test_to_dict_round_trip(self) -> None:
        cfg = AMLConfig.from_dict({"retrieval": {"alpha": 0.9}})
        assert AMLConfig.from_dict(cfg.to_dict()) == cfg

    def test_unknown_keys_raise(self) -> None:
        with pytest.raises(ValueError, match="unknown"):
            AMLConfig.from_dict({"retrieval": {"alhpa": 0.5}})  # typo
        with pytest.raises(ValueError, match="unknown top-level"):
            AMLConfig.from_dict({"retrival": {}})

    def test_invalid_values_raise(self) -> None:
        with pytest.raises(ValueError):
            RetrievalConfig(alpha=1.5)
        with pytest.raises(ValueError):
            RetrievalConfig(top_k=0)
        with pytest.raises(ValueError):
            TopologyConfig(min_level_bound=9, max_level_bound=8)

    def test_load_yaml_round_trip(self, tmp_path: Path) -> None:
        if not yaml_is_available():
            pytest.skip("PyYAML not installed")
        path = tmp_path / "cfg.yaml"
        path.write_text(
            "retrieval:\n  alpha: 0.25\n  coarse_k: 12\ntopology:\n"
            "  d_max: 2\nagent:\n  planner_max_retries: 1\n",
            encoding="utf-8",
        )
        cfg = AMLConfig.load_yaml(path)
        assert cfg.retrieval.alpha == 0.25
        assert cfg.retrieval.coarse_k == 12
        assert cfg.topology.d_max == 2
        assert cfg.agent.planner_max_retries == 1
        assert cfg.agent.temperature == DEFAULT_TEMPERATURE  # untouched

    def test_env_var_transparent_loading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if not yaml_is_available():
            pytest.skip("PyYAML not installed")
        path = tmp_path / "cfg.yaml"
        path.write_text("topology:\n  d_max: 3\n", encoding="utf-8")
        monkeypatch.setenv(AML_CONFIG_PATH_ENV, str(path))
        cfg = load_default_config()
        assert cfg.topology.d_max == 3
        monkeypatch.delenv(AML_CONFIG_PATH_ENV)
        assert load_default_config() == AMLConfig()

    def test_load_default_config_passthrough(self) -> None:
        explicit = AMLConfig.from_dict({"topology": {"d_max": 2}})
        assert load_default_config(explicit) is explicit


# ---------------------------------------------------------------------------
# 3. Dependency injection takes effect (and explicit kwargs win)
# ---------------------------------------------------------------------------
def _motifs():
    return build_default_knowledge_base()


class TestRetrieverInjection:
    def test_config_sets_hyper_parameters(self) -> None:
        cfg = AMLConfig.from_dict(
            {
                "retrieval": {
                    "alpha": 1.0,
                    "top_k": 2,
                    "strict": False,
                    "cache_embeddings": False,
                    "coarse_k": 3,
                }
            }
        )
        retriever = DualTrackMotifRetriever(_motifs(), config=cfg)
        assert retriever.alpha == 1.0
        assert retriever.top_k == 2
        assert retriever.strict is False
        assert retriever.cache_embeddings is False
        assert retriever.coarse_k == 3

    def test_explicit_kwargs_override_config(self) -> None:
        cfg = AMLConfig.from_dict(
            {"retrieval": {"alpha": 1.0, "coarse_k": 12, "top_k": 9}}
        )

        retriever = DualTrackMotifRetriever(
            _motifs(), config=cfg, alpha=0.25, coarse_k=None
        )
        assert retriever.alpha == 0.25
        assert retriever.coarse_k is None  # explicit None keeps "no pre-screen"
        assert retriever.top_k == 9  # untouched by kwargs -> from config

    def test_config_affects_ranking(self) -> None:
        """alpha=1.0 => pure semantic ranking (rule score ignored)."""
        kb = _motifs()
        cfg = AMLConfig.from_dict({"retrieval": {"alpha": 1.0}})
        retriever = DualTrackMotifRetriever(kb, config=cfg)
        state = CurrentState(current_level=0, current_chain="Chain_A")
        query = QueryContext(scenario="scenario", tactic_goal="goal")
        results = retriever.retrieve(state, query, top_k=5)
        assert results
        for r in results:
            # alpha=1 -> combined == semantic (+ tiny pattern bias)
            assert r.combined_score == pytest.approx(r.semantic_score, abs=1e-5)


class TestTopologyInjection:
    def test_environment_derives_from_config(self) -> None:
        cfg = AMLConfig.from_dict(
            {
                "topology": {
                    "d_max": 2,
                    "max_level_bound": 4,
                    "min_level_bound": 2,
                    "max_steps": 10,
                    "seed_chain": "Chain_B",
                    "initial_role": "Intermediate",
                }
            }
        )
        env = BehavioralEnvironment(config=cfg)
        assert env.constraints.max_branching_factor == 2
        assert env.constraints.max_level_bound == 4
        assert env._max_steps == 10  # noqa: SLF001
        assert env._seed_chain == "Chain_B"  # noqa: SLF001
        assert env._initial_role.value == "Intermediate"  # noqa: SLF001

    def test_verifier_derives_from_config(self) -> None:
        cfg = AMLConfig.from_dict({"topology": {"d_max": 3}})
        verifier = HardVerifier(config=cfg)
        assert verifier.constraints.max_branching_factor == 3

    def test_explicit_constraints_override_config(self) -> None:
        cfg = AMLConfig.from_dict({"topology": {"d_max": 3}})
        explicit = MotifConstraints(max_branching_factor=6)
        assert HardVerifier(explicit, config=cfg).constraints is explicit


class TestAgentInjection:
    def test_planner_derives_from_config(self) -> None:
        cfg = AMLConfig.from_dict(
            {
                "agent": {
                    "planner_top_k": 2,
                    "planner_max_retries": 1,
                    "compressor_max_motifs": 3,
                    "compressor_output_format": "json",
                }
            }
        )
        env = BehavioralEnvironment()
        retriever = DualTrackMotifRetriever(_motifs())
        planner = PlannerAgent(env, retriever, llm=None, config=cfg)
        assert planner._top_k == 2  # noqa: SLF001
        assert planner._max_retries == 1  # noqa: SLF001
        assert planner._compressor.max_motifs == 3  # noqa: SLF001
        assert planner._compressor.output_format == "json"  # noqa: SLF001

    def test_client_derives_from_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_BASE_URL",
                    "DEEPSEEK_MODEL"):
            monkeypatch.delenv(key, raising=False)
        cfg = AMLConfig.from_dict(
            {
                "agent": {
                    "temperature": 0.7,
                    "default_model": "deepseek-cfg-model",
                    "base_url": "https://cfg.example",
                    "timeout": 30.0,
                    "llm_max_retries": 1,
                }
            }
        )
        client = LLMClient(config=cfg)
        assert client.model == "deepseek-cfg-model"
        assert client.base_url == "https://cfg.example"
        assert client.temperature == 0.7
        assert client.timeout == 30.0
        assert client.max_retries == 1

    def test_client_env_vars_win_over_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_BASE_URL",
                    "DEEPSEEK_MODEL"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example")
        cfg = AMLConfig.from_dict(
            {"agent": {"default_model": "cfg-model", "base_url": "https://cfg.example"}}
        )
        client = LLMClient(config=cfg)
        assert client.model == "env-model"
        assert client.base_url == "https://env.example"

    def test_client_without_config_keeps_legacy_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_BASE_URL",
                    "DEEPSEEK_MODEL"):
            monkeypatch.delenv(key, raising=False)
        client = LLMClient()
        assert client.model == DEFAULT_MODEL
        assert client.base_url == DEFAULT_BASE_URL
        assert client.temperature == DEFAULT_TEMPERATURE
        assert client.timeout == 60.0
        assert client.max_retries == 3


# ---------------------------------------------------------------------------
# Template file hygiene (the shipped artifact itself)
# ---------------------------------------------------------------------------
class TestTemplateArtifact:
    def test_template_exists_and_parseable(self) -> None:
        assert DEFAULT_YAML.exists()
        if yaml_is_available():
            import yaml

            data = yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8"))
            assert set(data) == {"retrieval", "topology", "agent"}

    def test_template_serialises_to_json_compatible_dict(self) -> None:
        cfg = AMLConfig()
        blob = json.dumps(cfg.to_dict())  # must not raise (no exotic types)
        assert "retrieval" in blob and "topology" in blob and "agent" in blob
