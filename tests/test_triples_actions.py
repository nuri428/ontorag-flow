"""AssertTriple / RetractTriple — write-back actions over ontorag MCP.

The actions are pure forwarding shims: parameter shape in, MCP tool call
out, ``ActionResult`` with the same shape back. The saga ``compensate``
hook is the symmetric pair (assert ↔ retract).

We never need a real MCP server here — the fake client just records what
the action would have sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ontorag_flow.actions.triples import AssertTriple, RetractTriple, _TripleParams
from ontorag_flow.core.action import SideEffectKind
from ontorag_flow.core.registry import ActionRegistry, default_registry, with_triple_actions
from ontorag_flow.core.state import CaseState


@dataclass
class FakeOntoragClient:
    """Records MCP tool calls; mimics :class:`OntoragClient` for typing."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return None


def _client() -> FakeOntoragClient:
    return FakeOntoragClient()


# --- AssertTriple --------------------------------------------------------


async def test_assert_triple_calls_assert_triple_mcp_tool() -> None:
    client = _client()
    action = AssertTriple(client)  # type: ignore[arg-type]
    params = _TripleParams(subject="urn:s", predicate="urn:p", object="urn:o")

    result = await action.execute(params, CaseState())

    assert result.success is True
    assert result.action_uri == AssertTriple.uri
    assert client.calls == [
        ("assert_triple", {"subject": "urn:s", "predicate": "urn:p", "object": "urn:o"})
    ]
    # Outputs round-trip the triple shape for the compensate hook.
    assert result.outputs["operation"] == "assert"
    assert result.outputs["subject"] == "urn:s"


async def test_assert_triple_declares_abox_write_side_effect() -> None:
    """The executor's write-ahead audit fires only for externally-visible side effects."""

    assert AssertTriple.side_effects == frozenset({SideEffectKind.ABOX_WRITE})


async def test_assert_triple_passes_named_graph_when_set() -> None:
    client = _client()
    action = AssertTriple(client)  # type: ignore[arg-type]
    params = _TripleParams(subject="urn:s", predicate="urn:p", object="urn:o", graph="urn:g")

    await action.execute(params, CaseState())

    assert client.calls == [
        (
            "assert_triple",
            {"subject": "urn:s", "predicate": "urn:p", "object": "urn:o", "graph": "urn:g"},
        )
    ]


async def test_assert_triple_compensate_issues_retract() -> None:
    """Saga rollback: AssertTriple → compensate → retract_triple on the same shape."""

    client = _client()
    action = AssertTriple(client)  # type: ignore[arg-type]
    params = _TripleParams(subject="urn:s", predicate="urn:p", object="urn:o", graph="urn:g")
    result = await action.execute(params, CaseState())

    await action.compensate(result)

    assert client.calls[-1] == (
        "retract_triple",
        {"subject": "urn:s", "predicate": "urn:p", "object": "urn:o", "graph": "urn:g"},
    )


# --- RetractTriple -------------------------------------------------------


async def test_retract_triple_calls_retract_triple_mcp_tool() -> None:
    client = _client()
    action = RetractTriple(client)  # type: ignore[arg-type]
    params = _TripleParams(subject="urn:s", predicate="urn:p", object="urn:o")

    result = await action.execute(params, CaseState())

    assert result.success is True
    assert result.action_uri == RetractTriple.uri
    assert client.calls == [
        ("retract_triple", {"subject": "urn:s", "predicate": "urn:p", "object": "urn:o"})
    ]
    assert result.outputs["operation"] == "retract"


async def test_retract_triple_compensate_re_asserts() -> None:
    """Saga rollback: RetractTriple → compensate → assert_triple."""

    client = _client()
    action = RetractTriple(client)  # type: ignore[arg-type]
    params = _TripleParams(subject="urn:s", predicate="urn:p", object="urn:o")
    result = await action.execute(params, CaseState())

    await action.compensate(result)

    assert client.calls[-1] == (
        "assert_triple",
        {"subject": "urn:s", "predicate": "urn:p", "object": "urn:o"},
    )


# --- Registry wiring -----------------------------------------------------


def test_default_registry_does_not_include_triple_actions() -> None:
    """Without an injected client, ABox actions are not registered."""

    registry = default_registry()
    assert AssertTriple.uri not in registry
    assert RetractTriple.uri not in registry


def test_with_triple_actions_adds_both_when_client_provided() -> None:
    registry = with_triple_actions(default_registry(), _client())  # type: ignore[arg-type]
    assert AssertTriple.uri in registry
    assert RetractTriple.uri in registry


def test_with_triple_actions_rejects_non_client_objects() -> None:
    with pytest.raises(TypeError, match="OntoragClient"):
        with_triple_actions(ActionRegistry(), "not a client")  # type: ignore[arg-type]


def test_input_schema_rejects_empty_uris() -> None:
    """All three URIs are required and must be non-empty (pydantic guard)."""

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _TripleParams(subject="", predicate="urn:p", object="urn:o")
