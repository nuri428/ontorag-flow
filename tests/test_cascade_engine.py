"""CascadeEngine — fallback sequence semantics + explain trace."""

from __future__ import annotations

import pytest

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.state import CaseState
from ontorag_flow.engines.cascade import CascadeEngine


def _case() -> Case:
    return Case(
        case_uri="urn:c:1",
        process_uri="urn:p:1",
        status=CaseStatus.OPEN,
        state=CaseState(),
    )


def _proc() -> ProcessDefinition:
    return ProcessDefinition(process_uri="urn:p:1", name="P", allowed_actions=["urn:a"])


class _Empty:
    async def propose_next(self, case: Case, process: ProcessDefinition) -> list[ActionProposal]:
        return []


class _OneProposal:
    def __init__(self, label: str) -> None:
        self._label = label

    async def propose_next(self, case: Case, process: ProcessDefinition) -> list[ActionProposal]:
        return [ActionProposal(action_uri="urn:a", proposed_by=self._label, confidence=1.0)]


async def test_first_non_empty_wins() -> None:
    engine = CascadeEngine([("a", _Empty()), ("b", _OneProposal("B")), ("c", _OneProposal("C"))])
    proposals = await engine.propose_next(_case(), _proc())
    assert len(proposals) == 1
    assert proposals[0].proposed_by == "B"


async def test_all_empty_returns_empty() -> None:
    engine = CascadeEngine([("a", _Empty()), ("b", _Empty())])
    assert await engine.propose_next(_case(), _proc()) == []


async def test_explain_short_circuits_at_winner() -> None:
    """explain() must not invoke engines after the winner — same cost as propose_next."""

    class _CountingEngine:
        def __init__(self, label: str) -> None:
            self.label = label
            self.calls = 0

        async def propose_next(
            self, case: Case, process: ProcessDefinition
        ) -> list[ActionProposal]:
            self.calls += 1
            return [ActionProposal(action_uri="urn:a", proposed_by=self.label, confidence=1.0)]

    first = _Empty()
    second = _CountingEngine("Second")
    third = _CountingEngine("Third")

    engine = CascadeEngine([("first", first), ("second", second), ("third", third)])
    explanation = await engine.explain(_case(), _proc())

    assert explanation.engine_kind == "CascadeEngine"
    assert explanation.trace["sequence"] == ["first", "second", "third"]
    assert explanation.trace["chosen"] == "second"
    # third must not have been called — that's the whole point.
    assert third.calls == 0
    assert second.calls == 1

    # The post-winner entry is recorded as not consulted, so the operator
    # still sees the fallback tail without paying for it.
    attempts = {entry["kind"]: entry for entry in explanation.trace["attempts"]}
    assert attempts["first"] == {"kind": "first", "consulted": True, "count": 0}
    assert attempts["second"] == {"kind": "second", "consulted": True, "count": 1}
    assert attempts["third"] == {"kind": "third", "consulted": False, "count": None}

    assert len(explanation.proposals) == 1
    assert explanation.proposals[0].proposed_by == "Second"


def test_rejects_empty_sequence() -> None:
    with pytest.raises(ValueError):
        CascadeEngine([])
