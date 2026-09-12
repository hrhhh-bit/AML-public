"""Format-agnostic distillation pipeline: raw reports -> validated motifs.

Object-oriented, vendor-agnostic design:

- :class:`TextChunker` — splits arbitrary report text (Markdown / TXT /
  incident write-ups) into digestible segments, with sliding-window overflow
  for long sections. No per-report hard-coded regexes.
- :class:`DistillationPromptBuilder` — renders the structured distillation
  prompt (zero micro-noise, flow-archetype normalisation, scale-tier
  association) plus the Pydantic schema.
- :class:`MotifDistiller` — drives the LLM, defensively deserialises replies
  and performs bounded reflection-repair on parse/schema/topology errors.

The LLM is injected as ``Callable[[str], str]`` (e.g. ``aml_agent.LLMClient``),
so the module never imports the agent layer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .json_utils import extract_json_list
from .schema import TopologicalMotif

__all__ = [
    "TextChunker",
    "DistillationPromptBuilder",
    "DistillationFailure",
    "DistillationResult",
    "MotifDistiller",
    "DISTILLATION_SYSTEM_PROMPT_V2",
]

LLMCallable = Callable[[str], str]

DISTILLATION_SYSTEM_PROMPT_V2: str = """\
You are a crypto AML topological knowledge distiller.

Your input is a segment of a security tracing report describing money
laundering behaviour. Convert it into abstract topological motifs ONLY.

DISTILLATION RULES (hard constraints):
1. ZERO micro-numerical noise: NEVER output wallet addresses (0x...), exact
   amounts, gas fees, timestamps, tx hashes or token symbols. Strip them all.
2. PURE topological abstraction: abstract roles, chains, DAG levels and
   operations only.
3. Node roles MUST be: Source, Intermediate, Asset_Conversion, Cross_Chain,
   Aggregator, Target.
4. Edge operations MUST be: Transfer, Swap, Bridge, Split, Merge.
5. Chain labels MUST be abstract: Chain_A, Chain_B, Chain_C, ...
6. Node `level` MUST strictly increase along every edge (DAG topological
   order, sources at level 0).
7. `pattern_type` MUST be one of: Peeling_Chain, Chain_Hopping,
   Multi_Layering_Split, Token_Obfuscation, Integration_Merge.
8. FLOW ARCHETYPE normalisation: for every Split node, assign each out-edge a
   `flow_share` in (0, 1] summing to exactly 1.0 (tolerance 0.01). Model
   dominant-vs-peel splits asymmetrically (e.g. [0.9, 0.1]); equal slices
   symmetrically (e.g. [0.5, 0.5]). Merge in-edges must likewise sum to 1.0.
9. SCALE TIER association: infer the macro fund-volume tier the pattern is
   suited for and fill `applicable_scale_tiers` with a subset of
   ["Retail", "Medium", "Whale", "State_Sponsored"] (empty list if unclear).
10. Every motif MUST carry meaningful `preconditions` (min_level,
    allowed_node_roles, required_chains, max_active_branches) and a
    `post_state_effect` (branch_increment, chain_transition, target_chain,
    next_recommended_roles).
11. If the segment contains several distinct patterns, output ALL of them in
    one JSON array. If none, output an empty array [].

## Behavioural normalisation (semantic anchoring)
IGNORE marketing prose, tooling ads, white-hat refund narratives and
post-mortem digressions. Extract ONLY the core fund-flow topology actually
described, and normalise it to the standard operators:

- "assets moved across blockchains via a bridge"          -> Bridge edge
  (pattern_type: Chain_Hopping).
- "funds fanned out / thousands of addresses drained it"  -> Split edges
  (pattern_type: Multi_Layering_Split).
- "funds returned / consolidated into one recovery addr"  -> Merge edges,
  many-to-one (pattern_type: Integration_Merge).
- "several tokens swapped into one token via a DEX"       -> Swap edge
  (pattern_type: Token_Obfuscation). Cashing out via a DEX (Uniswap /
  Curve, "converted to ETH / WETH / USDC", "dumped the tokens") is
  ALWAYS a Swap edge — never omit it.
- "linear chain of small rapid hops, peeling a fraction"  -> Transfer edges
  (pattern_type: Peeling_Chain). "Sent to a specific address / mixer /
  cold wallet / recovery address" is ALWAYS a Transfer edge — never omit it.

Even if the text mixes several narratives (attack, refund, swapping), extract
every distinct operator present so that the union of operators faithfully
reflects the true fund-flow behaviour. Prefer the canonical pattern_type for
the dominant behaviour; do NOT invent a new label for diluted prose.

## Composite event awareness (multi-hop completeness)
- Real incidents are COMPOSITE flows: entry / cross-chain escape -> fan-out /
  mixing -> consolidation. When a segment describes BOTH the cross-chain
  escape (Bridge) AND the subsequent dispersal to many addresses / copycat
  replication (Split/Transfer), abstract the FULL chain into a composite motif
  (e.g. Bridge -> Split -> Transfer) — never a single isolated step.
- For a bridge hack, keep the Bridge edge AND the Split/Transfer edges; never
  drop the cross-chain origin just because the prose emphasises the dispersal,
  and never drop the dispersal just because it emphasises the bridge.
- Encourage the canonical three-stage laundering chain — [Bridge -> Swap ->
  Transfer] or [Bridge -> Split -> Swap] — so the operator union covers the
  full entry / cash-out path rather than a single stage.
- Output 1-3 core behaviour motifs when a segment clearly contains multiple
  laundering stages, so no stage is silently lost.

OUTPUT FORMAT:
Respond with ONLY a valid JSON array whose elements conform exactly to the
provided JSON schema. No markdown fences, no prose, no commentary.
"""

_HEADING_RE = re.compile(r"^#{2,6}\s+.+$", re.MULTILINE)


class TextChunker:
    """Format-agnostic long-text segmentation.

    Splits on Markdown headings first (each section usually describes one
    laundering pattern); sections longer than ``max_chars`` are further split
    into paragraph groups with sliding-window ``overlap_chars``.
    """

    def __init__(self, max_chars: int = 6000, overlap_chars: int = 200) -> None:
        if max_chars < 200:
            raise ValueError("max_chars must be >= 200")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, text: str) -> list[str]:
        """Split ``text`` into self-contained segments."""
        sections = self._split_by_headings(text)
        chunks: list[str] = []
        for section in sections:
            if len(section) <= self.max_chars:
                if section.strip():
                    chunks.append(section.strip())
                continue
            chunks.extend(self._split_long(section))
        return [c for c in chunks if c.strip()]

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _split_by_headings(text: str) -> list[str]:
        matches = list(_HEADING_RE.finditer(text))
        if not matches:
            return [text]
        sections: list[str] = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append(text[start:end])
        # prefix before the first heading (e.g. a title/intro paragraph)
        if matches[0].start() > 0 and text[: matches[0].start()].strip():
            sections.insert(0, text[: matches[0].start()])
        return sections

    def _split_long(self, section: str) -> list[str]:
        """Greedy paragraph packing with sliding-window overlap."""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
        # hard-split any single paragraph that exceeds the budget by itself
        pieces: list[str] = []
        for para in paragraphs:
            if len(para) > self.max_chars:
                pieces.extend(self._hard_split(para))
            else:
                pieces.append(para)

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for para in pieces:
            if current_len + len(para) > self.max_chars and current:
                chunks.append("\n\n".join(current))
                # sliding window: keep the last paragraph for context
                tail = current[-1]
                current = [tail] if self.overlap_chars > 0 else []
                current_len = len(tail) if current else 0
            current.append(para)
            current_len += len(para)
        if current:
            chunks.append("\n\n".join(current))
        return chunks

    def _hard_split(self, para: str) -> list[str]:
        """Split one oversized paragraph into fixed-window slices."""
        step = max(self.max_chars - self.overlap_chars, 100)
        return [para[i : i + self.max_chars] for i in range(0, len(para), step)]


class DistillationFailure(BaseModel):
    """A chunk that could not be distilled within the repair budget."""

    model_config = ConfigDict(extra="forbid")

    chunk_index: int
    error: str
    attempts: int


class DistillationResult(BaseModel):
    """Full distillation outcome (flat + per-chunk for saturation analysis)."""

    model_config = ConfigDict(extra="forbid")

    motifs: list[TopologicalMotif] = Field(default_factory=list)
    chunk_motifs: list[list[TopologicalMotif]] = Field(default_factory=list)
    failures: list[DistillationFailure] = Field(default_factory=list)
    chunks: int = 0


class DistillationPromptBuilder:
    """Renders the structured distillation prompt for one segment."""

    def __init__(self, system_prompt: str = DISTILLATION_SYSTEM_PROMPT_V2) -> None:
        self.system_prompt = system_prompt

    def build(self, chunk_text: str, *, retry_error: str | None = None) -> str:
        schema_json = json.dumps(
            TopologicalMotif.model_json_schema(), ensure_ascii=False, separators=(",", ":")
        )
        blocks = [
            self.system_prompt,
            "",
            "### TARGET JSON SCHEMA ###",
            schema_json,
            "",
            "### REPORT SEGMENT ###",
            chunk_text.strip(),
        ]
        if retry_error:
            blocks.extend(
                [
                    "",
                    "### PREVIOUS MISTAKE ###",
                    f"Your previous output was rejected for: {retry_error}",
                    "Fix the issue and output a corrected JSON array.",
                ]
            )
        return "\n".join(blocks)


class MotifDistiller:
    """Drives distillation with defensive deserialisation + reflection repair."""

    def __init__(
        self,
        llm: LLMCallable,
        *,
        chunker: TextChunker | None = None,
        prompt_builder: DistillationPromptBuilder | None = None,
        max_repair_retries: int = 2,
    ) -> None:
        self._llm = llm
        self._chunker = chunker or TextChunker()
        self._prompt_builder = prompt_builder or DistillationPromptBuilder()
        self._max_repair_retries = max_repair_retries

    # ----------------------------------------------------------------- distill
    def distill(self, text: str) -> DistillationResult:
        chunks = self._chunker.chunk(text)
        result = DistillationResult(chunks=len(chunks))
        for index, chunk in enumerate(chunks):
            motifs, failure = self._distill_chunk(index, chunk)
            result.chunk_motifs.append(motifs)
            result.motifs.extend(motifs)
            if failure is not None:
                result.failures.append(failure)
        return result

    # -- single chunk with reflection repair --------------------------------
    def _distill_chunk(
        self, index: int, chunk_text: str
    ) -> tuple[list[TopologicalMotif], DistillationFailure | None]:
        retry_error: str | None = None
        for attempt in range(1 + self._max_repair_retries):
            prompt = self._prompt_builder.build(chunk_text, retry_error=retry_error)
            reply = self._llm(prompt)

            payload, parse_error = extract_json_list(reply)
            if parse_error is not None:
                retry_error = parse_error
                continue

            motifs, validate_error = self._validate_items(payload)
            if validate_error is not None:
                retry_error = validate_error
                continue

            return motifs, None

        # repair budget exhausted
        failure = DistillationFailure(
            chunk_index=index,
            error=retry_error or "unknown error",
            attempts=1 + self._max_repair_retries,
        )
        return [], failure

    @staticmethod
    def _validate_items(items: list[Any]) -> tuple[list[TopologicalMotif], str | None]:
        motifs: list[TopologicalMotif] = []
        for i, item in enumerate(items):
            try:
                motifs.append(TopologicalMotif.model_validate(item))
            except Exception as exc:  # noqa: BLE001 - per-item schema/topology errors
                return [], f"motif item #{i} invalid: {exc}"
        return motifs, None
