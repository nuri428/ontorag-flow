"""``ontorag-flow process simulate`` — dry-run a process YAML against the engine.

The command builds an in-memory case, asks the engine, optionally executes
the top proposal, optionally prints the engine's explain trace. Nothing is
persisted, so this is the right CLI for *iterating on a process YAML*.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from ontorag_flow.cli import app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"


@pytest.fixture
def process_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "p.yaml"
    path.write_text(
        dedent(
            f"""
            process_uri: urn:p:sim
            name: SimTest
            allowed_actions: [{UPDATE}]
            goal: {{ done: true }}
            initial_state: {{ stage: ready }}
            rules:
              - name: ready-to-mark
                when: {{ stage: ready }}
                then: {{ action: {UPDATE}, params: {{ key: marked, value: true }} }}
                confidence: 0.9
            """
        ),
        encoding="utf-8",
    )
    return path


def _runner() -> CliRunner:
    # Wider columns so Rich tables don't wrap long URIs out of recognition.
    return CliRunner(env={"COLUMNS": "240"})


def test_simulate_shows_proposals(process_yaml: Path) -> None:
    result = _runner().invoke(app, ["process", "simulate", str(process_yaml)])
    assert result.exit_code == 0, result.output
    assert "Simulated case" in result.output
    assert "in-memory; not persisted" in result.output
    assert "ready-to-mark" in result.output
    assert UPDATE in result.output


def test_simulate_with_initial_state_override(process_yaml: Path) -> None:
    result = _runner().invoke(
        app, ["process", "simulate", str(process_yaml), "-s", "stage=blocked"]
    )
    assert result.exit_code == 0, result.output
    # The rule's `when: stage=ready` no longer matches → no proposals.
    assert "no proposals" in result.output.lower()


def test_simulate_execute_top_applies_proposal(process_yaml: Path) -> None:
    result = _runner().invoke(app, ["process", "simulate", str(process_yaml), "--execute-top"])
    assert result.exit_code == 0, result.output
    assert "Executed" in result.output
    assert '"marked": true' in result.output or '"marked":true' in result.output


def test_simulate_explain_prints_trace(process_yaml: Path) -> None:
    result = _runner().invoke(app, ["process", "simulate", str(process_yaml), "--explain"])
    assert result.exit_code == 0, result.output
    assert "RuleEngine" in result.output
    assert "rules_fired" in result.output
