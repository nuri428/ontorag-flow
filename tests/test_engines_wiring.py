"""Composition-root helpers — build_llm_client / maybe_connect_ontorag.

These functions are pure construction so the tests are unit-level: feed a
Settings object, observe the returned client (or None). The actual provider
classes are imported lazily inside :func:`make_llm_client`, so we don't need
the ``llm`` extra installed.
"""

from __future__ import annotations

from typing import Any

import pytest

from ontorag_flow.config import Settings
from ontorag_flow.engines.wiring import build_llm_client, maybe_connect_ontorag


def test_build_llm_client_returns_none_when_provider_unset() -> None:
    settings = Settings(llm_provider=None)
    assert build_llm_client(settings) is None


@pytest.mark.parametrize(
    "provider,expected_class_name",
    [
        ("anthropic", "AnthropicClient"),
        ("openai", "OpenAIClient"),
        ("ollama", "OllamaClient"),
    ],
)
def test_build_llm_client_returns_provider_specific_client(
    provider: str, expected_class_name: str
) -> None:
    # No API call is made here — only construction. The lazy import of
    # anthropic/openai inside .complete() means we don't need the extras.
    settings = Settings(llm_provider=provider, llm_model="some-model")
    client = build_llm_client(settings)
    assert client is not None
    assert type(client).__name__ == expected_class_name


def test_build_llm_client_unknown_provider_raises() -> None:
    settings = Settings(llm_provider="not-a-provider")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_llm_client(settings)


async def test_maybe_connect_ontorag_returns_none_when_disabled() -> None:
    settings = Settings(connect_ontorag=False)
    assert await maybe_connect_ontorag(settings) is None


async def test_maybe_connect_ontorag_surfaces_error_via_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the MCP connect fails, ``on_error`` is invoked and None is returned."""

    from ontorag_flow.ontorag_client import OntoragClientError
    from ontorag_flow.ontorag_client import client as client_module

    async def failing_connect(self: Any) -> None:
        raise OntoragClientError("unreachable: simulated")

    monkeypatch.setattr(client_module.OntoragClient, "connect", failing_connect)

    settings = Settings(connect_ontorag=True, ontorag_mcp_url="http://example.invalid")
    errors: list[str] = []
    result = await maybe_connect_ontorag(settings, on_error=errors.append)

    assert result is None
    assert len(errors) == 1
    assert "unreachable: simulated" in errors[0]


async def test_maybe_connect_ontorag_falls_back_to_logger_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Without ``on_error``, the failure goes to the module logger."""

    import logging

    from ontorag_flow.ontorag_client import OntoragClientError
    from ontorag_flow.ontorag_client import client as client_module

    async def failing_connect(self: Any) -> None:
        raise OntoragClientError("boom")

    monkeypatch.setattr(client_module.OntoragClient, "connect", failing_connect)

    settings = Settings(connect_ontorag=True, ontorag_mcp_url="http://example.invalid")
    with caplog.at_level(logging.WARNING, logger="ontorag_flow.engines.wiring"):
        result = await maybe_connect_ontorag(settings)

    assert result is None
    assert any("Bayesian/Causal engines disabled" in r.message for r in caplog.records)


async def test_maybe_connect_ontorag_returns_client_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ontorag_flow.ontorag_client import client as client_module

    connected: list[bool] = []

    async def fake_connect(self: Any) -> None:
        connected.append(True)

    monkeypatch.setattr(client_module.OntoragClient, "connect", fake_connect)

    settings = Settings(connect_ontorag=True, ontorag_mcp_url="http://example.invalid")
    client = await maybe_connect_ontorag(settings)

    assert client is not None
    assert connected == [True]
