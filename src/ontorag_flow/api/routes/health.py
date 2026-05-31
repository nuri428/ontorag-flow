"""Liveness + readiness endpoints.

Kubernetes-style split:

- ``/health`` — liveness. Process is up and serving HTTP. Must not block
  on dependencies; k8s uses this to decide whether to restart the pod.
  Returning anything 2xx from this means *the process itself is healthy*.
- ``/health/ready`` — readiness. The persistence store is reachable and
  the case manager is wired (lifespan completed). Returns 503 when the
  store is missing or hasn't been opened yet. k8s uses this to decide
  whether to route traffic.

Deep connectivity checks against ontorag MCP live behind the CLI
``status`` command, not behind /health/ready — they would couple our
readiness to a sister service's availability.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ontorag_flow import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    service: str
    version: str
    checks: dict[str, str]


@router.get("/health", operation_id="health_check", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report that the service process is up (liveness probe)."""

    return HealthResponse(status="ok", service="ontorag-flow", version=__version__)


@router.get(
    "/health/ready",
    operation_id="readiness_check",
    response_model=ReadinessResponse,
    responses={503: {"description": "One or more readiness checks failed."}},
)
async def ready(request: Request) -> ReadinessResponse:
    """Report that the service is ready to accept traffic (readiness probe)."""

    checks: dict[str, str] = {}

    # Graceful shutdown: flip to 503 as soon as the lifespan flagged
    # shutting_down — gives the load balancer time to drain traffic
    # before connections close.
    if getattr(request.app.state, "shutting_down", False):
        raise HTTPException(
            status_code=503,
            detail={"status": "shutting_down", "service": "ontorag-flow"},
        )

    store = getattr(request.app.state, "store", None)
    if store is None:
        checks["store"] = "missing"
    else:
        # Touch the store. SqliteStore + PostgresStore both expose list_processes;
        # if the underlying connection is closed it raises.
        try:
            await store.list_processes()
            checks["store"] = "ok"
        except Exception as exc:  # noqa: BLE001 — surface as readiness failure
            checks["store"] = f"error: {type(exc).__name__}"

    case_manager = getattr(request.app.state, "case_manager", None)
    checks["case_manager"] = "ok" if case_manager is not None else "missing"

    response = ReadinessResponse(
        status="ok" if all(v == "ok" for v in checks.values()) else "not_ready",
        service="ontorag-flow",
        version=__version__,
        checks=checks,
    )
    if response.status != "ok":
        raise HTTPException(status_code=503, detail=response.model_dump())
    return response
