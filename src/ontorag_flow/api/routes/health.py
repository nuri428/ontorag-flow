"""Liveness endpoint.

Kept shallow on purpose: it must not block on the ontorag MCP round-trip. Deep
connectivity checks live behind the CLI ``status`` command.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ontorag_flow import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", operation_id="health_check", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report that the service process is up."""

    return HealthResponse(status="ok", service="ontorag-flow", version=__version__)
