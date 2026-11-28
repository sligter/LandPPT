"""Regression tests for GHSA-hphg-cv3r-fgfr.

Non-admin users must never be able to write ``admin_only`` config keys (which are stored at
system scope and shared by every user) through the generic ``POST /api/config/{category}``
endpoint, through the dedicated web handlers that it shadows, or through the service layer.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _user(user_id: int = 7, *, is_admin: bool = False):
    return SimpleNamespace(id=user_id, is_admin=is_admin)


def _service(*, update: AsyncMock = None):
    """Service double that reuses the real schema / ADMIN_ONLY_CATEGORIES."""
    from landppt.services.db_config_service import DatabaseConfigService

    real = DatabaseConfigService()
    return SimpleNamespace(
        ADMIN_ONLY_CATEGORIES=real.ADMIN_ONLY_CATEGORIES,
        get_config_schema=real.get_config_schema,
        update_config=update if update is not None else AsyncMock(return_value=True),
    )


def _patch_service_factory(monkeypatch, service):
    """Route modules import get_db_config_service lazily, so patch the source module too."""
    import landppt.services.db_config_service as db_config_service_module
    from landppt.api import config_api
    from landppt.web.route_modules import config_routes

    factory = lambda: service  # noqa: E731
    monkeypatch.setattr(config_api, "get_db_config_service", factory)
    monkeypatch.setattr(db_config_service_module, "get_db_config_service", factory)
    monkeypatch.setattr(config_routes, "get_db_config_service", factory, raising=False)


def _written_keys(update: AsyncMock):
    return {key for call in update.await_args_list for key in call.args[0]}


def _never_writes_system_scope(update: AsyncMock):
    return all(call.kwargs.get("user_id") is not None for call in update.await_args_list)


# ==================== Generic handler: POST /api/config/{category} ====================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category, admin_only_key, allowed_key",
    [
        ("ai_providers", "landppt_base_url", "landppt_model"),
        ("ai_providers", "landppt_api_key", "openai_model"),
        ("oauth_settings", "github_client_secret", None),
        ("generation_params", "apryse_license_key", "research_provider"),
    ],
)
async def test_update_config_by_category_drops_admin_only_keys_for_non_admin(
    monkeypatch, category, admin_only_key, allowed_key
):
    from landppt.api import config_api

    update = AsyncMock(return_value=True)
    monkeypatch.setattr(config_api, "get_db_config_service", lambda: _service(update=update))

    payload = {admin_only_key: "attacker-controlled"}
    if allowed_key:
        payload[allowed_key] = "allowed-value"

    result = await config_api.update_config_by_category(
        category,
        config_api.ConfigUpdateRequest(config=payload),
        user=_user(is_admin=False),
    )

    assert result["success"] is True
    assert admin_only_key not in _written_keys(update)
    assert _never_writes_system_scope(update)
    assert all(call.kwargs.get("allow_admin_only") is False for call in update.await_args_list)

    if allowed_key:
        update.assert_awaited_once_with(
            {allowed_key: "allowed-value"}, user_id=7, allow_admin_only=False
        )
    else:
        update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category, admin_only_key",
    [
        ("ai_providers", "landppt_base_url"),
        ("oauth_settings", "github_client_secret"),
        ("generation_params", "apryse_license_key"),
    ],
)
async def test_update_config_by_category_still_accepts_admin_only_keys_for_admin(
    monkeypatch, category, admin_only_key
):
    from landppt.api import config_api

    update = AsyncMock(return_value=True)
    monkeypatch.setattr(config_api, "get_db_config_service", lambda: _service(update=update))

    result = await config_api.update_config_by_category(
        category,
        config_api.ConfigUpdateRequest(config={admin_only_key: "admin-value"}),
        user=_user(is_admin=True),
    )

    assert result["success"] is True
    update.assert_awaited_once_with(
        {admin_only_key: "admin-value"}, user_id=7, allow_admin_only=True
    )


@pytest.mark.asyncio
async def test_update_config_by_category_returns_403_for_admin_only_category(monkeypatch):
    from fastapi import HTTPException
    from landppt.api import config_api

    update = AsyncMock(return_value=True)
    monkeypatch.setattr(config_api, "get_db_config_service", lambda: _service(update=update))

    with pytest.raises(HTTPException) as excinfo:
        await config_api.update_config_by_category(
            "feature_flags",
            config_api.ConfigUpdateRequest(config={"debug": "false"}),
            user=_user(is_admin=False),
        )

    assert excinfo.value.status_code == 403
    update.assert_not_awaited()


# ==================== Route level: shadowed /api/config/ai_providers ====================

def test_post_ai_providers_route_never_writes_system_scope_for_non_admin(monkeypatch):
    """Reproduces the advisory through real routing.

    main.py registers api/config_api before the web router, so the generic
    POST /api/config/{category} handler is what actually serves /api/config/ai_providers.
    Whichever handler wins, a non-admin must not be able to overwrite system values.
    """
    from landppt.api import config_api
    from landppt.auth.middleware import get_current_user_required
    from landppt.web.route_modules import config_routes

    update = AsyncMock(return_value=True)
    service = _service(update=update)
    _patch_service_factory(monkeypatch, service)

    app = FastAPI()
    app.include_router(config_api.router)
    app.include_router(config_routes.router)
    app.dependency_overrides[get_current_user_required] = lambda: _user(is_admin=False)
    client = TestClient(app)

    response = client.post(
        "/api/config/ai_providers",
        json={
            "config": {
                "landppt_base_url": "https://attacker.example/v1",
                "landppt_model": "MODEL2",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "landppt_base_url" not in _written_keys(update)
    assert _never_writes_system_scope(update)


# ==================== Dedicated web handlers (shadowed today, locked for the future) =======

@pytest.mark.asyncio
async def test_web_update_ai_providers_rejects_admin_only_keys_for_non_admin(monkeypatch):
    from landppt.web.route_modules import config_routes

    update = AsyncMock(return_value=True)
    _patch_service_factory(monkeypatch, _service(update=update))

    request = SimpleNamespace(
        json=AsyncMock(
            return_value={
                "config": {
                    "landppt_api_key": "attacker-key",
                    "landppt_base_url": "https://attacker.example/v1",
                    "openai_model": "gpt-x",
                }
            }
        )
    )

    result = await config_routes.update_ai_providers_config(request, user=_user(is_admin=False))

    assert result["success"] is True
    assert result["errors"] == {
        "landppt_api_key": "Admin-only key",
        "landppt_base_url": "Admin-only key",
    }
    update.assert_awaited_once_with({"openai_model": "gpt-x"}, user_id=7, allow_admin_only=False)


@pytest.mark.asyncio
async def test_web_update_config_category_rejects_admin_only_keys_for_non_admin(monkeypatch):
    from landppt.web.route_modules import config_routes

    update = AsyncMock(return_value=True)
    _patch_service_factory(monkeypatch, _service(update=update))

    request = SimpleNamespace(
        json=AsyncMock(
            return_value={
                "config": {
                    "github_client_id": "attacker-id",
                    "github_client_secret": "attacker-secret",
                }
            }
        )
    )

    result = await config_routes._update_config_category(
        category="oauth_settings", request=request, user=_user(is_admin=False)
    )

    assert result["success"] is False
    assert result["errors"] == {
        "github_client_id": "Admin-only key",
        "github_client_secret": "Admin-only key",
    }
    update.assert_not_awaited()


# ==================== Service layer: DbConfigService.update_config ====================

def _patched_db_service(monkeypatch):
    import landppt.database.database as database_mod
    import landppt.database.repositories as repo_mod
    from landppt.services.db_config_service import DatabaseConfigService

    captured = {"set_calls": []}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    class FakeRepo:
        def __init__(self, session):
            self.session = session

        async def set_config(self, **kwargs):
            captured["set_calls"].append(kwargs)

    monkeypatch.setattr(database_mod, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(repo_mod, "UserConfigRepository", FakeRepo)

    service = DatabaseConfigService()
    monkeypatch.setattr(service, "_reload_services_for_categories", lambda categories: None)
    return service, captured


@pytest.mark.asyncio
async def test_update_config_never_promotes_admin_only_keys_on_per_user_write(monkeypatch):
    service, captured = _patched_db_service(monkeypatch)

    ok = await service.update_config(
        {"landppt_base_url": "https://attacker.example/v1", "openai_model": "gpt-x"},
        user_id=7,
    )

    assert ok is True
    assert [call["key"] for call in captured["set_calls"]] == ["openai_model"]
    assert captured["set_calls"][0]["user_id"] == 7


@pytest.mark.asyncio
async def test_update_config_promotes_admin_only_keys_only_with_explicit_admin_flag(monkeypatch):
    service, captured = _patched_db_service(monkeypatch)

    ok = await service.update_config(
        {"landppt_base_url": "https://admin.example/v1", "openai_model": "gpt-x"},
        user_id=7,
        allow_admin_only=True,
    )

    assert ok is True
    writes = {call["key"]: call["user_id"] for call in captured["set_calls"]}
    assert writes == {"landppt_base_url": None, "openai_model": 7}


@pytest.mark.asyncio
async def test_update_config_system_scope_write_still_accepts_admin_only_keys(monkeypatch):
    service, captured = _patched_db_service(monkeypatch)

    ok = await service.update_config({"landppt_base_url": "https://admin.example/v1"}, user_id=None)

    assert ok is True
    assert [call["key"] for call in captured["set_calls"]] == ["landppt_base_url"]
    assert captured["set_calls"][0]["user_id"] is None
