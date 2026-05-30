"""Read-only Web UI — server-rendered pages and static stylesheet."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontorag_flow.api.main import create_app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"

PROCESS = {
    "process_uri": "urn:p:ui",
    "name": "UI Test",
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
    with TestClient(create_app(db_path=str(tmp_path / "ui.db"), mount_mcp=False)) as test_client:
        yield test_client


def test_static_css_served(client: TestClient) -> None:
    resp = client.get("/ui/static/app.css")
    assert resp.status_code == 200
    assert "ontorag-flow Web UI" in resp.text


def test_dashboard_renders(client: TestClient) -> None:
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "<h1>Cases</h1>" in resp.text
    assert "No cases yet" in resp.text  # empty state callout


def test_actions_page_lists_builtins(client: TestClient) -> None:
    resp = client.get("/ui/actions")
    assert resp.status_code == 200
    assert UPDATE in resp.text
    assert "case_state" in resp.text  # side-effect badge text


def test_case_detail_renders_with_proposals(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:ui"}).json()["case_uri"]

    resp = client.get(f"/ui/cases/{case_uri}")
    assert resp.status_code == 200
    body = resp.text
    assert case_uri in body
    # the rule engine proposed the "assess unknown" rule → its rationale appears
    assert "assess unknown" in body
    assert "RuleEngine" in body


def test_case_detail_shows_friendly_message_when_engine_unavailable(
    client: TestClient,
) -> None:
    proc = {**PROCESS, "process_uri": "urn:p:llm-ui", "engine": "llm"}
    client.post("/processes", json=proc)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:llm-ui"}).json()["case_uri"]

    resp = client.get(f"/ui/cases/{case_uri}")
    assert resp.status_code == 200
    assert "Decision engine unavailable" in resp.text


def test_case_audit_renders_after_execute(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:ui"}).json()["case_uri"]
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "x", "value": 1}},
    )

    resp = client.get(f"/ui/cases/{case_uri}/audit")
    assert resp.status_code == 200
    body = resp.text
    assert "Audit trail" in body
    assert UPDATE in body
    assert "urn:test:agent" not in body  # default agent_id from settings, not test
    # the activity row should at least include the case_uri
    assert case_uri in body


def test_dashboard_status_filter(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    client.post("/cases", json={"process_uri": "urn:p:ui"})

    resp = client.get("/ui/?status=open")
    assert resp.status_code == 200
    assert "urn:ontorag-flow:case:" in resp.text

    # invalid status returns 400 (not 500)
    assert client.get("/ui/?status=bogus").status_code == 400


def test_case_detail_404_for_unknown(client: TestClient) -> None:
    assert client.get("/ui/cases/urn:nope").status_code == 404


# --- mutating UI form POSTs (303 redirect pattern, JS-free) ---------------


def _open_case(client: TestClient) -> str:
    client.post("/processes", json=PROCESS)
    return client.post("/cases", json={"process_uri": "urn:p:ui"}).json()["case_uri"]


def test_ui_suspend_then_resume_round_trip(client: TestClient) -> None:
    case_uri = _open_case(client)

    suspended = client.post(f"/ui/cases/{case_uri}/suspend", follow_redirects=False)
    assert suspended.status_code == 303
    assert suspended.headers["location"] == f"/ui/cases/{case_uri}"
    assert client.get(f"/cases/{case_uri}").json()["status"] == "suspended"

    resumed = client.post(f"/ui/cases/{case_uri}/resume", follow_redirects=False)
    assert resumed.status_code == 303
    assert client.get(f"/cases/{case_uri}").json()["status"] == "open"


def test_ui_invalid_transition_redirects_with_error_query(client: TestClient) -> None:
    case_uri = _open_case(client)
    # Resuming an open case is invalid.
    resp = client.post(f"/ui/cases/{case_uri}/resume", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_ui_compensate_undoes_actions(client: TestClient) -> None:
    case_uri = _open_case(client)
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "a", "value": 1}},
    )

    resp = client.post(f"/ui/cases/{case_uri}/compensate", follow_redirects=False)
    assert resp.status_code == 303
    body = client.get(f"/cases/{case_uri}").json()
    assert body["status"] == "open"
    # The UPDATE we executed is undone; the case reverts to PROCESS.initial_state.
    assert body["state"]["properties"] == {"triage_level": "unknown"}
    assert "a" not in body["state"]["properties"]


def test_ui_execute_top_runs_first_proposal(client: TestClient) -> None:
    case_uri = _open_case(client)

    resp = client.post(f"/ui/cases/{case_uri}/execute-top", follow_redirects=False)
    assert resp.status_code == 303
    state = client.get(f"/cases/{case_uri}").json()["state"]["properties"]
    # The PROCESS fixture's rule recommends triage_level=assessed for fresh cases.
    assert state.get("triage_level") == "assessed"


def test_ui_subcase_form_redirects_to_child(client: TestClient) -> None:
    parent_uri = _open_case(client)

    resp = client.post(
        f"/ui/cases/{parent_uri}/subcase",
        data={"process_uri": "urn:p:ui"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    child_uri = resp.headers["location"].rsplit("/", 1)[-1]
    assert child_uri != parent_uri
    assert client.get(f"/cases/{child_uri}").json()["parent_uri"] == parent_uri


def test_case_detail_renders_action_buttons_per_status(client: TestClient) -> None:
    case_uri = _open_case(client)

    body = client.get(f"/ui/cases/{case_uri}").text
    assert 'action="/ui/cases/' in body and "/suspend" in body
    assert "Execute top proposal" in body
    # No "Resume" button while the case is open.
    assert "/resume" not in body

    client.post(f"/ui/cases/{case_uri}/suspend")
    suspended_body = client.get(f"/ui/cases/{case_uri}").text
    assert "/resume" in suspended_body
    # No suspend button while suspended.
    assert ">Suspend</button>" not in suspended_body
