"""Audit endpoints — read the PROV-O trail recorded for a case.

Every executed action records a :class:`~ontorag_flow.core.action.ProvOActivity`
into the persistence store (which doubles as the audit store). This route
exposes that forensic trail so callers can answer "who changed what, when, why"
for a given case.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ontorag_flow.api.deps import get_store
from ontorag_flow.core.action import ProvOActivity
from ontorag_flow.stores.sqlite import SqliteStore

router = APIRouter(prefix="/cases", tags=["audit"])
aggregate_router = APIRouter(prefix="/audit", tags=["audit"])

GroupBy = Literal["action_uri", "case_uri", "status", "agent"]


class AuditAggregateRow(BaseModel):
    """One bucket of a cross-case audit aggregation."""

    key: str = Field(description="Group key (action URI, case URI, status, or agent).")
    count: int = Field(description="Number of activities in this bucket.")


@router.get(
    "/{case_uri}/audit",
    operation_id="get_audit_trail",
    response_model=list[ProvOActivity],
)
async def get_audit_trail(
    case_uri: str,
    store: SqliteStore = Depends(get_store),
) -> list[ProvOActivity]:
    """Return the ordered PROV-O activities recorded for a case.

    The trail is append-only and chronological; an unknown case simply yields
    an empty list (a case with no recorded actions has no audit trail).
    """

    return await store.list_by_case(case_uri)


@aggregate_router.get(
    "/aggregate",
    operation_id="aggregate_audit",
    response_model=list[AuditAggregateRow],
)
async def aggregate_audit(
    group_by: GroupBy = Query(
        "action_uri",
        description="Bucket activities by action URI, case URI, status, or agent.",
    ),
    process_uri: str | None = Query(
        None,
        description="Optional filter — only count activities whose case belongs to this process.",
    ),
    store: SqliteStore = Depends(get_store),
) -> list[AuditAggregateRow]:
    """Cross-case audit aggregation — "what's hot in the system right now?".

    Reads :meth:`AuditStore.list_all` and buckets by the chosen key. The
    only allowed group keys are fields on PROV-O activities that make
    operational sense to group on. Returned best-first (highest count)
    so the most-fired action / most-active case is at the top.

    Operational uses: catch a rule that's firing far more often than
    expected, find the case with the deepest history, surface a failed
    activity cluster after an incident.
    """

    activities = await store.list_all()

    if process_uri is not None:
        cases = await store.find_cases(process_uri=process_uri)
        keep = {case.case_uri for case in cases}
        activities = [activity for activity in activities if activity.case_uri in keep]

    keys: list[str] = []
    for activity in activities:
        if group_by == "action_uri":
            keys.append(activity.action_uri)
        elif group_by == "case_uri":
            keys.append(activity.case_uri or "")
        elif group_by == "status":
            keys.append(activity.status)
        elif group_by == "agent":
            keys.append(activity.agent or "")
        else:  # pragma: no cover — Literal already constrains the enum
            raise HTTPException(status_code=400, detail=f"Unsupported group_by: {group_by}")

    counts = Counter(k for k in keys if k)
    return [AuditAggregateRow(key=key, count=count) for key, count in counts.most_common()]
