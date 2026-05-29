"""PROV-O / DCAT export — JSON-LD and Turtle serialization."""

from __future__ import annotations

from rdflib import Graph
from rdflib.namespace import DCAT, PROV, RDF

from ontorag_flow.core.action import ProvOActivity, utcnow
from ontorag_flow.core.provenance import (
    activities_to_jsonld,
    activities_to_turtle,
    render,
)


def _sample_activities() -> list[ProvOActivity]:
    first = ProvOActivity(
        activity_uri="urn:ontorag-flow:activity:1",
        action_uri="urn:test:action:update",
        case_uri="urn:test:case:1",
        agent="urn:test:agent",
        started_at=utcnow(),
        ended_at=utcnow(),
        used={"key": "triage_level", "value": "assessed"},
        generated={"state_changes": {"triage_level": "assessed"}},
    )
    second = ProvOActivity(
        activity_uri="urn:ontorag-flow:activity:2",
        action_uri="urn:test:action:diagnose",
        case_uri="urn:test:case:1",
        agent="urn:test:agent",
        started_at=utcnow(),
        ended_at=utcnow(),
        used={"key": "diagnosed", "value": True},
        generated={"state_changes": {"diagnosed": True}},
        informed_by="urn:ontorag-flow:activity:1",
    )
    return [first, second]


def test_jsonld_has_graph_and_prov_fields() -> None:
    doc = activities_to_jsonld(_sample_activities())

    assert "@context" in doc
    assert doc["@context"]["prov"] == "http://www.w3.org/ns/prov#"
    assert doc["@context"]["dcat"] == "http://www.w3.org/ns/dcat#"
    assert "@graph" in doc

    activities = [n for n in doc["@graph"] if n["@type"] == "prov:Activity"]
    assert len(activities) == 2
    first = next(n for n in activities if n["@id"] == "urn:ontorag-flow:activity:1")
    assert first["prov:wasAssociatedWith"] == "urn:test:agent"
    assert "prov:startedAtTime" in first
    assert "prov:endedAtTime" in first
    assert first["ontoragflow:action"] == "urn:test:action:update"

    second = next(n for n in activities if n["@id"] == "urn:ontorag-flow:activity:2")
    assert second["prov:wasInformedBy"] == "urn:ontorag-flow:activity:1"


def test_jsonld_promotes_inputs_outputs_to_dcat_datasets() -> None:
    doc = activities_to_jsonld(_sample_activities())

    datasets = [n for n in doc["@graph"] if n["@type"] == "dcat:Dataset"]
    # Two activities, each with non-empty used + generated => 4 datasets.
    assert len(datasets) == 4
    assert all("dcat:distribution" in d for d in datasets)

    first = next(
        n
        for n in doc["@graph"]
        if n.get("@type") == "prov:Activity"
        and n["@id"] == "urn:ontorag-flow:activity:1"
    )
    # The activity references its datasets by @id, not inline mappings.
    assert first["prov:used"] == {"@id": "urn:ontorag-flow:activity:1#used"}
    assert first["prov:generated"] == {"@id": "urn:ontorag-flow:activity:1#generated"}


def test_turtle_is_parseable_with_expected_triples() -> None:
    activities = _sample_activities()
    turtle = activities_to_turtle(activities)

    assert "prov:Activity" in turtle

    graph = Graph()
    graph.parse(data=turtle, format="turtle")

    activity_nodes = list(graph.subjects(RDF.type, PROV.Activity))
    assert len(activity_nodes) == 2
    dataset_nodes = list(graph.subjects(RDF.type, DCAT.Dataset))
    assert len(dataset_nodes) == 4
    # Causal chain preserved.
    informed = list(graph.objects(predicate=PROV.wasInformedBy))
    assert len(informed) == 1


def test_empty_list_produces_valid_documents() -> None:
    assert activities_to_jsonld([]) == {
        "@context": {
            "prov": "http://www.w3.org/ns/prov#",
            "dcat": "http://www.w3.org/ns/dcat#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "ontoragflow": "urn:ontorag-flow:",
        },
        "@graph": [],
    }

    turtle = activities_to_turtle([])
    graph = Graph()
    graph.parse(data=turtle, format="turtle")  # must not raise
    assert len(list(graph.triples((None, None, None)))) == 0


def test_tolerates_none_timestamps_and_links() -> None:
    bare = ProvOActivity(action_uri="urn:test:bare")
    doc = activities_to_jsonld([bare])
    node = doc["@graph"][0]
    assert node["@type"] == "prov:Activity"
    assert "prov:startedAtTime" not in node
    assert "prov:wasInformedBy" not in node

    turtle = activities_to_turtle([bare])
    Graph().parse(data=turtle, format="turtle")  # must not raise


def test_render_dispatches_by_format() -> None:
    activities = _sample_activities()
    jsonld = render(activities, "jsonld")
    assert jsonld.lstrip().startswith("{")
    assert "prov:Activity" in jsonld

    ttl = render(activities, "ttl")
    Graph().parse(data=ttl, format="turtle")  # must not raise
