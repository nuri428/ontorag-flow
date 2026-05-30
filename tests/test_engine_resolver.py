"""EngineResolver: kind selection and engine construction with backing clients."""

from __future__ import annotations

from typing import Any

import pytest

from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.engines.bayesian import BayesianMpeEngine
from ontorag_flow.engines.causal import CausalSimulationEngine
from ontorag_flow.engines.llm_agent import LlmAgentEngine
from ontorag_flow.engines.rule import RuleEngine
from ontorag_flow.engines.selection import EngineResolver, EngineUnavailableError

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
_RULE = {"name": "r", "when": {}, "then": {"action": UPDATE}}


class FakeOntorag:
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return {"posterior": 0.5}


class FakeLlm:
    async def complete(self, *, system: str, user: str) -> str:
        return "[]"


def _proc(**kw: Any) -> ProcessDefinition:
    return ProcessDefinition(process_uri="urn:p", name="P", allowed_actions=[UPDATE], **kw)


def test_explicit_engine_overrides_inference() -> None:
    resolver = EngineResolver(ontorag_client=FakeOntorag(), llm_client=FakeLlm())
    assert resolver.kind_for(_proc(engine="llm", rules=[_RULE])) == "llm"


def test_infers_bayesian_then_rule_then_default() -> None:
    resolver = EngineResolver()
    assert resolver.kind_for(_proc(bayesian={"target": {}})) == "bayesian"
    assert resolver.kind_for(_proc(rules=[_RULE])) == "rule"
    assert resolver.kind_for(_proc()) == "rule"  # default
    assert EngineResolver(default="llm").kind_for(_proc()) == "llm"


def test_for_process_builds_rule_engine() -> None:
    engine = EngineResolver().for_process(_proc(rules=[_RULE]))
    assert isinstance(engine, RuleEngine)


def test_for_process_builds_bayesian_with_client() -> None:
    resolver = EngineResolver(ontorag_client=FakeOntorag())
    assert isinstance(resolver.for_process(_proc(bayesian={"target": {}})), BayesianMpeEngine)


def test_for_process_builds_llm_with_client() -> None:
    resolver = EngineResolver(llm_client=FakeLlm())
    assert isinstance(resolver.for_process(_proc(engine="llm")), LlmAgentEngine)


def test_bayesian_without_client_raises() -> None:
    with pytest.raises(EngineUnavailableError):
        EngineResolver().for_process(_proc(bayesian={"target": {}}))


def test_llm_without_client_raises() -> None:
    with pytest.raises(EngineUnavailableError):
        EngineResolver().for_process(_proc(engine="llm"))


def test_unknown_engine_name_raises() -> None:
    with pytest.raises(EngineUnavailableError):
        EngineResolver().kind_for(_proc(engine="bogus"))


def test_causal_inferred_from_causal_config() -> None:
    # causal config takes precedence over bayesian / rules in inference
    assert EngineResolver().kind_for(_proc(causal={"target": {"done": True}})) == "causal"


def test_for_process_builds_causal_with_client() -> None:
    resolver = EngineResolver(ontorag_client=FakeOntorag())
    assert isinstance(
        resolver.for_process(_proc(causal={"target": {"done": True}})),
        CausalSimulationEngine,
    )


def test_causal_without_client_raises() -> None:
    with pytest.raises(EngineUnavailableError):
        EngineResolver().for_process(_proc(causal={"target": {"done": True}}))


# --- stacked engine arbitration -----------------------------------------


def test_stacked_kind_recognised() -> None:
    resolver = EngineResolver()
    assert resolver.kind_for(_proc(engine="stacked")) == "stacked"


def test_stacked_with_rule_proposer_and_causal_validator_builds() -> None:
    from ontorag_flow.engines.causal import StackedEngine

    resolver = EngineResolver(ontorag_client=FakeOntorag())
    process = _proc(
        engine="stacked",
        rules=[_RULE],
        arbitration={"proposer": "rule", "validator": "causal"},
    )
    engine = resolver.for_process(process)
    assert isinstance(engine, StackedEngine)


def test_stacked_with_llm_proposer_requires_llm_client() -> None:
    """If the proposer kind needs a client, the error message points at *that*."""

    resolver = EngineResolver(ontorag_client=FakeOntorag())  # no LLM client
    process = _proc(
        engine="stacked",
        arbitration={"proposer": "llm", "validator": "causal"},
    )
    with pytest.raises(EngineUnavailableError, match="LLM"):
        resolver.for_process(process)


def test_stacked_without_ontorag_client_fails_on_validator() -> None:
    resolver = EngineResolver(llm_client=FakeLlm())  # no ontorag client
    process = _proc(
        engine="stacked",
        rules=[_RULE],
        arbitration={"proposer": "rule", "validator": "causal"},
    )
    with pytest.raises(EngineUnavailableError, match="ontorag"):
        resolver.for_process(process)


def test_stacked_rejects_unknown_proposer() -> None:
    resolver = EngineResolver(ontorag_client=FakeOntorag())
    with pytest.raises(EngineUnavailableError, match="arbitration.proposer"):
        resolver.for_process(
            _proc(engine="stacked", arbitration={"proposer": "magic", "validator": "causal"})
        )


def test_stacked_rejects_non_causal_validator() -> None:
    """Only causal exposes score_intervention today."""

    resolver = EngineResolver(ontorag_client=FakeOntorag())
    with pytest.raises(EngineUnavailableError, match="validator must be 'causal'"):
        resolver.for_process(
            _proc(
                engine="stacked",
                rules=[_RULE],
                arbitration={"proposer": "rule", "validator": "bayesian"},
            )
        )


def test_stacked_defaults_validator_to_causal_when_unspecified() -> None:
    """The validator field defaults to 'causal' so the YAML can omit it."""

    from ontorag_flow.engines.causal import StackedEngine

    resolver = EngineResolver(ontorag_client=FakeOntorag())
    process = _proc(
        engine="stacked",
        rules=[_RULE],
        arbitration={"proposer": "rule"},
    )
    assert isinstance(resolver.for_process(process), StackedEngine)
