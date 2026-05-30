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


# --- Dashboard global tick action -----------------------------------------


def test_dashboard_tick_renders_button_and_count(client: TestClient) -> None:
    # Process with a timer that fires immediately.
    proc = {
        **PROCESS,
        "process_uri": "urn:p:ui-timer",
        "timer_events": [
            {"after_minutes": 0, "action": UPDATE, "params": {"key": "fired", "value": True}}
        ],
    }
    client.post("/processes", json=proc)
    client.post("/cases", json={"process_uri": "urn:p:ui-timer"})

    # The Tick button is on the dashboard.
    body = client.get("/ui/").text
    assert 'action="/ui/tick"' in body
    assert "Tick all timers" in body

    resp = client.post("/ui/tick", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/?ticked=1"

    # The redirect target renders the "fired N timer events" callout.
    after = client.get("/ui/?ticked=1").text
    assert "Tick fired 1 timer event(s)" in after


def test_dashboard_tick_with_no_timers_returns_zero(client: TestClient) -> None:
    resp = client.post("/ui/tick", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/?ticked=0"


# --- Counterfactual UI (audit row → form → result/error callout) ---------


def _executed_activity_uri(client: TestClient) -> tuple[str, str]:
    """Set up a case + one execute, returning (case_uri, activity_uri)."""

    import re

    case_uri = _open_case(client)
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "x", "value": 1}},
    )
    audit_body = client.get(f"/ui/cases/{case_uri}/audit").text
    match = re.search(r"urn:ontorag-flow:activity:[a-zA-Z0-9-]+", audit_body)
    assert match, "no activity URI found in audit HTML"
    return case_uri, match.group(0)


def test_audit_row_shows_counterfactual_link(client: TestClient) -> None:
    case_uri = _open_case(client)
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "x", "value": 1}},
    )
    body = client.get(f"/ui/cases/{case_uri}/audit").text
    assert f"/ui/cases/{case_uri}/counterfactual?swap=" in body
    assert ">Counterfactual</a>" in body


def test_counterfactual_form_renders_with_actions(client: TestClient) -> None:
    case_uri, activity_uri = _executed_activity_uri(client)
    resp = client.get(f"/ui/cases/{case_uri}/counterfactual?swap={activity_uri}")
    assert resp.status_code == 200
    body = resp.text
    assert "Counterfactual replay" in body
    assert activity_uri in body
    # The action dropdown is populated from the registry.
    assert UPDATE in body
    assert 'name="action_uri"' in body


def test_counterfactual_form_404_for_unknown_activity(client: TestClient) -> None:
    case_uri = _open_case(client)
    resp = client.get(f"/ui/cases/{case_uri}/counterfactual?swap=urn:no:such:activity")
    assert resp.status_code == 404


def test_counterfactual_submit_surfaces_engine_error_inline(client: TestClient) -> None:
    # PROCESS uses RuleEngine — no counterfactual_replay → CounterfactualError
    # surfaces on the same page as an error callout (no redirect, no 500).
    case_uri, activity_uri = _executed_activity_uri(client)
    resp = client.post(
        f"/ui/cases/{case_uri}/counterfactual",
        data={
            "swap_activity_uri": activity_uri,
            "action_uri": UPDATE,
            "params_json": '{"key":"y","value":2}',
        },
    )
    assert resp.status_code == 200
    body = resp.text
    assert "CounterfactualError" in body or "Engine unavailable" in body
    # No Result section rendered when the engine errored.
    assert "<h2>Result</h2>" not in body


def test_counterfactual_invalid_json_surfaces_validation_error(client: TestClient) -> None:
    case_uri, activity_uri = _executed_activity_uri(client)
    resp = client.post(
        f"/ui/cases/{case_uri}/counterfactual",
        data={
            "swap_activity_uri": activity_uri,
            "action_uri": UPDATE,
            "params_json": "{not json",
        },
    )
    assert resp.status_code == 200
    assert "Invalid params JSON" in resp.text


def test_counterfactual_non_dict_params_rejected(client: TestClient) -> None:
    case_uri, activity_uri = _executed_activity_uri(client)
    resp = client.post(
        f"/ui/cases/{case_uri}/counterfactual",
        data={
            "swap_activity_uri": activity_uri,
            "action_uri": UPDATE,
            "params_json": "[1, 2, 3]",
        },
    )
    assert resp.status_code == 200
    assert "params must be a JSON object" in resp.text


def test_explain_page_renders_rule_engine_trace(client: TestClient) -> None:
    """RuleEngine implements explain(); the trace shows rules_fired."""

    client.post("/processes", json=PROCESS)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:ui"}).json()["case_uri"]

    resp = client.get(f"/ui/cases/{case_uri}/explain")
    assert resp.status_code == 200
    body = resp.text
    assert "Decision engine inspector" in body
    assert "RuleEngine" in body
    # PROCESS has one rule "assess unknown" that fires for initial_state.
    assert "assess unknown" in body
    assert "rules_fired" in body


def test_explain_page_link_appears_on_case_detail(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:ui"}).json()["case_uri"]
    body = client.get(f"/ui/cases/{case_uri}").text
    assert f"/ui/cases/{case_uri}/explain" in body


def test_explain_page_404_for_unknown_case(client: TestClient) -> None:
    assert client.get("/ui/cases/urn:nope/explain").status_code == 404


def test_explain_page_surfaces_engine_unavailable_inline(client: TestClient) -> None:
    """LLM engine without an LLM client → 'Decision engine unavailable' callout."""

    proc = {**PROCESS, "process_uri": "urn:p:explain-llm", "engine": "llm"}
    client.post("/processes", json=proc)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:explain-llm"}).json()["case_uri"]

    resp = client.get(f"/ui/cases/{case_uri}/explain")
    assert resp.status_code == 200
    assert "Decision engine unavailable" in resp.text


def test_explain_page_renders_rule_engine_structured_cards(client: TestClient) -> None:
    """The trace section now uses engine-specific cards, not just JSON."""

    proc = {
        **PROCESS,
        "process_uri": "urn:p:explain-rule",
        "rules": [
            {
                "name": "fires now",
                "when": {"triage_level": "unknown"},
                "then": {"action": UPDATE, "params": {"key": "k", "value": "v"}},
                "confidence": 0.7,
            },
            {
                "name": "never fires",
                "when": {"triage_level": "critical"},
                "then": {"action": UPDATE},
                "confidence": 0.9,
            },
        ],
    }
    client.post("/processes", json=proc)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:explain-rule"}).json()["case_uri"]

    body = client.get(f"/ui/cases/{case_uri}/explain").text
    # Structured cards, not raw JSON:
    assert "Rules fired" in body
    assert "fires now" in body
    assert "Rules unmatched" in body
    assert "never fires" in body
    # Raw JSON still available in a fold:
    assert "<summary" in body
    assert "Raw trace (JSON)" in body


def test_counterfactual_submit_404_for_unknown_case(client: TestClient) -> None:
    resp = client.post(
        "/ui/cases/urn:no:such:case/counterfactual",
        data={"swap_activity_uri": "urn:any", "action_uri": UPDATE, "params_json": "{}"},
    )
    assert resp.status_code == 404


# --- mutating UI error paths (small extras for coverage) -----------------


def test_ui_audit_404_for_unknown_case(client: TestClient) -> None:
    assert client.get("/ui/cases/urn:nope/audit").status_code == 404


def test_ui_processes_page_lists_loaded_processes(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    body = client.get("/ui/processes").text
    assert "Processes" in body
    assert PROCESS["process_uri"] in body
    assert PROCESS["name"] in body


def test_ui_processes_page_empty_state(client: TestClient) -> None:
    body = client.get("/ui/processes").text
    assert "No processes loaded" in body


def test_ui_process_detail_shows_status_and_action_stats(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    case_uri = client.post("/cases", json={"process_uri": "urn:p:ui"}).json()["case_uri"]
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "a", "value": 1}},
    )
    body = client.get(f"/ui/processes/{PROCESS['process_uri']}").text
    assert "process inspector" in body.lower() or "process &lt;" in body or "Process " in body
    # status mix: 1 open
    assert "open" in body
    # top fired actions table includes UPDATE
    assert UPDATE in body


def test_ui_process_detail_404_for_unknown(client: TestClient) -> None:
    assert client.get("/ui/processes/urn:nope").status_code == 404


def test_ui_process_diagram_renders_svg_with_action_nodes(client: TestClient) -> None:
    proc = {
        "process_uri": "urn:p:diagram",
        "name": "Diagram",
        "allowed_actions": [UPDATE, "urn:a:order_lab"],
        "constraints": {
            "requires": {"urn:a:order_lab": [UPDATE]},
            "mutex": [[UPDATE, "urn:a:order_lab"]],
            "at_most_once": [UPDATE],
        },
        "timer_events": [{"after_minutes": 30, "action": UPDATE, "params": {"key": "k"}}],
    }
    client.post("/processes", json=proc)
    body = client.get("/ui/processes/urn:p:diagram/diagram").text
    # SVG markup present
    assert "<svg" in body
    # constraint labels surface in the SVG text content
    assert "requires" in body
    assert "mutex" in body
    # timer event glyph
    assert "⏱" in body
    # at-most-once badge
    assert "×1" in body


def test_ui_process_diagram_404_for_unknown(client: TestClient) -> None:
    assert client.get("/ui/processes/urn:nope/diagram").status_code == 404


def test_ui_subcase_bad_process_redirects_with_error(client: TestClient) -> None:
    parent_uri = _open_case(client)
    resp = client.post(
        f"/ui/cases/{parent_uri}/subcase",
        data={"process_uri": "urn:no:such:process"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # The 303 lands back at the parent with an ?error= query.
    assert resp.headers["location"].startswith(f"/ui/cases/{parent_uri}?error=")


def test_ui_execute_top_on_closed_case_redirects_with_error(client: TestClient) -> None:
    # PROCESS goal {diagnosed: true} closes the case after that key is set.
    case_uri = _open_case(client)
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "diagnosed", "value": True}},
    )
    # Now closed — execute-top should fail gracefully (CaseClosedError surfaces).
    resp = client.post(f"/ui/cases/{case_uri}/execute-top", follow_redirects=False)
    assert resp.status_code == 303
    # And the redirect target shows the error.
    target = resp.headers["location"]
    assert target.startswith(f"/ui/cases/{case_uri}")
    assert "error=" in target


@pytest.mark.parametrize("path", ["suspend", "resume", "compensate"])
def test_ui_mutating_routes_on_unknown_case_redirect_with_error(
    client: TestClient, path: str
) -> None:
    """Unknown case → CaseNotFoundError → 303 redirect back to a non-existent case detail."""

    resp = client.post(f"/ui/cases/urn:no:such:case/{path}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/ui/cases/urn:no:such:case?error=")


def test_ui_execute_top_on_unknown_case_redirects_with_error(client: TestClient) -> None:
    resp = client.post("/ui/cases/urn:no:such:case/execute-top", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_ui_compensate_on_closed_case_still_works(client: TestClient) -> None:
    """Compensate should reverse history even on a closed case."""

    case_uri = _open_case(client)
    client.post(
        f"/cases/{case_uri}/execute",
        json={"action_uri": UPDATE, "params": {"key": "diagnosed", "value": True}},
    )
    resp = client.post(f"/ui/cases/{case_uri}/compensate", follow_redirects=False)
    assert resp.status_code == 303
    body = client.get(f"/cases/{case_uri}").json()
    assert body["state"]["properties"] == {"triage_level": "unknown"}
