"""API audit-trail endpoint over a real (temp-file) SQLite store."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontorag_flow.api.main import create_app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"

PROCESS = {
    "process_uri": "urn:p:triage",
    "name": "Triage",
    "allowed_actions": [UPDATE],
    "goal": {"diagnosed": True},
    "initial_state": {"triage_level": "unknown"},
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(db_path=str(tmp_path / "t.db"), mount_mcp=False)
    with TestClient(app) as test_client:
        yield test_client


def _seed_case_with_action(client: TestClient) -> str:
    assert client.post("/processes", json=PROCESS).status_code == 200
    created = client.post("/cases", json={"process_uri": "urn:p:triage"})
    assert created.status_code == 200
    case_uri = created.json()["case_uri"]

    executed = client.post(
        f"/cases/{case_uri}/execute",
        json={
            "action_uri": UPDATE,
            "params": {"key": "triage_level", "value": "assessed"},
        },
    )
    assert executed.status_code == 200
    return case_uri


def test_get_audit_trail_returns_recorded_activity(client: TestClient) -> None:
    case_uri = _seed_case_with_action(client)

    resp = client.get(f"/cases/{case_uri}/audit")
    assert resp.status_code == 200
    activities = resp.json()
    assert len(activities) >= 1

    activity = activities[0]
    assert activity["case_uri"] == case_uri
    assert activity["action_uri"] == UPDATE
    assert activity["agent"] is not None
    assert activity["started_at"] is not None


def test_get_audit_trail_records_each_execution(client: TestClient) -> None:
    case_uri = _seed_case_with_action(client)
    # A second execution should append another activity to the trail.
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "stage", "value": "review"}},
    )

    resp = client.get(f"/cases/{case_uri}/audit")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_audit_trail_unknown_case_is_empty(client: TestClient) -> None:
    resp = client.get("/cases/urn:no:such:case/audit")
    assert resp.status_code == 200
    assert resp.json() == []
