"""Read-only UI routes mounted at ``/ui``.

Templates and the single stylesheet live next to this module so the UI ships
inside the package. The pages reuse the same deps the JSON API uses, so they see
the same state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ontorag_flow import __version__
from ontorag_flow.api.deps import get_case_manager, get_registry, get_store
from ontorag_flow.core.case import CaseStatus
from ontorag_flow.core.case_manager import (
    CaseManager,
    CaseManagerError,
    NoEngineConfiguredError,
)
from ontorag_flow.core.registry import ActionRegistry
from ontorag_flow.engines.selection import EngineUnavailableError

_HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))
static_files = StaticFiles(directory=str(_HERE / "static"))

router = APIRouter(prefix="/ui", tags=["ui"])

__all__ = ["router", "static_files"]


def _ctx(**extra: Any) -> dict[str, Any]:
    """Build the per-page template context. Request is passed positionally."""

    return {"version": __version__, **extra}


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request,
    status: str | None = None,
    manager: CaseManager = Depends(get_case_manager),
) -> HTMLResponse:
    """Open cases plus a status filter."""

    case_status: CaseStatus | None = None
    if status:
        try:
            case_status = CaseStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status}") from exc

    cases = await manager.find_cases(status=case_status)
    return templates.TemplateResponse(request, "dashboard.html", _ctx(cases=cases, status=status))


@router.get("/actions", response_class=HTMLResponse, include_in_schema=False)
async def actions_page(
    request: Request, registry: ActionRegistry = Depends(get_registry)
) -> HTMLResponse:
    """Action library browser."""

    actions = [
        {
            "uri": action.uri,
            "name": action.name,
            "description": action.description,
            "side_effects": sorted(effect.value for effect in action.side_effects),
            "params": sorted(action.input_schema.model_json_schema().get("properties", {}).keys()),
        }
        for action in registry.all()
    ]
    return templates.TemplateResponse(request, "actions.html", _ctx(actions=actions))


@router.get("/cases/{case_uri}", response_class=HTMLResponse, include_in_schema=False)
async def case_detail(
    request: Request,
    case_uri: str,
    error: str | None = None,
    manager: CaseManager = Depends(get_case_manager),
) -> HTMLResponse:
    """One case: state, decision-engine proposals (live), and recent history.

    Mutating actions (suspend/resume/compensate/execute-top-proposal/subcase)
    post to dedicated routes below and 303-redirect back here — keeping the UI
    JS-free while still exposing the lifecycle CLI/API surface in the browser.
    """

    case = await manager.get_case(case_uri)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No such case: {case_uri}")

    proposals: list = []
    proposals_error: str | None = None
    try:
        proposals = await manager.propose_next(case_uri)
    except (NoEngineConfiguredError, EngineUnavailableError) as exc:
        proposals_error = f"Decision engine unavailable: {exc}"
    except CaseManagerError as exc:
        proposals_error = f"{type(exc).__name__}: {exc}"

    subcases = await manager.find_subcases(case_uri)
    parent = await manager.get_case(case.parent_uri) if case.parent_uri else None
    processes = await manager.list_processes()

    return templates.TemplateResponse(
        request,
        "case_detail.html",
        _ctx(
            case=case,
            proposals=proposals,
            proposals_error=proposals_error,
            subcases=subcases,
            parent=parent,
            processes=processes,
            error=error,
        ),
    )


# --- mutating UI actions (form POST → 303 redirect) ----------------------


def _back_to_case(case_uri: str, error: str | None = None) -> RedirectResponse:
    """303 redirect back to case detail (with optional ?error= message)."""

    target = f"/ui/cases/{case_uri}"
    if error:
        from urllib.parse import quote

        target = f"{target}?error={quote(error)}"
    return RedirectResponse(target, status_code=303)


@router.post("/cases/{case_uri}/suspend", include_in_schema=False)
async def ui_suspend(
    case_uri: str, manager: CaseManager = Depends(get_case_manager)
) -> RedirectResponse:
    try:
        await manager.suspend(case_uri)
    except CaseManagerError as exc:
        return _back_to_case(case_uri, error=f"{type(exc).__name__}: {exc}")
    return _back_to_case(case_uri)


@router.post("/cases/{case_uri}/resume", include_in_schema=False)
async def ui_resume(
    case_uri: str, manager: CaseManager = Depends(get_case_manager)
) -> RedirectResponse:
    try:
        await manager.resume(case_uri)
    except CaseManagerError as exc:
        return _back_to_case(case_uri, error=f"{type(exc).__name__}: {exc}")
    return _back_to_case(case_uri)


@router.post("/cases/{case_uri}/compensate", include_in_schema=False)
async def ui_compensate(
    case_uri: str, manager: CaseManager = Depends(get_case_manager)
) -> RedirectResponse:
    try:
        await manager.compensate(case_uri)
    except CaseManagerError as exc:
        return _back_to_case(case_uri, error=f"{type(exc).__name__}: {exc}")
    return _back_to_case(case_uri)


@router.post("/cases/{case_uri}/execute-top", include_in_schema=False)
async def ui_execute_top(
    case_uri: str, manager: CaseManager = Depends(get_case_manager)
) -> RedirectResponse:
    """Run the engine's highest-confidence proposal."""

    try:
        proposals = await manager.propose_next(case_uri)
        if not proposals:
            return _back_to_case(case_uri, error="Engine returned no proposals.")
        top = proposals[0]
        await manager.execute_action(case_uri, top.action_uri, top.params)
    except (NoEngineConfiguredError, EngineUnavailableError) as exc:
        return _back_to_case(case_uri, error=f"Engine unavailable: {exc}")
    except CaseManagerError as exc:
        return _back_to_case(case_uri, error=f"{type(exc).__name__}: {exc}")
    return _back_to_case(case_uri)


@router.post("/cases/{case_uri}/subcase", include_in_schema=False)
async def ui_subcase(
    case_uri: str,
    process_uri: str = Form(...),
    manager: CaseManager = Depends(get_case_manager),
) -> RedirectResponse:
    try:
        child = await manager.create_subcase(case_uri, process_uri)
    except CaseManagerError as exc:
        return _back_to_case(case_uri, error=f"{type(exc).__name__}: {exc}")
    return RedirectResponse(f"/ui/cases/{child.case_uri}", status_code=303)


@router.get("/cases/{case_uri}/audit", response_class=HTMLResponse, include_in_schema=False)
async def case_audit(
    request: Request,
    case_uri: str,
    manager: CaseManager = Depends(get_case_manager),
    store=Depends(get_store),
) -> HTMLResponse:
    """PROV-O activities for one case."""

    if await manager.get_case(case_uri) is None:
        raise HTTPException(status_code=404, detail=f"No such case: {case_uri}")
    activities = await store.list_by_case(case_uri)
    return templates.TemplateResponse(
        request, "audit.html", _ctx(case_uri=case_uri, activities=activities)
    )
