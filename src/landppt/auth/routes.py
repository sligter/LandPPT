"""
Authentication routes for LandPPT
"""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import logging
import time
from typing import Optional
from pydantic import BaseModel, Field, ValidationError

from .auth_service import get_auth_service, AuthService
from .middleware import get_current_user_optional, get_current_user_required, get_current_user
from ..database.database import get_db
from ..database.models import User
from ..core.config import app_config

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="src/landppt/web/templates")


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _is_oauth_provider_visible(
    system_config: dict,
    *,
    enabled_key: str,
    client_id_key: str,
    client_secret_key: str,
    fallback_enabled,
    fallback_client_id,
    fallback_client_secret,
) -> bool:
    enabled_value = system_config[enabled_key] if enabled_key in system_config else fallback_enabled
    client_id_value = system_config[client_id_key] if client_id_key in system_config else fallback_client_id
    client_secret_value = system_config[client_secret_key] if client_secret_key in system_config else fallback_client_secret
    enabled = _as_bool(enabled_value)
    client_id = str(client_id_value or "").strip()
    client_secret = str(client_secret_value or "").strip()
    return enabled and bool(client_id) and bool(client_secret)


async def _load_system_oauth_flags() -> dict:
    """Load effective system OAuth flags from DB config with app_config fallback."""
    try:
        from ..database.database import AsyncSessionLocal
        from ..database.repositories import UserConfigRepository

        async with AsyncSessionLocal() as session:
            repo = UserConfigRepository(session)
            raw_system_config = await repo.get_all_configs(user_id=None)
        system_config = {
            key: item.get("value")
            for key, item in raw_system_config.items()
        }
    except Exception as exc:
        logger.warning("Failed to load OAuth flags from system config: %s", exc)
        system_config = {}

    return {
        "github_oauth_enabled": _is_oauth_provider_visible(
            system_config,
            enabled_key="github_oauth_enabled",
            client_id_key="github_client_id",
            client_secret_key="github_client_secret",
            fallback_enabled=app_config.github_oauth_enabled,
            fallback_client_id=app_config.github_client_id,
            fallback_client_secret=app_config.github_client_secret,
        ),
        "linuxdo_oauth_enabled": _is_oauth_provider_visible(
            system_config,
            enabled_key="linuxdo_oauth_enabled",
            client_id_key="linuxdo_client_id",
            client_secret_key="linuxdo_client_secret",
            fallback_enabled=app_config.linuxdo_oauth_enabled,
            fallback_client_id=app_config.linuxdo_client_id,
            fallback_client_secret=app_config.linuxdo_client_secret,
        ),
        "authentik_oauth_enabled": (
            _is_oauth_provider_visible(
                system_config,
                enabled_key="authentik_oauth_enabled",
                client_id_key="authentik_client_id",
                client_secret_key="authentik_client_secret",
                fallback_enabled=app_config.authentik_oauth_enabled,
                fallback_client_id=app_config.authentik_client_id,
                fallback_client_secret=app_config.authentik_client_secret,
            )
            and bool(
                str(
                    system_config.get("authentik_issuer_url")
                    or app_config.authentik_issuer_url
                    or ""
                ).strip()
            )
        ),
    }


def _get_client_ip(request: Request) -> Optional[str]:
    """
    Best-effort client IP extraction (supports reverse proxies / Cloudflare).
    """
    headers = request.headers
    ip = headers.get("cf-connecting-ip") or headers.get("x-real-ip")
    if ip:
        return ip.strip()
    xff = headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _turnstile_template_ctx() -> dict:
    from ..services.turnstile_service import is_turnstile_active

    enabled = is_turnstile_active()
    return {
        "turnstile_enabled": enabled,
        "turnstile_site_key": app_config.turnstile_site_key if enabled else None,
    }


async def _oauth_template_ctx() -> dict:
    """Common OAuth flags for templates."""
    return await _load_system_oauth_flags()


async def _registration_template_ctx() -> dict:
    """Dynamic registration flags shared by login/register templates."""
    from ..services.community_service import community_service

    try:
        settings = await community_service.get_settings()
        invite_required = bool(settings.get("invite_code_required_for_registration", True))
    except Exception as exc:
        logger.warning("Failed to load registration template settings: %s", exc)
        invite_required = True

    return {
        "invite_code_required_for_registration": invite_required,
    }


def _forgot_password_template_response(
    request: Request,
    *,
    email: str = "",
    error: Optional[str] = None,
    success: Optional[str] = None,
):
    return templates.TemplateResponse("pages/auth/forgot_password.html", {
        "request": request,
        "email": email,
        "error": error,
        "success": success,
        **_turnstile_template_ctx(),
    })


@router.get("/auth/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str = None,
    register_error: str = None,
    success: str = None,
    username: str = None,
    register_invite_code: str = None,
    tab: Optional[str] = None,
):
    """Login page"""
    # Check if user is already logged in using request.state.user set by middleware
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)

    active_tab = "login"
    if tab in {"login", "register"}:
        active_tab = tab
    if register_error:
        active_tab = "register"
    if error and active_tab != "register":
        active_tab = "login"
    registration_ctx = await _registration_template_ctx()

    return templates.TemplateResponse("pages/auth/login.html", {
        "request": request,
        "error": error,
        "register_error": register_error,
        "success": success,
        "username": username,
        "register_invite_code": register_invite_code,
        "active_tab": active_tab,
        **_turnstile_template_ctx(),
        **(await _oauth_template_ctx()),
        **registration_ctx,
    })


@router.post("/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Handle login form submission"""
    registration_ctx = await _registration_template_ctx()
    try:
        # Authenticate user
        user = auth_service.authenticate_user(db, username, password)
        
        if not user:
            return templates.TemplateResponse("pages/auth/login.html", {
                "request": request,
                "error": "用户名或密码错误",
                "username": username,
                "active_tab": "login",
                **_turnstile_template_ctx(),
                **(await _oauth_template_ctx()),
                **registration_ctx,
            })
        
        # Create session
        session_id = auth_service.create_session(db, user)

        # Best-effort update last login IP (requires DB columns)
        try:
            ip = _get_client_ip(request)
            if ip:
                user.last_login_ip = ip
                db.commit()
        except Exception:
            pass
        
        # Redirect to dashboard
        response = RedirectResponse(url="/dashboard", status_code=302)

        # Set cookie max_age based on session expiration
        # If session_expire_minutes is 0, set cookie to never expire (None means session cookie)
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
        
        logger.info(f"User {username} logged in successfully")
        return response
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return templates.TemplateResponse("pages/auth/login.html", {
            "request": request,
            "error": "登录过程中发生错误，请重试",
            "username": username,
            "active_tab": "login",
            **_turnstile_template_ctx(),
            **(await _oauth_template_ctx()),
            **registration_ctx,
        })


@router.get("/auth/logout")
async def logout(
    request: Request,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Logout user"""
    session_id = request.cookies.get("session_id")
    
    if session_id:
        auth_service.logout_user(db, session_id)
    
    response = RedirectResponse(url="/auth/login?success=已成功退出登录", status_code=302)
    response.delete_cookie("session_id")
    
    return response


@router.get("/auth/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """User profile page"""
    return templates.TemplateResponse("pages/account/profile.html", {
        "request": request,
        "user": user.to_dict(),
        "credits_enabled": app_config.enable_credits_system
    })


@router.post("/auth/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Change user password"""
    try:
        # Validate current password
        if not user.check_password(current_password):
            return templates.TemplateResponse("pages/account/profile.html", {
                "request": request,
                "user": user.to_dict(),
                "credits_enabled": app_config.enable_credits_system,
                "error": "当前密码错误"
            })
        
        # Validate new password
        if new_password != confirm_password:
            return templates.TemplateResponse("pages/account/profile.html", {
                "request": request,
                "user": user.to_dict(),
                "credits_enabled": app_config.enable_credits_system,
                "error": "新密码和确认密码不匹配"
            })
        
        if len(new_password) < 6:
            return templates.TemplateResponse("pages/account/profile.html", {
                "request": request,
                "user": user.to_dict(),
                "credits_enabled": app_config.enable_credits_system,
                "error": "密码长度至少6位"
            })
        
        # Update password
        if auth_service.update_user_password(db, user, new_password):
            return templates.TemplateResponse("pages/account/profile.html", {
                "request": request,
                "user": user.to_dict(),
                "credits_enabled": app_config.enable_credits_system,
                "success": "密码修改成功"
            })
        else:
            return templates.TemplateResponse("pages/account/profile.html", {
                "request": request,
                "user": user.to_dict(),
                "credits_enabled": app_config.enable_credits_system,
                "error": "密码修改失败，请重试"
            })
            
    except Exception as e:
        logger.error(f"Change password error: {e}")
        return templates.TemplateResponse("pages/account/profile.html", {
            "request": request,
            "user": user.to_dict(),
            "credits_enabled": app_config.enable_credits_system,
            "error": "修改密码过程中发生错误"
        })


# API endpoints for authentication
@router.post("/api/auth/login")
async def api_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """API login endpoint"""
    user = auth_service.authenticate_user(db, username, password)
    
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    session_id = auth_service.create_session(db, user)

    # Best-effort update last login IP (requires DB columns)
    try:
        ip = _get_client_ip(request)
        if ip:
            user.last_login_ip = ip
            db.commit()
    except Exception:
        pass
    
    return {
        "success": True,
        "session_id": session_id,
        "user": user.to_dict()
    }


@router.post("/api/auth/logout")
async def api_logout(
    request: Request,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """API logout endpoint"""
    session_id = request.cookies.get("session_id")
    
    if session_id:
        auth_service.logout_user(db, session_id)
    
    return {"success": True, "message": "已成功退出登录"}


@router.get("/api/auth/me")
async def api_current_user(
    user: User = Depends(get_current_user_required)
):
    """Get current user info"""
    return {
        "success": True,
        "user": user.to_dict()
    }


@router.get("/api/auth/check")
async def api_check_auth(
    request: Request,
    db: Session = Depends(get_db)
):
    """Check authentication status"""
    user = get_current_user_optional(request, db)
    
    return {
        "authenticated": user is not None,
        "user": user.to_dict() if user else None
    }


class UserAPIKeyCreateRequest(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=100)
    api_key: Optional[str] = Field(default=None, min_length=16, max_length=512)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=3650)


def _serialize_user_api_key(record) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "key_prefix": record.key_prefix,
        "key_preview": f"{record.key_prefix}***",
        "is_active": record.is_active,
        "created_at": record.created_at,
        "last_used_at": record.last_used_at,
        "expires_at": record.expires_at,
    }


@router.get("/api/auth/api-keys")
async def api_list_user_api_keys(
    include_inactive: bool = True,
    user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """List API keys for current user."""
    records = auth_service.list_user_api_keys(
        db=db,
        user_id=user.id,
        include_inactive=include_inactive,
    )
    return {
        "success": True,
        "api_keys": [_serialize_user_api_key(record) for record in records]
    }


@router.post("/api/auth/api-keys")
async def api_create_or_rotate_user_api_key(
    request: Request,
    user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Create or rotate one named API key for current user."""
    try:
        content_type = (request.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            payload_data = await request.json()
        else:
            form_data = await request.form()
            payload_data = dict(form_data)
        payload = UserAPIKeyCreateRequest.model_validate(payload_data or {})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid request body: {exc}")

    expires_at = None
    if payload.expires_in_days:
        expires_at = time.time() + (payload.expires_in_days * 86400)

    key_name = payload.name.strip()
    existed = auth_service.get_user_api_key_by_name(db, user.id, key_name) is not None

    try:
        record, plaintext = auth_service.create_or_update_user_api_key(
            db=db,
            user=user,
            key_name=key_name,
            raw_api_key=payload.api_key,
            expires_at=expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "rotated": existed,
        "api_key": plaintext,
        "api_key_record": _serialize_user_api_key(record),
    }


@router.delete("/api/auth/api-keys/{key_id}")
async def api_delete_user_api_key(
    key_id: int,
    user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Delete one API key by id for current user."""
    success = auth_service.delete_user_api_key(db=db, user_id=user.id, key_id=key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"success": True}


# ========== Registration Routes ==========


class SendCodeRequest(BaseModel):
    email: str
    code_type: str  # 'register' or 'reset'
    invite_code: Optional[str] = None
    turnstile_token: Optional[str] = None


# Add Jinja2 global for registration enabled
templates.env.globals["registration_enabled"] = app_config.enable_user_registration


@router.get("/auth/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    error: str = None,
    success: str = None,
    invite_code: str = None,
):
    """Registration page"""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    registration_ctx = await _registration_template_ctx()

    return templates.TemplateResponse("pages/auth/register.html", {
        "request": request,
        "error": error,
        "success": success,
        "invite_code": invite_code,
        "registration_enabled": app_config.enable_user_registration,
        **(await _oauth_template_ctx()),
        **registration_ctx,
        **_turnstile_template_ctx(),
    })


@router.post("/auth/register")
async def register(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    invite_code: Optional[str] = Form(default=None),
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    turnstile_token: Optional[str] = Form(default=None),
    ui: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Handle registration form submission"""
    from ..services.email_service import verify_code
    from ..services.community_service import community_service
    registration_ctx = await _registration_template_ctx()
    
    ctx = {
        "request": request,
        "email": email,
        "invite_code": invite_code or "",
        "username": username,
        "registration_enabled": app_config.enable_user_registration,
        **_turnstile_template_ctx(),
        **(await _oauth_template_ctx()),
        **registration_ctx,
    }

    async def render_register_error(message: str):
        # If registration was initiated from the combined login/register page,
        # keep the user on that page and show the error inline.
        if (ui or "").lower() in {"login", "combined"}:
            return templates.TemplateResponse("pages/auth/login.html", {
                "request": request,
                "active_tab": "register",
                "register_error": message,
                "register_email": email,
                "register_invite_code": invite_code or "",
                "register_username": username,
                **_turnstile_template_ctx(),
                **(await _oauth_template_ctx()),
                **registration_ctx,
            })
        ctx["error"] = message
        return templates.TemplateResponse("pages/auth/register.html", ctx)
    
    if not app_config.enable_user_registration:
        return await render_register_error("用户注册已关闭")

    # Basic IP rate limiting for registration attempts
    from ..utils.rate_limiter import hit as rate_limit_hit
    ip = _get_client_ip(request)
    if ip:
        allowed, _, reset_in = await rate_limit_hit(
            key=f"rl:register:{ip}",
            limit=app_config.registration_ip_rate_limit_per_hour,
            window_seconds=3600,
        )
        if not allowed:
            hint = f"（约 {reset_in} 秒后恢复）" if reset_in is not None else ""
            return await render_register_error(
                f"请求过于频繁：同一 IP 每小时最多 {app_config.registration_ip_rate_limit_per_hour} 次{hint}"
            )
    
    if password != confirm_password:
        return await render_register_error("两次密码输入不一致")
    
    if len(password) < 6:
        return await render_register_error("密码长度至少6位")
    
    if len(username) < 3:
        return await render_register_error("用户名至少3个字符")

    try:
        validated_invite = community_service.resolve_registration_invite(db, invite_code, "mail")
    except ValueError as exc:
        return await render_register_error(str(exc))

    # Verify email code
    success, message = await verify_code(email, code, 'register')
    if not success:
        return await render_register_error(message)
    
    # Check if username or email already exists
    existing_user = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()
    if existing_user:
        if existing_user.username == username:
            return await render_register_error("用户名已被使用")
        else:
            return await render_register_error("邮箱已被注册")
    
    try:
        # Create user
        user = auth_service.create_user(db, username, password, email, commit=False)
        if user:
            ip = _get_client_ip(request)
            if ip:
                user.register_ip = ip
            user.registration_channel = "mail"
            if validated_invite is not None:
                community_service.apply_invite_code_to_user(db, user, validated_invite, "mail")
            db.commit()
            db.refresh(user)
            logger.info(f"New user registered: {username} ({email})")
            return RedirectResponse(
                url="/auth/login?success=注册成功，请登录",
                status_code=302
            )
        else:
            return await render_register_error("注册失败，请重试")
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return await render_register_error(f"注册失败: {str(e)}")


@router.get("/auth/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(
    request: Request,
    error: str = None,
    success: str = None
):
    """Forgot password page"""
    return _forgot_password_template_response(
        request,
        error=error,
        success=success,
    )


@router.post("/auth/reset-password")
async def reset_password(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle password reset form submission"""
    from ..services.email_service import verify_code

    if new_password != confirm_password:
        return _forgot_password_template_response(
            request,
            email=email,
            error="两次密码输入不一致",
        )

    if len(new_password) < 6:
        return _forgot_password_template_response(
            request,
            email=email,
            error="密码长度至少6位",
        )

    # Verify email code
    success, message = await verify_code(email, code, 'reset')
    if not success:
        return _forgot_password_template_response(
            request,
            email=email,
            error=message,
        )

    # Find user by email
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return _forgot_password_template_response(
            request,
            email=email,
            error="该邮箱未注册",
        )

    try:
        # Update password
        user.set_password(new_password)
        db.commit()
        await get_auth_service().invalidate_user_sessions_cache(user.id)
        logger.info(f"Password reset for user: {user.username}")
        return RedirectResponse(
            url="/auth/login?success=密码重置成功，请登录",
            status_code=302
        )
    except Exception as e:
        logger.error(f"Password reset error: {e}")
        return _forgot_password_template_response(
            request,
            email=email,
            error=f"密码重置失败: {str(e)}",
        )


@router.post("/auth/api/send-code")
async def api_send_code(request: Request, request_data: SendCodeRequest, db: Session = Depends(get_db)):
    """API endpoint to send verification code"""
    from ..services.email_service import send_verification_email
    from ..services.turnstile_service import is_turnstile_active, verify_turnstile
    
    email = request_data.email.strip().lower()
    code_type = request_data.code_type
    
    if code_type not in ['register', 'reset']:
        return {"success": False, "message": "无效的验证码类型"}
    
    # For registration, check if email already exists
    if code_type == 'register':
        from ..services.community_service import community_service
        from ..utils.rate_limiter import hit as rate_limit_hit
        ip = _get_client_ip(request)
        if ip:
            allowed, _, reset_in = await rate_limit_hit(
                key=f"rl:register:{ip}",
                limit=app_config.registration_ip_rate_limit_per_hour,
                window_seconds=3600,
            )
            if not allowed:
                hint = f"（约 {reset_in} 秒后恢复）" if reset_in is not None else ""
                return {
                    "success": False,
                    "message": f"请求过于频繁：同一 IP 每小时最多 {app_config.registration_ip_rate_limit_per_hour} 次{hint}",
                }

        if is_turnstile_active():
            ok, msg = await verify_turnstile(request_data.turnstile_token, _get_client_ip(request))
            if not ok:
                return {"success": False, "message": msg}
        if not app_config.enable_user_registration:
            return {"success": False, "message": "用户注册已关闭"}
        try:
            community_service.resolve_registration_invite(db, request_data.invite_code, "mail")
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return {"success": False, "message": "该邮箱已被注册"}
    
    # For password reset, check if email exists
    if code_type == 'reset':
        if is_turnstile_active():
            ok, msg = await verify_turnstile(request_data.turnstile_token, _get_client_ip(request))
            if not ok:
                return {"success": False, "message": msg}
        existing = db.query(User).filter(User.email == email).first()
        if not existing:
            return {"success": False, "message": "该邮箱未注册"}
    
    # Send verification email
    success, message = await send_verification_email(email, code_type)
    return {"success": success, "message": message}
