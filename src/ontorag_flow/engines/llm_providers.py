"""Concrete :class:`LlmClient` adapters — Anthropic, OpenAI, Ollama.

Each adapter lazy-imports its SDK inside ``complete`` so importing this module
costs nothing and requires no provider package until a client is actually used
(install with the ``llm`` extra). Ollama is reached over its REST API with httpx,
so it needs no SDK. Direct SDK calls only — no LangChain/LlamaIndex.
"""

from __future__ import annotations

import httpx

from ontorag_flow.engines.llm_agent import LlmClient
from ontorag_flow.log import get_logger

logger = get_logger(__name__)

__all__ = [
    "AnthropicClient",
    "OpenAIClient",
    "OllamaClient",
    "make_llm_client",
]

_MAX_TOKENS = 1024
# Fable 5's adaptive thinking tokens count toward max_tokens; allocate enough
# headroom so the model can reason before producing the JSON proposals.
_FABLE_MAX_TOKENS = 8096
_DEFAULT_TIMEOUT_SECONDS = 30.0
# Fable 5 can run for several minutes on hard reasoning tasks.
_FABLE_TIMEOUT_SECONDS = 180.0
_FABLE_5_MODEL = "claude-fable-5"


class AnthropicClient:
    """:class:`LlmClient` over the Anthropic Messages API."""

    def __init__(self, model: str = "claude-sonnet-4-6", *, api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key
        self._is_fable = model == _FABLE_5_MODEL

    async def complete(self, *, system: str, user: str) -> str:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - requires the `llm` extra
            raise RuntimeError("anthropic is not installed; install the 'llm' extra.") from exc

        timeout = _FABLE_TIMEOUT_SECONDS if self._is_fable else _DEFAULT_TIMEOUT_SECONDS
        max_tokens = _FABLE_MAX_TOKENS if self._is_fable else _MAX_TOKENS
        client = AsyncAnthropic(api_key=self._api_key, timeout=timeout)

        if self._is_fable:
            # Fable 5: thinking is always on (omit the parameter), use server-side
            # fallbacks so a safety refusal is transparently re-served by Opus 4.8.
            message = await client.beta.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                betas=["server-side-fallback-2026-06-01"],
                fallbacks=[{"model": "claude-opus-4-8"}],
            )
        else:
            message = await client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

        # Fable 5 (and the Opus 4.8 fallback) can return stop_reason="refusal".
        # An empty content array means nothing to parse — return "" so the
        # engine's JSON parser produces no proposals rather than crashing.
        if getattr(message, "stop_reason", None) == "refusal":
            logger.warning(
                "Anthropic safety classifier declined the request (model=%s); "
                "returning empty response so the engine produces no proposals.",
                self._model,
            )
            return ""

        # Anthropic's ContentBlock is a union of many types (text / tool_use /
        # thinking / ...); only TextBlock has a ``text`` attribute. Filter by
        # the type tag, then use getattr so the type checker is happy with the
        # union without us re-exporting every block class.
        return "".join(
            getattr(block, "text", "")
            for block in message.content
            if getattr(block, "type", None) == "text"
        )


class OpenAIClient:
    """:class:`LlmClient` over the OpenAI Chat Completions API."""

    def __init__(self, model: str = "gpt-4o", *, api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key

    async def complete(self, *, system: str, user: str) -> str:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - requires the `llm` extra
            raise RuntimeError("openai is not installed; install the 'llm' extra.") from exc

        client = AsyncOpenAI(api_key=self._api_key, timeout=_DEFAULT_TIMEOUT_SECONDS)
        response = await client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


class OllamaClient:
    """:class:`LlmClient` over a local Ollama server's REST API (no SDK)."""

    def __init__(self, model: str = "llama3.1", *, host: str = "http://localhost:11434") -> None:
        self._model = model
        self._host = host.rstrip("/")

    async def complete(self, *, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._host}/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            response.raise_for_status()
            return response.json()["message"]["content"]


def make_llm_client(provider: str, model: str | None = None, **kwargs: object) -> LlmClient:
    """Build an :class:`LlmClient` for the named provider.

    Args:
        provider: One of ``"anthropic"``, ``"openai"``, ``"ollama"``.
        model: Optional model override; each adapter has a sensible default.
        **kwargs: Passed to the adapter (e.g. ``api_key``, ``host``).

    Raises:
        ValueError: If the provider is unknown.
    """

    normalized = provider.lower()
    if normalized == "anthropic":
        return AnthropicClient(model or "claude-sonnet-4-6", **kwargs)  # type: ignore[arg-type]
    if normalized == "openai":
        return OpenAIClient(model or "gpt-4o", **kwargs)  # type: ignore[arg-type]
    if normalized == "ollama":
        return OllamaClient(model or "llama3.1", **kwargs)  # type: ignore[arg-type]
    raise ValueError(f"Unknown LLM provider: {provider!r}")
