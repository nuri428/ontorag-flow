"""Executor lifecycle: validation, immutable state apply, audit, error paths."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel

from ontorag_flow.actions.case_state import UpdateCaseProperty
from ontorag_flow.core.action import ActionResult, BaseAction, SideEffectKind
from ontorag_flow.core.audit import InMemoryAuditStore
from ontorag_flow.core.executor import ActionExecutor, ActionValidationError
from ontorag_flow.core.state import EMPTY_STATE


async def test_execute_applies_state_and_audits(
    executor: ActionExecutor,
    audit_store: InMemoryAuditStore,
    update_property: UpdateCaseProperty,
) -> None:
    outcome = await executor.execute(
        update_property, {"key": "severity", "value": 3}, EMPTY_STATE
    )

    assert outcome.result.success is True
    assert outcome.state.properties == {"severity": 3}
    assert EMPTY_STATE.properties == {}  # original untouched

    activities = await audit_store.list_all()
    assert len(activities) == 1
    assert activities[0].agent == "urn:test:agent"
    assert activities[0].used == {"key": "severity", "value": 3}
    assert activities[0].started_at is not None
    assert activities[0].ended_at is not None


async def test_informed_by_links_activities(
    executor: ActionExecutor, update_property: UpdateCaseProperty
) -> None:
    first = await executor.execute(update_property, {"key": "a", "value": 1}, EMPTY_STATE)
    second = await executor.execute(
        update_property,
        {"key": "b", "value": 2},
        first.state,
        informed_by=first.activity.activity_uri,
    )

    assert second.activity.informed_by == first.activity.activity_uri
    assert second.state.properties == {"a": 1, "b": 2}


async def test_invalid_params_raise_without_audit(
    executor: ActionExecutor,
    audit_store: InMemoryAuditStore,
    update_property: UpdateCaseProperty,
) -> None:
    with pytest.raises(ActionValidationError):
        await executor.execute(update_property, {"value": 1}, EMPTY_STATE)

    assert await audit_store.list_all() == []


class _FailingParams(BaseModel):
    pass


class _FailingAction(BaseAction):
    uri: ClassVar[str] = "urn:test:action:Failing"
    name: ClassVar[str] = "Failing"
    input_schema: ClassVar[type[BaseModel]] = _FailingParams
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.NONE})

    async def execute(self, params: BaseModel, state) -> ActionResult:  # type: ignore[override]
        raise RuntimeError("boom")


async def test_execution_failure_is_audited(
    executor: ActionExecutor, audit_store: InMemoryAuditStore
) -> None:
    outcome = await executor.execute(_FailingAction(), {}, EMPTY_STATE)

    assert outcome.result.success is False
    assert outcome.result.error == "boom"
    assert outcome.state is EMPTY_STATE  # no state change on failure

    activities = await audit_store.list_all()
    assert len(activities) == 1
    assert activities[0].success is False
    assert activities[0].error == "boom"


class _DenyParams(BaseModel):
    pass


class _DenyAction(BaseAction):
    uri: ClassVar[str] = "urn:test:action:Deny"
    name: ClassVar[str] = "Deny"
    input_schema: ClassVar[type[BaseModel]] = _DenyParams
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.NONE})

    async def validate(self, params: BaseModel, state) -> bool:  # type: ignore[override]
        return False

    async def execute(self, params: BaseModel, state) -> ActionResult:  # type: ignore[override]
        return ActionResult(action_uri=self.uri)


async def test_failed_precondition_raises(
    executor: ActionExecutor, audit_store: InMemoryAuditStore
) -> None:
    with pytest.raises(ActionValidationError):
        await executor.execute(_DenyAction(), {}, EMPTY_STATE)

    assert await audit_store.list_all() == []
