"""Read-only Web UI for ontorag-flow.

Server-rendered Jinja2 pages mounted under ``/ui`` (and ``/ui/static`` for the
single stylesheet). Provides four views:

* dashboard — open cases plus recent activity;
* action library — registered actions with their schemas and side effects;
* case inspector — current state, history, and live decision-engine proposals;
* audit trail — PROV-O activities for one case.

All four are read-only: mutating actions (suspend/compensate/...) live on the
JSON API and CLI, so the UI does not duplicate them.
"""

from __future__ import annotations
