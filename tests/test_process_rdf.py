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
