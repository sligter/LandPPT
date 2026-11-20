import json
import sys
import types

import aiohttp
import pytest

from landppt.ai.base import AIMessage, MessageRole
from landppt.ai.providers import AnthropicProvider

MESSAGES = [
    AIMessage(role=MessageRole.SYSTEM, content="first system"),
    AIMessage(role=MessageRole.SYSTEM, content="second system"),
    AIMessage(role=MessageRole.USER, content="hello"),
]
EXPECTED = "first system\n\nsecond system"


def _provider():
    return AnthropicProvider(
        {"api_key": "test-key", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-6"}
    )


@pytest.mark.asyncio
async def test_chat_completion_with_tools_keeps_all_system_messages(monkeypatch):
    calls = []

    class FakeMessages:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                model=kwargs["model"],
                content=[types.SimpleNamespace(type="text", text="ok")],
                stop_reason="end_turn",
                usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(
        sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic)
    )
    await _provider().chat_completion(
        MESSAGES, tools=[{"name": "noop", "input_schema": {"type": "object"}}]
    )
    assert calls[0]["system"] == EXPECTED


@pytest.mark.asyncio
async def test_stream_keeps_all_system_messages(monkeypatch):
    bodies = []

    class FakeContent:
        def __aiter__(self):
            return self._iterate()

        async def _iterate(self):
            yield f"data: {json.dumps({'type': 'message_stop'})}\n".encode()

    class FakeResponse:
        status = 200
        content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeSession:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            bodies.append(json)
            return FakeResponse()

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    async for _ in _provider().stream_chat_completion(MESSAGES):
        pass
    assert bodies[0]["system"] == EXPECTED
