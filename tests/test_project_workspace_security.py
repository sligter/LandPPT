from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _user(user_id: int, *, is_admin: bool = False):
    return SimpleNamespace(id=user_id, is_admin=is_admin)


@pytest.mark.asyncio
async def test_owned_project_helper_scopes_to_authenticated_user(monkeypatch):
    from landppt.services import db_project_manager as db_project_manager_module
    from landppt.web.route_modules import project_workspace_routes

    calls = {}

    class FakeProjectManager:
        async def get_project(self, project_id: str, user_id=None):
            calls["project_id"] = project_id
            calls["user_id"] = user_id
            return SimpleNamespace(project_id=project_id, user_id=user_id)

    monkeypatch.setattr(db_project_manager_module, "DatabaseProjectManager", FakeProjectManager)

    project = await project_workspace_routes._get_owned_project_or_404("proj-1", _user(42))

    assert project.project_id == "proj-1"
    assert calls == {"project_id": "proj-1", "user_id": 42}


@pytest.mark.asyncio
async def test_owned_project_helper_hides_other_users_projects(monkeypatch):
    from landppt.services import db_project_manager as db_project_manager_module
    from landppt.web.route_modules import project_workspace_routes

    class FakeProjectManager:
        async def get_project(self, project_id: str, user_id=None):
            return None

    monkeypatch.setattr(db_project_manager_module, "DatabaseProjectManager", FakeProjectManager)

    with pytest.raises(HTTPException) as excinfo:
        await project_workspace_routes._get_owned_project_or_404("proj-2", _user(7))

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Project not found"
