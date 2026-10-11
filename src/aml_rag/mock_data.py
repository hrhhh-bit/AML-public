"""Curated seed database of canonical AML topological motifs.

Every motif obeys the *zero micro-numerical noise* rule: no addresses,
amounts, gas or timestamps — only abstract roles, chains, DAG levels and
operations.

The seed set covers the six mandatory families required by the data
contract plus six production-grade extensions (12 motifs in total):

1.  ``Peeling_Chain_Single_Chain``      (Peeling_Chain)
2.  ``Cross_Chain_Swap_Bridge``         (Chain_Hopping)
3.  ``Multi_Split_Obfuscation``         (Multi_Layering_Split)
4.  ``Multi_Chain_Hop_Layering``        (Chain_Hopping)
5.  ``Aggregation_Merge_To_Target``     (Integration_Merge)
6.  ``DEX_Liquidity_Pool_Swap``         (Token_Obfuscation)
7.  ``Peeling_Chain_Multi_Layer``       (Peeling_Chain)
8.  ``Cross_Chain_Bridge_And_Back``     (Chain_Hopping)
9.  ``Mixer_Anonymization_Split_Merge`` (Token_Obfuscation)
10. ``Single_Chain_Multi_Swap_Layering``(Token_Obfuscation)
11. ``Cross_Chain_Layered_Integration`` (Integration_Merge)
12. ``Multi_Split_Cross_Chain_Bridge``  (Multi_Layering_Split)
"""

from __future__ import annotations

from .schema import (
    AbstractEdge,
    AbstractNode,
    MotifConstraints,
    NodeRole,
    OperationType,
    PatternType,
    PostStateEffect,
    Preconditions,
    TopologicalMotif,
)

__all__ = ["build_seed_motifs", "SEED_MOTIFS"]

# Chain vocabulary shared by all seed motifs (pure abstraction, no chain ids).
CHAIN_A = "Chain_A"
CHAIN_B = "Chain_B"
CHAIN_C = "Chain_C"


# ---------------------------------------------------------------------------
# Compact constructors (keep the seed table readable & audit-friendly)
# ---------------------------------------------------------------------------
def _n(temp_id: str, role: NodeRole, chain: str, level: int) -> AbstractNode:
    return AbstractNode(temp_id=temp_id, role=role, chain=chain, level=level)


def _e(
    source: str, target: str, operation: OperationType, flow_share: float = 1.0
) -> AbstractEdge:
    return AbstractEdge(
        source=source, target=target, operation=operation, flow_share=flow_share
    )


def build_seed_motifs() -> list[TopologicalMotif]:
    """Return the production seed motif list (validated by Pydantic)."""

    T = OperationType.TRANSFER
    S = OperationType.SWAP
    B = OperationType.BRIDGE
    P = OperationType.SPLIT
    M = OperationType.MERGE

    R_SRC = NodeRole.SOURCE
    R_INT = NodeRole.INTERMEDIATE
    R_AC = NodeRole.ASSET_CONVERSION
    R_CC = NodeRole.CROSS_CHAIN
    R_AGG = NodeRole.AGGREGATOR
    R_TGT = NodeRole.TARGET

    return [
        # 1 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="Peeling_Chain_Single_Chain",
            pattern_type=PatternType.PEELING_CHAIN,
            description=(
                "Rapid linear peeled transfers along a single chain: funds hop "
                "through a short chain of fresh intermediate wallets before "
                "reaching the final target."
            ),
            preconditions=Preconditions(
                min_level=0,
                allowed_node_roles=[R_SRC, R_INT],
                max_active_branches=1,
            ),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("I1", R_INT, CHAIN_A, 1),
                _n("I2", R_INT, CHAIN_A, 2),
                _n("T", R_TGT, CHAIN_A, 3),
            ],
            edges=[
                _e("S", "I1", T),
                _e("I1", "I2", T),
                _e("I2", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=0,
                chain_transition=False,
                next_recommended_roles=(R_INT, R_TGT),
            ),
            tags=("linear", "single_chain", "rapid", "peeling"),
        ),
        # 2 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="Cross_Chain_Swap_Bridge",
            pattern_type=PatternType.CHAIN_HOPPING,
            description=(
                "Swap volatile assets into a stablecoin on the origin chain, "
                "then bridge the proceeds to a target chain before final "
                "transfer to the destination wallet."
            ),
            preconditions=Preconditions(
                min_level=1,
                allowed_node_roles=[R_SRC, R_AC],
                max_active_branches=2,
            ),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("AC", R_AC, CHAIN_A, 1),
                _n("I", R_INT, CHAIN_A, 2),
                _n("CC", R_CC, CHAIN_B, 3),
                _n("T", R_TGT, CHAIN_B, 4),
            ],
            edges=[
                _e("S", "AC", T),
                _e("AC", "I", S),
                _e("I", "CC", B),
                _e("CC", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=0,
                chain_transition=True,
                target_chain=CHAIN_B,
                next_recommended_roles=(R_CC, R_TGT),
            ),
            tags=("swap", "stablecoin", "bridge", "cross_chain"),
        ),
        # 3 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="Multi_Split_Obfuscation",
            pattern_type=PatternType.MULTI_LAYERING_SPLIT,
            description=(
                "One-to-N splitting: the source fans funds out into multiple "
                "parallel intermediate nodes on the same chain, which later "
                "converge into an aggregator before the final target."
            ),
            preconditions=Preconditions(
                min_level=1,
                allowed_node_roles=[R_SRC, R_INT],
                max_active_branches=4,
            ),
            constraints=MotifConstraints(max_branching_factor=3),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("I1", R_INT, CHAIN_A, 1),
                _n("I2", R_INT, CHAIN_A, 1),
                _n("I3", R_INT, CHAIN_A, 1),
                _n("AGG", R_AGG, CHAIN_A, 2),
                _n("T", R_TGT, CHAIN_A, 3),
            ],
            edges=[
                # asymmetric split: dominant trunk + smaller peel streams
                _e("S", "I1", P, 0.60),
                _e("S", "I2", P, 0.25),
                _e("S", "I3", P, 0.15),
                # converging merge: each stream forwards 100% of its flow
                _e("I1", "AGG", M),
                _e("I2", "AGG", M),
                _e("I3", "AGG", M),
                _e("AGG", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=3,
                chain_transition=False,
                next_recommended_roles=(R_AGG, R_TGT),
            ),
            tags=("fan_out", "obfuscation", "1_to_N", "split"),
        ),
        # 4 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="Multi_Chain_Hop_Layering",
            pattern_type=PatternType.CHAIN_HOPPING,
            description=(
                "Layered chain hopping across three distinct chains: funds "
                "bridge from chain A to chain B, then immediately bridge again "
                "to chain C, where they are finally transferred to the target."
            ),
            preconditions=Preconditions(
                min_level=2,
                allowed_node_roles=[R_SRC, R_CC],
                required_chains=[CHAIN_A],
                max_active_branches=2,
            ),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("CC1", R_CC, CHAIN_B, 1),
                _n("CC2", R_CC, CHAIN_C, 2),
                _n("T", R_TGT, CHAIN_C, 3),
            ],
            edges=[
                _e("S", "CC1", B),
                _e("CC1", "CC2", B),
                _e("CC2", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=0,
                chain_transition=True,
                target_chain=CHAIN_C,
                next_recommended_roles=(R_CC, R_TGT),
            ),
            tags=("chain_hop", "multi_chain", "bridge", "layering"),
        ),
        # 5 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="Aggregation_Merge_To_Target",
            pattern_type=PatternType.INTEGRATION_MERGE,
            description=(
                "N-to-1 integration: several source streams merge into a "
                "single aggregator node, which then transfers the consolidated "
                "funds to the final target."
            ),
            preconditions=Preconditions(
                min_level=1,
                allowed_node_roles=[R_SRC, R_INT],
                max_active_branches=6,
            ),
            constraints=MotifConstraints(max_branching_factor=3),
            nodes=[
                _n("S1", R_SRC, CHAIN_A, 0),
                _n("S2", R_SRC, CHAIN_A, 0),
                _n("S3", R_SRC, CHAIN_A, 0),
                _n("AGG", R_AGG, CHAIN_A, 1),
                _n("T", R_TGT, CHAIN_A, 2),
            ],
            edges=[
                _e("S1", "AGG", M),
                _e("S2", "AGG", M),
                _e("S3", "AGG", M),
                _e("AGG", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=-3,
                chain_transition=False,
                next_recommended_roles=(R_TGT,),
            ),
            tags=("fan_in", "integration", "N_to_1", "merge"),
        ),
        # 6 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="DEX_Liquidity_Pool_Swap",
            pattern_type=PatternType.TOKEN_OBFUSCATION,
            description=(
                "Asset conversion through a decentralized exchange liquidity "
                "pool: funds are transferred into a swap node and converted "
                "into a different asset before reaching the target."
            ),
            preconditions=Preconditions(
                min_level=0,
                allowed_node_roles=[R_SRC, R_AC],
                max_active_branches=1,
            ),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("AC", R_AC, CHAIN_A, 1),
                _n("T", R_TGT, CHAIN_A, 2),
            ],
            edges=[
                _e("S", "AC", T),
                _e("AC", "T", S),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=0,
                chain_transition=False,
                next_recommended_roles=(R_TGT,),
            ),
            tags=("dex", "liquidity_pool", "swap", "single_chain"),
        ),
        # 7 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="Peeling_Chain_Multi_Layer",
            pattern_type=PatternType.PEELING_CHAIN,
            description=(
                "Deep layered peeling chain: a long sequence of linear hops "
                "through intermediate wallets on one chain, maximising the "
                "number of hops before reaching the target."
            ),
            preconditions=Preconditions(
                min_level=2,
                allowed_node_roles=[R_INT],
                max_active_branches=1,
            ),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("I1", R_INT, CHAIN_A, 1),
                _n("I2", R_INT, CHAIN_A, 2),
                _n("I3", R_INT, CHAIN_A, 3),
                _n("I4", R_INT, CHAIN_A, 4),
                _n("I5", R_INT, CHAIN_A, 5),
                _n("T", R_TGT, CHAIN_A, 6),
            ],
            edges=[
                _e("S", "I1", T),
                _e("I1", "I2", T),
                _e("I2", "I3", T),
                _e("I3", "I4", T),
                _e("I4", "I5", T),
                _e("I5", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=0,
                chain_transition=False,
                next_recommended_roles=(R_INT, R_TGT),
            ),
            tags=("linear", "deep_layering", "single_chain", "peeling"),
        ),
        # 8 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="Cross_Chain_Bridge_And_Back",
            pattern_type=PatternType.CHAIN_HOPPING,
            description=(
                "Round-trip bridging: funds leave the origin chain through a "
                "bridge, pass through an intermediate chain, and are bridged "
                "back to the origin chain before final settlement."
            ),
            preconditions=Preconditions(
                min_level=3,
                allowed_node_roles=[R_SRC, R_CC],
                required_chains=[CHAIN_A],
                max_active_branches=2,
            ),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("CC1", R_CC, CHAIN_B, 1),
                _n("CC2", R_CC, CHAIN_A, 2),
                _n("T", R_TGT, CHAIN_A, 3),
            ],
            edges=[
                _e("S", "CC1", B),
                _e("CC1", "CC2", B),
                _e("CC2", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=0,
                chain_transition=True,
                target_chain=CHAIN_A,
                next_recommended_roles=(R_TGT,),
            ),
            tags=("round_trip", "bridge", "return_to_origin", "chain_hop"),
        ),
        # 9 ---------------------------------------------------------------
        TopologicalMotif(
            motif_id="Mixer_Anonymization_Split_Merge",
            pattern_type=PatternType.TOKEN_OBFUSCATION,
            description=(
                "Mixer-style anonymisation: funds are swapped through an "
                "asset-conversion node, split into parallel streams, and "
                "merged back into an aggregator before the final target."
            ),
            preconditions=Preconditions(
                min_level=2,
                allowed_node_roles=[R_SRC, R_AC, R_INT],
                max_active_branches=5,
            ),
            constraints=MotifConstraints(max_branching_factor=2),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("AC", R_AC, CHAIN_A, 1),
                _n("I1", R_INT, CHAIN_A, 2),
                _n("I2", R_INT, CHAIN_A, 2),
                _n("AGG", R_AGG, CHAIN_A, 3),
                _n("T", R_TGT, CHAIN_A, 4),
            ],
            edges=[
                _e("S", "AC", T),
                # equal-slice anonymisation split (symmetric prototype)
                _e("AC", "I1", P, 0.50),
                _e("AC", "I2", P, 0.50),
                _e("I1", "AGG", M),
                _e("I2", "AGG", M),
                _e("AGG", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=0,
                chain_transition=False,
                next_recommended_roles=(R_TGT,),
            ),
            tags=("mixer", "anonymization", "split", "merge"),
        ),
        # 10 --------------------------------------------------------------
        TopologicalMotif(
            motif_id="Single_Chain_Multi_Swap_Layering",
            pattern_type=PatternType.TOKEN_OBFUSCATION,
            description=(
                "Repeated same-chain asset conversions: funds are swapped "
                "through multiple conversion nodes in sequence to obfuscate "
                "the asset trail before the final transfer."
            ),
            preconditions=Preconditions(
                min_level=1,
                allowed_node_roles=[R_SRC, R_AC],
                max_active_branches=2,
            ),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("AC1", R_AC, CHAIN_A, 1),
                _n("AC2", R_AC, CHAIN_A, 2),
                _n("T", R_TGT, CHAIN_A, 3),
            ],
            edges=[
                _e("S", "AC1", T),
                _e("AC1", "AC2", S),
                _e("AC2", "T", S),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=0,
                chain_transition=False,
                next_recommended_roles=(R_TGT,),
            ),
            tags=("swap", "layering", "single_chain", "token_obfuscation"),
        ),
        # 11 --------------------------------------------------------------
        TopologicalMotif(
            motif_id="Cross_Chain_Layered_Integration",
            pattern_type=PatternType.INTEGRATION_MERGE,
            description=(
                "Cross-chain layered integration: two source streams merge on "
                "the origin chain and are bridged to the target chain, where "
                "they merge again with a local stream before settlement."
            ),
            preconditions=Preconditions(
                min_level=3,
                allowed_node_roles=[R_SRC, R_INT, R_CC],
                max_active_branches=6,
            ),
            nodes=[
                _n("S1", R_SRC, CHAIN_A, 0),
                _n("S2", R_SRC, CHAIN_A, 0),
                _n("AGG1", R_AGG, CHAIN_A, 1),
                _n("CC", R_CC, CHAIN_B, 2),
                _n("S3", R_SRC, CHAIN_B, 0),
                _n("AGG2", R_AGG, CHAIN_B, 3),
                _n("T", R_TGT, CHAIN_B, 4),
            ],
            edges=[
                _e("S1", "AGG1", M),
                _e("S2", "AGG1", M),
                _e("AGG1", "CC", B),
                _e("S3", "AGG2", M),
                _e("CC", "AGG2", T),
                _e("AGG2", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=-1,
                chain_transition=True,
                target_chain=CHAIN_B,
                next_recommended_roles=(R_TGT,),
            ),
            tags=("integration", "merge", "bridge", "cross_chain"),
        ),
        # 12 --------------------------------------------------------------
        TopologicalMotif(
            motif_id="Multi_Split_Cross_Chain_Bridge",
            pattern_type=PatternType.MULTI_LAYERING_SPLIT,
            description=(
                "Split-then-bridge fan-out: funds are split into parallel "
                "streams on the origin chain and each stream is bridged to a "
                "different destination chain before re-converging on the "
                "final target chain."
            ),
            preconditions=Preconditions(
                min_level=3,
                allowed_node_roles=[R_SRC, R_INT, R_CC],
                max_active_branches=6,
            ),
            constraints=MotifConstraints(max_branching_factor=3),
            nodes=[
                _n("S", R_SRC, CHAIN_A, 0),
                _n("I1", R_INT, CHAIN_A, 1),
                _n("I2", R_INT, CHAIN_A, 1),
                _n("I3", R_INT, CHAIN_A, 1),
                _n("CC1", R_CC, CHAIN_B, 2),
                _n("CC2", R_CC, CHAIN_C, 2),
                _n("CC3", R_CC, CHAIN_B, 2),
                _n("T", R_TGT, CHAIN_B, 3),
            ],
            edges=[
                # equal three-way split (symmetric prototype)
                _e("S", "I1", P, 0.34),
                _e("S", "I2", P, 0.33),
                _e("S", "I3", P, 0.33),
                _e("I1", "CC1", B),
                _e("I2", "CC2", B),
                _e("I3", "CC3", B),
                _e("CC1", "T", T),
                _e("CC2", "T", B),
                _e("CC3", "T", T),
            ],
            post_state_effect=PostStateEffect(
                branch_increment=2,
                chain_transition=True,
                target_chain=CHAIN_B,
                next_recommended_roles=(R_CC, R_TGT),
            ),
            tags=("split", "bridge", "fan_out", "cross_chain"),
        ),
    ]


#: Immutable, validated seed motif collection (built once at import time).
SEED_MOTIFS: list[TopologicalMotif] = build_seed_motifs()
