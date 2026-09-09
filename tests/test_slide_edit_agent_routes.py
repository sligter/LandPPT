from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from landppt.services.slide.slide_edit_agent_service import (
    SlideEditAgentApplyRequest,
    SlideEditAgentCancelRequest,
    SlideEditAgentRequest,
    agent_run_registry,
    compute_slide_html_hash,
)
from landppt.web.route_modules import slide_edit_agent_routes as routes


class _FakeProjectManager:
    def __init__(self, project):
        self.project = project

    async def get_project(self, project_id, user_id=None):
        return self.project


class _FakePPTService:
    def __init__(self, project=None, providers=None):
        self.project_manager = _FakeProjectManager(project)
        self.providers = providers or {}
        self.roles = []

    async def get_role_provider_async(self, role):
        self.roles.append(role)
        return None, {"provider": self.providers.get(role, "landppt")}


async def _collect_stream_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        chunks.append(chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_apply_agent_proposal_rejects_base_hash_mismatch(monkeypatch):
    project = SimpleNamespace(
        slides_data=[
            {
                "title": "One",
                "html_content": "<div>Current</div>",
                "is_user_edited": False,
            }
        ]
    )
    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash("<div>Old</div>"),
        htmlContent="<div>New</div>",
        slideData={"title": "One"},
    )

    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(
            request, user=SimpleNamespace(id=10)
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_agent_proposal_saves_only_target_slide(monkeypatch):
    current_html = '<div style="width:1280px;height:720px"><h1>Current</h1></div>'
    project = SimpleNamespace(
        slides_data=[
            {"title": "One", "html_content": current_html, "is_user_edited": False},
            {
                "title": "Two",
                "html_content": "<div>Second</div>",
                "is_user_edited": False,
            },
        ]
    )
    saved = {}

    class _FakeDBManager:
        async def save_single_slide(self, project_id, slide_index, slide_data):
            saved["project_id"] = project_id
            saved["slide_index"] = slide_index
            saved["slide_data"] = slide_data
            return True

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )
    monkeypatch.setattr(routes, "DatabaseProjectManager", lambda: _FakeDBManager())

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html),
        htmlContent='<div style="width:1280px;height:720px"><h1>New</h1></div>',
        slideData={"title": "One"},
    )

    result = await routes.apply_slide_edit_agent_proposal(
        request, user=SimpleNamespace(id=10)
    )

    assert result["success"] is True
    assert saved["project_id"] == "proj"
    assert saved["slide_index"] == 0
    assert saved["slide_data"]["title"] == "One"
    assert "New" in saved["slide_data"]["html_content"]
    assert saved["slide_data"]["is_user_edited"] is True


@pytest.mark.asyncio
async def test_apply_layout_edit_preserves_server_stored_scripts(monkeypatch):
    from bs4 import BeautifulSoup

    current_html = (
        '<html><head><script src="/static/chart.js"></script></head><body>'
        '<h1 style="height:100px">Title</h1><canvas id="chart"></canvas>'
        '<script data-quick-ai-id="script-1">drawChart()</script></body></html>'
    )
    project = SimpleNamespace(slides_data=[{"title": "One", "html_content": current_html}])
    saved = {}

    class DB:
        async def save_single_slide(self, project_id, slide_index, data):
            saved.update(data)
            return True

    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda uid: _FakePPTService(project))
    monkeypatch.setattr(routes, "DatabaseProjectManager", DB)
    request = SlideEditAgentApplyRequest(
        proposalId="p1", projectId="proj", slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html),
        htmlContent=current_html.replace("height:100px", "height:120px"),
    )
    result = await routes.apply_slide_edit_agent_proposal(request, user=SimpleNamespace(id=10))
    assert result["success"]
    html = saved["html_content"]
    assert "height:120px" in html
    scripts = BeautifulSoup(html, "html.parser").find_all("script")
    assert len(scripts) == 2
    assert scripts[0]["src"] == "/static/chart.js"
    assert scripts[1].string == "drawChart()"
    assert "data-quick-ai-id" not in html


@pytest.mark.asyncio
async def test_apply_layout_edit_preserves_server_stored_event_handlers(monkeypatch):
    current_html = (
        '<div><h1 style="height:100px">Title</h1>'
        '<button onclick="showTab(1)">Tab</button></div>'
    )
    project = SimpleNamespace(slides_data=[{"title": "One", "html_content": current_html}])
    saved = {}

    class DB:
        async def save_single_slide(self, project_id, slide_index, data):
            saved.update(data)
            return True

    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda uid: _FakePPTService(project))
    monkeypatch.setattr(routes, "DatabaseProjectManager", DB)

    def make_request(html):
        return SlideEditAgentApplyRequest(
            proposalId="p1", projectId="proj", slideIndex=1,
            expectedBaseHash=compute_slide_html_hash(current_html), htmlContent=html,
        )

    edited = current_html.replace("height:100px", "height:120px")
    result = await routes.apply_slide_edit_agent_proposal(make_request(edited), user=SimpleNamespace(id=10))
    assert result["success"]
    assert "height:120px" in saved["html_content"]
    assert 'onclick="showTab(1)"' in saved["html_content"]

    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(
            make_request(edited.replace("showTab(1)", "steal()")), user=SimpleNamespace(id=10)
        )
    assert "inline event handlers are not allowed" in exc.value.detail["errors"]


@pytest.mark.asyncio
async def test_apply_accepts_preview_dom_that_lost_sri_metadata(monkeypatch):
    # 快速编辑弹窗的草稿来自预览 iframe，预览渲染前会剥掉 integrity/crossorigin。
    current_html = (
        '<html><head><script src="https://cdn.example.com/chart.js" '
        'integrity="sha384-abc" crossorigin="anonymous"></script></head>'
        '<body><h1 style="height:100px">Title</h1></body></html>'
    )
    submitted = (
        '<html><head><script src="https://cdn.example.com/chart.js"></script></head>'
        '<body><h1 style="height:120px">Title</h1></body></html>'
    )
    project = SimpleNamespace(slides_data=[{"title": "One", "html_content": current_html}])
    saved = {}

    class DB:
        async def save_single_slide(self, project_id, slide_index, data):
            saved.update(data)
            return True

    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda uid: _FakePPTService(project))
    monkeypatch.setattr(routes, "DatabaseProjectManager", DB)
    request = SlideEditAgentApplyRequest(
        proposalId="p1", projectId="proj", slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html), htmlContent=submitted,
    )
    result = await routes.apply_slide_edit_agent_proposal(request, user=SimpleNamespace(id=10))
    assert result["success"]
    assert "height:120px" in saved["html_content"]
    assert 'src="https://cdn.example.com/chart.js"' in saved["html_content"]

    request.htmlContent = submitted.replace("chart.js", "evil.js")
    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(request, user=SimpleNamespace(id=10))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("baseline", ["<div>Title</div>", '<div>Title<script src="/old.js"></script></div>'])
async def test_apply_cannot_use_client_slide_data_to_authorize_scripts(monkeypatch, baseline):
    project = SimpleNamespace(slides_data=[{"html_content": baseline}])
    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda uid: _FakePPTService(project))
    changed = '<div>Edited<script src="/new.js"></script></div>'
    request = SlideEditAgentApplyRequest(
        proposalId="p1", projectId="proj", slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(baseline), htmlContent=changed,
        slideData={"html_content": changed, "baseline_html": changed},
    )
    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(request, user=SimpleNamespace(id=10))
    assert exc.value.status_code == 400
    assert "script tags are not allowed" in exc.value.detail["errors"]


@pytest.mark.asyncio
async def test_apply_agent_proposal_strips_agent_ids_before_save(monkeypatch):
    current_html = '<div style="width:1280px;height:720px"><h1>Current</h1></div>'
    project = SimpleNamespace(
        slides_data=[
            {"title": "One", "html_content": current_html, "is_user_edited": False}
        ]
    )
    saved = {}

    class _FakeDBManager:
        async def save_single_slide(self, project_id, slide_index, slide_data):
            saved["slide_data"] = slide_data
            return True

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )
    monkeypatch.setattr(routes, "DatabaseProjectManager", lambda: _FakeDBManager())

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html),
        htmlContent=(
            '<div data-agent-id="a1" data-quick-ai-id="q1" '
            'style="width:1280px;height:720px">'
            '<h1 data-quick-ai-id="q2">New</h1></div>'
        ),
        slideData={"title": "One"},
    )

    result = await routes.apply_slide_edit_agent_proposal(
        request, user=SimpleNamespace(id=10)
    )

    saved_html = saved["slide_data"]["html_content"]
    assert result["htmlContent"] == saved_html
    assert "data-agent-id" not in saved_html
    assert "data-quick-ai-id" not in saved_html
    assert "New" in saved_html


@pytest.mark.parametrize(
    ("html_content", "expected_error"),
    [
        (
            '<div style="width:1280px;height:720px">'
            "<script>alert(1)</script><h1>New</h1></div>",
            "script tags are not allowed",
        ),
        (
            '<div style="width:1280px;height:720px">'
            '<h1 onclick="bad()">New</h1></div>',
            "inline event handlers are not allowed",
        ),
        (
            '<div style="width:1280px;height:720px">'
            '<a href="java&#115;cript:bad()">New</a></div>',
            "javascript urls are not allowed",
        ),
        ("", "html content is required"),
        (
            '<div style="width:1280px;height:720px"><section><h1>New</section></div>',
            "html is malformed",
        ),
    ],
)
@pytest.mark.asyncio
async def test_apply_agent_proposal_rejects_invalid_html_before_save(
    monkeypatch,
    html_content,
    expected_error,
):
    current_html = '<div style="width:1280px;height:720px"><h1>Current</h1></div>'
    project = SimpleNamespace(
        slides_data=[
            {"title": "One", "html_content": current_html, "is_user_edited": False}
        ]
    )

    class _FakeDBManager:
        async def save_single_slide(self, project_id, slide_index, slide_data):
            raise AssertionError("invalid HTML should not be saved")

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )
    monkeypatch.setattr(routes, "DatabaseProjectManager", lambda: _FakeDBManager())

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html),
        htmlContent=html_content,
        slideData={"title": "One"},
    )

    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(
            request, user=SimpleNamespace(id=10)
        )

    assert exc.value.status_code == 400
    assert expected_error in exc.value.detail["errors"]


def _agent_request(**overrides):
    data = {
        "projectId": "proj",
        "slideIndex": 1,
        "slideTitle": "One",
        "slideContent": "<div>Current</div>",
        "userRequest": "Shorten the title",
    }
    data.update(overrides)
    return SlideEditAgentRequest(**data)


def _finished_event(**overrides):
    event = {
        "type": "run_finished",
        "status": "completed",
        "summary": "done",
        "iterationsUsed": 2,
        "proposal": {"proposalId": "p1"},
    }
    event.update(overrides)
    return event


def _patch_billing(monkeypatch, service=None, agent_service=None):
    """装好积分与依赖桩，返回 (check 记录, charge 记录)。"""
    checks = []
    charges = []

    async def check_credits(*args, **kwargs):
        checks.append(kwargs.get("provider_name"))
        return True, 1, 10

    async def consume_credits(*args, **kwargs):
        charges.append({"args": args, "kwargs": kwargs})
        return True, "ok"

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: service or _FakePPTService()
    )
    monkeypatch.setattr(routes, "check_credits_for_operation", check_credits)
    monkeypatch.setattr(routes, "consume_credits_for_operation", consume_credits)
    if agent_service is not None:
        monkeypatch.setattr(routes, "SlideEditAgentService", agent_service)
    return checks, charges


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_charges_once_after_the_run_finishes(monkeypatch):
    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback, handle=None):
            await event_callback({"type": "run_started", "runId": request.runId})
            await event_callback({"type": "draft_updated", "revision": 1})
            await event_callback(_finished_event())

    _, charges = _patch_billing(monkeypatch, agent_service=_FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        _agent_request(), user=SimpleNamespace(id=10)
    )
    body = await _collect_stream_body(response)

    assert '"type": "run_finished"' in body
    assert len(charges) == 1
    assert charges[0]["args"][:3] == (10, "ai_edit", 1)
    assert charges[0]["kwargs"]["reference_id"] == "proj"


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_charges_before_yielding_the_billable_chunk(monkeypatch):
    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback, handle=None):
            await event_callback(_finished_event())

    _, charges = _patch_billing(monkeypatch, agent_service=_FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        _agent_request(), user=SimpleNamespace(id=10)
    )

    first_chunk = await anext(response.body_iterator)
    if isinstance(first_chunk, bytes):
        first_chunk = first_chunk.decode("utf-8")

    assert '"type": "run_finished"' in first_chunk
    assert len(charges) == 1

    await _collect_stream_body(response)


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_uses_editor_provider_without_vision_inputs(monkeypatch):
    service = _FakePPTService(
        providers={"editor": "editor-provider", "vision_analysis": "vision-provider"}
    )

    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback, handle=None):
            await event_callback(_finished_event())

    checks, charges = _patch_billing(
        monkeypatch, service=service, agent_service=_FakeAgentService
    )

    response = await routes.stream_slide_edit_agent(
        _agent_request(visionEnabled=True), user=SimpleNamespace(id=10)
    )
    body = await _collect_stream_body(response)

    assert '"type": "run_finished"' in body
    assert service.roles == ["editor"]
    assert checks == ["editor-provider"]
    assert [charge["kwargs"]["provider_name"] for charge in charges] == ["editor-provider"]


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_does_not_charge_a_failed_run(monkeypatch):
    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback, handle=None):
            await event_callback({"type": "run_started", "runId": request.runId})
            raise RuntimeError("model unavailable")

    _, charges = _patch_billing(monkeypatch, agent_service=_FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        _agent_request(), user=SimpleNamespace(id=10)
    )
    body = await _collect_stream_body(response)

    assert '"status": "failed"' in body
    assert "model unavailable" in body
    assert charges == []


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_does_not_charge_a_run_stopped_before_any_model_call(
    monkeypatch,
):
    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback, handle=None):
            await event_callback(
                _finished_event(status="cancelled", iterationsUsed=0, proposal=None)
            )

    _, charges = _patch_billing(monkeypatch, agent_service=_FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        _agent_request(), user=SimpleNamespace(id=10)
    )
    body = await _collect_stream_body(response)

    assert '"status": "cancelled"' in body
    assert charges == []


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_registers_a_cancellable_run_and_releases_it(monkeypatch):
    seen = {}

    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback, handle=None):
            seen["runId"] = request.runId
            seen["handle"] = handle
            seen["registered"] = agent_run_registry.get(request.runId) is handle
            await event_callback(_finished_event())

    _patch_billing(monkeypatch, agent_service=_FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        _agent_request(runId="run-abc"), user=SimpleNamespace(id=10)
    )
    await _collect_stream_body(response)

    assert seen["runId"] == "run-abc"
    assert seen["registered"] is True
    assert seen["handle"].user_id == 10
    # 流结束后要把 run 从注册表摘掉，否则会一直泄漏。
    assert agent_run_registry.get("run-abc") is None


@pytest.mark.asyncio
async def test_cancel_slide_edit_agent_signals_the_running_agent():
    handle = agent_run_registry.register("run-to-cancel", 10)
    try:
        result = await routes.cancel_slide_edit_agent(
            SlideEditAgentCancelRequest(runId="run-to-cancel"),
            user=SimpleNamespace(id=10),
        )

        assert result == {"success": True, "cancelled": True, "runId": "run-to-cancel"}
        assert handle.cancelled is True
    finally:
        agent_run_registry.release("run-to-cancel")


@pytest.mark.asyncio
async def test_cancel_slide_edit_agent_refuses_another_users_run():
    handle = agent_run_registry.register("run-of-other-user", 99)
    try:
        result = await routes.cancel_slide_edit_agent(
            SlideEditAgentCancelRequest(runId="run-of-other-user"),
            user=SimpleNamespace(id=10),
        )

        assert result["cancelled"] is False
        assert handle.cancelled is False
    finally:
        agent_run_registry.release("run-of-other-user")


@pytest.mark.asyncio
async def test_cancel_slide_edit_agent_tolerates_unknown_run_ids():
    result = await routes.cancel_slide_edit_agent(
        SlideEditAgentCancelRequest(runId="run-does-not-exist"),
        user=SimpleNamespace(id=10),
    )

    assert result == {"success": True, "cancelled": False, "runId": "run-does-not-exist"}
