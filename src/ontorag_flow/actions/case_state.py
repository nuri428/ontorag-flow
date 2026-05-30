"""Case-state actions — the only actions in v0.1.

These touch nothing outside the case: their sole declared side effect is
``CASE_STATE``. They never mutate state directly; they declare the intended
delta in their :class:`ActionResult` and let the executor apply it immutably.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ontorag_flow.core.action import (
    ActionResult,
    BaseAction,
    SideEffectKind,
)
from ontorag_flow.core.state import CaseState


class UpdateCaseProperty(BaseAction):
    """Set a single property on the case state."""

    uri: ClassVar[str] = "urn:ontorag-flow:action:UpdateCaseProperty"
    name: ClassVar[str] = "Update Case Property"
    description: ClassVar[str] = "Set a key/value property on the case state."
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.CASE_STATE})

    class Params(BaseModel):
        key: str = Field(min_length=1, description="Property name to set.")
        value: Any = Field(description="Value to assign to the property.")

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
        return ActionResult(
            action_uri=self.uri,
            success=True,
            outputs={"key": params.key, "value": params.value},
            state_changes={params.key: params.value},
        )


class SetGoal(BaseAction):
    """Declare (or replace) the case's target outcome predicate."""

    uri: ClassVar[str] = "urn:ontorag-flow:action:SetGoal"
    name: ClassVar[str] = "Set Goal"
    description: ClassVar[str] = "Set the case goal predicate, e.g. diagnosed=true."
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.CASE_STATE})

    class Params(BaseModel):
        predicate: str = Field(min_length=1, description="Goal predicate name.")
        value: Any = Field(default=True, description="Target value for the predicate.")

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
        return ActionResult(
            action_uri=self.uri,
            success=True,
            outputs={"predicate": params.predicate, "value": params.value},
            goal_change={params.predicate: params.value},
        )
