"""FastAPI application factory.

Wires the action registry onto ``app.state``, mounts the REST routes, and
(optionally) exposes them as MCP tools via fastapi-mcp. MCP mounting is a toggle
so tests can build a plain app without the MCP transport.
"""

from __future__ import annotations

from fastapi import FastAPI

from ontorag_flow import __version__
from ontorag_flow.api.routes import actions, health
from ontorag_flow.core.registry import ActionRegistry, default_registry
from ontorag_flow.log import get_logger

logger = get_logger(__name__)


def create_app(
    *,
    registry: ActionRegistry | None = None,
    mount_mcp: bool = True,
) -> FastAPI:
    """Build and return the ontorag-flow FastAPI app.

    Args:
        registry: Action registry to use; defaults to the built-in catalog.
        mount_mcp: When True, expose the routes as MCP tools at ``/mcp``.
    """

    app = FastAPI(
        title="ontorag-flow",
        version=__version__,
        summary="Ontology-grounded adaptive case management — the Kinetic layer.",
    )
    app.state.registry = registry or default_registry()

    app.include_router(health.router)
    app.include_router(actions.router)

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
