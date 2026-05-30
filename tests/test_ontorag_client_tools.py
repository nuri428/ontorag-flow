"""Typed wrappers in :mod:`ontorag_flow.ontorag_client.tools`.

Each wrapper is a thin translation from a Python signature into the MCP
``call_tool`` shape. We don't need a live MCP server — a fake client that
records its calls is enough to lock in the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ontorag_flow.ontorag_client.tools import (
    assert_triple,
    compute_posterior,
    counterfactual,
    describe_entity,
    do_query,
    find_entities,
    get_schema,
    retract_triple,
    smoke_test,
)


@dataclass
class FakeClient:
    """Records every call_tool invocation; returns whatever was queued."""

    response: Any = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, args))
        return self.response


@pytest.fixture
def client() -> FakeClient:
    return FakeClient(response={"ok": True})


async def test_find_entities_forwards_query_and_limit(client: FakeClient) -> None:
    out = await find_entities(client, "needle", limit=5)  # type: ignore[arg-type]
    assert out == {"ok": True}
    assert client.calls == [("find_entities", {"query": "needle", "limit": 5})]


async def test_describe_entity_forwards_uri(client: FakeClient) -> None:
    await describe_entity(client, "urn:thing:42")  # type: ignore[arg-type]
    assert client.calls == [("describe_entity", {"uri": "urn:thing:42"})]


async def test_get_schema_sends_empty_args(client: FakeClient) -> None:
    await get_schema(client)  # type: ignore[arg-type]
    assert client.calls == [("get_schema", {})]


async def test_compute_posterior_forwards_evidence_and_query(client: FakeClient) -> None:
    await compute_posterior(client, {"e": 1}, {"q": True})  # type: ignore[arg-type]
    assert client.calls == [("compute_posterior", {"evidence": {"e": 1}, "query": {"q": True}})]


async def test_do_query_forwards_intervention(client: FakeClient) -> None:
    await do_query(client, {"x": 0}, {"y": True})  # type: ignore[arg-type]
    assert client.calls == [("do_query", {"intervention": {"x": 0}, "query": {"y": True}})]


async def test_counterfactual_forwards_all_three(client: FakeClient) -> None:
    await counterfactual(client, {"e": 1}, {"i": 0}, {"q": True})  # type: ignore[arg-type]
    assert client.calls == [
        (
            "counterfactual",
            {"evidence": {"e": 1}, "intervention": {"i": 0}, "query": {"q": True}},
        )
    ]


async def test_smoke_test_returns_true_on_success(client: FakeClient) -> None:
    assert await smoke_test(client) is True  # type: ignore[arg-type]
    assert client.calls == [("find_entities", {"query": "*", "limit": 1})]


async def test_assert_triple_forwards_spo_without_graph(client: FakeClient) -> None:
    await assert_triple(client, "urn:s", "urn:p", "urn:o")  # type: ignore[arg-type]
    assert client.calls == [
        ("assert_triple", {"subject": "urn:s", "predicate": "urn:p", "object": "urn:o"})
    ]


async def test_assert_triple_includes_named_graph_when_given(client: FakeClient) -> None:
    await assert_triple(client, "urn:s", "urn:p", "urn:o", graph="urn:g")  # type: ignore[arg-type]
    assert client.calls == [
        (
            "assert_triple",
            {"subject": "urn:s", "predicate": "urn:p", "object": "urn:o", "graph": "urn:g"},
        )
    ]


async def test_retract_triple_mirrors_assert_triple_shape(client: FakeClient) -> None:
    await retract_triple(client, "urn:s", "urn:p", "urn:o", graph="urn:g")  # type: ignore[arg-type]
    assert client.calls == [
        (
            "retract_triple",
            {"subject": "urn:s", "predicate": "urn:p", "object": "urn:o", "graph": "urn:g"},
        )
    ]
