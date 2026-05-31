"""B3 — audit retention purge for terminal cases."""

from __future__ import annotations

from datetime import timedelta

from ontorag_flow.core.action import utcnow
from ontorag_flow.core.case import CaseStatus
from ontorag_flow.core.case_manager import CaseManager
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.stores.sqlite import SqliteStore

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
SET_GOAL = "urn:ontorag-flow:action:SetGoal"

PROCESS = ProcessDefinition(
    process_uri="urn:p:retain",
    name="Retention sample",
    allowed_actions=[UPDATE, SET_GOAL],
    goal={"done": True},
)


async def _seed_terminal(
    manager: CaseManager, store: SqliteStore, *, age_days: int, status: CaseStatus
) -> str:
    """Create a case + one action, then force terminal status and back-date it."""

    case = await manager.create_case("urn:p:retain")
    case, _ = await manager.execute_action(case.case_uri, UPDATE, {"key": "step", "value": 1})
    persisted = await store.get_case(case.case_uri)
    assert persisted is not None
    older = utcnow() - timedelta(days=age_days)
    persisted = persisted.model_copy(update={"status": status, "updated_at": older})
    await store.update_case(persisted)
    return case.case_uri


async def test_prune_removes_old_terminal_cases(
    case_manager_sqlite: CaseManager, sqlite_store: SqliteStore
) -> None:
    await case_manager_sqlite.register_process(PROCESS)

    old = await _seed_terminal(
        case_manager_sqlite, sqlite_store, age_days=120, status=CaseStatus.CLOSED
    )
    failed = await _seed_terminal(
        case_manager_sqlite, sqlite_store, age_days=200, status=CaseStatus.FAILED
    )
    recent = await _seed_terminal(
        case_manager_sqlite, sqlite_store, age_days=10, status=CaseStatus.CLOSED
    )

    removed = await case_manager_sqlite.prune_audit(older_than_days=90)

    assert set(removed) == {old, failed}
    assert await sqlite_store.get_case(old) is None
    assert await sqlite_store.get_case(failed) is None
    survivor = await sqlite_store.get_case(recent)
    assert survivor is not None
    # Activities for pruned cases should also be gone.
    assert await sqlite_store.list_by_case(old) == []
    assert await sqlite_store.list_by_case(failed) == []
    assert await sqlite_store.list_by_case(recent) != []


async def test_prune_dry_run_keeps_data(
    case_manager_sqlite: CaseManager, sqlite_store: SqliteStore
) -> None:
    await case_manager_sqlite.register_process(PROCESS)
    uri = await _seed_terminal(
        case_manager_sqlite, sqlite_store, age_days=120, status=CaseStatus.CLOSED
    )

    removed = await case_manager_sqlite.prune_audit(older_than_days=90, dry_run=True)

    assert removed == [uri]
    assert await sqlite_store.get_case(uri) is not None
    assert await sqlite_store.list_by_case(uri) != []


async def test_prune_skips_open_cases(
    case_manager_sqlite: CaseManager, sqlite_store: SqliteStore
) -> None:
    await case_manager_sqlite.register_process(PROCESS)

    # OPEN case, even ancient — must never be touched by retention.
    case = await case_manager_sqlite.create_case("urn:p:retain")
    persisted = await sqlite_store.get_case(case.case_uri)
    assert persisted is not None
    persisted = persisted.model_copy(update={"updated_at": utcnow() - timedelta(days=999)})
    await sqlite_store.update_case(persisted)

    removed = await case_manager_sqlite.prune_audit(older_than_days=30)

    assert removed == []
    assert await sqlite_store.get_case(case.case_uri) is not None
