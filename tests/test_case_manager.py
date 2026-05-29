"""Case manager orchestration: creation, execution, goal closing, errors."""

from __future__ import annotations

import pytest

from ontorag_flow.core.case import CaseStatus
from ontorag_flow.core.case_manager import (
    ActionNotAllowedError,
    CaseClosedError,
    CaseManager,
    CaseNotFoundError,
    ProcessNotFoundError,
)
from ontorag_flow.core.process import ProcessDefinition

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
SET_GOAL = "urn:ontorag-flow:action:SetGoal"

TRIAGE = ProcessDefinition(
    process_uri="urn:p:triage",
    name="Triage",
    allowed_actions=[UPDATE, SET_GOAL],
    goal={"diagnosed": True},
    initial_state={"triage_level": "unknown"},
)


async def test_create_case_seeds_state_and_goal(case_manager_sqlite: CaseManager) -> None:
    await case_manager_sqlite.register_process(TRIAGE)

    case = await case_manager_sqlite.create_case("urn:p:triage", initial_state={"age": 40})

    assert case.status is CaseStatus.OPEN
    assert case.state.properties == {"triage_level": "unknown", "age": 40}
    assert case.state.goal == {"diagnosed": True}


async def test_create_case_unknown_process(case_manager_sqlite: CaseManager) -> None:
    with pytest.raises(ProcessNotFoundError):
        await case_manager_sqlite.create_case("urn:p:none")


async def test_execute_advances_state_and_chains_provenance(
    case_manager_sqlite: CaseManager,
) -> None:
    await case_manager_sqlite.register_process(TRIAGE)
    case = await case_manager_sqlite.create_case("urn:p:triage")

    case, first = await case_manager_sqlite.execute_action(
        case.case_uri, UPDATE, {"key": "triage_level", "value": "high"}
    )
    assert case.state.properties["triage_level"] == "high"
    assert case.status is CaseStatus.OPEN
    assert len(case.history) == 1

    case, second = await case_manager_sqlite.execute_action(
        case.case_uri, UPDATE, {"key": "x", "value": 1}
    )
    assert second.activity.informed_by == first.activity.activity_uri
    assert second.activity.case_uri == case.case_uri


async def test_goal_reached_auto_closes_and_locks(
    case_manager_sqlite: CaseManager,
) -> None:
    await case_manager_sqlite.register_process(TRIAGE)
    case = await case_manager_sqlite.create_case("urn:p:triage")

    case, _ = await case_manager_sqlite.execute_action(
        case.case_uri, UPDATE, {"key": "diagnosed", "value": True}
    )
    assert case.status is CaseStatus.CLOSED

    with pytest.raises(CaseClosedError):
        await case_manager_sqlite.execute_action(
            case.case_uri, UPDATE, {"key": "y", "value": 2}
        )


async def test_action_not_allowed(case_manager_sqlite: CaseManager) -> None:
    locked = ProcessDefinition(process_uri="urn:p:locked", name="Locked", allowed_actions=[])
    await case_manager_sqlite.register_process(locked)
    case = await case_manager_sqlite.create_case("urn:p:locked")

    with pytest.raises(ActionNotAllowedError):
        await case_manager_sqlite.execute_action(case.case_uri, SET_GOAL, {"predicate": "x"})


async def test_execute_unknown_case(case_manager_sqlite: CaseManager) -> None:
    with pytest.raises(CaseNotFoundError):
        await case_manager_sqlite.execute_action("urn:c:none", SET_GOAL, {"predicate": "x"})
