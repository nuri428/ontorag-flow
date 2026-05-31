"""Z7 — ProcessDefinition rejects typos in execute_policy / audit_redact / arbitration.

Pydantic alone treats these as ``dict[str, Any]`` and ignores unknown
keys silently — exactly the failure mode where an operator's typo
turns a security gate into a permissive default. The model_validator
on ProcessDefinition catches them at parse time.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ontorag_flow.core.process import ProcessDefinition

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"


def _proc(**kw: object) -> ProcessDefinition:
    return ProcessDefinition(process_uri="urn:p:val", name="V", allowed_actions=[UPDATE], **kw)


# --- execute_policy shape ------------------------------------------------


def test_execute_policy_unknown_key_rejected() -> None:
    """Typo like 'min_confidance' would silently disable the gate; reject it."""

    with pytest.raises(ValidationError, match="execute_policy.*unknown keys.*min_confidance"):
        _proc(execute_policy={"auto": True, "min_confidance": 0.9})


def test_execute_policy_auto_must_be_bool() -> None:
    with pytest.raises(ValidationError, match="execute_policy.auto must be bool"):
        _proc(execute_policy={"auto": "yes"})


def test_execute_policy_min_confidence_must_be_in_unit_interval() -> None:
    with pytest.raises(ValidationError, match="execute_policy.min_confidence"):
        _proc(execute_policy={"auto": True, "min_confidence": 1.5})


def test_execute_policy_valid_shape_passes() -> None:
    proc = _proc(execute_policy={"auto": True, "min_confidence": 0.9})
    assert proc.execute_policy == {"auto": True, "min_confidence": 0.9}


# --- audit_redact pattern shape -----------------------------------------


def test_audit_redact_empty_string_rejected() -> None:
    with pytest.raises(ValidationError, match="audit_redact entries must be non-empty"):
        _proc(audit_redact=["ssn", ""])


def test_audit_redact_whitespace_only_rejected() -> None:
    with pytest.raises(ValidationError, match="audit_redact"):
        _proc(audit_redact=["ssn", "   "])


# --- arbitration shape ---------------------------------------------------


def test_arbitration_unknown_key_rejected() -> None:
    with pytest.raises(ValidationError, match="arbitration.*unknown keys.*proposor"):
        _proc(
            engine="stacked",
            arbitration={"proposor": "rule", "validator": "causal"},  # typo
        )


def test_arbitration_sequence_must_be_list_of_strings() -> None:
    with pytest.raises(ValidationError, match="arbitration.sequence"):
        _proc(engine="cascade", arbitration={"sequence": ["llm", 42]})


def test_arbitration_well_formed_passes() -> None:
    proc = _proc(
        engine="cascade",
        arbitration={"sequence": ["llm", "rule"], "health_check": True},
    )
    assert proc.arbitration is not None
    assert proc.arbitration["sequence"] == ["llm", "rule"]
