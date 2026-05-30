"""Skeleton deviation tagging — PROV-O metadata for off-happy-path executions.

A process's optional ``skeleton: [action_uri, ...]`` is advisory: actions
still execute, but the executor's PROV-O activity gets
``deviated_from_skeleton``/``skeleton_expected``/``skeleton_position`` keys
in ``metadata`` whenever the execution doesn't match the next expected
entry. This is the "auditable adaptive" promise of the design principle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from ontorag_flow.core.case_manager import CaseManager
from ontorag_flow.core.executor import ActionExecutor
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.registry import default_registry
from ontorag_flow.stores.sqlite import SqliteStore

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
SETGOAL = "urn:ontorag-flow:action:SetGoal"


@pytest_asyncio.fixture
async def manager() -> AsyncIterator[CaseManager]:
    async with SqliteStore(":memory:") as store:
        yield CaseManager(
            case_store=store,
            process_store=store,
            executor=ActionExecutor(audit_store=store, agent="urn:test"),
            registry=default_registry(),
        )


def _proc(*skeleton: str) -> ProcessDefinition:
    return ProcessDefinition(
        process_uri="urn:p:s",
        name="S",
        allowed_actions=[UPDATE, SETGOAL],
        skeleton=list(skeleton),
    )


async def test_no_skeleton_no_metadata(manager: CaseManager) -> None:
    """A process without a skeleton leaves activity.metadata empty."""

    await manager.register_process(_proc())
    case = await manager.create_case("urn:p:s")
    _, outcome = await manager.execute_action(case.case_uri, UPDATE, {"key": "x", "value": 1})
    assert outcome.activity.metadata == {}


async def test_on_skeleton_no_deviation_tag(manager: CaseManager) -> None:
    """Following the skeleton produces no deviation metadata."""

    await manager.register_process(_proc(UPDATE, SETGOAL))
    case = await manager.create_case("urn:p:s")
    _, outcome = await manager.execute_action(case.case_uri, UPDATE, {"key": "x", "value": 1})
    assert "deviated_from_skeleton" not in outcome.activity.metadata


async def test_first_action_deviation(manager: CaseManager) -> None:
    """First action != skeleton[0] is flagged with the expected URI."""

    await manager.register_process(_proc(SETGOAL, UPDATE))
    case = await manager.create_case("urn:p:s")
    _, outcome = await manager.execute_action(case.case_uri, UPDATE, {"key": "x", "value": 1})
    meta = outcome.activity.metadata
    assert meta["deviated_from_skeleton"] is True
    assert meta["skeleton_expected"] == SETGOAL
    assert meta["skeleton_position"] == 0


async def test_off_skeleton_after_end_tagged_with_null_expected(
    manager: CaseManager,
) -> None:
    """Executions past the skeleton's end get expected=None but still flagged."""

    await manager.register_process(_proc(UPDATE))  # single-step skeleton
    case = await manager.create_case("urn:p:s")
    _, _ = await manager.execute_action(case.case_uri, UPDATE, {"key": "x", "value": 1})
    _, outcome = await manager.execute_action(
        case.case_uri, SETGOAL, {"predicate": "diagnosed", "value": True}
    )
    meta = outcome.activity.metadata
    assert meta["deviated_from_skeleton"] is True
    assert meta["skeleton_expected"] is None
    assert meta["skeleton_position"] == 1


async def test_deviation_persists_to_audit_store(manager: CaseManager) -> None:
    """The annotated activity is re-recorded, so list_by_case returns the metadata."""

    await manager.register_process(_proc(SETGOAL, UPDATE))
    case = await manager.create_case("urn:p:s")
    await manager.execute_action(case.case_uri, UPDATE, {"key": "x", "value": 1})

    activities = await manager._executor.audit_store.list_by_case(case.case_uri)
    assert len(activities) == 1
    assert activities[0].metadata["deviated_from_skeleton"] is True
