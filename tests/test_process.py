"""Process definition loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontorag_flow.core.process import ProcessParseError, load_process


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "process.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_process(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "process_uri: urn:p:1\n"
        "name: Triage\n"
        "allowed_actions:\n"
        "  - urn:a:1\n"
        "goal:\n"
        "  done: true\n"
        "initial_state:\n"
        "  level: unknown\n",
    )

    process = load_process(path)

    assert process.process_uri == "urn:p:1"
    assert process.allows("urn:a:1")
    assert not process.allows("urn:a:2")
    assert process.goal == {"done": True}
    assert process.initial_state == {"level": "unknown"}


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ProcessParseError):
        load_process(tmp_path / "nope.yaml")


def test_non_mapping_raises(tmp_path: Path) -> None:
    with pytest.raises(ProcessParseError):
        load_process(_write(tmp_path, "- a\n- b\n"))


def test_invalid_definition_raises(tmp_path: Path) -> None:
    # Missing required process_uri.
    with pytest.raises(ProcessParseError):
        load_process(_write(tmp_path, "name: only-name\n"))
