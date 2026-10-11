"""OpenAI-compatible LLM client adapter (default model: ``deepseek-flash``).

Zero-dependency (stdlib ``urllib``) so offline unit tests never touch the
network.  Implements the ``Callable[[str], str]`` protocol expected by
:class:`PlannerAgent` / :class:`MotifExtractor` and collects per-call
telemetry (prompt/completion tokens, latency) for ablation baselines.

Configuration (environment variables):

- ``DEEPSEEK_API_KEY`` (falls back to ``OPENAI_API_KEY``)
- ``DEEPSEEK_BASE_URL`` (default ``https://api.deepseek.com``)
- ``DEEPSEEK_MODEL`` (default ``deepseek-flash``)

Robustness:

- network timeout (default 60s);
- exponential-backoff retry on HTTP 429 / 5xx and network errors
  (default 3 retries, base 2.0).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from aml_rag.config import AMLConfig, load_default_config

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_BASE_URL",
    "DEFAULT_TEMPERATURE",
    "CallRecord",
    "LLMMetrics",
    "LLMClient",
]

DEFAULT_MODEL: str = "deepseek-flash"
DEFAULT_BASE_URL: str = "https://api.deepseek.com"
DEFAULT_TEMPERATURE: float = 0.1


@dataclass
class CallRecord:
    """Telemetry for a single chat-completion call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    status: str = "ok"  # 'ok' | 'error'
    error: str | None = None


@dataclass
class LLMMetrics:
    """Aggregate telemetry over all calls made by one client."""

    calls: list[CallRecord] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls)

    @property
    def total_latency_ms(self) -> float:
        return sum(c.latency_ms for c in self.calls)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total_calls if self.total_calls else 0.0

    @property
    def failed_calls(self) -> int:
        return sum(1 for c in self.calls if c.status == "error")

    def snapshot(self) -> dict[str, Any]:
        """JSON-serialisable aggregate, attachable to a Trajectory."""
        return {
            "total_calls": self.total_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "failed_calls": self.failed_calls,
        }


class LLMClient:
    """Thin OpenAI-compatible chat client with retry + telemetry."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_base: float | None = None,
        extra_body: dict[str, Any] | None = None,
        config: AMLConfig | None = None,
    ) -> None:
        """Args:
        api_key: API key (falls back to env vars, see module docstring).
        base_url: API base URL (explicit > env > config > legacy default).
        model: model name (explicit > env > config > legacy default).
        temperature / timeout / max_retries / backoff_base: explicit values
            take precedence; otherwise resolved from the agent-domain
            config, whose defaults equal the legacy module constants
            (Zero-Delta when ``config=None``).
        config: optional :class:`aml_rag.config.AMLConfig`.
        """
        ac = load_default_config(config).agent
        self.api_key = (
            api_key
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.base_url = (
            base_url or os.getenv("DEEPSEEK_BASE_URL") or ac.base_url
        ).rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL") or ac.default_model
        self.temperature = ac.temperature if temperature is None else temperature
        self.timeout = ac.timeout if timeout is None else timeout
        self.max_retries = ac.llm_max_retries if max_retries is None else max_retries
        self.backoff_base = ac.backoff_base if backoff_base is None else backoff_base
        self.extra_body = dict(extra_body or {})
        self._metrics = LLMMetrics()

    # ------------------------------------------------------- Callable proto
    def __call__(self, prompt: str) -> str:
        return self.chat(prompt)

    # ----------------------------------------------------------------- chat
    def chat(self, prompt: str) -> str:
        """Send one chat completion, returning the assistant text content."""
        if not self.api_key:
            raise RuntimeError(
                "No API key configured: set DEEPSEEK_API_KEY (or OPENAI_API_KEY) "
                "or pass api_key=... to LLMClient."
            )
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "stream": False,
            **self.extra_body,
        }
        request_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_error: str | None = None
        for attempt in range(1 + self.max_retries):
            start = time.perf_counter()
            try:
                req = urllib.request.Request(
                    url, data=request_body, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                latency_ms = (time.perf_counter() - start) * 1000.0
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                self._metrics.calls.append(
                    CallRecord(
                        prompt_tokens=int(usage.get("prompt_tokens", 0)),
                        completion_tokens=int(usage.get("completion_tokens", 0)),
                        latency_ms=round(latency_ms, 2),
                    )
                )
                return content

            except urllib.error.HTTPError as exc:
                latency_ms = (time.perf_counter() - start) * 1000.0
                snippet = ""
                try:
                    snippet = exc.read().decode("utf-8", "replace")[:200]
                except Exception:  # noqa: BLE001 - best-effort error body
                    pass
                last_error = f"HTTP {exc.code}: {snippet}".strip()
                retryable = exc.code == 429 or exc.code >= 500
                if retryable and attempt < self.max_retries:
                    time.sleep(self.backoff_base ** attempt)
                    continue
                self._metrics.calls.append(
                    CallRecord(
                        latency_ms=round(latency_ms, 2),
                        status="error",
                        error=last_error,
                    )
                )
                raise RuntimeError(
                    f"LLM request failed ({last_error})"
                ) from exc

            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                latency_ms = (time.perf_counter() - start) * 1000.0
                last_error = f"network error: {exc}"
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base ** attempt)
                    continue
                self._metrics.calls.append(
                    CallRecord(
                        latency_ms=round(latency_ms, 2),
                        status="error",
                        error=last_error,
                    )
                )
                raise RuntimeError(
                    f"LLM request failed ({last_error})"
                ) from exc

        raise RuntimeError(f"LLM request failed: {last_error}")

    # ------------------------------------------------------------ telemetry
    @property
    def metrics(self) -> LLMMetrics:
        return self._metrics

    @property
    def last_call(self) -> CallRecord | None:
        return self._metrics.calls[-1] if self._metrics.calls else None
