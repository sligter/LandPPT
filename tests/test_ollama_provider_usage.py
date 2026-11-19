"""OllamaProvider reports the usage and stop reason that Ollama returns."""

import asyncio

from landppt.ai.base import AIMessage, MessageRole
from landppt.ai.providers import OllamaProvider


class _FakeClient:
    def __init__(self, response):
        self.response = response

    async def chat(self, **kwargs):
        return self.response


def _run(response):
    provider = OllamaProvider({"model": "llama3", "base_url": "http://localhost:11434"})
    provider.client = _FakeClient(response)
    messages = [AIMessage(role=MessageRole.USER, content="你好 世界")]
    return asyncio.run(provider.chat_completion(messages))


def test_usage_and_finish_reason_come_from_ollama():
    result = _run({
        "message": {"content": "你好，我是助手"},
        "prompt_eval_count": 12,
        "eval_count": 34,
        "done_reason": "length",
    })

    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}
    assert result.finish_reason == "length"


def test_falls_back_when_ollama_omits_counts():
    result = _run({"message": {"content": "hello there"}})

    assert result.usage["completion_tokens"] == 2
    assert result.finish_reason == "stop"


def test_images_are_sent_as_ollama_images_not_placeholder_text():
    from landppt.ai.base import ImageContent, TextContent

    captured = {}

    class _Capture:
        async def chat(self, **kwargs):
            captured.update(kwargs)
            return {"message": {"content": "ok"}}

    provider = OllamaProvider({"model": "llava", "base_url": "http://localhost:11434"})
    provider.client = _Capture()
    messages = [AIMessage(role=MessageRole.USER, content=[
        TextContent(text="describe this"),
        ImageContent(image_url={"url": "data:image/png;base64,QUJD"}),
    ])]
    asyncio.run(provider.chat_completion(messages))

    sent = captured["messages"][0]
    assert sent["images"] == ["QUJD"]
    assert sent["content"] == "describe this"


def test_tool_calls_are_normalized_to_openai_dicts():
    import json

    from ollama import Message

    message = Message(
        role="assistant",
        content="",
        tool_calls=[Message.ToolCall(function=Message.ToolCall.Function(name="edit_slide", arguments={"slide": 2}))],
    )
    result = _run({"message": message})

    assert result.tool_calls == [
        {
            "id": "ollama-tool-call-1",
            "type": "function",
            "function": {"name": "edit_slide", "arguments": json.dumps({"slide": 2})},
        }
    ]


def test_replayed_tool_call_arguments_are_sent_as_objects():
    captured = {}

    class _Capture:
        async def chat(self, **kwargs):
            captured.update(kwargs)
            return {"message": {"content": "ok"}}

    provider = OllamaProvider({"model": "llama3", "base_url": "http://localhost:11434"})
    provider.client = _Capture()
    call = {"id": "c1", "type": "function", "function": {"name": "edit_slide", "arguments": '{"slide": 2}'}}
    messages = [AIMessage(role=MessageRole.ASSISTANT, content="", tool_calls=[call])]
    asyncio.run(provider.chat_completion(messages))

    assert captured["messages"][0]["tool_calls"][0]["function"]["arguments"] == {"slide": 2}


def test_second_turn_sends_tool_name_on_the_serialized_tool_result():
    import json

    import httpx
    from ollama import AsyncClient

    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "done"}, "done": True})

    provider = OllamaProvider({"model": "llama3", "base_url": "http://localhost:11434"})
    provider.client = AsyncClient(host="http://localhost:11434", transport=httpx.MockTransport(handler))
    call = {"id": "ollama-tool-call-1", "type": "function", "function": {"name": "edit_slide", "arguments": '{"slide": 2}'}}
    messages = [
        AIMessage(role=MessageRole.USER, content="edit slide 2"),
        AIMessage(role=MessageRole.ASSISTANT, content="", tool_calls=[call]),
        AIMessage(role=MessageRole.TOOL, content='{"ok": true}', tool_call_id="ollama-tool-call-1"),
    ]
    asyncio.run(provider.chat_completion(messages))

    tool_message = bodies[0]["messages"][2]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_name"] == "edit_slide"
