"""Storage Protocols — the seam between orchestration and persistence.

The case manager and executor depend only on these Protocols, so the backend
(in-memory, SQLite now, Postgres in v0.5) can be swapped without touching them.
The audit side reuses :class:`ontorag_flow.core.audit.AuditStore`.
"""

from __future__ import annotations

from typing import Protocol

from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.process import ProcessDefinition

__all__ = ["ProcessStore", "CaseStore", "OptimisticLockError"]


class OptimisticLockError(RuntimeError):
    """``update_case`` lost the race — another writer moved the version forward.

    The caller should re-fetch the case, re-apply its change on top of the
    fresh state, and retry. The store does not auto-retry because the caller
    knows whether the change is idempotent under the new state.
    """


class ProcessStore(Protocol):
    """Persists process definitions."""

    async def save_process(self, process: ProcessDefinition) -> None: ...

    async def get_process(self, process_uri: str) -> ProcessDefinition | None: ...

    async def list_processes(self) -> list[ProcessDefinition]: ...


class CaseStore(Protocol):
    """Persists cases and their evolving state."""

    async def create_case(self, case: Case) -> None: ...

    async def get_case(self, case_uri: str) -> Case | None: ...

    async def update_case(self, case: Case) -> None: ...

    async def find_cases(
        self,
        *,
        status: CaseStatus | None = None,
        process_uri: str | None = None,
    ) -> list[Case]: ...
