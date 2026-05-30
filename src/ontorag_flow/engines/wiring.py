"""Composition-root helpers for building decision-engine backing clients.

The LLM client (for :class:`LlmAgentEngine`) and the ontorag MCP client (for
:class:`BayesianMpeEngine` / :class:`CausalSimulationEngine`) are built the same
way whether the app or the CLI is the entrypoint. Centralising the construction
here keeps the two composition roots in sync — a typo in one place was the
original :twin: this module replaces.
"""

from __future__ import annotations

from typing import Callable

from ontorag_flow.config import Settings
from ontorag_flow.engines.bayesian import SupportsToolCall
from ontorag_flow.engines.llm_agent import LlmClient
from ontorag_flow.log import get_logger

logger = get_logger(__name__)

__all__ = ["build_llm_client", "maybe_connect_ontorag"]


def build_llm_client(settings: Settings) -> LlmClient | None:
    """Construct an LLM client from settings, or None if no provider is set."""

    if not settings.llm_provider:
        return None
    from ontorag_flow.engines.llm_providers import make_llm_client

    return make_llm_client(settings.llm_provider, settings.llm_model)


async def maybe_connect_ontorag(
    settings: Settings,
    *,
    on_error: Callable[[str], None] | None = None,
) -> SupportsToolCall | None:
    """Open an ontorag MCP connection if enabled; None if disabled/unreachable.

    Failures are non-fatal — the resolver simply marks Bayesian/Causal engines as
    unavailable. ``on_error`` lets the caller surface the message the way it
    wants (API logger vs CLI console).
    """

    if not settings.connect_ontorag:
        return None
    from ontorag_flow.ontorag_client import OntoragClient, OntoragClientError

    client = OntoragClient(settings.ontorag_mcp_url)
    try:
        await client.connect()
    except OntoragClientError as exc:
        message = (
            f"ontorag unreachable; Bayesian/Causal engines disabled: {exc}"
        )
        if on_error is not None:
            on_error(message)
        else:
            logger.warning(message)
        return None
    return client
