"""Optional RDF representation of process definitions (alongside YAML).

A process can be expressed as an RDF/Turtle document so the process model itself
becomes ontology data — a small step toward processes living in ontorag's ABox.
This is additive: YAML remains the default; RDF is offered for users who want a
semantic representation.

Vocabulary (namespace ``urn:ontorag-flow:process#``)::

    <process-uri> a of:Process ;
        of:name "Medical Triage" ;
        of:allowedAction <action-uri-1>, <action-uri-2> ;
        of:goalJson "{\\"diagnosed\\": true}" ;
        of:initialStateJson "{\\"triage_level\\": \\"unknown\\"}" ;
        of:rulesJson "[...]" ;
        of:bayesianJson "{...}" .

The structured dict/list fields (goal, initial_state, rules, bayesian) are
carried as JSON-string literals — pragmatic and lossless, deferring a fully
modelled rule vocabulary to a later milestone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from ontorag_flow.core.process import ProcessDefinition, ProcessParseError

OF = Namespace("urn:ontorag-flow:process#")

__all__ = ["OF", "process_to_rdf", "load_process_rdf"]


def process_to_rdf(process: ProcessDefinition) -> str:
    """Serialize a process definition to Turtle."""

    graph = Graph()
    graph.bind("of", OF)
    subject = URIRef(process.process_uri)

    graph.add((subject, RDF.type, OF.Process))
    graph.add((subject, OF.name, Literal(process.name)))
    for action_uri in process.allowed_actions:
        graph.add((subject, OF.allowedAction, URIRef(action_uri)))
    if process.goal:
        graph.add((subject, OF.goalJson, Literal(json.dumps(process.goal, sort_keys=True))))
    if process.initial_state:
        graph.add(
            (
                subject,
                OF.initialStateJson,
                Literal(json.dumps(process.initial_state, sort_keys=True)),
            )
        )
    if process.rules:
        graph.add((subject, OF.rulesJson, Literal(json.dumps(process.rules, sort_keys=True))))
    if process.bayesian is not None:
        graph.add((subject, OF.bayesianJson, Literal(json.dumps(process.bayesian, sort_keys=True))))

    return graph.serialize(format="turtle")


def load_process_rdf(path: str | Path) -> ProcessDefinition:
    """Load and validate a process definition from a Turtle file.

    Args:
        path: Path to the ``.ttl`` file.

    Raises:
        ProcessParseError: If the file is missing, unparseable, does not contain
            exactly one ``of:Process``, or fails validation.
    """

    file_path = Path(path)
    if not file_path.exists():
        raise ProcessParseError(f"Process file not found: {file_path}")

    graph = Graph()
    try:
        graph.parse(file_path, format="turtle")
    except Exception as exc:  # noqa: BLE001 — rdflib raises a variety of errors
        raise ProcessParseError(f"Invalid Turtle in {file_path}: {exc}") from exc

    subjects = list(graph.subjects(RDF.type, OF.Process))
    if len(subjects) != 1:
        raise ProcessParseError(
            f"Expected exactly one of:Process in {file_path}, found {len(subjects)}."
        )
    candidate = subjects[0]
    if not isinstance(candidate, URIRef):
        raise ProcessParseError(
            f"Process subject in {file_path} must be a URI, not {type(candidate).__name__}."
        )
    subject: URIRef = candidate

    name = graph.value(subject, OF.name)
    allowed = sorted(str(obj) for obj in graph.objects(subject, OF.allowedAction))

    try:
        return ProcessDefinition(
            process_uri=str(subject),
            name=str(name) if name is not None else "",
            allowed_actions=allowed,
            goal=_json_literal(graph, subject, OF.goalJson) or {},
            initial_state=_json_literal(graph, subject, OF.initialStateJson) or {},
            rules=_json_literal(graph, subject, OF.rulesJson) or [],
            bayesian=_json_literal(graph, subject, OF.bayesianJson),
        )
    except ValidationError as exc:
        raise ProcessParseError(
            f"Invalid process definition in {file_path}: {exc.errors()}"
        ) from exc


def _json_literal(graph: Graph, subject: URIRef, predicate: URIRef) -> Any:
    """Decode a JSON-string literal value, or None if the predicate is absent."""

    value = graph.value(subject, predicate)
    if value is None:
        return None
    try:
        return json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ProcessParseError(f"Malformed JSON literal for {predicate}: {value!r}") from exc
