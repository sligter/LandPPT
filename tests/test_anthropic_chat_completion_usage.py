import json

import aiohttp
import pytest

from landppt.ai.base import AIMessage, MessageRole
from landppt.ai.providers import AnthropicProvider


def _sse(*events):
    return [f"data: {json.dumps(event)}\n".encode() for event in events]


def _text_delta(text):
    return {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": text},
    }


def _install_fake_session(monkeypatch, lines, *, attempts=None, closed=None):
    posts = []

    class FakeContent:
        def __aiter__(self):
            return self._iterate()

        async def _iterate(self):
            for line in lines:
                yield line

    class FakeResponse:
        status = 200
        content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            if closed is not None:
                closed.append("response")
            return False

    class FakeSession:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            if closed is not None:
                closed.append("session")
            return False

        def post(self, url, headers=None, json=None):
            posts.append(headers)
            response = FakeResponse()
            if attempts is not None:
                attempt_lines = attempts[len(posts) - 1]

                class AttemptContent:
                    async def __aiter__(self):
                        for line in attempt_lines:
                            yield line

                response.content = AttemptContent()
            return response

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    return posts


def _provider():
    return AnthropicProvider(
        {
            "api_key": "test-key",
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-5-5",
        }
    )


async def _chat(provider):
    provider.client = object()  # chat_completion only checks that a client exists; the stream uses aiohttp
    return await provider.chat_completion(
        [AIMessage(role=MessageRole.USER, content="hello")]
    )


def _stream_events(stop_reason):
    return _sse(
        {
            "type": "message_start",
            "message": {"usage": {"input_tokens": 25, "output_tokens": 1}},
        },
        _text_delta("Slide 1"),
        _text_delta(" done"),
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason},
            "usage": {"output_tokens": 42},
        },
        {"type": "message_stop"},
    )


@pytest.mark.asyncio
async def test_chat_completion_without_tools_reports_usage_and_stop_reason(
    monkeypatch,
):
    _install_fake_session(monkeypatch, _stream_events("end_turn"))

    response = await _chat(_provider())

    assert response.content == "Slide 1 done"
    assert response.usage == {
        "prompt_tokens": 25,
        "completion_tokens": 42,
        "total_tokens": 67,
    }
    assert response.finish_reason == "end_turn"


@pytest.mark.asyncio
async def test_chat_completion_without_tools_reports_truncation(monkeypatch):
    _install_fake_session(monkeypatch, _stream_events("max_tokens"))

    response = await _chat(_provider())

    assert response.finish_reason == "max_tokens"


@pytest.mark.asyncio
async def test_chat_completion_without_usage_events_keeps_the_old_defaults(
    monkeypatch,
):
    _install_fake_session(monkeypatch, _sse(_text_delta("hi")))

    response = await _chat(_provider())

    assert response.content == "hi"
    assert response.usage == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_auth_fallback_does_not_reuse_failed_attempt_usage(monkeypatch):
    posts = _install_fake_session(
        monkeypatch, [], attempts=[
            _sse(
                {"type": "message_start", "message": {
                    "usage": {"input_tokens": 250, "output_tokens": 1},
                }},
                {"type": "error", "error": {
                    "type": "overloaded_error", "message": "Overloaded",
                }},
            ),
            _sse(_text_delta("hi")),
        ],
    )

    response = await _chat(_provider())

    assert response.content == "hi"
    assert response.usage == {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    }
    assert response.finish_reason == "stop"
    assert [list(headers)[-1] for headers in posts] == ["x-api-key", "Authorization"]


@pytest.mark.asyncio
async def test_closing_stream_awaits_response_and_session_cleanup(monkeypatch):
    closed = []
    _install_fake_session(
        monkeypatch, _sse(_text_delta("hello"), _text_delta("world")), closed=closed,
    )
    stream = _provider().stream_chat_completion(
        [AIMessage(role=MessageRole.USER, content="hello")]
    )
    try:
        assert await anext(stream) == "hello"
        assert closed == []
    finally:
        await stream.aclose()

    assert closed == ["response", "session"]
