"""Audit store and PROV-O serialization."""

from __future__ import annotations

from ontorag_flow.core.action import ProvOActivity, utcnow
from ontorag_flow.core.audit import InMemoryAuditStore


async def test_record_and_retrieve() -> None:
    store = InMemoryAuditStore()
    activity = ProvOActivity(action_uri="urn:test:a", agent="urn:test:agent")

    await store.record(activity)

    assert await store.get(activity.activity_uri) is activity
    assert await store.get("missing") is None
    assert store.last is activity
    assert len(await store.list_all()) == 1


def test_prov_jsonld_contains_core_fields() -> None:
    activity = ProvOActivity(
        action_uri="urn:test:a",
        agent="urn:test:agent",
        started_at=utcnow(),
        ended_at=utcnow(),
        used={"key": "x"},
        generated={"state_changes": {"x": 1}},
        informed_by="urn:test:prev",
    )

    node = activity.to_jsonld()

    assert node["@type"] == "prov:Activity"
    assert node["prov:wasAssociatedWith"] == "urn:test:agent"
    assert node["prov:wasInformedBy"] == "urn:test:prev"
    assert "prov:startedAtTime" in node
    assert node["prov:used"] == {"key": "x"}
