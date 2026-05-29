"""Audit endpoints — read the PROV-O trail recorded for a case.

Every executed action records a :class:`~ontorag_flow.core.action.ProvOActivity`
into the persistence store (which doubles as the audit store). This route
exposes that forensic trail so callers can answer "who changed what, when, why"
for a given case.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ontorag_flow.api.deps import get_store
from ontorag_flow.core.action import ProvOActivity
from ontorag_flow.stores.sqlite import SqliteStore

router = APIRouter(prefix="/cases", tags=["audit"])


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
