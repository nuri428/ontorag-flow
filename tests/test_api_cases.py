"""End-to-end API flow over a real (temp-file) SQLite store."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontorag_flow.api.main import create_app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"
SET_GOAL = "urn:ontorag-flow:action:SetGoal"

PROCESS = {
    "process_uri": "urn:p:triage",
    "name": "Triage",
    "allowed_actions": [UPDATE],
    "goal": {"diagnosed": True},
    "initial_state": {"triage_level": "unknown"},
    "rules": [
        {
            "name": "assess unknown",
            "when": {"triage_level": "unknown"},
            "then": {"action": UPDATE, "params": {"key": "triage_level", "value": "assessed"}},
            "confidence": 0.7,
        }
    ],
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(db_path=str(tmp_path / "test.db"), mount_mcp=False)
    with TestClient(app) as test_client:
        yield test_client


def test_full_case_flow_closes_on_goal(client: TestClient) -> None:
    assert client.post("/processes", json=PROCESS).status_code == 200

    created = client.post(
        "/cases", json={"process_uri": "urn:p:triage", "initial_state": {"age": 40}}
    )
    assert created.status_code == 200
    case_uri = created.json()["case_uri"]
    assert created.json()["state"]["properties"] == {"triage_level": "unknown", "age": 40}

    executed = client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "diagnosed", "value": True}},
    )
    assert executed.status_code == 200
    assert executed.json()["case"]["status"] == "closed"
    assert executed.json()["result"]["success"] is True

    fetched = client.get(f"/cases/{case_uri}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "closed"

    found = client.post("/cases/find", json={"status": "closed"})
    assert len(found.json()) == 1


def test_create_case_unknown_process_404(client: TestClient) -> None:
    resp = client.post("/cases", json={"process_uri": "urn:p:none"})
    assert resp.status_code == 404


def test_propose_next_action_ranks_proposals(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:triage"}).json()["case_uri"]

    resp = client.post(f"/cases/{case_uri}/propose")
    assert resp.status_code == 200
    proposals = resp.json()
    assert len(proposals) == 1
    assert proposals[0]["action_uri"] == UPDATE
    assert proposals[0]["proposed_by"] == "RuleEngine"


def test_propose_llm_engine_unavailable_409(client: TestClient) -> None:
    # The default app configures no LLM client, so a process that asks for the
    # LLM engine cannot propose — the resolver raises and the route maps it to 409.
    process = {**PROCESS, "process_uri": "urn:p:llm", "engine": "llm"}
    client.post("/processes", json=process)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:llm"}).json()["case_uri"]

    resp = client.post(f"/cases/{case_uri}/propose")
    assert resp.status_code == 409


def test_execute_disallowed_action_409(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:triage"}).json()["case_uri"]

    resp = client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": SET_GOAL, "params": {"predicate": "x"}},
    )
    assert resp.status_code == 409
