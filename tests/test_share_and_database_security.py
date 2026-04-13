from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _user(user_id: int, *, is_admin: bool = False):
    return SimpleNamespace(id=user_id, is_admin=is_admin)


@pytest.mark.asyncio
async def test_share_routes_require_project_ownership_for_generate(monkeypatch):
    from landppt.web.route_modules import share_routes

    calls = {}

    class FakeShareService:
        def __init__(self, db):
            self.db = db

        def generate_share_token(self, project_id: str, user_id=None):
            calls["project_id"] = project_id
            calls["user_id"] = user_id
            return "share-token"

    class FakeProjectManager:
        async def get_project(self, project_id: str, user_id=None):
            calls["lookup_project_id"] = project_id
            calls["lookup_user_id"] = user_id
            return SimpleNamespace(project_id=project_id)

    monkeypatch.setattr(share_routes, "ShareService", FakeShareService)
    monkeypatch.setattr(share_routes, "DatabaseProjectManager", FakeProjectManager)

    response = await share_routes.generate_share_link(
        "proj-1",
        user=_user(42),
        db=object(),
    )

    assert response["success"] is True
    assert calls == {
        "lookup_project_id": "proj-1",
        "lookup_user_id": 42,
        "project_id": "proj-1",
        "user_id": 42,
    }


@pytest.mark.asyncio
async def test_share_routes_hide_other_users_projects(monkeypatch):
    from fastapi import HTTPException
    from landppt.web.route_modules import share_routes

    class FakeProjectManager:
        async def get_project(self, project_id: str, user_id=None):
            return None

    monkeypatch.setattr(share_routes, "DatabaseProjectManager", FakeProjectManager)

    with pytest.raises(HTTPException) as excinfo:
        await share_routes.get_share_info("proj-2", user=_user(7), db=object())

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Project not found"


def test_database_routes_require_admin_for_dangerous_operations():
    from landppt.api import database_api

    app = FastAPI()
    app.include_router(database_api.router)
    client = TestClient(app)

    admin_only_routes = [
        ("/api/database/health", "get"),
        ("/api/database/health/quick", "get"),
        ("/api/database/stats", "get"),
        ("/api/database/migrations/status", "get"),
        ("/api/database/migrations/run", "post"),
        ("/api/database/cleanup/orphaned", "post"),
        ("/api/database/backup/info", "get"),
    ]

    for path, method in admin_only_routes:
        response = getattr(client, method)(path)
        assert response.status_code == 401, (path, response.text)


def test_database_delete_project_scopes_to_authenticated_user(monkeypatch):
    from landppt.api import database_api
    from landppt.auth.middleware import get_current_user_required

    calls = {}

    class FakeProjectManager:
        async def get_project(self, project_id: str, user_id=None):
            calls["lookup_project_id"] = project_id
            calls["lookup_user_id"] = user_id
            return SimpleNamespace(project_id=project_id)

        async def delete_project(self, project_id: str, user_id=None):
            calls["delete_project_id"] = project_id
            calls["delete_user_id"] = user_id
            return True

        async def close(self):
            return None

    monkeypatch.setattr(database_api, "DatabaseProjectManager", FakeProjectManager)

    app = FastAPI()
    app.include_router(database_api.router)
    app.dependency_overrides[get_current_user_required] = lambda: _user(11, is_admin=False)
    client = TestClient(app)

    response = client.delete("/api/database/projects/proj-9")

    assert response.status_code == 200
    assert calls == {
        "lookup_project_id": "proj-9",
        "lookup_user_id": 11,
        "delete_project_id": "proj-9",
        "delete_user_id": 11,
    }


def test_database_delete_project_keeps_admin_global_scope(monkeypatch):
    from landppt.api import database_api
    from landppt.auth.middleware import get_current_user_required

    calls = {}

    class FakeProjectManager:
        async def get_project(self, project_id: str, user_id=None):
            calls["lookup_user_id"] = user_id
            return SimpleNamespace(project_id=project_id)

        async def delete_project(self, project_id: str, user_id=None):
            calls["delete_user_id"] = user_id
            return True

        async def close(self):
            return None

    monkeypatch.setattr(database_api, "DatabaseProjectManager", FakeProjectManager)

    app = FastAPI()
    app.include_router(database_api.router)
    app.dependency_overrides[get_current_user_required] = lambda: _user(1, is_admin=True)
    client = TestClient(app)

    response = client.delete("/api/database/projects/proj-admin")

    assert response.status_code == 200
    assert calls == {"lookup_user_id": None, "delete_user_id": None}
