"""``GET /audit/aggregate`` — cross-case audit bucket counts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontorag_flow.api.main import create_app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"

PROCESS_A = {
    "process_uri": "urn:p:agg-a",
    "name": "Aggregate A",
    "allowed_actions": [UPDATE],
}
PROCESS_B = {
    "process_uri": "urn:p:agg-b",
    "name": "Aggregate B",
    "allowed_actions": [UPDATE],
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_path=str(tmp_path / "agg.db"), mount_mcp=False)) as c:
        yield c


def _seed(client: TestClient) -> tuple[str, str]:
    """Create one case in PROCESS_A with 3 activities, one in PROCESS_B with 1."""

    client.post("/processes", json=PROCESS_A)
    client.post("/processes", json=PROCESS_B)
    a = client.post("/cases", json={"process_uri": "urn:p:agg-a"}).json()["case_uri"]
    b = client.post("/cases", json={"process_uri": "urn:p:agg-b"}).json()["case_uri"]
    for value in (1, 2, 3):
        client.post(
            f"/cases/{a}/execute",
            json={"action_uri": UPDATE, "params": {"key": "n", "value": value}},
        )
    client.post(
        f"/cases/{b}/execute",
        json={"action_uri": UPDATE, "params": {"key": "n", "value": 99}},
    )
    return a, b


def test_aggregate_by_action_uri(client: TestClient) -> None:
    _seed(client)
    rows = client.get("/audit/aggregate?group_by=action_uri").json()
    assert rows == [{"key": UPDATE, "count": 4}]


def test_aggregate_by_case_uri_orders_by_count(client: TestClient) -> None:
    a, b = _seed(client)
    rows = client.get("/audit/aggregate?group_by=case_uri").json()
    # case a fired 3, case b fired 1 — most-common first.
    assert rows[0] == {"key": a, "count": 3}
    assert rows[1] == {"key": b, "count": 1}


def test_aggregate_by_status_counts_completed(client: TestClient) -> None:
    _seed(client)
    rows = client.get("/audit/aggregate?group_by=status").json()
    statuses = {row["key"]: row["count"] for row in rows}
    # CASE_STATE-only actions write a single completed row each.
    assert statuses.get("completed", 0) == 4


def test_aggregate_filtered_by_process(client: TestClient) -> None:
    _seed(client)
    rows = client.get("/audit/aggregate?group_by=case_uri&process_uri=urn:p:agg-a").json()
    # Only the 3-activity case from process A counts; process B's case is excluded.
    assert len(rows) == 1
    assert rows[0]["count"] == 3


def test_aggregate_rejects_unknown_group_by(client: TestClient) -> None:
    resp = client.get("/audit/aggregate?group_by=bogus")
    assert resp.status_code == 422  # FastAPI Literal validation


def test_aggregate_empty_store_returns_empty_list(client: TestClient) -> None:
    rows = client.get("/audit/aggregate").json()
    assert rows == []
