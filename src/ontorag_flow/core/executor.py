"""Action executor — validate, run, apply state, audit.

This is the single place where an action's lifecycle is driven. Decision logic
lives in ``engines/``; the executor is deliberately mechanical:

1. coerce raw params against the action's ``input_schema``;
2. check the action's precondition against current state;
3. run the action, timing it;
4. apply the declared state delta immutably;
5. record a PROV-O activity (linked to the previous one in the case).

Validation failures *raise* (nothing happened, so no activity). Execution
failures are *caught and audited* (the attempt happened and must be on record).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ontorag_flow.core.action import (
    Action,
    ActionResult,
    ProvOActivity,
    SideEffectKind,
    utcnow,
)
from ontorag_flow.core.audit import AuditStore, InMemoryAuditStore
from ontorag_flow.core.state import CaseState
from ontorag_flow.log import get_logger

logger = get_logger(__name__)

# P7: actions with any of these side effects do something externally visible
# (HTTP call, ABox write, human notification). For those we record a "pending"
# activity *before* the action runs, then upsert the same row to completed/
# failed once we know the outcome — so an audit-store outage between
# "external effect happened" and "we tried to log it" can't orphan the
# external effect. CASE_STATE-only / NONE actions keep the single-write path.
_EXTERNALLY_VISIBLE_EFFECTS: frozenset[SideEffectKind] = frozenset(
    {SideEffectKind.EXTERNAL_API, SideEffectKind.ABOX_WRITE, SideEffectKind.HUMAN}
)


class ActionValidationError(Exception):
    """Raised when params are malformed or a precondition is not met.

    No side effect ran and no activity is recorded — the action never started.
    """


class ExecutionOutcome:
    """The full record of one executor run."""

    def __init__(
        self,
        *,
        result: ActionResult,
        state: CaseState,
        activity: ProvOActivity,
    ) -> None:
        self.result = result
        self.state = state
        self.activity = activity


class ActionExecutor:
    """Runs actions and records their provenance."""

    def __init__(
        self,
        *,
        audit_store: AuditStore | None = None,
        agent: str = "urn:ontorag-flow:agent:system",
    ) -> None:
        self.audit_store: AuditStore = audit_store or InMemoryAuditStore()
        self.agent = agent

    def coerce_params(self, action: Action, raw_params: dict[str, Any]):
        """Validate ``raw_params`` against the action schema, or raise.

        Returns the typed Pydantic params instance.
        """

        try:
            return action.input_schema.model_validate(raw_params)
        except PydanticValidationError as exc:
            raise ActionValidationError(f"Invalid params for {action.uri}: {exc.errors()}") from exc

    async def validate(self, action: Action, raw_params: dict[str, Any], state: CaseState) -> bool:
        """Schema-validate params and run the action's precondition check."""

        params = self.coerce_params(action, raw_params)
        return await action.validate(params, state)

    async def execute(
        self,
        action: Action,
        raw_params: dict[str, Any],
        state: CaseState,
        *,
        informed_by: str | None = None,
    ) -> ExecutionOutcome:
        """Validate, execute, apply state changes, and audit a single action.

        Args:
            action: The action to run.
            raw_params: Untyped parameter mapping (coerced to ``input_schema``).
            state: The case state the action runs against.
            informed_by: URI of the prior activity in this case, for the
                ``prov:wasInformedBy`` causal chain.

        Returns:
            An :class:`ExecutionOutcome` with the result, the new state, and the
            recorded activity.

        Raises:
            ActionValidationError: If params are invalid or the precondition
                fails. Nothing is executed or recorded.
        """

        params = self.coerce_params(action, raw_params)

        if not await action.validate(params, state):
            raise ActionValidationError(f"Precondition failed for {action.uri}")

        started_at = utcnow()
        common_audit_fields: dict[str, Any] = {
            "case_uri": state.case_uri,
            "state_before": dict(state.properties),
            "goal_before": dict(state.goal) if state.goal is not None else None,
            "agent": self.agent,
            "started_at": started_at,
            "used": params.model_dump(mode="json"),
            "informed_by": informed_by,
        }

        # P7: for externally-visible actions, record a pending row first and
        # carry its activity_uri forward so the post-execute write upserts the
        # same row. CASE_STATE-only actions use a single write (today's path).
        write_ahead = bool(action.side_effects & _EXTERNALLY_VISIBLE_EFFECTS)
        pending_uri: str | None = None
        if write_ahead:
            pending = action.audit_record(ActionResult(action_uri=action.uri)).model_copy(
                update={
                    **common_audit_fields,
                    "status": "pending",
                    "success": False,
                }
            )
            await self.audit_store.record(pending)
            pending_uri = pending.activity_uri

        try:
            result = await action.execute(params, state)
        except Exception as exc:  # noqa: BLE001 — failed attempts must be audited
            logger.exception("Action %s failed during execute", action.uri)
            result = ActionResult(action_uri=action.uri, success=False, error=str(exc))
            new_state = state
        else:
            new_state = state.apply(result)
        ended_at = utcnow()

        final_update: dict[str, Any] = {
            **common_audit_fields,
            "ended_at": ended_at,
            "status": "completed" if result.success else "failed",
        }
        if pending_uri is not None:
            final_update["activity_uri"] = pending_uri  # upsert the pending row
        activity = action.audit_record(result).model_copy(update=final_update)
        await self.audit_store.record(activity)

        return ExecutionOutcome(result=result, state=new_state, activity=activity)
