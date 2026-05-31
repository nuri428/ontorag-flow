"""``POST /audit/prune`` — retention endpoint smoke test."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontorag_flow.api.main import create_app

UPDATE = "urn:ontorag-flow:action:UpdateCaseProperty"

PROCESS = {
    "process_uri": "urn:p:prune-api",
    "name": "Prune API",
    "allowed_actions": [UPDATE],
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_path=str(tmp_path / "prune.db"), mount_mcp=False)) as c:
        yield c


def test_prune_requires_window(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    # Neither older_than_days nor AUDIT_RETENTION_DAYS supplied → 422.
    response = client.post("/audit/prune", json={})
    assert response.status_code == 422


def test_prune_dry_run_returns_empty_when_no_old_cases(client: TestClient) -> None:
    client.post("/processes", json=PROCESS)
    client.post("/cases", json={"process_uri": "urn:p:prune-api"})

    response = client.post("/audit/prune", json={"older_than_days": 30, "dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert body["older_than_days"] == 30
    assert body["dry_run"] is True
    # The case is OPEN, so it can never be pruned regardless of age.
    assert body["removed"] == []
