"""Audit log — PROV-O activities recorded for every executed action.

v0.1 keeps the trail in memory. The :class:`AuditStore` Protocol is the seam
that the SQLite/Postgres backends (v0.2+) will implement, so the executor never
depends on a concrete store.
"""

from __future__ import annotations

from typing import Protocol

from ontorag_flow.core.action import ProvOActivity


class AuditStore(Protocol):
    """Append-only store of provenance activities."""

    async def record(self, activity: ProvOActivity) -> None: ...

    async def list_all(self) -> list[ProvOActivity]: ...

    async def list_by_case(self, case_uri: str) -> list[ProvOActivity]: ...

    async def get(self, activity_uri: str) -> ProvOActivity | None: ...


class InMemoryAuditStore:
    """Default in-memory :class:`AuditStore` for v0.1 and tests."""

    def __init__(self) -> None:
        self._activities: list[ProvOActivity] = []

    async def record(self, activity: ProvOActivity) -> None:
        self._activities.append(activity)

    async def list_all(self) -> list[ProvOActivity]:
        return list(self._activities)

    async def list_by_case(self, case_uri: str) -> list[ProvOActivity]:
        return [a for a in self._activities if a.case_uri == case_uri]

    async def get(self, activity_uri: str) -> ProvOActivity | None:
        return next(
            (a for a in self._activities if a.activity_uri == activity_uri),
            None,
        )

    @property
    def last(self) -> ProvOActivity | None:
        """The most recently recorded activity, or None if the log is empty."""

        return self._activities[-1] if self._activities else None
