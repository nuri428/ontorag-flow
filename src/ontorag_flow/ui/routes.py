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
    CounterfactualError,
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


def _build_process_svg(process: Any) -> str:
    """Render a CMMN-style diagram of a process as inline SVG (no JS, no chart lib).

    Layout:
      - Each allowed action becomes a rounded rectangle node, arranged in a
        grid of three columns.
      - ``constraints.requires[a] = [b]``        → arrow b → a labeled "requires".
      - ``constraints.immediately_after[a] = b`` → arrow b → a labeled "→".
      - ``constraints.mutex = [[a, b]]``         → dashed double-headed line.
      - ``constraints.at_most_once = [a]``       → "×1" badge on the node.
      - ``timer_events``                         → small clock node above the
        target action with an arrow into it.

    The function is pure and returns the SVG markup as a string so the
    template inlines it (``{{ svg | safe }}``). Strings are HTML-escaped at
    insertion to defuse process URIs that happen to contain ``<`` or ``&``.
    """

    from html import escape

    cols = 3
    node_w, node_h = 220, 56
    gap_x, gap_y = 60, 90
    pad = 30

    actions = list(process.allowed_actions or [])
    constraints = process.constraints or {}
    timer_events = process.timer_events or []
    at_most_once = set(constraints.get("at_most_once") or [])
    requires = constraints.get("requires") or {}
    immediately_after = constraints.get("immediately_after") or {}
    mutex_pairs = constraints.get("mutex") or []

    positions: dict[str, tuple[int, int]] = {}
    for index, action_uri in enumerate(actions):
        row, col = divmod(index, cols)
        x = pad + col * (node_w + gap_x)
        y = pad + row * (node_h + gap_y)
        positions[action_uri] = (x, y)

    rows = (len(actions) + cols - 1) // cols if actions else 1
    width = pad * 2 + cols * node_w + (cols - 1) * gap_x
    height = pad * 2 + rows * (node_h + gap_y)

    def _short(uri: str) -> str:
        return uri.rsplit(":", 1)[-1] or uri

    def _center(uri: str) -> tuple[int, int]:
        x, y = positions[uri]
        return x + node_w // 2, y + node_h // 2

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Process diagram for {escape(process.process_uri)}">'
    ]
    # arrow-head marker
    parts.append(
        '<defs><marker id="arrow" viewBox="0 -5 10 10" refX="10" refY="0" '
        'markerWidth="6" markerHeight="6" orient="auto">'
        '<path d="M0,-5L10,0L0,5" fill="#57606a"/></marker></defs>'
    )

    # constraint edges first so node rects overlay them
    for target, prereqs in requires.items():
        if target not in positions:
            continue
        for prereq in prereqs or []:
            if prereq not in positions:
                continue
            sx, sy = _center(prereq)
            tx, ty = _center(target)
            parts.append(
                f'<line x1="{sx}" y1="{sy}" x2="{tx}" y2="{ty}" stroke="#0969da" '
                f'stroke-width="1.4" marker-end="url(#arrow)"/>'
                f'<text x="{(sx + tx) // 2}" y="{(sy + ty) // 2 - 4}" '
                f'fill="#0969da" font-size="11" text-anchor="middle">requires</text>'
            )

    for target, prereq in immediately_after.items():
        if target not in positions or prereq not in positions:
            continue
        sx, sy = _center(prereq)
        tx, ty = _center(target)
        parts.append(
            f'<line x1="{sx}" y1="{sy}" x2="{tx}" y2="{ty}" stroke="#1a7f37" '
            f'stroke-width="1.6" marker-end="url(#arrow)"/>'
            f'<text x="{(sx + tx) // 2}" y="{(sy + ty) // 2 - 4}" '
            f'fill="#1a7f37" font-size="11" text-anchor="middle">immediately after</text>'
        )

    for pair in mutex_pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        a, b = pair
        if a not in positions or b not in positions:
            continue
        ax, ay = _center(a)
        bx, by = _center(b)
        parts.append(
            f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="#cf222e" '
            f'stroke-width="1.4" stroke-dasharray="6,4"/>'
            f'<text x="{(ax + bx) // 2}" y="{(ay + by) // 2 - 4}" '
            f'fill="#cf222e" font-size="11" text-anchor="middle">mutex</text>'
        )

    # action nodes
    for action_uri, (x, y) in positions.items():
        label = escape(_short(action_uri))
        full = escape(action_uri)
        once_badge = (
            f'<text x="{x + node_w - 8}" y="{y + 14}" fill="#9a6700" '
            f'font-size="11" text-anchor="end">×1</text>'
            if action_uri in at_most_once
            else ""
        )
        parts.append(
            f"<g><title>{full}</title>"
            f'<rect x="{x}" y="{y}" rx="8" ry="8" width="{node_w}" height="{node_h}" '
            f'fill="#ffffff" stroke="#0969da" stroke-width="1.4"/>'
            f'<text x="{x + node_w // 2}" y="{y + node_h // 2 + 4}" '
            f'text-anchor="middle" font-size="13" fill="#1f2328">{label}</text>'
            f"{once_badge}"
            f"</g>"
        )

    # timer event nodes (above target action with an arrow in)
    for index, entry in enumerate(timer_events):
        if not isinstance(entry, dict):
            continue
        target = entry.get("action")
        if target not in positions:
            continue
        tx, ty = _center(target)
        timer_x = positions[target][0] + index * 18
        timer_y = positions[target][1] - 38
        after = entry.get("after_minutes", 0)
        parts.append(
            f"<g><title>fires after {escape(str(after))} minutes</title>"
            f'<circle cx="{timer_x + 12}" cy="{timer_y + 12}" r="12" '
            f'fill="#fff8c5" stroke="#d4a72c" stroke-width="1.4"/>'
            f'<text x="{timer_x + 12}" y="{timer_y + 16}" text-anchor="middle" '
            f'font-size="10" fill="#7a4f01">⏱</text>'
            f'<line x1="{timer_x + 12}" y1="{timer_y + 24}" x2="{tx}" y2="{ty}" '
            f'stroke="#d4a72c" stroke-width="1.2" marker-end="url(#arrow)"/>'
            f"</g>"
        )

    parts.append("</svg>")
    return "".join(parts)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request,
    status: str | None = None,
    ticked: str | None = None,
    error: str | None = None,
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
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _ctx(cases=cases, status=status, ticked=ticked, error=error),
    )


@router.post("/tick", include_in_schema=False)
async def ui_tick(
    manager: CaseManager = Depends(get_case_manager),
) -> RedirectResponse:
    """Fire elapsed timer events across all open cases, then redirect home."""

    from urllib.parse import quote

    try:
        fired = await manager.tick()
    except CaseManagerError as exc:
        return RedirectResponse(
            f"/ui/?error={quote(f'{type(exc).__name__}: {exc}')}", status_code=303
        )
    return RedirectResponse(f"/ui/?ticked={len(fired)}", status_code=303)


@router.get("/processes", response_class=HTMLResponse, include_in_schema=False)
async def processes_page(
    request: Request, manager: CaseManager = Depends(get_case_manager)
) -> HTMLResponse:
    """List loaded process definitions with quick stats."""

    processes = await manager.list_processes()
    rows = []
    for process in processes:
        cases = await manager.find_cases(process_uri=process.process_uri)
        rows.append(
            {
                "process": process,
                "case_count": len(cases),
                "open_count": sum(1 for case in cases if case.status.value == "open"),
            }
        )
    return templates.TemplateResponse(request, "processes.html", _ctx(rows=rows))


@router.get(
    "/processes/{process_uri}/diagram",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def process_diagram(
    request: Request,
    process_uri: str,
    manager: CaseManager = Depends(get_case_manager),
) -> HTMLResponse:
    """CMMN-style inline SVG of allowed actions + constraints + timer events.

    No external JS / no chart library — the SVG is built from the process
    definition's data in :func:`_build_process_svg` and inlined into the
    template. Layout is a simple grid (actions in rows of 3), constraints
    overlaid as labeled edges.
    """

    process = await manager.get_process(process_uri)
    if process is None:
        raise HTTPException(status_code=404, detail=f"No such process: {process_uri}")
    svg = _build_process_svg(process)
    return templates.TemplateResponse(
        request, "process_diagram.html", _ctx(process=process, svg=svg)
    )


@router.get("/processes/{process_uri}", response_class=HTMLResponse, include_in_schema=False)
async def process_detail(
    request: Request,
    process_uri: str,
    manager: CaseManager = Depends(get_case_manager),
    store=Depends(get_store),
) -> HTMLResponse:
    """Single-process analytics — status mix, hottest actions, average history length."""

    from collections import Counter

    process = await manager.get_process(process_uri)
    if process is None:
        raise HTTPException(status_code=404, detail=f"No such process: {process_uri}")

    cases = await manager.find_cases(process_uri=process_uri)
    case_uris = {case.case_uri for case in cases}

    activities = await store.list_all()
    activities = [activity for activity in activities if activity.case_uri in case_uris]

    status_counts = Counter(case.status.value for case in cases)
    action_counts = Counter(activity.action_uri for activity in activities)
    history_lengths = [len(case.history) for case in cases]
    avg_history = sum(history_lengths) / len(history_lengths) if history_lengths else 0.0

    return templates.TemplateResponse(
        request,
        "process_detail.html",
        _ctx(
            process=process,
            case_count=len(cases),
            status_counts=dict(status_counts),
            top_actions=action_counts.most_common(10),
            activity_count=len(activities),
            avg_history=avg_history,
            max_history=max(history_lengths) if history_lengths else 0,
        ),
    )


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


# --- engine inspector ("why did the engine recommend that?") ------------


@router.get(
    "/cases/{case_uri}/explain",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def case_explain(
    request: Request,
    case_uri: str,
    manager: CaseManager = Depends(get_case_manager),
) -> HTMLResponse:
    """Decision-engine inspector — proposals plus the engine's ``trace`` dict."""

    case = await manager.get_case(case_uri)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No such case: {case_uri}")

    explanation = None
    error: str | None = None
    try:
        explanation = await manager.explain_next(case_uri)
    except (NoEngineConfiguredError, EngineUnavailableError) as exc:
        error = f"Decision engine unavailable: {exc}"
    except CaseManagerError as exc:
        error = f"{type(exc).__name__}: {exc}"

    return templates.TemplateResponse(
        request,
        "explain.html",
        _ctx(case=case, explanation=explanation, error=error),
    )


# --- counterfactual (Pearl Rung 3) ---------------------------------------


@router.get(
    "/cases/{case_uri}/counterfactual",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def counterfactual_form(
    request: Request,
    case_uri: str,
    swap: str,
    registry: ActionRegistry = Depends(get_registry),
    manager: CaseManager = Depends(get_case_manager),
    store=Depends(get_store),
) -> HTMLResponse:
    """Show a form pre-populated with the swap activity, asking what to put in its place."""

    case = await manager.get_case(case_uri)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No such case: {case_uri}")
    swap_activity = await store.get(swap)
    if swap_activity is None:
        raise HTTPException(status_code=404, detail=f"No such activity: {swap}")
    actions = sorted(action.uri for action in registry.all())
    return templates.TemplateResponse(
        request,
        "counterfactual.html",
        _ctx(case=case, swap_activity=swap_activity, actions=actions, result=None, error=None),
    )


@router.post(
    "/cases/{case_uri}/counterfactual",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def counterfactual_submit(
    request: Request,
    case_uri: str,
    swap_activity_uri: str = Form(...),
    action_uri: str = Form(...),
    params_json: str = Form(default="{}"),
    registry: ActionRegistry = Depends(get_registry),
    manager: CaseManager = Depends(get_case_manager),
    store=Depends(get_store),
) -> HTMLResponse:
    """Replay the case with the swapped action and render the result inline."""

    import json

    case = await manager.get_case(case_uri)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No such case: {case_uri}")
    swap_activity = await store.get(swap_activity_uri)
    actions = sorted(action.uri for action in registry.all())

    error: str | None = None
    result = None
    try:
        params = json.loads(params_json) if params_json.strip() else {}
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
        result = await manager.counterfactual(
            case_uri,
            swap_activity_uri=swap_activity_uri,
            action_uri=action_uri,
            params=params,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        error = f"Invalid params JSON: {exc}"
    except (NoEngineConfiguredError, EngineUnavailableError) as exc:
        error = f"Engine unavailable: {exc}"
    except CounterfactualError as exc:
        error = f"CounterfactualError: {exc}"
    except CaseManagerError as exc:
        error = f"{type(exc).__name__}: {exc}"

    return templates.TemplateResponse(
        request,
        "counterfactual.html",
        _ctx(
            case=case,
            swap_activity=swap_activity,
            actions=actions,
            result=result,
            error=error,
        ),
    )
