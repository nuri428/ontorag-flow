"""Domain-specific actions for the supply-chain root-cause-analysis demo.

Each action picks a different :class:`SideEffectKind` so the demo exercises
the full spectrum the framework cares about — local state changes, external
API calls, and the human handoff that makes the case manager auto-suspend.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ontorag_flow.core.action import ActionResult, BaseAction, SideEffectKind
from ontorag_flow.core.state import CaseState


class RecordEvidence(BaseAction):
    """Append a free-text observation to the case's evidence dossier."""

    uri: ClassVar[str] = "urn:demo:supply-chain:RecordEvidence"
    name: ClassVar[str] = "Record evidence"
    description: ClassVar[str] = "Add a free-text note to the case's evidence list."
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.CASE_STATE})

    class Params(BaseModel):
        note: str = Field(min_length=1)

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
        existing: list[Any] = list(state.properties.get("evidence", []))
        existing.append(params.note)
        return ActionResult(
            action_uri=self.uri,
            outputs={"note": params.note},
            state_changes={
                "evidence": existing,
                "evidence_count": len(existing),
            },
        )


class QuerySupplier(BaseAction):
    """Call the supplier's status endpoint (simulated for the demo)."""

    uri: ClassVar[str] = "urn:demo:supply-chain:QuerySupplier"
    name: ClassVar[str] = "Query supplier"
    description: ClassVar[str] = (
        "Hit the supplier's status API and record the response. Simulated here "
        "as a non-responsive supplier so the demo flow exercises the fallback."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.EXTERNAL_API, SideEffectKind.CASE_STATE}
    )

    class Params(BaseModel):
        supplier_id: str

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
        # In a real engagement this would be an httpx call; for the demo we
        # return a deterministic "non_responsive" so the flow continues to the
        # backup-routing rule below.
        return ActionResult(
            action_uri=self.uri,
            outputs={"supplier_id": params.supplier_id, "response": "non_responsive"},
            state_changes={
                "supplier_id": params.supplier_id,
                "supplier_status": "non_responsive",
            },
        )


class RouteThroughBackup(BaseAction):
    """Switch the shipment to the backup carrier."""

    uri: ClassVar[str] = "urn:demo:supply-chain:RouteThroughBackup"
    name: ClassVar[str] = "Route through backup carrier"
    description: ClassVar[str] = (
        "Move the shipment to a secondary carrier. Side effect is external "
        "(carrier API) plus a state change recording the new route."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.EXTERNAL_API, SideEffectKind.CASE_STATE}
    )

    class Params(BaseModel):
        backup_id: str

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
        return ActionResult(
            action_uri=self.uri,
            outputs={"backup_id": params.backup_id},
            state_changes={
                "routing": "backup",
                "backup_id": params.backup_id,
            },
        )


class ApproveCompensation(BaseAction):
    """Request human sign-off on customer compensation — auto-suspends the case."""

    uri: ClassVar[str] = "urn:demo:supply-chain:ApproveCompensation"
    name: ClassVar[str] = "Approve customer compensation"
    description: ClassVar[str] = (
        "Open a compensation-approval ticket. Declaring the HUMAN side effect "
        "causes CaseManager to auto-suspend the case until a human calls resume."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.HUMAN, SideEffectKind.CASE_STATE}
    )

    class Params(BaseModel):
        reason: str

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
        return ActionResult(
            action_uri=self.uri,
            outputs={"reason": params.reason},
            state_changes={
                "compensation_pending": True,
                "compensation_reason": params.reason,
            },
        )


DOMAIN_ACTIONS: tuple[BaseAction, ...] = (
    RecordEvidence(),
    QuerySupplier(),
    RouteThroughBackup(),
    ApproveCompensation(),
)
"""Convenience tuple — every action the supply-chain demo needs to register."""
