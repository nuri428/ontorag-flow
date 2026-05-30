"""Audit endpoints — read the PROV-O trail recorded for a case.

Every executed action records a :class:`~ontorag_flow.core.action.ProvOActivity`
into the persistence store (which doubles as the audit store). This route
exposes that forensic trail so callers can answer "who changed what, when, why"
for a given case.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, Query
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
    limit: int = Query(
        10_000,
        ge=1,
        le=100_000,
        description=(
            "Cap on activities scanned. The endpoint loads activities into "
            "memory for in-process counting; this cap exists so a runaway "
            "table can't OOM the server. Push the limit up when you know "
            "the activities table is bounded (e.g. after retention purge)."
        ),
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

    Scale note: aggregation is currently in-process. Hard cap defaults to
    10,000 activities; for installations exceeding that, push the bucket
    counting into SQL (``GROUP BY``) instead — tracked as a follow-up.
    """

    activities = await store.list_all()
    if len(activities) > limit:
        activities = activities[-limit:]  # newest-N — operationally most useful

    if process_uri is not None:
        cases = await store.find_cases(process_uri=process_uri)
        keep = {case.case_uri for case in cases}
        activities = [activity for activity in activities if activity.case_uri in keep]

    extractors: dict[GroupBy, Callable[[ProvOActivity], str]] = {
        "action_uri": lambda a: a.action_uri,
        "case_uri": lambda a: a.case_uri or "",
        "status": lambda a: a.status,
        "agent": lambda a: a.agent or "",
    }
    extract = extractors[group_by]
    counts = Counter(key for activity in activities if (key := extract(activity)))
    return [AuditAggregateRow(key=key, count=count) for key, count in counts.most_common()]
