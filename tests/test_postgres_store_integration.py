"""Live Postgres integration tests via testcontainers.

Auto-skips when Docker is unavailable or the ``postgres`` extra is not
installed, so contributors without Docker still get a green ``pytest`` run.
The tests verify that ``PostgresStore``'s SQL actually compiles on real
Postgres (skipif on a DSN env var alone gave us no signal — premortem P3).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio


def _ensure_docker_host_env() -> None:
    """Point the Docker SDK at Docker Desktop's socket when DOCKER_HOST is unset.

    On macOS Docker Desktop, the socket lives at ``~/.docker/run/docker.sock``
    instead of the SDK's default ``/var/run/docker.sock`` — without this nudge
    the integration tests would silently skip on developer machines.
    """

    if "DOCKER_HOST" in os.environ:
        return
    desktop_socket = Path.home() / ".docker" / "run" / "docker.sock"
    if desktop_socket.exists():
        os.environ["DOCKER_HOST"] = f"unix://{desktop_socket}"


_ensure_docker_host_env()

testcontainers = pytest.importorskip(
    "testcontainers.postgres",
    reason="install the 'postgres' extra to run live Postgres integration tests",
)
PostgresContainer = testcontainers.PostgresContainer

from ontorag_flow.core.action import ProvOActivity  # noqa: E402
from ontorag_flow.core.case import Case, CaseStatus  # noqa: E402
from ontorag_flow.core.process import ProcessDefinition  # noqa: E402
from ontorag_flow.core.state import CaseState  # noqa: E402
from ontorag_flow.stores.base import OptimisticLockError  # noqa: E402
from ontorag_flow.stores.postgres import PostgresStore  # noqa: E402


def _docker_available() -> bool:
    try:
        import docker
        from docker.errors import DockerException
    except ImportError:
        return False
    try:
        docker.from_env().ping()
        return True
    except DockerException:
        return False
    except Exception:  # noqa: BLE001 — any startup error means "no Docker"
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker is not running; install Docker Desktop or set DOCKER_HOST to run.",
)


@pytest_asyncio.fixture
async def pg_store() -> AsyncIterator[PostgresStore]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        store = PostgresStore(dsn)
        await store.connect()
        try:
            yield store
        finally:
            await store.close()


async def test_process_and_case_roundtrip_live(pg_store: PostgresStore) -> None:
    proc = ProcessDefinition(process_uri="urn:p:live", name="Live", allowed_actions=["urn:a:1"])
    await pg_store.save_process(proc)
    assert await pg_store.get_process("urn:p:live") == proc

    case = Case(
        case_uri="urn:c:live", process_uri="urn:p:live", state=CaseState(case_uri="urn:c:live")
    )
    await pg_store.create_case(case)
    await pg_store.update_case(case.with_status(CaseStatus.SUSPENDED))

    reloaded = await pg_store.get_case("urn:c:live")
    assert reloaded is not None
    assert reloaded.status is CaseStatus.SUSPENDED
    assert reloaded.version == 1


async def test_optimistic_lock_live(pg_store: PostgresStore) -> None:
    case = Case(
        case_uri="urn:c:lock-live",
        process_uri="urn:p:live",
        state=CaseState(case_uri="urn:c:lock-live"),
    )
    await pg_store.create_case(case)

    first = await pg_store.get_case("urn:c:lock-live")
    assert first is not None
    await pg_store.update_case(first.with_status(CaseStatus.SUSPENDED))

    with pytest.raises(OptimisticLockError):
        await pg_store.update_case(case.with_status(CaseStatus.CLOSED))


async def test_activity_roundtrip_live(pg_store: PostgresStore) -> None:
    activity = ProvOActivity(
        action_uri="urn:act:live",
        case_uri="urn:c:live",
        agent="urn:test:agent",
    )
    await pg_store.record(activity)

    fetched = await pg_store.get(activity.activity_uri)
    assert fetched is not None and fetched.action_uri == "urn:act:live"

    by_case = await pg_store.list_by_case("urn:c:live")
    assert [a.activity_uri for a in by_case] == [activity.activity_uri]
