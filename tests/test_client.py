"""Offline tests for the OpenAI-compatible client & parser robustness.

No network access: HTTP is mocked.  Verifies:

- environment-variable driven configuration and defaults;
- successful chat + telemetry capture;
- 429/5xx exponential-backoff retry (then success / exhaustion);
- parser tolerance for CoT preambles, fences, trailing commas, array wrapper,
  and standardised syntax errors on unrecoverable JSON.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest import mock

import pytest

from aml_agent.client import DEFAULT_MODEL, LLMClient
from aml_agent.planner import parse_action_reply, strip_code_fences


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _ok_response(content: str, usage: dict | None = None) -> _FakeResponse:
    return _FakeResponse(
        {
            "choices": [{"message": {"content": content}}],
            "usage": usage or {"prompt_tokens": 12, "completion_tokens": 7},
        }
    )


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.deepseek.com/chat/completions",
        status,
        "Rate Limited" if status == 429 else "Server Error",
        {},
        io.BytesIO(b'{"error": "boom"}'),
    )


def _valid_action_json() -> str:
    return json.dumps(
        {
            "operation": "Transfer",
            "parent_ids": ["node_0"],
            "target_role": "Intermediate",
            "target_chain": "Chain_A",
        }
    )


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
def test_config_defaults_and_env_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_BASE_URL",
                "DEEPSEEK_MODEL"):
        monkeypatch.delenv(key, raising=False)

    client = LLMClient()
    assert client.model == DEFAULT_MODEL
    assert client.api_key is None  # unconfigured

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://custom.example/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash-custom")
    client = LLMClient()
    assert client.api_key == "sk-test"
    assert client.base_url == "https://custom.example/v1"
    assert client.model == "deepseek-flash-custom"

    # OPENAI_API_KEY fallback
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert LLMClient().api_key == "sk-openai"


# ---------------------------------------------------------------------------
# chat + telemetry
# ---------------------------------------------------------------------------
def test_chat_success_captures_telemetry() -> None:
    client = LLMClient(api_key="sk-test")
    with mock.patch("aml_agent.client.urllib.request.urlopen",
                    return_value=_ok_response("hello")) as mocked:
        out = client.chat("prompt")

    assert out == "hello"
    assert mocked.call_count == 1
    metrics = client.metrics
    assert metrics.total_calls == 1
    assert metrics.prompt_tokens == 12
    assert metrics.completion_tokens == 7
    assert client.last_call is not None and client.last_call.status == "ok"
    snap = metrics.snapshot()
    assert snap["prompt_tokens"] == 12 and snap["avg_latency_ms"] >= 0


def test_chat_429_then_success_with_backoff() -> None:
    client = LLMClient(api_key="sk-test", max_retries=3, backoff_base=2.0)
    with mock.patch("aml_agent.client.urllib.request.urlopen",
                    side_effect=[_http_error(429), _ok_response("ok")]) as mocked, \
         mock.patch("aml_agent.client.time.sleep") as sleep_mock:
        out = client.chat("p")

    assert out == "ok"
    assert mocked.call_count == 2
    sleep_mock.assert_called_once_with(2.0 ** 0)
    assert client.metrics.failed_calls == 0  # 429 retries are not recorded as failures


def test_chat_retry_exhaustion_raises() -> None:
    client = LLMClient(api_key="sk-test", max_retries=2)
    with mock.patch("aml_agent.client.urllib.request.urlopen",
                    side_effect=[_http_error(429)] * 3), \
         mock.patch("aml_agent.client.time.sleep"):
        with pytest.raises(RuntimeError, match="HTTP 429"):
            client.chat("p")
    assert client.metrics.failed_calls == 1


def test_chat_network_error_retries() -> None:
    client = LLMClient(api_key="sk-test", max_retries=1)
    with mock.patch(
        "aml_agent.client.urllib.request.urlopen",
        side_effect=[urllib.error.URLError("conn reset"), _ok_response("ok")],
    ), mock.patch("aml_agent.client.time.sleep"):
        assert client.chat("p") == "ok"


def test_chat_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="API key"):
        LLMClient().chat("p")


# ---------------------------------------------------------------------------
# parser robustness
# ---------------------------------------------------------------------------
def test_parse_chain_of_thought_with_fence() -> None:
    raw = (
        "Let me reason step by step.\n"
        "```json\n" + _valid_action_json() + "\n```\n"
        "This action seems reasonable."
    )
    action, err = parse_action_reply(raw)
    assert err is None and action is not None
    assert action.operation.value == "Transfer"


def test_parse_trailing_comma_repair() -> None:
    raw = '{"operation": "Transfer", "parent_ids": ["node_0"], ' \
          '"target_role": "Intermediate", "target_chain": "Chain_A",}'
    action, err = parse_action_reply(raw)
    assert err is None and action is not None


def test_parse_array_wrapper_takes_first() -> None:
    raw = "[" + _valid_action_json() + "]"
    action, err = parse_action_reply(raw)
    assert err is None and action is not None


def test_parse_unrecoverable_syntax_returns_standard_error() -> None:
    action, err = parse_action_reply('{"operation": "Transfer", "parent_ids":')
    assert action is None
    assert err is not None and "invalid JSON after cleanup" in err


def test_strip_code_fences_handles_plain_fence_and_prose() -> None:
    assert strip_code_fences("```\n{\"a\": 1}\n```") == '{"a": 1}'
    assert strip_code_fences("preamble {\"a\": 1} postamble") == '{"a": 1}'
    nested = strip_code_fences('prefix {"a": {"b": 2}} suffix')
    assert nested == '{"a": {"b": 2}}'
