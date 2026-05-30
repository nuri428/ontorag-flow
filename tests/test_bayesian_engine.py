"""BayesianMpeEngine posterior scoring, ranking, allowed-action filtering, and
the tolerant ``_extract_posterior`` parsing of provisional ontorag responses."""

from __future__ import annotations

from typing import Any

import pytest

from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.state import CaseState
from ontorag_flow.engines.bayesian import BayesianMpeEngine, _extract_posterior

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
OTHER = "urn:other:action:Nope"


class FakeClient:
    """A stand-in ontorag MCP client.

    Returns a canned posterior keyed by a value found in the evidence, so that
    different candidates score differently. Records every call for assertions.
    """

    def __init__(self, scores_by_severity: dict[Any, Any]) -> None:
        self._scores = scores_by_severity
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        severity = arguments["evidence"].get("severity")
        return self._scores[severity]


def _process(
    bayesian: dict[str, Any] | None, allowed: list[str] | None = None
) -> ProcessDefinition:
    return ProcessDefinition(
        process_uri="urn:p",
        name="P",
        allowed_actions=allowed if allowed is not None else [UPDATE],
        bayesian=bayesian,
    )


def _case(properties: dict[str, Any]) -> Case:
    return Case(case_uri="urn:c", process_uri="urn:p", state=CaseState(properties=properties))


def _bayesian(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "target": {"diagnosed": True},
        "query_tool": "compute_posterior",
        "candidates": candidates,
    }


async def test_propose_ranks_candidates_by_posterior_descending() -> None:
    bayesian = _bayesian(
        [
            {
                "action": UPDATE,
                "params": {"key": "t", "value": "low"},
                "evidence": {"severity": "low"},
            },
            {
                "action": UPDATE,
                "params": {"key": "t", "value": "high"},
                "evidence": {"severity": "high"},
            },
        ]
    )
    process = _process(bayesian)
    client = FakeClient({"low": 0.2, "high": 0.9})

    proposals = await BayesianMpeEngine(client).propose_next(_case({}), process)

    assert [p.confidence for p in proposals] == [0.9, 0.2]
    assert proposals[0].proposed_by == "BayesianMpeEngine"
    assert proposals[0].params == {"key": "t", "value": "high"}
    assert proposals[0].rationale == "P(target | action) ≈ 0.90"


async def test_no_bayesian_config_returns_empty() -> None:
    process = _process(bayesian=None)
    client = FakeClient({})

    assert await BayesianMpeEngine(client).propose_next(_case({}), process) == []
    assert client.calls == []  # short-circuits before any MCP call


async def test_disallowed_candidate_action_is_skipped() -> None:
    bayesian = _bayesian(
        [
            {"action": OTHER, "evidence": {"severity": "high"}},
            {"action": UPDATE, "evidence": {"severity": "low"}},
        ]
    )
    process = _process(bayesian, allowed=[UPDATE])
    client = FakeClient({"low": 0.4, "high": 0.9})

    proposals = await BayesianMpeEngine(client).propose_next(_case({}), process)

    assert len(proposals) == 1
    assert proposals[0].action_uri == UPDATE
    # The disallowed candidate is never scored.
    assert all(call[1]["evidence"].get("severity") != "high" for call in client.calls)


async def test_base_evidence_merges_case_properties() -> None:
    bayesian = _bayesian([{"action": UPDATE, "evidence": {"severity": "high"}}])
    process = _process(bayesian)
    client = FakeClient({"high": 0.7})

    await BayesianMpeEngine(client).propose_next(_case({"age": 42}), process)

    name, arguments = client.calls[0]
    assert name == "compute_posterior"
    assert arguments["evidence"] == {"age": 42, "severity": "high"}
    assert arguments["query"] == {"diagnosed": True}


async def test_params_propagate_to_proposal() -> None:
    params = {"key": "triage_level", "value": "urgent"}
    bayesian = _bayesian([{"action": UPDATE, "params": params, "evidence": {"severity": "high"}}])
    process = _process(bayesian)
    client = FakeClient({"high": 0.8})

    proposals = await BayesianMpeEngine(client).propose_next(_case({}), process)

    assert proposals[0].params == params


def test_extract_posterior_accepts_bare_float() -> None:
    assert _extract_posterior(0.42) == 0.42
    assert _extract_posterior(1) == 1.0
    assert _extract_posterior(0) == 0.0


def test_extract_posterior_accepts_posterior_key() -> None:
    assert _extract_posterior({"posterior": 0.73}) == 0.73


def test_extract_posterior_accepts_probability_key() -> None:
    assert _extract_posterior({"probability": 0.55}) == 0.55


def test_extract_posterior_prefers_posterior_over_probability() -> None:
    assert _extract_posterior({"posterior": 0.9, "probability": 0.1}) == 0.9


def test_extract_posterior_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        _extract_posterior("not a number")
    with pytest.raises(ValueError):
        _extract_posterior({"unexpected": 0.5})
    with pytest.raises(ValueError):
        _extract_posterior(None)
    with pytest.raises(ValueError):
        _extract_posterior(True)  # bool is not a valid posterior


def test_extract_posterior_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        _extract_posterior(1.5)
    with pytest.raises(ValueError):
        _extract_posterior({"posterior": -0.1})
