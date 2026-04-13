"""
GitHub OAuth routes with PKCE support for LandPPT
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


@router.get("/auth/github/login")
async def github_login(
    request: Request,
    redirect_url: str = "/dashboard",
    invite_code: Optional[str] = None,
):
    """Initiate GitHub OAuth login with PKCE"""
    logger.info("=== GitHub OAuth login route called ===")
    
    from .github_oauth_service import (
        is_github_oauth_enabled,
        generate_pkce_pair,
        generate_state,
        store_oauth_state,
        build_authorization_url,
        get_callback_url,
    )
    
    # Check if already logged in
    user = get_current_user(request)
    if user:
        logger.info("User already logged in, redirecting to dashboard")
        return RedirectResponse(url="/dashboard", status_code=302)
    
    # Check if GitHub OAuth is enabled
    enabled = is_github_oauth_enabled()
    logger.info(f"GitHub OAuth enabled: {enabled}")
    if not enabled:
        logger.warning("GitHub OAuth not enabled - check config")
        return RedirectResponse(
            url="/auth/login?error=GitHub登录未启用",
            status_code=302
        )
    
    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()
    
    # Generate state for CSRF protection
    state = generate_state()
    callback_url = get_callback_url(request)
    
    # Store state with code_verifier
    await store_oauth_state(
        state,
        code_verifier,
        redirect_url,
        callback_url=callback_url,
        invite_code=invite_code,
    )
    
    # Build authorization URL and redirect
    auth_url = build_authorization_url(state, code_challenge, callback_url=callback_url)
    
    logger.info(f"Redirecting to GitHub OAuth: state={state[:8]}..., callback_url={callback_url}")
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/auth/github/callback")
async def github_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Handle GitHub OAuth callback with PKCE verification"""
    from .github_oauth_service import (
        is_github_oauth_enabled,
        get_and_consume_oauth_state,
        exchange_code_for_token,
        get_github_user_info,
        get_or_create_user_by_github,
        get_callback_url,
    )
    
    # Handle OAuth errors from GitHub
    if error:
        error_msg = error_description or error
        logger.warning(f"GitHub OAuth error: {error_msg}")
        return RedirectResponse(
            url=f"/auth/login?error=GitHub授权失败: {error_msg}",
            status_code=302
        )
    
    # Validate required parameters
    if not code or not state:
        return RedirectResponse(
            url="/auth/login?error=GitHub授权参数缺失",
            status_code=302
        )
    
    # Check if GitHub OAuth is enabled
    if not is_github_oauth_enabled():
        return RedirectResponse(
            url="/auth/login?error=GitHub登录未启用",
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
    
    code_verifier = state_data.get("code_verifier")
    redirect_url = state_data.get("redirect_url", "/dashboard")
    callback_url = state_data.get("callback_url") or get_callback_url(request)
    invite_code = state_data.get("invite_code")
    
    # Exchange code for access token with PKCE
    access_token = await exchange_code_for_token(code, code_verifier, callback_url=callback_url)
    if not access_token:
        return RedirectResponse(
            url="/auth/login?error=获取GitHub访问令牌失败",
            status_code=302
        )
    
    # Get GitHub user info
    github_user = await get_github_user_info(access_token)
    if not github_user:
        return RedirectResponse(
            url="/auth/login?error=获取GitHub用户信息失败",
            status_code=302
        )
    
    # Get or create user
    user, _, error_message = get_or_create_user_by_github(
        db=db,
        github_id=github_user["id"],
        github_login=github_user["login"],
        email=github_user.get("email"),
        name=github_user.get("name"),
        avatar_url=github_user.get("avatar_url"),
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
    
    # Redirect to dashboard with session cookie
    response = RedirectResponse(url=redirect_url, status_code=302)
    
    # Set cookie max_age based on session expiration
    current_expire_minutes = auth_service._get_current_expire_minutes()
    cookie_max_age = None if current_expire_minutes == 0 else current_expire_minutes * 60
    
    response.set_cookie(
        key="session_id",
        value=session_id,
        max_age=cookie_max_age,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax"
    )
    
    logger.info(f"User {user.username} logged in via GitHub OAuth (github_id={github_user['id']})")
    return response
