# Prompt v2 — rep_slowmist_002

- vendor: SlowMist
- title: Threat Intelligence | Analysis of FomoPeek App Store Poisoning and iOS Kernel Exploitation
- filename: rep_slowmist_002_2026-09-20.txt
- hops_detected: 10

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
hops_detected: 10
flow_markers: fund flow, money laundering, laundering, cross-chain, bridge
This anchor is a signpost ONLY — the report body remains the single source of truth. Do NOT invent chains/relays beyond the evidence.
=== END ATTENTION ANCHOR ===

### TARGET JSON SCHEMA ###
{"title":"TwoPhaseDistillationPayload","type":"object","required":["phase_a_inflow_motifs","phase_b_outflow_motifs","grounded_chains"],"additionalProperties":false,"properties":{"grounded_chains":{"type":"array","minItems":1,"items":{"type":"string","minLength":1},"description":"Abstract chain labels actually grounded in the report evidence (e.g. ['Chain_A', 'Chain_B']). Every `chain` used by ANY node in EITHER phase MUST appear here; the number of distinct chains used by the motifs must NEVER exceed the number of chains declared here."},"phase_a_inflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-in / consolidation / first-hop / cross-chain ENTRY motifs (funds flowing INTO the laundering structure)."},"phase_b_outflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-out / dispersal / DEX swap / OTC cash-out / EXIT motifs (funds leaving the structure toward sinks)."}}}

### REPORT SEGMENT ###
Recently, the SlowMist security team received multiple reports of user assets being stolen. Upon verification, all of the incidents involved private key exposure, and some of the affected users had previously downloaded and used FomoPeek App versions 1.1–1.2.
Through a joint analysis with the OKX security team, we confirmed that FomoPeek 1.1 and 1.2 had the two malicious modules, apptrace and libapptracecore, embedded in them. These modules are capable of remote configuration, kernel exploit execution, sandbox escape, Keychain decryption, and cross-application data collection.
Dynamic verification showed that the app retrieves an encrypted C2 address from Bitbucket and reports device information to api-a95f0ed200f.assisaint[.]com, while receiving remote configurations. During testing, the exploit_enabled value returned by the C2 was false. To verify the subsequent execution chain, we used Hook in an isolated environment to modify the relevant switch, after client-side decryption, to true. We then obtained a collection list targeting 19 wallet and note-taking applications and captured the complete request for packaging and uploading the Apple Notes container.
By hooking the client-side encryption functions, we decrypted the requests and responses transmitted through this channel. The configuration returned by the server confirmed that the attacker could remotely enable exploit execution through the server, adjust the execution interval, and control its periodic repeated execution.
We completed reverse engineering analysis and sample attribution based on historical-version IPAs obtained through the official App Store channel. The results showed that the above-mentioned malicious modules were not found in version 1.0; version 1.1 (build 105) first introduced them on September 9, 2026; version 1.2 (build 110) was released on September 12 and retained the same code; and version 1.3 (build 111) removed both frameworks entirely on September 17. Therefore, the explicitly affected App versions are 1.1 and 1.2. The relevant malicious modules were distributed through official App Store versions, rather than third-party re-signed or sideloaded builds.
The system version coverage declared by the framework at the code level includes iOS 12.0–18.7.2 and iOS 26.0–26.1, indicating that its attack targets were not limited to older system versions or legacy devices.
MistEye is a Web3 threat intelligence and dynamic security monitoring system independently developed by SlowMist. It integrates security monitoring and intelligence aggregation capabilities to provide users with real-time risk alerts and asset protection.
MistEye synchronized the risk through intelligence feeds and customer alert channels at the earliest opportunity.
Some users whose assets were stolen had installed and used FomoPeek before the incidents occurred. To verify its connection with the private key exposure incidents, we obtained historical-version IPAs of the app through the official App Store channel and conducted a version-by-version analysis of the package structure, loading dependencies, signing ownership, and binary contents.
From the publicly available information, FomoPeek had all the outward appearances of a normal project:
The app was normally listed on the App Store, had an official website and official social media accounts, and was publicly positioned as a “read-only on-chain monitoring and alerting tool” that did not connect to wallets or require a seed phrase. Therefore, from either the review side or the user side, it would be difficult to associate it with kernel exploitation based on its appearance alone.
Public promotional information indicates that FomoPeek was primarily distributed through crypto KOLs and related communities. Users were required to use a referral code to download and register the app from the App Store, set a “security code,” add wallets for monitoring, and operate the app on a physical device for several minutes. After review, users could receive 5–7 USDT. Some promotional materials specifically emphasized that “each iPhone has only one chance,” “multiple accounts on the same device are invalid,” and that users “must use a physical device and stay for 5–7 minutes.”
This requirement is noteworthy. The sample integrates an exploitation strategy named CicutaVirosaStrategy, corresponding to the publicly disclosed cicuta_virosa exploit, which takes more than two minutes to run per execution. Therefore, the promotional requirements of “physical device only,” “cloud phones not supported,” and “remaining active for several minutes” are consistent with the technical characteristics of an exploit chain that requires continuous execution on a real device for a period of time. However, this promotional rule can only be treated as a supporting clue and cannot, by itself, be used to determine malicious intent.
In mid-September, user warnings had already appeared on public social platforms. At 17:11 UTC on September 16, 2026, X user 金灰 (@GXingPing) posted that they had experienced an asset theft incident after downloading the FomoPeek app and advised others to uninstall it as soon as possible.
Before users began reporting concentrated asset theft incidents, iOS data extraction capabilities related to such attacks had already been publicly warned about. On March 25, 2026, SlowMist Chief Information Security Officer @im23pds issued a security alert stating that the DarkSword attack tool had been leaked and could extract and exfiltrate forensic-level data from iOS devices through an HTTP interface. Attackers could also combine social engineering or watering-hole attacks to trick targets into visiting websites or pages implanted with malicious code, thereby stealing data from iPhones and iPads and uploading it to servers controlled by the attackers.
Publicly available information shows that the Seller registered with Apple is Porter Manufacturing, L.L.C., while the developer display name is WhaleScanv. Currently, only one app, FomoPeek, has been identified under this developer name.
The following timeline is noteworthy:
We discovered two frameworks unrelated to the app’s business functionality in versions 1.1 and 1.2.
A version comparison showed that 1.1 and 1.2 contained the same set of malicious modules, with identical code and data segments. Version 1.3, on the other hand, removed both frameworks entirely, reducing the IPA size from 10.47 MB to 1.81 MB.
The main application and both frameworks all used the same Apple signing entity. The original IPA also retained FairPlay encryption metadata, indicating that the malicious modules were part of the official package content submitted by the developer to the App Store, rather than a third-party re-signed or sideloaded build.
The two modules have clearly defined roles: apptrace is responsible for C2 communication, while libapptracecore is responsible for kernel exploitation and data collection.
The namespace distribution of libapptracecore indicates its nature: it is not a telemetry, analytics, or anti-debugging component, but rather a complete toolchain spanning exploitation (exploit), kernel access (kernel), permissions and sandbox access (permissions), Keychain operations (keychain), and data acquisition and transmission (acquisition). apptrace handles all communications with the external control server, and the two components together form an implant combining “communication + exploitation.”
The Mach-O load commands of the main program reference the two frameworks via LC_LOAD_DYLIB (non-weak):
@rpath/apptrace.framework/apptrace
@rpath/libapptracecore.framework/libapptracecore
This means that regardless of whether the business code invokes them, both frameworks will be loaded by dyld into the same process when the App starts.
On the other hand, there are indeed no explicit invocation traces on the main program side: all 1,048 imported symbols in the symbol table come from system libraries, and the ObjC class references contain only system classes. Apart from the two loading paths mentioned above, no class names or method names from the frameworks can be found. The frameworks themselves also do not contain ObjC +load / +initialize methods. We performed three levels of call tracing on the 34 C++ static initialization functions (__mod_init_func), but none of them reached the exploitation or data collection code.
Therefore, at the static level, it can be confirmed that the modules are forcibly loaded into the process when the App starts, and that the capability code is complete. The actual trigger timing and execution evidence need to be verified through dynamic testing on a real device.
libapptracecore implements 8 exploitation strategy classes, all of which inherit from exploit::IExploitStrategy / KernelMachTaskExploitStrategyBase, with each strategy containing built-in logic to determine whether it supports the current device:
The version windows of the 8 strategies are contiguous, and the coverage range declared in the code is iOS 12.0–18.7.2 and iOS 26.0–26.1. The framework sequentially determines whether a strategy is available based on the system version and device model, and distinguishes among three outcomes: successful exploitation, failed exploitation, and unsupported device.
The built-in device model table also includes models such as iPhone16,1/16,2, iPhone17,1–17,5, iPad15,3–15,6, and iPad16,1–16,6, covering devices released from 2023 to 2025. This indicates that the adaptation targets were not limited to older devices.
The sandbox component is implemented by permissions::SandboxExtPatcher, with the target entitlement string com.apple.app-sandbox.read-write. After escaping the sandbox, the process can read paths outside the container of the current app.
The Keychain component is the most directly harmful part of the entire framework:
After running the affected version on an isolated device (disguised as an iPhone 16 / iOS 26.1), we captured two requests completely unrelated to the app’s business functionality and fully decrypted their contents.
① Dead Drop: Retrieving an Encrypted C2 Address List from a Public Code Hosting Site
GET hxxps://bitbucket[.]org/discordseven/text/raw/main/xxhVOn
The repository (bitbucket[.]org/discordseven/text) is public. Its README and .gitignore are both default Bitbucket templates and are only used for disguise. The repository was created on 2026-08-04, and the commit author’s email address is discdseven@outlook.com. The xxhVOn file is an encrypted list of C2 addresses:
By editing this single public file, the attacker can replace the C2 address for all affected devices without having to release a new version of the App.
② C2 Reporting: Encrypted Device Information and Remote Commands
The C2 domain assisaint[.]com was registered on 2026-09-12 (the exact day version 1.2 was listed), with Cloudflare as the registrar and the origin server concealed behind a fronting setup. CT logs also show another subdomain under the same domain, bp-a95010ced.assisaint[.]com (with a 90-day certificate issued by TrustAsia).
③ Decryption Results
The client uses CommonCrypto’s CCCrypt (alg = kCCAlgorithmAES(0), options = kCCOptionPKCS7Padding(1), i.e., AES-CBC + PKCS7) to encrypt the message body. By hooking this function, we obtained the session key for this communication session and decrypted the plaintext in both directions:
After decryption, the request body params contains device information reporting:
{"app_version":"1.0.5","app_pac":"com.fomopeek.app","app_uuid":"7A5475A0007346BCB6EDB30E43315999","timestamp":1789806193645,"machine":"iPhone 16","ios_version":"26.1"}
The decrypted data in the response contains remote commands:
{"version":"1.0.0","min_close_exploit_version":"","exploit_enabled":false,"exploit_repeat_enabled":false,"exploit_test":false,"app_log_report_enabled":false,"exploit_repeat_interval":86400}
Dynamic verification confirmed that all dead drop and C2 requests were sent by apptrace (with the multipart boundary prefix ---AppTraceBoundary), while the exploitation strategies, kernel read/write, Keychain decryption, and the service on port 40000 are all located in libapptracecore.
It should be noted that exploit_enabled was false both during this run and in the packet capture at 08:23 on 2026-09-19; however, the existence of this switch and its interval parameter indicates that the attacker can enable exploitation, adjust the execution interval, or forcibly disable it at any time through the server response, without updating the App. At the same time, the test virtual device’s self-reported profile (iPhone 16 / iOS 26.1) happened to fall within the coverage range of the DarkSwordStrategy (16.7–18.7.2 and 26.0–26.1) described in Section 3.3.
To verify “what happens after the switches are enabled,” we used Frida to modify exploit_enabled / exploit_repeat_enabled / exploit_test in the response to true in place within the decryption callback, and then observed the client’s behavior.
When the client retrieved the configuration again, in addition to the switch states, it also received a list of collection targets (collect_configs) — directly exposing the intent of this operation:
The collect_configs delivered by the C2 contains a total of 19 collection targets, almost all of which are wallet apps, including Gate Web3, SafePal, OKX Wallet, MetaMask, Trust Wallet, imToken, TokenPocket, TronLink, and others.
The collection paths are concentrated in keystore, SQLite, MMKV, React Native local storage, and Keychain access groups, and include the entire Apple Notes container group.com.apple.notes. These configurations indicate that the attack targets wallet key materials and other sensitive information stored by users, and that the collection scope can be dynamically adjusted by the server.
At this point, the malicious modules’ attack capabilities and the targeted collection targets delivered by the C2 form a complete chain of evidence.
After the collection was triggered, we captured a multipart request sent to /api/upload/zip. The params field contains AES-CBC-encrypted file metadata, while the file field contains a ZIP archive that is not additionally encrypted.
The decrypted metadata showed that the upload target was group.com.apple.notes, with an archive size of 46,092 bytes, along with the file MD5, device UUID, local path, and timestamp. The restored ZIP package contained NoteStore.sqlite, WAL files, and related configuration files, consistent with the structure of the Apple Notes container.
This confirms that the sample reads the target containers according to the list delivered by the C2, packages the results and temporarily stores them in its own sandbox, and then uploads them to /api/upload/zip.
We reconstructed the archive itself from this request, and the archive contents were the Apple Notes container:
group.com.apple.notes/NoteStore.sqlite 307,200
group.com.apple.notes/NoteStore.sqlite-shm 32,768
group.com.apple.notes/.com.apple.mobile_container_manager.metadata.plist 577
group.com.apple.notes/Library/Preferences/group.com.apple.notes.plist 127
group.com.apple.notes/NoteStore.sqlite-wal / com.apple.notes.databaseopen.lock
At this point, we verified the target container reading, file packaging, and data upload process in an isolated testing environment. Combined with the kernel exploitation, privilege escalation, and sandbox escape code in the framework, its designed execution chain can be reconstructed as: remote configuration delivery → kernel exploitation and privilege escalation → target data collection → packaging and upload.
In addition to the configuration delivery and data exfiltration endpoints, we also confirmed two supporting endpoints that together form a complete C2 protocol of “reconnaissance → command delivery → collection → reporting.”
① /api/device/apps: Reporting the Installed Application List
After decrypting the params section of this request using the same KEY/IV, we obtained a list of the bundle IDs of all 135 applications installed on the device:
{"app_uuid":"7A5475A0007346BCB6EDB30E43315999",
"apps":["com.apple.Home.HomeControlService","com.apple.CarCamera","com.debank.rabby-mobile-regression","com.apple.ScreenSharingViewService","com.okx.wallet", … a total of 135 entries …]}
The purpose of this list is straightforward: based on it, the server determines which wallets are installed on the device and then decides which collect_configs to deliver.
② /api/device/report: Execution Result Reporting and Subsequent Commands
③ Summary of Confirmed C2 Endpoints
The conclusions from the infrastructure investigation of the C2 domain itself are as follows:
The domain was registered recently and uses registration information privacy protection, Cloudflare reverse proxying, and rapid certificate deployment, which are common characteristics of short-term attack infrastructure. The domain registration date coincides with the FomoPeek 1.2 listing date and can serve as a temporal correlation clue, but the above public information is insufficient to determine the origin server location or the identity of the attacker.
When checking the public infrastructure of this domain, one of its subdomains can be seen to host a management interface named Collect. Its frontend routes include entries related to devices, applications, and keys (/machineApp, /machineApp/needBlast, /machineApp/walletAddress, /machineAppKeys, /machineStat, /mnemonic, /partner/account, /partner/home, /partner/machine/detail, etc.):
This indicates that the domain hosts not an ordinary business API, but an operational-side interface associated with device collection and key-related data; its specific functions and fields are not discussed in this article.
Through tracking and analysis of the collected on-chain data, it was found that the funds stolen by the attacker in this incident involved multiple chains, including TRON, Ethereum, and other EVM-compatible chains. This section focuses only on the analysis of the primary hacker address (0x6d37f2C5e8F8546b648D317295565dA95975f4BB).
According to MistTrack data, this address received a total of 579,984.34 USDT and became active starting September 15.
The address’s fund activity spans multiple chains, including Ethereum, BNB Chain, and Arbitrum, and funds were still continuously flowing into it as of the time of publication. Its current balance is as follows:
Most of the funds held by this address were consolidated on the Ethereum network. Funds on the other chains were mainly converted to USDT through cross-chain/swap platforms such as OKX DEX, Meson.fi, Relay.link, and Mayan Finance, and then bridged to Ethereum.
Subsequently, the address transferred the consolidated USDT in batches to the following downstream addresses:
(1) 0x0A571f0Fa18D7EB9abcc1e98a0Bb9bC15534BbAe
The address currently holds 24,352 USDT. Notably, this address became active as early as May 23, before the main attack window of this incident.
It has interacted with FixedFloat, cce.cash, OKX, and others:
In addition, a relatively large amount of 111,458 USDT was transferred to the address 0x4c73d7e8ef0e61129403e219debc597fd43aa0ec and then transferred into USDT0: UsdtOFT for cross-chain transfer.
The cross-chain receiving address is the TRON address TF2hm96RC2Aqon9FeQjGidofoC2J1zM8v1. This address has received a total of 2,123,570.8821 USDT, which was subsequently dispersed across multiple addresses and transferred to suspected OTC platforms.
(2) 0x0DF6aC2e2856114228756947d1b1d9Ff63eA3e68
The address has received a total of 159,000 USDT:
All funds were transferred to FixedFloat:
(3) 0x2d53113c89c83c520c17b8bbcdc22aa0518a38be
The address has received a total of 47,028 USDT:
Of this amount, 10,000 USDT was transferred to KuCoin, while the remaining 37,028 USDT was transferred to FixedFloat:
(4) 0x111faeb95cd0786593433bcc762dc5c1debf541c
The address has received a total of 227,154 USDT:
215,000 USDT was transferred to FixedFloat, and 10,000 USDT was transferred to cce.cash:
The remaining 2,154 USDT was converted via Bridgers Swap into 6,432.54 TRX and cross-chained to the TRON address TUi5qPcjDuqbmwfunMbzwkpLNhaqRpqcJg, with most of the TRX ultimately transferred to FixedFloat. Notably, a significant portion of the funds received by the TUi5q address came from cce.cash:
We will continue to monitor the fund movements of the above addresses. If you have ever installed FomoPeek and recently experienced asset theft, you can submit the stolen address and hacker address through the following link: https://aml.slowmist.com/cn/recovery-funds.html.
URL :
hxxps://api-a95f0ed200f.assisaint.com/api/device/config
hxxps://bp-a95010ced.assisaint.com
hxxps://admin-e433360cb0e.assisaint.com
hxxps://customer-c1cb36b5.assisaint.com
hxxps://bitbucket.org/discordseven/text/raw/main/xxhVOn
Domain:
assisaint[.]com
api-a95f0ed200f[.]assisaint.com
bp-a95010ced[.]assisaint.com
admin-e433360cb0e[.]assisaint.com
customer-c1cb36b5[.]assisaint.com
File:
FomoPeek-1.1–891048157.ipa
MD5: fce99b45709a6f8e241175be0c121874
SHA-256: d6b6407b4c97697fdde174cbc190b6433315470f58df6b483ac5b806f35e20f9
FomoPeek-1.1.ipa
MD5: f5bdaed5953033ac8c3256f2933b9a81
SHA-256: ca5dfd0fa7a16f26f5b369516f5b8bcac1d5a6fe01a8511a5ededf4cd2c0d042
FomoPeek-1.2.ipa
MD5: 38a8a5ddecd9a5626b42dae593ac28f6
SHA-256: 48f9d5623af1518e774d57c41e6e0b915a7e9f896909bf596a9b27de5022911e
apptrace
MD5: 645b9053390246995c2cb7a9b9eddf40
SHA-256: 764663ff5c8bd1bdf33bbd1ec352ce262a4fe79695456f2612dc27c35840ab9d
libapptracecore
MD5: 03d67a68b5e8507dbbe36f2a4b41aca0
SHA-256: f0b3be01e8597f7f35ca36c009f68e7004527fe4a01d4349a01e211ca16de1e2
If your device has ever installed FomoPeek version 1.1 or 1.2, please note: uninstalling the app or upgrading to 1.3 does not mean that the device is already secure. Once the framework has been successfully exploited, the data it accessed has already left the device.
1. Immediately stop using the app and do not reinstall it;
2. On a secure device that has never installed the app, create a new wallet, generate a completely new seed phrase, and transfer your assets; treat all old seed phrases and private keys as compromised and do not reuse them;
3. Check for abnormal transfers and authorization records across accounts on each chain, and revoke authorizations that are no longer in use;
4. Change the passwords and login credentials used on the device and enable two-factor authentication;
5. Check whether the device has installed any configuration profiles / MDM, or whether it has been sideloaded or jailbroken; if necessary, erase the device and reinstall the operating system;
6. Preserve the device and relevant evidence (App version, installation time, abnormal transaction records) for further investigation;
7. If you discover any abnormal asset activity, immediately contact the official customer support of the relevant platform.
1. Add file hashes, class names, key strings, and network characteristics to sample databases, EDR, and traffic detection rules;
2. Send targeted risk alerts to users who have installed FomoPeek 1.1 or 1.2, and handle the cases as credential exposure incidents;
3. Block assisaint[.]com and its subdomains, as well as bitbucket[.]org/discordseven/*;
4. Starting from September 9, 2026, review access logs for the Bitbucket dead drop, and starting from September 12, review DNS, proxy, EDR, VPN, and mobile device logs related to *.assisaint[.]com. If the log retention period allows, further trace back to August 4 to investigate access to the Bitbucket repository and historical C2 configurations.
Through static analysis and dynamic verification, we confirmed that FomoPeek 1.1 and 1.2 had two malicious modules, apptrace and libapptracecore, embedded in them, with capabilities including remote configuration, kernel exploitation, sandbox escape, Keychain decryption, and cross-application data collection.
After triggering the relevant functionality in an isolated environment, the sample obtained a collection list targeting 19 wallet and note-taking applications from the C2 and packaged and uploaded the Apple Notes container to /api/upload/zip, verifying the complete technical chain from remote configuration and unauthorized access to data exfiltration.
The above-mentioned modules were not found in FomoPeek 1.0, were first introduced in 1.1, remained in 1.2, and were completely removed in 1.3. For users who have used 1.1 or 1.2, uninstalling or upgrading the app alone cannot rule out the risk of historical data exposure. It is recommended to treat the relevant seed phrases, private keys, and sensitive credentials as compromised.
The currently confirmed risk window is from September 9 to September 17, 2026.
FomoPeek 1.0 was first listed on August 29, when no relevant malicious modules were found. Version 1.1, released on September 9, first introduced apptrace and libapptracecore, while version 1.2, released on September 12, continued to carry the same malicious code. It was not until version 1.3 was released on September 17 that the two Frameworks were completely removed.
On September 16, alerts had already appeared on public social platforms regarding users experiencing asset theft after installing FomoPeek. Since the installation time and asset theft time of not all victims can be fully obtained, it is currently impossible to determine the exact time when the earliest actual attack occurred based on this information alone.
In terms of App versions, the explicitly affected versions are FomoPeek 1.1 and 1.2.
Based on the iOS coverage declared in the attack framework’s code, it contains 8 built-in exploitation strategies covering iOS 12.0–18.7.2 and iOS 26.0–26.1, and selects the corresponding exploitation strategy based on the device model and system version.
It should be noted that FomoPeek’s App Store page specifies iOS 16.0+ as the system requirement. Therefore, the “theoretical coverage of the attack framework” and the “range of devices on which FomoPeek can actually be installed through the App Store” are not exactly the same concept.
In this FomoPeek incident, the confirmed distribution entry point was the official App Store version itself, rather than a third-party re-signed, enterprise-signed, or sideloaded package. The malicious Frameworks and the main program used the same Apple signing entity, and the original IPA also retained FairPlay encryption metadata.
FomoPeek mainly attracted users to install the App through crypto KOLs, communities, invitation codes, and small USDT rewards, and required users to run it on a real device for several minutes.
However, from the perspective of the attack technique itself, this type of iOS kernel exploitation is not necessarily limited to being hidden in a particular App. Similar capabilities could theoretically also be triggered through malicious or poisoned Apps, supply-chain components, phishing pages, compromised websites, and watering-hole pages deployed for specific groups.
The previously mentioned public alerts related to DarkSword also pointed out that attackers could potentially combine social engineering or watering-hole attacks to induce targets to visit websites or pages implanted with malicious code, thereby further stealing data from iPhones and iPads.
Therefore, do not simply assume that something is absolutely safe because it “comes from the App Store” or “comes from a website that is frequently visited.”
The idea behind a “Watering Hole Attack” is not to directly seek out every victim, but to first identify places that the target group frequently visits and trusts.
For example, if an attacker wants to target a group of cryptocurrency professionals, they may first analyze which industry websites, tool sites, communities, project websites, or event pages these people frequently visit, and then look for targets that can be compromised or implanted with malicious code.
Once these legitimate websites are compromised, victims may enter the attack chain simply by visiting the websites as they normally would.
The name comes from “watering holes” in nature: a predator does not need to chase every prey animal, but only needs to wait at places where animals frequently go to drink.
For mobile devices, this “watering hole” can also be understood as a broader trusted entry point: it could be a familiar website, a long-used App, a third-party SDK, a community link, or even an update to a legitimate application.
No.
What makes FomoPeek particularly noteworthy is not only whether a particular wallet user installed this specific App, but that it once again demonstrates that an attack entry point may be hidden in an application that appears completely legitimate, or even comes from an official app store.
Among publicly documented cases, ComeCome provides another notable example. Public analysis showed that this is a food delivery App targeting Chinese users in regions such as Dubai. Its version 2.9.3 was found to contain a hidden component named DKStatistics, with capabilities to escape the iOS sandbox and access data from wallet Apps, WhatsApp, Apple Notes, and other applications. Public pages also disclosed relevant on-chain fund flows. It should be noted that the website also explicitly distinguishes between “technical and on-chain facts that can be publicly verified” and the boundary of “attribution of the actual attacker, which cannot be directly established based on these facts.”
The takeaway from such cases is:
A “watering hole” does not necessarily look like a dangerous website. It could be a website, tool, food delivery App, community link, or even software downloaded from an official store that you open every day.
By the traditional definition, FomoPeek and ComeCome are more accurately described as App poisoning / trusted-channel poisoning rather than classic web-based Watering Hole attacks. However, the underlying attack approach is very similar: first enter an access point trusted and frequently used by the target group, and then wait for targets to voluntarily enter the attack environment.
Therefore, what really needs attention is not just FomoPeek. A watering hole may exist anywhere that is long-term trusted by the target group.
For reference, see the publicly available ComeCome case: https://comecome.icu/
MistEye is a Web3 threat intelligence and dynamic security monitoring platform independently developed by SlowMist. Through its API, it provides malicious activity detection and supply chain risk alerts for open-source package ecosystems.
All malicious packages and IOCs involved in this incident have been integrated into the MistEye threat detection engine. Developers can use the API to automatically scan project dependencies, quickly determine whether they match known malicious packages, and obtain mitigation recommendations.
📖 API Documentation: https://app.misteye.io/api-docs
🛠️ MistEye-DepScan: https://github.com/slowmist/MistEye-DepScan A lightweight CLI tool that scans project dependencies and globally installed packages for known malicious packages with a single command. It supports the npm / PyPI / Cargo / Go / RubyGems ecosystems.
🛠️ MistEye-Skills: https://github.com/slowmist/misteye-skills A security skills package for coding assistants that automatically triggers MistEye security checks before dependency installation and URL access.
🛠️ MistEye-DNS-Guard: https://github.com/slowmist/MistEye-DNS-Guard A DNS security protection tool that detects malicious domains and risky access, and identifies network threats such as phishing and C2.
This article was written by the SlowMist Threat Intelligence Team based on the MistEye threat intelligence system and SlowMist Agent’s AI-powered analysis. If you have any questions, please feel free to contact us for consultation or feedback.
SlowMist is a threat intelligence firm focused on blockchain security, established in January 2018. The firm was started by a team with over ten years of network security experience to become a global force. Our goal is to make the blockchain ecosystem as secure as possible for everyone. We are now a renowned international blockchain security firm that has worked on various well-known projects such as HashKey Exchange, OSL, MEEX, BGE, BTCBOX, Bitget, BHEX.SG, OKX, Binance, HTX, Amber Group, Crypto.com, etc.
SlowMist offers a variety of services that include but are not limited to security audits, threat information, defense deployment, security consultants, and other security-related services. We also offer AML (Anti-money laundering) software, MistEye (Security Monitoring), SlowMist Hacked (Crypto hack archives), FireWall.x (Smart contract firewall) and other SaaS products. We have partnerships with domestic and international firms such as Akamai, BitDefender, RC², TianJi Partners, IPIP, etc. Our extensive work in cryptocurrency crime investigations has been cited by international organizations and government bodies, including the United Nations Security Council and the United Nations Office on Drugs and Crime.
By delivering a comprehensive security solution customized to individual projects, we can identify risks and prevent them from occurring. Our team was able to find and publish several high-risk blockchain security flaws. By doing so, we could spread awareness and raise the security standards in the blockchain ecosystem.