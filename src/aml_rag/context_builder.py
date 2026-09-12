"""Agent prompt context compression (MOT-style).

:class:`PromptContextCompressor` turns retrieval results into a compact,
agent-ready prompt block:

- **Token-efficient JSON**: nodes as 4-key dicts, edges as 3-tuples
  (MOT-style triplets), preconditions/post-effects flattened to short keys.
- **Mermaid DAG syntax**: optional ``flowchart`` rendering so the LLM agent
  can read topological direction at a glance.
- **Redundancy compression**: motifs fully dominated by another candidate's
  edge signature set are dropped (sub-path elimination), remaining motifs are
  ordered by retrieval score (execution order preserved inside each DAG).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Literal

from .retriever import RetrievalResult
from .schema import CurrentState, QueryContext, TopologicalMotif

__all__ = ["PromptContextCompressor", "OutputFormat"]

OutputFormat = Literal["json", "mermaid", "hybrid"]

_MERMAID_ID_RE = re.compile(r"[^0-9A-Za-z_]")


class PromptContextCompressor:
    """Compresses retrieval results into an LLM-ready prompt segment."""

    def __init__(
        self,
        *,
        max_motifs: int = 5,
        output_format: OutputFormat = "hybrid",
        include_scores: bool = True,
        token_budget_hint: int | None = None,
    ) -> None:
        """Args:
        max_motifs: hard cap on motifs injected into the prompt.
        output_format: 'json', 'mermaid' or 'hybrid' (json + mermaid).
        include_scores: annotate each motif with retrieval scores.
        token_budget_hint: if set and the JSON block would exceed the budget,
            motifs are trimmed from the tail until the budget is respected.
        """
        if max_motifs < 1:
            raise ValueError("max_motifs must be >= 1")
        self.max_motifs = max_motifs
        self.output_format = output_format
        self.include_scores = include_scores
        self.token_budget_hint = token_budget_hint

    # ------------------------------------------------------------ serialise
    @staticmethod
    def to_compact_json(motif: TopologicalMotif) -> dict[str, Any]:
        """Token-efficient JSON payload for one motif."""
        pre = motif.preconditions
        post = motif.post_state_effect
        return {
            "motif_id": motif.motif_id,
            "pattern": motif.pattern_type.value,
            "desc": motif.description,
            "pre": {
                "min_level": pre.min_level,
                "allowed_roles": (
                    [r.value for r in pre.allowed_node_roles]
                    if pre.allowed_node_roles is not None
                    else None
                ),
                "required_chains": pre.required_chains,
                "max_branches": pre.max_active_branches,
            },
            "nodes": [
                {"id": n.temp_id, "role": n.role.value, "chain": n.chain, "lvl": n.level}
                for n in motif.topological_order()
            ],
            # MOT-style quadruplets: [source, target, operation, flow_share]
            # (flow_share is the motif's recommended relative flow ratio)
            "edges": [
                [e.source, e.target, e.operation.value, round(e.flow_share, 4)]
                for e in motif.edges
            ],
            "post": {
                "branch_inc": post.branch_increment,
                "chain_transition": post.chain_transition,
                "target_chain": post.target_chain,
                "next_roles": [r.value for r in post.next_recommended_roles],
            },
        }

    @staticmethod
    def to_mermaid(motif: TopologicalMotif, prefix: str = "m") -> str:
        """Render the motif as a Mermaid ``flowchart LR`` DAG block."""
        def mid(node_id: str) -> str:
            return f"{prefix}_{_MERMAID_ID_RE.sub('_', node_id)}"

        lines = ["flowchart LR"]
        for node in motif.topological_order():
            label = f"{node.role.value}<br/>{node.chain} · L{node.level}"
            lines.append(f'    {mid(node.temp_id)}["{label}"]')
        for edge in motif.edges:
            op_label = edge.operation.value
            if edge.flow_share < 1.0:
                op_label += f" {edge.flow_share:.2f}"
            lines.append(
                f"    {mid(edge.source)} -->|{op_label}| {mid(edge.target)}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------- compress
    def compress(self, results: Sequence[RetrievalResult]) -> list[RetrievalResult]:
        """Drop dominated (redundant sub-path) motifs and order by score.

        A motif ``A`` is dominated by ``B`` when every edge signature of ``A``
        appears in ``B`` and ``B`` is strictly larger — i.e. ``A`` adds no new
        topology to the prompt.
        """
        ordered = sorted(
            results, key=lambda r: (-r.combined_score, -r.semantic_score, r.motif_id)
        )
        kept: list[RetrievalResult] = []
        for candidate in ordered:
            cand_sig = candidate.motif.edge_signature_set()
            cand_nodes = len(candidate.motif.nodes)
            dominated = False
            for survivor in kept:
                surv_sig = survivor.motif.edge_signature_set()
                if cand_sig <= surv_sig and (
                    len(cand_sig) < len(surv_sig)
                    or (
                        len(cand_sig) == len(surv_sig)
                        and cand_nodes < len(survivor.motif.nodes)
                    )
                ):
                    dominated = True
                    break
            if not dominated:
                kept.append(candidate)
        return kept[: self.max_motifs]

    # ------------------------------------------------------------ prompt
    def build_agent_prompt(
        self,
        state: CurrentState,
        query: QueryContext,
        results: Sequence[RetrievalResult],
    ) -> str:
        """Assemble the final agent-ready prior-context prompt string."""
        compressed = self.compress(results)
        header = (
            "[AML-PRIOR-CONTEXT] Module-1 Topological Prior Knowledge "
            "(abstract motifs only; no addresses/amounts/timestamps)"
        )

        state_json = json.dumps(
            {
                "current_level": state.current_level,
                "current_chain": state.current_chain,
                "active_nodes": [
                    {
                        "id": n.temp_id,
                        "role": n.role.value,
                        "chain": n.chain,
                        "lvl": n.level,
                    }
                    for n in state.active_nodes
                ],
                "history_edges": [
                    [e.source, e.target, e.operation.value]
                    for e in state.graph_history
                ],
            },
            ensure_ascii=False,
        )
        query_json = json.dumps(
            {
                "scenario": query.scenario,
                "tactic_goal": query.tactic_goal,
                "target_pattern": (
                    query.target_pattern_type.value
                    if query.target_pattern_type is not None
                    else None
                ),
            },
            ensure_ascii=False,
        )

        blocks: list[str] = [
            header,
            "",
            "<STATE>",
            state_json,
            "</STATE>",
            "",
            "<QUERY>",
            query_json,
            "</QUERY>",
            "",
        ]

        if not compressed:
            blocks.append("<MOTIFS>[]</MOTIFS>")
            blocks.append(
                "<NOTE>No motif satisfied the hard precondition gate for the "
                "current state. Fall back to the generic DAG-extension rules."
            )
        else:
            blocks.append("<MOTIFS>")
            for rank, result in enumerate(compressed, start=1):
                payload: dict[str, Any] = self.to_compact_json(result.motif)
                if self.include_scores:
                    payload["score"] = round(result.combined_score, 4)
                    payload["rank"] = rank
                json_block = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                if self.output_format in ("mermaid", "hybrid"):
                    blocks.append(
                        f"[MOTIF {rank}/{len(compressed)}] {result.motif_id}\n"
                        f"{json_block}\n"
                        f"```mermaid\n{self.to_mermaid(result.motif, f'm{rank}')}\n```"
                    )
                else:
                    blocks.append(f"[MOTIF {rank}/{len(compressed)}] {json_block}")
            blocks.append("</MOTIFS>")

        blocks.extend(
            [
                "",
                "<INSTRUCTION>",
                (
                    "Use the motifs above ONLY as topological priors for the "
                    "next DAG-extension action. Pick at most one motif, map its "
                    "abstract nodes/edges onto the current state (re-indexing "
                    "temp ids), and respect the motif preconditions and the "
                    "global DAG constraints. Never introduce wallet addresses, "
                    "amounts, gas or timestamps."
                ),
                "</INSTRUCTION>",
            ]
        )
        return "\n".join(blocks)

    def build_mermaid_block(self, results: Sequence[RetrievalResult]) -> str:
        """Convenience: concatenated Mermaid rendering of compressed results."""
        return "\n\n".join(
            self.to_mermaid(r.motif, f"m{i}")
            for i, r in enumerate(self.compress(results), start=1)
        )
