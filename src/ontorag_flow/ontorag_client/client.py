"""Connection management for ontorag's MCP server.

A single, shared Streamable-HTTP session is opened on :meth:`connect` and reused
for every tool call (the project keeps one connection, not one per call).

Why a background task owns the connection
-----------------------------------------
``streamablehttp_client``/``ClientSession`` run anyio task groups, and anyio's
structured-concurrency rule requires a task group to be *exited in the same task
that entered it*. Holding the transport open across separate ``connect()`` and
``aclose()`` calls (e.g. via ``AsyncExitStack``) violates that rule the moment a
cancellation crosses scopes, producing "cancel scope exited in a different task"
errors. So a dedicated :meth:`_serve` task owns the whole ``async with``
lifecycle; the public methods talk to it through asyncio events and the session's
(cross-task-safe) memory streams.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from ontorag_flow.log import get_logger

logger = get_logger(__name__)


class OntoragClientError(RuntimeError):
    """Raised when the ontorag MCP server cannot be reached or returns an error."""


class OntoragClient:
    """Thin async wrapper over an ontorag MCP session (read-only in v0.1)."""

    def __init__(self, mcp_url: str) -> None:
        self._mcp_url = mcp_url
        self._session: ClientSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._connect_error: BaseException | None = None

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> None:
        """Open and initialise the shared MCP session.

        Raises:
            OntoragClientError: If the server cannot be reached or initialised.
        """

        if self._task is not None:
            return

        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._connect_error = None
        self._task = asyncio.create_task(self._serve(), name="ontorag-mcp-session")

        ready_waiter = asyncio.ensure_future(self._ready.wait())
        try:
            await asyncio.wait(
                {ready_waiter, self._task}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            ready_waiter.cancel()

        if not self._ready.is_set():
            # _serve exited before signalling ready -> connection failed.
            error = self._connect_error
            await self._await_task()
            self._task = None
            detail = _root_cause(error) if error is not None else "unknown error"
            raise OntoragClientError(
                f"Could not connect to ontorag MCP at {self._mcp_url}: {detail}"
            )

        logger.info("Connected to ontorag MCP at %s", self._mcp_url)

    async def _serve(self) -> None:
        """Own the session lifecycle for one connection, in a single task."""

        try:
            async with streamablehttp_client(self._mcp_url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._ready.set()
                    await self._shutdown.wait()
        except BaseException as exc:  # noqa: BLE001 — relayed to connect()
            self._connect_error = exc
        finally:
            self._session = None

    async def aclose(self) -> None:
        """Signal the session task to close and wait for it to finish."""

        if self._task is None:
            return
        self._shutdown.set()
        await self._await_task()
        self._task = None

    async def _await_task(self) -> None:
        """Await the serve task, swallowing its (already-captured) errors."""

        if self._task is None:
            return
        try:
            await self._task
        except BaseException:  # noqa: BLE001 — teardown errors are non-actionable
            logger.debug("Suppressed error while closing ontorag MCP session.")

    async def __aenter__(self) -> OntoragClient:
        await self.connect()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an ontorag MCP tool and return its parsed payload.

        Args:
            name: The ontorag tool name (e.g. ``"find_entities"``).
            arguments: The tool arguments.

        Raises:
            OntoragClientError: If not connected or the tool reports an error.
        """

        if self._session is None:
            raise OntoragClientError("Not connected — call connect() first.")

        result = await self._session.call_tool(name, arguments)
        if getattr(result, "isError", False):
            raise OntoragClientError(f"ontorag tool {name!r} returned an error.")
        return _parse_tool_result(result)

    async def list_tools(self) -> list[str]:
        """Return the names of tools the ontorag server exposes."""

        if self._session is None:
            raise OntoragClientError("Not connected — call connect() first.")
        result = await self._session.list_tools()
        return [tool.name for tool in result.tools]


def _root_cause(exc: BaseException) -> str:
    """Render a concise message, unwrapping ExceptionGroups to their leaves."""

    if isinstance(exc, BaseExceptionGroup):
        leaves = [_root_cause(inner) for inner in exc.exceptions]
        return "; ".join(dict.fromkeys(leaves)) or str(exc)
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def _parse_tool_result(result: Any) -> Any:
    """Extract a usable payload from an MCP ``CallToolResult``.

    Prefers ``structuredContent``; otherwise decodes text content blocks as JSON
    (falling back to the raw text when it is not JSON).
    """

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured

    content = getattr(result, "content", None) or []
    texts: list[str] = [
        block.text for block in content if getattr(block, "type", None) == "text"
    ]
    if not texts:
        return None
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined
