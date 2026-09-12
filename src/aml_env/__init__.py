"""aml_env — Stage-1 behavioural graph environment & hard verifier.

Provides the execution layer of the Cross-Chain AML Behavioural Graph
Generation framework:

- :class:`AgentAction` / :class:`StepResult`: action & transition payloads;
- :class:`HardVerifier`: zero-tolerance structural gate (DAG, level
  monotonicity, branching cap, chain conservation);
- :class:`BehavioralEnvironment`: incremental :math:`G_b` state machine that
  exports :class:`aml_rag.schema.CurrentState` snapshots consumed directly by
  the dual-track RAG retriever.
"""

from __future__ import annotations

from .environment import (
    AgentAction,
    BehavioralEnvironment,
    RewardConfig,
    StepResult,
)
from .verifier import HardVerifier

__version__ = "0.1.0"

__all__ = [
    "AgentAction",
    "StepResult",
    "RewardConfig",
    "HardVerifier",
    "BehavioralEnvironment",
    "__version__",
]
