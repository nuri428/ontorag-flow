"""Case manager — the orchestration core for cases.

It owns the case lifecycle: create a case from a process, run an explicitly
chosen action against it, advance state, chain provenance, and auto-close on
goal satisfaction. It deliberately contains *no* decision logic — which action
to run next is the job of a decision engine (v0.3+). Here the caller chooses.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.executor import ActionExecutor, ExecutionOutcome
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.registry import ActionRegistry
from ontorag_flow.core.state import CaseState
from ontorag_flow.log import get_logger
from ontorag_flow.stores.base import CaseStore, ProcessStore

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
    ) -> None:
        self._cases = case_store
        self._processes = process_store
        self._executor = executor
        self._registry = registry

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
            raise CaseClosedError(
                f"Case {case_uri} is {case.status.value}, not open."
            )

        process = await self._processes.get_process(case.process_uri)
        if process is None:
            raise ProcessNotFoundError(case.process_uri)
        if not process.allows(action_uri):
            raise ActionNotAllowedError(
                f"Action {action_uri} is not allowed by process {case.process_uri}."
            )

        action = self._registry.get(action_uri)
        if action is None:
            raise ActionNotFoundError(action_uri)

        outcome = await self._executor.execute(
            action, params, case.state, informed_by=case.last_activity_uri
        )

        new_case = case.record_execution(outcome.activity, outcome.state)
        if new_case.state.goal_reached():
            new_case = new_case.with_status(CaseStatus.CLOSED)
            logger.info("Case %s reached its goal and was closed.", case_uri)

        await self._cases.update_case(new_case)
        return new_case, outcome
