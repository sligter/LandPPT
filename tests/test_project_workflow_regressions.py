import ast
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from landppt.database.service import DatabaseService


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _load_class_method(relative_path: str, class_name: str, method_name: str):
    tree = ast.parse(_read(relative_path))
    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method_node = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    module = ast.Module(body=[method_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Optional": Optional,
        "PPTGenerationRequest": dict,
    }
    exec(compile(module, relative_path, "exec"), namespace)
    return namespace[method_name]


@pytest.mark.asyncio
async def test_rename_project_scopes_to_current_user(monkeypatch):
    from landppt.api import landppt_api
    from landppt.api.models import ProjectRenameRequest

    calls = {}

    class FakeProjectManager:
        async def get_project(self, project_id, user_id=None):
            calls["lookup"] = (project_id, user_id)
            return SimpleNamespace(project_id=project_id)

        async def update_project_data(self, project_id, update_data, user_id=None):
            calls["update"] = (project_id, update_data, user_id)
            return True

    monkeypatch.setattr(
        landppt_api,
        "get_ppt_service_for_user",
        lambda user_id: SimpleNamespace(project_manager=FakeProjectManager()),
    )

    response = await landppt_api.rename_project(
        "proj-1",
        ProjectRenameRequest(title="  New project title  "),
        user=SimpleNamespace(id=11),
    )

    assert response["status"] == "success"
    assert response["title"] == "New project title"
    assert calls == {
        "lookup": ("proj-1", 11),
        "update": ("proj-1", {"title": "New project title"}, 11),
    }


@pytest.mark.asyncio
async def test_rename_project_rejects_blank_title():
    from fastapi import HTTPException
    from landppt.api import landppt_api
    from landppt.api.models import ProjectRenameRequest

    with pytest.raises(HTTPException) as excinfo:
        await landppt_api.rename_project(
            "proj-1",
            ProjectRenameRequest(title="   "),
            user=SimpleNamespace(id=11),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "Project title is required"


@pytest.mark.asyncio
async def test_continue_from_outline_stage_returns_stream_action(monkeypatch):
    from landppt.api import landppt_api

    calls = []

    class FakeRequest:
        async def json(self):
            return {"stage_id": "outline_generation"}

    class FakeProjectManager:
        async def get_project(self, project_id, user_id=None):
            calls.append(("get_project", project_id, user_id))
            return SimpleNamespace(project_id=project_id, confirmed_requirements={"topic": "demo"})

    class FakePPTService:
        project_manager = FakeProjectManager()

        async def reset_stages_from(self, project_id, stage_id, user_id=None):
            calls.append(("reset", project_id, stage_id, user_id))
            return True

        async def start_workflow_from_stage(self, project_id, stage_id, user_id=None):
            calls.append(("prepare", project_id, stage_id, user_id))
            return True

    monkeypatch.setattr(
        landppt_api,
        "get_ppt_service_for_user",
        lambda user_id: FakePPTService(),
    )

    response = await landppt_api.continue_from_stage(
        "project-1",
        FakeRequest(),
        user=SimpleNamespace(id=11),
    )

    assert response["status"] == "ready"
    assert response["action"] == "start_outline_stream"
    assert response["stream_url"] == "/projects/project-1/outline-stream?force_regenerate=1"
    assert calls == [
        ("get_project", "project-1", 11),
        ("reset", "project-1", "outline_generation", 11),
        ("prepare", "project-1", "outline_generation", 11),
    ]


@pytest.mark.asyncio
async def test_enhanced_ppt_service_keeps_project_workflow_proxy():
    execute_project_workflow = _load_class_method(
        "src/landppt/services/enhanced_ppt_service.py",
        "EnhancedPPTService",
        "_execute_project_workflow",
    )

    class FakeWorkflow:
        async def _execute_project_workflow(self, project_id, request, user_id=None):
            return {
                "project_id": project_id,
                "request": request,
                "user_id": user_id,
            }

    service = SimpleNamespace(project_outline_workflow=FakeWorkflow())

    result = await execute_project_workflow(service, "project-1", {"topic": "demo"}, user_id=9)

    assert result == {
        "project_id": "project-1",
        "request": {"topic": "demo"},
        "user_id": 9,
    }


def _make_db_project(project_id: str, raw_status: str, *, confirmed=False, outline_pages=0, slides_count=0):
    now = time.time()
    slides = [
        SimpleNamespace(
            slide_id=f"{project_id}-slide-{idx}",
            title=f"Slide {idx + 1}",
            content_type="content",
            html_content=f"<section>{idx + 1}</section>",
            slide_metadata={},
            is_user_edited=False,
            created_at=now,
            updated_at=now,
            slide_index=idx,
        )
        for idx in range(slides_count)
    ]
    outline = {"slides": [{"title": f"Page {idx + 1}"} for idx in range(outline_pages)]} if outline_pages else None
    return SimpleNamespace(
        project_id=project_id,
        title=project_id,
        scenario="general",
        topic=project_id,
        requirements="req",
        status=raw_status,
        outline=outline,
        slides_html="",
        slides_data=None,
        confirmed_requirements={"ok": True} if confirmed else None,
        project_metadata={},
        todo_board=None,
        version=1,
        versions=[],
        slides=slides,
        created_at=now,
        updated_at=now,
    )


class _FakeProjectRepo:
    def __init__(self, projects):
        self.projects = projects

    async def list_projects(self, user_id=None, page=1, page_size=10, status=None):
        items = self.projects
        if status is not None:
            items = [project for project in items if project.status == status]
        start = (page - 1) * page_size
        end = start + page_size
        return items[start:end]

    async def count_projects(self, user_id=None, status=None):
        if status is None:
            return len(self.projects)
        return len([project for project in self.projects if project.status == status])


@pytest.mark.asyncio
async def test_database_service_filters_projects_by_effective_status_after_conversion():
    service = DatabaseService(None)
    service.project_repo = _FakeProjectRepo(
        [
            _make_db_project("derived-in-progress", "draft", confirmed=True),
            _make_db_project("still-draft", "draft"),
            _make_db_project("already-completed", "completed", outline_pages=3, slides_count=3),
        ]
    )

    response = await service.list_projects(page=1, page_size=10, status="in_progress", user_id=1)

    assert response.total == 1
    assert [project.project_id for project in response.projects] == ["derived-in-progress"]


def test_todo_board_preserves_saved_outline_before_auto_starting_generation():
    script = _read("src/landppt/web/templates/components/project/todo_board/extra_js_1.html")

    assert "Saved outline exists, skipping auto-start outline generation." in script
    assert "Saved outline exists, hydrating instead of starting outline generation." in script
    assert "Saved outline exists, skipping workflow auto-start." in script


def test_slide_record_from_payload_preserves_outline_metadata():
    record = DatabaseService._slide_record_from_payload(
        "project-1",
        2,
        {
            "title": "Updated title",
            "slide_type": "section",
            "description": "Updated description",
            "content_points": ["point-a", "point-b"],
            "html_content": "<section>Updated</section>",
            "is_user_edited": True,
        },
    )

    assert record["title"] == "Updated title"
    assert record["content_type"] == "section"
    assert record["slide_metadata"]["description"] == "Updated description"
    assert record["slide_metadata"]["content_points"] == ["point-a", "point-b"]
    assert record["html_content"] == "<section>Updated</section>"
    assert record["is_user_edited"] is True


def test_editor_slide_save_sends_full_slide_payload():
    script = _read(
        "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.slideGeneration.js"
    )

    assert "slide_data: slidePayload" in script
    assert "content_points: slidePayload.content_points || []" in script
    assert "metadata: slidePayload.metadata || {}" in script


def test_outline_operations_send_structure_operation_payload():
    script = _read("src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.aiChat.js")

    assert "const operationPayload = {" in script
    assert "operation: operationPayload" in script
    assert "await saveSingleSlideToServer(" in script


def test_project_detail_outline_supports_drag_delete_and_duplicate():
    content = _read("src/landppt/web/templates/components/project/detail/content_1.html")
    script = _read("src/landppt/web/templates/components/project/detail/extra_js_1.html")

    assert 'draggable="true"' in content
    assert "deleteOutlineSlide(" in content
    assert "duplicateProject()" in content
    assert "function initializeOutlineDragAndDrop()" in script
    assert "async function persistProjectOutline(operation)" in script


def test_project_detail_outline_uses_icon_only_toolbar():
    content = _read("src/landppt/web/templates/components/project/detail/content_1.html")
    css = _read("src/landppt/web/templates/components/project/detail/extra_css_1.html")
    script = _read("src/landppt/web/templates/components/project/detail/extra_js_1.html")

    assert "outline-panel__header" in content
    assert "outline-tool-btn" in content
    assert 'data-tooltip="编辑大纲"' in content
    assert 'id="outlineViewToggleBtn"' in content
    assert "outline-slide-card__actions" in content
    assert ".outline-tool-btn[data-tooltip]::after" in css
    assert "setOutlineToggleState(isDetailView)" in script
    assert "toggleIcon.className = 'fas fa-th-large'" in script


def test_editor_sidebar_thumbnail_refresh_recalculates_scale_without_overriding_load_handler():
    core = _read("src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.core.js")
    slide_crud = _read("src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.slideCrud.js")
    css = _read("src/landppt/web/static/css/pages/project/slides_editor/projectSlidesEditor.css")

    assert "function requestThumbnailPreviewScale(iframe)" in core
    assert "iframe.addEventListener('load', handleIframeLoad, { once: true });" in core
    assert "requestThumbnailPreviewScale(iframe);" in slide_crud
    assert "iframe.onload = function" not in slide_crud
    assert "aspect-ratio: 16 / 9;" in css
    assert "height: 95px" not in css
    assert "scale(0.1875)" in css


def test_continue_outline_stage_starts_real_outline_stream():
    api = _read("src/landppt/api/landppt_api.py")
    script = _read("src/landppt/web/templates/components/project/todo_board/extra_js_1.html")

    assert '"action": "start_outline_stream"' in api
    assert 'stream_url": f"/projects/{project_id}/outline-stream?force_regenerate=1"' in api
    assert "result.action === 'start_outline_stream'" in script
    assert "startOutlineGenerationNew({ forceRegenerate: true })" in script


def test_outline_generation_failures_are_not_left_running_or_pending():
    route = _read("src/landppt/web/route_modules/outline_generation_routes.py")
    streaming_service = _read("src/landppt/services/outline/project_outline_streaming_service.py")
    script = _read("src/landppt/web/templates/components/project/todo_board/extra_js_1.html")

    assert '"outline_generation",\n                        "running"' in route
    assert '"outline_generation",\n                                    "failed"' in route
    assert "'outline_generation',\n                        'failed'" in streaming_service
    assert "outlineGenerationStarted = false;" in script


def test_requirements_return_auto_start_no_longer_skips_outline_stream():
    script = _read("src/landppt/web/templates/components/project/todo_board/extra_js_1.html")

    assert "function isOutlineStageReadyToStart(statusText)" in script
    assert "['⏳', '✗', '✕'].includes" in script

    auto_start_block = script[
        script.index(
            "if ((fromRequirements || requirementsCompleted) && isOutlineStageReadyToStart(outlineStatus))"
        )
        : script.index("} else if (!requirementsCompleted)")
    ]

    assert "startOutlineGenerationNew();" in auto_start_block
    assert "if (!fromRequirements)" not in auto_start_block
    assert "if (!outlineGenerationStarted)" in auto_start_block
