# 保持此模块轻量，避免在最小化或测试环境中导入 request_context 等子模块时
# 提前加载可选依赖，例如 SQLAlchemy。

from __future__ import annotations

from typing import Any

__all__ = [
    "AuthService",
    "get_auth_service",
    "init_default_admin",
    "AuthMiddleware",
    "create_auth_middleware",
    "get_current_user",
    "require_auth",
    "require_admin",
    "get_current_user_optional",
    "get_current_user_required",
    "get_current_admin_user",
    "is_authenticated",
    "is_admin",
    "get_user_info",
    "auth_router",
]


def __getattr__(name: str) -> Any:  # pragma: no cover
    if name in {"AuthService", "get_auth_service", "init_default_admin"}:
        from .auth_service import AuthService, get_auth_service, init_default_admin

        value = {"AuthService": AuthService, "get_auth_service": get_auth_service, "init_default_admin": init_default_admin}[name]
        globals()[name] = value
        return value

    middleware_exports = {
        "AuthMiddleware",
        "create_auth_middleware",
        "get_current_user",
        "require_auth",
        "require_admin",
        "get_current_user_optional",
        "get_current_user_required",
        "get_current_admin_user",
        "is_authenticated",
        "is_admin",
        "get_user_info",
    }
    if name in middleware_exports:
        from .middleware import (
            AuthMiddleware,
            create_auth_middleware,
            get_current_user,
            require_auth,
            require_admin,
            get_current_user_optional,
            get_current_user_required,
            get_current_admin_user,
            is_authenticated,
            is_admin,
            get_user_info,
        )

        value = locals()[name]
        globals()[name] = value
        return value

    if name == "auth_router":
        from fastapi import APIRouter

        from .routes import router as _base_auth_router

        try:
            from .github_oauth_routes import router as _github_oauth_router
        except Exception:
            _github_oauth_router = None

        try:
            from .linuxdo_oauth_routes import router as _linuxdo_oauth_router
        except Exception:
            _linuxdo_oauth_router = None

        try:
            from .authentik_oauth_routes import router as _authentik_oauth_router
        except Exception:
            _authentik_oauth_router = None

        auth_router = APIRouter()
        auth_router.include_router(_base_auth_router)
        if _github_oauth_router is not None:
            auth_router.include_router(_github_oauth_router)
        if _linuxdo_oauth_router is not None:
            auth_router.include_router(_linuxdo_oauth_router)
        if _authentik_oauth_router is not None:
            auth_router.include_router(_authentik_oauth_router)

        globals()["auth_router"] = auth_router
        return auth_router

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:  # pragma: no cover
    return sorted(set(globals().keys()) | set(__all__))

