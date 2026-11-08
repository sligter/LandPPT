import sys
import types
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

# 这些模块是研究链路的可选依赖，本测试只验证大纲与运行时逻辑，缺失时用最小桩避免导入失败。
if "bs4" not in sys.modules and importlib.util.find_spec("bs4") is None:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object, Comment=object)

if "tavily" not in sys.modules and importlib.util.find_spec("tavily") is None:
    sys.modules["tavily"] = types.SimpleNamespace(TavilyClient=object)

if "langchain_core.documents" not in sys.modules and importlib.util.find_spec("langchain_core") is None:
    langchain_core_module = sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
    documents_module = types.ModuleType("langchain_core.documents")
    documents_module.Document = object
    sys.modules["langchain_core.documents"] = documents_module
    setattr(langchain_core_module, "documents", documents_module)

from landppt.ai.base import AIResponse, MessageRole
from landppt.services.outline.project_outline_research_service import ProjectOutlineResearchService
from landppt.services.outline.project_outline_streaming_service import ProjectOutlineStreamingService
from landppt.services.runtime import runtime_research_service as runtime_research_module
from landppt.services.runtime.runtime_provider_service import RuntimeProviderService
from landppt.services.runtime.runtime_research_service import RuntimeResearchService
from landppt.services.prompts.system_prompts import SystemPrompts


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


class _RuntimeResearchSupportStub:
    def __init__(self, owner):
        self._service = owner

    def __getattr__(self, name):
        return getattr(self._service, name)


class _FakeEnhancedResearchService:
    def __init__(self, user_id=None):
        self.user_id = user_id

    def get_available_providers(self):
        return ["fake-enhanced"]

    def is_available(self):
        return True


class _FakeEnhancedReportGenerator:
    def __init__(self, reports_dir="research_reports"):
        self.reports_dir = reports_dir


class _FakeLegacyResearchService:
    def __init__(self, user_id=None):
        self.user_id = user_id

    def is_available(self):
        return True


class _FakeLegacyReportGenerator:
    def __init__(self, reports_dir="research_reports"):
        self.reports_dir = reports_dir


def test_runtime_research_service_initializes_research_attrs_on_owner(monkeypatch):
    owner = SimpleNamespace(user_id=42)
    support = _RuntimeResearchSupportStub(owner)
    service = RuntimeResearchService(support)

    fake_deep_module = types.ModuleType("landppt.services.deep_research_service")
    fake_deep_module.DEEPResearchService = _FakeLegacyResearchService
    fake_report_module = types.ModuleType("landppt.services.research_report_generator")
    fake_report_module.ResearchReportGenerator = _FakeLegacyReportGenerator

    monkeypatch.setattr(
        runtime_research_module,
        "EnhancedResearchService",
        _FakeEnhancedResearchService,
    )
    monkeypatch.setattr(
        runtime_research_module,
        "EnhancedReportGenerator",
        _FakeEnhancedReportGenerator,
    )
    monkeypatch.setitem(sys.modules, "landppt.services.deep_research_service", fake_deep_module)
    monkeypatch.setitem(sys.modules, "landppt.services.research_report_generator", fake_report_module)

    service._initialize_research_services()

    assert isinstance(owner.enhanced_research_service, _FakeEnhancedResearchService)
    assert isinstance(owner.enhanced_report_generator, _FakeEnhancedReportGenerator)
    assert isinstance(owner.research_service, _FakeLegacyResearchService)
    assert isinstance(owner.report_generator, _FakeLegacyReportGenerator)
    assert service.enhanced_research_service is owner.enhanced_research_service
    assert service._get_preferred_outline_research_runtime()["service"] is owner.enhanced_research_service


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
    assert messages[0].content == SystemPrompts.with_cache_prefix("只输出 JSON")
    assert messages[1].content == "请生成大纲"
    assert kwargs["model"] == "fake-model"


@pytest.mark.asyncio
async def test_anthropic_outline_preserves_provider_response(monkeypatch):
    provider = _FakeProvider()
    response = AIResponse(
        content="partial outline",
        model="claude-sonnet-test",
        usage={"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
        finish_reason="max_tokens",
        metadata={"provider": "anthropic"},
    )

    async def text_completion(prompt, **kwargs):
        provider.text_calls.append((prompt, kwargs))
        return response

    service = RuntimeProviderService(_RuntimeStubService())

    async def get_provider(role):
        return provider, {"provider": "anthropic", "model": "claude-sonnet-test"}

    monkeypatch.setattr(provider, "text_completion", text_completion)
    monkeypatch.setattr(service, "_get_role_provider_async", get_provider)
    result = await service._text_completion_for_role(
        "outline", prompt="Generate an outline", temperature=0.2, top_p=0.9,
    )

    assert result is response
    assert not provider.stream_text_calls
    assert len(provider.text_calls) == 1
    prompt, kwargs = provider.text_calls[0]
    assert prompt == SystemPrompts.with_text_cache_prefix("Generate an outline")
    assert kwargs["model"] == "claude-sonnet-test"


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
    assert messages[0].content == SystemPrompts.with_cache_prefix("只输出 JSON")
    assert messages[1].content == "请生成大纲"
    assert kwargs["model"] == "fake-model"


class _OutlineStreamingStubService:
    def __init__(self):
        self.parsed_content_calls = []
        self.standardize_calls = []

    async def _validate_and_repair_outline_json(self, outline_data, confirmed_requirements):
        return outline_data

    def _standardize_outline_format(self, outline_data):
        """The streaming parser normalizes locally before validating.

        Local normalization keeps cosmetic variants (a `pages` key, page-number
        gaps) from turning into a chain of blocking LLM repair calls.
        """
        self.standardize_calls.append(outline_data)
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


class _OutlineResearchStubService:
    enhanced_research_service = None
    enhanced_report_generator = None

    def _initialize_research_services(self):
        return None


@pytest.mark.asyncio
async def test_project_outline_research_service_uses_direct_file_processor_import(monkeypatch, tmp_path):
    service = ProjectOutlineResearchService(_OutlineResearchStubService())

    fake_module = types.ModuleType("landppt.services.file_processor")

    class _FakeFileProcessor:
        async def process_file(self, file_path, filename, file_processing_mode=None):
            return SimpleNamespace(
                processed_content=f"{filename}:{file_processing_mode or 'default'}:{file_path}"
            )

    fake_module.FileProcessor = _FakeFileProcessor
    monkeypatch.setitem(sys.modules, "landppt.services.file_processor", fake_module)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    merged_path = await service.conduct_research_and_merge_with_files(
        topic="Test Topic",
        language="zh",
        file_paths=["dummy.txt"],
        context={"file_processing_mode": "markitdown"},
    )

    merged_content = Path(merged_path).read_text(encoding="utf-8")
    assert "dummy.txt" in merged_content
    assert "markitdown" in merged_content
    assert str(tmp_path) in str(Path(merged_path).parent.parent)


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


class _ProjectManagerStub:
    def __init__(self, project):
        self.project = project
        self.projects = {}
        self.status_updates = []
        self.stage_status_updates = []

    async def get_project(self, project_id):
        return self.project

    async def update_project_status(self, project_id, status):
        self.status_updates.append((project_id, status))

    async def update_stage_status(self, project_id, stage_id, status, progress=None, result=None):
        self.stage_status_updates.append((project_id, stage_id, status, progress, result))


class _OutlineStreamingFreshGenerationStubService:
    def __init__(self, project):
        self.project_manager = _ProjectManagerStub(project)
        self.stage_updates = []

    async def _update_outline_generation_stage(self, project_id, outline):
        self.stage_updates.append((project_id, outline))


@pytest.mark.asyncio
async def test_generate_outline_streaming_force_regenerate_skips_saved_outline(monkeypatch):
    project = SimpleNamespace(
        topic="fresh topic",
        outline={
            "title": "cached",
            "slides": [{"page_number": 1, "title": "cached"}],
            "metadata": {"generated_with_file": True},
        },
        confirmed_requirements={"content_source": "file"},
        project_metadata={},
        todo_board=None,
        updated_at=0,
    )
    stub = _OutlineStreamingFreshGenerationStubService(project)
    service = ProjectOutlineStreamingService(stub)
    extract_calls = []

    def _fake_extract_saved_file_outline(project_outline, confirmed_requirements, ignore_saved_outline=False):
        extract_calls.append(ignore_saved_outline)
        return None

    async def _fake_run_streaming_outline_research(project_id, current_project, confirmed_requirements, network_mode):
        yield {
            "outline": {
                "title": "fresh",
                "slides": [{"page_number": 1, "title": "fresh"}],
                "metadata": {"generated_with_file": True},
            },
            "llm_call_count": 0,
        }

    class _FakeDatabaseProjectManager:
        async def save_project_outline(self, project_id, outline):
            return True

    monkeypatch.setattr(
        "landppt.services.file_outline_utils.should_force_file_outline_regeneration",
        lambda confirmed_requirements: False,
    )
    monkeypatch.setattr(
        "landppt.services.file_outline_utils.extract_saved_file_outline",
        _fake_extract_saved_file_outline,
    )
    monkeypatch.setattr(
        "landppt.services.db_project_manager.DatabaseProjectManager",
        _FakeDatabaseProjectManager,
    )
    monkeypatch.setattr(
        service,
        "_run_streaming_outline_research",
        _fake_run_streaming_outline_research,
        raising=False,
    )

    events = []
    async for chunk in service.generate_outline_streaming("project-1", force_regenerate=True):
        events.append(chunk)

    assert extract_calls == [True]
    assert stub.project_manager.status_updates == [("project-1", "in_progress")]
    assert stub.stage_updates
    assert project.outline["title"] == "fresh"
    assert any('"outline"' in chunk and '"fresh"' in chunk for chunk in events)
    assert any('"done": true' in chunk for chunk in events)


@pytest.mark.asyncio
async def test_generate_outline_streaming_replays_saved_outline_without_regeneration(monkeypatch):
    project = SimpleNamespace(
        topic="cached topic",
        outline={
            "title": "cached",
            "slides": [{"page_number": 1, "title": "cached"}],
            "metadata": {},
        },
        confirmed_requirements={"content_source": "manual"},
        project_metadata={},
        todo_board=None,
        updated_at=0,
    )
    stub = _OutlineStreamingFreshGenerationStubService(project)
    service = ProjectOutlineStreamingService(stub)

    async def _unexpected_run_streaming_outline_research(*args, **kwargs):
        raise AssertionError("saved outline should not trigger fresh generation")

    monkeypatch.setattr(
        service,
        "_run_streaming_outline_research",
        _unexpected_run_streaming_outline_research,
        raising=False,
    )

    events = []
    async for chunk in service.generate_outline_streaming("project-1"):
        events.append(chunk)

    assert stub.project_manager.status_updates == []
    assert stub.stage_updates == [("project-1", project.outline)]
    assert any('"step": "cached"' in chunk for chunk in events)
    assert any('"outline"' in chunk and '"cached"' in chunk for chunk in events)
    assert any('"llm_call_count": 0' in chunk for chunk in events)
