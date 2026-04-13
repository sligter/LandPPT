from pathlib import Path
from types import SimpleNamespace

import pytest

from landppt.services.template.template_selection_service import TemplateSelectionService


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class _ProjectManagerStub:
    def __init__(self, project):
        self.project = project
        self.metadata_updates = []

    async def get_project(self, project_id, user_id=None):
        return self.project

    async def update_project_metadata(self, project_id, metadata):
        copied = dict(metadata)
        self.metadata_updates.append(copied)
        self.project.project_metadata = copied


class _GlobalTemplateServiceStub:
    def __init__(self):
        self.calls = []

    async def generate_template_with_ai_stream(self, **kwargs):
        self.calls.append(kwargs)
        yield {
            "type": "thinking",
            "content": "前置说明```html\n<!DOCTYPE html><html><body><div class='preview'>partial",
        }
        yield {
            "type": "complete",
            "message": "模板生成完成！",
            "template_name": "自由模板-proj1234",
            "html_template": "<!DOCTYPE html><html><body><div class='final'>done</div></body></html>",
        }


class _TemplateSelectionServiceStub:
    def __init__(self, project):
        self.project_manager = _ProjectManagerStub(project)
        self.global_template_service = _GlobalTemplateServiceStub()
        self._free_template_generation_locks = {}
        self.cleared_projects = []

    def clear_cached_style_genes(self, project_id=None):
        self.cleared_projects.append(project_id)


class _JsonRequestStub:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_stream_free_template_generation_emits_preview_and_persists_final_html():
    project = SimpleNamespace(
        topic="流式模板",
        outline={"slides": [{"title": "封面"}]},
        confirmed_requirements={"style": "modern"},
        requirements="请生成现代商务风格",
        description="演示流式模板预览",
        project_metadata={"template_mode": "free", "free_template_status": "pending"},
    )
    stub = _TemplateSelectionServiceStub(project)
    service = TemplateSelectionService(stub)

    events = [
        event
        async for event in service.stream_free_template_generation("proj12345678", user_id=99, force=False)
    ]

    assert [event["type"] for event in events[:2]] == ["status", "status"]
    assert any(event["type"] == "preview" for event in events)
    assert events[-1]["type"] == "complete"
    assert events[-1]["template"]["html_template"].startswith("<!DOCTYPE html>")

    assert stub.project_manager.metadata_updates[0]["free_template_status"] == "generating"
    final_metadata = stub.project_manager.metadata_updates[-1]
    assert final_metadata["free_template_status"] == "ready"
    assert final_metadata["free_template_name"] == "自由模板-proj1234"
    assert final_metadata["free_template_html"] == "<!DOCTYPE html><html><body><div class='final'>done</div></body></html>"
    assert final_metadata["free_template_prompt"]
    assert stub.cleared_projects == ["proj12345678"]
    assert stub.global_template_service.calls[0]["prompt_is_ready"] is True


@pytest.mark.asyncio
async def test_stream_free_template_generation_reuses_existing_template_without_regenerating():
    project = SimpleNamespace(
        topic="流式模板",
        outline={},
        confirmed_requirements={},
        requirements="",
        description="",
        project_metadata={
            "template_mode": "free",
            "free_template_status": "ready",
            "free_template_name": "已有模板",
            "free_template_html": "<!DOCTYPE html><html><body>cached</body></html>",
        },
    )
    stub = _TemplateSelectionServiceStub(project)
    service = TemplateSelectionService(stub)

    events = [
        event
        async for event in service.stream_free_template_generation("proj12345678", user_id=99, force=False)
    ]

    assert [event["type"] for event in events] == ["status", "complete"]
    assert events[-1]["template_name"] == "已有模板"
    assert events[-1]["html_template"] == "<!DOCTYPE html><html><body>cached</body></html>"
    assert stub.project_manager.metadata_updates == []
    assert stub.global_template_service.calls == []


def test_extract_free_template_preview_html_supports_partial_html_chunks():
    preview = TemplateSelectionService._extract_free_template_preview_html(
        "说明文字```html\n<!DOCTYPE html><html><body><div class='preview'>partial"
    )

    assert preview == "<!DOCTYPE html><html><body><div class='preview'>partial"


@pytest.mark.asyncio
async def test_confirm_route_persists_current_frontend_html_before_generation(monkeypatch):
    from landppt.web.route_modules import template_routes

    project = SimpleNamespace(
        topic="template-demo",
        project_metadata={
            "template_mode": "free",
            "free_template_name": "first-version",
            "free_template_html": "<!DOCTYPE html><html><body>first</body></html>",
            "free_template_status": "ready",
        },
    )
    stub = _TemplateSelectionServiceStub(project)
    service = TemplateSelectionService(stub)

    async def _get_selected_global_template(project_id, user_id=None):
        return await service.get_selected_global_template(project_id, user_id=user_id)

    stub.get_selected_global_template = _get_selected_global_template
    monkeypatch.setattr(template_routes, "get_ppt_service_for_user", lambda user_id: stub)

    confirm_result = await template_routes.confirm_project_free_template(
        "proj-confirm",
        _JsonRequestStub(
            {
                "save_to_library": False,
                "template_name": "adjusted-version",
                "html_template": "<!DOCTYPE html><html><body>adjusted</body></html>",
            }
        ),
        user=SimpleNamespace(id=7),
    )

    selected_result = await template_routes.get_selected_global_template(
        "proj-confirm",
        user=SimpleNamespace(id=7),
    )

    assert confirm_result["success"] is True
    assert stub.project_manager.metadata_updates[-1]["free_template_html"] == "<!DOCTYPE html><html><body>adjusted</body></html>"
    assert stub.project_manager.metadata_updates[-1]["free_template_name"] == "adjusted-version"
    assert selected_result["template"]["html_template"] == "<!DOCTYPE html><html><body>adjusted</body></html>"
    assert stub.cleared_projects == ["proj-confirm"]


def test_free_template_streaming_route_and_frontend_use_sse_preview_pipeline():
    route_text = _read("src/landppt/web/route_modules/template_routes.py")
    service_text = _read("src/landppt/services/template/template_selection_service.py")
    script_text = _read("src/landppt/web/templates/components/project/todo_board_with_editor/script_1.html")

    assert 'want_stream = True if stream_flag is None else bool(stream_flag)' in route_text
    assert 'media_type="text/event-stream"' in route_text
    assert 'stream_free_template_generation(' in route_text
    assert '"type": "preview"' in service_text
    assert "'Accept': 'text/event-stream'" in script_text
    assert "consumeSseJsonStream(resp" in script_text
    assert 'iframe.srcdoc = freeTemplateCurrentHtml;' in script_text
    assert "html_template: getFreeTemplateHtmlForConfirm()" in script_text
    assert 'submitted_html = data.get("html_template")' in route_text
