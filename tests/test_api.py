"""API smoke tests via FastAPI TestClient (MCP transport disabled)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ontorag_flow.api.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(mount_mcp=False))


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "ontorag-flow"


def test_list_actions_includes_builtins(client: TestClient) -> None:
    resp = client.get("/actions")
    assert resp.status_code == 200
    uris = {a["uri"] for a in resp.json()["actions"]}

    assert "urn:ontorag-flow:action:UpdateCaseProperty" in uris
    assert "urn:ontorag-flow:action:SetGoal" in uris


def test_action_info_exposes_schema_and_effects(client: TestClient) -> None:
    resp = client.get("/actions")
    actions = {a["uri"]: a for a in resp.json()["actions"]}
    update = actions["urn:ontorag-flow:action:UpdateCaseProperty"]

    assert update["side_effects"] == ["case_state"]
    assert "key" in update["input_schema"]["properties"]
