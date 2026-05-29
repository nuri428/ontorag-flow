"""Shared FastAPI dependencies.

The action registry, persistence store, and case manager are created once per app
(see :func:`ontorag_flow.api.main.create_app`) and resolved here so route handlers
share the same instances the MCP layer and CLI use.
"""

from __future__ import annotations

from fastapi import Request

from ontorag_flow.core.case_manager import CaseManager
from ontorag_flow.core.registry import ActionRegistry


def get_registry(request: Request) -> ActionRegistry:
    """Return the app-wide :class:`ActionRegistry`."""

    return request.app.state.registry


def get_case_manager(request: Request) -> CaseManager:
    """Return the app-wide :class:`CaseManager` (requires app lifespan)."""

    return request.app.state.case_manager
