"""Process definition endpoints — register and inspect process definitions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ontorag_flow.api.deps import get_case_manager
from ontorag_flow.core.case_manager import CaseManager
from ontorag_flow.core.process import ProcessDefinition

router = APIRouter(prefix="/processes", tags=["processes"])


@router.post("", operation_id="load_process", response_model=ProcessDefinition)
async def load_process(
    process: ProcessDefinition,
    manager: CaseManager = Depends(get_case_manager),
) -> ProcessDefinition:
    """Register (or replace) a process definition."""

    return await manager.register_process(process)


@router.get("", operation_id="list_processes", response_model=list[ProcessDefinition])
async def list_processes(
    manager: CaseManager = Depends(get_case_manager),
) -> list[ProcessDefinition]:
    """List all registered process definitions."""

    return await manager.list_processes()


@router.get(
    "/{process_uri}",
    operation_id="get_process",
    response_model=ProcessDefinition,
)
async def get_process(
    process_uri: str,
    manager: CaseManager = Depends(get_case_manager),
) -> ProcessDefinition:
    """Fetch one process definition by URI."""

    process = await manager.get_process(process_uri)
    if process is None:
        raise HTTPException(status_code=404, detail=f"No such process: {process_uri}")
    return process
