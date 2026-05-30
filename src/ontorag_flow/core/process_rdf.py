"""Optional RDF representation of process definitions (alongside YAML).

A process can be expressed as an RDF document (Turtle or JSON-LD) so the
process model itself becomes ontology data — a small step toward processes
living in ontorag's ABox. This is additive: YAML remains the default; RDF
is offered for users who want a semantic representation.

Vocabulary (namespace ``urn:ontorag-flow:process#``)::

    <process-uri> a of:Process ;
        of:name "Medical Triage" ;
        of:allowedAction <action-uri-1>, <action-uri-2> ;
        of:engine "rule" ;
        of:goalJson         "{\\"diagnosed\\": true}" ;
        of:initialStateJson "{\\"triage_level\\": \\"unknown\\"}" ;
        of:rulesJson        "[...]" ;
        of:bayesianJson     "{...}" ;
        of:causalJson       "{...}" ;
        of:constraintsJson  "{...}" ;
        of:timerEventsJson  "[...]" .

The structured dict/list fields (goal, initial_state, rules, bayesian,
causal, constraints, timer_events) are carried as JSON-string literals —
pragmatic and lossless, deferring a fully modelled rule vocabulary to a
later milestone. The ``engine`` field is a plain literal because it is a
fixed-vocabulary string.

Both ``process_to_rdf(p, format="turtle")`` and ``format="json-ld"`` are
supported, and :func:`load_process_rdf` dispatches on file extension
(``.ttl`` / ``.n3`` / ``.rdf`` → turtle; ``.jsonld`` / ``.json-ld`` →
json-ld). Other rdflib-supported formats can be requested explicitly.
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


def process_to_rdf(process: ProcessDefinition, *, format: str = "turtle") -> str:
    """Serialize a process definition to RDF (Turtle by default; ``json-ld`` also).

    Args:
        process: The process definition to render.
        format: An rdflib-supported serialization format. Common choices:
            ``"turtle"`` (default), ``"json-ld"``, ``"n3"``, ``"xml"``.
    """

    graph = Graph()
    graph.bind("of", OF)
    subject = URIRef(process.process_uri)

    graph.add((subject, RDF.type, OF.Process))
    graph.add((subject, OF.name, Literal(process.name)))
    for action_uri in process.allowed_actions:
        graph.add((subject, OF.allowedAction, URIRef(action_uri)))
    if process.engine is not None:
        graph.add((subject, OF.engine, Literal(process.engine)))
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
    if process.causal is not None:
        graph.add((subject, OF.causalJson, Literal(json.dumps(process.causal, sort_keys=True))))
    if process.constraints:
        graph.add(
            (
                subject,
                OF.constraintsJson,
                Literal(json.dumps(process.constraints, sort_keys=True)),
            )
        )
    if process.timer_events:
        graph.add(
            (
                subject,
                OF.timerEventsJson,
                Literal(json.dumps(process.timer_events, sort_keys=True)),
            )
        )
    if process.arbitration is not None:
        graph.add(
            (
                subject,
                OF.arbitrationJson,
                Literal(json.dumps(process.arbitration, sort_keys=True)),
            )
        )
    if process.skeleton:
        # Ordered sequence — store as a single JSON literal so the order
        # survives. RDF lists are valid but rdflib's Collection helpers
        # complicate round-trips; JSON keeps it symmetric with other
        # list-shaped fields (timer_events, rules).
        graph.add(
            (
                subject,
                OF.skeletonJson,
                Literal(json.dumps(process.skeleton)),
            )
        )
    if process.max_llm_confidence is not None:
        graph.add((subject, OF.maxLlmConfidence, Literal(process.max_llm_confidence)))
    if process.execute_policy:
        graph.add(
            (
                subject,
                OF.executePolicyJson,
                Literal(json.dumps(process.execute_policy, sort_keys=True)),
            )
        )
    if process.audit_redact:
        graph.add(
            (
                subject,
                OF.auditRedactJson,
                Literal(json.dumps(process.audit_redact)),
            )
        )

    return graph.serialize(format=format)


_FORMAT_BY_SUFFIX = {
    ".ttl": "turtle",
    ".n3": "n3",
    ".rdf": "xml",
    ".xml": "xml",
    ".jsonld": "json-ld",
    ".json-ld": "json-ld",
    ".nt": "nt",
}


def load_process_rdf(path: str | Path, *, format: str | None = None) -> ProcessDefinition:
    """Load and validate a process definition from an RDF file.

    Args:
        path: Path to the RDF file. Format is inferred from the suffix
            (``.ttl`` → turtle, ``.jsonld`` → json-ld, ``.rdf``/``.xml`` →
            xml, ``.n3`` → n3, ``.nt`` → nt). Override with ``format=``.
        format: rdflib format name; overrides the suffix-based dispatch.

    Raises:
        ProcessParseError: If the file is missing, unparseable, does not contain
            exactly one ``of:Process``, or fails validation.
    """

    file_path = Path(path)
    if not file_path.exists():
        raise ProcessParseError(f"Process file not found: {file_path}")

    resolved_format = format or _FORMAT_BY_SUFFIX.get(file_path.suffix.lower(), "turtle")

    graph = Graph()
    try:
        graph.parse(file_path, format=resolved_format)
    except Exception as exc:  # noqa: BLE001 — rdflib raises a variety of errors
        raise ProcessParseError(f"Invalid RDF ({resolved_format}) in {file_path}: {exc}") from exc

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
    engine = graph.value(subject, OF.engine)

    try:
        return ProcessDefinition(
            process_uri=str(subject),
            name=str(name) if name is not None else "",
            allowed_actions=allowed,
            engine=str(engine) if engine is not None else None,
            goal=_json_literal(graph, subject, OF.goalJson) or {},
            initial_state=_json_literal(graph, subject, OF.initialStateJson) or {},
            rules=_json_literal(graph, subject, OF.rulesJson) or [],
            bayesian=_json_literal(graph, subject, OF.bayesianJson),
            causal=_json_literal(graph, subject, OF.causalJson),
            constraints=_json_literal(graph, subject, OF.constraintsJson) or {},
            timer_events=_json_literal(graph, subject, OF.timerEventsJson) or [],
            arbitration=_json_literal(graph, subject, OF.arbitrationJson),
            skeleton=_json_literal(graph, subject, OF.skeletonJson) or [],
            max_llm_confidence=(
                float(str(graph.value(subject, OF.maxLlmConfidence)))
                if graph.value(subject, OF.maxLlmConfidence) is not None
                else None
            ),
            execute_policy=_json_literal(graph, subject, OF.executePolicyJson) or {},
            audit_redact=_json_literal(graph, subject, OF.auditRedactJson) or [],
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
