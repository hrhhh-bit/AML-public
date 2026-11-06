# Prompt v2 — rep_certik_014

- vendor: CertiK
- title: Evil in the Shadows: Unveiling the Chaos in Ethereum’s Token Ecosystem
- filename: rep_certik_014_2025-07-22.txt
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
flow_markers: fund flow, cash out, cash-out
This anchor is a signpost ONLY — the report body remains the single source of truth. Do NOT invent chains/relays beyond the evidence.
=== END ATTENTION ANCHOR ===

### TARGET JSON SCHEMA ###
{"title":"TwoPhaseDistillationPayload","type":"object","required":["phase_a_inflow_motifs","phase_b_outflow_motifs","grounded_chains"],"additionalProperties":false,"properties":{"grounded_chains":{"type":"array","minItems":1,"items":{"type":"string","minLength":1},"description":"Abstract chain labels actually grounded in the report evidence (e.g. ['Chain_A', 'Chain_B']). Every `chain` used by ANY node in EITHER phase MUST appear here; the number of distinct chains used by the motifs must NEVER exceed the number of chains declared here."},"phase_a_inflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-in / consolidation / first-hop / cross-chain ENTRY motifs (funds flowing INTO the laundering structure)."},"phase_b_outflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-out / dispersal / DEX swap / OTC cash-out / EXIT motifs (funds leaving the structure toward sinks)."}}}

### REPORT SEGMENT ###
In the Web3 space, new tokens are constantly emerging. Have you ever wondered how many new tokens are issued each day? And more importantly, are these new tokens safe?
These concerns are not unfounded. Over the past few months, CertiK’s security team has identified numerous cases of rug pull transactions. Notably, all of the tokens involved in these cases were newly listed on the blockchain.
Upon investigating these rug pull incidents, CertiK uncovered organized groups behind these scams and identified patterns in their fraudulent operations. Through detailed analysis of their methods, CertiK discovered a potential scam promotion channel used by rug pull groups: Telegram groups. These scammers leverage tools like “New Token Tracer” features in groups such as Banana Gun and Unibot to lure users into purchasing fraudulent tokens, ultimately profiting from rug pulls.
CertiK analyzed token promotion data from these Telegram groups between November 2023 and early August 2024. During this period, 93,930 new tokens were promoted, with 46,526 of them involved in rug pull schemes — an astonishing 49.53%. These rug pull schemes cost the scam groups a total of 149,813.72 ETH, yet they profited 282,699.96 ETH, achieving a staggering 188.7% return on investment. This profit equates to approximately $800 million.
To assess the proportion of new tokens promoted through Telegram groups in relation to the Ethereum mainnet, CertiK analyzed the number of new tokens issued on the Ethereum network during the same period. The data showed that 100,260 new tokens were launched, 89.99% of which were promoted via Telegram groups.
On average, around 370 new tokens are issued daily, significantly exceeding reasonable expectations. Further investigation revealed an unsettling truth — at least 48,265 tokens were involved in rug pull scams, representing 48.14% of the total. In other words, almost one out of every two new tokens on the Ethereum mainnet is linked to fraudulent activity.
CertiK has identified additional rug pull cases on other blockchain networks. This indicates that the security risks within the entire Web3 new token ecosystem are far more severe than previously anticipated. In response, CertiK has compiled this research report to help all Web3 participants raise their awareness, stay vigilant against the ever-evolving scams, and take necessary precautions to protect their assets.
The ERC-20 token standard is fundamental to the Ethereum ecosystem, as it defines a set of rules and functions that enable the creation, transfer, and management of digital assets. Tokens that adhere to the ERC-20 standard are compatible with a vast array of smart contracts and decentralized applications (dApps), promoting interoperability and composability.
One of the primary benefits of the ERC-20 standard is its ease of use. Developers can leverage the standard to create their own tokens, facilitating fundraising efforts through initial coin offerings (ICOs) and decentralized finance (DeFi) projects. For instance, tokens like USDT, PEPE, and DOGE adhere to the ERC-20 standard and can be traded with one another on decentralized exchanges (DEXs).
Unfortunately, the widespread adoption of ERC-20 tokens has also opened doors for malicious actors to target users. Many scammers create fraudulent ERC-20 tokens with hidden vulnerabilities or back doors in the code, and list them on DEXs to deceive unsuspecting investors.
In the DeFi ecosystem, rug pull scams typically involve the following steps:
Below, we will examine a specific rug pull case to gain a deeper understanding of how these scams typically operate. The token we will discuss is often referred to as a “Honey Pot” or “Exit Scam” token; however, for consistency, we will use the term “Rug pull token” throughout this analysis.
First, the malicious actors deployed the TOMMI token using a Deployer address (0x4bAF). They initiated a liquidity pool by pairing 1.5 ETH with 100,000,000 TOMMI tokens and began purchasing TOMMI through other addresses to fabricate trading volume within the pool. This strategy was designed to attract users and token-sniping bots to the protocol.
Once a sufficient number of bots and unsuspecting users had purchased TOMMI, the attacker executed the rug pull using the rug puller address (0x43a9). With 38,739,354 TOMMI tokens, the attacker dumped these tokens into the liquidity pool, extracting approximately 3.95 ETH.
The attacker obtained tokens through a malicious “Approve” mechanism embedded in the TOMMI token contract. When the liquidity pool was deployed, it granted the rug puller address “approve” permission, allowing the attacker to pull TOMMI tokens directly from the pool.
The attacker deposited 2.47309009 ETH into the Token Deployer (0x4bAF) via the centralized exchange as initial funding for the rug pull.
Figure 1: Transaction Information of Initial Funding from Exchange to Deployer
The Deployer created the TOMMI token, pre-mining a total of 100,000,000 tokens, which were allocated to itself.
Figure 2: Transaction Information for the Creation of TOMMI Token
The Deployer established a liquidity pool using 1.5 ETH along with all pre-mined tokens, thereby acquiring approximately 0.387 LP tokens.
Figure 3: Fund Flow for Liquidity Pool Creation by Deployer
The Token Deployer sent all LP tokens to the zero address for destruction. Since the TOMMI contract lacks a Mint function, the Token Deployer theoretically lost the ability to execute a rug pull at this point. (This is one of the necessary conditions to attract bots, as some buyers evaluate whether newly pooled tokens are at risk of a rug pull. The Deployer also set the contract’s Owner to the zero address to deceive anti-fraud programs used by buyers.)
Figure 4: Transaction Information for the Destruction of LP Tokens
The attacker used multiple addresses to actively purchase TOMMI tokens from the liquidity pool, artificially inflating the trading volume to further entice new token buyers. (The basis for identifying these addresses as the attacker’s masquerade lies in the fact that the funds originate from the historical fund-transfer addresses of the rug pull group.)
Figure 5: Transaction Information and Fund Flow for Purchases of TOMMI Tokens from Attacker’s Other Addresses
The attacker initiated the rug pull using the rug puller address (0x43A9), directly transferring 38,739,354 tokens from the liquidity pool through the token’s back door, and subsequently sold these tokens to withdraw approximately 3.95 ETH.
Figure 6: Transaction Information and Fund Flow for Rug Pull
The attacker sent the funds from the rug pull address to the fund-transfer address (0xD921).
Figure 7: Transaction Information for Rug Puller Sending Funds to Fund-Transfer Address
The fund-transfer address (0xD921) sent the funds to the fund-holding address (0x2836). From this, it is evident that, after the completion of the rug pull, the attacker sent the funds to a designated fund-holding address.
This fund-holding address serves as a central collection point for a significant number of rug pull cases we have monitored. The address typically splits the majority of the received funds to initiate a new round of rug pulls, while a smaller portion is withdrawn through centralized exchanges (CEXs). We have identified several fund-holding addresses, with 0x2836 being one of them.
Figure 8: Fund Transfer Information from Fund-Transfer Address
The attackers left a malicious back door in the ‘openTrading’ function of the TOMMI token contract, allowing the liquidity pool to grant transfer permissions to the attacker’s address. Consequently, the attacker could withdraw tokens directly from the liquidity pool during the rug pull.
Figure 9: ‘openTrading’ Function in the TOMMI Token Contract
Figure 10: ‘onInit’ Function in the TOMMI Token Contract
The ‘openTrading’ function, primarily responsible for creating a new liquidity pool (Figure 9), was invoked by the attackers. However, the ‘onInit’ function, which already had an embedded back door (Figure 10), was also executed. The ‘onInit’ function granted the ‘uniswapV2Pair’ contract the ability to transfer tokens in an amount equal to ‘type(uint256)’ to the ‘_chefAddress’. Here, ‘uniswapV2Pair’ refers to the liquidity pool address, while ‘_chefAddress’ refers to the attacker’s address, which was defined during the contract’s deployment (Figure 11).
Figure 11: ‘Constructor’ Function of the TOMMI Token Contract
These characteristics are common across the cases we have examined, suggesting common patterns in rug pull operations. We have also noticed that funds in rug pull schemes are often consolidated in a fund-holding address after the scheme is complete, suggesting that seemingly independent cases may actually be connected to the same group or organized criminal network.
Based on these characteristics, we have identified a behavioral pattern for rug pull operations and have applied this model to detect and analyze additional cases in hopes of identifying the groups behind these schemes.
Attackers orchestrating rug pulls typically funnel their proceeds into fund-holding addresses after their operations. Based on this pattern, we selected several highly active fund-holding addresses linked to distinct and well-documented fraudulent activities for further analysis. We identified seven fund-holding addresses that stood out in our investigation. These addresses were linked to 1,124 suspected rug pull cases, all successfully detected by our on-chain monitoring system (CertiKAlert).
After executing a rug pull, the associated criminal groups consolidate their illicit gains into these fund-holding addresses. The funds within these fund-holding addresses are then split and used to fund future rug pull schemes, including launching new tokens and manipulating liquidity pools. Additionally, a small portion of the funds is cashed out via CEXs or swap platforms.
The financial data associated with these fund-holding addresses is summarized in Table 1:
Table 1: Reserve Addresses Income and Cost Data
In a complete rug pull scam, the criminal group typically uses one address as the Deployer for the rug pull token and acquires initial funding by withdrawing from a CEX to create the token and its corresponding liquidity pool. Once they have attracted enough users or front-running bots to purchase the rug pull token using ETH, the group utilizes another address, known as the rug puller, to execute the scheme and transfer the profits to the fund-holding address.
In this process, we consider the ETH that the Deployer withdraws from the exchange or invests when creating the liquidity pool as the rug pull’s cost (calculated depending on the Deployer’s actions). The ETH transferred by the rug puller to the fund-holding address (or any intermediary fund-transfer address) after completing the rug pull is considered the profit from that specific scam, leading to the profit and cost data presented in Table 1. The ETH/USD exchange rate (1 ETH = 2,513.56 USD, with the price recorded on August 31, 2024) used for USD profit conversion is calculated based on the real-time rate at the time of data consolidation.
It is important to note that during the scam, the attackers often use their own ETH to purchase the rug pull token they created, simulating legitimate liquidity pool activity to attract front-running bots. However, these costs were not included in the calculations, meaning the data in Table 1 overestimates the actual profits of the attackers. In reality, the true profits would be slightly lower.
We generated a profit distribution pie chart based on the rug pull profit data for each address from Table 1 (Figure 12). The top three addresses by profit share are 0x1607, 0xDF1a, and 0x2836. The address 0x1607 yielded the highest profit, approximately 2,668.17 ETH, representing 27.7% of the total profit across all addresses.
Figure 12: Profit Distribution Pie Chart for Fund-Holding Addresses
Although the final funds were consolidated into different fund-holding addresses, the commonalities among the related cases (such as the back door mechanism of the rug pull, profit paths, etc.) strongly suggest that these fund-holding addresses might belong to the same syndicate.
One key indicator for determining whether there is a connection between fund-holding addresses is to check for direct transfer relationships between them. To verify the correlation among these addresses, we analyzed their historical transaction records.
In most of the cases we have previously analyzed, the profits from each rug pull scam eventually flowed to only one fund-holding address. Therefore, tracking the flow of these profits alone is insufficient to link different fund-holding addresses. Instead, we examined the direct fund transfers between these addresses to uncover potential links, shown in Figure 13.
Figure 13: Fund-Holding Address Fund Flow Diagram
It is important to note that addresses 0x1d39 and 0x6348 in Figure 13 serve as shared rug pull infrastructure contracts for the fund-holding addresses. These addresses use the contracts to split funds and send them to other addresses, which use these funds to falsify the trading volume of rug pull tokens.
Based on the direct ETH transfer relationships in Figure 13, we can classify the fund-holding addresses into the following three groups:
There are direct transfer relationships within each group, but no direct transfers between groups. As a result, it is likely that these seven fund-holding addresses belong to three separate groups. However, these three groups are all connected by the same infrastructure contracts, which split ETH for subsequent rug pull operations, thereby linking what appear to be loosely-connected groups into a unified entity.
As previously mentioned, there are two primary shared infrastructure addresses used by the fund-holding addresses: 0x1d3970677aa2324E4822b293e500220958d493d0 and 0x634847D6b650B9f442b3B582971f859E6e65eB53.
The infrastructure address 0x1d39 primarily operates through two key functions: ‘multiSendETH’ and ‘0x7a860e7e.’ The main function of ‘multiSendETH’ is to facilitate split transfers. Fund-holding addresses use the ‘Multi Send ETH’ function of 0x1d39 to divide funds into multiple addresses, simulating transaction volume for rug pull tokens. The transaction details are shown in Figure 14.
This splitting mechanism helps attackers create the illusion of token activity, making the tokens appear more attractive and enticing more users or sniping bots to make purchases. Through this method, the attackers enhance both the deception and complexity of the scams.
Figure 14: Transaction Data Showing Fund Splitting by Fund-Holding Addresses via 0x1d39
The function ‘0x7a860e7e’ is designed for purchasing rug pull tokens. Once the addresses disguised as regular users receive the split funds from the fund-holding address, they either directly interact with Uniswap’s Router or use the ‘0x7a860e7e’ function through 0x1d39 to purchase the tokens, thus simulating active trading volume.
The core functions of infrastructure address 0x6348 are similar to those of 0x1d39, with the only difference being that the function used to purchase tokens is renamed ‘0x3f8a436c’.
To further understand the usage of these infrastructures by the rug pull groups, we analyzed the transaction histories of 0x1d39 and 0x6348, and compiled statistics on the frequency with which external addresses utilized the two key functions of these contracts. The results are shown in Table 2 and Table 3.
Table 2: Usage Statistics of Two Main Functions in Infrastructure Address 0x1d39 by External Addresses
Table 3: Usage Statistics of Two Main Functions in Infrastructure Address 0x6348 by External Addresses
The above data illustrates that the rug pull groups exhibit clear characteristics in their use of infrastructure addresses: They use only a small number of fund-holding addresses or fund-transfer addresses to split funds, while utilizing a large number of other addresses to fabricate trading volume for the tokens. For instance, as many as 6,224 addresses were used to fake trading volume through the address 0x6348. This vast number of addresses significantly increases the difficulty in distinguishing between the attackers’ addresses and the victims’ addresses.
It is important to note that the rug pull groups’ method of fabricating trading volume is not limited to the use of these infrastructure addresses; some addresses also directly exchange tokens through DEXs to fake trading volume.
Additionally, we have compiled the usage statistics of the seven aforementioned fund-holding addresses for each function within the 0x1d39 and 0x6348 infrastructure addresses, along with the amount of ETH involved in each function. The resulting data is presented in Table 4 and Table 5.
Table 4: Direct Usage of Infrastructure Address 0x1d39 by Fund-Holding Addresses
Table 5: Direct Usage of Infrastructure Address 0x6348 by Fund-Holding Addresses
From the above data, we can see that the fund-holding addresses split funds a total of 3,616 times through the infrastructure, with the total amount reaching 9,369.98 ETH. Additionally, all fund-holding addresses, except for 0xDF1a, split funds only through the infrastructure, while the purchase of rug pull tokens is carried out by the addresses that receive these split funds. This indicates that these rug pull groups followed a clear strategy with distinct role divisions during their operations.
Address 0x0573 did not participate in fund splitting through the infrastructure, and in the rug pull cases associated with it, the funds used to fabricate transaction volumes came from other addresses. This suggests some degree of operational variation between different fund-holding addresses.
By analyzing the financial connections between different fund-holding addresses and their usage of the infrastructure, we gained a more comprehensive understanding of the relationships among these addresses. These rug pull groups operate in a far more professional and organized manner than we initially thought, strongly suggesting that criminal syndicates are behind the scenes, carefully planning and executing these systematic scams.
When conducting a rug pull, the attackers typically use a new external account address (EOA) as the Deployer to deploy the rug pull token. These Deployer addresses usually obtain initial funds through CEXs or swap platforms. Therefore, we conducted a source of funds analysis on the rug pull cases associated with the fund-holding addresses mentioned earlier with the goal of acquiring more detailed information on the origins of operational funds.
Table 6: Correspondence between Fund Source Tags and Fund-Holding Address Case Numbers
The data in Table 6 shows that the majority of the funds for deploying rug pull tokens in the associated cases of fund-holding addresses primarily originate from a CEX. Among the 1,124 cases we analyzed, the number of cases with funding sourced from the CEX’s hot wallet reached 1,069, accounting for an impressive 95.11%. This indicates that, for the vast majority of rug pull cases, we can trace back to specific account holders through the KYC information and withdrawal history records of CEX accounts, thus obtaining crucial leads for solving the cases.
We also found that these rug pull groups often obtain operational funds from multiple exchange hot wallets simultaneously, and the usage levels of each wallet (in terms of usage frequency and proportion) are approximately equal. This indicates that the rug pull groups intentionally aim to increase the financial independence of each scheme, thereby raising the difficulty of tracing their sources and adding complexity to the tracking process. It is logical to conclude that the attackers involved in these groups are well-trained, have clear divisions of labor, and are tightly organized.
With such tightly-organized groups of criminals, we then wondered how they acquire users to trick into purchasing their tokens. Next, we will explore the typical behavior of victim addresses in these cases to reveal how attackers lure them into scams.
By analyzing financial connections, we maintained a list of addresses associated with rug pull groups. We were able to use this list to filter out the victim addresses from the transaction records of the liquidity pools corresponding to the rug pull tokens. We obtained information associated with the fund-holding addresses (Table 7) as well as the contract call information of the victim addresses (Table 8).
Table 7: Information on Victim Addresses Associated with Funding Source Addresses
From the data in Table 7, it can be observed that, in the rug pull cases captured by our on-chain monitoring system (CertiKAlert), the average number of victim addresses per case is 26.82.
Table 8: Information on Victim Address Contract Call
From the data in Table 8, we can see that 30.40% of the rug pull tokens were purchased through well-known on-chain sniper bot platforms such as Maestro and Banana Gun. This finding suggests that on-chain sniper bots may be an important promotional channel for rug pull groups, as they help to quickly attract participants who are interested in newly-launched tokens.
By investigating the current Web3 ICOs ecosystem, studying the operational models of on-chain sniper bots, and combining certain social engineering techniques, we ultimately identify two possible advertising channels used by rug pull groups: Twitter and Telegram.
These Twitter and Telegram groups are not specifically created by the rug pull groups, but rather exist as fundamental components within the ICOs ecosystem. They are maintained by third-party organizations, such as on-chain sniper bot operating teams or professional ICOs teams, specifically designed to advertise newly launched tokens. These groups have become natural advertising avenues for rug pull groups.
Figure 16: Banana Gun New Token Push Group
Figure 16 illustrates the Telegram group maintained by the on-chain sniper bot team, Banana Gun, which is specifically designed to promote newly-launched tokens. This shares essential information about new tokens and provides users with convenient purchasing access. Once users have configured the basic settings of the Banana Gun Sniper Bot, they can quickly purchase the token by clicking the ‘Snipe’ button associated with the corresponding token promotion message in the group. We conducted a manual sampling of the tokens promoted within this group and discovered that a significant portion of these tokens were likely associated with rug pulls.
To investigate the portion of rug pull tokens among newly-promoted tokens in these Telegram groups, we utilized the Telegram API to scrape information on newly-launched Ethereum tokens promoted by the Banana Gun, Unibot, and other third-party token message groups from October 2023 to August 2024. During this period, these groups promoted 93,930 tokens.
Rug pull groups typically create liquidity pools for tokens in Uniswap V2 and inject a certain amount of ETH. After users or sniper bots purchase the tokens from these pools, the scammers profit by either crashing the price or removing liquidity. This entire process generally concludes within 24 hours.
Consequently, we have summarized the following detection criteria for rug pull tokens and applied these rules to scan the 93,930 tokens:
As shown in Table 9, among the 93,930 tokens pushed in Telegram groups, a total of 46,526 tokens were detected as rug pull tokens, which represents 49.53%.
Table 9: Detection Results of Tokens in Telegram Groups
Considering that some project teams may also withdraw liquidity after a project’s failure, such actions should not be simplistically classified as the rug pull fraud discussed above. Therefore, we need to account for the potential impact of such situations on our results. Although our third detection rule has effectively filtered out the vast majority of similar cases, there may still be instances of misjudgment.
To better understand the impact of these potential false positives, we statistically analyzed the active duration of the 46,526 tokens identified as rug pull tokens, with the results presented in Table 10. By examining the active duration of these tokens, we can further differentiate between rug pull activities and liquidity withdrawals due to project failures, thus enabling a more accurate assessment of the actual scale of rug pulls.
Table 10: Time Distribution of Rug Pull Tokens from Creation to End of Rug Pull
We found that 41,801 tokens (89.84%) had an active time (from token creation to the last execution of the rug pull) of less than 72 hours. Under normal circumstances, 72 hours is insufficient to determine whether a project has failed. Thus, we posit that rug pull behaviors with an active time of less than 72 hours are not indicative of normal project-related fund withdrawals.
It is noteworthy that 25,622 tokens had an active time of less than three hours, constituting 55.07% of the total. This suggests that rug pull groups operate with remarkable efficiency, favoring a ‘short, quick, and fast’ modus operandi, which results in a very high turnover of funds.
We also evaluated the cash-out methods and contract call methods employed by these 46,526 rug pull groups to confirm their tendencies:
The assessment of contract call methods examines the target contract objects that rug pull groups call when executing their schemes. The main objects include:
By evaluating the cash-out methods and contract call methods, we can further comprehend the operating patterns and characteristics of rug pull groups, thereby enhancing our ability to prevent and identify similar fraudulent activities.
Table 11: Number of Cases Corresponding to Each Cash-Out Method for Rug Pull Tokens in Telegram Groups
Rug pull groups predominantly cash out by removing liquidity, with 32,131 cases, accounting for 69.06% of the total. This suggests that these rug pull groups prefer to cash out by removing liquidity due to its simplicity and directness, as it does not require writing customized contracts or additional actions. In contrast, cashing out by dumping requires the rug pull groups to embed back doors into the token’s contract code. This process is more complicated and potentially riskier, which may explain the relatively lower number of cases adopting this method.
As shown in the table below, rug pull groups predominantly prefer to execute through Uniswap’s Router contract, accounting for 40,887 executions, or 76.35% of the total. The overall number of rug pull executions, 53,552, exceeds the number of rug pull tokens, 46,526, indicating that in certain cases, rug pull groups may execute multiple rug pull operations. This could be to maximize their profit or to cash out from different victims in separate batches.
Table 12: Contract Call Information for Rug Pull Attack
Next, we conducted a statistical analysis of the costs and profits associated with the 46,526 rug pull cases. We considered the ETH obtained by rug pull groups from CEXs or flash swap services prior to token deployment as the cost, and the ETH recovered during the final execution of the rug pull as the profit. Since we did not take into account the ETH invested by some rug pull groups when fabricating liquidity pool trading volume, the actual cost data may be higher.
Table 13: Cost and Profit Analysis of Rug Pull Tokens in Telegram Groups
Among the 46,526 rug pull tokens analyzed, the total profit reached 282,699.96 ETH, resulting in a profit margin of 188.70%, equivalent to approximately $800 million. Although the actual profits may be slightly lower than the figures presented, the overall scale is significant, indicating that these groups have generated substantial earnings through fraudulent activities.
We also initiated a detailed analysis of overall tokens on the Ethereum mainnet to compare their coverage to those promoted in Telegram groups. We crawled the block data from RPC nodes between October 2023 and August 2024, and obtained information on newly-deployed tokens (excluding tokens that implement business logic through proxies, as there are very few cases of rug pull involving tokens with proxy implementations). The final count of captured tokens was 154,500, with 54,240 being Uniswap V2 liquidity pool (LP) tokens, which are not within the scope of this analysis.
Therefore, we filtered out the LP tokens, resulting in a final token count of 100,260.
Table 14: Mainnet Token Information
We applied the rug pull detection rules to these 100,260 tokens and identified 48,265 as rug pull tokens, accounting for 48.14% of the total. This percentage is roughly equivalent to the proportion of rug pull tokens found among the tokens promoted in Telegram groups.
Table 15: Detection Results for Tokens in Telegram Groups
To further analyze the relationship between the tokens promoted in Telegram groups and all tokens launched on the Ethereum mainnet, we conducted a detailed comparison between the two sets of tokens.
The data in Table 16 shows that there is a significant overlap between the tokens promoted in Telegram groups and the tokens captured on the Ethereum mainnet, with 90,228 shared tokens, accounting for 89.99% of the mainnet tokens. However, 3,703 tokens from the Telegram groups were not captured in the mainnet data. Upon sampling, we found that all of these tokens had proxy implementations, which were excluded from our mainnet token capture.
Table 16: Overlap between Tokens in Telegram Groups and Mainnet Tokens
As for the 10,032 tokens that were exclusive to the mainnet, it is likely that they were filtered out by Telegram groups’ promotion criteria due to their lack of appeal or failure to meet specific standards for promotion.
We conducted a separate rug pull detection on the 3,703 tokens with proxy implementations and found only 10 rug pull tokens. Therefore, these tokens have a minimal impact on the rug pull detection results of tokens promoted in Telegram groups, confirming the high consistency between the rug pull detection results of Telegram group tokens and mainnet tokens.
Table 17: Addresses of Rug Pull Tokens with Proxy Implementations in Telegram Groups
The tokens promoted by Telegram groups account for approximately 90% of the mainnet, and their rug pull detection results are highly consistent with those of the mainnet tokens. Therefore, the previous analysis of the rug pull detection and data analysis for tokens promoted by Telegram groups generally reflect the current state of Ethereum’s token ecosystem.
As mentioned earlier, the proportion of rug pull tokens on the Ethereum mainnet is approximately 48.14%. However, we are equally interested in the remaining 51.86% of non-rug pull tokens. Even after excluding rug pull tokens, there are still 51,995 tokens in an unknown state, a number that far exceeds our expectations for a reasonable quantity of tokens. Therefore, we conducted a statistical analysis of the time from the creation to the final cessation of activity for all tokens on the mainnet:
Table 18: Time Distribution from Creation to Final Cessation of Activity for All Tokens on the Mainnet
From the data in Table 18, we can see that, when we broaden our perspective to the entire Ethereum mainnet, the number of tokens with a life cycle of less than 72 hours amounts to 78,018, accounting for 77.82% of the total. This figure is significantly higher than the number of rug pull tokens we detected, indicating that the initial rug pull detection rules do not fully cover all cases. In fact, we have discovered rug pull tokens that went undetected through sampling detection.
Additionally, the number of tokens with a lifecycle greater than 72 hours is 22,242. This subset of tokens is not the focus of our analysis in this paper, and thus there may still be other details to uncover. For instance, some of these tokens may represent failed projects or projects with a certain user base that have not received long-term support for development; the stories and reasons behind these tokens may conceal more complex market dynamics.
The token ecology of the Ethereum mainnet is far more complex than we initially expected, with a mix of various short-term and long-term projects, and potential fraudulent activities regularly emerging. We hope that through such analysis, we can encourage Ethereum participants to proceed carefully and study these issues, thereby enhancing the security of the entire blockchain ecosystem.
The fact that 48.14% of newly issued tokens on the Ethereum mainnet are rug pull tokens is highly alarming. This means that, for every two tokens launched, on average, one is a scam. However, what is even more concerning is that, in the rug pull cases captured by on-chain monitoring programs, the number of cases on other blockchain networks even surpasses that on Ethereum. The token ecosystem of other networks is a subject worthy of further research.
Moreover, even excluding the 48.14% of rug pull tokens, Ethereum still sees about 140 new tokens being launched each day, which is far beyond the reasonable range of issuance. In this context, we think it is worth exploring other scams that may be plaguing the network.
In addition, several key points raised in this paper require further exploration:
With the large number of rug pull cases detected, how can we effectively determine how many independent rug pull groups are operating behind these cases and whether there are connections between these groups? This analysis may require combining data on fund flows and shared address usage.
Distinguishing between victims and attackers is a critical step in identifying fraudulent activities, but the line between victim and attacker addresses is often blurred. How to more precisely differentiate them remains a question for deeper investigation.
Current rug pull detection methods are primarily based on post-event analysis. Is it possible to develop a method to detect potential rug pull risks in active tokens in real-time or even before the event occurs? Such a capability would help minimize investor losses and allow for timely intervention.
Studying the conditions under which rug pull groups execute these operations (e.g., how much profit they typically make before pulling the rug and whether they employ any mechanisms or techniques to secure their profits) could help predict and prevent future rug pulls.
The rug pull groups discussed in this paper primarily promote their tokens through Twitter and Telegram. Are they using other channels, such as forums, social media platforms, or advertising platforms? Do these channels present similar risks?
As previously mentioned, the current ICO ecosystem is rife with scams, and Web3 investors may suffer losses if they are not cautious. With the escalating battle between rug pull groups and anti-fraud teams, it has become increasingly difficult for investors to identify fraudulent tokens or projects. For investors seeking to enter the ICOs market, our team of security experts offers the following recommendations:
Additionally, we recommend using Certik’s TokenScan service, which can effectively detect hidden risks within tokens and prevent losses before they occur. TokenScan now fully supports the Ethereum, BSC and Solana chain, with plans to gradually extend coverage across multiple chains, helping investors better safeguard their assets in the complex Web3 environment.
Beyond the rug pull groups examined in this paper, an increasing number of similar criminals are exploiting the infrastructure and mechanisms of various sectors and platforms in Web3 for illicit profits. It is crucial to start paying attention to these often overlooked vulnerabilities to prevent criminals from taking advantage of innocent victims
Rug pull groups’ funds inevitably flow through major exchanges, but we believe that the financial flows related to rug pull scams are just the tip of the iceberg. The scale of malicious funds passing through exchanges may be far greater than we can imagine. Therefore, we strongly urge all major exchanges to implement stricter measures and actively combat illicit activities to ensure the safety of users’ assets.
Third-party service providers, such as project promotion and on-chain sniping bots, have unfortunately become tools for organized scam groups to profit from. Thus, we call on all third-party service providers to enhance security reviews of their products or content to avoid being exploited by criminals.
At the same time, we appeal to all victims, including MEV arbitrageurs and regular users, to proactively use security scanning tools to evaluate potential projects and to refer to ratings from reputable security institutions before investing in unknown ventures. We also encourage victims to actively disclose the malicious actions of criminals.
As a professional security team, we also call upon all security practitioners to take the initiative in discovering, identifying, and combating illegal activities, and to consistently voice concerns to protect users’ assets.
In the Web3 space, every participant — whether a user, project team, exchange, MEV arbitrageur or a third-party service provider similar to bots — plays a crucial role. We hope that each participant contributes to the sustainable development of Web3, working together to create a safer and more transparent blockchain environment.