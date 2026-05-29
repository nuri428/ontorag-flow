"""Typed wrappers over the read-only ontorag MCP tools used in v0.1.

Keeping the tool names and argument shapes in one place means the rest of the
codebase never hard-codes MCP call details. More wrappers (compute_posterior,
mpe, do_query) arrive alongside the engines that need them.
"""

from __future__ import annotations

from typing import Any

from ontorag_flow.ontorag_client.client import OntoragClient


async def find_entities(
    client: OntoragClient, query: str, *, limit: int = 10
) -> Any:
    """Look up entities in ontorag's ABox (also the connection smoke test)."""

    return await client.call_tool("find_entities", {"query": query, "limit": limit})


async def describe_entity(client: OntoragClient, uri: str) -> Any:
    """Fetch the full description of a single entity by URI."""

    return await client.call_tool("describe_entity", {"uri": uri})


async def get_schema(client: OntoragClient) -> Any:
    """Fetch ontorag's TBox schema (classes and properties)."""

    return await client.call_tool("get_schema", {})


async def compute_posterior(
    client: OntoragClient, evidence: dict[str, Any], query: Any
) -> Any:
    """Query P(query | evidence) from ontorag's Bayesian layer (requires ontorag v0.7)."""

    return await client.call_tool(
        "compute_posterior", {"evidence": evidence, "query": query}
    )


async def mpe(client: OntoragClient, evidence: dict[str, Any]) -> Any:
    """Most Probable Explanation given evidence (requires ontorag v0.7)."""

    return await client.call_tool("mpe", {"evidence": evidence})


async def do_query(
    client: OntoragClient, intervention: dict[str, Any], query: Any
) -> Any:
    """Pearl's do-operator: P(query | do(intervention)) (requires ontorag v0.8)."""

    return await client.call_tool(
        "do_query", {"intervention": intervention, "query": query}
    )


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


async def smoke_test(client: OntoragClient) -> bool:
    """Verify the ontorag connection works via a trivial ``find_entities`` call.

    Returns:
        True if the call round-trips without error.
    """

    await find_entities(client, query="*", limit=1)
    return True
