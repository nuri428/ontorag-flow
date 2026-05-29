"""Case model and state machine."""

from __future__ import annotations

from ontorag_flow.core.action import ProvOActivity, utcnow
from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.state import CaseState


def _make_case() -> Case:
    return Case(
        case_uri="urn:c:1",
        process_uri="urn:p:1",
        state=CaseState(case_uri="urn:c:1", properties={"a": 1}, goal={"done": True}),
    )


def test_new_case_is_open_with_empty_history() -> None:
    case = _make_case()
    assert case.status is CaseStatus.OPEN
    assert case.history == ()
    assert case.last_activity_uri is None


def test_record_execution_is_immutable_and_appends() -> None:
    case = _make_case()
    activity = ProvOActivity(
        activity_uri="urn:a:1", action_uri="urn:act:1", ended_at=utcnow(), success=True
    )
    new_state = case.state.with_property("done", True)

    advanced = case.record_execution(activity, new_state)

    assert case.history == ()  # original untouched
    assert len(advanced.history) == 1
    assert advanced.history[0].activity_uri == "urn:a:1"
    assert advanced.last_activity_uri == "urn:a:1"
    assert advanced.state.properties["done"] is True


def test_goal_reached() -> None:
    case = _make_case()
    assert case.state.goal_reached() is False
    assert case.state.with_property("done", True).goal_reached() is True


def test_with_status_is_immutable() -> None:
    case = _make_case()
    closed = case.with_status(CaseStatus.CLOSED)

    assert case.status is CaseStatus.OPEN
    assert closed.status is CaseStatus.CLOSED
    assert CaseStatus.CLOSED.is_terminal
    assert not CaseStatus.OPEN.is_terminal
