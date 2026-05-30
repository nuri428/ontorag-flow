"""LLM provider adapters — Anthropic / OpenAI / Ollama.

Each adapter's ``complete()`` is a thin shim over a third-party SDK. We patch
the SDK entry point so no real API call is made; the test is locking in the
*translation* (model name, message shape, response parsing) — not the SDK.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

# The Anthropic / OpenAI SDKs ship in the optional ``llm`` extra. CI's lint /
# test job installs ``dev`` only — skip the whole module rather than fail
# collection. The ``typecheck`` and ``demo`` paths use --all-extras / --llm.
pytest.importorskip("anthropic", reason="install the 'llm' extra to exercise LLM providers")
pytest.importorskip("openai", reason="install the 'llm' extra to exercise LLM providers")

from ontorag_flow.engines.llm_providers import (  # noqa: E402 — must come after importorskip
    AnthropicClient,
    OllamaClient,
    OpenAIClient,
    make_llm_client,
)

# --- Anthropic -----------------------------------------------------------


class _AnthropicTextBlock:
    type = "text"
    text = "anthropic response"


class _AnthropicNonTextBlock:
    type = "thinking"  # no .text attribute


class _AnthropicMessage:
    content = [_AnthropicTextBlock(), _AnthropicNonTextBlock()]


class _FakeAnthropicMessages:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _AnthropicMessage:
        self.last_kwargs = kwargs
        return _AnthropicMessage()


class _FakeAsyncAnthropic:
    instances: list[_FakeAnthropicMessages] = []

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.messages = _FakeAnthropicMessages()
        _FakeAsyncAnthropic.instances.append(self.messages)


@pytest.fixture
def fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_FakeAsyncAnthropic]]:
    import anthropic

    _FakeAsyncAnthropic.instances = []
    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)
    yield _FakeAsyncAnthropic


async def test_anthropic_client_concatenates_text_blocks_only(
    fake_anthropic: type[_FakeAsyncAnthropic],
) -> None:
    client = AnthropicClient(model="m", api_key="k")
    out = await client.complete(system="sys", user="u")
    assert out == "anthropic response"  # only text block, not thinking block
    messages = fake_anthropic.instances[0]
    assert messages.last_kwargs is not None
    assert messages.last_kwargs["model"] == "m"
    assert messages.last_kwargs["system"] == "sys"
    assert messages.last_kwargs["messages"] == [{"role": "user", "content": "u"}]


# --- OpenAI --------------------------------------------------------------


class _OpenAIMessage:
    content = "openai response"


class _OpenAIChoice:
    message = _OpenAIMessage()


class _OpenAIResponse:
    choices = [_OpenAIChoice()]


class _FakeOpenAICompletions:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _OpenAIResponse:
        self.last_kwargs = kwargs
        return _OpenAIResponse()


class _FakeOpenAIChat:
    def __init__(self) -> None:
        self.completions = _FakeOpenAICompletions()


class _FakeAsyncOpenAI:
    instances: list[_FakeOpenAIChat] = []

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.chat = _FakeOpenAIChat()
        _FakeAsyncOpenAI.instances.append(self.chat)


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_FakeAsyncOpenAI]]:
    import openai

    _FakeAsyncOpenAI.instances = []
    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)
    yield _FakeAsyncOpenAI


async def test_openai_client_reads_first_choice_content(
    fake_openai: type[_FakeAsyncOpenAI],
) -> None:
    client = OpenAIClient(model="gpt-X", api_key="k")
    out = await client.complete(system="sys", user="u")
    assert out == "openai response"
    chat = fake_openai.instances[0]
    assert chat.completions.last_kwargs is not None
    assert chat.completions.last_kwargs["model"] == "gpt-X"
    assert chat.completions.last_kwargs["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
    ]


# --- Ollama (no SDK; raw httpx) ------------------------------------------


async def test_ollama_client_posts_chat_and_parses_message_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    captured: dict[str, Any] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"message": {"content": "ollama response"}}

    class _FakeAsyncClient:
        def __init__(self, timeout: float | None = None) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = OllamaClient(model="llama-test", host="http://ollama.test/")
    out = await client.complete(system="sys", user="u")

    assert out == "ollama response"
    assert captured["url"] == "http://ollama.test/api/chat"
    assert captured["json"]["model"] == "llama-test"
    assert captured["json"]["stream"] is False
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
    ]


# --- make_llm_client unknown provider ------------------------------------


def test_make_llm_client_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        make_llm_client("not-a-thing")
