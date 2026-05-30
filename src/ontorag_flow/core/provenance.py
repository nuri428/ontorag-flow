"""PROV-O export — render audit activities as JSON-LD or Turtle.

The audit trail records a :class:`~ontorag_flow.core.action.ProvOActivity` per
executed action. v0.6 turns that trail into an interchange-grade provenance
document so external tools can answer "who changed what, when, why".

These are *pure* functions: they take a list of activities and return a
serialized representation with no I/O, so callers (the REST layer, the CLI)
control fetching and output. They tolerate activities with ``None`` timestamps,
agents, or causal links.

DCAT modelling choice
---------------------
Each activity's inputs (``prov:used``) and outputs (``prov:generated``) are
promoted to standalone ``dcat:Dataset`` nodes in the graph. The activity then
references those datasets by ``@id`` (``prov:used`` / ``prov:generated``),
rather than inlining the raw mappings. This keeps datasets addressable and
re-usable across activities while staying a modest, correct representation: the
key/value payload of each dataset is attached as a ``dcat:distribution`` literal
(a JSON string) so no information is lost. Activities with empty inputs/outputs
produce no dataset node.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from rdflib import Graph, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.namespace import DCAT, PROV, RDF, XSD

from ontorag_flow.core.action import ProvOActivity

ExportFormat = Literal["jsonld", "ttl"]
"""Supported provenance export formats: JSON-LD or Turtle."""

_ONTORAGFLOW = "urn:ontorag-flow:"
_CONTEXT: dict[str, str] = {
    "prov": "http://www.w3.org/ns/prov#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "ontoragflow": _ONTORAGFLOW,
}


def _dataset_uri(activity_uri: str, role: str) -> str:
    """Deterministic URI for the input/output dataset of an activity."""

    return f"{activity_uri}#{role}"


def _dataset_node(activity_uri: str, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a ``dcat:Dataset`` JSON-LD node for an input/output payload."""

    return {
        "@id": _dataset_uri(activity_uri, role),
        "@type": "dcat:Dataset",
        "ontoragflow:role": role,
        "dcat:distribution": json.dumps(payload, default=str, sort_keys=True),
    }


def activities_to_jsonld(activities: list[ProvOActivity]) -> dict[str, Any]:
    """Render activities as a single JSON-LD provenance document.

    Produces ``{"@context": {...}, "@graph": [...]}`` where the graph holds one
    ``prov:Activity`` node per activity plus the ``dcat:Dataset`` nodes for any
    non-empty inputs/outputs. The activity links to its datasets by ``@id`` via
    ``prov:used`` / ``prov:generated``.

    Args:
        activities: The activities to export (may be empty).

    Returns:
        A JSON-LD document as a plain ``dict`` (JSON-serializable).
    """

    graph: list[dict[str, Any]] = []
    for activity in activities:
        node = activity.to_jsonld()
        node.pop("@context", None)

        if activity.used:
            used_uri = _dataset_uri(activity.activity_uri, "used")
            node["prov:used"] = {"@id": used_uri}
            graph.append(_dataset_node(activity.activity_uri, "used", activity.used))
        if activity.generated:
            gen_uri = _dataset_uri(activity.activity_uri, "generated")
            node["prov:generated"] = {"@id": gen_uri}
            graph.append(_dataset_node(activity.activity_uri, "generated", activity.generated))

        graph.append(node)

    return {"@context": dict(_CONTEXT), "@graph": graph}


def _add_activity_triples(graph: Graph, activity: ProvOActivity) -> None:
    """Add one activity (and its datasets) to an rdflib graph."""

    subject = URIRef(activity.activity_uri)
    graph.add((subject, RDF.type, PROV.Activity))
    graph.add((subject, URIRef(f"{_ONTORAGFLOW}action"), RdfLiteral(activity.action_uri)))
    graph.add(
        (
            subject,
            URIRef(f"{_ONTORAGFLOW}success"),
            RdfLiteral(activity.success, datatype=XSD.boolean),
        )
    )

    if activity.case_uri is not None:
        graph.add((subject, URIRef(f"{_ONTORAGFLOW}case"), URIRef(activity.case_uri)))
    if activity.agent is not None:
        graph.add((subject, PROV.wasAssociatedWith, URIRef(activity.agent)))
    if activity.started_at is not None:
        graph.add(
            (
                subject,
                PROV.startedAtTime,
                RdfLiteral(activity.started_at.isoformat(), datatype=XSD.dateTime),
            )
        )
    if activity.ended_at is not None:
        graph.add(
            (
                subject,
                PROV.endedAtTime,
                RdfLiteral(activity.ended_at.isoformat(), datatype=XSD.dateTime),
            )
        )
    if activity.informed_by is not None:
        graph.add((subject, PROV.wasInformedBy, URIRef(activity.informed_by)))
    if activity.error is not None:
        graph.add((subject, URIRef(f"{_ONTORAGFLOW}error"), RdfLiteral(activity.error)))

    _add_dataset(graph, subject, PROV.used, activity, "used", activity.used)
    _add_dataset(graph, subject, PROV.generated, activity, "generated", activity.generated)


def _add_dataset(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    activity: ProvOActivity,
    role: str,
    payload: dict[str, Any],
) -> None:
    """Promote a non-empty input/output payload to a ``dcat:Dataset`` node."""

    if not payload:
        return
    dataset = URIRef(_dataset_uri(activity.activity_uri, role))
    graph.add((subject, predicate, dataset))
    graph.add((dataset, RDF.type, DCAT.Dataset))
    graph.add((dataset, URIRef(f"{_ONTORAGFLOW}role"), RdfLiteral(role)))
    graph.add(
        (
            dataset,
            DCAT.distribution,
            RdfLiteral(json.dumps(payload, default=str, sort_keys=True)),
        )
    )


def activities_to_turtle(activities: list[ProvOActivity]) -> str:
    """Serialize activities as Turtle using rdflib.

    Binds the ``prov`` and ``dcat`` namespaces, adds a triple set mirroring
    :func:`activities_to_jsonld`, and serializes. An empty list yields valid
    (namespace-only) Turtle.

    Args:
        activities: The activities to export (may be empty).

    Returns:
        A Turtle document as a string.
    """

    graph = Graph()
    graph.bind("prov", PROV)
    graph.bind("dcat", DCAT)
    graph.bind("ontoragflow", _ONTORAGFLOW)
    for activity in activities:
        _add_activity_triples(graph, activity)
    return graph.serialize(format="turtle")


def render(activities: list[ProvOActivity], fmt: ExportFormat) -> str:
    """Render activities in the requested export format as a string.

    Args:
        activities: The activities to export.
        fmt: Either ``"jsonld"`` or ``"ttl"``.

    Returns:
        The serialized provenance document.

    Raises:
        ValueError: If ``fmt`` is not a recognized export format.
    """

    if fmt == "jsonld":
        return json.dumps(activities_to_jsonld(activities), indent=2, default=str)
    if fmt == "ttl":
        return activities_to_turtle(activities)
    raise ValueError(f"Unsupported export format: {fmt!r}")


__all__ = [
    "ExportFormat",
    "activities_to_jsonld",
    "activities_to_turtle",
    "render",
]
