from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _user(user_id: int, *, is_admin: bool = False):
    return SimpleNamespace(id=user_id, is_admin=is_admin)


def _task(*, metadata=None, result=None, status="completed", task_type="pdf_generation"):
    return SimpleNamespace(
        task_id="task-1",
        task_type=task_type,
        status=SimpleNamespace(value=status),
        progress=100.0,
        created_at=datetime(2026, 4, 7, 12, 0, 0),
        updated_at=datetime(2026, 4, 7, 12, 1, 0),
        metadata=metadata or {},
        result=result,
        error=None,
    )


def test_export_task_routes_require_authentication():
    from landppt.web.route_modules import export_routes

    app = FastAPI()
    app.include_router(export_routes.router)
    app.dependency_overrides[export_routes.get_current_user_required] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=401, detail="Authentication required")
    )
    client = TestClient(app)

    status_response = client.get("/api/landppt/tasks/task-1")
    download_response = client.get("/api/landppt/tasks/task-1/download")

    assert status_response.status_code == 401
    assert download_response.status_code == 401


def test_export_task_status_hides_other_users_tasks(monkeypatch):
    from landppt.services import background_tasks as background_tasks_module
    from landppt.web.route_modules import export_routes

    class FakeTaskManager:
        async def get_task_async(self, task_id: str):
            return _task(metadata={"project_id": "proj-1", "user_id": 22})

    monkeypatch.setattr(background_tasks_module, "get_task_manager", lambda: FakeTaskManager())

    app = FastAPI()
    app.include_router(export_routes.router)
    app.dependency_overrides[export_routes.get_current_user_required] = lambda: _user(11, is_admin=False)
    client = TestClient(app)

    response = client.get("/api/landppt/tasks/task-1")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_export_task_status_hides_ownerless_tasks_from_non_admin(monkeypatch):
    from landppt.services import background_tasks as background_tasks_module
    from landppt.web.route_modules import export_routes

    class FakeTaskManager:
        async def get_task_async(self, task_id: str):
            return _task(metadata={"project_id": "proj-1"})

    monkeypatch.setattr(background_tasks_module, "get_task_manager", lambda: FakeTaskManager())

    app = FastAPI()
    app.include_router(export_routes.router)
    app.dependency_overrides[export_routes.get_current_user_required] = lambda: _user(11, is_admin=False)
    client = TestClient(app)

    response = client.get("/api/landppt/tasks/task-1")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_export_task_status_redacts_internal_paths(monkeypatch):
    from landppt.services import background_tasks as background_tasks_module
    from landppt.web.route_modules import export_routes

    class FakeTaskManager:
        async def get_task_async(self, task_id: str):
            return _task(
                metadata={
                    "project_id": "proj-1",
                    "project_topic": "Demo",
                    "user_id": 11,
                    "pdf_path": "/tmp/private.pdf",
                    "pptx_path": "/tmp/private.pptx",
                    "progress_message": "working",
                },
                result={
                    "success": True,
                    "pdf_path": "/tmp/private.pdf",
                    "pptx_path": "/tmp/private.pptx",
                    "project_topic": "Demo",
                },
                task_type="pdf_generation",
            )

    monkeypatch.setattr(background_tasks_module, "get_task_manager", lambda: FakeTaskManager())

    app = FastAPI()
    app.include_router(export_routes.router)
    app.dependency_overrides[export_routes.get_current_user_required] = lambda: _user(11, is_admin=False)
    client = TestClient(app)

    response = client.get("/api/landppt/tasks/task-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "working"
    assert payload["download_url"] == "/api/landppt/tasks/task-1/download"
    assert payload["metadata"] == {
        "project_id": "proj-1",
        "project_topic": "Demo",
        "user_id": 11,
        "progress_message": "working",
    }
    assert payload["result"] == {
        "success": True,
        "project_topic": "Demo",
    }


def test_export_task_download_allows_admin_bypass(monkeypatch, tmp_path):
    from landppt.services import background_tasks as background_tasks_module
    from landppt.web.route_modules import export_routes

    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    class FakeTaskManager:
        async def get_task_async(self, task_id: str):
            return _task(
                metadata={"project_id": "proj-1", "project_topic": "Demo"},
                result={"success": True, "pdf_path": str(pdf_path)},
                task_type="pdf_generation",
            )

    monkeypatch.setattr(background_tasks_module, "get_task_manager", lambda: FakeTaskManager())
    monkeypatch.setattr(background_tasks_module, "TaskStatus", SimpleNamespace(COMPLETED=_task().status))

    app = FastAPI()
    app.include_router(export_routes.router)
    app.dependency_overrides[export_routes.get_current_user_required] = lambda: _user(1, is_admin=True)
    client = TestClient(app)

    response = client.get("/api/landppt/tasks/task-1/download")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-1.4")


def test_export_task_route_source_includes_owner_scoping_changes():
    source = Path("/root/clawd/src/landppt/web/route_modules/export_routes.py").read_text(encoding="utf-8")

    assert 'metadata_filter={"project_id": project_id, "user_id": user.id}' in source
    assert '"user_id": user.id' in source
    assert '"metadata": _sanitize_task_mapping(task.metadata)' in source
    assert 'response["result"] = _sanitize_task_mapping(task.result)' in source
    assert "_ensure_task_access(task, user)" in source


def test_narration_task_route_source_includes_owner_scoping_changes():
    source = Path("/root/clawd/src/landppt/web/route_modules/narration_routes.py").read_text(encoding="utf-8")

    assert 'metadata_filter={"project_id": project_id, "language": language, "provider": provider, "user_id": user.id}' in source
    assert '"user_id": user.id' in source
