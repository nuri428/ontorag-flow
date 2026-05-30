"""Typed wrappers over the read-only ontorag MCP tools used in v0.1.

Keeping the tool names and argument shapes in one place means the rest of the
codebase never hard-codes MCP call details. More wrappers (compute_posterior,
mpe, do_query) arrive alongside the engines that need them.
"""

from __future__ import annotations

from typing import Any

from ontorag_flow.ontorag_client.client import OntoragClient


async def find_entities(client: OntoragClient, query: str, *, limit: int = 10) -> Any:
    """Look up entities in ontorag's ABox (also the connection smoke test)."""

    return await client.call_tool("find_entities", {"query": query, "limit": limit})


async def describe_entity(client: OntoragClient, uri: str) -> Any:
    """Fetch the full description of a single entity by URI."""

    return await client.call_tool("describe_entity", {"uri": uri})


async def get_schema(client: OntoragClient) -> Any:
    """Fetch ontorag's TBox schema (classes and properties)."""

    return await client.call_tool("get_schema", {})


async def compute_posterior(client: OntoragClient, evidence: dict[str, Any], query: Any) -> Any:
    """Query P(query | evidence) from ontorag's Bayesian layer (requires ontorag v0.7)."""

    return await client.call_tool("compute_posterior", {"evidence": evidence, "query": query})


async def do_query(client: OntoragClient, intervention: dict[str, Any], query: Any) -> Any:
    """Pearl's do-operator: P(query | do(intervention)) (requires ontorag v0.8)."""

    return await client.call_tool("do_query", {"intervention": intervention, "query": query})


async def counterfactual(
    client: OntoragClient,
    evidence: dict[str, Any],
    intervention: dict[str, Any],
    query: Any,
) -> Any:
    """Counterfactual replay: P(query | evidence, do(intervention)) (requires ontorag v0.8)."""

    return await client.call_tool(
        "counterfactual",
        {"evidence": evidence, "intervention": intervention, "query": query},
    )


async def assert_triple(
    client: OntoragClient,
    subject: str,
    predicate: str,
    object_: str,
    *,
    graph: str | None = None,
) -> Any:
    """Write one ``(s, p, o)`` triple to ontorag's ABox (requires ontorag v0.7.x).

    The CLAUDE.md *Open question* "Write-back to ontorag" picks
    ``assert_triple`` over a ``load_rdf`` round-trip for the
    single-triple-per-call write path — fewer hops, no RDF serialisation,
    typed at the tool boundary. When ontorag exposes the tool, this is
    the fast path the :class:`AssertTriple` action calls.
    """

    args: dict[str, Any] = {"subject": subject, "predicate": predicate, "object": object_}
    if graph is not None:
        args["graph"] = graph
    return await client.call_tool("assert_triple", args)


async def retract_triple(
    client: OntoragClient,
    subject: str,
    predicate: str,
    object_: str,
    *,
    graph: str | None = None,
) -> Any:
    """Remove one ``(s, p, o)`` triple from ontorag's ABox (requires ontorag v0.7.x).

    The compensation pair to :func:`assert_triple` — saga rollback of an
    earlier write goes through this so the ABox returns to its pre-action
    shape.
    """

    args: dict[str, Any] = {"subject": subject, "predicate": predicate, "object": object_}
    if graph is not None:
        args["graph"] = graph
    return await client.call_tool("retract_triple", args)


async def smoke_test(client: OntoragClient) -> bool:
    """Verify the ontorag connection works via a trivial ``find_entities`` call.

    Returns:
        True if the call round-trips without error.
    """

    await find_entities(client, query="*", limit=1)
    return True
