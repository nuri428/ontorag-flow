"""RDF (Turtle) process representation round-trips back to ProcessDefinition."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontorag_flow.core.process import ProcessDefinition, ProcessParseError
from ontorag_flow.core.process_rdf import load_process_rdf, process_to_rdf


def test_round_trip(tmp_path: Path) -> None:
    process = ProcessDefinition(
        process_uri="urn:ontorag-flow:process:triage",
        name="Triage",
        allowed_actions=["urn:a:1", "urn:a:2"],
        goal={"diagnosed": True},
        initial_state={"level": "unknown"},
        rules=[{"name": "r", "when": {}, "then": {"action": "urn:a:1"}}],
    )

    ttl = process_to_rdf(process)
    path = tmp_path / "process.ttl"
    path.write_text(ttl, encoding="utf-8")
    loaded = load_process_rdf(path)

    assert loaded.process_uri == "urn:ontorag-flow:process:triage"
    assert loaded.name == "Triage"
    assert sorted(loaded.allowed_actions) == ["urn:a:1", "urn:a:2"]
    assert loaded.goal == {"diagnosed": True}
    assert loaded.initial_state == {"level": "unknown"}
    assert loaded.rules == [{"name": "r", "when": {}, "then": {"action": "urn:a:1"}}]


def test_round_trip_with_bayesian(tmp_path: Path) -> None:
    process = ProcessDefinition(
        process_uri="urn:p:b",
        name="B",
        allowed_actions=["urn:a:1"],
        bayesian={"target": {"diagnosed": True}, "candidates": []},
    )
    path = tmp_path / "b.ttl"
    path.write_text(process_to_rdf(process), encoding="utf-8")
    loaded = load_process_rdf(path)
    assert loaded.bayesian == {"target": {"diagnosed": True}, "candidates": []}


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ProcessParseError):
        load_process_rdf(tmp_path / "nope.ttl")


def test_no_process_subject_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.ttl"
    path.write_text("@prefix of: <urn:ontorag-flow:process#> .\n", encoding="utf-8")
    with pytest.raises(ProcessParseError):
        load_process_rdf(path)


def test_full_round_trip_preserves_every_field(tmp_path: Path) -> None:
    """Every ProcessDefinition field survives a Turtle round-trip — including
    causal / engine / constraints / timer_events, added in v0.7–v0.9."""

    process = ProcessDefinition(
        process_uri="urn:p:full",
        name="Full",
        allowed_actions=["urn:a:1", "urn:a:2"],
        engine="causal",
        goal={"diagnosed": True},
        initial_state={"triage_level": "unknown"},
        rules=[{"name": "r", "when": {}, "then": {"action": "urn:a:1"}}],
        bayesian={"target": {"diagnosed": True}, "candidates": []},
        causal={"target": {"diagnosed": True}, "candidates": []},
        constraints={
            "mutex": [["urn:a:1", "urn:a:2"]],
            "requires": {"urn:a:2": ["urn:a:1"]},
            "immediately_after": {"urn:a:2": "urn:a:1"},
            "at_most_once": ["urn:a:1"],
        },
        timer_events=[
            {"after_minutes": 0, "action": "urn:a:1", "params": {"k": "v"}},
        ],
        arbitration={"proposer": "rule", "validator": "causal"},
    )

    path = tmp_path / "full.ttl"
    path.write_text(process_to_rdf(process), encoding="utf-8")
    loaded = load_process_rdf(path)

    assert loaded.engine == "causal"
    assert loaded.bayesian == process.bayesian
    assert loaded.causal == process.causal
    assert loaded.constraints == process.constraints
    assert loaded.timer_events == process.timer_events
    assert loaded.rules == process.rules
    assert loaded.goal == process.goal
    assert loaded.initial_state == process.initial_state
    assert loaded.arbitration == process.arbitration


def test_json_ld_round_trip(tmp_path: Path) -> None:
    """JSON-LD format works alongside Turtle; suffix dispatch picks it up."""

    process = ProcessDefinition(
        process_uri="urn:p:jsonld",
        name="JSON-LD",
        allowed_actions=["urn:a:1"],
        engine="rule",
        goal={"done": True},
    )

    path = tmp_path / "p.jsonld"
    path.write_text(process_to_rdf(process, format="json-ld"), encoding="utf-8")
    loaded = load_process_rdf(path)

    assert loaded.process_uri == "urn:p:jsonld"
    assert loaded.engine == "rule"
    assert loaded.goal == {"done": True}


def test_explicit_format_overrides_suffix(tmp_path: Path) -> None:
    """When the suffix is misleading, the explicit format argument wins."""

    process = ProcessDefinition(process_uri="urn:p:x", name="X", allowed_actions=[])
    # Serialize as turtle but save with a .jsonld suffix on purpose.
    path = tmp_path / "misleading.jsonld"
    path.write_text(process_to_rdf(process, format="turtle"), encoding="utf-8")

    loaded = load_process_rdf(path, format="turtle")
    assert loaded.process_uri == "urn:p:x"


def test_malformed_json_literal_raises(tmp_path: Path) -> None:
    """A JSON literal that is not valid JSON surfaces as ProcessParseError."""

    path = tmp_path / "bad.ttl"
    path.write_text(
        "@prefix of: <urn:ontorag-flow:process#> .\n"
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n"
        '<urn:p:bad> a of:Process ; of:name "Bad" ; of:goalJson "{not json" .\n',
        encoding="utf-8",
    )
    with pytest.raises(ProcessParseError):
        load_process_rdf(path)


def test_blank_node_process_subject_rejected(tmp_path: Path) -> None:
    """The of:Process subject must be a URI, not a blank node."""

    path = tmp_path / "blank.ttl"
    path.write_text(
        '@prefix of: <urn:ontorag-flow:process#> .\n_:b a of:Process ; of:name "Blank" .\n',
        encoding="utf-8",
    )
    with pytest.raises(ProcessParseError, match="must be a URI"):
        load_process_rdf(path)
