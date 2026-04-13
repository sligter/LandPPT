import sys
import types
from types import SimpleNamespace

import pytest

# 这些模块是研究链路的可选依赖，本测试只验证大纲与运行时逻辑，缺失时用最小桩避免导入失败。
if "bs4" not in sys.modules:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object, Comment=object)

if "tavily" not in sys.modules:
    sys.modules["tavily"] = types.SimpleNamespace(TavilyClient=object)

if "langchain_core.documents" not in sys.modules:
    langchain_core_module = sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
    documents_module = types.ModuleType("langchain_core.documents")
    documents_module.Document = object
    sys.modules["langchain_core.documents"] = documents_module
    setattr(langchain_core_module, "documents", documents_module)

from landppt.ai.base import AIResponse, MessageRole
from landppt.services.outline.project_outline_streaming_service import ProjectOutlineStreamingService
from landppt.services.runtime.runtime_provider_service import RuntimeProviderService


class _FakeProvider:
    def __init__(self):
        self.chat_calls = []
        self.text_calls = []
        self.stream_chat_calls = []
        self.stream_text_calls = []

    async def chat_completion(self, messages, **kwargs):
        self.chat_calls.append((messages, kwargs))
        return AIResponse(
            content="ok",
            model="fake-model",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
            metadata={"provider": "fake"},
        )

    async def text_completion(self, prompt, **kwargs):
        self.text_calls.append((prompt, kwargs))
        return AIResponse(
            content="text-ok",
            model="fake-model",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
            metadata={"provider": "fake"},
        )

    async def stream_chat_completion(self, messages, **kwargs):
        self.stream_chat_calls.append((messages, kwargs))
        yield "A"
        yield "B"

    async def stream_text_completion(self, prompt, **kwargs):
        self.stream_text_calls.append((prompt, kwargs))
        yield "T"


class _RuntimeStubService:
    user_id = None
    provider_name = None


@pytest.mark.asyncio
async def test_runtime_provider_service_passes_system_prompt_to_chat_completion(monkeypatch):
    provider = _FakeProvider()
    service = RuntimeProviderService(_RuntimeStubService())

    async def _fake_get_role_provider_async(role):
        return provider, {"provider": "openai", "model": "fake-model"}

    async def _fake_user_generation_config():
        return {"temperature": 0.2, "top_p": 0.9}

    monkeypatch.setattr(service, "_get_role_provider_async", _fake_get_role_provider_async)
    monkeypatch.setattr(service, "_get_user_generation_config", _fake_user_generation_config, raising=False)

    await service._text_completion_for_role(
        "outline",
        prompt="请生成大纲",
        system_prompt="只输出 JSON",
    )

    assert not provider.text_calls
    assert len(provider.chat_calls) == 1
    messages, kwargs = provider.chat_calls[0]
    assert [message.role for message in messages] == [MessageRole.SYSTEM, MessageRole.USER]
    assert messages[0].content == "只输出 JSON"
    assert messages[1].content == "请生成大纲"
    assert kwargs["model"] == "fake-model"


@pytest.mark.asyncio
async def test_runtime_provider_service_streaming_passes_system_prompt_to_chat_completion(monkeypatch):
    provider = _FakeProvider()
    service = RuntimeProviderService(_RuntimeStubService())

    async def _fake_get_role_provider_async(role):
        return provider, {"provider": "openai", "model": "fake-model"}

    async def _fake_user_generation_config():
        return {"temperature": 0.2, "top_p": 0.9}

    monkeypatch.setattr(service, "_get_role_provider_async", _fake_get_role_provider_async)
    monkeypatch.setattr(service, "_get_user_generation_config", _fake_user_generation_config, raising=False)

    chunks = []
    async for chunk in service._stream_text_completion_for_role(
        "outline",
        prompt="请生成大纲",
        system_prompt="只输出 JSON",
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "AB"
    assert not provider.stream_text_calls
    assert len(provider.stream_chat_calls) == 1
    messages, kwargs = provider.stream_chat_calls[0]
    assert [message.role for message in messages] == [MessageRole.SYSTEM, MessageRole.USER]
    assert messages[0].content == "只输出 JSON"
    assert messages[1].content == "请生成大纲"
    assert kwargs["model"] == "fake-model"


class _OutlineStreamingStubService:
    def __init__(self):
        self.parsed_content_calls = []

    async def _validate_and_repair_outline_json(self, outline_data, confirmed_requirements):
        return outline_data

    def _parse_outline_content(self, content, project):
        self.parsed_content_calls.append((content, project))
        return {
            "title": project.topic,
            "slides": [
                {
                    "page_number": 1,
                    "title": project.topic,
                    "content_points": ["项目介绍"],
                    "slide_type": "title",
                    "type": "title",
                },
                {
                    "page_number": 2,
                    "title": "核心内容",
                    "content_points": ["要点一", "要点二"],
                    "slide_type": "content",
                    "type": "content",
                },
            ],
            "metadata": {},
        }


@pytest.mark.asyncio
async def test_streaming_outline_parser_uses_json_when_available():
    service = ProjectOutlineStreamingService(_OutlineStreamingStubService())
    project = SimpleNamespace(topic="三体解析")

    outline, used_text_fallback = await service._parse_streaming_outline_content(
        '```json\n{"title":"三体解析","slides":[{"page_number":1,"title":"封面","content_points":["主题"],"slide_type":"title"}]}\n```',
        project,
        {},
    )

    assert used_text_fallback is False
    assert outline["title"] == "三体解析"
    assert len(outline["slides"]) == 1


@pytest.mark.asyncio
async def test_streaming_outline_parser_falls_back_to_text_outline_when_json_is_missing():
    stub = _OutlineStreamingStubService()
    service = ProjectOutlineStreamingService(stub)
    project = SimpleNamespace(topic="三体解析")

    outline, used_text_fallback = await service._parse_streaming_outline_content(
        'Topic: 三体解析\nPage 1: Title Page.\nPage 2: Agenda.\nPage 3: Conclusion.',
        project,
        {},
    )

    assert used_text_fallback is True
    assert outline["title"] == "三体解析"
    assert len(outline["slides"]) == 2
    assert len(stub.parsed_content_calls) == 1
