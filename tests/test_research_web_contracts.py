"""The existing research API accepts query parameters and returns display fields."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from landppt.api import landppt_api as routes


@pytest.mark.asyncio
async def test_research_query_parameters_and_display_result(monkeypatch):
    report = SimpleNamespace(
        topic="教育 + 研究 & 趋势",
        language="zh",
        executive_summary="摘要",
        key_findings=["发现"],
        recommendations=["建议"],
        total_duration=1.5,
        sources=[],
        steps=[{}],
    )
    service = SimpleNamespace(
        is_available=lambda: True, conduct_deep_research=AsyncMock(return_value=report)
    )
    monkeypatch.setattr(routes, "get_research_service", lambda user_id=None: service)
    monkeypatch.setattr(routes, "get_report_generator", lambda: None)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/research/conduct", params=dict(topic=report.topic, language="zh")
        )
    assert response.status_code == 200
    service.conduct_deep_research.assert_awaited_once_with(report.topic, "zh")
    assert response.json()["report"] == dict(
        topic=report.topic,
        language="zh",
        executive_summary="摘要",
        key_findings=["发现"],
        recommendations=["建议"],
        total_duration=1.5,
        sources_count=0,
        steps_count=1,
    )


@pytest.mark.asyncio
async def test_old_form_body_cannot_supply_required_research_topic():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/research/conduct", data=dict(topic="教育研究", language="zh")
        )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "topic"]
