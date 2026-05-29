"""Action catalog endpoint — the registered actions and their contracts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ontorag_flow.api.deps import get_registry
from ontorag_flow.core.registry import ActionRegistry

router = APIRouter(prefix="/actions", tags=["actions"])


class ActionInfo(BaseModel):
    uri: str
    name: str
    description: str
    side_effects: list[str]
    input_schema: dict[str, Any]


class ActionListResponse(BaseModel):
    actions: list[ActionInfo]


def _to_info(action: Any) -> ActionInfo:
    return ActionInfo(
        uri=action.uri,
        name=action.name,
        description=action.description,
        side_effects=sorted(effect.value for effect in action.side_effects),
        input_schema=action.input_schema.model_json_schema(),
    )


@router.get("", operation_id="list_actions", response_model=ActionListResponse)
async def list_actions(
    registry: ActionRegistry = Depends(get_registry),
) -> ActionListResponse:
    """Return the registered action catalog."""

    return ActionListResponse(actions=[_to_info(a) for a in registry.all()])
