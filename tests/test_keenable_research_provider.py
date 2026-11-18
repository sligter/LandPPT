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
    service = EnhancedResearchService()
    monkeypatch.setattr(service.deep_research_service, "is_tavily_available", lambda: False)
    monkeypatch.setattr(service.deepseek_provider, "is_available", lambda: False)
    monkeypatch.setattr(service.searxng_provider, "is_available", lambda: False)
    monkeypatch.setattr(service, "ai_provider", object())
    monkeypatch.setattr(service.deep_research_service, "_get_research_provider_sync", lambda: "tavily")

    assert service.get_available_providers() == []
    assert service.is_available() is False

    monkeypatch.setattr(service.deep_research_service, "_get_research_provider_sync", lambda: "keenable")
    assert service.is_available() is True
    assert service.get_available_providers() == ["keenable"]
