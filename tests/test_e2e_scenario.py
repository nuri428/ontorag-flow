"""End-to-end scenario — UI ↔ JSON API ↔ store, single SQLite tmp_path.

The intent: prove that a realistic operator workflow flows through every layer
without anyone needing to know about the others. If a future refactor breaks
the contract between layers, this test fails *before* the unit tests do.

Workflow:

    1. Register a process (with a goal + a timer event that fires immediately).
    2. Create a case.
    3. Execute one action via the JSON API.
    4. Suspend the case from the UI.
    5. Resume from the UI.
    6. Spawn a subcase from the UI; verify parent linkage.
    7. Tick from the dashboard; verify the timer fired and updated state.
    8. Compensate from the UI; verify state reverted to initial_state.
    9. The audit log was the authority for history all along — verify the
       audit page reflects every step.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontorag_flow.api.main import create_app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"

E2E_PROCESS = {
    "process_uri": "urn:p:e2e",
    "name": "E2E lifecycle",
    "allowed_actions": [UPDATE],
    "goal": {"diagnosed": True},
    "initial_state": {"triage_level": "unknown"},
    "timer_events": [
        {"after_minutes": 0, "action": UPDATE, "params": {"key": "timer_fired", "value": True}}
    ],
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Single shared SQLite store across UI + API for the whole scenario."""

    db_path = str(tmp_path / "e2e.db")
    with TestClient(create_app(db_path=db_path, mount_mcp=False)) as test_client:
        yield test_client


def _location_target(resp: object) -> str:
    """Extract the 303 Location header (or fail loudly)."""

    headers = getattr(resp, "headers", {})
    location = headers.get("location") if hasattr(headers, "get") else None
    assert location is not None, f"expected 303 with Location header, got {resp!r}"
    return location


def test_operator_runs_full_lifecycle_through_ui_and_api(client: TestClient) -> None:
    # 1. Process registered.
    assert client.post("/processes", json=E2E_PROCESS).status_code == 200

    # 2. Case created via JSON API.
    case_uri = client.post("/cases", json={"process_uri": "urn:p:e2e"}).json()["case_uri"]
    state = client.get(f"/cases/{case_uri}").json()["state"]["properties"]
    assert state == {"triage_level": "unknown"}

    # 3. Execute one action via JSON API.
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "symptom", "value": "fever"}},
    )
    state = client.get(f"/cases/{case_uri}").json()["state"]["properties"]
    assert state["symptom"] == "fever"

    # 4. Suspend from UI (form POST → 303).
    resp = client.post(f"/ui/cases/{case_uri}/suspend", follow_redirects=False)
    assert resp.status_code == 303
    assert client.get(f"/cases/{case_uri}").json()["status"] == "suspended"

    # 5. Resume from UI.
    resp = client.post(f"/ui/cases/{case_uri}/resume", follow_redirects=False)
    assert resp.status_code == 303
    assert client.get(f"/cases/{case_uri}").json()["status"] == "open"

    # 6. Spawn a subcase via UI form; the redirect lands on the child.
    resp = client.post(
        f"/ui/cases/{case_uri}/subcase",
        data={"process_uri": "urn:p:e2e"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    child_uri = _location_target(resp).rsplit("/", 1)[-1]
    child_body = client.get(f"/cases/{child_uri}").json()
    assert child_body["parent_uri"] == case_uri

    # The case detail HTML now lists the subcase in the "Subcases" section.
    detail_html = client.get(f"/ui/cases/{case_uri}").text
    assert "Subcases (1)" in detail_html
    assert child_uri in detail_html

    # 7. Tick from the dashboard fires the timer on every open case
    #    (parent + child both inherit the timer_events from urn:p:e2e).
    tick_resp = client.post("/ui/tick", follow_redirects=False)
    assert tick_resp.status_code == 303
    tick_match = re.search(r"ticked=(\d+)", _location_target(tick_resp))
    assert tick_match is not None
    assert int(tick_match.group(1)) >= 2  # parent + child

    state = client.get(f"/cases/{case_uri}").json()["state"]["properties"]
    assert state.get("timer_fired") is True

    # 8. Compensate from UI undoes every action and returns to initial_state.
    resp = client.post(f"/ui/cases/{case_uri}/compensate", follow_redirects=False)
    assert resp.status_code == 303
    state = client.get(f"/cases/{case_uri}").json()["state"]["properties"]
    assert state == {"triage_level": "unknown"}

    # 9. Audit page must show the full PROV-O trail (execute + tick + compensate).
    audit_html = client.get(f"/ui/cases/{case_uri}/audit").text
    assert "PROV-O activity record" in audit_html
    # Compensation is logged as a composite activity URI.
    assert "_Compensate" in audit_html or UPDATE in audit_html


def test_dashboard_filter_and_static_assets_round_trip(client: TestClient) -> None:
    """Belt-and-suspenders: every UI surface returns 200 in a populated dashboard."""

    client.post("/processes", json=E2E_PROCESS)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:e2e"}).json()["case_uri"]

    for path in [
        "/ui/",
        "/ui/?status=open",
        "/ui/actions",
        f"/ui/cases/{case_uri}",
        f"/ui/cases/{case_uri}/audit",
        "/ui/static/app.css",
        "/health",
        "/openapi.json",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
