"""PostgresStore tests.

The integration tests require a live PostgreSQL — set ``ONTORAG_FLOW_PG_DSN``
(e.g. ``postgresql://user:pass@localhost/ontorag_flow_test``) to run them. Without
it they are skipped. The connection-guard test always runs (no DB needed).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.state import CaseState
from ontorag_flow.stores.postgres import PostgresStore

_DSN = os.getenv("ONTORAG_FLOW_PG_DSN")
requires_pg = pytest.mark.skipif(
    not _DSN, reason="set ONTORAG_FLOW_PG_DSN to run Postgres integration tests"
)


def test_store_requires_connection() -> None:
    store = PostgresStore("postgresql://invalid/none")
    with pytest.raises(RuntimeError):
        _ = store._c  # not connected yet


@pytest_asyncio.fixture
async def pg_store() -> AsyncIterator[PostgresStore]:
    store = PostgresStore(_DSN)  # type: ignore[arg-type]
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@requires_pg
async def test_process_and_case_roundtrip(pg_store: PostgresStore) -> None:
    proc = ProcessDefinition(process_uri="urn:p:pg", name="PG", allowed_actions=["urn:a:1"])
    await pg_store.save_process(proc)
    assert await pg_store.get_process("urn:p:pg") == proc

    case = Case(
        case_uri="urn:c:pg", process_uri="urn:p:pg", state=CaseState(case_uri="urn:c:pg")
    )
    await pg_store.create_case(case)
    await pg_store.update_case(case.with_status(CaseStatus.CLOSED))

    reloaded = await pg_store.get_case("urn:c:pg")
    assert reloaded is not None and reloaded.status is CaseStatus.CLOSED
    assert len(await pg_store.find_cases(status=CaseStatus.CLOSED)) >= 1
