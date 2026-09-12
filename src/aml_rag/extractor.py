"""LLM-based distillation pipeline: raw case text -> :class:`TopologicalMotif`.

The extractor implements the RDLI-inspired knowledge extraction stage:

1. :meth:`MotifExtractor.build_prompt` renders a strict distillation prompt
   (zero micro-numerical noise) plus the Pydantic JSON schema;
2. the configured LLM callable answers in JSON;
3. :meth:`MotifExtractor.parse_response` robustly parses and Pydantic-validates
   the reply into :class:`TopologicalMotif` records.

The LLM backend is injected as a plain ``Callable[[str], str]`` so the module
works with OpenAI, Azure OpenAI, local models or a deterministic mock —
without coupling to any vendor SDK.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from .schema import TopologicalMotif

__all__ = [
    "DistillationError",
    "DistillationParseError",
    "DISTILLATION_SYSTEM_PROMPT",
    "MotifExtractor",
]

LLMCallable = Callable[[str], str]

# ---------------------------------------------------------------------------
# Prompt engineering (distillation system prompt)
# ---------------------------------------------------------------------------
DISTILLATION_SYSTEM_PROMPT: str = """\
You are a crypto AML topological knowledge distiller.

Your input is a raw security investigation report (e.g. Chainalysis, Elliptic,
FBI) describing money-laundering behaviour.

DISTILLATION RULES (hard constraints):
1. ZERO micro-numerical noise: NEVER output wallet addresses, exact amounts,
   gas fees, timestamps or tx hashes. Strip them completely.
2. PURE topological abstraction: express the case only as abstract node roles
   and edge operations.
3. Node roles MUST come from: Source, Intermediate, Asset_Conversion,
   Cross_Chain, Aggregator, Target.
4. Edge operations MUST come from: Transfer, Swap, Bridge, Split, Merge.
5. Chain labels MUST be abstract: Chain_A, Chain_B, Chain_C, ...
6. Node `level` fields MUST strictly increase along every edge
   (a valid DAG topological order, starting at 0 for sources).
7. `pattern_type` MUST be one of: Peeling_Chain, Chain_Hopping,
   Multi_Layering_Split, Token_Obfuscation, Integration_Merge.
8. Every motif MUST carry meaningful `preconditions` (min_level,
   allowed_node_roles, required_chains, max_active_branches) and a
   `post_state_effect` (branch_increment, chain_transition, target_chain,
   next_recommended_roles).
9. If a report contains several distinct patterns, output ALL of them as a
   JSON array. If only one, still output a JSON array with one element.

OUTPUT FORMAT:
Respond with ONLY a valid JSON array whose elements conform exactly to the
provided JSON schema. No markdown fences, no prose, no commentary.
"""

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class DistillationError(RuntimeError):
    """Base error raised by the distillation pipeline."""


class DistillationParseError(DistillationError):
    """Raised when the LLM reply cannot be parsed/validated into motifs."""


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences and pick the largest JSON-looking chunk."""
    text = raw.strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    # Fallback: keep everything between the first '[' / '{' and last ']' / '}'
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    ends = [text.rfind("]"), text.rfind("}")]
    if starts and ends and max(ends) > min(starts):
        return text[min(starts) : max(ends) + 1]
    return text


class MotifExtractor:
    """Orchestrates prompt build, LLM call and strict response parsing."""

    def __init__(
        self,
        llm: LLMCallable | None = None,
        *,
        system_prompt: str = DISTILLATION_SYSTEM_PROMPT,
        strict: bool = True,
    ) -> None:
        """Args:
        llm: callable mapping a prompt string to the model reply. If omitted,
             only :meth:`build_prompt` / :meth:`parse_response` are usable.
        system_prompt: override of the distillation system prompt.
        strict: when True, any invalid item in a batch aborts the whole batch;
                when False, invalid items are skipped (with the failures
                recorded in :attr:`last_failures`).
        """
        self._llm = llm
        self._system_prompt = system_prompt
        self._strict = strict
        self.last_failures: list[str] = []

    # ------------------------------------------------------------ prompting
    def build_prompt(self, raw_report: str) -> str:
        """Render the full distillation prompt for a raw case report."""
        schema_json = json.dumps(
            TopologicalMotif.model_json_schema(), indent=2, ensure_ascii=False
        )
        return (
            f"{self._system_prompt}\n\n"
            f"### TARGET JSON SCHEMA ###\n{schema_json}\n\n"
            f"### RAW CASE REPORT ###\n{raw_report.strip()}\n"
        )

    # -------------------------------------------------------------- parsing
    def parse_response(self, raw_response: str) -> list[TopologicalMotif]:
        """Parse an LLM reply into validated motifs.

        Tolerates markdown fences and surrounding prose; enforces Pydantic
        validation on every element. Raises :class:`DistillationParseError`
        on unrecoverable input.
        """
        cleaned = _strip_fences(raw_response)
        try:
            payload: Any = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise DistillationParseError(
                f"LLM reply is not valid JSON: {exc.msg} at line {exc.lineno}."
            ) from exc

        items: list[Any]
        if isinstance(payload, dict):
            items = [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            raise DistillationParseError(
                f"Expected a JSON object/array of motifs, got {type(payload).__name__}."
            )

        motifs: list[TopologicalMotif] = []
        self.last_failures = []
        for idx, item in enumerate(items):
            try:
                motifs.append(TopologicalMotif.model_validate(item))
            except Exception as exc:  # noqa: BLE001 - collect per-item failures
                if self._strict:
                    raise DistillationParseError(
                        f"Motif item #{idx} failed validation: {exc}"
                    ) from exc
                self.last_failures.append(f"item #{idx}: {exc}")
        if not motifs and not items:
            raise DistillationParseError("LLM reply contained no motif items.")
        return motifs

    # ------------------------------------------------------------ end-to-end
    def extract(self, raw_report: str) -> list[TopologicalMotif]:
        """Full pipeline: build prompt -> call LLM -> parse & validate."""
        if self._llm is None:
            raise DistillationError(
                "No LLM callable configured. Inject one via "
                "MotifExtractor(llm=...) before calling extract()."
            )
        prompt = self.build_prompt(raw_report)
        reply = self._llm(prompt)
        return self.parse_response(reply)

    def extract_many(self, reports: Iterable[str]) -> list[TopologicalMotif]:
        """Distill a batch of reports into a flat motif list (deduplicated)."""
        seen: set[str] = set()
        collected: list[TopologicalMotif] = []
        for report in reports:
            for motif in self.extract(report):
                if motif.motif_id not in seen:
                    seen.add(motif.motif_id)
                    collected.append(motif)
        return collected

    @property
    def llm(self) -> LLMCallable | None:
        return self._llm

    @llm.setter
    def llm(self, fn: LLMCallable | None) -> None:
        self._llm = fn


# Convenience aliases for downstream imports
DistillationPrompt = DISTILLATION_SYSTEM_PROMPT
__all__ += ["DistillationPrompt"]
