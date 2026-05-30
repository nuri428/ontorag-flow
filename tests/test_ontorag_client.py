"""ontorag MCP client — result parsing and error handling (mocked session)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ontorag_flow.ontorag_client.client import (
    OntoragClient,
    OntoragClientError,
    _parse_tool_result,
    _root_cause,
)
from ontorag_flow.ontorag_client.tools import find_entities


def test_parse_prefers_structured_content() -> None:
    result = SimpleNamespace(structuredContent={"entities": []}, content=[])
    assert _parse_tool_result(result) == {"entities": []}


def test_parse_decodes_json_text_block() -> None:
    block = SimpleNamespace(type="text", text='{"count": 2}')
    result = SimpleNamespace(structuredContent=None, content=[block])
    assert _parse_tool_result(result) == {"count": 2}


def test_parse_falls_back_to_raw_text() -> None:
    block = SimpleNamespace(type="text", text="not json")
    result = SimpleNamespace(structuredContent=None, content=[block])
    assert _parse_tool_result(result) == "not json"


async def test_call_tool_requires_connection() -> None:
    client = OntoragClient("http://localhost:8000/mcp")
    with pytest.raises(OntoragClientError):
        await client.call_tool("find_entities", {})


async def test_call_tool_parses_and_wraps_errors() -> None:
    client = OntoragClient("http://localhost:8000/mcp")
    session = AsyncMock()
    session.call_tool.return_value = SimpleNamespace(
        isError=False, structuredContent={"entities": ["urn:x"]}, content=[]
    )
    client._session = session  # type: ignore[attr-defined]

    payload = await find_entities(client, "x", limit=5)

    assert payload == {"entities": ["urn:x"]}
    session.call_tool.assert_awaited_once_with("find_entities", {"query": "x", "limit": 5})


async def test_call_tool_raises_on_tool_error() -> None:
    client = OntoragClient("http://localhost:8000/mcp")
    session = AsyncMock()
    session.call_tool.return_value = SimpleNamespace(
        isError=True, structuredContent=None, content=[]
    )
    client._session = session  # type: ignore[attr-defined]

    with pytest.raises(OntoragClientError):
        await client.call_tool("find_entities", {})


async def test_connect_to_unreachable_server_raises_cleanly() -> None:
    # Port 1 is not listening; the anyio TaskGroup teardown must not leak an
    # ExceptionGroup — we expect a single, typed OntoragClientError.
    client = OntoragClient("http://127.0.0.1:1/mcp")

    with pytest.raises(OntoragClientError):
        await client.connect()

    assert client.connected is False
    await client.aclose()  # idempotent / safe after a failed connect


async def test_call_tool_detects_zombie_session() -> None:
    # Simulate a connected client whose background serve task has already
    # exited (e.g. ontorag server hung up). Without the guard, the next
    # call_tool would hang on memory streams that nobody feeds.
    import asyncio
    from unittest.mock import AsyncMock as _AsyncMock

    client = OntoragClient("http://127.0.0.1:1/mcp")

    async def _serve_that_dies() -> None:
        raise RuntimeError("server hung up mid-session")

    task = asyncio.create_task(_serve_that_dies())
    await asyncio.wait({task})

    client._task = task  # type: ignore[attr-defined]
    client._session = _AsyncMock()  # type: ignore[attr-defined]

    with pytest.raises(OntoragClientError, match="ended unexpectedly"):
        await client.call_tool("anything", {})

    # The guard reset client state so a subsequent connect() can re-establish.
    assert client._session is None  # type: ignore[attr-defined]
    assert client._task is None  # type: ignore[attr-defined]


def test_root_cause_unwraps_exception_group() -> None:
    group = ExceptionGroup("boom", [ConnectionError("refused"), ConnectionError("refused")])
    message = _root_cause(group)

    assert "ConnectionError: refused" in message
    # duplicate leaves collapse to a single entry
    assert message.count("ConnectionError: refused") == 1


def test_root_cause_uses_class_name_when_str_is_empty() -> None:
    assert _root_cause(RuntimeError()) == "RuntimeError"


def test_parse_returns_none_when_no_text_blocks() -> None:
    result = SimpleNamespace(structuredContent=None, content=[])
    assert _parse_tool_result(result) is None


async def test_aclose_is_idempotent_when_never_connected() -> None:
    client = OntoragClient("http://localhost:8000/mcp")
    await client.aclose()  # no task; should be a no-op (line 102-103)


async def test_connect_is_idempotent_when_already_connecting() -> None:
    """A second connect() while a task is alive returns immediately (line 59)."""

    import asyncio

    client = OntoragClient("http://localhost:8000/mcp")
    pretend_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(60))
    client._task = pretend_task  # type: ignore[attr-defined]
    try:
        await client.connect()  # short-circuit early return
    finally:
        pretend_task.cancel()
        try:
            await pretend_task
        except asyncio.CancelledError:
            pass


async def test_list_tools_requires_connection() -> None:
    client = OntoragClient("http://localhost:8000/mcp")
    with pytest.raises(OntoragClientError):
        await client.list_tools()


async def test_list_tools_returns_tool_names() -> None:
    client = OntoragClient("http://localhost:8000/mcp")
    session = AsyncMock()
    tool_a = SimpleNamespace(name="find_entities")
    tool_b = SimpleNamespace(name="describe_entity")
    session.list_tools.return_value = SimpleNamespace(tools=[tool_a, tool_b])
    client._session = session  # type: ignore[attr-defined]

    names = await client.list_tools()
    assert names == ["find_entities", "describe_entity"]


async def test_await_task_swallows_exceptions_during_teardown() -> None:
    """``aclose()`` after a task crashed mid-life must not re-raise."""

    import asyncio

    client = OntoragClient("http://localhost:8000/mcp")

    async def _crash() -> None:
        raise RuntimeError("simulated mid-life crash")

    task: asyncio.Task[None] = asyncio.create_task(_crash())
    # Let it finish so the exception is set on the task.
    try:
        await task
    except RuntimeError:
        pass

    client._task = task  # type: ignore[attr-defined]
    # aclose() should not re-raise the swallowed exception.
    await client.aclose()


async def test_zombie_guard_uses_connect_error_when_cancelled() -> None:
    """When the serve task was cancelled, fall back to ``_connect_error`` for the cause."""

    import asyncio

    client = OntoragClient("http://localhost:8000/mcp")

    async def _placeholder() -> None:
        await asyncio.sleep(0.01)

    task: asyncio.Task[None] = asyncio.create_task(_placeholder())
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    client._task = task  # type: ignore[attr-defined]
    client._session = AsyncMock()  # type: ignore[attr-defined]
    client._connect_error = RuntimeError("recorded cause")  # type: ignore[attr-defined]

    with pytest.raises(OntoragClientError, match="recorded cause"):
        await client.call_tool("anything", {})
