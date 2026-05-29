"""Persistence backends for processes, cases, and the audit log.

ontorag-flow stores only its *own* data here — process definitions, case state,
and provenance. Domain ontology data (TBox/ABox) lives in ontorag and is reached
over MCP, never duplicated.
"""

from __future__ import annotations
