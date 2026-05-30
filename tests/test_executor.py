"""Executor lifecycle: validation, immutable state apply, audit, error paths."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel

from ontorag_flow.actions.case_state import UpdateCaseProperty
from ontorag_flow.core.action import ActionResult, BaseAction, ProvOActivity, SideEffectKind
from ontorag_flow.core.audit import InMemoryAuditStore
from ontorag_flow.core.executor import ActionExecutor, ActionValidationError
from ontorag_flow.core.state import EMPTY_STATE


async def test_execute_applies_state_and_audits(
    executor: ActionExecutor,
    audit_store: InMemoryAuditStore,
    update_property: UpdateCaseProperty,
) -> None:
    outcome = await executor.execute(update_property, {"key": "severity", "value": 3}, EMPTY_STATE)

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


# --- P7: write-ahead audit for externally-visible side effects ----------


class _SpyAuditStore:
    """Captures every record() call so we can assert pending → completed."""

    def __init__(self) -> None:
        self.records: list[ProvOActivity] = []

    async def record(self, activity: ProvOActivity) -> None:
        # Snapshot at write time — later upserts produce a separate entry.
        self.records.append(activity.model_copy())

    async def list_all(self) -> list[ProvOActivity]:
        return list(self.records)

    async def list_by_case(self, case_uri: str) -> list[ProvOActivity]:
        return [a for a in self.records if a.case_uri == case_uri]

    async def get(self, activity_uri: str) -> ProvOActivity | None:
        return next((a for a in self.records if a.activity_uri == activity_uri), None)


class _ExternalParams(BaseModel):
    payload: str = "x"


class _ExternalAction(BaseAction):
    """A stand-in for an action with a real external side effect."""

    uri: ClassVar[str] = "urn:test:action:External"
    name: ClassVar[str] = "External"
    input_schema: ClassVar[type[BaseModel]] = _ExternalParams
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.EXTERNAL_API, SideEffectKind.CASE_STATE}
    )

    async def execute(self, params: BaseModel, state) -> ActionResult:  # type: ignore[override]
        return ActionResult(
            action_uri=self.uri,
            outputs={"payload": _ExternalParams.model_validate(params.model_dump()).payload},
        )


async def test_external_action_is_write_ahead_pending_then_completed() -> None:
    spy = _SpyAuditStore()
    executor = ActionExecutor(audit_store=spy, agent="urn:test:agent")

    await executor.execute(_ExternalAction(), {}, EMPTY_STATE)

    assert len(spy.records) == 2, "externally-visible action should write-ahead"
    pending, completed = spy.records
    assert pending.status == "pending"
    assert completed.status == "completed"
    # Same row gets upserted (store's record() is idempotent on activity_uri).
    assert pending.activity_uri == completed.activity_uri
    assert pending.ended_at is None and completed.ended_at is not None


async def test_state_only_action_keeps_single_write(
    executor: ActionExecutor, audit_store: InMemoryAuditStore, update_property: UpdateCaseProperty
) -> None:
    # UpdateCaseProperty declares only CASE_STATE — no write-ahead, one row.
    await executor.execute(update_property, {"key": "k", "value": 1}, EMPTY_STATE)

    activities = await audit_store.list_all()
    assert len(activities) == 1
    assert activities[0].status == "completed"


async def test_external_action_failure_upserts_to_failed() -> None:
    spy = _SpyAuditStore()
    executor = ActionExecutor(audit_store=spy, agent="urn:test:agent")

    class _BadExternal(_ExternalAction):
        async def execute(self, params: BaseModel, state) -> ActionResult:  # type: ignore[override]
            raise RuntimeError("network exploded")

    await executor.execute(_BadExternal(), {}, EMPTY_STATE)

    assert [r.status for r in spy.records] == ["pending", "failed"]
    assert spy.records[1].error == "network exploded"
    assert spy.records[0].activity_uri == spy.records[1].activity_uri
