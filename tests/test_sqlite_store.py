"""SQLite store round-trips for processes, cases, and activities."""

from __future__ import annotations

import pytest

from ontorag_flow.core.action import ProvOActivity
from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.state import CaseState
from ontorag_flow.stores.base import OptimisticLockError
from ontorag_flow.stores.sqlite import SqliteStore


async def test_process_roundtrip(sqlite_store: SqliteStore) -> None:
    proc = ProcessDefinition(
        process_uri="urn:p:1", name="P", allowed_actions=["urn:a:1"], goal={"done": True}
    )
    await sqlite_store.save_process(proc)

    assert await sqlite_store.get_process("urn:p:1") == proc
    assert await sqlite_store.get_process("missing") is None
    assert [p.process_uri for p in await sqlite_store.list_processes()] == ["urn:p:1"]


async def test_case_roundtrip_and_find(sqlite_store: SqliteStore) -> None:
    case = Case(case_uri="urn:c:1", process_uri="urn:p:1", state=CaseState(case_uri="urn:c:1"))
    await sqlite_store.create_case(case)

    loaded = await sqlite_store.get_case("urn:c:1")
    assert loaded is not None and loaded.case_uri == "urn:c:1"

    await sqlite_store.update_case(case.with_status(CaseStatus.CLOSED))
    reloaded = await sqlite_store.get_case("urn:c:1")
    assert reloaded is not None and reloaded.status is CaseStatus.CLOSED

    assert len(await sqlite_store.find_cases(status=CaseStatus.CLOSED)) == 1
    assert len(await sqlite_store.find_cases(status=CaseStatus.OPEN)) == 0
    assert len(await sqlite_store.find_cases(process_uri="urn:p:1")) == 1
    assert len(await sqlite_store.find_cases(process_uri="urn:p:other")) == 0


async def test_persisted_case_excludes_history(sqlite_store: SqliteStore) -> None:
    # P5: the audit log is the authoritative history. The cases.data row must
    # not grow with every event — only the cross-cutting fields are stored,
    # and CaseManager rehydrates history from the activities table on load.
    import json

    from ontorag_flow.core.case import CaseEvent

    case = Case(
        case_uri="urn:c:history-exclude",
        process_uri="urn:p",
        state=CaseState(case_uri="urn:c:history-exclude"),
        history=(
            CaseEvent(
                activity_uri="urn:a:1",
                action_uri="urn:act:1",
                at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").UTC),
                success=True,
            ),
        ),
    )
    await sqlite_store.create_case(case)

    async with sqlite_store._conn.execute(  # type: ignore[union-attr]
        "SELECT data FROM cases WHERE uri = ?", ("urn:c:history-exclude",)
    ) as cursor:
        row = await cursor.fetchone()
    payload = json.loads(row["data"])
    assert "history" not in payload, (
        "case.data must not carry history — audit log is the authority (P5)."
    )


async def test_optimistic_lock_blocks_stale_update(sqlite_store: SqliteStore) -> None:
    case = Case(case_uri="urn:c:lock", process_uri="urn:p", state=CaseState(case_uri="urn:c:lock"))
    await sqlite_store.create_case(case)

    # First writer wins and moves the row to version 1.
    first = await sqlite_store.get_case("urn:c:lock")
    assert first is not None and first.version == 0
    await sqlite_store.update_case(first.with_status(CaseStatus.SUSPENDED))

    # A concurrent writer still holds the version=0 view and must lose the race.
    with pytest.raises(OptimisticLockError):
        await sqlite_store.update_case(case.with_status(CaseStatus.CLOSED))

    # Re-fetching gives version=1; that case can be updated again.
    fresh = await sqlite_store.get_case("urn:c:lock")
    assert fresh is not None and fresh.version == 1
    await sqlite_store.update_case(fresh.with_status(CaseStatus.CLOSED))

    final = await sqlite_store.get_case("urn:c:lock")
    assert final is not None and final.version == 2 and final.status is CaseStatus.CLOSED


async def test_activity_roundtrip_filtered_by_case(sqlite_store: SqliteStore) -> None:
    a1 = ProvOActivity(action_uri="urn:act:1", case_uri="urn:c:1")
    a2 = ProvOActivity(action_uri="urn:act:2", case_uri="urn:c:2")
    await sqlite_store.record(a1)
    await sqlite_store.record(a2)

    assert len(await sqlite_store.list_all()) == 2

    by_case = await sqlite_store.list_by_case("urn:c:1")
    assert [a.activity_uri for a in by_case] == [a1.activity_uri]

    got = await sqlite_store.get(a1.activity_uri)
    assert got is not None and got.action_uri == "urn:act:1"
