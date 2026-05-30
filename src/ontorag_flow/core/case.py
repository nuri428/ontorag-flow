"""Case — a long-running, ontology-grounded unit of work.

A case is *not* a script. It is a context that carries state, a goal, and a
history of what has happened, governed by a process definition. The next action
is decided at runtime (by a decision engine, from v0.3); in v0.2 actions are
chosen explicitly by the caller.

Cases are immutable: every transition returns a new :class:`Case`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ontorag_flow.core.action import ProvOActivity, utcnow
from ontorag_flow.core.state import CaseState


class CaseStatus(StrEnum):
    """Lifecycle states a case can be in."""

    OPEN = "open"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (CaseStatus.CLOSED, CaseStatus.FAILED)


class CaseEvent(BaseModel):
    """One entry in a case's history — a recorded action execution."""

    model_config = ConfigDict(frozen=True)

    activity_uri: str
    action_uri: str
    at: datetime
    success: bool


class Case(BaseModel):
    """An immutable snapshot of a case."""

    model_config = ConfigDict(frozen=True)

    case_uri: str
    process_uri: str
    state: CaseState
    status: CaseStatus = CaseStatus.OPEN
    # History is derived from the activities table (the audit log is the
    # authority — premortem P5). The field stays on the in-memory model so
    # callers (compensation, UI, demos, API responses) read it naturally;
    # stores explicitly exclude it when persisting (see Case.PERSIST_EXCLUDE)
    # so the case row no longer grows unboundedly with every event.
    # CaseManager.get_case/find_cases hydrate this on load.
    history: tuple[CaseEvent, ...] = ()
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    version: int = Field(
        default=0,
        description=(
            "Optimistic-lock generation counter; bumped by every successful "
            "update so concurrent writers detect lost updates."
        ),
    )

    @property
    def last_activity_uri(self) -> str | None:
        """URI of the most recent activity, for ``prov:wasInformedBy`` chaining."""

        return self.history[-1].activity_uri if self.history else None

    def record_execution(self, activity: ProvOActivity, new_state: CaseState) -> Case:
        """Return a new case with the execution appended and state advanced.

        Args:
            activity: The PROV-O activity produced by the executor.
            new_state: The case state after the action's changes were applied.
        """

        event = CaseEvent(
            activity_uri=activity.activity_uri,
            action_uri=activity.action_uri,
            at=activity.ended_at or utcnow(),
            success=activity.success,
        )
        return self.model_copy(
            update={
                "state": new_state,
                "history": self.history + (event,),
                "updated_at": utcnow(),
            }
        )

    def with_status(self, status: CaseStatus) -> Case:
        """Return a copy with the status changed and ``updated_at`` refreshed."""

        return self.model_copy(update={"status": status, "updated_at": utcnow()})

    def persistable_json(self) -> str:
        """JSON the store should persist — history is excluded (audit is authority, P5)."""

        return self.model_dump_json(exclude={"history"})
