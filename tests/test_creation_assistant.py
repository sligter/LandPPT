"""Conversational requirement intake must only ever hand the form validated values."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from landppt.services.creation_assistant import extract_urls, parse_reply, sanitize_fields
from landppt.web.route_modules import creation_assistant_routes as routes

SCENARIOS = ["general", "business"]


def test_sanitize_fields_drops_values_outside_the_form_options():
    fields = sanitize_fields(
        {
            "topic": "  2026 AI 落地计划 ",
            "scenario": "space-opera",
            "audience_type": "公司董事会",
            "page_count_mode": "custom_range",
            "min_pages": "30",
            "max_pages": 2,
            "ppt_style": "custom",
            "language": "fr",
            "network_mode": "true",
            "unattended_mode": True,
        },
        SCENARIOS,
    )
    assert fields == {
        "topic": "2026 AI 落地计划",
        "audience_type": "自定义",
        "custom_audience": "公司董事会",
        "page_count_mode": "custom_range",
        "min_pages": 5,
        "max_pages": 30,
        "network_mode": True,
    }


def test_custom_range_without_page_bounds_is_not_applied():
    assert "page_count_mode" not in sanitize_fields({"page_count_mode": "custom_range"}, SCENARIOS)


def test_parse_reply_only_keeps_links_the_user_actually_sent():
    user_urls = extract_urls(["参考 https://a.example/x。还有 https://b.example/y"])
    assert user_urls == ["https://a.example/x", "https://b.example/y"]
    reply = parse_reply(
        "<think>…</think>```json\n"
        + json.dumps({"reply": "好的", "ready": True, "fields": {"topic": "AI"}, "content_urls": ["https://b.example/y", "https://made.up/z"]})
        + "\n```",
        user_urls,
        SCENARIOS,
    )
    assert reply["ready"] is True
    assert reply["content_urls"] == ["https://b.example/y"]
    assert reply["mentioned_urls"] == user_urls


def test_parse_reply_needs_a_topic_before_it_is_ready():
    text = json.dumps({"reply": "开始吧", "ready": True, "fields": {}})
    assert parse_reply(text, [], SCENARIOS)["ready"] is False
    assert parse_reply(text, [], SCENARIOS, current_topic="已有标题")["ready"] is True


def test_plain_text_reply_keeps_the_conversation_without_touching_fields():
    reply = parse_reply("你想面向哪些受众？", [], SCENARIOS)
    assert reply == {"reply": "你想面向哪些受众？", "ready": False, "fields": {}, "content_urls": [], "mentioned_urls": []}


@pytest.fixture
def client(monkeypatch):
    service = SimpleNamespace(
        get_role_provider_async=AsyncMock(return_value=(None, {"provider": "openai"})),
        _chat_completion_for_role=AsyncMock(
            return_value=SimpleNamespace(content=json.dumps({"reply": "要多少页？", "ready": False, "fields": {"topic": "AI 计划", "language": "en"}}))
        ),
    )
    consume = AsyncMock()
    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda uid: service)
    monkeypatch.setattr(routes, "check_credits_for_operation", AsyncMock(return_value=(True, 1, 10)))
    monkeypatch.setattr(routes, "consume_credits_for_operation", consume)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_current_user_required] = lambda: SimpleNamespace(id=7)
    return SimpleNamespace(client=TestClient(app), service=service, consume=consume)


def test_route_returns_validated_fields_and_charges_one_turn(client):
    response = client.client.post(
        "/api/ai/creation-assistant",
        json={"messages": [{"role": "user", "content": "做个 AI 计划汇报 https://a.example/x"}], "fields": {"topic": ""}},
    )
    assert response.json() == {
        "success": True,
        "reply": "要多少页？",
        "ready": False,
        "fields": {"topic": "AI 计划", "language": "en"},
        "content_urls": ["https://a.example/x"],
        "mentioned_urls": ["https://a.example/x"],
    }
    assert client.service._chat_completion_for_role.await_args.args[0] == "outline"
    client.consume.assert_awaited_once()


def test_route_rejects_turns_that_do_not_end_with_the_user(client, monkeypatch):
    response = client.client.post("/api/ai/creation-assistant", json={"messages": [{"role": "assistant", "content": "你好"}]})
    assert response.json()["success"] is False
    client.service._chat_completion_for_role.assert_not_awaited()


def test_route_stops_when_credits_run_out(client, monkeypatch):
    monkeypatch.setattr(routes, "check_credits_for_operation", AsyncMock(return_value=(False, 1, 0)))
    response = client.client.post("/api/ai/creation-assistant", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.json()["success"] is False
    client.service._chat_completion_for_role.assert_not_awaited()
