"""RuleEngine — a DMN-inspired decision table.

Rules are declared *data*, not Python: each rule matches the current case
properties (``when``) and, if it fires, proposes an action (``then``). The engine
only proposes actions the process actually allows, and ranks proposals by
confidence. It never executes anything.

A condition value is either a scalar (equality) or a single-key operator mapping,
e.g. ``{gte: 3}`` or ``{in: [a, b]}``. Supported operators: ``eq, ne, gt, gte,
lt, lte, in, exists``.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field, model_validator

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.log import get_logger

logger = get_logger(__name__)


def _op_gt(actual: Any, operand: Any) -> bool:
    return actual is not None and actual > operand


def _op_gte(actual: Any, operand: Any) -> bool:
    return actual is not None and actual >= operand


def _op_lt(actual: Any, operand: Any) -> bool:
    return actual is not None and actual < operand


def _op_lte(actual: Any, operand: Any) -> bool:
    return actual is not None and actual <= operand


_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda actual, operand: actual == operand,
    "ne": lambda actual, operand: actual != operand,
    "gt": _op_gt,
    "gte": _op_gte,
    "lt": _op_lt,
    "lte": _op_lte,
    "in": lambda actual, operand: actual in operand,
    "exists": lambda actual, operand: (actual is not None) == bool(operand),
}


class RuleOutcome(BaseModel):
    """What a fired rule proposes."""

    action: str
    params: dict[str, Any] = Field(default_factory=dict)


class Rule(BaseModel):
    """One decision-table row."""

    name: str
    when: dict[str, Any] = Field(default_factory=dict)
    then: RuleOutcome
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str | None = None

    @model_validator(mode="after")
    def _reject_unknown_operators(self) -> Rule:
        """Fail loudly at parse time on typo'd operator names (e.g. ``gtt``).

        Without this guard, an unknown operator made the condition silently
        evaluate to False — the rule would simply never fire and decision-making
        would go wrong with no signal. We surface the typo here instead.
        """

        for key, expected in self.when.items():
            if isinstance(expected, dict):
                unknown = sorted(op for op in expected if op not in _OPERATORS)
                if unknown:
                    raise ValueError(
                        f"Unknown operator(s) {unknown} in rule {self.name!r} "
                        f"condition for {key!r}; valid: {sorted(_OPERATORS)}."
                    )
        return self


def _match_condition(actual: Any, expected: Any) -> bool:
    """Match one property value against a scalar or an operator mapping."""

    if isinstance(expected, dict):
        return all(
            _OPERATORS[op](actual, operand)
            for op, operand in expected.items()
            if op in _OPERATORS
        ) and all(op in _OPERATORS for op in expected)
    return actual == expected


def _matches(when: dict[str, Any], properties: dict[str, Any]) -> bool:
    """Whether every condition in ``when`` holds for the given properties."""

    return all(
        _match_condition(properties.get(key), expected)
        for key, expected in when.items()
    )


class RuleEngine:
    """Evaluates a decision table against case state."""

    def __init__(self, rules: list[Rule]) -> None:
        self._rules = rules

    @classmethod
    def from_process(cls, process: ProcessDefinition) -> RuleEngine:
        """Build an engine from a process's opaque ``rules`` list."""

        return cls([Rule.model_validate(raw) for raw in process.rules])

    async def propose_next(
        self, case: Case, process: ProcessDefinition
    ) -> list[ActionProposal]:
        """Return proposals for every fired rule, ranked by confidence."""

        proposals: list[ActionProposal] = []
        for rule in self._rules:
            if not process.allows(rule.then.action):
                logger.warning(
                    "Rule %r proposes disallowed action %s; skipping.",
                    rule.name,
                    rule.then.action,
                )
                continue
            if _matches(rule.when, case.state.properties):
                proposals.append(
                    ActionProposal(
                        action_uri=rule.then.action,
                        params=rule.then.params,
                        rationale=rule.rationale or rule.name,
                        confidence=rule.confidence,
                        proposed_by="RuleEngine",
                    )
                )
        proposals.sort(key=lambda proposal: proposal.confidence or 0.0, reverse=True)
        return proposals
