"""
Authentik OAuth routes for LandPPT
"""

from typing import Optional
from urllib.parse import quote
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .auth_service import AuthService, get_auth_service
from .middleware import get_current_user
from ..database.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/auth/authentik/login")
async def authentik_login(
    request: Request,
    redirect_url: str = "/dashboard",
    invite_code: Optional[str] = None,
):
    """Initiate Authentik OAuth login"""
    from .authentik_oauth_service import (
        build_authorization_url,
        generate_state,
        is_authentik_oauth_enabled,
        store_oauth_state,
    )

    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)

    if not is_authentik_oauth_enabled():
        return RedirectResponse(
            url="/auth/login?error=Authentik登录未启用",
            status_code=302,
        )

    state = generate_state()
    await store_oauth_state(state, redirect_url, invite_code=invite_code)
    auth_url = build_authorization_url(state)

    logger.info("Redirecting to Authentik OAuth: state=%s...", state[:8])
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/auth/authentik/callback")
async def authentik_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Handle Authentik OAuth callback"""
    from .authentik_oauth_service import (
        exchange_code_for_token,
        get_and_consume_oauth_state,
        get_authentik_user_info,
        get_or_create_user_by_authentik,
        is_authentik_oauth_enabled,
    )

    if error:
        error_msg = error_description or error
        logger.warning("Authentik OAuth error: %s", error_msg)
        return RedirectResponse(
            url=f"/auth/login?error=Authentik授权失败: {error_msg}",
            status_code=302,
        )

    if not code or not state:
        return RedirectResponse(
            url="/auth/login?error=Authentik授权参数缺失",
            status_code=302,
        )

    if not is_authentik_oauth_enabled():
        return RedirectResponse(
            url="/auth/login?error=Authentik登录未启用",
            status_code=302,
        )

    state_data = await get_and_consume_oauth_state(state)
    if not state_data:
        return RedirectResponse(
            url="/auth/login?error=授权请求已过期，请重试",
            status_code=302,
        )

    redirect_url = state_data.get("redirect_url", "/dashboard")
    invite_code = state_data.get("invite_code")

    access_token = await exchange_code_for_token(code)
    if not access_token:
        return RedirectResponse(
            url="/auth/login?error=获取Authentik访问令牌失败",
            status_code=302,
        )

    authentik_user = await get_authentik_user_info(access_token)
    if not authentik_user:
        return RedirectResponse(
            url="/auth/login?error=获取Authentik用户信息失败",
            status_code=302,
        )

    user, _, error_message = get_or_create_user_by_authentik(
        db=db,
        authentik_sub=authentik_user["sub"],
        username=authentik_user["username"],
        email=authentik_user.get("email"),
        name=authentik_user.get("name"),
        avatar_url=authentik_user.get("avatar_url"),
        invite_code=invite_code,
    )

    if not user:
        return RedirectResponse(
            url=(
                f"/auth/login?tab=register&register_error={quote(error_message or '用户创建失败')}"
                f"&register_invite_code={quote(invite_code or '')}"
            ),
            status_code=302,
        )

    session_id = auth_service.create_session(db, user)
    response = RedirectResponse(url=redirect_url, status_code=302)

    current_expire_minutes = auth_service._get_current_expire_minutes()
    cookie_max_age = None if current_expire_minutes == 0 else current_expire_minutes * 60

    response.set_cookie(
        key="session_id",
        value=session_id,
        max_age=cookie_max_age,
        httponly=True,
        secure=False,
        samesite="lax",
    )

    logger.info("User %s logged in via Authentik OAuth (sub=%s)", user.username, authentik_user["sub"])
    return response
