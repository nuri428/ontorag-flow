"""SQLite-backed persistence (dev default).

One :class:`SqliteStore` satisfies the :class:`ProcessStore`, :class:`CaseStore`,
and :class:`ontorag_flow.core.audit.AuditStore` Protocols over a single aiosqlite
connection. Rows keep the full Pydantic JSON in a ``data`` column plus a few
indexed columns for filtering — simple, and a clean target for the Postgres
backend (v0.5) to mirror.
"""

from __future__ import annotations

import aiosqlite

from ontorag_flow.core.action import ProvOActivity
from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.log import get_logger
from ontorag_flow.stores.base import OptimisticLockError

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processes (
    uri  TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
    uri         TEXT PRIMARY KEY,
    process_uri TEXT NOT NULL,
    status      TEXT NOT NULL,
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS activities (
    uri      TEXT PRIMARY KEY,
    case_uri TEXT,
    data     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_process ON cases(process_uri);
-- SQLite uses its implicit rowid for ORDER BY when filtered by an
-- indexed column; the single-column index here covers
-- ``WHERE case_uri = ? ORDER BY rowid`` (which case-manager hydration
-- relies on after P5). Postgres uses a composite (case_uri, seq) index
-- in its schema because BIGSERIAL needs explicit help.
CREATE INDEX IF NOT EXISTS idx_activities_case ON activities(case_uri);
"""


class SqliteStore:
    """aiosqlite-backed store for processes, cases, and provenance."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the connection and create the schema if needed."""

        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("SQLite store ready at %s", self._path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> SqliteStore:
        await self.connect()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteStore is not connected — call connect() first.")
        return self._db

    # --- ProcessStore -----------------------------------------------------

    async def save_process(self, process: ProcessDefinition) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO processes (uri, name, data) VALUES (?, ?, ?)",
            (process.process_uri, process.name, process.model_dump_json()),
        )
        await self._conn.commit()

    async def get_process(self, process_uri: str) -> ProcessDefinition | None:
        async with self._conn.execute(
            "SELECT data FROM processes WHERE uri = ?", (process_uri,)
        ) as cursor:
            row = await cursor.fetchone()
        return ProcessDefinition.model_validate_json(row["data"]) if row else None

    async def list_processes(self) -> list[ProcessDefinition]:
        async with self._conn.execute("SELECT data FROM processes ORDER BY rowid") as cursor:
            rows = await cursor.fetchall()
        return [ProcessDefinition.model_validate_json(r["data"]) for r in rows]

    # --- CaseStore --------------------------------------------------------

    async def create_case(self, case: Case) -> None:
        await self._conn.execute(
            "INSERT INTO cases (uri, process_uri, status, data, version) VALUES (?, ?, ?, ?, ?)",
            (
                case.case_uri,
                case.process_uri,
                case.status.value,
                case.persistable_json(),
                case.version,
            ),
        )
        await self._conn.commit()

    async def get_case(self, case_uri: str) -> Case | None:
        async with self._conn.execute(
            "SELECT data FROM cases WHERE uri = ?", (case_uri,)
        ) as cursor:
            row = await cursor.fetchone()
        return Case.model_validate_json(row["data"]) if row else None

    async def update_case(self, case: Case) -> None:
        """Persist the case, asserting nobody else has updated it meanwhile.

        Uses ``case.version`` as the expected current version and writes
        ``version + 1``; rowcount == 0 means another writer won the race.
        """

        expected_version = case.version
        new_version = expected_version + 1
        next_case = case.model_copy(update={"version": new_version})
        cursor = await self._conn.execute(
            "UPDATE cases SET process_uri = ?, status = ?, data = ?, version = ? "
            "WHERE uri = ? AND version = ?",
            (
                next_case.process_uri,
                next_case.status.value,
                next_case.persistable_json(),
                new_version,
                case.case_uri,
                expected_version,
            ),
        )
        await self._conn.commit()
        if cursor.rowcount == 0:
            raise OptimisticLockError(
                f"Case {case.case_uri} was modified by another writer "
                f"(expected version {expected_version})."
            )

    async def find_cases(
        self,
        *,
        status: CaseStatus | None = None,
        process_uri: str | None = None,
    ) -> list[Case]:
        query = "SELECT data FROM cases"
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if process_uri is not None:
            clauses.append("process_uri = ?")
            params.append(process_uri)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY rowid"

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [Case.model_validate_json(r["data"]) for r in rows]

    # --- AuditStore -------------------------------------------------------

    async def record(self, activity: ProvOActivity) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO activities (uri, case_uri, data) VALUES (?, ?, ?)",
            (activity.activity_uri, activity.case_uri, activity.model_dump_json()),
        )
        await self._conn.commit()

    async def list_all(self) -> list[ProvOActivity]:
        async with self._conn.execute("SELECT data FROM activities ORDER BY rowid") as cursor:
            rows = await cursor.fetchall()
        return [ProvOActivity.model_validate_json(r["data"]) for r in rows]

    async def list_by_case(
        self,
        case_uri: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ProvOActivity]:
        query = "SELECT data FROM activities WHERE case_uri = ? ORDER BY rowid"
        params: list = [case_uri]
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset > 0:
            # SQLite needs a LIMIT clause for OFFSET to apply; -1 means "no limit".
            query += " LIMIT -1 OFFSET ?"
            params.append(offset)
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [ProvOActivity.model_validate_json(r["data"]) for r in rows]

    async def get(self, activity_uri: str) -> ProvOActivity | None:
        async with self._conn.execute(
            "SELECT data FROM activities WHERE uri = ?", (activity_uri,)
        ) as cursor:
            row = await cursor.fetchone()
        return ProvOActivity.model_validate_json(row["data"]) if row else None
