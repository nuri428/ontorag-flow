"""The Action abstraction — a first-class, ontology-grounded unit of work.

Every action declares its side effects upfront (no hidden mutation), validates
preconditions against the current case state, executes to produce an
:class:`ActionResult`, and yields a PROV-O activity for the audit trail. This is
the heart of the framework: decision engines *propose* actions, the executor
*runs* them, and the audit log *remembers* them.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

from ontorag_flow.core.state import CaseState


class SideEffectKind(str, Enum):
    """The categories of effect an action may declare.

    Declaring effects upfront lets the executor, reviewers, and policies reason
    about blast radius *before* anything runs.
    """

    NONE = "none"
    CASE_STATE = "case_state"
    ABOX_WRITE = "abox_write"
    EXTERNAL_API = "external_api"
    HUMAN = "human"


def _new_activity_uri() -> str:
    return f"urn:ontorag-flow:activity:{uuid4()}"


class ActionResult(BaseModel):
    """The outcome of executing an action.

    The action performs any genuinely external side effects itself (HTTP, ABox
    writes), but it does *not* mutate case state directly. Instead it declares
    the intended state delta here; the executor applies it immutably.
    """

    action_uri: str
    success: bool = True
    outputs: dict[str, Any] = Field(default_factory=dict)
    state_changes: dict[str, Any] = Field(
        default_factory=dict,
        description="Property updates to merge into the case state.",
    )
    goal_change: dict[str, Any] | None = Field(
        default=None,
        description="If set, replaces the case goal.",
    )
    error: str | None = None


class ActionProposal(BaseModel):
    """A recommendation to run an action, emitted by a decision engine.

    Carried here (rather than only in ``engines/``) because it is part of the
    action vocabulary; decision engines arrive from v0.3 onward.
    """

    action_uri: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    proposed_by: str | None = None


class ProvOActivity(BaseModel):
    """A PROV-O ``prov:Activity`` describing one executed action.

    Captures the forensic "who did what, when, using what, producing what, after
    what" that the audit trail is built from.
    """

    activity_uri: str = Field(default_factory=_new_activity_uri)
    action_uri: str
    agent: str | None = Field(default=None, description="prov:wasAssociatedWith")
    started_at: datetime | None = Field(default=None, description="prov:startedAtTime")
    ended_at: datetime | None = Field(default=None, description="prov:endedAtTime")
    used: dict[str, Any] = Field(default_factory=dict, description="prov:used (inputs)")
    generated: dict[str, Any] = Field(
        default_factory=dict, description="prov:wasGeneratedBy (outputs)"
    )
    informed_by: str | None = Field(
        default=None, description="prov:wasInformedBy (previous activity in the case)"
    )
    success: bool = True
    error: str | None = None

    def to_jsonld(self) -> dict[str, Any]:
        """Render a minimal PROV-O JSON-LD node (richer export lands in v0.6)."""

        node: dict[str, Any] = {
            "@context": {"prov": "http://www.w3.org/ns/prov#"},
            "@id": self.activity_uri,
            "@type": "prov:Activity",
            "prov:wasAssociatedWith": self.agent,
            "prov:used": self.used,
            "prov:generated": self.generated,
            "ontoragflow:action": self.action_uri,
            "ontoragflow:success": self.success,
        }
        if self.started_at is not None:
            node["prov:startedAtTime"] = self.started_at.isoformat()
        if self.ended_at is not None:
            node["prov:endedAtTime"] = self.ended_at.isoformat()
        if self.informed_by is not None:
            node["prov:wasInformedBy"] = self.informed_by
        if self.error is not None:
            node["ontoragflow:error"] = self.error
        return node


@runtime_checkable
class Action(Protocol):
    """Structural contract every action satisfies.

    Implementations declare identity (``uri``/``name``), an ``input_schema``
    (a Pydantic model), and their ``side_effects``, then provide the lifecycle
    methods. See :class:`BaseAction` for sensible defaults.
    """

    uri: str
    name: str
    description: str
    input_schema: type[BaseModel]
    side_effects: frozenset[SideEffectKind]

    async def validate(self, params: BaseModel, state: CaseState) -> bool: ...

    async def execute(self, params: BaseModel, state: CaseState) -> ActionResult: ...

    async def compensate(self, result: ActionResult) -> None: ...

    def audit_record(self, result: ActionResult) -> ProvOActivity: ...


class BaseAction(abc.ABC):
    """Convenience base implementing :class:`Action` with default behaviour.

    Subclasses must set the class attributes and implement :meth:`execute`.
    :meth:`validate` defaults to allowing execution, :meth:`compensate` is a
    no-op (overridden once saga support lands in v0.7), and :meth:`audit_record`
    builds the action-specific part of the PROV-O activity (the executor enriches
    it with timing, agent and causal links).
    """

    uri: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    input_schema: ClassVar[type[BaseModel]]
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.NONE})

    async def validate(self, params: BaseModel, state: CaseState) -> bool:
        """Pre-execution precondition check. Defaults to permissible."""

        return True

    @abc.abstractmethod
    async def execute(self, params: BaseModel, state: CaseState) -> ActionResult:
        """Perform the action and return its result."""

    async def compensate(self, result: ActionResult) -> None:
        """Rollback hook (saga pattern). No-op until v0.7."""

        return None

    def audit_record(self, result: ActionResult) -> ProvOActivity:
        """Build the activity skeleton; the executor fills timing/agent/links."""

        generated: dict[str, Any] = dict(result.outputs)
        if result.state_changes:
            generated["state_changes"] = result.state_changes
        if result.goal_change is not None:
            generated["goal_change"] = result.goal_change
        return ProvOActivity(
            action_uri=self.uri,
            generated=generated,
            success=result.success,
            error=result.error,
        )


def utcnow() -> datetime:
    """Timezone-aware current UTC time (used for PROV-O timestamps)."""

    return datetime.now(tz=timezone.utc)
