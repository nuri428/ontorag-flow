"""``ontorag-flow process test`` — run inline expectations as engine regression tests."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from ontorag_flow.cli import app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"


def _runner() -> CliRunner:
    return CliRunner(env={"COLUMNS": "240"})


@pytest.fixture
def passing_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "passing.yaml"
    path.write_text(
        dedent(
            f"""
            process_uri: urn:p:test-pass
            name: TestPass
            allowed_actions: [{UPDATE}]
            initial_state: {{ stage: ready }}
            rules:
              - name: ready-to-go
                when: {{ stage: ready }}
                then: {{ action: {UPDATE}, params: {{ key: stage, value: done }} }}
            expectations:
              - name: ready proposes update
                given_state: {{ stage: ready }}
                proposes: {UPDATE}
              - name: blocked proposes nothing
                given_state: {{ stage: blocked }}
                proposes_none: true
              - name: execute-top transitions stage
                given_state: {{ stage: ready }}
                after_execute_top:
                  state: {{ stage: done }}
            """
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def failing_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "failing.yaml"
    path.write_text(
        dedent(
            f"""
            process_uri: urn:p:test-fail
            name: TestFail
            allowed_actions: [{UPDATE}]
            rules:
              - name: never-fires
                when: {{ impossible: true }}
                then: {{ action: {UPDATE} }}
            expectations:
              - name: should propose update but won't
                given_state: {{}}
                proposes: {UPDATE}
            """
        ),
        encoding="utf-8",
    )
    return path


def test_process_test_passes_when_expectations_match(passing_yaml: Path) -> None:
    result = _runner().invoke(app, ["process", "test", str(passing_yaml)])
    assert result.exit_code == 0, result.output
    assert "All 3 expectation(s) passed" in result.output


def test_process_test_exits_nonzero_when_an_expectation_fails(failing_yaml: Path) -> None:
    result = _runner().invoke(app, ["process", "test", str(failing_yaml)])
    assert result.exit_code == 1
    assert "expectation(s) failed" in result.output
    assert "should propose update but won't" in result.output


def test_process_test_complains_when_no_expectations_present(tmp_path: Path) -> None:
    path = tmp_path / "no_exp.yaml"
    path.write_text(
        f"process_uri: urn:p:noexp\nname: NoExp\nallowed_actions: [{UPDATE}]\n",
        encoding="utf-8",
    )
    result = _runner().invoke(app, ["process", "test", str(path)])
    assert result.exit_code == 1
    assert "No 'expectations:'" in result.output


def test_process_test_404_for_missing_file(tmp_path: Path) -> None:
    result = _runner().invoke(app, ["process", "test", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1
    assert "Not found" in result.output
