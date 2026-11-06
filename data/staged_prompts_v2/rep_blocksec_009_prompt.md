# Prompt v2 — rep_blocksec_009

- vendor: BlockSec
- title: Sep 17 2026Security Insights~$320M Lost: Liquid Network, Symbiosis Exploits | BlockSecThis report, covering 2026/09/07 - 2026/09/13, examines two security incidents that caused approximately $320M in losses, including the Liquid Network exploit of 2026/09/06 that the previous report did not cover. The larger was that Liquid Network exploit, where the rangeproof validation cache in Elements derived its key by hashing four fields — two of them variable in length — concatenated with nothing marking the boundaries between them, so a verdict recorded for one output was returned for another whose proof was never examined, letting the attacker create 4,000 unbacked L-BTC and peg out nearly all of them as bitcoin. On the Bitcoin route of the Symbiosis cross-chain bridge, spanning BNB Smart Chain, Ethereum and Rootstock, off-chain code that reads Bitcoin deposits took the depositor&#x27;s identity from a field the depositor controls and then subtracted its fee from the deposit without checking whether the fee itself was negative, letting a 330-satoshi deposit mint `46,116,860,184.27388234 syBTC`; the pools it had to be sold through held only 11.26 syBTC, so the loss to liquidity providers and users came to an estimated 9.97 BTC (~$770K).
- filename: rep_blocksec_009_2026-09-24.txt
- hops_detected: 2

---

You are a crypto AML topological knowledge distiller.

Your input is a segment of a security tracing report describing money
laundering behaviour. Convert it into abstract topological motifs ONLY,
organised into TWO phases and grounded to the chains actually evidenced.

## HARD CONSTRAINTS (axioms)
1. ZERO micro-numerical noise: NEVER output wallet addresses (0x... / bc1...
   / T...), exact amounts, gas fees, timestamps, tx hashes or token symbols.
2. PURE topological abstraction: abstract roles, chains, DAG levels and
   operations only. Chain labels MUST be abstract: Chain_A, Chain_B, ...
3. Node roles MUST be: Source, Intermediate, Asset_Conversion, Cross_Chain,
   Aggregator, Target.
4. Edge operations MUST be: Transfer, Swap, Bridge, Split, Merge.
5. Node `level` MUST strictly increase along every edge (DAG topological
   order, sources at level 0).
6. `pattern_type` MUST be one of: Peeling_Chain, Chain_Hopping,
   Multi_Layering_Split, Token_Obfuscation, Integration_Merge.
7. FLOW ARCHETYPE normalisation: `flow_share` is ALWAYS the local OUT-degree
   distribution ratio of its SOURCE node; for EVERY node the out-edge shares
   must sum to exactly 1.0 (tolerance 0.01). Single out-edges MUST carry
   1.0; Split out-edges must sum to 1.0. NEVER write a downstream merge
   target's IN-FLOW weight onto an upstream edge.
8. CROSS-CHAIN ledger law: any edge whose source and target live on
   DIFFERENT chains MUST use the Bridge operation. Transfer / Swap / Split /
   Merge can never cross chains.
9. ASSET_CONVERSION contract: an Asset_Conversion node must carry exactly one
   adjacent Swap edge (never Transfer on BOTH sides).
10. Every motif MUST carry meaningful `preconditions` (min_level,
    allowed_node_roles, required_chains, max_active_branches) and a
    `post_state_effect` (branch_increment, chain_transition, target_chain,
    next_recommended_roles).

## ENTITY GROUNDING INVARIANT (grounded_chains)
- Output a top-level `grounded_chains` list naming ONLY the abstract chain
  labels actually evidenced in the report.
- Every `chain` value used by ANY node in BOTH phases MUST appear in
  `grounded_chains`. The number of distinct chain labels used by the motifs
  must NEVER exceed the number of chains declared in `grounded_chains`.
- NEVER invent an intermediate relay chain or ghost node just to make the
  graph look bigger. A direct consolidation (funds merge straight into an
  aggregator) is correct; a fake "CC_A -> CC_B" relay is hallucination.

## TWO-PHASE CONTRACT
- `phase_a_inflow_motifs`: Fan-in / consolidation / first-hop / cross-chain
  ENTRY motifs (funds flowing INTO the laundering structure).
- `phase_b_outflow_motifs`: Fan-out / dispersal / DEX swap / OTC cash-out /
  EXIT motifs (funds leaving the structure toward sinks).
- Put every extracted motif in exactly one phase; leave an empty array []
  when a phase has no motifs.

## MACRO CAMPAIGN TOPOLOGY MANDATE
- MINIMUM EDGE COUNT: each motif MUST have at least 3 edges
  (len(edges) >= 3). Isolated 1-edge transfers or 2-edge simple hops are
  STRICTLY FORBIDDEN.
- CAUSAL FIDELITY: extract each actually-evidenced laundering stage as one
  motif that closes its causal loop (entry -> transformation -> exit).
  Never inflate hop counts, never insert ghost relay nodes or chains, and
  never split one logical flow into per-address fragments.
- CRITICAL: Do NOT mention concrete token symbols (e.g., USDT, ETH, BTC)
  even in descriptions or tags. Always use generic terms like
  'native_asset', 'stablecoin', or 'token'.

## BEHAVIOURAL NORMALISATION
IGNORE marketing prose, tooling ads, white-hat refund narratives and
post-mortem digressions. Extract ONLY the core fund-flow topology actually
described and normalise it to the standard operators:

- "assets moved across blockchains via a bridge"           -> Bridge edge
  (pattern_type: Chain_Hopping, phase_a inflow entry).
- "funds fanned out / many addresses drained it"           -> Split edges
  (pattern_type: Multi_Layering_Split, phase_b outflow).
- "funds consolidated into one recovery / aggregator addr" -> Merge edges
  (pattern_type: Integration_Merge, phase_a inflow).
- "several tokens swapped into one token via a DEX"        -> Swap edge
  (pattern_type: Token_Obfuscation, phase_b outflow).
- "linear chain of small rapid hops, peeling a fraction"   -> Transfer edges
  (pattern_type: Peeling_Chain, phase_b outflow).
- "sold via OTC / P2P desk, cashed out to fiat"            -> Transfer into
  the OTC acceptor address (pattern_type: Integration_Merge, phase_b).

## NEGATIVE EXAMPLE (rejected — hallucinated intermediate relay chain)
The report only evidences TWO chains (Chain_A -> Chain_B). The following
answer invents a ghost chain "Chain_C" and ghost relay nodes "CC_A"/"CC_B"
that the report never mentions:

[REJECTED: Hallucinated Intermediate Relay Chain/Node]
{
  "grounded_chains": ["Chain_A", "Chain_B"],
  "phase_a_inflow_motifs": [
    {
      "motif_id": "bad_ghost_relay",
      "pattern_type": "Chain_Hopping",
      "description": "bridge then bounce through an invented relay chain",
      "nodes": [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "CC_A", "role": "Cross_Chain", "chain": "Chain_C", "level": 1},
        {"temp_id": "CC_B", "role": "Cross_Chain", "chain": "Chain_C", "level": 2},
        {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 3}
      ],
      "edges": [
        {"source": "S", "target": "CC_A", "operation": "Bridge"},
        {"source": "CC_A", "target": "CC_B", "operation": "Bridge"},
        {"source": "CC_B", "target": "T", "operation": "Bridge"}
      ]
    }
  ],
  "phase_b_outflow_motifs": []
}
WHY REJECTED: "Chain_C" is used by the motif but is absent from
`grounded_chains`. Direct consolidation into the evidenced chains is fine;
inventing relay chains is not.

## NEGATIVE EXAMPLE (rejected — micro-fragment / trivial transfer)
The report describes a single deposit of stolen funds into one exchange. The
following answer emits that one hop as a standalone motif:

[REJECTED: Micro-fragment / Trivial Transfer]
{
  "grounded_chains": ["Chain_A"],
  "phase_a_inflow_motifs": [],
  "phase_b_outflow_motifs": [
    {
      "motif_id": "bad_single_transfer",
      "pattern_type": "Peeling_Chain",
      "description": "one isolated transfer hop into an exchange",
      "nodes": [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 1}
      ],
      "edges": [{"source": "S", "target": "T", "operation": "Transfer"}]
    }
  ]
}
WHY REJECTED: only 1 edge (< 3). Fold this branch into the unified fan-out
DAG (or the consolidation DAG) instead of emitting it as a standalone motif.

## THREE GOLDEN FEW-SHOT EXAMPLES (from the calibrated 18-motif gold KB)

### Few-shot 1 — single-chain multi-layer peeling split (phase_b outflow)
{
  "grounded_chains": ["Chain_A"],
  "phase_a_inflow_motifs": [],
  "phase_b_outflow_motifs": [
    {
      "motif_id": "single_chain_peeling_split",
      "pattern_type": "Peeling_Chain",
      "description": "Peeled dispersal along a single chain with a dominant trunk and a minor peeled branch before final collection.",
      "preconditions": {"min_level": 0, "allowed_node_roles": ["Source", "Intermediate"], "max_active_branches": 2},
      "nodes": [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "I1", "role": "Intermediate", "chain": "Chain_A", "level": 1},
        {"temp_id": "M", "role": "Intermediate", "chain": "Chain_A", "level": 2},
        {"temp_id": "P", "role": "Intermediate", "chain": "Chain_A", "level": 2},
        {"temp_id": "T", "role": "Target", "chain": "Chain_A", "level": 3}
      ],
      "edges": [
        {"source": "S", "target": "I1", "operation": "Transfer", "flow_share": 1.0},
        {"source": "I1", "target": "M", "operation": "Transfer", "flow_share": 0.8},
        {"source": "I1", "target": "P", "operation": "Transfer", "flow_share": 0.2},
        {"source": "M", "target": "T", "operation": "Transfer", "flow_share": 1.0},
        {"source": "P", "target": "T", "operation": "Transfer", "flow_share": 1.0}
      ],
      "post_state_effect": {"branch_increment": 0, "chain_transition": false, "next_recommended_roles": ["Target"]}
    }
  ]
}

### Few-shot 2 — standard cross-chain swap-bridge (phase_a inflow entry)
{
  "grounded_chains": ["Chain_A", "Chain_B"],
  "phase_a_inflow_motifs": [
    {
      "motif_id": "cross_chain_swap_bridge",
      "pattern_type": "Chain_Hopping",
      "description": "Swap volatile assets into a stablecoin on the origin chain, then bridge the proceeds to a target chain before final transfer to the destination wallet.",
      "preconditions": {"min_level": 1, "allowed_node_roles": ["Source", "Asset_Conversion"], "max_active_branches": 2},
      "nodes": [
        {"temp_id": "S", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "AC", "role": "Asset_Conversion", "chain": "Chain_A", "level": 1},
        {"temp_id": "I", "role": "Intermediate", "chain": "Chain_A", "level": 2},
        {"temp_id": "CC", "role": "Cross_Chain", "chain": "Chain_B", "level": 3},
        {"temp_id": "T", "role": "Target", "chain": "Chain_B", "level": 4}
      ],
      "edges": [
        {"source": "S", "target": "AC", "operation": "Swap", "flow_share": 1.0},
        {"source": "AC", "target": "I", "operation": "Transfer", "flow_share": 1.0},
        {"source": "I", "target": "CC", "operation": "Bridge", "flow_share": 1.0},
        {"source": "CC", "target": "T", "operation": "Transfer", "flow_share": 1.0}
      ],
      "post_state_effect": {"branch_increment": 0, "chain_transition": true, "target_chain": "Chain_B", "next_recommended_roles": ["Cross_Chain", "Target"]}
    }
  ],
  "phase_b_outflow_motifs": []
}

### Few-shot 3 — multi-chain consolidation + OTC cash-out (both phases)
{
  "grounded_chains": ["Chain_A", "Chain_B"],
  "phase_a_inflow_motifs": [
    {
      "motif_id": "multi_chain_consolidation",
      "pattern_type": "Integration_Merge",
      "description": "Two source streams merge into an aggregator on the origin chain, then bridge to the target chain.",
      "preconditions": {"min_level": 2, "allowed_node_roles": ["Source", "Intermediate", "Aggregator", "Cross_Chain"], "max_active_branches": 2},
      "nodes": [
        {"temp_id": "S1", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "S2", "role": "Source", "chain": "Chain_A", "level": 0},
        {"temp_id": "AGG", "role": "Aggregator", "chain": "Chain_A", "level": 1},
        {"temp_id": "CC", "role": "Cross_Chain", "chain": "Chain_B", "level": 2}
      ],
      "edges": [
        {"source": "S1", "target": "AGG", "operation": "Merge", "flow_share": 1.0},
        {"source": "S2", "target": "AGG", "operation": "Merge", "flow_share": 1.0},
        {"source": "AGG", "target": "CC", "operation": "Bridge", "flow_share": 1.0}
      ],
      "post_state_effect": {"branch_increment": -1, "chain_transition": true, "target_chain": "Chain_B", "next_recommended_roles": ["Cross_Chain"]}
    }
  ],
  "phase_b_outflow_motifs": [
    {
      "motif_id": "otc_cash_out_fanout",
      "pattern_type": "Multi_Layering_Split",
      "description": "Consolidated funds are fanned out into three target-chain OTC/P2P acceptor deposit addresses for off-chain cash-out.",
      "preconditions": {"min_level": 2, "allowed_node_roles": ["Cross_Chain", "Intermediate", "Target"], "max_active_branches": 3},
      "nodes": [
        {"temp_id": "CC", "role": "Cross_Chain", "chain": "Chain_B", "level": 0},
        {"temp_id": "T1", "role": "Target", "chain": "Chain_B", "level": 1},
        {"temp_id": "T2", "role": "Target", "chain": "Chain_B", "level": 1},
        {"temp_id": "T3", "role": "Target", "chain": "Chain_B", "level": 1}
      ],
      "edges": [
        {"source": "CC", "target": "T1", "operation": "Split", "flow_share": 0.34},
        {"source": "CC", "target": "T2", "operation": "Split", "flow_share": 0.33},
        {"source": "CC", "target": "T3", "operation": "Split", "flow_share": 0.33}
      ],
      "post_state_effect": {"branch_increment": 2, "chain_transition": false, "next_recommended_roles": ["Target"]}
    }
  ]
}

OUTPUT FORMAT:
Respond with ONLY a valid JSON object conforming to the provided schema.
No markdown fences, no prose, no commentary.


=== VERIFIED FUND-FLOW TELEMETRY (ATTENTION ANCHOR) ===
hops_detected: 2
flow_markers: cross-chain, bridge, phalcon
This anchor is a signpost ONLY — the report body remains the single source of truth. Do NOT invent chains/relays beyond the evidence.
=== END ATTENTION ANCHOR ===

### TARGET JSON SCHEMA ###
{"title":"TwoPhaseDistillationPayload","type":"object","required":["phase_a_inflow_motifs","phase_b_outflow_motifs","grounded_chains"],"additionalProperties":false,"properties":{"grounded_chains":{"type":"array","minItems":1,"items":{"type":"string","minLength":1},"description":"Abstract chain labels actually grounded in the report evidence (e.g. ['Chain_A', 'Chain_B']). Every `chain` used by ANY node in EITHER phase MUST appear here; the number of distinct chains used by the motifs must NEVER exceed the number of chains declared here."},"phase_a_inflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-in / consolidation / first-hop / cross-chain ENTRY motifs (funds flowing INTO the laundering structure)."},"phase_b_outflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-out / dispersal / DEX swap / OTC cash-out / EXIT motifs (funds leaving the structure toward sinks)."}}}

### REPORT SEGMENT ###
During the past week (2026/09/07 - 2026/09/13), we observed 2 security incidents with a total estimated loss of approximately $320M.
*The Liquid Network incident occurred on September 6 and was not covered in last week's report. It is included here for completeness.
Best Security Auditor for Web3
Validate design, code, and business logic before launch
Weekly Highlight: Liquid Network
The Liquid Network incident was selected for its subtle cache-key collision mechanism and the substantial losses it caused. By crafting a transaction whose validation data re-divided the bytes of an earlier one, the attacker had a cached validation result returned for a proof that was never checked.
On 2026/09/06, the Liquid Network, a Bitcoin sidechain, was exploited for approximately $320M [1]. A collision in the rangeproof validation cache of Elements, the node software Liquid runs, allowed a valid verdict recorded for one output to be returned for a second, entirely different output, whose proof was therefore accepted without ever being examined. The attacker used this to create 4,000 L-BTC that no bitcoin backed, then withdrew them through the network's ordinary peg-out. The following day 3,400 BTC was returned to the federation, leaving about 598.5 BTC with the attacker [2].
Background
The Liquid Network is a Bitcoin sidechain built on Elements, an open-source blockchain platform derived from the Bitcoin codebase. It exists to move bitcoin faster, more cheaply and more privately than the main chain allows. Bitcoin crosses between the two networks through a two-way peg: in a peg-in, a user locks BTC with the network's federation, a fixed group of vetted organizations that jointly custody the peg funds, and receives an equal amount of L-BTC; in a peg-out, the user destroys L-BTC and the federation releases the corresponding BTC. Liquid blocks are not mined. A rotating set of the federation's functionary nodes proposes them, and a threshold of federation signatures finalizes them.
Like Bitcoin, Liquid tracks funds as unspent transaction outputs rather than as account balances. A transaction names existing unspent outputs, unlocks them, and creates new ones, and the value it creates must equal the value it consumes. Every output carries a locking script, its scriptPubKey. An output whose script begins with OP_RETURN can never be spent; it exists to carry data, and a peg-out is expressed as exactly that kind of output.
Liquid also hides amounts by default. Rather than writing a figure into an output, it writes a Pedersen commitment to that figure. Commitments are additive, so a node can confirm that a transaction's inputs and outputs balance without learning any of the values involved. That property cuts both ways: a commitment can just as well hide a value that behaves as negative, which would let a transaction's outputs exceed its inputs and still balance. Every output whose amount is hidden therefore carries a rangeproof, a proof that the committed amount lies within [0, 2^64). Verifying a rangeproof is expensive, and the same output is verified more than once — when the transaction enters the mempool, and again when it arrives in a block — so Elements keeps a cache of the proofs it has already accepted, keyed by the proof and the data it was checked against.
Vulnerability Analysis
The defect is in how Elements, the node software every Liquid participant runs, caches already-verified rangeproofs.
CachingRangeProofChecker::VerifyRangeProof() derives a cache entry for the output in front of it and, on a hit, returns success immediately without touching the proof:
The entry comes from ComputeEntryRangeProof(), which writes four fields one after another into a single SHA-256 stream and finalizes the digest:
The four fields are the rangeproof itself, the Pedersen commitment to the amount, the asset generator that identifies which asset the output holds, and the scriptPubKey, included so that an accepted proof binds to one specific locking script.
None of the four fields carries a length prefix or a separator. The rangeproof and the scriptPubKey vary in length; the Pedersen commitment and the asset generator are always 33-byte points. The digest therefore records only the concatenated bytes, with nothing to mark where one field ended and the next began. Two different sets of four fields that happen to concatenate to the same byte stream produce the same entry, and whichever is validated first leaves behind a verdict the other one collects. The hasher is seeded with a per-node random salt, but the salt is prefixed to both streams alike, so it changes the digest without distinguishing the two inputs. The defect was remediated in commit 94000967 [3].
Attack Analysis
The following analysis is based on the transactions 271147...187ec5 and f24a4b...0a183f, both accepted by nodes running the vulnerable code.
- Step 1: The attacker published a transaction whose first output is an OP_RETURN carrying 67 bytes of data.
Its scriptPubKey reads 6a 43 — the OP_RETURN opcode followed by a push of 67 bytes — then two 33-byte values and a trailing 6a. Those 67 pushed bytes are not data this transaction needs. They are the value commitment and the asset generator of an output that did not exist yet. Validating this output stored a valid verdict under the entry for its own four fields.
- Step 2: The attacker then submitted the inflation transaction. Its OP_RETURN output has ascriptPubKey consisting of the single byte6a , and its value commitment is exactly the 33-byte value embedded in the earlier transaction's push. Its rangeproof field was built from the earlier transaction's rangeproof, commitment and asset generator, followed by the two bytes6a 43 .
The four fields of this output therefore concatenate to the same byte stream as the first transaction's, re-divided along different boundaries:
Primer: P0 │ C0 │ X │ S0, where S0 = 6a 43 <33-byte C1> <33-byte X> 6a
Inflation: P1 │ C1 │ X │ S1, where P1 = P0 ‖ C0 ‖ X ‖ 6a 43 and S1 = 6a
Both concatenate to: P0 ‖ C0 ‖ X ‖ 6a 43 ‖ C1 ‖ X ‖ 6a
The cache returned the earlier verdict, and P1 was never verified — it is not a rangeproof at all. C1 commits to a small negative amount. The transaction's other output, a normal pay-to-witness-public-key-hash output to the attacker's address ex1q7kg...qa2w, carried a large positive commitment with a genuine rangeproof, and the two offset each other, so the transaction balanced. It left 4,000 unspent L-BTC that no bitcoin backed.
- Step 3: The attacker pegged out. Two transactions burned 3,996.01834922 and2.65138358 L-BTC through ordinaryOP_RETURN peg-out outputs,3,998.66973280 L-BTC in total. The functionary nodes that authorize peg-outs validated them with the same vulnerable code and released the bitcoin:3,995.99999857 BTC and2.49749857 BTC reached the attacker on Bitcoin,3,998.49749714 BTC in all.
The network paused and split into two chains while the incident was resolved [4], and resumed with the invalid peg-out rejected [2]: a block explorer today shows the primer transaction confirmed but not the inflation transaction, even though the bitcoin it released had already left the federation's wallet. At 16:09:25 UTC the next day, the attacker returned 3,400.00000000 BTC to the federation's peg wallet, keeping the remaining ~598.5 BTC outstanding [2], as the two sides negotiated through messages embedded in Bitcoin transactions [4].
Conclusion
The attacker broke no cryptography and compromised no key. The defect was in how the rangeproof cache identified what it had already checked. Its key concatenated four fields — two of them variable in length — into one hash stream with nothing marking where each field ended, so a second set of fields could re-divide the same bytes and land on the same entry. A stored valid verdict was then returned for a proof no node had ever verified, and once a rangeproof stops constraining the amount behind it, a confidential ledger loses the only thing keeping its hidden values non-negative. One crafted output became 4,000 L-BTC, and the two-way peg turned them into bitcoin on the main chain.
Any identifier derived from more than one variable-length input has to commit to the boundaries between them, whether by prefixing each field with its length or by hashing the fields into separate fixed-size slots. Without that the derivation is not injective, and two distinct inputs can be mistaken for one. The requirement is sharpest wherever a cache stands in for a check, because there a hit is a decision not to run it.
More Incidents This Week
Symbiosis
On 2026/09/11, the Bitcoin route of the Symbiosis cross-chain bridge was exploited across its BNB Smart Chain, Ethereum and Rootstock deployments, costing liquidity providers and users an estimated 9.97 BTC (~$770K, at the ~$77K September-11 price) [5]. Off-chain code that decides how much synthetic bitcoin to mint from a Bitcoin deposit took the depositor's identity from a part of the transaction the depositor controls, letting the attacker pass as the administrator and push the minimum fee below zero; it then subtracted that fee from the deposit without checking its sign, so the subtraction added.
Background
Symbiosis is a cross-chain liquidity protocol that moves value between chains by locking and minting rather than by transferring the asset itself: on chains with smart contracts, a user's tokens are locked by the Portal contract on the source chain, and the Synthesis contract mints an equal amount of a synthetic token, an sToken, on the host chain; burning the sToken releases the original [6]. Bitcoin arrives through this route as syBTC, a token with 8 decimals matching bitcoin's own smallest unit, issued on BNB Smart Chain, Ethereum and Rootstock and paired in pools against BTCB, cbBTC, WBTC and RBTC [5].
Bitcoin has none of that: no smart contracts, so no Portal contract to lock deposits. In its place is the portal — a designated Bitcoin address that plays the same role. A deposit is an ordinary Bitcoin transaction paying it, with the instructions for the destination chain attached to it as data. Off-chain code belonging to the bridge reads that data to learn who is depositing, how much, and where the synthetic token should go, and enforces the portal's fee — subtracted from the deposited amount before the amount to mint is fixed — whose minimum is a parameter its administrator sets.
Nothing about the Bitcoin side is visible to the destination chain, so a Relayers Network carries the resulting request across. The request arrives at BridgeV2, the bridge's on-chain entry point, as an encoded call that it forwards to Synthesis. Authorization rests on an MPC key: the protocol's signers hold shares of a single private key and jointly produce one signature over the request. The entry point for relayed requests carries a single modifier and does nothing else before dispatching the call:
That modifier hashes the request and requires the accompanying signature to be valid for the MPC address:
What the contract establishes is that the MPC key signed the request. The amount the request carries is computed on the Bitcoin side.
Vulnerability Analysis
The defect is not in the destination-chain contracts. It is in the off-chain service that reads Bitcoin deposits and turns them into cross-chain requests. Its source is not publicly available, so the account below follows the team's post-mortem [5] together with a 2024 third-party audit report that contains a code snippet which appears related [7].
Two flaws in the deposit path had to line up, and the post-mortem states that neither was sufficient on its own.
The first is in how the depositor is identified. The instructions attached to a deposit are decoded to recover who is making it, and the decoder took that identity from a part of the transaction data that whoever spends the input controls. A depositor could therefore name themselves as any party the protocol recognizes, including the portal's administrator, the role that sets the minimum fee the portal will accept.
The second is in how that fee is applied. The 2024 audit reported the line in decodeWrap() that computes the amount to mint by subtracting the fee from the value of the deposit output:
Value: types.Satoshi(tx.TxOut[idx].Value) - info.PortalFee,
Its finding was that types.Satoshi is a signed integer type while the info structure carrying PortalFee is untrusted and user-controlled, so the result can be driven negative and, serialized for the destination chain as an unsigned value, becomes large enough to mint an arbitrary quantity of synthetic bitcoin. The audit recorded the issue as fixed at the time [7]. The 2026 post-mortem describes the same kind of failure: the fee was subtracted from the deposit without a check on its sign [5], so a fee below zero enlarged the deposit rather than reducing it. Nothing in the deposit path appears to bound the amount to mint by the bitcoin actually received.
Attack Analysis
Twelve forged mints went through across BNB Smart Chain, Ethereum and Rootstock in roughly four minutes [5]. The following analysis is based on one of them, the transaction 0x9a2bc0...21b9b959 on BNB Smart Chain.
-
Step 1: Passing as the portal's administrator, the attacker moved the minimum fee the portal accepts below zero, so that a deposit declaring a negative fee would be processed instead of rejected [5].
-
Step 2: The attacker deposited 330 satoshi, which appears as 0x000000000000014a . The request that reached BNB Smart Chain carried0x400000000000014a — the same value with the bit for2^62 set,4,611,686,018,427,388,234 base units. The difference between the two is exactly2^62 , so the fee subtracted from this deposit was-4,611,686,018,427,387,904 satoshi:330 - (-4,611,686,018,427,387,904) = 4,611,686,018,427,388,234The request was signed and relayed in that form.
-
Step 3: receiveRequestV2Signed() verified the MPC signature over the request and passed it on, reachingmetaMintSyntheticTokenBTC() . That function resolved the synthetic representation of the real token for the source chain ID,syBTC , and calledsynthesize() for the full signed amount. All of it was transferred to the attacker's address0x025122...5d3Ba2 :46,116,860,184.27388234 syBTC .
-
Step 4: The attacker sold the synthetic token into the pools holding it. A single swap through a Uniswap v4 syBTC /WBTC pool settled18,446,744,072,845,450,682 base units ofsyBTC , about four times what the transaction above minted, and took out4.38897292 WBTC .
Routed onward, the proceeds of that swap came to roughly 137 ether.
The team paused the Bitcoin route, and about 15.2 BTC of portal funds were moved to reserve addresses within hours [5]. A bounty of 20% of anything returned was offered, open until September 13 [8]. The protocol's other routes were unaffected.
Conclusion
No key was stolen and no contract was tricked into running code it was not written to run. The signature the destination chain checked was genuine; what it authorized was a number that off-chain code had already produced incorrectly in two separate ways: once when it read the depositor's identity from a field the depositor controls, letting the attacker pose as the portal's administrator and push its minimum fee below zero, and again when it subtracted that fee from the deposit without checking its sign, so a negative fee enlarged the deposit instead of reducing it.
An identity read out of untrusted input is not an identity: a privileged role can only be established by something the depositor cannot choose, such as the address that actually authorized the spent input, checked against a list the protocol maintains — not a field the depositor is free to fill in. A value that is subtracted needs bounds on both sides: a fee should be required to fall between zero and the deposit, and the amount to mint should never be permitted to exceed what the source chain actually received. Either bound would have stopped this on its own.
References
[1] https://x.com/Liquid_BTC/status/2096696272447218108
[2] https://x.com/Liquid_BTC/status/2097404704028545175
[3] https://github.com/ElementsProject/elements/commit/94000967f6dc05b1afd435e79b1bbc597e29f816
[4] https://www.coindesk.com/markets/2026/09/08/white-hat-hackers-return-most-of-usd320m-bitcoin-taken-from-liquid-network
[5] https://x.com/symbiosis_fi/status/2099566361940795831
[6] https://docs.symbiosis.finance/crosschain-liquidity-engine/synthesizing-process
[7] https://github.com/symbiosis-finance/audits/blob/master/Symbiosis%20Relayers%20Network/Symbiosis%20Relayers%20Network%202024%20-%20Decurity.pdf
[8] https://x.com/symbiosis_fi/status/2098442463358718264
About BlockSec
BlockSec is a full-stack blockchain security and crypto compliance provider. We build products and services that help customers to perform code audit (including smart contracts, blockchain and wallets), intercept attacks in real time, analyze incidents, trace illicit funds, and meet AML/CFT obligations, across the full lifecycle of protocols and platforms.
BlockSec has published multiple blockchain security papers in prestigious conferences, reported several zero-day attacks of DeFi applications, blocked multiple hacks to rescue more than 20 million dollars, and secured billions of cryptocurrencies.
-
Official website: https://blocksec.com/
-
Official Twitter account: https://twitter.com/BlockSecTeam
-
🔗 BlockSec Auditing Service : Submit a request
-
🔗 Phalcon Security APP: Book a demo
-
🔗 Phalcon Compliance