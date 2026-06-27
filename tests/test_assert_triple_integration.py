"""AssertTriple / RetractTriple 연동 테스트.

Unit  — InProcessMcpServer(fake ontorag)로 액션 흐름 전체 검증.
Integration — 실제 ontorag HTTP MCP(localhost:8000)와 Fuseki(localhost:3030) 연동.
"""

from __future__ import annotations

from typing import Any

import pytest

from ontorag_flow.actions.triples import AssertTriple, RetractTriple
from ontorag_flow.core.action import SideEffectKind
from ontorag_flow.core.state import EMPTY_STATE
from tests._mcp_fixture import InProcessMcpServer

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fake_ontorag(captured: list[dict]) -> InProcessMcpServer:
    """assert_triple / retract_triple 호출을 기록하는 fake MCP 서버."""

    def _responder(name: str) -> Any:
        def _handler(args: dict[str, Any]) -> dict:
            captured.append({"tool": name, **args})
            return {"status": name.replace("_", "d "), "triple": args}

        return _handler

    return InProcessMcpServer(
        {
            "assert_triple": _responder("assert_triple"),
            "retract_triple": _responder("retract_triple"),
        }
    )


# ── Unit 테스트 — fake ontorag ────────────────────────────────────────────────


class TestAssertTripleAction:
    def test_declares_abox_write_side_effect(self) -> None:
        from unittest.mock import MagicMock

        action = AssertTriple(MagicMock())
        assert SideEffectKind.ABOX_WRITE in action.side_effects

    def test_auto_execute_disabled(self) -> None:
        assert AssertTriple.auto_execute_disabled is True
        assert RetractTriple.auto_execute_disabled is True

    async def test_execute_calls_assert_triple_tool(self) -> None:
        captured: list[dict] = []
        server = _fake_ontorag(captured)
        server.start()

        from ontorag_flow.ontorag_client.client import OntoragClient

        client = OntoragClient(server.url)
        await client.connect()

        action = AssertTriple(client)
        params = action.input_schema.model_validate(
            {
                "subject": "urn:test:s",
                "predicate": "urn:test:p",
                "object": "hello world",
            }
        )
        result = await action.execute(params, EMPTY_STATE)

        assert result.success is True
        assert result.outputs["operation"] == "assert"
        assert len(captured) == 1
        assert captured[0]["tool"] == "assert_triple"
        assert captured[0]["subject"] == "urn:test:s"
        assert captured[0]["object"] == "hello world"

        await client.aclose()
        server.stop()

    async def test_compensate_calls_retract_triple(self) -> None:
        captured: list[dict] = []
        server = _fake_ontorag(captured)
        server.start()

        from ontorag_flow.core.action import ActionResult
        from ontorag_flow.ontorag_client.client import OntoragClient

        client = OntoragClient(server.url)
        await client.connect()

        action = AssertTriple(client)
        result = ActionResult(
            action_uri=AssertTriple.uri,
            success=True,
            outputs={
                "subject": "urn:test:s",
                "predicate": "urn:test:p",
                "object": "hello world",
                "graph": None,
                "operation": "assert",
            },
        )
        await action.compensate(result)

        assert len(captured) == 1
        assert captured[0]["tool"] == "retract_triple"
        assert captured[0]["subject"] == "urn:test:s"

        await client.aclose()
        server.stop()

    async def test_retract_compensate_reasserts(self) -> None:
        captured: list[dict] = []
        server = _fake_ontorag(captured)
        server.start()

        from ontorag_flow.core.action import ActionResult
        from ontorag_flow.ontorag_client.client import OntoragClient

        client = OntoragClient(server.url)
        await client.connect()

        action = RetractTriple(client)
        result = ActionResult(
            action_uri=RetractTriple.uri,
            success=True,
            outputs={
                "subject": "urn:test:s",
                "predicate": "urn:test:p",
                "object": "hello world",
                "graph": None,
                "operation": "retract",
            },
        )
        await action.compensate(result)

        assert captured[0]["tool"] == "assert_triple"

        await client.aclose()
        server.stop()

    async def test_graph_param_forwarded(self) -> None:
        captured: list[dict] = []
        server = _fake_ontorag(captured)
        server.start()

        from ontorag_flow.ontorag_client.client import OntoragClient

        client = OntoragClient(server.url)
        await client.connect()

        action = AssertTriple(client)
        params = action.input_schema.model_validate(
            {
                "subject": "urn:test:s",
                "predicate": "urn:test:p",
                "object": "val",
                "graph": "urn:custom:graph",
            }
        )
        await action.execute(params, EMPTY_STATE)

        assert captured[0].get("graph") == "urn:custom:graph"

        await client.aclose()
        server.stop()


# ── Integration 테스트 — 실제 ontorag HTTP MCP ────────────────────────────────


@pytest.mark.integration
async def test_assert_triple_live_roundtrip() -> None:
    """AssertTriple 액션 → ontorag HTTP MCP → Fuseki 저장 → SPARQL 검증."""
    import httpx

    from ontorag_flow.ontorag_client.client import OntoragClient

    ONTORAG_MCP = "http://localhost:8000/mcp/"
    FUSEKI_SPARQL = "http://localhost:3030/ontorag/sparql"
    SUBJECT = "urn:flow:test:assert-triple-live"
    PREDICATE = "http://www.w3.org/2000/01/rdf-schema#label"
    OBJECT = "ontorag-flow AssertTriple integration test"

    client = OntoragClient(ONTORAG_MCP)
    await client.connect()

    # 사용 가능한 툴 목록 확인
    tools = await client.list_tools()
    assert "assert_triple" in tools, f"assert_triple 툴 없음. 사용 가능: {tools}"
    assert "retract_triple" in tools

    action = AssertTriple(client)
    params = action.input_schema.model_validate(
        {
            "subject": SUBJECT,
            "predicate": PREDICATE,
            "object": OBJECT,
        }
    )

    # assert
    result = await action.execute(params, EMPTY_STATE)
    assert result.success is True

    # Fuseki에서 직접 확인
    auth = httpx.BasicAuth("admin", "admin")
    async with httpx.AsyncClient(auth=auth, timeout=10.0) as http:
        ask = f'ASK {{ GRAPH ?g {{ <{SUBJECT}> <{PREDICATE}> "{OBJECT}" . }} }}'
        resp = await http.post(
            FUSEKI_SPARQL,
            data={"query": ask},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        assert resp.json()["boolean"] is True, "Fuseki에 트리플 없음"

    # compensate(retract) → 정리
    await action.compensate(result)

    async with httpx.AsyncClient(auth=auth, timeout=10.0) as http:
        resp2 = await http.post(
            FUSEKI_SPARQL,
            data={"query": ask},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp2.raise_for_status()
        assert resp2.json()["boolean"] is False, "retract 후에도 트리플 남아있음"

    await client.aclose()


@pytest.mark.integration
async def test_retract_triple_live() -> None:
    """RetractTriple 액션 독립 테스트 — assert 후 retract, 결과 검증."""
    import httpx

    from ontorag_flow.ontorag_client.client import OntoragClient

    ONTORAG_MCP = "http://localhost:8000/mcp/"
    FUSEKI_SPARQL = "http://localhost:3030/ontorag/sparql"
    SUBJECT = "urn:flow:test:retract-live"
    PREDICATE = "http://www.w3.org/2000/01/rdf-schema#label"
    OBJECT = "retract test"

    client = OntoragClient(ONTORAG_MCP)
    await client.connect()

    # 먼저 assert
    assert_action = AssertTriple(client)
    p = assert_action.input_schema.model_validate(
        {"subject": SUBJECT, "predicate": PREDICATE, "object": OBJECT}
    )
    await assert_action.execute(p, EMPTY_STATE)

    # retract
    retract_action = RetractTriple(client)
    rp = retract_action.input_schema.model_validate(
        {"subject": SUBJECT, "predicate": PREDICATE, "object": OBJECT}
    )
    result = await retract_action.execute(rp, EMPTY_STATE)
    assert result.success is True
    assert result.outputs["operation"] == "retract"

    # 삭제 확인
    auth = httpx.BasicAuth("admin", "admin")
    async with httpx.AsyncClient(auth=auth, timeout=10.0) as http:
        ask = f'ASK {{ GRAPH ?g {{ <{SUBJECT}> <{PREDICATE}> "{OBJECT}" . }} }}'
        resp = await http.post(
            FUSEKI_SPARQL,
            data={"query": ask},
            headers={"Accept": "application/sparql-results+json"},
        )
        assert resp.json()["boolean"] is False

    await client.aclose()
