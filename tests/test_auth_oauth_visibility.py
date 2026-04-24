import importlib
import sys
import types

import pytest
from starlette.requests import Request

class _CaptureTemplates:
    def __init__(self):
        self.calls = []

    def TemplateResponse(self, template_name, context):
        self.calls.append((template_name, context))
        return {
            "template_name": template_name,
            "context": context,
        }


def _import_auth_routes(monkeypatch):
    import fastapi.templating

    class _DummyTemplates:
        def __init__(self, *args, **kwargs):
            self.env = types.SimpleNamespace(globals={})

        def TemplateResponse(self, *args, **kwargs):
            raise AssertionError("测试中应替换为捕获模板对象")

    monkeypatch.setattr(fastapi.templating, "Jinja2Templates", _DummyTemplates)
    sys.modules.pop("landppt.auth.routes", None)
    return importlib.import_module("landppt.auth.routes")


def _build_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


def _patch_common_dependencies(monkeypatch, auth_routes, config):
    from landppt.database import database as database_module
    from landppt.database import repositories as repositories_module

    templates = _CaptureTemplates()
    monkeypatch.setattr(auth_routes, "templates", templates)
    monkeypatch.setattr(auth_routes, "get_current_user", lambda request: None)
    monkeypatch.setattr(auth_routes, "_turnstile_template_ctx", lambda: {})

    async def _fake_registration_template_ctx():
        return {"invite_code_required_for_registration": True}

    monkeypatch.setattr(auth_routes, "_registration_template_ctx", _fake_registration_template_ctx)

    class _FakeAsyncSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeUserConfigRepository:
        def __init__(self, session):
            self.session = session

        async def get_all_configs(self, user_id=None):
            return {
                key: {"value": value}
                for key, value in config.items()
            }

    monkeypatch.setattr(
        database_module,
        "AsyncSessionLocal",
        lambda: _FakeAsyncSession(),
    )
    monkeypatch.setattr(repositories_module, "UserConfigRepository", _FakeUserConfigRepository)
    return templates


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page_func_name", "path", "template_name"),
    [
        ("login_page", "/auth/login", "pages/auth/login.html"),
        ("register_page", "/auth/register", "pages/auth/register.html"),
    ],
)
async def test_auth_pages_hide_oauth_buttons_when_provider_disabled(
    monkeypatch,
    page_func_name,
    path,
    template_name,
):
    auth_routes = _import_auth_routes(monkeypatch)
    page_func = getattr(auth_routes, page_func_name)
    templates = _patch_common_dependencies(
        monkeypatch,
        auth_routes,
        {
            "github_oauth_enabled": False,
            "github_client_id": "github-client-id",
            "github_client_secret": "github-client-secret",
            "linuxdo_oauth_enabled": False,
            "linuxdo_client_id": "linuxdo-client-id",
            "linuxdo_client_secret": "linuxdo-client-secret",
            "authentik_oauth_enabled": False,
            "authentik_client_id": "authentik-client-id",
            "authentik_client_secret": "authentik-client-secret",
            "authentik_issuer_url": "https://auth.example.com/application/o/landppt",
        },
    )

    response = await page_func(_build_request(path))

    assert response["template_name"] == template_name
    assert templates.calls
    context = response["context"]
    assert context["github_oauth_enabled"] is False
    assert context["linuxdo_oauth_enabled"] is False
    assert context["authentik_oauth_enabled"] is False


@pytest.mark.asyncio
async def test_oauth_template_ctx_requires_complete_credentials_before_showing_button(monkeypatch):
    auth_routes = _import_auth_routes(monkeypatch)
    _patch_common_dependencies(
        monkeypatch,
        auth_routes,
        {
            "github_oauth_enabled": True,
            "github_client_id": "github-client-id",
            "github_client_secret": "",
            "linuxdo_oauth_enabled": True,
            "linuxdo_client_id": "linuxdo-client-id",
            "linuxdo_client_secret": "",
            "authentik_oauth_enabled": True,
            "authentik_client_id": "authentik-client-id",
            "authentik_client_secret": "authentik-client-secret",
            "authentik_issuer_url": "",
        },
    )

    flags = await auth_routes._load_system_oauth_flags()

    assert flags == {
        "github_oauth_enabled": False,
        "linuxdo_oauth_enabled": False,
        "authentik_oauth_enabled": False,
    }
