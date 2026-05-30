"""Case manager — the orchestration core for cases.

It owns the case lifecycle: create a case from a process, run an explicitly
chosen action against it, advance state, chain provenance, and auto-close on
goal satisfaction. It deliberately contains *no* decision logic — which action
to run next is the job of a decision engine (v0.3+). Here the caller chooses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ontorag_flow.core.action import (
    ActionProposal,
    ActionResult,
    ProvOActivity,
    SideEffectKind,
    utcnow,
)
from ontorag_flow.core.case import Case, CaseEvent, CaseStatus
from ontorag_flow.core.executor import ActionExecutor, ExecutionOutcome
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.registry import ActionRegistry
from ontorag_flow.core.state import CaseState
from ontorag_flow.log import get_logger
from ontorag_flow.stores.base import CaseStore, ProcessStore

if TYPE_CHECKING:
    from ontorag_flow.engines.base import DecisionEngine
    from ontorag_flow.engines.causal import CounterfactualResult

# A factory builds a decision engine for a given process (so per-process rules
# are honoured). Injected by the composition root to keep core free of any
# runtime dependency on the engines layer.
EngineFactory = Callable[[ProcessDefinition], "DecisionEngine"]

logger = get_logger(__name__)


class CaseManagerError(Exception):
    """Base class for case-manager errors."""


class ProcessNotFoundError(CaseManagerError):
    """The referenced process definition does not exist."""


class CaseNotFoundError(CaseManagerError):
    """The referenced case does not exist."""


class ActionNotAllowedError(CaseManagerError):
    """The action is not in the process's allowed set."""


class ActionNotFoundError(CaseManagerError):
    """The action URI is not in the registry."""


class CaseClosedError(CaseManagerError):
    """The case is not open, so it cannot accept further actions."""


class NoEngineConfiguredError(CaseManagerError):
    """No decision engine factory was provided, so proposals are unavailable."""


class CompensationError(CaseManagerError):
    """Compensation cannot proceed (bad target, missing snapshot, etc.)."""


class CaseStateTransitionError(CaseManagerError):
    """An invalid case lifecycle transition was requested (e.g. resume an open case)."""


class ConstraintViolationError(CaseManagerError):
    """The process's mutex/requires constraints reject this action right now."""


class CounterfactualError(CaseManagerError):
    """Counterfactual replay cannot proceed (missing snapshot, unsupported engine, etc.)."""


COMPENSATION_ACTION_URI = "urn:ontorag-flow:action:_Compensate"
"""Synthetic action URI marking a composite compensation event in case history."""


def new_case_uri() -> str:
    """Mint a fresh case URI."""

    return f"urn:ontorag-flow:case:{uuid4()}"


class CaseManager:
    """Creates cases and runs actions against them, persisting every step."""

    def __init__(
        self,
        *,
        case_store: CaseStore,
        process_store: ProcessStore,
        executor: ActionExecutor,
        registry: ActionRegistry,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self._cases = case_store
        self._processes = process_store
        self._executor = executor
        self._registry = registry
        self._engine_factory = engine_factory

    # --- process facade ---------------------------------------------------

    async def register_process(self, process: ProcessDefinition) -> ProcessDefinition:
        """Persist (or replace) a process definition."""

        await self._processes.save_process(process)
        logger.info("Registered process %s", process.process_uri)
        return process

    async def get_process(self, process_uri: str) -> ProcessDefinition | None:
        return await self._processes.get_process(process_uri)

    async def list_processes(self) -> list[ProcessDefinition]:
        return await self._processes.list_processes()

    # --- case reads -------------------------------------------------------

    async def get_case(self, case_uri: str) -> Case | None:
        return await self._cases.get_case(case_uri)

    async def find_cases(
        self,
        *,
        status: CaseStatus | None = None,
        process_uri: str | None = None,
    ) -> list[Case]:
        return await self._cases.find_cases(status=status, process_uri=process_uri)

    # --- decisions --------------------------------------------------------

    async def propose_next(self, case_uri: str) -> list[ActionProposal]:
        """Ask the decision engine for ranked next-action proposals.

        This never executes anything — recommendation is not execution.

        Raises:
            NoEngineConfiguredError: If no engine factory was provided.
            CaseNotFoundError, ProcessNotFoundError: As applicable.
        """

        if self._engine_factory is None:
            raise NoEngineConfiguredError("No decision engine configured for this case manager.")

        case = await self._cases.get_case(case_uri)
        if case is None:
            raise CaseNotFoundError(case_uri)
        process = await self._processes.get_process(case.process_uri)
        if process is None:
            raise ProcessNotFoundError(case.process_uri)

        engine = self._engine_factory(process)
        return await engine.propose_next(case, process)

    async def counterfactual(
        self,
        case_uri: str,
        *,
        swap_activity_uri: str,
        action_uri: str,
        params: dict[str, Any],
        target: dict[str, Any] | None = None,
    ) -> CounterfactualResult:
        """Replay a case with a swapped action and return the hypothetical outcome.

        Routes the call to the case's resolved decision engine; only causal
        engines support counterfactual replay (Pearl Rung 3 via ontorag).

        Raises:
            NoEngineConfiguredError: If the manager has no engine_factory.
            CaseNotFoundError, ProcessNotFoundError: As applicable.
            CounterfactualError: If the engine does not support counterfactual
                replay, or the swap activity is missing / lacks a state_before
                snapshot.
        """

        if self._engine_factory is None:
            raise NoEngineConfiguredError("No decision engine configured.")

        case = await self._cases.get_case(case_uri)
        if case is None:
            raise CaseNotFoundError(case_uri)
        process = await self._processes.get_process(case.process_uri)
        if process is None:
            raise ProcessNotFoundError(case.process_uri)

        engine = self._engine_factory(process)
        replay = getattr(engine, "counterfactual_replay", None)
        if replay is None:
            raise CounterfactualError(
                f"The engine for process {case.process_uri} does not support "
                "counterfactual replay (need a CausalSimulationEngine)."
            )

        activity = await self._executor.audit_store.get(swap_activity_uri)
        if activity is None:
            raise CounterfactualError(f"Unknown swap activity: {swap_activity_uri}.")
        if activity.state_before is None:
            raise CounterfactualError(
                f"Activity {swap_activity_uri} has no state_before snapshot (it predates v0.7)."
            )

        return await replay(
            case_uri=case_uri,
            swap_activity_uri=swap_activity_uri,
            evidence=activity.state_before,
            counterfactual_action_uri=action_uri,
            counterfactual_params=params,
            target=target if target is not None else (process.goal or {}),
        )

    # --- case writes ------------------------------------------------------

    async def create_case(
        self,
        process_uri: str,
        *,
        initial_state: dict[str, Any] | None = None,
        case_uri: str | None = None,
    ) -> Case:
        """Create and persist a new case governed by a process.

        Raises:
            ProcessNotFoundError: If the process does not exist.
        """

        process = await self._processes.get_process(process_uri)
        if process is None:
            raise ProcessNotFoundError(process_uri)

        uri = case_uri or new_case_uri()
        properties = {**process.initial_state, **(initial_state or {})}
        state = CaseState(
            case_uri=uri,
            properties=properties,
            goal=process.goal or None,
        )
        case = Case(case_uri=uri, process_uri=process_uri, state=state)
        await self._cases.create_case(case)
        logger.info("Created case %s from process %s", uri, process_uri)
        return case

    async def execute_action(
        self,
        case_uri: str,
        action_uri: str,
        params: dict[str, Any],
    ) -> tuple[Case, ExecutionOutcome]:
        """Run a chosen action against a case and persist the result.

        Validates that the case is open and the action is permitted by the
        process, executes it, advances the case (auto-closing if the goal is
        reached), and persists both the case and its audit activity.

        Raises:
            CaseNotFoundError, ProcessNotFoundError, CaseClosedError,
            ActionNotAllowedError, ActionNotFoundError: As applicable.
        """

        case = await self._cases.get_case(case_uri)
        if case is None:
            raise CaseNotFoundError(case_uri)
        if case.status is not CaseStatus.OPEN:
            raise CaseClosedError(f"Case {case_uri} is {case.status.value}, not open.")

        process = await self._processes.get_process(case.process_uri)
        if process is None:
            raise ProcessNotFoundError(case.process_uri)
        if not process.allows(action_uri):
            raise ActionNotAllowedError(
                f"Action {action_uri} is not allowed by process {case.process_uri}."
            )

        _enforce_constraints(action_uri, process, case)

        action = self._registry.get(action_uri)
        if action is None:
            raise ActionNotFoundError(action_uri)

        outcome = await self._executor.execute(
            action,  # pyright: ignore[reportArgumentType] -- see registry.py docstring
            params,
            case.state,
            informed_by=case.last_activity_uri,
        )

        new_case = case.record_execution(outcome.activity, outcome.state)
        if new_case.state.goal_reached():
            new_case = new_case.with_status(CaseStatus.CLOSED)
            logger.info("Case %s reached its goal and was closed.", case_uri)
        elif SideEffectKind.HUMAN in action.side_effects:
            new_case = new_case.with_status(CaseStatus.SUSPENDED)
            logger.info("Case %s suspended for human review.", case_uri)

        await self._cases.update_case(new_case)
        return new_case, outcome

    # --- saga compensation -------------------------------------------------

    async def compensate(self, case_uri: str, *, target_activity_uri: str | None = None) -> Case:
        """Undo a contiguous tail of executed actions on a case.

        For each undone activity (most-recent first) the action's ``compensate``
        hook is invoked so external side effects can be rolled back. The case
        state itself is restored from the ``state_before`` snapshot of the
        earliest undone activity (never replayed — replay would re-trigger any
        external effects). The undone events are replaced in the case history
        by a single composite compensation event; the original activities remain
        in the audit log.

        Args:
            case_uri: Case to compensate.
            target_activity_uri: If given, undo from this activity (inclusive)
                to the end of history. If None, undo the entire history.

        Returns:
            The compensated case (status set to ``OPEN``).

        Raises:
            CaseNotFoundError: Unknown case.
            CompensationError: Nothing to undo, target not found in history, or
                a prior compensation lies between target and end (unsupported).
        """

        case = await self._cases.get_case(case_uri)
        if case is None:
            raise CaseNotFoundError(case_uri)
        if not case.history:
            raise CompensationError(f"Case {case_uri} has no actions to compensate.")

        undo_start = self._find_undo_start(case, target_activity_uri)
        kept = case.history[:undo_start]
        undone = case.history[undo_start:]

        if any(event.action_uri == COMPENSATION_ACTION_URI for event in undone):
            raise CompensationError("Cannot compensate across a previous compensation event.")

        audit_store = self._executor.audit_store
        first_undone_activity = await audit_store.get(undone[0].activity_uri)
        if first_undone_activity is None or first_undone_activity.state_before is None:
            raise CompensationError(
                "Missing state_before snapshot; this activity predates v0.7 and cannot be compensated."
            )

        for event in reversed(undone):
            activity = await audit_store.get(event.activity_uri)
            if activity is None:
                continue
            action = self._registry.get(activity.action_uri)
            if action is None:
                logger.warning(
                    "No registered action for %s; external rollback skipped.",
                    activity.action_uri,
                )
                continue
            await action.compensate(_activity_to_result(activity))

        new_state = CaseState(
            case_uri=case.case_uri,
            properties=dict(first_undone_activity.state_before),
            goal=(
                dict(first_undone_activity.goal_before)
                if first_undone_activity.goal_before is not None
                else None
            ),
        )

        started, ended = utcnow(), utcnow()
        compensation = ProvOActivity(
            action_uri=COMPENSATION_ACTION_URI,
            case_uri=case.case_uri,
            agent=self._executor.agent,
            started_at=started,
            ended_at=ended,
            used={"target_activity_uri": target_activity_uri},
            generated={"compensated": [event.activity_uri for event in undone]},
            informed_by=kept[-1].activity_uri if kept else None,
            state_before=dict(case.state.properties),
            goal_before=dict(case.state.goal) if case.state.goal is not None else None,
            success=True,
        )
        await audit_store.record(compensation)

        new_event = CaseEvent(
            activity_uri=compensation.activity_uri,
            action_uri=COMPENSATION_ACTION_URI,
            at=ended,
            success=True,
        )
        new_case = case.model_copy(
            update={
                "state": new_state,
                "history": kept + (new_event,),
                "status": CaseStatus.OPEN,
                "updated_at": utcnow(),
            }
        )
        await self._cases.update_case(new_case)
        logger.info("Compensated %d activities on case %s.", len(undone), case_uri)
        return new_case

    def _find_undo_start(self, case: Case, target_activity_uri: str | None) -> int:
        if target_activity_uri is None:
            return 0
        for index, event in enumerate(case.history):
            if event.activity_uri == target_activity_uri:
                return index
        raise CompensationError(
            f"Activity {target_activity_uri} is not in case {case.case_uri}'s history."
        )

    # --- lifecycle: suspend / resume / fork --------------------------------

    async def suspend(self, case_uri: str) -> Case:
        """Pause an open case; rejected if the case is not currently open."""

        case = await self._require_case(case_uri)
        if case.status is not CaseStatus.OPEN:
            raise CaseStateTransitionError(
                f"Case {case_uri} is {case.status.value}; only open cases can be suspended."
            )
        new_case = case.with_status(CaseStatus.SUSPENDED)
        await self._cases.update_case(new_case)
        return new_case

    async def resume(self, case_uri: str) -> Case:
        """Reopen a suspended case; rejected if the case is not suspended."""

        case = await self._require_case(case_uri)
        if case.status is not CaseStatus.SUSPENDED:
            raise CaseStateTransitionError(
                f"Case {case_uri} is {case.status.value}; only suspended cases can be resumed."
            )
        new_case = case.with_status(CaseStatus.OPEN)
        await self._cases.update_case(new_case)
        return new_case

    async def fork(
        self,
        case_uri: str,
        *,
        new_uri: str | None = None,
    ) -> Case:
        """Create a new open case copying state and history from one source.

        Args:
            case_uri: The case to fork from.
            new_uri: URI for the new case; auto-generated if omitted.
        """

        source = await self._require_case(case_uri)
        target_uri = new_uri or new_case_uri()
        new_state = source.state.model_copy(update={"case_uri": target_uri})
        new_case = Case(
            case_uri=target_uri,
            process_uri=source.process_uri,
            state=new_state,
            status=CaseStatus.OPEN,
            history=source.history,
        )
        await self._cases.create_case(new_case)
        logger.info("Forked case %s -> %s", case_uri, target_uri)
        return new_case

    async def _require_case(self, case_uri: str) -> Case:
        case = await self._cases.get_case(case_uri)
        if case is None:
            raise CaseNotFoundError(case_uri)
        return case


def _activity_to_result(activity: ProvOActivity) -> ActionResult:
    """Reconstruct an :class:`ActionResult` from a recorded activity.

    ``BaseAction.audit_record`` packs ``state_changes`` / ``goal_change`` into
    ``activity.generated``; this peels them back out so an action's
    ``compensate`` hook sees the same result shape it produced.
    """

    generated = dict(activity.generated)
    state_changes = generated.pop("state_changes", {})
    goal_change = generated.pop("goal_change", None)
    return ActionResult(
        action_uri=activity.action_uri,
        success=activity.success,
        outputs=generated,
        state_changes=state_changes if isinstance(state_changes, dict) else {},
        goal_change=goal_change if isinstance(goal_change, dict) else None,
        error=activity.error,
    )


def _enforce_constraints(action_uri: str, process, case: Case) -> None:  # type: ignore[no-untyped-def]
    """Check the process's mutex/requires constraints against current history.

    Mutex: an action cannot run if another member of one of its mutex groups
    has already been executed in this case.
    Requires: an action's prerequisites must all appear in case history first.
    """

    constraints = process.constraints or {}
    executed = {event.action_uri for event in case.history}

    for group in constraints.get("mutex", []) or []:
        if action_uri in group:
            conflict = executed.intersection(set(group) - {action_uri})
            if conflict:
                raise ConstraintViolationError(
                    f"Mutex: {action_uri} cannot run; case already executed {sorted(conflict)}."
                )

    requires = (constraints.get("requires") or {}).get(action_uri, [])
    missing = [prereq for prereq in requires if prereq not in executed]
    if missing:
        raise ConstraintViolationError(
            f"Requires: {action_uri} needs prerequisites {missing} which are not in case history."
        )
