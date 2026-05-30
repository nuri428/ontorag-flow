"""CausalSimulationEngine, StackedEngine, counterfactual replay (fake client)."""

from __future__ import annotations

from typing import Any

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.state import CaseState
from ontorag_flow.engines.causal import (
    CausalSimulationEngine,
    CounterfactualResult,
    StackedEngine,
)

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
OTHER = "urn:other:nope"


class FakeOntorag:
    """Returns a canned posterior per tool name (or per intervention key)."""

    def __init__(
        self,
        *,
        posteriors: dict[str, float] | None = None,
        per_intervention: dict[str, float] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._posteriors = posteriors or {}
        self._per_intervention = per_intervention or {}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name in ("do_query", "compute_posterior"):
            intervention = arguments.get("intervention") or arguments.get("evidence") or {}
            for key, value in intervention.items():
                marker = f"{key}={value}"
                if marker in self._per_intervention:
                    return {"posterior": self._per_intervention[marker]}
        if name == "counterfactual":
            intervention = arguments.get("intervention", {})
            for key, value in intervention.items():
                marker = f"{key}={value}"
                if marker in self._per_intervention:
                    return {"posterior": self._per_intervention[marker]}
        return {"posterior": self._posteriors.get(name, 0.5)}


def _process(causal=None, allowed=None, goal=None) -> ProcessDefinition:  # type: ignore[no-untyped-def]
    return ProcessDefinition(
        process_uri="urn:p",
        name="P",
        allowed_actions=allowed if allowed is not None else [UPDATE],
        causal=causal,
        goal=goal or {},
    )


def _case(properties: dict[str, Any] | None = None) -> Case:
    return Case(case_uri="urn:c", process_uri="urn:p", state=CaseState(properties=properties or {}))


# --- propose_next ----------------------------------------------------------


async def test_propose_uses_do_query_and_ranks_by_posterior() -> None:
    causal = {
        "target": {"diagnosed": True},
        "candidates": [
            {"action": UPDATE, "params": {"key": "tx", "value": "A"}, "intervention": {"tx": "A"}},
            {"action": UPDATE, "params": {"key": "tx", "value": "B"}, "intervention": {"tx": "B"}},
        ],
    }
    client = FakeOntorag(per_intervention={"tx=A": 0.4, "tx=B": 0.9})
    process = _process(causal=causal)

    proposals = await CausalSimulationEngine(client).propose_next(_case(), process)

    assert [p.confidence for p in proposals] == [0.9, 0.4]
    assert proposals[0].proposed_by == "CausalSimulationEngine"
    assert all(call[0] == "do_query" for call in client.calls)


async def test_propose_returns_empty_without_config() -> None:
    proposals = await CausalSimulationEngine(FakeOntorag()).propose_next(_case(), _process())
    assert proposals == []


async def test_propose_skips_disallowed_actions() -> None:
    causal = {
        "target": {"diagnosed": True},
        "candidates": [{"action": OTHER, "intervention": {"x": 1}}],
    }
    process = _process(causal=causal, allowed=[UPDATE])

    proposals = await CausalSimulationEngine(FakeOntorag()).propose_next(_case(), process)
    assert proposals == []


# --- score_intervention + counterfactual ----------------------------------


async def test_score_intervention_direct_call() -> None:
    client = FakeOntorag(per_intervention={"tx=A": 0.7})
    posterior = await CausalSimulationEngine(client).score_intervention({"tx": "A"}, {"goal": True})
    assert posterior == 0.7
    assert client.calls[-1][0] == "do_query"


async def test_counterfactual_replay_returns_result() -> None:
    client = FakeOntorag(per_intervention={"tx=B": 0.85})
    engine = CausalSimulationEngine(client)

    result = await engine.counterfactual_replay(
        case_uri="urn:c:1",
        swap_activity_uri="urn:a:99",
        evidence={"severity": "high"},
        counterfactual_action_uri=UPDATE,
        counterfactual_params={"tx": "B"},
        target={"diagnosed": True},
    )

    assert isinstance(result, CounterfactualResult)
    assert result.posterior == 0.85
    assert result.counterfactual_action_uri == UPDATE
    assert client.calls[-1][0] == "counterfactual"
    assert client.calls[-1][1]["evidence"] == {"severity": "high"}


# --- StackedEngine ---------------------------------------------------------


class FakeProposer:
    def __init__(self, proposals: list[ActionProposal]) -> None:
        self._proposals = proposals

    async def propose_next(self, case, process):  # type: ignore[no-untyped-def]
        return list(self._proposals)


async def test_stacked_engine_rescore_via_causal_validator() -> None:
    proposer = FakeProposer(
        [
            ActionProposal(
                action_uri=UPDATE, params={"tx": "A"}, confidence=0.9, proposed_by="LlmAgentEngine"
            ),
            ActionProposal(
                action_uri=UPDATE, params={"tx": "B"}, confidence=0.6, proposed_by="LlmAgentEngine"
            ),
        ]
    )
    client = FakeOntorag(per_intervention={"tx=A": 0.2, "tx=B": 0.95})
    stacked = StackedEngine(proposer=proposer, validator=CausalSimulationEngine(client))
    process = _process(goal={"diagnosed": True})

    proposals = await stacked.propose_next(_case(), process)

    # Causal flips the ranking: tx=B (do-effect 0.95) outranks tx=A (do-effect 0.2)
    assert [p.params for p in proposals] == [{"tx": "B"}, {"tx": "A"}]
    assert proposals[0].confidence == 0.95
    assert "CausalValidator" in proposals[0].proposed_by


async def test_stacked_engine_without_target_returns_proposer_proposals() -> None:
    proposals = [ActionProposal(action_uri=UPDATE, confidence=0.5)]
    stacked = StackedEngine(
        proposer=FakeProposer(proposals), validator=CausalSimulationEngine(FakeOntorag())
    )

    out = await stacked.propose_next(_case(), _process())  # no goal -> no target
    assert out == proposals
