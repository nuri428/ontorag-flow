"""End-to-end :class:`OntoragClient` against a real in-process MCP server.

These tests don't mock the transport. They stand up an actual
Streamable-HTTP MCP server in a background uvicorn thread (see
``_mcp_fixture.py``), point a real client at it, and exercise the
``connect`` / ``call_tool`` / ``list_tools`` / ``aclose`` lifecycle.

Together with the unit tests in ``test_ontorag_client.py``, this gives
us:

- Unit tests: contract / parsing / error wrapping (mocked session).
- This file: lifecycle — anyio task ownership, ``_serve`` happy path,
  the ``async with`` context manager, list_tools on a real session.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ontorag_flow.ontorag_client import OntoragClient, OntoragClientError
from tests._mcp_fixture import InProcessMcpServer


@pytest.fixture(scope="module")
def mcp_server() -> Iterator[InProcessMcpServer]:
    """One MCP server per module — startup is the slow bit, share across tests."""

    server = InProcessMcpServer(
        tools={
            "find_entities": lambda args: {
                "entities": [f"urn:test:{i}" for i in range(int(args.get("limit", 3)))]
            },
            "describe_entity": lambda args: {"uri": args["uri"], "label": "fake"},
        }
    )
    server.start()
    try:
        yield server
    finally:
        server.stop()


async def test_connect_against_real_mcp_server(mcp_server: InProcessMcpServer) -> None:
    """Exercises connect → _serve happy path → session ready."""

    client = OntoragClient(mcp_server.url)
    try:
        await client.connect()
        assert client.connected is True
    finally:
        await client.aclose()
        assert client.connected is False


async def test_call_tool_round_trips_through_real_session(
    mcp_server: InProcessMcpServer,
) -> None:
    client = OntoragClient(mcp_server.url)
    try:
        await client.connect()
        out = await client.call_tool("find_entities", {"query": "x", "limit": 4})
        assert out == {"entities": ["urn:test:0", "urn:test:1", "urn:test:2", "urn:test:3"]}
    finally:
        await client.aclose()


async def test_list_tools_against_real_session(mcp_server: InProcessMcpServer) -> None:
    client = OntoragClient(mcp_server.url)
    try:
        await client.connect()
        tools = await client.list_tools()
        assert "find_entities" in tools
        assert "describe_entity" in tools
    finally:
        await client.aclose()


async def test_async_context_manager_round_trip(mcp_server: InProcessMcpServer) -> None:
    """``async with`` enters connect() and exits aclose() in the same task."""

    async with OntoragClient(mcp_server.url) as client:
        assert client.connected is True
        out = await client.call_tool("describe_entity", {"uri": "urn:thing:42"})
        assert out == {"uri": "urn:thing:42", "label": "fake"}
    assert client.connected is False


async def test_unknown_tool_surfaces_as_typed_error(mcp_server: InProcessMcpServer) -> None:
    """The server raises → MCP marks isError=True → client raises OntoragClientError."""

    async with OntoragClient(mcp_server.url) as client:
        with pytest.raises(OntoragClientError):
            await client.call_tool("not_a_tool", {})
