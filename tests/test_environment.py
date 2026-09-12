"""Tests for the Stage-1 behavioural graph environment & hard verifier.

Covers the agreed decision matrix:
- frontier nodes are re-usable until their out-degree saturates at d_max;
- terminate is ``operation=None`` through :meth:`step`;
- rewards: legal 0 / illegal -1 / successful termination +1;
- ``current_chain`` = target chain of the last successful action;
- Merge requires parents sharing chain & level;
- max_steps=64 default; Split num_children in [2, d_max];
- illegal actions never mutate the graph (idempotence);
- snapshots are directly consumable by the RAG hard gate.
"""

from __future__ import annotations

from aml_env import AgentAction, BehavioralEnvironment, HardVerifier
from aml_rag import DualTrackMotifRetriever, QueryContext, build_default_knowledge_base
from aml_rag.schema import NodeRole, OperationType

TRANSFER = OperationType.TRANSFER
BRIDGE = OperationType.BRIDGE
SPLIT = OperationType.SPLIT
MERGE = OperationType.MERGE

SRC = NodeRole.SOURCE
INT = NodeRole.INTERMEDIATE
CC = NodeRole.CROSS_CHAIN
AGG = NodeRole.AGGREGATOR
TGT = NodeRole.TARGET


def _action(op, parents, role=INT, chain="Chain_A", **params) -> AgentAction:
    return AgentAction(
        operation=op,
        parent_ids=list(parents),
        target_role=role,
        target_chain=chain,
        parameters=dict(params),
    )


# ---------------------------------------------------------------------------
# 1. reset & linear evolution
# ---------------------------------------------------------------------------
def test_reset_initial_snapshot() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    state = env.reset()

    assert state.current_level == 0
    assert state.current_chain == "Chain_A"
    assert len(state.active_nodes) == 1
    root = state.active_nodes[0]
    assert root.temp_id == "node_0"
    assert root.role == NodeRole.SOURCE
    assert root.level == 0
    assert state.graph_history == []
    assert env.frontier == {"node_0"}
    assert env.step_count == 0
    assert not env.done


def test_linear_transfer_with_saturation_terminates_on_sink() -> None:
    # d_max=1 => every action saturates its parent: frontier stays linear
    env = BehavioralEnvironment(d_max=1, max_level=8)
    env.reset()

    r1 = env.step(_action(TRANSFER, ["node_0"], INT))
    assert r1.done is False
    assert r1.reward == 0.0
    assert r1.state.current_level == 1
    assert [n.temp_id for n in r1.state.active_nodes] == ["node_1"]

    r2 = env.step(_action(TRANSFER, ["node_1"], INT))
    assert r2.state.current_level == 2

    r3 = env.step(_action(TRANSFER, ["node_2"], TGT))
    # all frontier nodes are sinks -> termination condition 3
    assert r3.done is True
    assert r3.reward == 1.0
    assert r3.info["terminated_by"] == "all_frontier_are_sinks"
    assert len(r3.state.graph_history) == 3


# ---------------------------------------------------------------------------
# 2. frontier re-usability until out-degree saturation (d_max=4)
# ---------------------------------------------------------------------------
def test_frontier_node_reusable_until_saturated() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()

    for i in range(4):  # extend node_0 four times -> out-degree saturates
        r = env.step(_action(TRANSFER, ["node_0"], INT))
        assert r.done is False
        assert "node_0" in env.frontier or i == 3
    assert "node_0" not in env.frontier  # saturated -> leaves frontier

    # node_0 no longer in frontier -> refused
    bad = env.step(_action(TRANSFER, ["node_0"], INT))
    assert bad.done is False
    assert bad.reward == -1.0
    assert "not in the active frontier" in bad.info["error"]


# ---------------------------------------------------------------------------
# 3. bridge & chain conservation
# ---------------------------------------------------------------------------
def test_bridge_switches_chain_and_updates_current_chain() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()

    r = env.step(_action(BRIDGE, ["node_0"], CC, chain="Chain_B"))
    assert r.done is False
    assert r.state.current_chain == "Chain_B"
    # new Cross_Chain node lives on Chain_B; node_0 (unsaturated) stays active
    by_id = {n.temp_id: n for n in r.state.active_nodes}
    assert by_id["node_1"].chain == "Chain_B"
    assert by_id["node_1"].role == NodeRole.CROSS_CHAIN
    assert by_id["node_0"].chain == "Chain_A"


def test_chain_change_rejected_without_bridge() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()

    bad = env.step(_action(TRANSFER, ["node_0"], INT, chain="Chain_C"))
    assert bad.reward == -1.0
    assert "chain change not allowed" in bad.info["error"]


# ---------------------------------------------------------------------------
# 4. split & merge frontier bookkeeping
# ---------------------------------------------------------------------------
def test_split_and_merge_update_frontier_correctly() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()

    # Split node_0 into 2 children (node_0 keeps 2 spare out-degree slots)
    r = env.step(_action(SPLIT, ["node_0"], INT, num_children=2))
    assert r.done is False
    children = {n.temp_id for n in r.state.active_nodes}
    assert {"node_1", "node_2"} <= children
    assert "node_0" in children  # not saturated yet
    assert r.state.current_level == 1
    # two Split edges emitted from node_0
    assert len(r.state.graph_history) == 2
    assert all(e.operation == SPLIT for e in r.state.graph_history)

    # Merge node_1 + node_2 (same chain, same level) into an aggregator
    m = env.step(_action(MERGE, ["node_1", "node_2"], AGG))
    assert m.done is False
    assert m.state.current_level == 2
    ids = {n.temp_id for n in m.state.active_nodes}
    assert "node_3" in ids
    # node_1/node_2 out-degree=1 < 4: still reusable, remain in frontier
    assert {"node_1", "node_2"} <= ids


# ---------------------------------------------------------------------------
# 5. verifier interception matrix
# ---------------------------------------------------------------------------
def test_unknown_parent_rejected() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    bad = env.step(_action(TRANSFER, ["node_99"], INT))
    assert bad.reward == -1.0
    assert "does not exist" in bad.info["error"]


def test_merge_requires_two_parents() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    bad = env.step(_action(MERGE, ["node_0"], AGG))
    assert ">= 2 parents" in bad.info["error"]


def test_merge_parents_must_share_level_and_chain() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    env.step(_action(TRANSFER, ["node_0"], INT))              # node_1, L1, Chain_A
    env.step(_action(TRANSFER, ["node_0"], INT))              # node_2, L1, Chain_A
    env.step(_action(BRIDGE, ["node_0"], CC, chain="Chain_B"))  # node_3, L1, Chain_B

    wrong_level = env.step(_action(MERGE, ["node_0", "node_1"], AGG))
    assert "same level" in wrong_level.info["error"]

    wrong_chain = env.step(_action(MERGE, ["node_1", "node_3"], AGG))
    assert "same chain" in wrong_chain.info["error"]


def test_split_num_children_bounds() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    too_many = env.step(_action(SPLIT, ["node_0"], INT, num_children=5))
    assert "out of range" in too_many.info["error"]
    too_few = env.step(_action(SPLIT, ["node_0"], INT, num_children=1))
    assert "out of range" in too_few.info["error"]


def test_max_level_bound_interception() -> None:
    env = BehavioralEnvironment(d_max=1, max_level=2)
    env.reset()
    env.step(_action(TRANSFER, ["node_0"], INT))  # L1
    r = env.step(_action(TRANSFER, ["node_1"], INT))  # L2 -> reaches L_max
    assert r.done is True
    assert r.info["terminated_by"] == "max_level_reached"


# ---------------------------------------------------------------------------
# 6. idempotence of illegal actions
# ---------------------------------------------------------------------------
def test_illegal_action_does_not_mutate_graph() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    before = env.reset()

    bad = env.step(_action(TRANSFER, ["node_0"], INT, chain="Chain_Z"))
    after = bad.state

    assert bad.reward == -1.0
    assert after == before  # CurrentState is a Pydantic model: field-wise equality
    assert env.export_behavioral_graph()["meta"]["node_count"] == 1
    assert env.export_behavioral_graph()["meta"]["edge_count"] == 0


# ---------------------------------------------------------------------------
# 7. termination conditions
# ---------------------------------------------------------------------------
def test_explicit_terminate_action() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()

    r = env.step(AgentAction(operation=None))
    assert r.done is True
    assert r.reward == 1.0
    assert r.info["terminated_by"] == "agent_terminate"
    # env is sealed afterwards
    after = env.step(_action(TRANSFER, ["node_0"], INT))
    assert after.done is True
    assert after.reward == -1.0
    assert "already terminated" in after.info["error"]


def test_max_steps_reached() -> None:
    env = BehavioralEnvironment(d_max=1, max_level=8, max_steps=3)
    env.reset()
    env.step(_action(TRANSFER, ["node_0"], INT))
    env.step(_action(TRANSFER, ["node_1"], INT))
    r = env.step(_action(TRANSFER, ["node_2"], INT))
    assert r.done is True
    assert r.info["terminated_by"] == "max_steps_reached"


def test_frontier_empty_termination() -> None:
    # d_max=1, split impossible (needs >=2 children); frontier empties when
    # all nodes saturate and no successors can be added
    env = BehavioralEnvironment(d_max=1, max_level=8, max_steps=64)
    env.reset()
    r = env.step(_action(TRANSFER, ["node_0"], TGT))
    assert r.done is True
    assert r.info["terminated_by"] == "all_frontier_are_sinks"


# ---------------------------------------------------------------------------
# 8. structural invariants
# ---------------------------------------------------------------------------
def test_graph_remains_dag_throughout() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    actions = [
        _action(TRANSFER, ["node_0"], INT),
        _action(SPLIT, ["node_0"], INT, num_children=2),
        _action(MERGE, ["node_1", "node_2"], AGG),
        _action(BRIDGE, ["node_3"], CC, chain="Chain_B"),
    ]
    for action in actions:
        env.step(action)
    export = env.export_behavioral_graph()
    level_of = {n["id"]: n["level"] for n in export["nodes"]}
    for e in export["edges"]:
        assert level_of[e["target"]] > level_of[e["source"]]
    assert "flowchart LR" in env.render_mermaid()
    assert "-->" in env.render_mermaid()


# ---------------------------------------------------------------------------
# 9. RAG integration smoke test
# ---------------------------------------------------------------------------
def test_snapshot_feeds_rag_hard_gate() -> None:
    retriever = DualTrackMotifRetriever(build_default_knowledge_base())
    query = QueryContext(scenario="layering", tactic_goal="progress")
    env = BehavioralEnvironment(d_max=4, max_level=8)
    state = env.reset()

    # cold start: 1 active Source branch, level 0
    admitted = {r.motif_id for r in retriever.retrieve(state, query, top_k=50)}
    assert admitted == {"Peeling_Chain_Single_Chain", "DEX_Liquidity_Pool_Swap"}

    # one transfer -> 2 active branches (source still reusable) at level 1:
    # linear motifs capped at 1 branch are gated out, split motif admitted
    state = env.step(_action(TRANSFER, ["node_0"], INT)).state
    admitted = {r.motif_id for r in retriever.retrieve(state, query, top_k=50)}
    assert "Peeling_Chain_Single_Chain" not in admitted
    assert "Multi_Split_Obfuscation" in admitted


# ---------------------------------------------------------------------------
# 10. verifier as a standalone pure function
# ---------------------------------------------------------------------------
def test_hard_verifier_is_reusable_and_stateless() -> None:
    env = BehavioralEnvironment(d_max=4, max_level=8)
    env.reset()
    export = env.export_behavioral_graph()
    # verifier only reads snapshots -> repeated calls are independent
    from aml_rag.schema import AbstractEdge, AbstractNode

    nodes = {
        n["id"]: AbstractNode(
            temp_id=n["id"], role=NodeRole(n["role"]),
            chain=n["chain"], level=n["level"],
        )
        for n in export["nodes"]
    }
    edges = [
        AbstractEdge(source=e["source"], target=e["target"],
                     operation=OperationType(e["operation"]))
        for e in export["edges"]
    ]
    verifier = HardVerifier(env.constraints)
    ok, reason = verifier.validate(
        nodes=nodes, edges=edges, frontier={"node_0"},
        action=_action(TRANSFER, ["node_0"], INT),
    )
    assert ok and reason is None
    ok2, reason2 = verifier.validate(
        nodes=nodes, edges=edges, frontier={"node_0"},
        action=_action(TRANSFER, ["node_0"], INT, chain="Chain_Z"),
    )
    assert not ok2 and reason2 is not None
