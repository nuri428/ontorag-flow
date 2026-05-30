"""RuleEngine decision-table matching, ranking, and allowed-action filtering."""

from __future__ import annotations

from typing import Any

from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.state import CaseState
from ontorag_flow.engines.rule import RuleEngine, _matches

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
OTHER = "urn:other:action:Nope"


def _process(rules: list[dict[str, Any]], allowed: list[str] | None = None) -> ProcessDefinition:
    return ProcessDefinition(
        process_uri="urn:p",
        name="P",
        allowed_actions=allowed if allowed is not None else [UPDATE],
        rules=rules,
    )


def _case(properties: dict[str, Any]) -> Case:
    return Case(
        case_uri="urn:c", process_uri="urn:p", state=CaseState(properties=properties)
    )


def test_matches_scalar_equality() -> None:
    assert _matches({"a": 1}, {"a": 1})
    assert not _matches({"a": 1}, {"a": 2})
    assert not _matches({"a": 1}, {})  # missing property


def test_matches_operators() -> None:
    assert _matches({"sev": {"gte": 7}}, {"sev": 7})
    assert not _matches({"sev": {"gte": 7}}, {"sev": 6})
    assert _matches({"x": {"in": ["a", "b"]}}, {"x": "b"})
    assert _matches({"x": {"ne": 3}}, {"x": 4})
    assert _matches({"x": {"exists": True}}, {"x": 0})
    assert _matches({"x": {"exists": False}}, {})
    assert not _matches({"sev": {"gt": 7}}, {})  # missing -> None -> False


async def test_propose_fires_matching_rules_ranked() -> None:
    rules = [
        {"name": "low", "when": {"a": 1}, "then": {"action": UPDATE, "params": {"k": "v"}}, "confidence": 0.5},
        {"name": "high", "when": {"a": 1}, "then": {"action": UPDATE}, "confidence": 0.9},
        {"name": "nomatch", "when": {"a": 2}, "then": {"action": UPDATE}, "confidence": 1.0},
    ]
    process = _process(rules)
    proposals = await RuleEngine.from_process(process).propose_next(_case({"a": 1}), process)

    assert [p.confidence for p in proposals] == [0.9, 0.5]
    assert proposals[0].proposed_by == "RuleEngine"
    assert proposals[1].params == {"k": "v"}


async def test_propose_skips_disallowed_actions() -> None:
    rules = [{"name": "x", "when": {}, "then": {"action": OTHER}, "confidence": 1.0}]
    process = _process(rules, allowed=[UPDATE])
    assert await RuleEngine.from_process(process).propose_next(_case({}), process) == []


async def test_empty_when_always_fires() -> None:
    rules = [{"name": "always", "when": {}, "then": {"action": UPDATE}}]
    process = _process(rules)
    proposals = await RuleEngine.from_process(process).propose_next(_case({"anything": 1}), process)
    assert len(proposals) == 1
    assert proposals[0].rationale == "always"


def test_unknown_operator_in_rule_is_rejected_at_parse_time() -> None:
    # Typo'd 'gtt' previously made matching silently False, hiding the rule;
    # the validator now surfaces it as a ValidationError instead.
    import pytest as _pytest
    from pydantic import ValidationError

    rules = [{"name": "typo", "when": {"sev": {"gtt": 7}}, "then": {"action": UPDATE}}]
    process = _process(rules)
    with _pytest.raises(ValidationError):
        RuleEngine.from_process(process)
