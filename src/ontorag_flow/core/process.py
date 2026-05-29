"""Process definitions — CMMN-inspired, not BPMN.

A process declares the *allowed* actions for a case type, an optional default
initial state, and the goal conditions that mark a case complete. It does not
prescribe a rigid sequence; ordering is decided at runtime. Constraints and
per-action preconditions (mutual exclusions, prerequisite chains) arrive with
the rule engine in v0.3.

Serialized as YAML in v0.2; an optional RDF vocabulary may follow in v0.5+.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError


class ProcessParseError(ValueError):
    """Raised when a process YAML file is malformed or fails validation."""


class ProcessDefinition(BaseModel):
    """The governing definition for a class of cases."""

    process_uri: str = Field(min_length=1)
    name: str = Field(min_length=1)
    allowed_actions: list[str] = Field(
        default_factory=list,
        description="Action URIs permitted in cases of this process.",
    )
    goal: dict[str, Any] = Field(
        default_factory=dict,
        description="Predicate(s) that, once satisfied by case state, close the case.",
    )
    initial_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Default properties seeded into a new case's state.",
    )
    rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Opaque decision-table rules interpreted by a decision engine "
            "(e.g. the RuleEngine). Kept untyped here so core stays engine-agnostic."
        ),
    )
    bayesian: dict[str, Any] | None = Field(
        default=None,
        description="Optional Bayesian decision config interpreted by BayesianMpeEngine.",
    )
    engine: str | None = Field(
        default=None,
        description=(
            "Which decision engine drives next-action selection: 'rule', "
            "'bayesian', or 'llm'. If unset, it is inferred from the config "
            "present (bayesian block -> bayesian, rules -> rule)."
        ),
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "CMMN-style ordering constraints enforced at execute time. "
            "Shape: {'mutex': [[uri_a, uri_b], ...], 'requires': {uri: [prereq_uri, ...]}}."
        ),
    )

    def allows(self, action_uri: str) -> bool:
        """Whether an action is permitted in this process."""

        return action_uri in self.allowed_actions


def load_process(path: str | Path) -> ProcessDefinition:
    """Load and validate a process definition from a YAML file.

    Args:
        path: Path to the YAML file.

    Raises:
        ProcessParseError: If the file is missing, not a mapping, or invalid.
    """

    file_path = Path(path)
    if not file_path.exists():
        raise ProcessParseError(f"Process file not found: {file_path}")

    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProcessParseError(f"Invalid YAML in {file_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProcessParseError(
            f"Process file {file_path} must contain a YAML mapping."
        )

    try:
        return ProcessDefinition.model_validate(raw)
    except ValidationError as exc:
        raise ProcessParseError(
            f"Invalid process definition in {file_path}: {exc.errors()}"
        ) from exc
