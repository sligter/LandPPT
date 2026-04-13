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
