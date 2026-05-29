"""Human-in-the-loop actions.

Executing one of these signals that the case needs human attention. The case
manager recognises the :class:`~ontorag_flow.core.action.SideEffectKind.HUMAN`
side effect and auto-suspends the case so a human can review and resume it.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from ontorag_flow.core.action import (
    ActionResult,
    BaseAction,
    SideEffectKind,
)
from ontorag_flow.core.state import CaseState


class RequestHumanReview(BaseAction):
    """Mark the case as awaiting a human review."""

    uri: ClassVar[str] = "urn:ontorag-flow:action:RequestHumanReview"
    name: ClassVar[str] = "Request Human Review"
    description: ClassVar[str] = (
        "Hand the case off to a human for review; the case auto-suspends and "
        "resumes only when a human explicitly calls resume."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.HUMAN, SideEffectKind.CASE_STATE}
    )

    class Params(BaseModel):
        reason: str = Field(
            default="Decision engine deferred to human judgment.",
            description="Why the case needs human attention.",
        )

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
        return ActionResult(
            action_uri=self.uri,
            success=True,
            outputs={"reason": params.reason},
            state_changes={
                "awaiting_human_review": True,
                "human_review_reason": params.reason,
            },
        )
