import asyncio
from types import SimpleNamespace

import pytest


def _provider(finish_reason):
    from landppt.ai.providers import GoogleProvider

    provider = GoogleProvider.__new__(GoogleProvider)
    provider.config = {}
    provider.model = "gemini-2.5-flash"
    provider.base_url = None
    provider.client = object()
    provider.model_instance = SimpleNamespace(model_name="gemini-2.5-flash")
    provider._should_use_rest_api = lambda base_url: False
    provider._convert_messages_to_gemini = lambda messages: "prompt"
    provider._extract_gemini_tool_calls_from_response = lambda response: []

    async def fake_generate(*args, **kwargs):
        candidate = SimpleNamespace(
            finish_reason=SimpleNamespace(name=finish_reason),
            content=None,
        )
        return SimpleNamespace(candidates=[candidate], usage_metadata=None, text="")

    provider._generate_async = fake_generate
    return provider


@pytest.mark.parametrize(
    "reason", ["SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"]
)
def test_blocked_finish_reasons_return_block_notice(reason):
    from landppt.ai.base import AIMessage, MessageRole

    provider = _provider(reason)
    response = asyncio.run(
        provider.chat_completion([AIMessage(role=MessageRole.USER, content="hi")])
    )

    assert response.finish_reason == reason
    assert response.content == "[内容被安全过滤器阻止]"
