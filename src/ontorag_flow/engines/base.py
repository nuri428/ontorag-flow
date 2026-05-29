"""The DecisionEngine contract.

Given a case's current state and its governing process, an engine returns zero or
more ranked :class:`ActionProposal` objects. Multiple engines can be stacked
(e.g. LLM proposes, rule engine validates) — the arbitration policy is decided
later; here we fix only the single-engine contract.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition

__all__ = ["DecisionEngine", "ActionProposal"]


@runtime_checkable
class DecisionEngine(Protocol):
    """Proposes the next action(s) for a case, ranked best-first."""

    async def propose_next(
        self, case: Case, process: ProcessDefinition
    ) -> list[ActionProposal]: ...
