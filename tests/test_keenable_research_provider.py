"""Opt-in Keenable research provider: public title header, keyed endpoint, default unchanged."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from landppt.services.research.keenable_provider import (
    APP_TITLE,
    KEYED_SEARCH_URL,
    PUBLIC_SEARCH_URL,
    KeenableContentProvider,
)


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def text(self):
        return "ok"

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _session(response):
    session = MagicMock()
    session.post.return_value = response
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


def test_normalize_results_maps_snippet_and_skips_blank_urls():
    payload = {
        "results": [
            {"title": "A", "url": "https://a.example", "snippet": "body A"},
            {"title": "Missing"},
            {"title": "B", "link": "https://b.example", "content": "body B"},
        ]
    }
    out = KeenableContentProvider._normalize_results(payload, max_results=10)
    assert out == [
        {"title": "A", "url": "https://a.example", "content": "body A"},
        {"title": "B", "url": "https://b.example", "content": "body B"},
    ]


def test_search_uses_public_endpoint_and_title_header_without_a_key(monkeypatch):
    from landppt.core.config import ai_config

    monkeypatch.setattr(ai_config, "keenable_api_key", None)
    monkeypatch.setattr(ai_config, "keenable_max_results", 5)
    monkeypatch.setattr(ai_config, "keenable_timeout", 20)
    provider = KeenableContentProvider()
    provider._load_user_config = AsyncMock(return_value={})
    response = _FakeResponse(
        {"results": [{"title": "A", "url": "https://a.example", "snippet": "body A"}]}
    )
    session = _session(response)

    with (
        patch("landppt.services.research.keenable_provider.aiohttp.ClientSession", return_value=session),
        patch("landppt.services.research.keenable_provider.aiohttp.ClientTimeout", return_value=SimpleNamespace()),
    ):
        out = asyncio.run(provider.search("hello"))

    assert out == [{"title": "A", "url": "https://a.example", "content": "body A"}]
    assert session.post.call_args.args[0] == PUBLIC_SEARCH_URL
    headers = session.post.call_args.kwargs["headers"]
    assert headers["X-Keenable-Title"] == APP_TITLE
    assert "X-API-Key" not in headers
    assert session.post.call_args.kwargs["json"] == {"query": "hello", "max_results": 5}


def test_search_uses_keyed_endpoint_when_a_key_is_configured(monkeypatch):
    from landppt.core.config import ai_config

    monkeypatch.setattr(ai_config, "keenable_api_key", "secret-key")
    monkeypatch.setattr(ai_config, "keenable_max_results", 3)
    monkeypatch.setattr(ai_config, "keenable_timeout", 20)
    provider = KeenableContentProvider()
    provider._load_user_config = AsyncMock(return_value={})
    session = _session(_FakeResponse({"results": []}))

    with (
        patch("landppt.services.research.keenable_provider.aiohttp.ClientSession", return_value=session),
        patch("landppt.services.research.keenable_provider.aiohttp.ClientTimeout", return_value=SimpleNamespace()),
    ):
        asyncio.run(provider.search("hello"))

    assert session.post.call_args.args[0] == KEYED_SEARCH_URL
    headers = session.post.call_args.kwargs["headers"]
    assert headers["X-API-Key"] == "secret-key"
    assert headers["X-Keenable-Title"] == APP_TITLE


def test_enhanced_research_keenable_is_available_without_tavily(monkeypatch):
    from landppt.core.config import ai_config
    from landppt.services.research.enhanced_research_service import EnhancedResearchService

    monkeypatch.setattr(ai_config, "tavily_api_key", None)
    monkeypatch.setattr(EnhancedResearchService, "ai_provider", property(lambda self: object()))
    service = EnhancedResearchService()
    monkeypatch.setattr(service.deep_research_service, "is_tavily_available", lambda: False)
    monkeypatch.setattr(service.deepseek_provider, "is_available", lambda: False)
    monkeypatch.setattr(service.searxng_provider, "is_available", lambda: False)
    monkeypatch.setattr(service.deep_research_service, "_get_research_provider_sync", lambda: "tavily")

    assert service.get_available_providers() == []
    assert service.is_available() is False

    monkeypatch.setattr(service.deep_research_service, "_get_research_provider_sync", lambda: "keenable")
    assert service.is_available() is True
    assert service.get_available_providers() == ["keenable"]


def test_settings_use_saved_system_key_without_a_user(monkeypatch):
    """The standalone research API has no user; it must still read the admin's saved settings."""
    from landppt.core.config import ai_config

    monkeypatch.setattr(ai_config, "keenable_api_key", None)
    monkeypatch.setattr(ai_config, "keenable_max_results", 7)
    monkeypatch.setattr(ai_config, "keenable_timeout", 15)
    db = MagicMock()
    db.get_all_config = AsyncMock(return_value={"keenable_api_key": "saved-key"})
    with patch("landppt.services.db_config_service.get_db_config_service", return_value=db):
        provider = KeenableContentProvider()
        settings = provider._settings(asyncio.run(provider._load_user_config()))

    db.get_all_config.assert_awaited_once_with(user_id=None)
    assert settings == {"api_key": "saved-key", "max_results": 7, "timeout": 15}


def test_settings_precedence_saved_then_environment(monkeypatch):
    from landppt.core.config import ai_config

    monkeypatch.setattr(ai_config, "keenable_api_key", "env-key")
    monkeypatch.setattr(ai_config, "keenable_max_results", 4)
    monkeypatch.setattr(ai_config, "keenable_timeout", 12)
    provider = KeenableContentProvider(user_id=1)

    # Nothing saved: the environment wins.
    assert provider._settings({"keenable_api_key": None, "keenable_max_results": None, "keenable_timeout": None}) == {
        "api_key": "env-key", "max_results": 4, "timeout": 12,
    }
    # Saved values win over the environment; a masked key falls back to the environment key.
    assert provider._settings({"keenable_api_key": "********", "keenable_max_results": 9, "keenable_timeout": 30}) == {
        "api_key": "env-key", "max_results": 9, "timeout": 30,
    }


def test_schema_defaults_follow_the_environment():
    from landppt.core.config import ai_config
    from landppt.services.db_config_service import DatabaseConfigService

    schema = DatabaseConfigService().config_schema
    assert schema["keenable_max_results"]["default"] == str(ai_config.keenable_max_results)
    assert schema["keenable_timeout"]["default"] == str(ai_config.keenable_timeout)


def _report():
    return SimpleNamespace(
        topic="t", language="zh", executive_summary="s", key_findings=["k"], recommendations=["r"],
        total_duration=1.0, sources=["https://a.example"], steps=[object(), object()],
    )


def test_research_page_endpoints_honor_keenable(monkeypatch):
    from landppt.api import landppt_api

    enhanced = MagicMock()
    enhanced.is_available.return_value = True
    enhanced.get_status.return_value = {"service": "enhanced_research"}
    enhanced.conduct_enhanced_research = AsyncMock(return_value=_report())
    legacy = MagicMock()
    legacy._get_research_provider_sync.return_value = "keenable"
    legacy.is_available.return_value = False
    generator = MagicMock()
    generator.save_report_to_file.return_value = "research_reports/t.md"
    monkeypatch.setattr(landppt_api, "get_research_service", lambda: legacy)
    monkeypatch.setattr(landppt_api, "get_enhanced_research_service", lambda: enhanced)
    monkeypatch.setattr(landppt_api, "get_enhanced_report_generator", lambda: generator)

    status = asyncio.run(landppt_api.get_research_status())
    assert status["available"] is True
    assert status["research_provider"] == "keenable"

    result = asyncio.run(landppt_api.conduct_research("t", "zh"))
    enhanced.conduct_enhanced_research.assert_awaited_once_with("t", "zh")
    legacy.conduct_deep_research.assert_not_called()
    assert result["report"]["sources_count"] == 1
    assert result["report"]["steps_count"] == 2
    assert result["report_path"] == "research_reports/t.md"


def test_research_page_keeps_the_legacy_service_for_other_providers(monkeypatch):
    from landppt.api import landppt_api

    legacy = MagicMock()
    legacy._get_research_provider_sync.return_value = "tavily"
    legacy.is_available.return_value = True
    legacy.get_status.return_value = {"deepseek_available": False}
    enhanced = MagicMock()
    monkeypatch.setattr(landppt_api, "get_research_service", lambda: legacy)
    monkeypatch.setattr(landppt_api, "get_enhanced_research_service", lambda: enhanced)

    status = asyncio.run(landppt_api.get_research_status())
    assert status["available"] is True
    assert "research_provider" not in status
    enhanced.is_available.assert_not_called()
