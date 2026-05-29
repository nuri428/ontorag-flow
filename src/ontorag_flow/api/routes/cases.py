"""Case endpoints — create cases, inspect state, and execute actions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ontorag_flow.api.deps import get_case_manager
from ontorag_flow.core.action import ActionProposal, ActionResult, ProvOActivity
from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.case_manager import (
    ActionNotAllowedError,
    ActionNotFoundError,
    CaseClosedError,
    CaseManager,
    CaseNotFoundError,
    NoEngineConfiguredError,
    ProcessNotFoundError,
)
from ontorag_flow.core.executor import ActionValidationError

router = APIRouter(prefix="/cases", tags=["cases"])


class CreateCaseRequest(BaseModel):
    process_uri: str
    initial_state: dict[str, Any] = Field(default_factory=dict)
    case_uri: str | None = None


class ExecuteActionRequest(BaseModel):
    action_uri: str
    params: dict[str, Any] = Field(default_factory=dict)


class ExecuteActionResponse(BaseModel):
    case: Case
    result: ActionResult
    activity: ProvOActivity


class FindCasesRequest(BaseModel):
    status: CaseStatus | None = None
    process_uri: str | None = None


@router.post("", operation_id="create_case", response_model=Case)
async def create_case(
    body: CreateCaseRequest,
    manager: CaseManager = Depends(get_case_manager),
) -> Case:
    """Create a new case from a process definition."""

    try:
        return await manager.create_case(
            body.process_uri,
            initial_state=body.initial_state,
            case_uri=body.case_uri,
        )
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such process: {exc}") from exc


@router.post("/find", operation_id="find_cases", response_model=list[Case])
async def find_cases(
    body: FindCasesRequest,
    manager: CaseManager = Depends(get_case_manager),
) -> list[Case]:
    """Filter cases by status and/or process."""

    return await manager.find_cases(status=body.status, process_uri=body.process_uri)


@router.get("/{case_uri}", operation_id="get_case_state", response_model=Case)
async def get_case_state(
    case_uri: str,
    manager: CaseManager = Depends(get_case_manager),
) -> Case:
    """Return a case's current state, status, and history."""

    case = await manager.get_case(case_uri)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No such case: {case_uri}")
    return case


@router.post(
    "/{case_uri}/propose",
    operation_id="propose_next_action",
    response_model=list[ActionProposal],
)
async def propose_next_action(
    case_uri: str,
    manager: CaseManager = Depends(get_case_manager),
) -> list[ActionProposal]:
    """Run the decision engine and return ranked proposals — no execution."""

    try:
        return await manager.propose_next(case_uri)
    except (CaseNotFoundError, ProcessNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoEngineConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/{case_uri}/execute",
    operation_id="execute_action",
    response_model=ExecuteActionResponse,
)
async def execute_action(
    case_uri: str,
    body: ExecuteActionRequest,
    manager: CaseManager = Depends(get_case_manager),
) -> ExecuteActionResponse:
    """Execute a chosen action against a case and return the new state."""

    try:
        case, outcome = await manager.execute_action(
            case_uri, body.action_uri, body.params
        )
    except (CaseNotFoundError, ProcessNotFoundError, ActionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CaseClosedError, ActionNotAllowedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ExecuteActionResponse(
        case=case, result=outcome.result, activity=outcome.activity
    )
