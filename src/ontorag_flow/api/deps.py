"""Shared FastAPI dependencies.

The action registry is created once per app and stored on ``app.state`` so route
handlers resolve the same instance the MCP layer and CLI share.
"""

from __future__ import annotations

from fastapi import Request

from ontorag_flow.core.registry import ActionRegistry


def get_registry(request: Request) -> ActionRegistry:
    """Return the app-wide :class:`ActionRegistry`."""

    return request.app.state.registry
