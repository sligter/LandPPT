"""
Authentication middleware for LandPPT
"""

from typing import Optional, Callable
from fastapi import Request, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import logging

from .auth_service import get_auth_service
from ..database.database import get_db
from ..database.models import User
from ..core.config import app_config
from .request_context import current_base_url, current_user_id, resolve_request_base_url

logger = logging.getLogger(__name__)


def _is_api_path(path: str) -> bool:
    """Detect API-style paths that should return JSON auth errors."""
    return (
        path == "/api"
        or path.startswith("/api/")
        or path == "/v1"
        or path.startswith("/v1/")
    )


def _extract_api_key(request: Request) -> Optional[str]:
    """
    Extract machine API key from request headers.
    Supported headers:
    - Authorization: Bearer <key>
    - X-API-Key: <key>
    """
    auth_header = (request.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    api_key = (request.headers.get("x-api-key") or "").strip()
    return api_key or None


def _extract_session_id(request: Request) -> Optional[str]:
    """Extract session ID from cookie first, then optional X-Session-Id header."""
    cookie_session = (request.cookies.get("session_id") or "").strip()
    if cookie_session:
        return cookie_session

    if not app_config.allow_header_session_auth:
        return None

    header_session = (request.headers.get("x-session-id") or "").strip()
    return header_session or None


class AuthMiddleware:
    """Authentication middleware"""
    
    def __init__(self):
        self.auth_service = get_auth_service()
        # 不需要认证的路径
        self.public_paths = {
            "/",
            "/health",
            "/auth/login",
            "/auth/logout",
            "/auth/github/login",
            "/auth/github/callback",
            "/auth/linuxdo/login",
            "/auth/linuxdo/callback",
            "/auth/register",
            "/auth/forgot-password",
            "/auth/reset-password",
            "/auth/api/send-code",
            "/sponsors",
            "/api/community/public-settings",
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/check",
            "/static",
            "/favicon.ico"
        }

        # 不需要认证的路径前缀
        self.public_prefixes = [
            "/static/",
            "/temp/",  # 添加temp目录用于图片缓存访问
            "/api/image/view/",  # 图床图片访问无需认证
            "/api/image/thumbnail/",  # 图片缩略图访问无需认证
            "/share/",  # 公开分享链接无需认证
            "/api/share/",  # 分享API无需认证
        ]
    
    def is_public_path(self, path: str) -> bool:
        """Check if path is public (doesn't require authentication)"""
        # Check exact matches
        if path in self.public_paths:
            return True
        
        # Check prefixes
        for prefix in self.public_prefixes:
            if path.startswith(prefix):
                return True
        
        return False

    def should_resolve_optional_user(self, path: str) -> bool:
        """公开页尽量识别当前用户，避免模板导航与真实登录态不一致。"""
        if _is_api_path(path):
            return False

        if path == "/favicon.ico":
            return False

        return not path.startswith(("/static/", "/temp/"))

    def _resolve_request_user(self, request: Request, db: Session) -> Optional[User]:
        """统一解析当前请求用户，供公开页与受保护页复用。"""
        api_key = _extract_api_key(request)
        if api_key:
            user = self.auth_service.get_user_by_api_key(db, api_key)
            if user:
                return user

        session_id = _extract_session_id(request)
        if session_id:
            return self.auth_service.get_user_by_session(db, session_id)

        return None

    async def _get_user_from_session_cache(self, session_id: Optional[str]) -> Optional[User]:
        """Resolve a user from cached session state without touching the database."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return None

        try:
            from ..services.cache_service import get_cache_service

            cache = await get_cache_service()
            if not cache or not cache.is_connected:
                return None

            payload = await cache.get_session(normalized_session_id)
            user = self.auth_service.user_from_session_cache(payload)
            if not self.auth_service.is_cached_session_valid(payload, user):
                if payload:
                    await cache.delete_session(normalized_session_id)
                return None

            ttl = self.auth_service.get_session_cache_ttl((payload or {}).get("expires_at"))
            await cache.refresh_session(normalized_session_id, ttl=ttl)
            return user
        except Exception as exc:
            logger.debug("Session cache lookup failed for %s: %s", normalized_session_id, exc)
            return None
    
    async def __call__(self, request: Request, call_next: Callable):
        """Middleware function"""
        # Ensure request-scoped user context is always initialized/reset
        ctx_token = current_user_id.set(None)
        base_url_token = current_base_url.set(resolve_request_base_url(request))
        path = request.url.path
        is_api_request = _is_api_path(path)
        session_cookie = request.cookies.get("session_id")
        try:
            # 模板层会读取 request.state.user，这里统一初始化，避免未设置时报错。
            request.state.user = None

            # Skip authentication for public paths
            if self.is_public_path(path):
                if self.should_resolve_optional_user(path):
                    try:
                        db = None
                        db_gen = None

                        def ensure_db():
                            nonlocal db, db_gen
                            if db is None:
                                db_gen = get_db()
                                db = next(db_gen)
                            return db

                        try:
                            user: Optional[User] = None
                            session_id = _extract_session_id(request)
                            if session_id:
                                user = await self._get_user_from_session_cache(session_id)

                            if not user:
                                user = self._resolve_request_user(request, ensure_db())

                            if user:
                                request.state.user = user
                                current_user_id.set(user.id)
                        finally:
                            if db is not None:
                                db.close()
                    except Exception as exc:
                        # 公开页不应因可选登录态识别失败而中断访问。
                        logger.debug("Optional auth resolution failed for public path %s: %s", path, exc)

                response = await call_next(request)
                return response

            try:
                db = None
                db_gen = None

                def ensure_db():
                    nonlocal db, db_gen
                    if db is None:
                        db_gen = get_db()
                        db = next(db_gen)
                    return db

                try:
                    user: Optional[User] = None
                    session_id = _extract_session_id(request)
                    if session_id:
                        user = await self._get_user_from_session_cache(session_id)

                    if not user:
                        user = self._resolve_request_user(request, ensure_db())

                    if not user:
                        # Unauthenticated request
                        if is_api_request:
                            return Response(
                                content='{"detail": "Authentication required"}',
                                status_code=401,
                                media_type="application/json"
                            )
                        else:
                            response = RedirectResponse(url="/auth/login", status_code=302)
                            # If cookie-based session is present but invalid, clear it.
                            if session_cookie:
                                response.delete_cookie("session_id")
                            return response

                    # Add user to request state and request context
                    request.state.user = user
                    current_user_id.set(user.id)

                    # Continue with request
                    response = await call_next(request)
                    return response

                finally:
                    if db is not None:
                        db.close()

            except Exception as e:
                logger.error(f"Authentication middleware error: {e}")
                if is_api_request:
                    return Response(
                        content='{"detail": "Authentication error"}',
                        status_code=500,
                        media_type="application/json"
                    )
                else:
                    return RedirectResponse(url="/auth/login", status_code=302)
        finally:
            current_base_url.reset(base_url_token)
            current_user_id.reset(ctx_token)


def get_current_user(request: Request) -> Optional[User]:
    """Get current authenticated user from request"""
    return getattr(request.state, 'user', None)


def require_auth(request: Request) -> User:
    """Dependency to require authentication"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(request: Request) -> User:
    """Dependency to require admin privileges"""
    user = require_auth(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Get current user if authenticated, None otherwise.
    For use with FastAPI dependency injection.
    """
    # Prefer middleware-resolved user.
    state_user = get_current_user(request)
    if state_user:
        return state_user

    auth_service = get_auth_service()

    # Try machine API key auth.
    api_key = _extract_api_key(request)
    if api_key:
        user = auth_service.get_user_by_api_key(db, api_key)
        if user:
            request.state.user = user
            return user

    # Fallback to session auth.
    session_id = _extract_session_id(request)
    if not session_id:
        return None

    user = auth_service.get_user_by_session(db, session_id)
    if user:
        request.state.user = user
    return user


def get_current_user_required(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Get current user, raise exception if not authenticated.
    For use with FastAPI dependency injection.
    """
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def get_current_admin_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Get current admin user, raise exception if not admin.
    For use with FastAPI dependency injection.
    """
    user = get_current_user_required(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def create_auth_middleware() -> AuthMiddleware:
    """Create authentication middleware instance"""
    return AuthMiddleware()


# Utility functions for templates
def is_authenticated(request: Request) -> bool:
    """Check if user is authenticated"""
    return get_current_user(request) is not None


def is_admin(request: Request) -> bool:
    """Check if user is admin"""
    user = get_current_user(request)
    return user is not None and user.is_admin


def get_user_info(request: Request) -> Optional[dict]:
    """Get user info for templates"""
    user = get_current_user(request)
    if user:
        return user.to_dict()
    return None
