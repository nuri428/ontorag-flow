"""ABox write-back actions — :class:`AssertTriple` / :class:`RetractTriple`.

These are the only built-in actions whose declared side effect is
``ABOX_WRITE``: every execution makes a network call to ontorag's MCP
server (``assert_triple`` / ``retract_triple`` — see
:mod:`ontorag_flow.ontorag_client.tools`) and changes ontology state
that *other repos and reasoners can see*.

Two consequences:

1. The executor's write-ahead audit fires (a ``pending`` PROV-O row is
   written *before* the MCP call, then upserted to ``completed`` /
   ``failed`` after) — same protocol every external action uses.
2. They are constructed with an :class:`OntoragClient` injected; without
   one, instantiation fails fast at composition root. This keeps the
   "domain registry should not know about transports" rule —
   :func:`default_registry` doesn't include them unless the caller
   explicitly provides a client (see ``triple_registry()`` below).

Saga compensation: ``AssertTriple.compensate`` issues ``retract_triple``
on the same ``(s, p, o, graph)`` so a rollback returns the ABox to its
pre-action shape. ``RetractTriple.compensate`` is the inverse.
"""

from __future__ import annotations

from typing import ClassVar, override

from pydantic import BaseModel, Field

from ontorag_flow.core.action import (
    ActionResult,
    BaseAction,
    SideEffectKind,
)
from ontorag_flow.core.state import CaseState
from ontorag_flow.ontorag_client.client import OntoragClient
from ontorag_flow.ontorag_client.tools import assert_triple, retract_triple


class _TripleParams(BaseModel):
    """Common shape — every triple action takes the same four fields."""

    subject: str = Field(min_length=1, description="Subject URI of the triple.")
    predicate: str = Field(min_length=1, description="Predicate URI of the triple.")
    object: str = Field(min_length=1, description="Object URI or literal.")
    graph: str | None = Field(
        default=None,
        description="Optional named graph URI; defaults to the ABox default graph.",
    )


class AssertTriple(BaseAction):
    """Write one ``(s, p, o)`` triple into ontorag's ABox."""

    uri: ClassVar[str] = "urn:ontorag-flow:action:AssertTriple"
    name: ClassVar[str] = "Assert Triple"
    description: ClassVar[str] = (
        "Write one (s, p, o) triple into ontorag's ABox via the assert_triple MCP tool."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.ABOX_WRITE})

    input_schema: ClassVar[type[BaseModel]] = _TripleParams

    def __init__(self, client: OntoragClient) -> None:
        self._client = client

    async def execute(self, params: _TripleParams, state: CaseState) -> ActionResult:  # type: ignore[override]
        await assert_triple(
            self._client,
            params.subject,
            params.predicate,
            params.object,
            graph=params.graph,
        )
        return ActionResult(
            action_uri=self.uri,
            success=True,
            outputs={
                "subject": params.subject,
                "predicate": params.predicate,
                "object": params.object,
                "graph": params.graph,
                "operation": "assert",
            },
        )

    @override
    async def compensate(self, result: ActionResult) -> None:
        """Saga rollback: retract the same triple we asserted."""

        out = result.outputs
        await retract_triple(
            self._client,
            str(out["subject"]),
            str(out["predicate"]),
            str(out["object"]),
            graph=out.get("graph"),
        )


class RetractTriple(BaseAction):
    """Remove one ``(s, p, o)`` triple from ontorag's ABox."""

    uri: ClassVar[str] = "urn:ontorag-flow:action:RetractTriple"
    name: ClassVar[str] = "Retract Triple"
    description: ClassVar[str] = (
        "Remove one (s, p, o) triple from ontorag's ABox via the retract_triple MCP tool."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.ABOX_WRITE})

    input_schema: ClassVar[type[BaseModel]] = _TripleParams

    def __init__(self, client: OntoragClient) -> None:
        self._client = client

    async def execute(self, params: _TripleParams, state: CaseState) -> ActionResult:  # type: ignore[override]
        await retract_triple(
            self._client,
            params.subject,
            params.predicate,
            params.object,
            graph=params.graph,
        )
        return ActionResult(
            action_uri=self.uri,
            success=True,
            outputs={
                "subject": params.subject,
                "predicate": params.predicate,
                "object": params.object,
                "graph": params.graph,
                "operation": "retract",
            },
        )

    @override
    async def compensate(self, result: ActionResult) -> None:
        """Saga rollback: re-assert the triple we retracted."""

        out = result.outputs
        await assert_triple(
            self._client,
            str(out["subject"]),
            str(out["predicate"]),
            str(out["object"]),
            graph=out.get("graph"),
        )
