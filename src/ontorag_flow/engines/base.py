"""The DecisionEngine contract.

Given a case's current state and its governing process, an engine returns zero or
more ranked :class:`ActionProposal` objects. Multiple engines can be stacked
(e.g. LLM proposes, rule engine validates) — the arbitration policy is decided
later; here we fix only the single-engine contract.

Engines may *optionally* implement :meth:`explain`, returning an
:class:`EngineExplanation` with the same proposals plus a free-form ``trace``
dict describing *why* (rule matches, posterior breakdown, prompts, etc.).
The inspector UI surfaces this so an operator can audit a recommendation.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition

__all__ = ["DecisionEngine", "ActionProposal", "EngineExplanation"]


class EngineExplanation(BaseModel):
    """Why the engine returned what it returned.

    ``trace`` is intentionally a free-form dict — every engine has a
    different vocabulary of "why" (rule matches vs posterior breakdown
    vs LLM prompt), and forcing a common schema would erase the
    information that makes the inspector useful.
    """

    engine_kind: str = Field(description="The engine class name (e.g. 'RuleEngine').")
    proposals: list[ActionProposal] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class DecisionEngine(Protocol):
    """Proposes the next action(s) for a case, ranked best-first."""

    async def propose_next(
        self, case: Case, process: ProcessDefinition
    ) -> list[ActionProposal]: ...
