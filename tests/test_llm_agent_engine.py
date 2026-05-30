"""LlmAgentEngine: parsing, filtering, ranking, and prompt construction."""

from __future__ import annotations

import pytest

from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.registry import default_registry
from ontorag_flow.core.state import CaseState
from ontorag_flow.engines.llm_agent import LlmAgentEngine
from ontorag_flow.engines.llm_providers import (
    AnthropicClient,
    OllamaClient,
    OpenAIClient,
    make_llm_client,
)

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
SET_GOAL = "urn:ontorag-flow:action:SetGoal"
OTHER = "urn:other:action:Nope"


class FakeLlm:
    """Records the prompt and returns a canned reply."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_user: str | None = None
        self.last_system: str | None = None

    async def complete(self, *, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        return self.reply


def _process(allowed: list[str] | None = None) -> ProcessDefinition:
    return ProcessDefinition(
        process_uri="urn:p",
        name="P",
        allowed_actions=allowed if allowed is not None else [UPDATE, SET_GOAL],
    )


def _case(properties: dict | None = None) -> Case:
    return Case(case_uri="urn:c", process_uri="urn:p", state=CaseState(properties=properties or {}))


async def test_parses_and_ranks_by_confidence() -> None:
    reply = (
        f'[{{"action_uri":"{UPDATE}","params":{{"key":"x","value":1}},'
        f'"rationale":"r","confidence":0.4}},'
        f'{{"action_uri":"{SET_GOAL}","params":{{"predicate":"done"}},"confidence":0.9}}]'
    )
    proposals = await LlmAgentEngine(FakeLlm(reply)).propose_next(_case(), _process())

    assert [p.action_uri for p in proposals] == [SET_GOAL, UPDATE]
    assert proposals[0].proposed_by == "LlmAgentEngine"
    assert proposals[1].params == {"key": "x", "value": 1}


async def test_filters_disallowed_actions() -> None:
    reply = f'[{{"action_uri":"{OTHER}","confidence":1.0}},{{"action_uri":"{UPDATE}","confidence":0.5}}]'
    proposals = await LlmAgentEngine(FakeLlm(reply)).propose_next(
        _case(), _process(allowed=[UPDATE])
    )
    assert [p.action_uri for p in proposals] == [UPDATE]


async def test_handles_json_code_fence() -> None:
    reply = f'```json\n[{{"action_uri":"{UPDATE}","confidence":0.7}}]\n```'
    proposals = await LlmAgentEngine(FakeLlm(reply)).propose_next(_case(), _process())
    assert len(proposals) == 1 and proposals[0].action_uri == UPDATE


async def test_extracts_array_from_prose() -> None:
    reply = f'Sure, here:\n[{{"action_uri":"{UPDATE}","confidence":0.6}}]\nHope it helps.'
    proposals = await LlmAgentEngine(FakeLlm(reply)).propose_next(_case(), _process())
    assert len(proposals) == 1


async def test_malformed_reply_returns_empty() -> None:
    proposals = await LlmAgentEngine(FakeLlm("I cannot decide.")).propose_next(_case(), _process())
    assert proposals == []


async def test_no_allowed_actions_returns_empty() -> None:
    proposals = await LlmAgentEngine(FakeLlm("[]")).propose_next(_case(), _process(allowed=[]))
    assert proposals == []


async def test_confidence_is_clamped() -> None:
    reply = f'[{{"action_uri":"{UPDATE}","confidence":5}}]'
    proposals = await LlmAgentEngine(FakeLlm(reply)).propose_next(_case(), _process())
    assert proposals[0].confidence == 1.0


async def test_max_proposals_caps_results() -> None:
    items = ",".join(f'{{"action_uri":"{UPDATE}","confidence":{i / 10}}}' for i in range(5))
    engine = LlmAgentEngine(FakeLlm(f"[{items}]"), max_proposals=2)
    assert len(await engine.propose_next(_case(), _process())) == 2


async def test_prompt_includes_state_goal_and_actions() -> None:
    fake = FakeLlm("[]")
    await LlmAgentEngine(fake, registry=default_registry()).propose_next(
        _case({"severity": 3}), _process()
    )
    assert fake.last_user is not None
    assert "severity" in fake.last_user
    assert UPDATE in fake.last_user
    assert "params:" in fake.last_user  # registry enriched the catalog line


def test_make_llm_client_dispatch() -> None:
    assert isinstance(make_llm_client("anthropic"), AnthropicClient)
    assert isinstance(make_llm_client("openai"), OpenAIClient)
    assert isinstance(make_llm_client("ollama"), OllamaClient)


def test_make_llm_client_unknown_provider() -> None:
    with pytest.raises(ValueError):
        make_llm_client("bedrock")


# --- pure helpers: _extract_json_array and _clamp_confidence ------------


def test_clamp_confidence_rejects_bool_and_non_numeric() -> None:
    from ontorag_flow.engines.llm_agent import _clamp_confidence

    assert _clamp_confidence(True) is None  # bool is the trap (subclass of int)
    assert _clamp_confidence("0.5") is None
    assert _clamp_confidence(None) is None


def test_clamp_confidence_clamps_to_unit_interval() -> None:
    from ontorag_flow.engines.llm_agent import _clamp_confidence

    assert _clamp_confidence(-0.4) == 0.0
    assert _clamp_confidence(1.7) == 1.0
    assert _clamp_confidence(0.42) == 0.42


def test_extract_json_array_handles_fenced_object_with_proposals() -> None:
    """LLM wraps the array in a ```json fenced object with a "proposals" key."""

    from ontorag_flow.engines.llm_agent import _extract_json_array

    raw = '```json\n{"proposals": [{"action_uri": "u"}]}\n```'
    assert _extract_json_array(raw) == [{"action_uri": "u"}]


def test_extract_json_array_recovers_bracketed_array_from_prose() -> None:
    """First JSON parse fails (extra prose); falls back to [...] substring scan."""

    from ontorag_flow.engines.llm_agent import _extract_json_array

    raw = 'Sure! Here are my picks: [{"action_uri": "u"}] hope that helps.'
    assert _extract_json_array(raw) == [{"action_uri": "u"}]


def test_extract_json_array_returns_none_when_substring_also_unparseable() -> None:
    from ontorag_flow.engines.llm_agent import _extract_json_array

    # Has brackets but the inside is garbage.
    assert _extract_json_array("prose [not, valid, json[[]] more") is None


def test_extract_json_array_returns_none_when_no_array_anywhere() -> None:
    from ontorag_flow.engines.llm_agent import _extract_json_array

    assert _extract_json_array("no arrays here") is None


def test_extract_json_array_returns_none_for_scalar_top_level() -> None:
    """Parses, but the top level is neither a list nor an object-with-proposals."""

    from ontorag_flow.engines.llm_agent import _extract_json_array

    assert _extract_json_array('"a string"') is None
    assert _extract_json_array("42") is None
