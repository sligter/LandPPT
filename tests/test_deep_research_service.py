import os
import sys
import types

import pytest


os.environ["DEBUG"] = "false"


if "tavily" not in sys.modules:
    fake_tavily = types.ModuleType("tavily")

    class _BootstrapTavilyClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def search(self, **kwargs):
            return {"results": []}

    fake_tavily.TavilyClient = _BootstrapTavilyClient
    sys.modules["tavily"] = fake_tavily


from landppt.services import deep_research_service as drs
from landppt.services.deep_research_service import (
    DEEPResearchService,
    _is_tavily_auth_error,
    _normalize_secret_value,
)


def test_normalize_secret_value_filters_empty_and_masked_values():
    assert _normalize_secret_value(None) is None
    assert _normalize_secret_value("") is None
    assert _normalize_secret_value("   ") is None
    assert _normalize_secret_value("********") is None
    assert _normalize_secret_value("  tvly-good  ") == "tvly-good"


def test_is_tavily_auth_error_matches_common_messages():
    assert _is_tavily_auth_error(Exception("Unauthorized: missing or invalid API key.")) is True
    assert _is_tavily_auth_error(Exception("invalid_api_key")) is True
    assert _is_tavily_auth_error(Exception("timeout")) is False


@pytest.mark.asyncio
async def test_tavily_search_retries_next_key_on_auth_error(monkeypatch):
    service = DEEPResearchService()

    async def fake_candidates():
        return [
            ("user database override", "bad-key"),
            ("system database default", "good-key"),
        ]

    class FakeTavilyClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def search(self, **kwargs):
            if self.api_key == "bad-key":
                raise Exception("Unauthorized: missing or invalid API key.")
            return {
                "results": [
                    {
                        "title": "SkillNet",
                        "url": "https://example.com",
                        "content": "ok",
                        "score": 0.9,
                        "published_date": "2026-03-08",
                    }
                ]
            }

    monkeypatch.setattr(service, "_get_tavily_api_key_candidates_async", fake_candidates)
    monkeypatch.setattr(drs, "TavilyClient", FakeTavilyClient)
    monkeypatch.setattr(drs.ai_config, "tavily_include_domains", None, raising=False)
    monkeypatch.setattr(drs.ai_config, "tavily_exclude_domains", None, raising=False)

    results = await service._tavily_search("SkillNet", "zh")

    assert results == [
        {
            "title": "SkillNet",
            "url": "https://example.com",
            "content": "ok",
            "score": 0.9,
            "published_date": "2026-03-08",
        }
    ]
    assert service._active_tavily_key_source == "system database default"
