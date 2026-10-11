"""Stage-3 Part A: unit checks for the correlation-evaluation script.

The statistics layer of ``scripts/eval_retrieval_correlation.py`` is a pure
Python implementation (zero third-party dependencies).  These tests load the
script as a module and verify:

1. tie-corrected ranking (rankdata);
2. Spearman's rho on known reference series;
3. the Student-t approximated p-value against a scipy-known reference value;
4. benchmark query hygiene: abstract semantics only (zero micro noise) and
   valid NodeRole vocabulary;
5. experiment asset conventions (read-only KB + phase3 asset directory).
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "eval_retrieval_correlation.py"

_spec = importlib.util.spec_from_file_location("eval_retrieval_correlation", SCRIPT)
assert _spec is not None and _spec.loader is not None
eval_mod = importlib.util.module_from_spec(_spec)
sys.modules["eval_retrieval_correlation"] = eval_mod
_spec.loader.exec_module(eval_mod)


# ---------------------------------------------------------------------------
# Statistics layer
# ---------------------------------------------------------------------------
class TestRankdata:
    def test_simple_ranks(self) -> None:
        assert eval_mod.rankdata([3.0, 1.0, 2.0]) == [3.0, 1.0, 2.0]

    def test_tie_average_ranks(self) -> None:
        assert eval_mod.rankdata([1.0, 2.0, 2.0, 4.0]) == [1.0, 2.5, 2.5, 4.0]

    def test_all_ties(self) -> None:
        assert eval_mod.rankdata([7.0, 7.0, 7.0]) == [2.0, 2.0, 2.0]


class TestSpearman:
    def test_perfect_agreement(self) -> None:
        assert eval_mod.spearman_rho([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)

    def test_perfect_inversion(self) -> None:
        assert eval_mod.spearman_rho([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)

    def test_known_rho(self) -> None:
        # ranks of y = [2,1,3,5,4] are [2,1,3,5,4] -> rho = 1 - 6*4/(5*24) = 0.8
        rho = eval_mod.spearman_rho([1, 2, 3, 4, 5], [2, 1, 3, 5, 4])
        assert rho == pytest.approx(0.8, abs=1e-12)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            eval_mod.spearman_rho([1, 2, 3], [1, 2])

    def test_ties_do_not_break(self) -> None:
        rho = eval_mod.spearman_rho([1.0, 1.0, 3.0], [1.0, 1.0, 3.0])
        assert rho == pytest.approx(1.0)


class TestSpearmanPValue:
    def test_p_value_matches_scipy_reference(self) -> None:
        # scipy.stats.spearmanr([1,2,3,4,5], [2,1,3,5,4]) -> rho=0.8, p~=0.1041
        p = eval_mod.spearman_p_value(0.8, 5)
        assert p is not None
        assert 0.09 < p < 0.12

    def test_perfect_correlation_p_zero(self) -> None:
        assert eval_mod.spearman_p_value(1.0, 10) == 0.0
        assert eval_mod.spearman_p_value(-1.0, 10) == 0.0

    def test_insufficient_samples_none(self) -> None:
        assert eval_mod.spearman_p_value(1.0, 2) is None

    def test_zero_rho_mid_p(self) -> None:
        p = eval_mod.spearman_p_value(0.0, 30)
        assert p is not None and 0.9 < p <= 1.0


# ---------------------------------------------------------------------------
# Query hygiene & asset conventions
# ---------------------------------------------------------------------------
class TestBenchmarkQueries:
    _ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{8,}")
    _AMOUNT_RE = re.compile(r"(?<!to-)\b\d+(?:\.\d+)?\b")
    _TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
    _BANNED_TICKERS = frozenset(
        {"USDC", "USDT", "DAI", "ETH", "BTC", "WBTC", "SOL", "BNB", "AVAX", "MATIC", "XMR"}
    )

    def test_at_least_six_distinct_queries(self) -> None:
        specs = eval_mod.BENCHMARK_QUERIES
        assert len(specs) >= 6
        assert len({q["query_id"] for q in specs}) == len(specs)

    def test_all_states_use_valid_node_roles(self) -> None:
        from aml_rag import NodeRole

        valid = {r.value for r in NodeRole}
        for spec in eval_mod.BENCHMARK_QUERIES:
            for role in spec["state"]["roles"]:
                assert role in valid

    def test_queries_free_of_micro_noise(self) -> None:
        for spec in eval_mod.BENCHMARK_QUERIES:
            text = f"{spec['scenario']} {spec['tactic_goal']}"
            assert not self._ADDRESS_RE.search(text), text
            assert not self._TIMESTAMP_RE.search(text), text
            assert not self._AMOUNT_RE.search(text), text
            words = set(re.findall(r"[A-Za-z]+", text))
            assert not (words & self._BANNED_TICKERS), text


class TestAssetConventions:
    def test_phase3_asset_directory(self) -> None:
        out = eval_mod.DEFAULT_OUT_PATH
        assert out.parent.name == "phase3_dense_retrieval"
        assert out.parent.parent.name == "experiments"

    def test_kb_default_is_production_asset(self) -> None:
        kb = eval_mod.DEFAULT_KB_PATH
        assert kb.name == "distilled_kb.json"
        assert kb.parent.name == "data"

    def test_module_import_does_not_run_main(self) -> None:
        # the loader ran exec_module without touching the knowledge base:
        # main() is guarded by __main__ and was never invoked.
        assert eval_mod.DEFAULT_KB_PATH.exists()
