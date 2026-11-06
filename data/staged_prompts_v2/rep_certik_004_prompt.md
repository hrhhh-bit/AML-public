# Prompt v2 — rep_certik_004

- vendor: CertiK
- title: JaredFromSubway MEV bot Incident Analysis - CertiK
- filename: rep_certik_004_jaredfromsubway-mev-bot-incident-analysis-certik.txt
- hops_detected: 4

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
hops_detected: 4
flow_markers: fund flow, tornado
This anchor is a signpost ONLY — the report body remains the single source of truth. Do NOT invent chains/relays beyond the evidence.
=== END ATTENTION ANCHOR ===

### TARGET JSON SCHEMA ###
{"title":"TwoPhaseDistillationPayload","type":"object","required":["phase_a_inflow_motifs","phase_b_outflow_motifs","grounded_chains"],"additionalProperties":false,"properties":{"grounded_chains":{"type":"array","minItems":1,"items":{"type":"string","minLength":1},"description":"Abstract chain labels actually grounded in the report evidence (e.g. ['Chain_A', 'Chain_B']). Every `chain` used by ANY node in EITHER phase MUST appear here; the number of distinct chains used by the motifs must NEVER exceed the number of chains declared here."},"phase_a_inflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-in / consolidation / first-hop / cross-chain ENTRY motifs (funds flowing INTO the laundering structure)."},"phase_b_outflow_motifs":{"type":"array","items":{"$defs":{"AbstractEdge":{"additionalProperties":false,"description":"A directed abstract operation edge between two motif-local nodes.\n\n``flow_share`` is STRICTLY the local out-degree distribution ratio of the\nedge's SOURCE node: for every node :math:`u`,\n:math:`\\sum_{e \\in Out(u)} flow\\_share(e) = 1.0 \\pm 0.01`.  A single\nout-edge therefore always carries ``1.0`` (the node forwards 100% of the\nflow).  In-flow weights of a downstream merge target must NEVER be\nwritten onto upstream edges.  Pure relative prior: no absolute amounts\nallowed.","properties":{"source":{"minLength":1,"title":"Source","type":"string"},"target":{"minLength":1,"title":"Target","type":"string"},"operation":{"$ref":"#/$defs/OperationType"},"flow_share":{"default":1.0,"description":"Normalised flow share in (0.0, 1.0]; relative prior only.","exclusiveMinimum":0.0,"maximum":1.0,"title":"Flow Share","type":"number"}},"required":["source","target","operation"],"title":"AbstractEdge","type":"object"},"AbstractNode":{"additionalProperties":false,"description":"A single abstract vertex of a motif. Frozen so it can be hashed.","properties":{"temp_id":{"description":"Motif-local node identifier, e.g. 'S', 'AC1'.","minLength":1,"title":"Temp Id","type":"string"},"role":{"$ref":"#/$defs/NodeRole"},"chain":{"description":"Abstract chain label, e.g. 'Chain_A'.","minLength":1,"title":"Chain","type":"string"},"level":{"description":"DAG step level (0 = source level).","minimum":0,"title":"Level","type":"integer"}},"required":["temp_id","role","chain","level"],"title":"AbstractNode","type":"object"},"MotifConstraints":{"additionalProperties":false,"description":"Constraint Layer: hard structural limits for DAG generation.","properties":{"max_branching_factor":{"default":4,"description":"Maximum out-degree (branching factor) :math:`d_{max}` enforced inside the motif.","minimum":1,"title":"Max Branching Factor","type":"integer"},"min_level_bound":{"default":2,"description":"Global step interval lower bound :math:`L_{min}`.","minimum":1,"title":"Min Level Bound","type":"integer"},"max_level_bound":{"default":8,"description":"Global step interval upper bound :math:`L_{max}`.","minimum":1,"title":"Max Level Bound","type":"integer"},"require_acyclic":{"default":true,"description":"Whether the motif DAG must be acyclic (always True in production; exists for schema completeness).","title":"Require Acyclic","type":"boolean"}},"title":"MotifConstraints","type":"object"},"NodeRole":{"description":"Abstract node roles of the behavioral graph :math:`V_{abstract}`.","enum":["Source","Intermediate","Asset_Conversion","Cross_Chain","Aggregator","Target"],"title":"NodeRole","type":"string"},"OperationType":{"description":"Abstract edge operations :math:`E_{abstract}`.\n\nCase-insensitive parsing is enabled via :meth:`_missing_` so that\n``\"bridge\"`` / ``\"BRIDGE\"`` resolve to :attr:`BRIDGE` defensively.","enum":["Transfer","Swap","Bridge","Split","Merge"],"title":"OperationType","type":"string"},"PatternType":{"description":"High-level AML tactic vocabularies (Tactic Layer).","enum":["Peeling_Chain","Chain_Hopping","Multi_Layering_Split","Token_Obfuscation","Integration_Merge"],"title":"PatternType","type":"string"},"PostStateEffect":{"additionalProperties":false,"description":"Expected state transition after applying the motif.","properties":{"branch_increment":{"default":0,"description":"Net change in active branch count after expansion. Positive = branching (split), negative = convergence (merge).","title":"Branch Increment","type":"integer"},"chain_transition":{"default":false,"description":"Whether the motif triggers a cross-chain state transition.","title":"Chain Transition","type":"boolean"},"target_chain":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Target chain after transition (recommended when chain_transition=True).","title":"Target Chain"},"next_recommended_roles":{"default":[],"description":"Recommended node roles for the next agent action.","items":{"$ref":"#/$defs/NodeRole"},"title":"Next Recommended Roles","type":"array"}},"title":"PostStateEffect","type":"object"},"Preconditions":{"additionalProperties":false,"description":"Hard trigger conditions of a motif.\n\n``None``-valued fields mean *unconstrained*.  A motif is applicable only\nwhen the current :class:`CurrentState` satisfies **all** non-null fields.","properties":{"min_level":{"default":0,"description":"Minimum global DAG level required to trigger the motif.","minimum":0,"title":"Min Level","type":"integer"},"allowed_node_roles":{"anyOf":[{"items":{"$ref":"#/$defs/NodeRole"},"type":"array"},{"type":"null"}],"default":null,"description":"Applicable active node roles: at least one current active role must overlap this set (multi-role frontiers are the norm). None = no restriction.","title":"Allowed Node Roles"},"required_chains":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Current chain must belong to this set. None = no restriction.","title":"Required Chains"},"max_active_branches":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"description":"Maximum number of active (frontier) nodes allowed. None = no restriction.","title":"Max Active Branches"}},"title":"Preconditions","type":"object"}},"additionalProperties":false,"description":"Canonical DAG pattern :math:`g_{motif} = (V_{abstract}, E_{abstract})`.\n\nStructural invariants are validated at construction time:\n\n1. every edge endpoint references an existing ``temp_id``;\n2. ``temp_id`` values are unique and self-loops are forbidden;\n3. every edge advances strictly to a higher DAG level (guarantees a\n   topological order, hence DAG-acyclicity is enforced by a Kahn check);\n4. no node out-degree exceeds ``constraints.max_branching_factor``.","properties":{"motif_id":{"description":"Globally unique motif identifier.","minLength":1,"title":"Motif Id","type":"string"},"pattern_type":{"$ref":"#/$defs/PatternType"},"description":{"description":"Human-readable abstract description (no micro numbers).","minLength":1,"title":"Description","type":"string"},"preconditions":{"$ref":"#/$defs/Preconditions"},"nodes":{"items":{"$ref":"#/$defs/AbstractNode"},"minItems":1,"title":"Nodes","type":"array"},"edges":{"items":{"$ref":"#/$defs/AbstractEdge"},"title":"Edges","type":"array"},"post_state_effect":{"$ref":"#/$defs/PostStateEffect"},"constraints":{"$ref":"#/$defs/MotifConstraints"},"tags":{"default":[],"description":"Optional semantic tags used by the dense retriever.","items":{"type":"string"},"title":"Tags","type":"array"},"applicable_scale_tiers":{"default":[],"description":"Macro fund-volume tiers this motif applies to (e.g. 'Whale'). Strings kept in aml_rag to avoid an upward dependency on the agent layer; valid values mirror ScaleTier.","items":{"type":"string"},"title":"Applicable Scale Tiers","type":"array"}},"required":["motif_id","pattern_type","description","nodes"],"title":"TopologicalMotif","type":"object"},"description":"Fan-out / dispersal / DEX swap / OTC cash-out / EXIT motifs (funds leaving the structure toward sinks)."}}}

### REPORT SEGMENT ###
Incident Summary
On 20 June 2026, the JaredFromSubway MEV bot lost 4,424 ETH (~$7.5M) due to an approval hijacking flaw. The attacker deployed fake arbitrage pools and bait tokens that appeared to offer profitable trading opportunities, causing the bot’s automated strategy to interact with malicious contracts and grant token approvals.
The core issue was that these approvals were not fully consumed or revoked after execution. As a result, the attacker was able to activate the bait contracts and use the remaining allowances to drain the bot’s WETH, USDC, and USDT reserves.Background
Background
Jaredfromsubway.eth is a MEV (Maximal Extractable Value) bot, meaning an automated program that monitors pending transactions on the blockchain and reorders their execution to capture a profit. Its specialty is the sandwich attack, which consists of front-running and back-running a user's transaction with two of the bot's own orders to profit from the price difference.
When a user submits a swap on a decentralized exchange, the transaction may become visible before it is included on-chain. MEV bots monitor this flow, simulate the impact of pending trades on liquidity pools, and identify opportunities where a user’s transaction is likely to move the price of an asset.
Key Addresses
Attack Flow
Preparation:
- So to entice MEV bots, one would need set-up imbalanced pools with some real assets in it Attacker deployed several helper contracts that is used to set up such traps:
- 0x81f248ff583d3f8592ea0354a7b8dbe66de40091 for deploying fake tokens
- 0xb84db016324e8F2BFdD8DD9c260338AEE0A8DF52 for coordinating token status and profit extraction
- 0xEEE172A069f5171b407eBf47e8FCFB637E944ec2 for creating fake pools
- 0x4dE8C729A064Ff6087Cc84A4152969349e4FEb98 for conducting swaps
- Deploying 131 fake token contracts as bait through method 0x9045f3f9() (txn) These bait contracts appear in the form of restaked WETH/USDC tokens. That you get exactly 1 such token for 1 WETH/USDC wrapTo() it, the wrapTo() method requires approvals to call but is binded by the coordinate contract.
i) When ‘owner_a_0_19’ is not set up, wrapTo() called _safeTransferFrom() and the allowance was consumed.
ii) After ‘owner_a_0_19’ is set up (to coordinator contract), getStatus() returns _getStatus == block.number. iii) If _getStatus is not up to blocknumber, then setStor3 is called to remind attacker that _getStatus should be reset. iv) If _getStatus is up to blocknumber and status == 1, wrapTo() skipped transferFrom — the allowance was not consumed; the amount is also updated in the coordinator to keep track of newly acquired allowances.
- Set up fake LPs (txn), some are seeded (txn) with WETH-fCAP and some with fWETH-fCAP. Then make calibrating swaps to create imbalance.
Exploit:
- At block 25354425 (txn), jaredfromsubway.eth took the bait in its first interaction with SwapV2Pair_0x0e97. When assuming 1 fWETH = 1 WETH, the token balances on the two fake SwapV2Pairs present an arbitrage opportunity in swap route fWETH->fCAP->WETH:
- SwapV2Pair_0x0e97: 0.1 fWETH, 0.1 fCAP
- SwapV2Pair_0xc12a: 0.086034434021378528 fCAP, 0.116281374898538093 WETH The MEV bot approved and wrapped 7,391,033,126,027,264 WETH to the bait, which in turn minted the same amount to SwapV2Pair_0x0e97. It then swapped out 6,863,125,844,328,448 wei fCAP for 8,566,811,964,473,344 wei WETH. The MEV bot netted 0.002351557676892158 WETH; the approval is properly spent normally as status coordinator ‘owner_a_0_19’ hasn’t been set.
- Wait patiently for nearly a day, as MEV builds trust for the setup. Attacker set up (txn) the ‘owner_a_0_19’ for the bait tokens to coordinator. Starting from block 25360428, the attacker calls markStatusAndTip() (txn) with some bribe to frontrun Jared and set ‘_getStatus’ to block.number. The ensuing wrapTo() (txn) during MEV arbitrage would not cost the allowance.
- Wait for the MEV to conduct more swaps to accumulate unrevoked approvals. It didn’t take long as it seems MEV fully trusts the set-up now and grews greedy by conducting hundreds of swaps per txn, In fact the attacker only conducted a dozen ‘_getStatus’ updates / 0xb6e808af() to get the allowance it needed. Then at blockheight 25360696, activate 66 approval bait contracts (txn), 60 of which have approval of the target MEV Bot, and transfer funds to the attacker.
Vulnerability
The arbitrage bot approves wrapper contracts to spend its tokens for wrapTo() operations, assuming the allowance is fully consumed. However, the bot never verifies this consumption or revokes unspent allowances. If a wrapper avoids calling transferFrom, this lingering approval creates a persistent vulnerability, allowing it to drain the bot's funds.
Fund Flow
The attacker 0x3e37f4A10d771Ba9dE44b6d301410b1BEdeA65d0 was able to drained 2,869,812.43 USDC, 2,032,769.62 USDT, and 1,474 wETH ($2,567,708) then swapped all the stablecoins for ETH.
The funds were then sent to these 5 addresses:
- 0x5aF38735B215b00aa7C9f93fEd7ee415CeCB36e1
- 0x71d4416A7A85e08a5Fe7227Ca3B44Fc639e94e97
- 0x74Dc5b93586D248D5Aec64b3586736FF0A0D0e65
- 0xe3Da36E4bd1a5738fa5D6Ef4F0e4dF40bDeB5f17
- 0xd8C125efCBc99408eC8723E9BBd81d1E8D39D845 Finally, the attacker deposited 3,000 ETH into Tornado Cash and swapped 1,422 ETH for ~$2.44M in DAI, which is still in wallet 0x7B4F24a4522bc2AEE9D1686FFB7d6c9dAC514e20.
To keep up to date on the latest incident alerts and statistics, follow @certikalert on X, or read our latest analysis on certik.com.