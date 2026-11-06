# Prompt v2 — rep_certik_008

- vendor: CertiK
- title: SOF/LAXO Incident Analysis - CertiK
- filename: rep_certik_008_sof-laxo-incident-analysis-certik.txt
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
flow_markers: fund flow, tornado
This anchor is a signpost ONLY — the report body remains the single source of truth. Do NOT invent chains/relays beyond the evidence.
=== END ATTENTION ANCHOR ===

### TARGET JSON SCHEMA ###
{"title":"TwoPhaseDistillationPayload","type":"object","required":["phase_a_inflow_motifs","phase_b_outflow_motifs","grounded_chains"],"additionalProperties":false,"properties":{"grounded_chains":{"type":"array","minItems":1,"items":{"type":"string","minLength":1},"description":"Abstract chain labels actually grounded in the report evidence (e.g. ['Chain_A', 'Chain_B']). Every `chain` used by ANY node in EITHER phase MUST appear here; the number of distinct chains used by the motifs must NEVER exceed the number of chains declared here."},"phase_a_inflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-in / consolidation / first-hop / cross-chain ENTRY motifs (funds flowing INTO the laundering structure)."},"phase_b_outflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-out / dispersal / DEX swap / OTC cash-out / EXIT motifs (funds leaving the structure toward sinks)."}}}

### REPORT SEGMENT ###
Incident Summary
In February 2026 two separate exploits occurred on the BNB Smart Chain (BSC), affecting SOF and LAXO tokens, leveraging the same class of vulnerability: a flawed token burn mechanism that allowed price manipulation within a single transaction.
SOF token was exploited on 14 February 2026 for 190,540.
Both attacks follow a similar playbook: an attacker used a flash loan to acquire a large portion of the token supply, sold it into the pool and exploited an inflated price to extract more BSC-USD than was originally invested.
Attack Flow
Addresses:
Exploiter:
- SOF Exploiter: 0x29e5F70ebab2B5b830609E0f2b8A357F2295EBfD
- LAXO Exploiter 1: 0x17f9132E66A78b93195b4B186702Ad18Fdcd6E3D
- LAXO Exploiter 2: 0xBe5424Ac3FB767A5d4586aB46d9A45Ce8eD03FEB
- LAXO Exploiter 3: 0x127Ad42933819e508103DEa135f681b36961BD3A
Victims:
- SOF token: 0xaeB414d0a64DFCA14fd41B28EfC78f437008dF42
- LAXO token: 0x62951CaD7659393BF07fbe790cF898A3B6d317CB
SOF Token Step by Step Event Flow:
2026-02-14 08:35:03 - Txn
- Precursor - Claim 875 SOF tokens in mining rewards from purchasing miners.
2026-02-14 08:45:28 - Txn
- The attacker executed multiple flash loans totalling over $590M in assets while also transferring the 875 SOF tokens previously accumulated through legitimate SOF mining activity to attack contract 0xc4DB5Bc25B502a366903E93E2229e1386EF9Dd3F.
- The attacker swapped 313,567,718 BSC-USD for 991,223 SOF tokens. This swap directed the SOF tokens to the SOMining contract rather than to the attacker directly as the mining contract is exempt from fees. This step left the pool with only 787 SOF tokens remaining, while loaded with 313,816,344 BSC-USD.
- The attacker then sold the 875 SOF mining rewards into the pool. Due to SOF's sell fee mechanism, after fee deductions, an effective 787 SOF was swapped into the pool — matching exactly the remaining. The SOF burn occurs and is then synced BEFORE the BSC-USD return is calculated. As a result the pool price for SOF is inflated at the moment of the price calculation. 875 SOF — worth a few hundred dollars at market price — was exchanged for the entire BSC-USD pool balance of 313,816,344.
- Repaid all flash loans including fees, keeping 225,936 BSC-USD as profit.
LAXO Token Step by Step Event Flow:
2026-02-22 15:32:44 - First Exploiter Txn
- First exploiter borrowed 350,000 BSC-USD via a flash loan.
- Swapped the 350,000 BSC-USD for 43,238,694 LAXO tokens. These tokens were sent to the PancakeSwap router, again exempt from fees.
- The attacker added minimal liquidity (0.0001 BNB + 0.00000000000001 LAXO) then immediately removed it. During the removal, the router transfers its entire LAXO balance (the 43M LAXO from step 2) to the attacker, which avoids a fee on swapping direct.
- The attacker transferred 52,057,043 LAXO to the PancakeSwap pool and triggered a swap. The contract automatically caps the transfer amount as the attacker’s balance. After a sell fee of 2,161,718 LAXO was transferred to the LAXO contract, 41,072,653 LAXO was burned. The pool then called sync() to update balances before calculating the BSC-USD swap output. With over 41M LAXO burned, the pool's LAXO balance decreased from ~54M to ~13M, while the BSC-USD balance remained the same — inflating the implied price per LAXO.
- Repay 350,175 BSC-USD (principal + fee) and keep 137,320 BSC-USD profit.
Copycat Exploits:
After this first transaction, two additional exploiters (Exploiter 2 and Exploiter 3) identified the same vulnerability and executed their own versions of the attack within 13 minutes:
- Transaction 2 (15:35:55 UTC): Exploiter 1 ran a second attack, extracting an additional 45,061 BSC-USD.
- Exploiter 2 (15:45:11 UTC): Executed the same exploit, netting 6,974 BSC-USD.
- Exploiter 3 (15:45:49 UTC): Gained 1,185 BSC-USD but after paying a 949 BSC-USD MEV bribe, was left with a net gain of only $236.
Vulnerability
Both exploits share the exact same root cause: a burn-before-sync architecture that allows any user to artificially inflate the token's price within a single transaction.
SOF — update() Function
In the SOF contract, the _update() function processes the sell by burning (amount - taxAmount) tokens and then calls sync(). The sync() function updates the pool's internal balance record to reflect the post-burn supply. Since the BSC-USD return calculation happens after sync(), the pool now believes there are far fewer SOF tokens than before, and thus prices each remaining SOF at a far higher USD value. LAXO — Burn in Transfer to Pair
For LAXO, the flaw is triggered when the Uniswap/PancakeSwap pool address is the recipient of a transfer. The token contract:
- caps the transfer amount at (balanceOf[sender] * 9999) / 10000;
- deducts a sell fee;
- burns the remainder;
- calls sync() all before the pool calculates how much BSC-USD to return.
The result is identical: the attacker can burn a massive amount of LAXO supply and receive BSC-USD at the post-burn, artificially inflated price.
Fund Flow
The SOF attacker moved funds rapidly after the exploit:
- ~$213,617 BSC-USD was deposited to FixedFloat across 10 transactions within 30 minutes of the exploit.
- 20 BNB (2 x 10 BNB) was sent to Tornado Cash
LAXO first exploiter funds remain in contract 0x6de0499e347f07582505930498D01A68b8D7ffa5 as of February 23, 2026.
Second exploiter funds remain in wallet 0xBe5424Ac3FB767A5d4586aB46d9A45Ce8eD03FEB as of February 23, 2026
To keep up to date on the latest incident alerts and statistics follow @certikalert on X, or read our latest analysis on certik.com.