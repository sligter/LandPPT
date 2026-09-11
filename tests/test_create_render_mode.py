"""The primary /create flow must persist the page renderer before work starts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from landppt.web.route_modules import project_lifecycle_routes as routes


@pytest.fixture
def creation(monkeypatch):
    project = SimpleNamespace(
        project_id="new-project",
        project_metadata={"language": "en", "network_mode": False},
    )
    manager = SimpleNamespace(
        create_project=AsyncMock(return_value=project),
        update_project_status=AsyncMock(return_value=True),
        update_project_metadata=AsyncMock(return_value=True),
    )
    service = SimpleNamespace(
        project_manager=manager,
        confirm_requirements_and_update_workflow=AsyncMock(return_value=True),
    )
    launch = AsyncMock(return_value=None)
    monkeypatch.setattr(routes, "ppt_service", service)
    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda uid: service)
    monkeypatch.setattr(routes, "maybe_start_unattended_run", launch)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_current_user_required] = (
        lambda: SimpleNamespace(id=7, is_admin=True)
    )
    return SimpleNamespace(app=app, manager=manager, service=service, launch=launch)


@pytest.mark.parametrize(
    "submitted, expected",
    [
        (None, "html"),
        ("html", "html"),
        ("svg", "svg"),
        (" SVG ", "svg"),
        ("unknown", "html"),
    ],
)
def test_create_persists_renderer_and_preserves_metadata_before_workflow(
    creation, submitted, expected
):
    async def confirm(project_id, requirements):
        creation.manager.update_project_metadata.assert_awaited_once_with(
            "new-project",
            {"language": "en", "network_mode": False, "render_mode": expected},
            user_id=7,
        )
        # Renderer metadata must not alter the shared semantic guidance inputs.
        assert "render_mode" not in requirements
        return True

    creation.service.confirm_requirements_and_update_workflow.side_effect = confirm
    form = {
        "topic": "Renderer verification",
        "language": "en",
        "unattended_mode": "true",
    }
    if submitted is not None:
        form["render_mode"] = submitted
    with TestClient(creation.app) as client:
        response = client.post("/projects/create-and-confirm", data=form)
    assert response.status_code == 200, response.text
    assert response.json()["redirect_url"] == "/projects/new-project/todo"
    creation.service.confirm_requirements_and_update_workflow.assert_awaited_once()
    creation.launch.assert_awaited_once()


def test_create_does_not_start_generation_when_renderer_cannot_be_saved(creation):
    creation.manager.update_project_metadata.return_value = False
    with TestClient(creation.app) as client:
        response = client.post(
            "/projects/create-and-confirm", data={"topic": "Test", "render_mode": "svg"}
        )
    assert response.status_code == 500
    assert "页面绘制方式保存失败" in response.json()["message"]
    creation.service.confirm_requirements_and_update_workflow.assert_not_awaited()
    creation.launch.assert_not_awaited()
