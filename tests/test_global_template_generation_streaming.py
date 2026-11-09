"""AI master templates stream real model output without saving partial results."""

import asyncio
import json
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from landppt.api import global_master_template_api as api
from landppt.ai.base import AIProvider
from landppt.services.template.global_master_template_service import (
    GlobalMasterTemplateService,
)
from landppt.web.responses import ClosingStreamingResponse


HTML = "<!DOCTYPE html><html><head><title>母版</title></head><body><h1>{{title}}</h1></body></html>"
REFERENCE = dict(
    filename="ref.png",
    data="data:image/png;base64,Zml4dHVyZQ==",
    size=7,
    type="image/png",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["text_only", "reference_style", "exact_replica", "pptx_extract"]
)
async def test_model_chunks_and_preview_arrive_before_completion_for_all_modes(
    monkeypatch, mode
):
    service = GlobalMasterTemplateService(user_id=42)
    finish = asyncio.Event()
    calls = []
    closed = []

    async def model_stream(messages, **kwargs):
        calls.append(dict(messages=messages, **kwargs))
        try:
            yield "说明\n```html\n" + HTML[: HTML.index("</body>")]
            await finish.wait()
            yield "</body></html>\n```"
        finally:
            closed.append(True)

    provider = SimpleNamespace(
        stream_chat_completion=model_stream, model="template-test"
    )

    async def collect(**kwargs):
        return await AIProvider.collect_streamed_chat_completion(provider, **kwargs)

    provider.collect_streamed_chat_completion = collect
    monkeypatch.setattr(
        service,
        "_get_template_role_provider_async",
        AsyncMock(return_value=(provider, {"model": "template-test"})),
    )
    hosting = AsyncMock(
        side_effect=lambda image: "https://assets.test/" + image["filename"]
    )
    monkeypatch.setattr(service, "_prompt_safe_image_url_from_reference", hosting)
    extraction = AsyncMock(
        return_value={
            "analysis_summary": "提取的母版风格",
            "reference_image": {**REFERENCE, "filename": "slide1.png"},
            "extra_reference_images": [{**REFERENCE, "filename": "slide2.png"}],
        }
    )
    monkeypatch.setattr(service, "_extract_pptx_template_reference", extraction)
    kwargs = dict(
        prompt="简洁商务设计",
        template_name="流式母版",
        generation_mode=mode,
        tags=["商务"],
    )
    if mode == "pptx_extract":
        kwargs["reference_pptx"] = dict(filename="reference.pptx", data="fixture")
    elif mode != "text_only":
        kwargs["reference_images"] = [REFERENCE, {**REFERENCE, "filename": "ref2.png"}]
    async with aclosing(service.generate_template_with_ai_stream(**kwargs)) as stream:
        events = []
        while not any(event["type"] == "preview" for event in events):
            events.append(await asyncio.wait_for(anext(stream), 2))
        assert any(event["type"] == "thinking" for event in events)
        assert not any(event["type"] == "complete" for event in events)
        assert "<h1>" in events[-1]["html_template"]
        assert not finish.is_set()
        finish.set()
        events.extend([event async for event in stream])
    assert events[-1]["type"] == "complete"
    assert events[-1]["html_template"] == HTML
    assert events[-1]["template_name"] == "流式母版"
    assert events[-1]["tags"] == ["商务"]
    assert len(calls) == 1 and calls[0]["model"] == "template-test"
    assert closed == [True]
    content = calls[0]["messages"][-1].content
    images = [part.image_url["url"] for part in content if hasattr(part, "image_url")]
    assert len(images) == (0 if mode == "text_only" else 2)
    assert all(url.startswith("https://assets.test/") for url in images)
    assert extraction.await_count == (1 if mode == "pptx_extract" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty", "provider"])
async def test_service_failure_never_emits_completion(monkeypatch, failure):
    service = GlobalMasterTemplateService(user_id=42)

    async def model_stream(messages, **kwargs):
        if failure == "provider":
            yield HTML[:65]
            raise RuntimeError("模型连接断开")
        yield ""

    provider = SimpleNamespace(
        stream_chat_completion=model_stream, model="template-test"
    )

    async def collect(**kwargs):
        return await AIProvider.collect_streamed_chat_completion(provider, **kwargs)

    provider.collect_streamed_chat_completion = collect
    monkeypatch.setattr(
        service,
        "_get_template_role_provider_async",
        AsyncMock(return_value=(provider, {})),
    )
    events = [
        event
        async for event in service.generate_template_with_ai_stream("设计", "母版")
    ]
    assert events[-1]["type"] == "error"
    assert not any(event["type"] == "complete" for event in events)


@pytest.mark.asyncio
async def test_heartbeat_does_not_cancel_model_and_success_is_billed_once():
    finish, closed = asyncio.Event(), asyncio.Event()

    async def source():
        try:
            await finish.wait()
            yield {"type": "complete", "html_template": HTML}
            pytest.fail("must stop after completion")
        finally:
            closed.set()

    billed = AsyncMock()
    async with aclosing(
        api._template_generation_events(source(), billed, heartbeat_seconds=0.01)
    ) as stream:
        assert "status" in await anext(stream)
        assert await anext(stream) == ": heartbeat\n\n"
        assert await anext(stream) == ": heartbeat\n\n"
        assert not closed.is_set() and billed.await_count == 0
        finish.set()
        assert "complete" in await anext(stream)
    assert closed.is_set() and billed.await_count == 1


@pytest.mark.asyncio
async def test_disconnect_cancels_waiting_upstream_without_billing():
    closed = asyncio.Event()

    async def source():
        try:
            await asyncio.Event().wait()
            yield {"type": "complete"}
        finally:
            closed.set()

    billed = AsyncMock()
    stream = api._template_generation_events(source(), billed, heartbeat_seconds=0.01)
    await anext(stream)
    assert "heartbeat" in await anext(stream)
    await stream.aclose()
    assert closed.is_set() and billed.await_count == 0


@pytest.mark.asyncio
async def test_http_disconnect_closes_model_iterator():
    waiting, closed = asyncio.Event(), asyncio.Event()

    async def source():
        try:
            yield {"type": "thinking", "content": HTML[:65]}
            waiting.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    async def receive():
        await waiting.wait()
        return {"type": "http.disconnect"}

    sent = []

    async def send(message):
        sent.append(message)

    billed = AsyncMock()
    response = ClosingStreamingResponse(
        api._template_generation_events(source(), billed),
        media_type="text/event-stream",
    )
    await asyncio.wait_for(
        response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), 2
    )
    assert closed.is_set() and billed.await_count == 0
    assert any(b'"type": "thinking"' in event.get("body", b"") for event in sent)


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", [None, "length"])
async def test_openai_incomplete_completion_is_not_accepted_as_a_template(
    monkeypatch, finish
):
    from test_package_streaming_completion import SSEBody, streaming_runtime

    body = SSEBody(finish=finish)
    service = GlobalMasterTemplateService(user_id=42)
    async with streaming_runtime(body) as (_, provider, requests):
        monkeypatch.setattr(
            service,
            "_get_template_role_provider_async",
            AsyncMock(return_value=(provider, {"model": "test"})),
        )
        events = [
            event
            async for event in service.generate_template_with_ai_stream("设计", "母版")
        ]
    assert events[-1]["type"] == "error"
    assert not any(event["type"] == "complete" for event in events)
    assert len(requests) == 1 and requests[0]["stream"] is True
    assert body.closed


@pytest.fixture
def generation_api(monkeypatch):
    state = dict(calls=[], bills=[], balance=50, failure=None)

    class Service:
        def __init__(self, user_id):
            assert user_id == 42

        async def _get_template_role_provider_async(self):
            return None, {"provider": "landppt"}

        async def generate_template_with_ai(self, **kwargs):
            state["calls"].append(("json", kwargs))
            return dict(html_template=HTML, template_name=kwargs["template_name"])

        async def generate_template_with_ai_stream(self, **kwargs):
            state["calls"].append(("stream", kwargs))
            yield dict(type="thinking", content=HTML[:65])
            if state["failure"] == "eof":
                return
            if state["failure"] == "error":
                raise ValueError("模型失败")
            yield dict(type="preview", html_template=HTML[:65])
            yield dict(
                type="complete",
                html_template=HTML,
                template_name=kwargs["template_name"],
            )

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Credits:
        def __init__(self, session):
            pass

        def get_operation_cost(self, *args):
            return 10

        async def get_balance(self, user_id):
            return state["balance"]

        async def consume_credits(self, **kwargs):
            state["bills"].append(kwargs)

    monkeypatch.setattr(api, "GlobalMasterTemplateService", Service)
    monkeypatch.setattr(api, "AsyncSessionLocal", Session)
    monkeypatch.setattr(api, "CreditsService", Credits)
    monkeypatch.setattr(api.app_config, "enable_credits_system", True)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_current_user_required] = lambda: SimpleNamespace(
        id=42
    )
    return app, state


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["query", "accept", "json"])
async def test_generation_endpoint_stream_negotiation_and_legacy_json(
    generation_api, transport
):
    app, state = generation_api
    payload = dict(
        prompt="设计",
        template_name="母版",
        generation_mode="reference_style",
        reference_images=[REFERENCE],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/global-master-templates/generate"
            + ("?stream=true" if transport == "query" else ""),
            json=payload,
            headers={
                "Accept": (
                    "text/event-stream" if transport == "accept" else "application/json"
                )
            },
        )
    assert response.status_code == 200
    assert len(state["bills"]) == 1 and state["bills"][0]["user_id"] == 42
    assert state["calls"][0][1]["reference_images"] == [REFERENCE]
    if transport == "json":
        assert response.json()["data"]["html_template"] == HTML
        assert state["calls"][0][0] == "json"
    else:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        events = [
            json.loads(block[6:]) for block in response.text.strip().split("\n\n")
        ]
        assert [event["type"] for event in events] == [
            "status",
            "thinking",
            "preview",
            "complete",
        ]
        assert state["calls"][0][0] == "stream"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "eof", "credits"])
async def test_failed_generations_are_not_billed(generation_api, failure):
    app, state = generation_api
    state["failure"] = failure
    if failure == "credits":
        state["balance"] = 0
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/global-master-templates/generate?stream=true",
            json=dict(prompt="设计", template_name="母版"),
        )
    assert not state["bills"]
    if failure == "credits":
        assert not state["calls"] and response.json()["success"] is False
    else:
        assert '"type": "error"' in response.text
        assert '"type": "complete"' not in response.text
