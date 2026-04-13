import os
import sys
import types

import pytest

os.environ["DEBUG"] = "false"

from landppt.ai.base import AIMessage, MessageRole
from landppt.ai.providers import OpenAIProvider


class _FailingChatCompletions:
    async def create(self, **kwargs):
        raise AssertionError("chat.completions.create should not be used when responses API is enabled")


class _FakeChatCompletions:
    def __init__(self):
        self.create_calls = []

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return types.SimpleNamespace(
            model=kwargs["model"],
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="Hello from chat completions"),
                    finish_reason="stop",
                )
            ],
            usage=types.SimpleNamespace(prompt_tokens=13, completion_tokens=8, total_tokens=21),
        )


class _FakeResponsesStream:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        async def _iterate():
            for event in self._events:
                yield event

        return _iterate()


class _FakeResponsesStreamManager:
    def __init__(self, events):
        self._events = events

    async def __aenter__(self):
        return _FakeResponsesStream(self._events)

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeResponsesAPI:
    def __init__(self):
        self.create_calls = []
        self.stream_calls = []

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return types.SimpleNamespace(
            model=kwargs["model"],
            output_text="Hello from responses",
            usage=types.SimpleNamespace(input_tokens=11, output_tokens=7, total_tokens=18),
            status="completed",
            incomplete_details=None,
        )

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        events = [
            types.SimpleNamespace(type="response.output_text.delta", delta="Hello "),
            types.SimpleNamespace(type="response.output_text.delta", delta="from "),
            types.SimpleNamespace(type="response.output_text.delta", delta="responses"),
        ]
        return _FakeResponsesStreamManager(events)


@pytest.mark.asyncio
async def test_openai_provider_chat_completion_uses_responses_api(monkeypatch):
    instances = []

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.responses = _FakeResponsesAPI()
            self.chat = types.SimpleNamespace(completions=_FailingChatCompletions())
            instances.append(self)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI))

    provider = OpenAIProvider(
        {
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1",
            "use_responses_api": True,
            "enable_reasoning": True,
            "reasoning_effort": "high",
        }
    )

    response = await provider.chat_completion(
        [AIMessage(role=MessageRole.USER, content="hello")],
    )

    assert response.content == "Hello from responses"
    assert response.usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert response.metadata["transport"] == "responses"
    assert len(instances) == 1
    assert instances[0].responses.create_calls[0]["input"][0]["content"] == "hello"
    assert instances[0].responses.create_calls[0]["reasoning"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_openai_provider_streaming_uses_responses_api(monkeypatch):
    instances = []

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.responses = _FakeResponsesAPI()
            self.chat = types.SimpleNamespace(completions=_FailingChatCompletions())
            instances.append(self)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI))

    provider = OpenAIProvider(
        {
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1",
            "use_responses_api": True,
            "enable_reasoning": True,
            "reasoning_effort": "minimal",
        }
    )

    chunks = []
    async for chunk in provider.stream_chat_completion(
        [AIMessage(role=MessageRole.USER, content="hello")],
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "Hello from responses"
    assert len(instances) == 1
    assert instances[0].responses.stream_calls[0]["input"][0]["content"] == "hello"
    assert instances[0].responses.stream_calls[0]["reasoning"] == {"effort": "minimal"}


@pytest.mark.asyncio
async def test_openai_provider_chat_completions_uses_reasoning_effort(monkeypatch):
    instances = []

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.responses = _FakeResponsesAPI()
            self.chat = types.SimpleNamespace(completions=_FakeChatCompletions())
            instances.append(self)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI))

    provider = OpenAIProvider(
        {
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1",
            "enable_reasoning": True,
            "reasoning_effort": "low",
        }
    )

    response = await provider.chat_completion(
        [AIMessage(role=MessageRole.USER, content="hello")],
    )

    assert response.content == "Hello from chat completions"
    assert response.metadata["transport"] == "chat_completions"
    assert len(instances) == 1
    assert instances[0].chat.completions.create_calls[0]["reasoning_effort"] == "low"
