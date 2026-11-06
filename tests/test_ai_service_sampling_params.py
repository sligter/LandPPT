"""A caller-supplied temperature/top_p of 0 must reach the provider, not the config default."""

import asyncio
from types import SimpleNamespace

import pytest

from landppt.api.models import ChatCompletionRequest, CompletionRequest
from landppt.core.config import ai_config
from landppt.services import ai_service as ai_service_module
from landppt.services.ai_service import AIService


class _RecordingProvider:
    def __init__(self):
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content="ok")

    async def text_completion(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content="ok")


@pytest.fixture
def provider(monkeypatch):
    recorder = _RecordingProvider()
    monkeypatch.setattr(ai_service_module, "get_ai_provider", lambda name=None: recorder)
    monkeypatch.setattr(ai_config, "temperature", 0.7, raising=False)
    monkeypatch.setattr(ai_config, "top_p", 0.9, raising=False)
    return recorder


def _chat(**extra):
    return ChatCompletionRequest(
        model="m", messages=[{"role": "user", "content": "hi"}], **extra
    )


def _completion(**extra):
    return CompletionRequest(model="m", prompt="hi", **extra)


@pytest.mark.parametrize("handler", ["handle_ppt_chat_request", "handle_general_chat_request"])
def test_chat_keeps_zero_temperature_and_top_p(provider, handler):
    asyncio.run(getattr(AIService(), handler)(_chat(temperature=0, top_p=0)))
    assert provider.calls[0]["temperature"] == 0
    assert provider.calls[0]["top_p"] == 0


@pytest.mark.parametrize(
    "handler", ["handle_ppt_completion_request", "handle_general_completion_request"]
)
def test_completion_keeps_zero_temperature_and_top_p(provider, handler):
    asyncio.run(getattr(AIService(), handler)(_completion(temperature=0, top_p=0)))
    assert provider.calls[0]["temperature"] == 0
    assert provider.calls[0]["top_p"] == 0


def test_unset_values_still_use_config_defaults(provider):
    request = _chat()
    request.temperature = None
    request.top_p = None
    asyncio.run(AIService().handle_general_chat_request(request))
    assert provider.calls[0]["temperature"] == 0.7
    assert provider.calls[0]["top_p"] == 0.9
