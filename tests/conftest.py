"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from ontorag_flow.actions.case_state import SetGoal, UpdateCaseProperty
from ontorag_flow.core.audit import InMemoryAuditStore
from ontorag_flow.core.case_manager import CaseManager
from ontorag_flow.core.executor import ActionExecutor
from ontorag_flow.core.registry import default_registry
from ontorag_flow.stores.sqlite import SqliteStore


@pytest.fixture
def audit_store() -> InMemoryAuditStore:
    return InMemoryAuditStore()


@pytest.fixture
def executor(audit_store: InMemoryAuditStore) -> ActionExecutor:
    return ActionExecutor(audit_store=audit_store, agent="urn:test:agent")


@pytest.fixture
def update_property() -> UpdateCaseProperty:
    return UpdateCaseProperty()


@pytest.fixture
def set_goal() -> SetGoal:
    return SetGoal()


@pytest_asyncio.fixture
async def sqlite_store() -> AsyncIterator[SqliteStore]:
    store = SqliteStore(":memory:")
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@pytest_asyncio.fixture
async def case_manager_sqlite(sqlite_store: SqliteStore) -> CaseManager:
    executor = ActionExecutor(audit_store=sqlite_store, agent="urn:test:agent")
    return CaseManager(
        case_store=sqlite_store,
        process_store=sqlite_store,
        executor=executor,
        registry=default_registry(),
    )
