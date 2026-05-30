"""v0.7: saga compensation, suspend/resume/fork, constraints, human handoff."""

from __future__ import annotations

import pytest

from ontorag_flow.actions.human import RequestHumanReview
from ontorag_flow.core.case import CaseStatus
from ontorag_flow.core.case_manager import (
    CaseManager,
    CaseStateTransitionError,
    CompensationError,
    ConstraintViolationError,
)
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.engines.human import HumanReviewEngine

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
HUMAN = "urn:ontorag-flow:action:RequestHumanReview"

TRIAGE = ProcessDefinition(
    process_uri="urn:p:triage",
    name="Triage",
    allowed_actions=[UPDATE],
    goal={"diagnosed": True},
)


# --- compensation ----------------------------------------------------------


async def test_compensate_restores_state_and_reopens(
    case_manager_sqlite: CaseManager,
) -> None:
    manager = case_manager_sqlite
    await manager.register_process(TRIAGE)
    case = await manager.create_case("urn:p:triage")

    case, _ = await manager.execute_action(case.case_uri, UPDATE, {"key": "a", "value": 1})
    case, _ = await manager.execute_action(case.case_uri, UPDATE, {"key": "b", "value": 2})
    case, _ = await manager.execute_action(
        case.case_uri, UPDATE, {"key": "diagnosed", "value": True}
    )
    assert case.status is CaseStatus.CLOSED
    assert case.state.properties == {"a": 1, "b": 2, "diagnosed": True}

    compensated = await manager.compensate(case.case_uri)

    assert compensated.status is CaseStatus.OPEN  # reopened
    assert compensated.state.properties == {}     # back to creation state
    # history is replaced by a single compensation event:
    assert len(compensated.history) == 1
    assert compensated.history[0].action_uri.endswith(":_Compensate")


async def test_compensate_partial_to_target(
    case_manager_sqlite: CaseManager,
) -> None:
    manager = case_manager_sqlite
    await manager.register_process(TRIAGE)
    case = await manager.create_case("urn:p:triage")

    case, first = await manager.execute_action(case.case_uri, UPDATE, {"key": "a", "value": 1})
    case, second = await manager.execute_action(case.case_uri, UPDATE, {"key": "b", "value": 2})

    compensated = await manager.compensate(
        case.case_uri, target_activity_uri=second.activity.activity_uri
    )
    # Only the second action is undone; first action's effect remains.
    assert compensated.state.properties == {"a": 1}
    # kept history (first) + compensation event = 2
    assert len(compensated.history) == 2
    assert compensated.history[0].activity_uri == first.activity.activity_uri


async def test_compensate_unknown_target_raises(
    case_manager_sqlite: CaseManager,
) -> None:
    manager = case_manager_sqlite
    await manager.register_process(TRIAGE)
    case = await manager.create_case("urn:p:triage")
    await manager.execute_action(case.case_uri, UPDATE, {"key": "a", "value": 1})

    with pytest.raises(CompensationError):
        await manager.compensate(case.case_uri, target_activity_uri="urn:nope")


async def test_compensate_empty_history_raises(
    case_manager_sqlite: CaseManager,
) -> None:
    manager = case_manager_sqlite
    await manager.register_process(TRIAGE)
    case = await manager.create_case("urn:p:triage")

    with pytest.raises(CompensationError):
        await manager.compensate(case.case_uri)


# --- suspend / resume / fork ----------------------------------------------


async def test_suspend_resume_cycle(case_manager_sqlite: CaseManager) -> None:
    manager = case_manager_sqlite
    await manager.register_process(TRIAGE)
    case = await manager.create_case("urn:p:triage")

    suspended = await manager.suspend(case.case_uri)
    assert suspended.status is CaseStatus.SUSPENDED

    with pytest.raises(CaseStateTransitionError):
        await manager.suspend(case.case_uri)  # already suspended

    resumed = await manager.resume(case.case_uri)
    assert resumed.status is CaseStatus.OPEN

    with pytest.raises(CaseStateTransitionError):
        await manager.resume(case.case_uri)  # already open


async def test_fork_copies_state_and_history(case_manager_sqlite: CaseManager) -> None:
    manager = case_manager_sqlite
    await manager.register_process(TRIAGE)
    case = await manager.create_case("urn:p:triage")
    case, _ = await manager.execute_action(case.case_uri, UPDATE, {"key": "a", "value": 1})

    forked = await manager.fork(case.case_uri)
    assert forked.case_uri != case.case_uri
    assert forked.process_uri == case.process_uri
    assert forked.state.properties == {"a": 1}
    assert len(forked.history) == 1
    assert forked.status is CaseStatus.OPEN


# --- constraints -----------------------------------------------------------


async def test_mutex_constraint_blocks_conflicting_action(
    case_manager_sqlite: CaseManager,
) -> None:
    process = ProcessDefinition(
        process_uri="urn:p:mutex",
        name="Mutex",
        allowed_actions=[UPDATE],
        constraints={"mutex": [[UPDATE, UPDATE]]},  # trivially mutex with itself
    )
    # use a non-self-mutex example:
    other = "urn:ontorag-flow:action:SetGoal"
    process = ProcessDefinition(
        process_uri="urn:p:mutex2",
        name="Mutex2",
        allowed_actions=[UPDATE, other],
        constraints={"mutex": [[UPDATE, other]]},
    )
    await case_manager_sqlite.register_process(process)
    case = await case_manager_sqlite.create_case("urn:p:mutex2")
    await case_manager_sqlite.execute_action(case.case_uri, UPDATE, {"key": "x", "value": 1})

    with pytest.raises(ConstraintViolationError):
        await case_manager_sqlite.execute_action(case.case_uri, other, {"predicate": "done"})


async def test_requires_constraint_blocks_missing_prereq(
    case_manager_sqlite: CaseManager,
) -> None:
    prereq = "urn:ontorag-flow:action:SetGoal"
    process = ProcessDefinition(
        process_uri="urn:p:req",
        name="Req",
        allowed_actions=[UPDATE, prereq],
        constraints={"requires": {UPDATE: [prereq]}},
    )
    await case_manager_sqlite.register_process(process)
    case = await case_manager_sqlite.create_case("urn:p:req")

    with pytest.raises(ConstraintViolationError):
        await case_manager_sqlite.execute_action(case.case_uri, UPDATE, {"key": "x", "value": 1})

    # satisfy the prereq, then UPDATE works
    await case_manager_sqlite.execute_action(case.case_uri, prereq, {"predicate": "p"})
    case, _ = await case_manager_sqlite.execute_action(
        case.case_uri, UPDATE, {"key": "x", "value": 1}
    )
    assert case.state.properties["x"] == 1


# --- human-in-the-loop handoff --------------------------------------------


async def test_human_engine_proposes_request_human_review() -> None:
    process = ProcessDefinition(
        process_uri="urn:p:h", name="H", allowed_actions=[HUMAN], engine="human"
    )
    case = await _build_case_for(process)
    proposals = await HumanReviewEngine().propose_next(case, process)

    assert len(proposals) == 1
    assert proposals[0].action_uri == RequestHumanReview.uri
    assert proposals[0].proposed_by == "HumanReviewEngine"


async def test_executing_human_action_auto_suspends_case(
    case_manager_sqlite: CaseManager,
) -> None:
    process = ProcessDefinition(
        process_uri="urn:p:h", name="H", allowed_actions=[HUMAN]
    )
    await case_manager_sqlite.register_process(process)
    case = await case_manager_sqlite.create_case("urn:p:h")

    case, _ = await case_manager_sqlite.execute_action(
        case.case_uri, HUMAN, {"reason": "low confidence"}
    )

    assert case.status is CaseStatus.SUSPENDED
    assert case.state.properties["awaiting_human_review"] is True

    # Resuming brings it back to OPEN
    resumed = await case_manager_sqlite.resume(case.case_uri)
    assert resumed.status is CaseStatus.OPEN


async def _build_case_for(process: ProcessDefinition):
    from ontorag_flow.core.case import Case
    from ontorag_flow.core.state import CaseState

    return Case(
        case_uri="urn:c", process_uri=process.process_uri, state=CaseState(case_uri="urn:c")
    )
