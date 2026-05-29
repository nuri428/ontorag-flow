"""Case state — the context an action runs against.

In v0.1 there is no persisted :class:`Case` yet (that arrives in v0.2). A
:class:`CaseState` is the minimal, immutable snapshot of the properties and goal
that actions read and propose changes to. Mutations are never applied in place;
:meth:`CaseState.apply` returns a *new* state, honouring the project's
immutability rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ontorag_flow.core.action import ActionResult


class CaseState(BaseModel):
    """An immutable snapshot of a case's properties and goal."""

    model_config = ConfigDict(frozen=True)

    case_uri: str | None = Field(
        default=None,
        description="URI of the case in ontorag's ABox, or None for ad-hoc runs.",
    )
    properties: dict[str, Any] = Field(default_factory=dict)
    goal: dict[str, Any] | None = Field(
        default=None,
        description="Target outcome predicate, e.g. {'diagnosed': True}.",
    )

    def with_property(self, key: str, value: Any) -> CaseState:
        """Return a copy with ``key`` set to ``value``."""

        return self.model_copy(update={"properties": {**self.properties, key: value}})

    def apply(self, result: ActionResult) -> CaseState:
        """Return a new state with an action result's declared changes applied.

        Args:
            result: The outcome of executing an action. Its ``state_changes`` are
                merged into ``properties`` and a non-None ``goal_change`` replaces
                the goal.
        """

        new_properties = {**self.properties, **result.state_changes}
        new_goal = result.goal_change if result.goal_change is not None else self.goal
        return self.model_copy(update={"properties": new_properties, "goal": new_goal})

    def goal_reached(self) -> bool:
        """Whether the current properties satisfy every goal predicate.

        A state with no goal is never "reached" — there is nothing to satisfy.
        """

        if not self.goal:
            return False
        return all(self.properties.get(key) == value for key, value in self.goal.items())


EMPTY_STATE: CaseState = CaseState()
"""A blank state, used by ``action run`` when no case exists yet."""
