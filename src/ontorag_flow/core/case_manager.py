"""Case manager — the orchestration core for cases.

It owns the case lifecycle: create a case from a process, run an explicitly
chosen action against it, advance state, chain provenance, and auto-close on
goal satisfaction. It deliberately contains *no* decision logic — which action
to run next is the job of a decision engine (v0.3+). Here the caller chooses.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
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
    from ontorag_flow.engines.base import DecisionEngine, EngineExplanation
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


_REDACTION_MASK = "***"


def _redact(payload: dict[str, Any], patterns: list[str]) -> dict[str, Any]:
    """Return a copy of ``payload`` with values for matching keys masked.

    ``patterns`` are ``fnmatch`` globs ('ssn', 'patient.*', 'api_key',
    '*token*'). Matching is recursive: nested dicts are walked, lists of
    dicts too. Non-dict / non-list values pass through unchanged.
    """

    from fnmatch import fnmatch

    if not patterns:
        return payload

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (_REDACTION_MASK if any(fnmatch(k, pat) for pat in patterns) else _walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    # _walk on a dict always returns a dict (its first branch); type-narrow
    # without an assert so bandit's B101 stays clean.
    walked = _walk(payload)
    return walked if isinstance(walked, dict) else payload


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
        case = await self._cases.get_case(case_uri)
        if case is None:
            return None
        return await self._hydrate_history(case)

    async def find_cases(
        self,
        *,
        status: CaseStatus | None = None,
        process_uri: str | None = None,
    ) -> list[Case]:
        cases = await self._cases.find_cases(status=status, process_uri=process_uri)
        return [await self._hydrate_history(case) for case in cases]

    async def find_subcases(self, parent_uri: str) -> list[Case]:
        """Return every case whose parent_uri matches (subprocess children)."""

        all_cases = await self._cases.find_cases()
        return [await self._hydrate_history(c) for c in all_cases if c.parent_uri == parent_uri]

    async def _hydrate_history(self, case: Case) -> Case:
        """Rebuild ``case.history`` from the authoritative audit log (P5)."""

        activities = await self._executor.audit_store.list_by_case(case.case_uri)
        events = tuple(_activity_to_event(activity) for activity in activities)
        return case.model_copy(update={"history": events})

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

        case = await self.get_case(case_uri)
        if case is None:
            raise CaseNotFoundError(case_uri)
        process = await self._processes.get_process(case.process_uri)
        if process is None:
            raise ProcessNotFoundError(case.process_uri)

        engine = self._engine_factory(process)
        return await engine.propose_next(case, process)

    async def explain_next(self, case_uri: str) -> EngineExplanation:
        """Ask the decision engine for proposals *plus* a "why" trace.

        Engines opt-in by implementing :meth:`explain`; those that do not
        fall back to a no-trace explanation built from ``propose_next``.

        Raises:
            NoEngineConfiguredError: If no engine factory was provided.
            CaseNotFoundError, ProcessNotFoundError: As applicable.
        """

        # Import inside the method to keep the core / engines layering
        # one-way (engines depend on core; core does not depend on engines
        # at module load time).
        from ontorag_flow.engines.base import EngineExplanation as _Explanation

        if self._engine_factory is None:
            raise NoEngineConfiguredError("No decision engine configured for this case manager.")

        case = await self.get_case(case_uri)
        if case is None:
            raise CaseNotFoundError(case_uri)
        process = await self._processes.get_process(case.process_uri)
        if process is None:
            raise ProcessNotFoundError(case.process_uri)

        engine = self._engine_factory(process)
        explain = getattr(engine, "explain", None)
        if explain is not None:
            explanation = await explain(case, process)
        else:
            # Default explanation for engines that haven't opted in.
            proposals = await engine.propose_next(case, process)
            explanation = _Explanation(
                engine_kind=type(engine).__name__,
                proposals=proposals,
                trace={"note": "engine does not implement explain(); only proposals available"},
            )

        # Redact sensitive keys from the trace (and from proposal params),
        # mirroring what manager.execute_action does for activity rows.
        # The UI displays this verbatim, so this is the natural choke point.
        if process.audit_redact:
            explanation = explanation.model_copy(
                update={
                    "trace": _redact(explanation.trace, process.audit_redact),
                    "proposals": [
                        p.model_copy(update={"params": _redact(p.params, process.audit_redact)})
                        for p in explanation.proposals
                    ],
                },
            )
        return explanation

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

        case = await self.get_case(case_uri)
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

        case = await self.get_case(case_uri)  # hydrated history is needed by constraint checks
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

        # Audit redaction: mask sensitive keys before the activity is
        # persisted. Applied to used / generated / metadata; the snapshot
        # in state_before is also masked. Patterns are fnmatch globs from
        # process.audit_redact (e.g. ['ssn', 'patient.*', 'api_key']).
        if process.audit_redact:
            outcome.activity = outcome.activity.model_copy(
                update={
                    "used": _redact(outcome.activity.used, process.audit_redact),
                    "generated": _redact(outcome.activity.generated, process.audit_redact),
                    "state_before": (
                        _redact(outcome.activity.state_before, process.audit_redact)
                        if outcome.activity.state_before is not None
                        else None
                    ),
                },
            )
            await self._executor.audit_store.record(outcome.activity)

        # Skeleton deviation tag: when the process declares a happy-path
        # skeleton, compare *this* action against the next expected entry.
        # Counts only non-compensation history events so a saga rollback
        # doesn't pretend we advanced past where we did. ExecutionOutcome
        # is a plain mutable container, so we replace its activity in-place
        # and re-record (audit_store.record is upsert in both backends).
        if process.skeleton:
            position = sum(
                1 for event in case.history if event.action_uri != COMPENSATION_ACTION_URI
            )
            on_path = position < len(process.skeleton)
            expected = process.skeleton[position] if on_path else None
            deviated = (not on_path) or (expected != action_uri)
            if deviated:
                outcome.activity = outcome.activity.model_copy(
                    update={
                        "metadata": {
                            **outcome.activity.metadata,
                            "deviated_from_skeleton": True,
                            "skeleton_expected": expected,
                            "skeleton_position": position,
                        },
                    },
                )
                await self._executor.audit_store.record(outcome.activity)

        new_case = case.record_execution(outcome.activity, outcome.state)
        if new_case.state.goal_reached():
            new_case = new_case.with_status(CaseStatus.CLOSED)
            logger.info("Case %s reached its goal and was closed.", case_uri)
        elif SideEffectKind.HUMAN in action.side_effects:
            new_case = new_case.with_status(CaseStatus.SUSPENDED)
            logger.info("Case %s suspended for human review.", case_uri)

        await self._cases.update_case(new_case)

        # If this case just closed and has a parent, project the outcome
        # onto the parent so its decision engine can react.
        if new_case.status is CaseStatus.CLOSED and new_case.parent_uri is not None:
            await self._notify_parent_of_child_close(new_case)

        return new_case, outcome

    async def _notify_parent_of_child_close(self, child: Case) -> None:
        """Mark the parent's state with the child's terminal snapshot."""

        parent = await self.get_case(child.parent_uri)  # type: ignore[arg-type]
        if parent is None:
            logger.warning(
                "Subcase %s closed but parent %s is gone; nothing to project.",
                child.case_uri,
                child.parent_uri,
            )
            return
        updates = {
            f"subcase_{child.case_uri}_closed": True,
            f"subcase_{child.case_uri}_state": dict(child.state.properties),
        }
        new_state = parent.state.model_copy(
            update={"properties": {**parent.state.properties, **updates}}
        )
        await self._cases.update_case(
            parent.model_copy(update={"state": new_state, "updated_at": utcnow()})
        )

    # --- timer events ------------------------------------------------------

    async def prune_audit(self, *, older_than_days: int, dry_run: bool = False) -> list[str]:
        """Delete closed/failed cases (and their activities) older than N days.

        Only terminal cases (``closed`` / ``failed``) are eligible — open
        and suspended cases are work-in-progress, not history. "Age" is
        measured from ``Case.updated_at``. Returns the list of case URIs
        that were removed (or *would be* if ``dry_run=True``).

        This is the data side of the operations guide's retention
        policy. Schedule from cron (``ontorag-flow audit prune
        --older-than 90``); without scheduling, the audit table grows
        without bound and eventually presses on disk + backup.
        """

        cutoff = utcnow() - timedelta(days=older_than_days)
        removed: list[str] = []
        # Terminal cases only — walk both terminal statuses.
        for status in (CaseStatus.CLOSED, CaseStatus.FAILED):
            cases = await self._cases.find_cases(status=status)
            for case in cases:
                if case.updated_at >= cutoff:
                    continue
                if dry_run:
                    removed.append(case.case_uri)
                    continue
                # Delete the activities first, then the case row. The order
                # matters for foreign-key-aware stores (Postgres); SQLite
                # accepts either.
                deleter = getattr(self._executor.audit_store, "delete_by_case", None)
                if deleter is not None:
                    await deleter(case.case_uri)
                case_deleter = getattr(self._cases, "delete_case", None)
                if case_deleter is not None:
                    await case_deleter(case.case_uri)
                removed.append(case.case_uri)
        if removed and not dry_run:
            logger.info(
                "Pruned %d terminal case(s) older than %d day(s).",
                len(removed),
                older_than_days,
            )
        return removed

    async def auto_run_all(self) -> list[str]:
        """Auto-execute the top proposal on every open case that passes the gate.

        The gate (S3 in docs/security.md):
          - case.status is OPEN
          - process.execute_policy.auto is True
          - engine returned at least one proposal
          - top proposal's confidence >= process.execute_policy.min_confidence
            (defaulting to 0.0 if unset)
          - top proposal's action is NOT marked auto_execute_disabled
            (AssertTriple / RetractTriple / RequestHumanReview never auto-run)

        Any case failing any check is *silently skipped* — auto-run is a
        no-op for cases the operator did not explicitly opt into. Returns
        the list of case_uris where an action actually fired.
        """

        fired: list[str] = []
        cases = await self.find_cases(status=CaseStatus.OPEN)
        for case in cases:
            process = await self._processes.get_process(case.process_uri)
            if process is None:
                continue
            policy = process.execute_policy or {}
            if not policy.get("auto"):
                continue
            min_conf = float(policy.get("min_confidence", 0.0))
            try:
                proposals = await self.propose_next(case.case_uri)
            except CaseManagerError:
                continue
            if not proposals:
                continue
            top = proposals[0]
            if top.confidence is None or top.confidence < min_conf:
                continue
            action = self._registry.get(top.action_uri)
            if action is None or getattr(action, "auto_execute_disabled", False):
                continue
            try:
                await self.execute_action(case.case_uri, top.action_uri, top.params)
                fired.append(case.case_uri)
            except CaseManagerError as exc:
                logger.warning("auto-run skipped case %s: %s", case.case_uri, exc)
        return fired

    async def tick(self) -> list[str]:
        """Fire elapsed timer events across all OPEN cases.

        For every open case whose process declares ``timer_events``, walk
        the entries and fire any whose ``after_minutes`` from
        ``case.created_at`` has elapsed and which hasn't already fired
        (tracked in case state under ``_timers_fired`` as a list of timer
        indices). Each fire goes through :meth:`execute_action` so it gets
        the full audit + side-effect + constraint treatment.

        Returns:
            The list of (case_uri, timer_index) pairs that fired, flattened
            into a string list ``["urn:c:1#0", ...]``.
        """

        now = utcnow()
        fired: list[str] = []
        open_cases = await self.find_cases(status=CaseStatus.OPEN)
        for case in open_cases:
            process = await self._processes.get_process(case.process_uri)
            if process is None or not process.timer_events:
                continue
            elapsed_minutes = (now - case.created_at).total_seconds() / 60
            already_fired = set(case.state.properties.get("_timers_fired", []))
            for index, spec in enumerate(process.timer_events):
                if index in already_fired:
                    continue
                after = spec.get("after_minutes", 0)
                if elapsed_minutes < after:
                    continue
                # Mark fired BEFORE executing so an exception in the action
                # doesn't cause a re-fire on the next tick.
                marked = sorted({*already_fired, index})
                new_properties = {**case.state.properties, "_timers_fired": marked}
                new_state = case.state.model_copy(update={"properties": new_properties})
                refreshed_case = case.model_copy(
                    update={"state": new_state, "updated_at": utcnow()}
                )
                await self._cases.update_case(refreshed_case)
                already_fired.add(index)

                try:
                    await self.execute_action(
                        case.case_uri,
                        spec["action"],
                        spec.get("params", {}),
                    )
                    fired.append(f"{case.case_uri}#{index}")
                except CaseManagerError as exc:
                    logger.warning(
                        "Timer %d on case %s failed to fire: %s",
                        index,
                        case.case_uri,
                        exc,
                    )
        return fired

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

        case = await self.get_case(case_uri)
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

        # P5: history is derived from the audit log on the next load, so we
        # only need to persist the state/status change here. Reload the case
        # so the returned object has the freshly-hydrated history (including
        # the compensation event we just recorded).
        intermediate = case.model_copy(
            update={
                "state": new_state,
                "status": CaseStatus.OPEN,
                "updated_at": utcnow(),
            }
        )
        await self._cases.update_case(intermediate)
        logger.info("Compensated %d activities on case %s.", len(undone), case_uri)
        refreshed = await self.get_case(case_uri)
        if refreshed is None:
            # We just updated this row; if it's gone something raced us
            # (concurrent delete or store inconsistency) — surface it loudly
            # rather than silently returning a stale in-memory snapshot.
            raise CompensationError(
                f"Case {case_uri} disappeared between compensate update and refresh."
            )
        return refreshed

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

    async def create_subcase(
        self,
        parent_uri: str,
        child_process_uri: str,
        *,
        initial_state: dict[str, Any] | None = None,
        case_uri: str | None = None,
    ) -> Case:
        """Spawn a child case linked back to ``parent_uri``.

        When the child closes (status → CLOSED), :meth:`execute_action`
        projects the child's final state onto the parent under
        ``subcase_<child_uri>_closed`` and ``subcase_<child_uri>_state`` so a
        parent decision engine can react to the child's outcome.

        Raises CaseNotFoundError / ProcessNotFoundError as applicable.
        """

        await self._require_case(parent_uri)  # rejects if parent missing
        child = await self.create_case(
            child_process_uri, initial_state=initial_state, case_uri=case_uri
        )
        attached = child.model_copy(update={"parent_uri": parent_uri})
        await self._cases.update_case(attached)
        logger.info("Created subcase %s under parent %s", child.case_uri, parent_uri)
        refreshed = await self.get_case(child.case_uri)
        if refreshed is None:  # pragma: no cover - just created
            raise CaseNotFoundError(child.case_uri)
        return refreshed

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
        case = await self.get_case(case_uri)
        if case is None:
            raise CaseNotFoundError(case_uri)
        return case


def _activity_to_event(activity: ProvOActivity) -> CaseEvent:
    """Project an audit activity onto the case-history view.

    The audit log is the authority for what happened in a case (P5); this
    helper renders one activity record as the lightweight ``CaseEvent`` that
    in-memory consumers (compensation, UI, demos) prefer to read.
    """

    return CaseEvent(
        activity_uri=activity.activity_uri,
        action_uri=activity.action_uri,
        at=activity.ended_at or activity.started_at or utcnow(),
        success=activity.success,
    )


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
    """Check the process's ordering constraints against current history.

    Supported keys (CMMN-friendly extensions; not BPMN sequence flow):

    - ``mutex``: groups of mutually exclusive actions.
    - ``requires``: prerequisite-chain — the named actions must already
      appear in case history.
    - ``immediately_after``: the action may only run right after the named
      action — no other real action may have run in between (compensation
      markers are ignored when computing "most recent").
    - ``at_most_once``: the action may run at most once per case.
    """

    constraints = process.constraints or {}
    executed = {event.action_uri for event in case.history}
    executed_in_order = [event.action_uri for event in case.history]

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

    expected_predecessor = (constraints.get("immediately_after") or {}).get(action_uri)
    if expected_predecessor is not None:
        most_recent_real = next(
            (uri for uri in reversed(executed_in_order) if uri != COMPENSATION_ACTION_URI),
            None,
        )
        if most_recent_real != expected_predecessor:
            raise ConstraintViolationError(
                f"Immediately-after: {action_uri} must follow {expected_predecessor} "
                f"directly; most recent action was {most_recent_real!r}."
            )

    if action_uri in (constraints.get("at_most_once") or []) and action_uri in executed:
        raise ConstraintViolationError(
            f"At-most-once: {action_uri} has already run on case {case.case_uri}."
        )
