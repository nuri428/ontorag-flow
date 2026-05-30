"""v0.7 API: compensate / suspend / resume / fork end-to-end."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontorag_flow.api.main import create_app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"

PROCESS = {
    "process_uri": "urn:p:lifecycle",
    "name": "Lifecycle",
    "allowed_actions": [UPDATE],
    "goal": {"diagnosed": True},
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), mount_mcp=False)) as test_client:
        yield test_client


def _create_case(client: TestClient) -> str:
    client.post("/processes", json=PROCESS)
    return client.post("/cases", json={"process_uri": "urn:p:lifecycle"}).json()["case_uri"]


def test_suspend_resume_endpoints(client: TestClient) -> None:
    case_uri = _create_case(client)

    suspended = client.post(f"/cases/{case_uri}/suspend")
    assert suspended.status_code == 200 and suspended.json()["status"] == "suspended"

    # invalid: suspending again
    assert client.post(f"/cases/{case_uri}/suspend").status_code == 409

    resumed = client.post(f"/cases/{case_uri}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "open"


def test_compensate_endpoint_undoes_actions(client: TestClient) -> None:
    case_uri = _create_case(client)
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "a", "value": 1}},
    )

    resp = client.post(f"/cases/{case_uri}/compensate", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "open"
    assert body["state"]["properties"] == {}


def test_subcase_endpoint_links_child_to_parent(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    parent_uri = client.post("/cases", json={"process_uri": "urn:p:lifecycle"}).json()["case_uri"]

    resp = client.post(f"/cases/{parent_uri}/subcase", json={"process_uri": "urn:p:lifecycle"})
    assert resp.status_code == 200
    child = resp.json()
    assert child["parent_uri"] == parent_uri
    assert child["case_uri"] != parent_uri


def test_tick_endpoint_fires_due_timers(client: TestClient) -> None:
    proc = {
        **PROCESS,
        "process_uri": "urn:p:lifecycle-timer",
        "timer_events": [
            {"after_minutes": 0, "action": UPDATE, "params": {"key": "ticked", "value": True}}
        ],
    }
    client.post("/processes", json=proc)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:lifecycle-timer"}).json()[
        "case_uri"
    ]

    resp = client.post("/cases/tick")
    assert resp.status_code == 200
    assert resp.json() == [f"{case_uri}#0"]

    state = client.get(f"/cases/{case_uri}").json()["state"]["properties"]
    assert state.get("ticked") is True


def test_fork_endpoint_creates_new_case(client: TestClient) -> None:
    source = _create_case(client)
    client.post(
        f"/cases/{source}/execute",
        json={"action_uri": UPDATE, "params": {"key": "a", "value": 1}},
    )

    resp = client.post(f"/cases/{source}/fork", json={})
    assert resp.status_code == 200
    forked = resp.json()
    assert forked["case_uri"] != source
    assert forked["state"]["properties"] == {"a": 1}
    assert len(forked["history"]) == 1
