"""DeepSeek Search / Fetch contracts and integration without paid API calls."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.core.config import ai_config
from landppt.services import db_config_service
from landppt.services import deep_research_service as research_module
from landppt.services.deep_research_service import DEEPResearchService
from landppt.services.research import deepseek_provider as module
from landppt.services.research.deepseek_provider import DeepSeekContentProvider
from landppt.services.research.enhanced_research_service import EnhancedResearchService
from landppt.services.research_config import redact_inherited_research_keys
from landppt.services.runtime.runtime_research_service import RuntimeResearchService


@pytest.fixture
def transport(monkeypatch):
    """Record actual aiohttp request arguments and supply HTTP responses."""
    calls = []
    responses = []

    class Response:
        def __init__(self, status, body):
            self.status = status
            self.body = body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def json(self):
            return self.body

    class Session:
        def __init__(self, **kwargs):
            self.options = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def post(self, endpoint, **kwargs):
            calls.append({"endpoint": endpoint, **kwargs, **self.options})
            return Response(*responses.pop(0))

    monkeypatch.setattr(module.aiohttp, "ClientSession", Session)
    provider = DeepSeekContentProvider(user_id=7)
    config = provider._resolve_config(
        {
            "deepseek_api_key": "sk-test",
            "deepseek_base_url": "https://gateway.example/deepseek/v1/",
            "deepseek_max_results": 12,
            "deepseek_timeout": 45,
        }
    )
    monkeypatch.setattr(provider, "get_config", AsyncMock(return_value=config))
    return provider, calls, responses


@pytest.mark.asyncio
async def test_search_uses_documented_endpoint_and_normalizes_evidence(transport):
    provider, calls, responses = transport
    responses.append(
        (
            200,
            {
                "results": [
                    {
                        "title": "研究来源",
                        "url": "https://example.com/report",
                        "snippet": "短摘要",
                        "summary": "用于模型阅读的长摘要",
                        "content": "",
                        "rerank_score": 2.4,
                        "date": "2026-10-28T00:00:00Z",
                        "authority": 3,
                    }
                ]
            },
        )
    )
    results = await provider.search("研究主题", ori_question="用户原始问题")
    assert calls[0]["endpoint"] == "https://gateway.example/deepseek/v1/tools/search"
    assert calls[0]["headers"] == {
        "Authorization": "Bearer sk-test",
        "Content-Type": "application/json",
    }
    assert calls[0]["json"] == {
        "query": "研究主题",
        "count": 12,
        "ori_question": "用户原始问题",
        "need_content": False,
    }
    assert calls[0]["timeout"].total == 45
    assert results[0]["content"] == "用于模型阅读的长摘要"
    assert results[0]["score"] == 2.4
    assert results[0]["published_date"] == "2026-10-28T00:00:00Z"
    assert results[0]["authority"] == 3
    assert results[0]["provider"] == "deepseek"


@pytest.mark.asyncio
async def test_search_content_empty_results_and_count_limits(transport):
    provider, calls, responses = transport
    responses.extend(
        [
            (200, {"results": [{"content": "完整正文", "summary": "摘要"}]}),
            (200, {"results": []}),
        ]
    )
    results = await provider.search("中" * 128, max_results=100, need_content=True)
    assert results[0]["content"] == "完整正文"
    assert calls[0]["json"]["count"] == 50
    assert calls[0]["json"]["need_content"] is True
    assert await provider.search("no matches", max_results=0) == []
    assert calls[1]["json"]["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "  ", "中" * 129])
async def test_invalid_query_is_rejected_before_request(transport, query):
    provider, calls, _ = transport
    with pytest.raises(ValueError, match="1–128"):
        await provider.search(query)
    assert not calls


@pytest.mark.asyncio
async def test_fetch_returns_markdown_and_title(transport):
    provider, calls, responses = transport
    responses.append((200, {"title": "报告", "content": "# 报告\n\n正文"}))
    assert await provider.fetch("https://example.com/report") == {
        "url": "https://example.com/report",
        "title": "报告",
        "content": "# 报告\n\n正文",
    }
    assert calls[0]["endpoint"].endswith("/v1/tools/fetch")
    assert calls[0]["json"] == {"url": "https://example.com/report"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "",
        "file:///etc/passwd",
        "https:///missing-host",
        "https://user:pass@example.com",
        "https://example.com/" + "a" * 8192,
    ],
)
async def test_fetch_validates_documented_url_constraints(transport, url):
    provider, calls, _ = transport
    with pytest.raises(ValueError):
        await provider.fetch(url)
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
async def test_permanent_http_errors_are_not_retried_or_leaked(transport, status):
    provider, calls, responses = transport
    responses.append((status, {"error": {"message": "credential sk-test"}}))
    with pytest.raises(RuntimeError, match=f"HTTP {status}") as exc:
        await provider.search("query")
    assert len(calls) == 1
    assert "sk-test" not in str(exc.value)


@pytest.mark.asyncio
async def test_transient_http_errors_retry_with_backoff(transport, monkeypatch):
    provider, calls, responses = transport
    responses.extend([(429, {}), (504, {}), (200, {"results": []})])
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    assert await provider.search("query") == []
    assert len(calls) == 3
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]


@pytest.mark.asyncio
async def test_config_is_fresh_and_user_scoped_with_environment_fallback(monkeypatch):
    saved = {"deepseek_api_key": "user-key", "deepseek_max_results": 4}
    service = SimpleNamespace(
        get_all_config=AsyncMock(side_effect=lambda **kwargs: dict(saved)),
        get_all_config_sync=lambda **kwargs: dict(saved),
    )
    monkeypatch.setattr(db_config_service, "get_db_config_service", lambda: service)
    monkeypatch.setattr(ai_config, "deepseek_api_key", "env-key")
    provider = DeepSeekContentProvider(user_id=19)
    assert provider.is_available()
    assert (await provider.get_config())["api_key"] == "user-key"
    saved["deepseek_api_key"] = "changed-key"
    assert (await provider.get_config())["api_key"] == "changed-key"
    saved["deepseek_api_key"] = ""
    assert (await provider.get_config())["api_key"] == "env-key"
    service.get_all_config.assert_any_await(user_id=19)
    saved["deepseek_api_key"] = "********"
    assert not provider.is_available()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "own_key,expected_base",
    [
        ("system-key", "https://api.deepseek.com"),
        ("own-key", "https://user-gateway.example"),
        ("", "https://api.deepseek.com"),
    ],
)
async def test_custom_gateway_cannot_receive_inherited_system_key(
    monkeypatch, own_key, expected_base
):
    system = {
        "deepseek_api_key": "system-key",
        "deepseek_base_url": "https://api.deepseek.com",
    }
    saved = {
        **system,
        "deepseek_base_url": "https://user-gateway.example",
        "deepseek_api_key": own_key,
    }
    monkeypatch.setattr(ai_config, "deepseek_api_key", "system-key")
    service = SimpleNamespace(
        get_all_config=AsyncMock(
            side_effect=lambda user_id: saved if user_id == 19 else system
        ),
        get_all_config_sync=lambda user_id: saved if user_id == 19 else system,
    )
    monkeypatch.setattr(db_config_service, "get_db_config_service", lambda: service)
    provider = DeepSeekContentProvider(user_id=19)
    assert (await provider.get_config())["base_url"] == expected_base
    assert provider.get_config_sync()["base_url"] == expected_base


@pytest.mark.asyncio
async def test_react_agent_uses_selected_deepseek_tools_and_sources(
    monkeypatch, transport
):
    provider, calls, responses = transport
    responses.extend(
        [
            (
                200,
                {
                    "results": [
                        {
                            "url": "https://example.com/report",
                            "title": "报告",
                            "summary": "搜索证据",
                        }
                    ]
                },
            ),
            (200, {"title": "报告", "content": "# 正文证据"}),
        ]
    )
    actions = iter(
        [
            {"action": "search", "action_input": {"query": "主题"}},
            {"action": "fetch", "action_input": {"url": "https://example.com/report"}},
            {
                "action": "final",
                "action_input": {
                    "executive_summary": "证据摘要",
                    "key_findings": ["发现"],
                },
            },
        ]
    )
    prompts = []

    class AI:
        async def stream_text_completion(self, prompt, **kwargs):
            prompts.append(prompt)
            yield json.dumps(next(actions), ensure_ascii=False)

    service = DEEPResearchService(user_id=7)
    service.deepseek_provider = provider
    monkeypatch.setattr(
        service, "_get_research_provider_async", AsyncMock(return_value="deepseek")
    )
    monkeypatch.setattr(service, "get_ai_provider_async", AsyncMock(return_value=AI()))
    events = []
    report = await service.conduct_deep_research("主题", event_callback=events.append)
    assert report.executive_summary == "证据摘要"
    assert report.sources == ["https://example.com/report"]
    assert [call["endpoint"].rsplit("/", 1)[1] for call in calls] == ["search", "fetch"]
    assert all("tavily_search" not in prompt for prompt in prompts)
    search_event = next(event for event in events if event["type"] == "search_results")
    assert search_event["provider"] == "deepseek"
    assert search_event["results"][0]["content"] == "搜索证据"


@pytest.mark.asyncio
async def test_enhanced_research_fetches_analyzes_and_cites_deepseek(monkeypatch):
    service = EnhancedResearchService(user_id=7)
    monkeypatch.setattr(ai_config, "research_enable_content_extraction", True)
    monkeypatch.setattr(
        service, "_get_research_provider_async", AsyncMock(return_value="deepseek")
    )
    service.deepseek_provider = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "title": "来源",
                    "url": "https://example.com/report",
                    "content": "长摘要",
                }
            ]
        ),
        fetch=AsyncMock(
            return_value={
                "title": "来源",
                "url": "https://example.com/report",
                "content": "# 完整正文",
            }
        ),
    )
    llm = AsyncMock(return_value="分析结果")
    monkeypatch.setattr(service, "_collect_llm_response", llm)
    monkeypatch.setattr(service, "_search_with_tavily", AsyncMock())
    monkeypatch.setattr(service.content_extractor, "extract_multiple", AsyncMock())
    stats = {"content_extraction": 0}
    events = []
    step = await service._execute_enhanced_research_step(
        1,
        {"query": "查询", "description": "目标"},
        "主题",
        "zh",
        stats,
        event_callback=events.append,
    )
    assert step.completed
    assert step.deepseek_results[0]["content"] == "长摘要"
    assert step.extracted_content[0].content == "# 完整正文"
    assert stats == {"deepseek": 1, "content_extraction": 1}
    assert "DeepSeek搜索结果" in llm.await_args.kwargs["prompt"]
    service._search_with_tavily.assert_not_awaited()
    service.content_extractor.extract_multiple.assert_not_awaited()
    analysis = await service._analyze_collected_content([step], "主题", "zh")
    assert analysis["content_stats"]["deepseek_results"] == 1
    report = await service._generate_enhanced_report(
        "主题", "zh", [step], analysis, 1.0, stats
    )
    assert report.sources == ["https://example.com/report"]
    assert report.provider_stats["deepseek"] == 1
    assert next(e for e in events if e["type"] == "search_results")["deepseek_results"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_admin,override,visible",
    [(False, False, False), (False, True, True), (True, True, False)],
)
async def test_shared_deepseek_key_is_redacted(is_admin, override, visible):
    config = {"deepseek_api_key": "sk-private", "research_provider": "deepseek"}
    result = await redact_inherited_research_keys(
        config,
        SimpleNamespace(id=7, is_admin=is_admin),
        SimpleNamespace(is_user_override=AsyncMock(return_value=override)),
    )
    assert ("deepseek_api_key" in result) is visible
    assert result["deepseek_api_key_configured"] is True
    assert result["deepseek_uses_admin_default"] is (not is_admin and not override)
    assert config["deepseek_api_key"] == "sk-private"


@pytest.mark.asyncio
async def test_environment_deepseek_key_is_reported_without_exposing_it(monkeypatch):
    monkeypatch.setattr(ai_config, "deepseek_api_key", "sk-environment")
    result = await redact_inherited_research_keys(
        {"deepseek_api_key": ""},
        SimpleNamespace(id=7, is_admin=False),
        SimpleNamespace(is_user_override=AsyncMock(return_value=False)),
    )
    assert result["deepseek_api_key_configured"] is True
    assert result["deepseek_uses_admin_default"] is True
    assert "deepseek_api_key" not in result
    assert "sk-environment" not in json.dumps(result)


def test_deepseek_search_results_appear_in_outline_stream():
    service = RuntimeResearchService(SimpleNamespace())
    for event in [
        {
            "provider": "deepseek",
            "results": [
                {
                    "title": "来源",
                    "content": "摘要",
                    "url": "https://example.com/report",
                }
            ],
        },
        {
            "deepseek_results": [
                {
                    "title": "来源",
                    "content": "摘要",
                    "url": "https://example.com/report",
                }
            ]
        },
    ]:
        payloads = service.iter_research_stream_payloads(
            {"type": "search_results", "step_number": 1, **event}
        )
        text = "".join(payload.get("content", "") for payload in payloads)
        assert "DeepSeek 搜索结果" in text
        assert "摘要" in text
        assert "https://example.com/report" in text


def test_deepseek_is_available_without_tavily_and_reports_selected_tools(monkeypatch):
    monkeypatch.setattr(research_module, "get_ai_provider", lambda: object())
    monkeypatch.setattr(ai_config, "tavily_api_key", None)
    service = DEEPResearchService(user_id=7)
    monkeypatch.setattr(service, "_get_research_provider_sync", lambda: "deepseek")
    monkeypatch.setattr(
        service.deepseek_provider,
        "get_config_sync",
        lambda: {
            "api_key": "sk-private",
            "base_url": "https://api.deepseek.com",
            "max_results": 20,
        },
    )
    assert service.is_available()
    assert not service.is_tavily_available()
    status = service.get_status()
    assert status["tools"] == ["deepseek_search", "deepseek_fetch"]
    assert status["research_provider"] == "deepseek"
    assert status["max_results"] == 20
    assert "sk-private" not in json.dumps(status)
    enhanced = EnhancedResearchService(user_id=7)
    enhanced.deep_research_service = service
    enhanced.deepseek_provider = service.deepseek_provider
    monkeypatch.setattr(enhanced, "_ai_provider", object())
    monkeypatch.setattr(enhanced.searxng_provider, "is_available", lambda: False)
    assert enhanced.is_available()
    assert enhanced.get_available_providers() == ["deepseek"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        "get_user_config",
        "get_user_config_by_category",
        "get_all_config",
        "get_config_by_category",
    ],
)
async def test_config_read_endpoints_do_not_expose_inherited_deepseek_key(
    monkeypatch, endpoint
):
    from landppt.api import config_api

    saved = {"deepseek_api_key": "sk-shared", "research_provider": "deepseek"}
    schema = {key: {"category": "generation_params"} for key in saved}
    service = SimpleNamespace(
        get_all_config=AsyncMock(return_value=saved),
        get_all_config_for_user=AsyncMock(return_value=saved),
        get_config_by_category=AsyncMock(return_value=saved),
        get_config_schema=lambda **kwargs: schema,
        is_user_override=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(config_api, "get_db_config_service", lambda: service)
    kwargs = {"user": SimpleNamespace(id=7, is_admin=False)}
    if "category" in endpoint:
        kwargs["category"] = "generation_params"
    result = await getattr(config_api, endpoint)(**kwargs)
    assert "deepseek_api_key" not in result["config"]
    assert result["config"]["deepseek_api_key_configured"] is True
    assert result["config"]["deepseek_uses_admin_default"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin", [True, False])
async def test_deepseek_key_save_uses_correct_scope(monkeypatch, is_admin):
    from landppt.api import config_api

    update = AsyncMock(return_value=True)
    service = SimpleNamespace(
        get_config_schema=lambda: {
            "deepseek_api_key": {"category": "generation_params"},
            "research_provider": {"category": "generation_params"},
        },
        update_config=update,
    )
    monkeypatch.setattr(config_api, "get_db_config_service", lambda: service)
    result = await config_api.update_config_by_category(
        "generation_params",
        config_api.ConfigUpdateRequest(
            config={"deepseek_api_key": "sk-new", "research_provider": "deepseek"}
        ),
        user=SimpleNamespace(id=7, is_admin=is_admin),
    )
    assert result["success"]
    if is_admin:
        assert update.await_args_list[0].args == ({"deepseek_api_key": "sk-new"},)
        assert update.await_args_list[0].kwargs == {"user_id": None}
        assert update.await_args_list[1].args == ({"research_provider": "deepseek"},)
        assert update.await_args_list[1].kwargs == {"user_id": 7}
    else:
        update.assert_awaited_once_with(
            {"deepseek_api_key": "sk-new", "research_provider": "deepseek"}, user_id=7
        )
