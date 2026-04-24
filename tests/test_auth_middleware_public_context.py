import pytest
from starlette.requests import Request
from starlette.responses import Response

from landppt.auth import middleware as auth_middleware_module
from landppt.auth.middleware import AuthMiddleware


class _FakeUser:
    def __init__(self, user_id: int = 1, is_admin: bool = False):
        self.id = user_id
        self.is_admin = is_admin


class _FakeAuthService:
    def __init__(self, user=None):
        self.user = user
        self.session_calls = []
        self.api_key_calls = []

    def get_user_by_api_key(self, db, api_key):
        self.api_key_calls.append(api_key)
        return None

    def get_user_by_session(self, db, session_id):
        self.session_calls.append(session_id)
        return self.user


def _build_request(path: str, cookie: str = "") -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


async def _fake_cached_session_none(session_id):
    return None


async def _fake_call_next(request: Request) -> Response:
    return Response(content="ok", media_type="text/plain")


def _fake_get_db():
    yield object()


@pytest.mark.asyncio
async def test_public_page_populates_request_state_user_when_session_is_valid(monkeypatch):
    middleware = AuthMiddleware()
    middleware.auth_service = _FakeAuthService(user=_FakeUser(user_id=7))
    monkeypatch.setattr(middleware, "_get_user_from_session_cache", _fake_cached_session_none)
    monkeypatch.setattr(auth_middleware_module, "get_db", _fake_get_db)

    request = _build_request("/sponsors", "session_id=valid-session")
    response = await middleware(request, _fake_call_next)

    assert response.status_code == 200
    assert request.state.user is not None
    assert request.state.user.id == 7
    assert middleware.auth_service.session_calls == ["valid-session"]


@pytest.mark.asyncio
async def test_public_page_skips_optional_auth_for_static_assets(monkeypatch):
    middleware = AuthMiddleware()
    middleware.auth_service = _FakeAuthService(user=_FakeUser(user_id=9))
    monkeypatch.setattr(middleware, "_get_user_from_session_cache", _fake_cached_session_none)
    monkeypatch.setattr(auth_middleware_module, "get_db", _fake_get_db)

    request = _build_request("/static/images/logo.png", "session_id=valid-session")
    response = await middleware(request, _fake_call_next)

    assert response.status_code == 200
    assert request.state.user is None
    assert middleware.auth_service.session_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/auth/authentik/login", "/auth/authentik/callback"])
async def test_authentik_oauth_routes_are_public(monkeypatch, path):
    middleware = AuthMiddleware()
    middleware.auth_service = _FakeAuthService(user=None)
    monkeypatch.setattr(middleware, "_get_user_from_session_cache", _fake_cached_session_none)
    monkeypatch.setattr(auth_middleware_module, "get_db", _fake_get_db)

    request = _build_request(path)
    response = await middleware(request, _fake_call_next)

    assert response.status_code == 200
