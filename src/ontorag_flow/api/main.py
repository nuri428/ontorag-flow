"""FastAPI application factory.

Wires the action registry, persistence store, and case manager onto ``app.state``
(the store is opened in the lifespan so its connection lives on the serving event
loop), mounts the REST routes, and optionally exposes them as MCP tools.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ontorag_flow import __version__
from ontorag_flow.api.routes import actions, cases, health, processes
from ontorag_flow.config import get_settings
from ontorag_flow.core.executor import ActionExecutor
from ontorag_flow.core.case_manager import CaseManager
from ontorag_flow.core.registry import ActionRegistry, default_registry
from ontorag_flow.log import get_logger
from ontorag_flow.stores.sqlite import SqliteStore

logger = get_logger(__name__)


def create_app(
    *,
    registry: ActionRegistry | None = None,
    store: SqliteStore | None = None,
    db_path: str | None = None,
    agent: str | None = None,
    mount_mcp: bool = True,
) -> FastAPI:
    """Build and return the ontorag-flow FastAPI app.

    Args:
        registry: Action registry; defaults to the built-in catalog.
        store: Pre-connected store to reuse; if omitted, the app opens and owns
            its own SQLite store for the lifespan.
        db_path: SQLite path used when the app owns the store.
        agent: Provenance agent id; defaults to settings.
        mount_mcp: When True, expose the routes as MCP tools at ``/mcp``.
    """

    settings = get_settings()
    resolved_registry = registry or default_registry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_store = store is None
        active_store = store or SqliteStore(db_path or settings.db_path)
        if owns_store:
            await active_store.connect()

        executor = ActionExecutor(
            audit_store=active_store, agent=agent or settings.agent_id
        )
        app.state.store = active_store
        app.state.case_manager = CaseManager(
            case_store=active_store,
            process_store=active_store,
            executor=executor,
            registry=resolved_registry,
        )
        try:
            yield
        finally:
            if owns_store:
                await active_store.close()

    app = FastAPI(
        title="ontorag-flow",
        version=__version__,
        summary="Ontology-grounded adaptive case management — the Kinetic layer.",
        lifespan=lifespan,
    )
    app.state.registry = resolved_registry

    app.include_router(health.router)
    app.include_router(actions.router)
    app.include_router(processes.router)
    app.include_router(cases.router)

    if mount_mcp:
        _mount_mcp(app)

    return app


def _mount_mcp(app: FastAPI) -> None:
    """Mount the fastapi-mcp transport, logging a warning if unavailable."""

    try:
        from fastapi_mcp import FastApiMCP
    except ImportError:  # pragma: no cover - dependency declared in pyproject
        logger.warning("fastapi-mcp not installed; MCP endpoint disabled.")
        return

    mcp = FastApiMCP(app, name="ontorag-flow")
    mcp.mount()
    logger.info("Mounted MCP endpoint at /mcp")
