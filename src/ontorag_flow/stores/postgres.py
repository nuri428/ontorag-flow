"""PostgreSQL-backed persistence (production backend).

``PostgresStore`` mirrors :class:`~ontorag_flow.stores.sqlite.SqliteStore` — same
JSON-in-``data``-column schema, same Protocols (ProcessStore, CaseStore, and the
audit store) — over asyncpg. Because the orchestration layer depends only on the
Protocols, swapping SQLite for Postgres is a wiring change, not a code change.

``asyncpg`` is imported lazily inside :meth:`connect`, so this module imports
without the ``postgres`` extra installed; only opening a connection requires it.
"""

from __future__ import annotations

from typing import Any

from ontorag_flow.core.action import ProvOActivity
from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.log import get_logger
from ontorag_flow.stores.base import OptimisticLockError

logger = get_logger(__name__)

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS processes (
        uri  TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        data TEXT NOT NULL,
        seq  BIGSERIAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cases (
        uri         TEXT PRIMARY KEY,
        process_uri TEXT NOT NULL,
        status      TEXT NOT NULL,
        data        TEXT NOT NULL,
        version     INTEGER NOT NULL DEFAULT 0,
        seq         BIGSERIAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        uri      TEXT PRIMARY KEY,
        case_uri TEXT,
        data     TEXT NOT NULL,
        seq      BIGSERIAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status)",
    "CREATE INDEX IF NOT EXISTS idx_cases_process ON cases(process_uri)",
    # Composite serves both "all activities for a case" and the ORDER BY seq
    # scan that case-manager hydration depends on (P5).
    "CREATE INDEX IF NOT EXISTS idx_activities_case_seq ON activities(case_uri, seq)",
)


class PostgresStore:
    """asyncpg-backed store for processes, cases, and provenance."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: Any = None

    async def connect(self) -> None:
        """Open the connection and create the schema if needed."""

        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - requires the `postgres` extra
            raise RuntimeError("asyncpg is not installed; install the 'postgres' extra.") from exc

        self._conn = await asyncpg.connect(self._dsn)
        for statement in _SCHEMA_STATEMENTS:
            await self._conn.execute(statement)
        logger.info("Postgres store ready")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> PostgresStore:
        await self.connect()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    @property
    def _c(self) -> Any:
        if self._conn is None:
            raise RuntimeError("PostgresStore is not connected — call connect() first.")
        return self._conn

    # --- ProcessStore -----------------------------------------------------

    async def save_process(self, process: ProcessDefinition) -> None:
        await self._c.execute(
            """
            INSERT INTO processes (uri, name, data) VALUES ($1, $2, $3)
            ON CONFLICT (uri) DO UPDATE SET name = EXCLUDED.name, data = EXCLUDED.data
            """,
            process.process_uri,
            process.name,
            process.model_dump_json(),
        )

    async def get_process(self, process_uri: str) -> ProcessDefinition | None:
        row = await self._c.fetchrow("SELECT data FROM processes WHERE uri = $1", process_uri)
        return ProcessDefinition.model_validate_json(row["data"]) if row else None

    async def list_processes(self) -> list[ProcessDefinition]:
        rows = await self._c.fetch("SELECT data FROM processes ORDER BY seq")
        return [ProcessDefinition.model_validate_json(r["data"]) for r in rows]

    # --- CaseStore --------------------------------------------------------

    async def create_case(self, case: Case) -> None:
        await self._c.execute(
            "INSERT INTO cases (uri, process_uri, status, data, version) VALUES ($1, $2, $3, $4, $5)",
            case.case_uri,
            case.process_uri,
            case.status.value,
            case.persistable_json(),
            case.version,
        )

    async def get_case(self, case_uri: str) -> Case | None:
        row = await self._c.fetchrow("SELECT data FROM cases WHERE uri = $1", case_uri)
        return Case.model_validate_json(row["data"]) if row else None

    async def update_case(self, case: Case) -> None:
        """Optimistic update: write version+1 only if the row is still at version."""

        expected_version = case.version
        new_version = expected_version + 1
        next_case = case.model_copy(update={"version": new_version})
        result = await self._c.execute(
            "UPDATE cases SET process_uri = $1, status = $2, data = $3, version = $4 "
            "WHERE uri = $5 AND version = $6",
            next_case.process_uri,
            next_case.status.value,
            next_case.persistable_json(),
            new_version,
            case.case_uri,
            expected_version,
        )
        # asyncpg execute returns a status string like "UPDATE 1" / "UPDATE 0".
        if isinstance(result, str) and result.endswith(" 0"):
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
        clauses: list[str] = []
        args: list[str] = []
        if status is not None:
            args.append(status.value)
            clauses.append(f"status = ${len(args)}")
        if process_uri is not None:
            args.append(process_uri)
            clauses.append(f"process_uri = ${len(args)}")

        query = "SELECT data FROM cases"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY seq"

        rows = await self._c.fetch(query, *args)
        return [Case.model_validate_json(r["data"]) for r in rows]

    # --- AuditStore -------------------------------------------------------

    async def record(self, activity: ProvOActivity) -> None:
        await self._c.execute(
            """
            INSERT INTO activities (uri, case_uri, data) VALUES ($1, $2, $3)
            ON CONFLICT (uri) DO UPDATE SET case_uri = EXCLUDED.case_uri, data = EXCLUDED.data
            """,
            activity.activity_uri,
            activity.case_uri,
            activity.model_dump_json(),
        )

    async def list_all(self) -> list[ProvOActivity]:
        rows = await self._c.fetch("SELECT data FROM activities ORDER BY seq")
        return [ProvOActivity.model_validate_json(r["data"]) for r in rows]

    async def list_by_case(
        self,
        case_uri: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ProvOActivity]:
        query = "SELECT data FROM activities WHERE case_uri = $1 ORDER BY seq"
        args: list = [case_uri]
        if limit is not None:
            args.extend([limit, offset])
            query += f" LIMIT ${len(args) - 1} OFFSET ${len(args)}"
        elif offset > 0:
            args.append(offset)
            query += f" OFFSET ${len(args)}"
        rows = await self._c.fetch(query, *args)
        return [ProvOActivity.model_validate_json(r["data"]) for r in rows]

    async def get(self, activity_uri: str) -> ProvOActivity | None:
        row = await self._c.fetchrow("SELECT data FROM activities WHERE uri = $1", activity_uri)
        return ProvOActivity.model_validate_json(row["data"]) if row else None
