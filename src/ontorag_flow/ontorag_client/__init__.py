"""MCP client for the sister ontorag server.

ontorag-flow consumes ontorag's reasoning (lookup, schema, Bayesian, causal)
purely over MCP. It never reimplements reasoning or talks to a triple store
directly — all ontorag access flows through this package.
"""

from __future__ import annotations

from ontorag_flow.ontorag_client.client import OntoragClient, OntoragClientError

__all__ = ["OntoragClient", "OntoragClientError"]
