"""Composition-root helpers for building decision-engine backing clients.

The LLM client (for :class:`LlmAgentEngine`) and the ontorag MCP client (for
:class:`BayesianMpeEngine` / :class:`CausalSimulationEngine`) are built the same
way whether the app or the CLI is the entrypoint. Centralising the construction
here keeps the two composition roots in sync — a typo in one place was the
original :twin: this module replaces.
"""

from __future__ import annotations

from collections.abc import Callable

from ontorag_flow.config import Settings
from ontorag_flow.engines.llm_agent import LlmClient
from ontorag_flow.log import get_logger
from ontorag_flow.ontorag_client.client import OntoragClient

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
) -> OntoragClient | None:
    """Open an ontorag MCP connection if enabled; None if disabled/unreachable.

    Failures are non-fatal — the resolver simply marks Bayesian/Causal engines as
    unavailable. ``on_error`` lets the caller surface the message the way it
    wants (API logger vs CLI console).
    """

    if not settings.connect_ontorag:
        return None

    # Transport trust gate: refuse plain-text when the operator opted into
    # HTTPS-only. URL hijack via env-var manipulation is the threat model.
    if settings.ontorag_mcp_https_only and not settings.ontorag_mcp_url.startswith("https://"):
        message = (
            f"ontorag MCP URL is not https:// ({settings.ontorag_mcp_url}) and "
            f"ONTORAG_MCP_HTTPS_ONLY=true; refusing to connect."
        )
        if on_error is not None:
            on_error(message)
        else:
            logger.warning(message)
        return None

    from ontorag_flow.ontorag_client import OntoragClientError

    client = OntoragClient(settings.ontorag_mcp_url)
    try:
        await client.connect()
    except OntoragClientError as exc:
        message = f"ontorag unreachable; Bayesian/Causal engines disabled: {exc}"
        if on_error is not None:
            on_error(message)
        else:
            logger.warning(message)
        return None

    # Optional version pin: drift detection between this repo and ontorag.
    # WARN only — the connection still works, but the operator knows.
    if settings.ontorag_expected_version is not None:
        try:
            status = await client.call_tool("get_status", {})
            actual = status.get("version") if isinstance(status, dict) else None
            if actual and actual != settings.ontorag_expected_version:
                drift = (
                    f"ontorag version drift: expected "
                    f"{settings.ontorag_expected_version!r}, got {actual!r}"
                )
                if on_error is not None:
                    on_error(drift)
                else:
                    logger.warning(drift)
        except Exception as exc:  # noqa: BLE001 — drift check must not abort boot
            logger.debug("ontorag version check skipped: %s", exc)

    return client
