"""
Linux Do OAuth routes for LandPPT
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional
from urllib.parse import quote
import logging

from .auth_service import get_auth_service, AuthService
from .middleware import get_current_user
from ..database.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/auth/linuxdo/login")
async def linuxdo_login(
    request: Request,
    redirect_url: str = "/dashboard",
    invite_code: Optional[str] = None,
):
    """Initiate Linux Do OAuth login"""
    logger.info("=== Linux Do OAuth login route called ===")
    
    from .linuxdo_oauth_service import (
        is_linuxdo_oauth_enabled,
        generate_state,
        store_oauth_state,
        build_authorization_url
    )
    
    # Check if already logged in
    user = get_current_user(request)
    if user:
        logger.info("User already logged in, redirecting to dashboard")
        return RedirectResponse(url="/dashboard", status_code=302)
    
    # Check if Linux Do OAuth is enabled
    enabled = is_linuxdo_oauth_enabled()
    logger.info(f"Linux Do OAuth enabled: {enabled}")
    if not enabled:
        logger.warning("Linux Do OAuth not enabled - check config")
        return RedirectResponse(
            url="/auth/login?error=Linux Do登录未启用",
            status_code=302
        )
    
    # Generate state for CSRF protection
    state = generate_state()
    
    # Store state
    await store_oauth_state(state, redirect_url, invite_code=invite_code)
    
    # Build authorization URL and redirect
    auth_url = build_authorization_url(state)
    
    logger.info(f"Redirecting to Linux Do OAuth: state={state[:8]}..., url={auth_url[:80]}...")
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/auth/linuxdo/callback")
async def linuxdo_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Handle Linux Do OAuth callback"""
    from .linuxdo_oauth_service import (
        is_linuxdo_oauth_enabled,
        get_and_consume_oauth_state,
        exchange_code_for_token,
        get_linuxdo_user_info,
        get_or_create_user_by_linuxdo
    )
    
    # Handle OAuth errors
    if error:
        error_msg = error_description or error
        logger.warning(f"Linux Do OAuth error: {error_msg}")
        return RedirectResponse(
            url=f"/auth/login?error=Linux Do授权失败: {error_msg}",
            status_code=302
        )
    
    # Validate required parameters
    if not code or not state:
        return RedirectResponse(
            url="/auth/login?error=Linux Do授权参数缺失",
            status_code=302
        )
    
    # Check if Linux Do OAuth is enabled
    if not is_linuxdo_oauth_enabled():
        return RedirectResponse(
            url="/auth/login?error=Linux Do登录未启用",
            status_code=302
        )
    
    # Get and validate state
    state_data = await get_and_consume_oauth_state(state)
    if not state_data:
        logger.warning(f"Invalid or expired OAuth state: {state[:8]}...")
        return RedirectResponse(
            url="/auth/login?error=授权请求已过期，请重试",
            status_code=302
        )
    
    redirect_url = state_data.get("redirect_url", "/dashboard")
    invite_code = state_data.get("invite_code")
    
    # Exchange code for access token
    access_token = await exchange_code_for_token(code)
    if not access_token:
        return RedirectResponse(
            url="/auth/login?error=获取Linux Do访问令牌失败",
            status_code=302
        )
    
    # Get Linux Do user info
    linuxdo_user = await get_linuxdo_user_info(access_token)
    if not linuxdo_user:
        return RedirectResponse(
            url="/auth/login?error=获取Linux Do用户信息失败",
            status_code=302
        )
    
    # Get or create user
    user, _, error_message = get_or_create_user_by_linuxdo(
        db=db,
        linuxdo_id=linuxdo_user["id"],
        username=linuxdo_user["username"],
        email=linuxdo_user.get("email"),
        name=linuxdo_user.get("name"),
        avatar_url=linuxdo_user.get("avatar_url"),
        invite_code=invite_code,
    )
    
    if not user:
        return RedirectResponse(
            url=(
                f"/auth/login?tab=register&register_error={quote(error_message or '用户创建失败')}"
                f"&register_invite_code={quote(invite_code or '')}"
            ),
            status_code=302
        )
    
    # Create session
    session_id = auth_service.create_session(db, user)
    
    # Redirect with session cookie
    response = RedirectResponse(url=redirect_url, status_code=302)
    
    current_expire_minutes = auth_service._get_current_expire_minutes()
    cookie_max_age = None if current_expire_minutes == 0 else current_expire_minutes * 60
    
    response.set_cookie(
        key="session_id",
        value=session_id,
        max_age=cookie_max_age,
        httponly=True,
        secure=False,
        samesite="lax"
    )
    
    logger.info(f"User {user.username} logged in via Linux Do OAuth (linuxdo_id={linuxdo_user['id']})")
    return response
