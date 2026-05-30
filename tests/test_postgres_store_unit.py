"""Unit-level coverage for :class:`PostgresStore` query construction.

The real Postgres round-trip (transaction semantics, optimistic-lock race,
crash recovery) belongs in the testcontainers integration job. What we
verify here is *what query the store builds* for each method shape —
clause assembly, parameter ordering, LIMIT/OFFSET branches — using a fake
asyncpg connection that just records its calls.

If the store ever produces a different shape of SQL, this test fails
*before* a live integration test does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ontorag_flow.core.action import ProvOActivity
from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.state import CaseState
from ontorag_flow.stores.base import OptimisticLockError
from ontorag_flow.stores.postgres import PostgresStore


@dataclass
class FakeRow:
    """asyncpg returns Record-like rows — for our reads, dict-indexing is enough."""

    payload: dict[str, str]

    def __getitem__(self, key: str) -> str:
        return self.payload[key]


@dataclass
class FakeAsyncpgConn:
    """Records every execute/fetch/fetchrow call; returns queued results."""

    execute_result: str = "UPDATE 1"
    fetchrow_result: FakeRow | None = None
    fetch_result: list[FakeRow] = field(default_factory=list)
    calls: list[tuple[str, str, tuple[Any, ...]]] = field(default_factory=list)
    closed: bool = False

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", sql, args))
        return self.execute_result

    async def fetchrow(self, sql: str, *args: Any) -> FakeRow | None:
        self.calls.append(("fetchrow", sql, args))
        return self.fetchrow_result

    async def fetch(self, sql: str, *args: Any) -> list[FakeRow]:
        self.calls.append(("fetch", sql, args))
        return self.fetch_result

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def store_and_conn() -> tuple[PostgresStore, FakeAsyncpgConn]:
    """Pre-connected store wrapped around the fake connection."""

    store = PostgresStore(dsn="postgres://fake")
    conn = FakeAsyncpgConn()
    store._conn = conn  # type: ignore[attr-defined]
    return store, conn


def _sample_case(case_uri: str = "urn:c:1") -> Case:
    return Case(
        case_uri=case_uri,
        process_uri="urn:p:1",
        status=CaseStatus.OPEN,
        state=CaseState(),
    )


def _sample_process(uri: str = "urn:p:1") -> ProcessDefinition:
    return ProcessDefinition(process_uri=uri, name="P", allowed_actions=[])


# --- lifecycle / connection guard ---------------------------------------


async def test_c_property_raises_when_not_connected() -> None:
    store = PostgresStore(dsn="postgres://fake")
    with pytest.raises(RuntimeError, match="not connected"):
        _ = store._c  # type: ignore[attr-defined]


async def test_close_resets_connection_to_none(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    await store.close()
    assert conn.closed is True
    assert store._conn is None  # type: ignore[attr-defined]


async def test_close_is_idempotent_when_never_connected() -> None:
    store = PostgresStore(dsn="postgres://fake")
    await store.close()  # no-op; line 80->exit


async def test_aexit_closes_via_context_manager(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    """Exercise ``__aexit__`` directly — ``__aenter__`` requires asyncpg."""

    store, conn = store_and_conn
    await store.__aexit__(None, None, None)
    assert conn.closed is True


# --- process queries -----------------------------------------------------


async def test_list_processes_orders_by_seq(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    proc = _sample_process()
    conn.fetch_result = [FakeRow(payload={"data": proc.model_dump_json()})]

    out = await store.list_processes()

    assert len(out) == 1
    assert out[0].process_uri == proc.process_uri
    sql = conn.calls[0][1]
    assert "ORDER BY seq" in sql
    assert "FROM processes" in sql


# --- case queries: find_cases clause matrix -----------------------------


async def test_find_cases_without_filters_emits_no_where(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    await store.find_cases()
    _, sql, args = conn.calls[0]
    assert "WHERE" not in sql
    assert args == ()


async def test_find_cases_with_status_only(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    await store.find_cases(status=CaseStatus.OPEN)
    _, sql, args = conn.calls[0]
    assert "status = $1" in sql
    assert "WHERE" in sql
    assert args == ("open",)


async def test_find_cases_with_process_only(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    await store.find_cases(process_uri="urn:p:1")
    _, sql, args = conn.calls[0]
    assert "process_uri = $1" in sql
    assert args == ("urn:p:1",)


async def test_find_cases_with_both_filters_orders_params(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    await store.find_cases(status=CaseStatus.SUSPENDED, process_uri="urn:p:1")
    _, sql, args = conn.calls[0]
    assert "status = $1" in sql
    assert "process_uri = $2" in sql
    assert " AND " in sql
    assert args == ("suspended", "urn:p:1")


async def test_find_cases_returns_parsed_cases(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    case = _sample_case()
    conn.fetch_result = [FakeRow(payload={"data": case.persistable_json()})]

    out = await store.find_cases()

    assert len(out) == 1
    assert out[0].case_uri == case.case_uri


# --- case update: optimistic lock ---------------------------------------


async def test_update_case_raises_on_zero_rows_updated(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    conn.execute_result = "UPDATE 0"

    with pytest.raises(OptimisticLockError):
        await store.update_case(_sample_case())


async def test_update_case_passes_on_one_row(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    conn.execute_result = "UPDATE 1"

    await store.update_case(_sample_case())  # no raise

    _, sql, args = conn.calls[-1]
    assert "UPDATE cases SET" in sql
    # version is incremented in the SET, and the WHERE pins the old version.
    # case starts at version=0, write should be at version=1 with WHERE version=0.
    assert args[3] == 1
    assert args[5] == 0


# --- audit queries -------------------------------------------------------


def _sample_activity() -> ProvOActivity:
    return ProvOActivity(
        activity_uri="urn:a:1",
        case_uri="urn:c:1",
        action_uri="urn:act:1",
    )


async def test_list_all_orders_by_seq(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    activity = _sample_activity()
    conn.fetch_result = [FakeRow(payload={"data": activity.model_dump_json()})]

    out = await store.list_all()

    assert len(out) == 1
    assert out[0].activity_uri == activity.activity_uri
    sql = conn.calls[0][1]
    assert "FROM activities" in sql
    assert "ORDER BY seq" in sql


async def test_list_by_case_no_limit_no_offset(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    await store.list_by_case("urn:c:1")
    _, sql, args = conn.calls[0]
    assert "LIMIT" not in sql
    assert "OFFSET" not in sql
    assert args == ("urn:c:1",)


async def test_list_by_case_with_limit_adds_limit_and_offset(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    await store.list_by_case("urn:c:1", limit=10, offset=5)
    _, sql, args = conn.calls[0]
    assert "LIMIT $2" in sql
    assert "OFFSET $3" in sql
    assert args == ("urn:c:1", 10, 5)


async def test_list_by_case_with_offset_only(
    store_and_conn: tuple[PostgresStore, FakeAsyncpgConn],
) -> None:
    store, conn = store_and_conn
    await store.list_by_case("urn:c:1", offset=7)
    _, sql, args = conn.calls[0]
    assert "OFFSET $2" in sql
    assert "LIMIT" not in sql
    assert args == ("urn:c:1", 7)
