import ast
import json
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
async def test_dashboard_renders_model_timestamp_without_falling_back_to_error(monkeypatch):
    from fastapi import Request
    from landppt.api.models import PPTProject, ProjectListResponse
    from landppt.web.route_modules import project_lifecycle_routes

    project = PPTProject(
        project_id="timestamp-regression",
        title="真实时间戳项目",
        topic="Dashboard",
        scenario="general",
        status="completed",
    )
    calls = []

    class ProjectManager:
        async def list_projects(self, **query):
            calls.append(query)
            return ProjectListResponse(projects=[project], total=1, page=1, page_size=100)

    monkeypatch.setattr(
        project_lifecycle_routes, "ppt_service",
        SimpleNamespace(project_manager=ProjectManager()),
    )
    request = Request({"type": "http", "path": "/dashboard", "headers": []})
    user = SimpleNamespace(id=17, username="timestamp-user", is_admin=False)
    request.state.user = user
    response = await project_lifecycle_routes.web_dashboard(request, user=user)
    assert response.template.name == "pages/project/project_dashboard.html"
    html = response.body.decode()
    payload = json.loads(
        html.split('<script id="antdData" type="application/json">', 1)[1].split("</script>", 1)[0]
    )
    assert payload["projects"][0]["project_id"] == project.project_id
    assert payload["projects"][0]["updated"]
    assert payload["stats"] == [1, 1, 0, 0]
    assert calls == [{"page": 1, "page_size": 100, "user_id": 17}]


@pytest.mark.asyncio
async def test_dashboard_ships_recent_project_candidates_newest_first(monkeypatch):
    from fastapi import Request
    from landppt.api.models import PPTProject, ProjectListResponse
    from landppt.web.route_modules import project_lifecycle_routes

    projects = [
        PPTProject(
            project_id=f"recent-{index:02d}",
            title=f"最近项目 {index}",
            topic="Dashboard",
            scenario="general",
            status="completed",
            updated_at=float(1000 + index),
        )
        for index in range(15)
    ]

    class ProjectManager:
        async def list_projects(self, **query):
            return ProjectListResponse(
                projects=projects, total=len(projects), page=1, page_size=100
            )

    monkeypatch.setattr(
        project_lifecycle_routes, "ppt_service",
        SimpleNamespace(project_manager=ProjectManager()),
    )
    request = Request({"type": "http", "path": "/dashboard", "headers": []})
    user = SimpleNamespace(id=23, username="recent-user", is_admin=False)
    request.state.user = user
    response = await project_lifecycle_routes.web_dashboard(request, user=user)
    payload = json.loads(
        response.body.decode()
        .split('<script id="antdData" type="application/json">', 1)[1]
        .split("</script>", 1)[0]
    )
    # The page turns these candidates into whole card rows at the current column
    # count, so the payload must be newest-first and wide enough for desktop grids.
    assert project_lifecycle_routes.RECENT_PROJECT_CANDIDATE_LIMIT == 12
    assert [project["project_id"] for project in payload["projects"]] == [
        f"recent-{index:02d}" for index in range(14, 2, -1)
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










def test_outline_stream_headers_are_http2_safe():
    route_source = _read("src/landppt/web/route_modules/outline_generation_routes.py")

    assert '"Connection": "keep-alive"' not in route_source
    assert '"Cache-Control": "no-cache, no-transform"' in route_source


def test_todo_board_template_injects_outline_stage_status():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(ROOT / "src/landppt/web/templates"))
    rendered = env.get_template("pages/project/todo_board.html").render(
        request=SimpleNamespace(state=SimpleNamespace(user=None)), user=None,
        todo_board={"task_id": "project-1", "title": "Fixture project", "stages": [
            {"id": "requirements_confirmation", "status": "completed"},
            {"id": "outline_generation", "status": "running"},
            {"id": "ppt_creation", "status": "pending"},
        ]},
        project={"project_id": "project-1", "project_metadata": {}, "outline": None,
                 "slides_data": [], "slides_html": "", "confirmed_requirements": {"topic": "Demo"}},
    )
    payload = json.loads(rendered.split('<script id="antdData" type="application/json">')[1].split('</script>')[0])
    assert payload["outlineInitial"]["stageStatus"] == "running"
    assert payload["outlineInitial"]["confirmed"] is True
    assert set(payload["outlineInitial"]) == {"outline", "language", "confirmed", "stageStatus", "pptStageStatus"}
    assert 'initialProjectSlides' not in rendered and 'outline_ui_bridge.js' not in rendered


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


# Project detail actions are covered by built-browser regressions in
# test_antd_projects_ui.py and test_app_ui.py.


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


def test_ai_optimize_modals_settle_safely_and_use_scoped_dom():
    sources = [
        _read(
            "src/landppt/web/static/js/pages/project/slides_editor/"
            "projectSlidesEditor.aiOptimize.js"
        ),
    ]

    for source in sources:
        assert "function closeModal(value = null)" in source
        assert "content.querySelector('.ai-optimize-input')" in source
        assert "suggestionButton.textContent = String(suggestion)" in source
        assert "currentInfoElement.textContent = String(config.currentInfo || '')" in source
        assert "document.addEventListener('keydown', handleKeydown)" in source
        assert ".ai-optimize-modal__close').addEventListener('click', () => closeModal())" in source
        assert ".ai-optimize-cancel').addEventListener('click', () => closeModal())" in source
        assert "if (event.target === modal) closeModal()" in source
        assert 'id="aiOptimizeInput"' not in source
        assert 'id="confirmOptimizeBtn"' not in source
        assert "${suggestions.map" not in source
        assert "${config.currentInfo}" not in source
        assert "onclick=\"this.closest('.ai-optimize-modal').remove()\"" not in source

    assert "document.head.appendChild(style)" not in _read("frontend/src/components/todo-outline.tsx")
