from types import SimpleNamespace

import pytest


def _user(user_id: int, *, is_admin: bool = False):
    return SimpleNamespace(id=user_id, is_admin=is_admin)


@pytest.mark.asyncio
async def test_slide_cleanup_route_passes_authenticated_user_id(monkeypatch):
    from landppt.services import db_project_manager as db_project_manager_module
    from landppt.web.route_modules import slide_routes

    calls = {}

    class FakeProjectManager:
        async def get_project(self, project_id: str, user_id=None):
            calls["lookup_project_id"] = project_id
            calls["lookup_user_id"] = user_id
            return SimpleNamespace(project_id=project_id)

    class FakeDatabaseProjectManager:
        async def cleanup_excess_slides(self, project_id: str, current_slide_count: int, user_id=None):
            calls["cleanup_project_id"] = project_id
            calls["cleanup_slide_count"] = current_slide_count
            calls["cleanup_user_id"] = user_id
            return 2

    class FakeRequest:
        async def json(self):
            return {"current_slide_count": 3}

    monkeypatch.setattr(slide_routes.ppt_service, "project_manager", FakeProjectManager())
    monkeypatch.setattr(db_project_manager_module, "DatabaseProjectManager", FakeDatabaseProjectManager)

    result = await slide_routes.cleanup_excess_slides("proj-1", FakeRequest(), _user(42))

    assert result == {
        "success": True,
        "message": "Successfully cleaned up 2 excess slides",
        "deleted_count": 2,
    }
    assert calls == {
        "lookup_project_id": "proj-1",
        "lookup_user_id": 42,
        "cleanup_project_id": "proj-1",
        "cleanup_slide_count": 3,
        "cleanup_user_id": 42,
    }


@pytest.mark.asyncio
async def test_database_service_cleanup_excess_slides_prefers_explicit_user_id():
    from landppt.auth.request_context import current_user_id
    from landppt.database.service import DatabaseService

    class FakeProjectRepo:
        def __init__(self):
            self.calls = []

        async def get_by_id(self, project_id: str, user_id=None):
            self.calls.append((project_id, user_id))
            return object()

    class FakeSlideRepo:
        def __init__(self):
            self.calls = []

        async def delete_slides_after_index(self, project_id: str, current_slide_count: int):
            self.calls.append((project_id, current_slide_count))
            return 4

    service = DatabaseService(SimpleNamespace())
    service.project_repo = FakeProjectRepo()
    service.slide_repo = FakeSlideRepo()

    token = current_user_id.set(999)
    try:
        deleted_count = await service.cleanup_excess_slides("proj-2", 5, user_id=12)
    finally:
        current_user_id.reset(token)

    assert deleted_count == 4
    assert service.project_repo.calls == [("proj-2", 12)]
    assert service.slide_repo.calls == [("proj-2", 5)]


@pytest.mark.asyncio
async def test_database_service_cleanup_excess_slides_falls_back_to_request_context():
    from landppt.auth.request_context import current_user_id
    from landppt.database.service import DatabaseService

    class FakeProjectRepo:
        def __init__(self):
            self.calls = []

        async def get_by_id(self, project_id: str, user_id=None):
            self.calls.append((project_id, user_id))
            return object()

    class FakeSlideRepo:
        async def delete_slides_after_index(self, project_id: str, current_slide_count: int):
            return 1

    service = DatabaseService(SimpleNamespace())
    service.project_repo = FakeProjectRepo()
    service.slide_repo = FakeSlideRepo()

    token = current_user_id.set(33)
    try:
        deleted_count = await service.cleanup_excess_slides("proj-ctx", 2)
    finally:
        current_user_id.reset(token)

    assert deleted_count == 1
    assert service.project_repo.calls == [("proj-ctx", 33)]


def test_slide_cleanup_source_threads_explicit_user_id():
    source = open("/root/clawd/src/landppt/web/route_modules/slide_routes.py", "r", encoding="utf-8").read()
    assert "deleted_count = await db_manager.cleanup_excess_slides(" in source
    assert "user_id=user.id" in source


def test_db_project_manager_source_accepts_cleanup_user_id():
    source = open("/root/clawd/src/landppt/services/db_project_manager.py", "r", encoding="utf-8").read()
    assert "async def cleanup_excess_slides(" in source
    assert "user_id: Optional[int] = None" in source
    assert "user_id=user_id" in source


def test_database_service_source_prefers_explicit_cleanup_user_id_with_fallback():
    source = open("/root/clawd/src/landppt/database/service.py", "r", encoding="utf-8").read()
    assert "async def cleanup_excess_slides(" in source
    assert "effective_user_id = user_id" in source
    assert "if effective_user_id == USER_SCOPE_ALL:" in source
    assert "if effective_user_id is None:" in source
    assert "effective_user_id = current_user_id.get()" in source
