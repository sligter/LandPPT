import os
import sys
import types

import pytest

os.environ["DEBUG"] = "false"

from landppt.ai.base import AIMessage, MessageRole
from landppt.ai.providers import OpenAIProvider


def _delta(text):
    return types.SimpleNamespace(type="response.output_text.delta", delta=text)


def _provider(monkeypatch, events):
    class _Stream:
        def __aiter__(self):
            async def _iterate():
                for event in events:
                    yield event

            return _iterate()

    class _Manager:
        async def __aenter__(self):
            return _Stream()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.responses = types.SimpleNamespace(stream=lambda **kw: _Manager())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI))
    return OpenAIProvider(
        {
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1",
            "use_responses_api": True,
        }
    )


async def _collect(provider):
    chunks = []
    async for chunk in provider.stream_chat_completion(
        [AIMessage(role=MessageRole.USER, content="hello")]
    ):
        chunks.append(chunk)
    return chunks


@pytest.mark.asyncio
async def test_responses_stream_raises_on_response_failed(monkeypatch):
    failed = types.SimpleNamespace(
        type="response.failed",
        response=types.SimpleNamespace(
            error=types.SimpleNamespace(code="server_error", message="boom")
        ),
    )
    provider = _provider(monkeypatch, [_delta("partial"), failed])
    chunks = []
    with pytest.raises(RuntimeError, match="server_error: boom"):
        async for chunk in provider.stream_chat_completion(
            [AIMessage(role=MessageRole.USER, content="hello")]
        ):
            chunks.append(chunk)
    assert "".join(chunks) == "partial"


@pytest.mark.asyncio
async def test_responses_stream_raises_on_error_event(monkeypatch):
    error = types.SimpleNamespace(type="error", code="rate_limit_exceeded", message="slow down")
    provider = _provider(monkeypatch, [error])
    with pytest.raises(RuntimeError, match="rate_limit_exceeded: slow down"):
        await _collect(provider)


@pytest.mark.asyncio
async def test_responses_stream_completes_normally(monkeypatch):
    completed = types.SimpleNamespace(type="response.completed")
    provider = _provider(monkeypatch, [_delta("Hello "), _delta("world"), completed])
    assert "".join(await _collect(provider)) == "Hello world"
