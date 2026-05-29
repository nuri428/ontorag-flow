"""Shared fixtures."""

from __future__ import annotations

import pytest

from ontorag_flow.actions.case_state import SetGoal, UpdateCaseProperty
from ontorag_flow.core.audit import InMemoryAuditStore
from ontorag_flow.core.executor import ActionExecutor


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
