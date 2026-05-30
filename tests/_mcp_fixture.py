"""In-process MCP HTTP server for integration testing :class:`OntoragClient`.

The client wraps the official ``mcp`` SDK's Streamable HTTP transport plus a
``ClientSession``. Mocking those out (e.g. ``test_ontorag_client.py``) proves
the request/response *contract* but skips the lifecycle — the actual
``connect`` ↔ ``_serve`` ↔ ``aclose`` dance crossing anyio TaskGroup
boundaries.

This fixture stands up a real ``StreamableHTTPSessionManager`` behind a tiny
Starlette app running in a background uvicorn thread, on a free localhost
port. The tests then point a real :class:`OntoragClient` at it and exercise
the full lifecycle — no mock anywhere on the connection path.

Keeping it in its own module so test files stay declarative.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

import mcp.types as mt
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

# A tool response is either a literal JSON-serialisable value, or a callable
# that takes the args and returns one. ``"__error__"`` flips ``isError=True``
# on the response so we can also exercise the error branch.
ToolResponder = Any | Callable[[dict[str, Any]], Any]


def _build_app(tools: dict[str, ToolResponder]) -> Starlette:
    server: Server = Server("fake-ontorag")

    @server.list_tools()
    async def _list() -> list[mt.Tool]:
        return [
            mt.Tool(name=name, description=f"fake {name}", inputSchema={"type": "object"})
            for name in tools
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict[str, Any]) -> Any:
        if name not in tools:
            # MCP server lowlevel: raising surfaces as isError=True to the client.
            raise RuntimeError(f"unknown tool: {name}")
        responder = tools[name]
        payload = responder(arguments) if callable(responder) else responder
        return [mt.TextContent(type="text", text=json.dumps(payload))]

    manager = StreamableHTTPSessionManager(server, stateless=True)

    async def _asgi(scope: Any, receive: Any, send: Any) -> None:
        await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def _lifespan(_app: Starlette) -> Any:
        async with manager.run():
            yield

    return Starlette(lifespan=_lifespan, routes=[Mount("/mcp", app=_asgi)])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class InProcessMcpServer:
    """A real Streamable-HTTP MCP server pinned to localhost on a free port."""

    def __init__(self, tools: dict[str, ToolResponder]) -> None:
        self._app = _build_app(tools)
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}/mcp/"
        self._config = uvicorn.Config(
            self._app,
            host="127.0.0.1",
            port=self.port,
            log_level="error",
            lifespan="on",
        )
        self._server = uvicorn.Server(self._config)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.run(self._server.serve())

    def start(self, *, timeout: float = 5.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("in-process MCP server failed to start in time")

    def stop(self, *, timeout: float = 5.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=timeout)
