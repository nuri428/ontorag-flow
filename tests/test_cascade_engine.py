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


async def test_explain_records_every_attempt_and_chosen() -> None:
    engine = CascadeEngine(
        [("first", _Empty()), ("second", _OneProposal("Second")), ("third", _OneProposal("Third"))]
    )
    explanation = await engine.explain(_case(), _proc())
    assert explanation.engine_kind == "CascadeEngine"
    assert explanation.trace["sequence"] == ["first", "second", "third"]
    assert explanation.trace["chosen"] == "second"
    attempts = {entry["kind"]: entry["count"] for entry in explanation.trace["attempts"]}
    # first contributed 0; the second won with 1; the third also had 1 (logged for the operator)
    assert attempts == {"first": 0, "second": 1, "third": 1}
    assert len(explanation.proposals) == 1
    assert explanation.proposals[0].proposed_by == "Second"


def test_rejects_empty_sequence() -> None:
    with pytest.raises(ValueError):
        CascadeEngine([])
