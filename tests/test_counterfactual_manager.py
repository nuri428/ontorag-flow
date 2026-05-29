"""CaseManager.counterfactual dispatches to a causal engine and validates."""

from __future__ import annotations

from typing import Any

import pytest

from ontorag_flow.core.case_manager import (
    CaseManager,
    CounterfactualError,
)
from ontorag_flow.core.executor import ActionExecutor
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.registry import default_registry
from ontorag_flow.engines.causal import CausalSimulationEngine
from ontorag_flow.engines.rule import RuleEngine
from ontorag_flow.stores.sqlite import SqliteStore

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"


class FakeOntorag:
    def __init__(self, posterior: float = 0.8) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._posterior = posterior

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return {"posterior": self._posterior}


def _causal_factory(client):  # type: ignore[no-untyped-def]
    def _factory(process):  # type: ignore[no-untyped-def]
        return CausalSimulationEngine(client)
    return _factory


async def test_counterfactual_via_causal_engine(sqlite_store: SqliteStore) -> None:
    client = FakeOntorag(posterior=0.77)
    manager = CaseManager(
        case_store=sqlite_store,
        process_store=sqlite_store,
        executor=ActionExecutor(audit_store=sqlite_store, agent="urn:test:agent"),
        registry=default_registry(),
        engine_factory=_causal_factory(client),
    )
    process = ProcessDefinition(
        process_uri="urn:p:cf", name="CF", allowed_actions=[UPDATE], goal={"diagnosed": True}
    )
    await manager.register_process(process)
    case = await manager.create_case("urn:p:cf")
    case, outcome = await manager.execute_action(case.case_uri, UPDATE, {"key": "a", "value": 1})

    result = await manager.counterfactual(
        case.case_uri,
        swap_activity_uri=outcome.activity.activity_uri,
        action_uri=UPDATE,
        params={"a": 2},
    )

    assert result.posterior == 0.77
    assert result.target == {"diagnosed": True}  # defaulted from process.goal
    assert client.calls[-1][0] == "counterfactual"
    # evidence comes from the snapshot taken before the swapped activity ran:
    assert client.calls[-1][1]["evidence"] == {}


async def test_counterfactual_rejected_when_engine_does_not_support_it(
    sqlite_store: SqliteStore,
) -> None:
    manager = CaseManager(
        case_store=sqlite_store,
        process_store=sqlite_store,
        executor=ActionExecutor(audit_store=sqlite_store, agent="urn:test:agent"),
        registry=default_registry(),
        engine_factory=RuleEngine.from_process,  # rule engine has no counterfactual_replay
    )
    process = ProcessDefinition(process_uri="urn:p:r", name="R", allowed_actions=[UPDATE])
    await manager.register_process(process)
    case = await manager.create_case("urn:p:r")
    case, outcome = await manager.execute_action(case.case_uri, UPDATE, {"key": "a", "value": 1})

    with pytest.raises(CounterfactualError):
        await manager.counterfactual(
            case.case_uri,
            swap_activity_uri=outcome.activity.activity_uri,
            action_uri=UPDATE,
            params={"a": 2},
        )


async def test_counterfactual_unknown_swap_activity_raises(
    sqlite_store: SqliteStore,
) -> None:
    manager = CaseManager(
        case_store=sqlite_store,
        process_store=sqlite_store,
        executor=ActionExecutor(audit_store=sqlite_store, agent="urn:test:agent"),
        registry=default_registry(),
        engine_factory=_causal_factory(FakeOntorag()),
    )
    process = ProcessDefinition(process_uri="urn:p:cf", name="CF", allowed_actions=[UPDATE])
    await manager.register_process(process)
    case = await manager.create_case("urn:p:cf")

    with pytest.raises(CounterfactualError):
        await manager.counterfactual(
            case.case_uri,
            swap_activity_uri="urn:nope",
            action_uri=UPDATE,
            params={},
        )
