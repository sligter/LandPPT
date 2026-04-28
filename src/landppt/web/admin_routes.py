"""
Admin routes for user management and system administration
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database.database import get_db, get_async_db, AsyncSessionLocal
from ..database.models import User, UserSession
from ..database.repositories import UserRepository, CreditTransactionRepository, RedemptionCodeRepository
from ..auth.middleware import get_current_user_required
from ..auth.auth_service import auth_service
from ..services.credits_service import CreditsService
from ..services.community_service import community_service
from ..core.config import app_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="src/landppt/web/templates")


# Request models
class UserCreateRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    is_admin: bool = False
    credits_balance: int = 0


class UserUpdateRequest(BaseModel):
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None


class CreditAdjustRequest(BaseModel):
    amount: int
    description: str


class RedemptionCodeCreateRequest(BaseModel):
    count: int = 1
    credits_amount: int
    description: Optional[str] = None
    expires_in_days: Optional[int] = None


class SMTPConfigRequest(BaseModel):
    email_provider: str = "smtp"  # smtp | resend
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = True
    smtp_from_email: str = ""
    smtp_from_name: str = "LandPPT"
    resend_api_key: str = ""
    resend_from_email: str = ""
    resend_from_name: str = "LandPPT"
    test_email: Optional[str] = None  # For test endpoint


class OAuthProviderSettings(BaseModel):
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    callback_url: Optional[str] = ""
    callback_use_request_host: Optional[bool] = False
    issuer_url: Optional[str] = ""


class OAuthSettingsRequest(BaseModel):
    github: OAuthProviderSettings
    linuxdo: OAuthProviderSettings
    authentik: OAuthProviderSettings


class CommunitySettingsRequest(BaseModel):
    daily_checkin_enabled: bool = False
    daily_checkin_reward_mode: str = "fixed"
    daily_checkin_reward_fixed: int = 5
    daily_checkin_reward_min: int = 2
    daily_checkin_reward_max: int = 8
    invite_code_required_for_registration: bool = True
    sponsor_page_enabled: bool = False
    site_notice_enabled: bool = False
    site_notice_level: str = "info"
    site_notice_title: str = ""
    site_notice_message: str = ""
    site_notice_start_at: Optional[float] = None
    site_notice_end_at: Optional[float] = None


class InviteCodeCreateRequest(BaseModel):
    count: int = 1
    channel: str
    credits_amount: int = 0
    max_uses: int = 1
    description: Optional[str] = None
    expires_in_days: Optional[int] = None


class InviteCodeUpdateRequest(BaseModel):
    channel: Optional[str] = None
    credits_amount: Optional[int] = None
    max_uses: Optional[int] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None
    expires_in_days: Optional[int] = None
    clear_expiration: bool = False


class SponsorCreateRequest(BaseModel):
    nickname: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    link_url: Optional[str] = None
    amount: Optional[str] = None
    note: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class SponsorUpdateRequest(BaseModel):
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    link_url: Optional[str] = None
    amount: Optional[str] = None
    note: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class SystemLandPptModelsRequest(BaseModel):
    api_key: str = ""
    base_url: str = ""


# Admin user dependency
async def get_admin_user_required(
    request: Request,
    user: User = Depends(get_current_user_required)
) -> User:
    """Require admin user"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# Redirect /admin to /admin/users
@router.get("", response_class=HTMLResponse)
async def admin_root(request: Request, user: User = Depends(get_admin_user_required)):
    """Redirect to admin users page"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/users", status_code=302)


# Admin pages
@router.get("/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    user: User = Depends(get_admin_user_required)
):

    """Admin user management page"""
    return templates.TemplateResponse(
        "pages/admin/users.html",
        {
            "request": request,
            "user": user,
            "credits_enabled": app_config.enable_credits_system
        }
    )


@router.get("/credits", response_class=HTMLResponse)
async def admin_credits_page(
    request: Request,
    user: User = Depends(get_admin_user_required)
):
    """Admin credits/points management page"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=404, detail="积分系统未启用")
    
    return templates.TemplateResponse(
        "pages/admin/credits.html",
        {
            "request": request,
            "user": user
        }
    )


@router.get("/smtp", response_class=HTMLResponse)
async def admin_smtp_page(
    request: Request,
    user: User = Depends(get_admin_user_required)
):
    """Admin SMTP settings page"""
    return templates.TemplateResponse(
        "pages/admin/smtp.html",
        {
            "request": request,
            "user": user,
            "credits_enabled": app_config.enable_credits_system
        }
    )


@router.get("/oauth", response_class=HTMLResponse)
async def admin_oauth_page(
    request: Request,
    user: User = Depends(get_admin_user_required)
):
    """Admin OAuth settings page"""
    return templates.TemplateResponse(
        "pages/admin/oauth.html",
        {
            "request": request,
            "user": user,
            "credits_enabled": app_config.enable_credits_system
        }
    )


@router.get("/community", response_class=HTMLResponse)
async def admin_community_page(
    request: Request,
    user: User = Depends(get_admin_user_required)
):
    """Admin community operations page."""
    return templates.TemplateResponse(
        "pages/admin/community.html",
        {
            "request": request,
            "user": user,
            "credits_enabled": app_config.enable_credits_system,
        }
    )


def _normalize_openai_compatible_base_url(
    base_url: Optional[str],
    default: str = "https://api.openai.com/v1",
) -> str:
    """规范化 OpenAI 兼容接口地址，避免把完整接口路径误当作 base URL。"""
    normalized = (base_url or "").strip() or default
    normalized = normalized.rstrip("/")

    for suffix in ("/chat/completions", "/responses", "/completions", "/models"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].rstrip("/")

    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"

    return normalized


def _extract_model_ids(payload: object) -> List[str]:
    """兼容不同 OpenAI 兼容服务的 models 返回结构。"""
    models: List[str] = []

    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        for item in payload.get("data", []):
            if isinstance(item, dict):
                model_id = str(item.get("id") or item.get("name") or "").strip()
                if model_id:
                    models.append(model_id)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                model_id = str(item.get("id") or item.get("name") or "").strip()
            else:
                model_id = str(item or "").strip()
            if model_id:
                models.append(model_id)

    unique_models = sorted(set(models), key=lambda item: item.lower())
    if "MODEL1" in unique_models:
        unique_models.remove("MODEL1")
        unique_models.insert(0, "MODEL1")
    return unique_models


async def _fetch_landppt_models_with_credentials(api_key: str, base_url: str, timeout_seconds: int) -> List[str]:
    """通过后端代理请求 LandPPT 模型列表。"""
    import aiohttp

    models_url = f"{_normalize_openai_compatible_base_url(base_url)}/models"

    async with aiohttp.ClientSession() as session:
        async with session.get(
            models_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error("Failed to fetch system LandPPT models: %s - %s", response.status, error_text)
                raise HTTPException(status_code=400, detail=f"获取模型列表失败: HTTP {response.status}")

            payload = await response.json(content_type=None)
            return _extract_model_ids(payload)


@router.post("/api/system-landppt-models")
async def get_system_landppt_models(
    data: SystemLandPptModelsRequest,
    user: User = Depends(get_admin_user_required),
):
    """优先使用后台当前表单值代理拉取 LandPPT 模型列表。"""
    from ..services.db_config_service import get_db_config_service, get_user_llm_timeout_seconds

    try:
        config_service = get_db_config_service()
        system_config = await config_service.get_all_config(user_id=None)

        api_key = (data.api_key or "").strip() or str(system_config.get("landppt_api_key") or "").strip()
        base_url = (data.base_url or "").strip() or str(system_config.get("landppt_base_url") or "").strip()

        if not api_key:
            return {"success": False, "error": "请先填写 LandPPT API Key", "models": []}

        timeout_seconds = await get_user_llm_timeout_seconds(user.id)
        models = await _fetch_landppt_models_with_credentials(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

        return {
            "success": True,
            "models": models,
            "base_url": _normalize_openai_compatible_base_url(base_url),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to fetch system LandPPT models: %s", exc)
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {exc}")


@router.get("/api/smtp")
async def get_smtp_config(
    user: User = Depends(get_admin_user_required)
):
    """Get current SMTP configuration"""
    return {
        "success": True,
        "config": {
            "email_provider": app_config.email_provider,
            "smtp_host": app_config.smtp_host,
            "smtp_port": app_config.smtp_port,
            "smtp_user": app_config.smtp_user,
            "smtp_password": app_config.smtp_password,
            "smtp_use_ssl": app_config.smtp_use_ssl,
            "smtp_from_email": app_config.smtp_from_email,
            "smtp_from_name": app_config.smtp_from_name,
            "resend_api_key": app_config.resend_api_key,
            "resend_from_email": app_config.resend_from_email,
            "resend_from_name": app_config.resend_from_name,
        }
    }


@router.get("/api/oauth")
async def get_oauth_config(
    user: User = Depends(get_admin_user_required)
):
    """Get current OAuth configuration from system config."""
    from ..services.db_config_service import get_db_config_service

    config_service = get_db_config_service()
    system_config = await config_service.get_all_config(user_id=None)

    return {
        "success": True,
        "config": {
            "github": {
                "enabled": bool(system_config.get("github_oauth_enabled", app_config.github_oauth_enabled)),
                "client_id": str(system_config.get("github_client_id") or app_config.github_client_id or ""),
                "client_secret": str(system_config.get("github_client_secret") or app_config.github_client_secret or ""),
                "callback_url": str(system_config.get("github_callback_url") or app_config.github_callback_url or ""),
                "callback_use_request_host": bool(
                    system_config.get(
                        "github_callback_use_request_host",
                        getattr(app_config, "github_callback_use_request_host", False),
                    )
                ),
            },
            "linuxdo": {
                "enabled": bool(system_config.get("linuxdo_oauth_enabled", app_config.linuxdo_oauth_enabled)),
                "client_id": str(system_config.get("linuxdo_client_id") or app_config.linuxdo_client_id or ""),
                "client_secret": str(system_config.get("linuxdo_client_secret") or app_config.linuxdo_client_secret or ""),
                "callback_url": str(system_config.get("linuxdo_callback_url") or app_config.linuxdo_callback_url or ""),
            },
            "authentik": {
                "enabled": bool(system_config.get("authentik_oauth_enabled", app_config.authentik_oauth_enabled)),
                "client_id": str(system_config.get("authentik_client_id") or app_config.authentik_client_id or ""),
                "client_secret": str(system_config.get("authentik_client_secret") or app_config.authentik_client_secret or ""),
                "callback_url": str(system_config.get("authentik_callback_url") or app_config.authentik_callback_url or ""),
                "issuer_url": str(system_config.get("authentik_issuer_url") or app_config.authentik_issuer_url or ""),
            },
        },
    }


@router.post("/api/oauth")
async def save_oauth_config(
    data: OAuthSettingsRequest,
    user: User = Depends(get_admin_user_required)
):
    """Save OAuth configuration into system config."""
    from ..services.db_config_service import get_db_config_service

    github_enabled = bool(data.github.enabled)
    github_client_id = (data.github.client_id or "").strip()
    github_client_secret = (data.github.client_secret or "").strip()
    github_callback_url = (data.github.callback_url or "").strip()
    github_callback_use_request_host = bool(data.github.callback_use_request_host)

    linuxdo_enabled = bool(data.linuxdo.enabled)
    linuxdo_client_id = (data.linuxdo.client_id or "").strip()
    linuxdo_client_secret = (data.linuxdo.client_secret or "").strip()
    linuxdo_callback_url = (data.linuxdo.callback_url or "").strip()

    authentik_enabled = bool(data.authentik.enabled)
    authentik_client_id = (data.authentik.client_id or "").strip()
    authentik_client_secret = (data.authentik.client_secret or "").strip()
    authentik_callback_url = (data.authentik.callback_url or "").strip()
    authentik_issuer_url = (data.authentik.issuer_url or "").strip().rstrip("/")

    if github_enabled and (not github_client_id or not github_client_secret):
        return {"success": False, "message": "启用 GitHub OAuth 前需要填写 Client ID 和 Client Secret"}

    if linuxdo_enabled and (not linuxdo_client_id or not linuxdo_client_secret):
        return {"success": False, "message": "启用 LinuxDo OAuth 前需要填写 Client ID 和 Client Secret"}

    if authentik_enabled and (not authentik_client_id or not authentik_client_secret or not authentik_issuer_url):
        return {"success": False, "message": "启用 Authentik OAuth 前需要填写 Issuer URL、Client ID 和 Client Secret"}

    config_service = get_db_config_service()
    success = await config_service.update_config(
        {
            "github_oauth_enabled": github_enabled,
            "github_client_id": github_client_id,
            "github_client_secret": github_client_secret,
            "github_callback_url": github_callback_url,
            "github_callback_use_request_host": github_callback_use_request_host,
            "linuxdo_oauth_enabled": linuxdo_enabled,
            "linuxdo_client_id": linuxdo_client_id,
            "linuxdo_client_secret": linuxdo_client_secret,
            "linuxdo_callback_url": linuxdo_callback_url,
            "authentik_oauth_enabled": authentik_enabled,
            "authentik_client_id": authentik_client_id,
            "authentik_client_secret": authentik_client_secret,
            "authentik_callback_url": authentik_callback_url,
            "authentik_issuer_url": authentik_issuer_url,
        },
        user_id=None,
    )

    if not success:
        return {"success": False, "message": "OAuth 设置保存失败"}

    # Keep current process config hot-reloaded for routes still reading app_config directly.
    app_config.github_oauth_enabled = github_enabled
    app_config.github_client_id = github_client_id or None
    app_config.github_client_secret = github_client_secret or None
    app_config.github_callback_url = github_callback_url or None
    app_config.github_callback_use_request_host = github_callback_use_request_host
    app_config.linuxdo_oauth_enabled = linuxdo_enabled
    app_config.linuxdo_client_id = linuxdo_client_id or None
    app_config.linuxdo_client_secret = linuxdo_client_secret or None
    app_config.linuxdo_callback_url = linuxdo_callback_url or None
    app_config.authentik_oauth_enabled = authentik_enabled
    app_config.authentik_client_id = authentik_client_id or None
    app_config.authentik_client_secret = authentik_client_secret or None
    app_config.authentik_callback_url = authentik_callback_url or None
    app_config.authentik_issuer_url = authentik_issuer_url or None

    logger.info("Admin %s updated OAuth configuration", user.username)
    return {"success": True, "message": "OAuth 设置已保存"}


@router.post("/api/smtp")
async def save_smtp_config(
    data: SMTPConfigRequest,
    user: User = Depends(get_admin_user_required)
):
    """Save SMTP configuration to .env file"""
    import os
    from pathlib import Path
    
    try:
        # Update app_config in memory
        app_config.email_provider = data.email_provider
        app_config.smtp_host = data.smtp_host
        app_config.smtp_port = data.smtp_port
        app_config.smtp_user = data.smtp_user
        app_config.smtp_password = data.smtp_password
        app_config.smtp_use_ssl = data.smtp_use_ssl
        app_config.smtp_from_email = data.smtp_from_email
        app_config.smtp_from_name = data.smtp_from_name
        app_config.resend_api_key = data.resend_api_key
        app_config.resend_from_email = data.resend_from_email
        app_config.resend_from_name = data.resend_from_name
        
        # Also save to .env file for persistence
        env_path = Path('.env')
        env_content = {}
        
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_content[key.strip()] = value.strip()
        
        # Update SMTP settings
        env_content['EMAIL_PROVIDER'] = data.email_provider
        env_content['SMTP_HOST'] = data.smtp_host
        env_content['SMTP_PORT'] = str(data.smtp_port)
        env_content['SMTP_USER'] = data.smtp_user
        env_content['SMTP_PASSWORD'] = data.smtp_password
        env_content['SMTP_USE_SSL'] = str(data.smtp_use_ssl).lower()
        env_content['SMTP_FROM_EMAIL'] = data.smtp_from_email
        env_content['SMTP_FROM_NAME'] = data.smtp_from_name
        env_content['RESEND_API_KEY'] = data.resend_api_key
        env_content['RESEND_FROM_EMAIL'] = data.resend_from_email
        env_content['RESEND_FROM_NAME'] = data.resend_from_name
        
        # Write back to .env
        with open(env_path, 'w', encoding='utf-8') as f:
            for key, value in env_content.items():
                f.write(f"{key}={value}\n")
        
        logger.info(f"Admin {user.username} updated email configuration")
        return {"success": True, "message": "邮件设置已保存"}
        
    except Exception as e:
        logger.error(f"Error saving SMTP config: {e}")
        return {"success": False, "message": f"保存失败: {str(e)}"}


@router.post("/api/smtp/test")
async def test_smtp_config(
    data: SMTPConfigRequest,
    user: User = Depends(get_admin_user_required)
):
    """Test email configuration by sending a test email"""
    provider = (data.email_provider or "smtp").strip().lower()
    
    if not data.test_email:
        return {"success": False, "message": "请提供测试收件邮箱"}

    if provider == "resend":
        if not data.resend_api_key:
            return {"success": False, "message": "请填写 Resend API Key"}
        if not data.resend_from_email:
            return {"success": False, "message": "请填写 Resend 发件人邮箱"}

        try:
            import asyncio
            try:
                import resend
            except ModuleNotFoundError:
                return {"success": False, "message": "Resend 依赖未安装"}

            def _send():
                resend.api_key = data.resend_api_key
                from_name = (data.resend_from_name or "LandPPT").strip()
                from_value = f"{from_name} <{data.resend_from_email}>" if from_name else data.resend_from_email
                params: resend.Emails.SendParams = {
                    "from": from_value,
                    "to": [data.test_email],
                    "subject": "LandPPT Resend 测试邮件",
                    "html": """
                    <html>
                    <body style="font-family: Arial, sans-serif; padding: 20px;">
                        <h2>🎉 Resend 配置测试成功！</h2>
                        <p>如果您收到这封邮件，说明 LandPPT 的 Resend 邮件服务已正确配置。</p>
                        <hr>
                        <p style="color: #666; font-size: 12px;">此邮件由 LandPPT 管理后台发送</p>
                    </body>
                    </html>
                    """,
                }
                return resend.Emails.send(params)

            await asyncio.to_thread(_send)
            logger.info(f"Admin {user.username} sent test email to {data.test_email} via Resend")
            return {"success": True, "message": f"测试邮件已发送至 {data.test_email}"}

        except Exception as e:
            return {"success": False, "message": f"发送失败: {str(e)}"}

    # SMTP
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    if not data.smtp_host or not data.smtp_user:
        return {"success": False, "message": "请填写 SMTP 服务器和用户名"}

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'LandPPT SMTP 测试邮件'
        msg['From'] = f"{data.smtp_from_name} <{data.smtp_from_email or data.smtp_user}>"
        msg['To'] = data.test_email

        html_content = """
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>🎉 SMTP 配置测试成功！</h2>
            <p>如果您收到这封邮件，说明 LandPPT 的 SMTP 邮件服务已正确配置。</p>
            <hr>
            <p style="color: #666; font-size: 12px;">此邮件由 LandPPT 管理后台发送</p>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        if data.smtp_use_ssl:
            server = smtplib.SMTP_SSL(data.smtp_host, data.smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(data.smtp_host, data.smtp_port, timeout=30)
            server.starttls()

        server.login(data.smtp_user, data.smtp_password)
        server.sendmail(
            data.smtp_from_email or data.smtp_user,
            [data.test_email],
            msg.as_string()
        )
        server.quit()

        logger.info(f"Admin {user.username} sent test email to {data.test_email}")
        return {"success": True, "message": f"测试邮件已发送至 {data.test_email}"}

    except smtplib.SMTPAuthenticationError as e:
        return {"success": False, "message": "SMTP 认证失败，请检查用户名和密码"}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP 错误: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"发送失败: {str(e)}"}


# User API endpoints
@router.get("/api/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_admin: Optional[bool] = None,
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc"),
    user: User = Depends(get_admin_user_required)
):
    """List all users with pagination"""
    async with AsyncSessionLocal() as session:
        user_repo = UserRepository(session)
        users, total = await user_repo.list_users(
            page=page,
            page_size=page_size,
            is_active=is_active,
            is_admin=is_admin,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
         
        return {
            "users": [u.to_dict() for u in users],
            "total": total,
            "page": page,
            "page_size": page_size,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "total_pages": (total + page_size - 1) // page_size
        }


@router.post("/api/users")
async def create_user(
    data: UserCreateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user_required)
):
    """Create a new user"""
    try:
        user = auth_service.create_user(
            db=db,
            username=data.username,
            password=data.password,
            email=data.email,
            is_admin=data.is_admin
        )
        
        # If custom credits balance specified, update it
        if data.credits_balance > 0 and data.credits_balance != app_config.default_credits_for_new_users:
            user.credits_balance = data.credits_balance
            db.commit()
            db.refresh(user)
        
        logger.info(f"Admin {admin_user.username} created user {data.username}")
        return {"success": True, "user": user.to_dict()}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="创建用户失败")


@router.get("/api/users/{user_id}")
async def get_user(
    user_id: int,
    admin_user: User = Depends(get_admin_user_required)
):
    """Get user details"""
    async with AsyncSessionLocal() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(user_id)
        
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        return {"user": user.to_dict()}


@router.put("/api/users/{user_id}")
async def update_user(
    user_id: int,
    data: UserUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user_required)
):
    """Update user properties"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # Prevent admin from deactivating themselves
    if user.id == admin_user.id and data.is_active == False:
        raise HTTPException(status_code=400, detail="不能停用自己的账户")
    
    # Update fields
    if data.email is not None:
        # Check if email is already taken
        existing = db.query(User).filter(User.email == data.email, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="邮箱已被使用")
        user.email = data.email
    
    if data.is_admin is not None:
        # Prevent admin from removing their own admin status
        if user.id == admin_user.id and data.is_admin == False:
            raise HTTPException(status_code=400, detail="不能移除自己的管理员权限")
        user.is_admin = data.is_admin
    
    if data.is_active is not None:
        user.is_active = data.is_active
        if data.is_active is False:
            # Revoke all active sessions so the disable takes effect immediately.
            db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.is_active == True).update(
                {"is_active": False},
                synchronize_session=False,
            )
    
    db.commit()
    db.refresh(user)
    await auth_service.invalidate_user_sessions_cache(user.id)
    
    logger.info(f"Admin {admin_user.username} updated user {user.username}")
    return {"success": True, "user": user.to_dict()}


@router.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user_required)
):
    """Deactivate a user (soft delete)"""
    if user_id == admin_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账户")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user.is_active = False
    # Revoke all active sessions so the disable takes effect immediately.
    db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.is_active == True).update(
        {"is_active": False},
        synchronize_session=False,
    )
    db.commit()
    await auth_service.invalidate_user_sessions_cache(user.id)
    
    logger.info(f"Admin {admin_user.username} deactivated user {user.username}")
    return {"success": True, "message": "用户已停用"}


@router.post("/api/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user_required)
):
    """Reset user password to a temporary password"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    import secrets
    temp_password = secrets.token_urlsafe(8)
    user.set_password(temp_password)
    db.commit()
    await auth_service.invalidate_user_sessions_cache(user.id)
    
    logger.info(f"Admin {admin_user.username} reset password for user {user.username}")
    return {"success": True, "temporary_password": temp_password}


# Credits API endpoints
@router.post("/api/users/{user_id}/credits")
async def adjust_user_credits(
    user_id: int,
    data: CreditAdjustRequest,
    admin_user: User = Depends(get_admin_user_required)
):
    """Adjust user credits (admin)"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    async with AsyncSessionLocal() as session:
        credits_service = CreditsService(session)
        
        if data.amount > 0:
            success, message = await credits_service.add_credits(
                user_id=user_id,
                amount=data.amount,
                transaction_type="admin_adjust",
                description=f"管理员调整: {data.description}",
                reference_id=f"admin:{admin_user.id}"
            )
        else:
            # For negative adjustments, we use consume_credits
            success, message = await credits_service.consume_credits(
                user_id=user_id,
                operation_type="ai_other",
                quantity=abs(data.amount),
                description=f"管理员调整: {data.description}",
                reference_id=f"admin:{admin_user.id}"
            )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        logger.info(f"Admin {admin_user.username} adjusted credits for user {user_id}: {data.amount}")
        return {"success": True, "message": message}


@router.get("/api/users/{user_id}/transactions")
async def get_user_transactions(
    user_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin_user: User = Depends(get_admin_user_required)
):
    """Get user's credit transaction history"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    async with AsyncSessionLocal() as session:
        credits_service = CreditsService(session)
        transactions, total = await credits_service.get_transaction_history(
            user_id=user_id,
            page=page,
            page_size=page_size
        )
        
        return {
            "transactions": transactions,
            "total": total,
            "page": page,
            "page_size": page_size
        }


# Redemption codes API
@router.post("/api/redemption-codes")
async def create_redemption_codes(
    data: RedemptionCodeCreateRequest,
    admin_user: User = Depends(get_admin_user_required)
):
    """Create redemption codes"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    import time
    expires_at = None
    if data.expires_in_days:
        expires_at = time.time() + (data.expires_in_days * 24 * 60 * 60)
    
    async with AsyncSessionLocal() as session:
        code_repo = RedemptionCodeRepository(session)
        codes = await code_repo.create_batch(
            count=data.count,
            credits_amount=data.credits_amount,
            created_by=admin_user.id,
            expires_at=expires_at,
            description=data.description
        )
        
        logger.info(f"Admin {admin_user.username} created {len(codes)} redemption codes")
        return {
            "success": True,
            "codes": [c.to_dict() for c in codes]
        }


@router.get("/api/redemption-codes")
async def list_redemption_codes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_used: Optional[bool] = None,
    created_by: Optional[int] = None,
    search: Optional[str] = None,
    admin_user: User = Depends(get_admin_user_required)
):
    """List redemption codes"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    async with AsyncSessionLocal() as session:
        code_repo = RedemptionCodeRepository(session)
        codes, total = await code_repo.list_codes(
            page=page,
            page_size=page_size,
            is_used=is_used,
            created_by=created_by,
            search=search
        )
        
        return {
            "codes": [c.to_dict() for c in codes],
            "total": total,
            "page": page,
            "page_size": page_size
        }


@router.get("/api/redemption-codes/export")
async def export_redemption_codes(
    is_used: Optional[bool] = None,
    created_by: Optional[int] = None,
    search: Optional[str] = None,
    admin_user: User = Depends(get_admin_user_required),
):
    """Export redemption codes as CSV (filters match list endpoint)."""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="绉垎绯荤粺鏈惎鐢?")

    import csv
    import io
    from datetime import datetime

    def fmt_ts(ts: Optional[float]) -> str:
        if not ts:
            return ""
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""

    filename = f"redemption_codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    async def iter_csv():
        async with AsyncSessionLocal() as session:
            repo = RedemptionCodeRepository(session)
            now_ts = datetime.now().timestamp()

            output = io.StringIO()
            output.write("\ufeff")  # UTF-8 BOM for Excel compatibility
            writer = csv.writer(output)
            writer.writerow([
                "兑换码",
                "积分",
                "状态",
                "使用者ID",
                "使用时间",
                "创建者ID",
                "创建时间",
                "过期时间",
                "备注",
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

            page = 1
            page_size = 100
            while True:
                codes, _ = await repo.list_codes(
                    page=page,
                    page_size=page_size,
                    is_used=is_used,
                    created_by=created_by,
                    search=search,
                )
                if not codes:
                    break

                for c in codes:
                    status = "已使用" if c.is_used else ("已过期" if (c.expires_at and c.expires_at < now_ts) else "未使用")
                    writer.writerow([
                        c.code,
                        c.credits_amount,
                        status,
                        c.used_by or "",
                        fmt_ts(c.used_at),
                        c.created_by,
                        fmt_ts(c.created_at),
                        fmt_ts(c.expires_at) if c.expires_at else "永久",
                        c.description or "",
                    ])

                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
                page += 1

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/api/redemption-codes/{code_id}")
async def delete_redemption_code(
    code_id: int,
    admin_user: User = Depends(get_admin_user_required)
):
    """Delete an unused redemption code"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    async with AsyncSessionLocal() as session:
        code_repo = RedemptionCodeRepository(session)
        success = await code_repo.delete_code(code_id)
        
        if not success:
            raise HTTPException(status_code=400, detail="无法删除该兑换码（可能已被使用）")
        
        return {"success": True, "message": "兑换码已删除"}


@router.get("/api/community/settings")
async def get_community_settings(
    admin_user: User = Depends(get_admin_user_required)
):
    """Get community operation settings."""
    settings = await community_service.get_settings()
    return {
        "success": True,
        "settings": settings,
    }


@router.post("/api/community/settings")
async def update_community_settings(
    data: CommunitySettingsRequest,
    admin_user: User = Depends(get_admin_user_required)
):
    """Update community operation settings."""
    settings = await community_service.update_settings(data.model_dump())
    return {
        "success": True,
        "settings": settings,
        "message": "运营配置已更新",
    }


@router.get("/api/invite-codes")
async def list_invite_codes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    channel: Optional[str] = None,
    is_active: Optional[bool] = None,
    admin_user: User = Depends(get_admin_user_required)
):
    """List registration invite codes."""
    items, total = await community_service.list_invite_codes(
        page=page,
        page_size=page_size,
        search=search,
        channel=channel,
        is_active=is_active,
    )
    return {
        "success": True,
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/api/invite-codes/export")
async def export_invite_codes(
    search: Optional[str] = None,
    channel: Optional[str] = None,
    is_active: Optional[bool] = None,
    admin_user: User = Depends(get_admin_user_required)
):
    """Export invite codes as CSV."""
    import csv
    import io
    import time
    from datetime import datetime

    def fmt_ts(ts: Optional[float]) -> str:
        if not ts:
            return ""
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""

    filename = f"invite_codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    async def iter_csv():
        now_ts = time.time()
        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow([
            "Code",
            "Channel",
            "Credits",
            "Max Uses",
            "Used Count",
            "Remaining Uses",
            "Status",
            "Expires At",
            "Created At",
            "Description",
        ])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        page = 1
        page_size = 100
        while True:
            items, _ = await community_service.list_invite_codes(
                page=page,
                page_size=page_size,
                search=search,
                channel=channel,
                is_active=is_active,
            )
            if not items:
                break

            for item in items:
                is_expired = bool(item.get("expires_at")) and float(item["expires_at"]) < now_ts
                remaining_uses = int(item.get("remaining_uses") or 0)
                if not item.get("is_active"):
                    status = "inactive"
                elif is_expired:
                    status = "expired"
                elif remaining_uses <= 0:
                    status = "exhausted"
                else:
                    status = "active"

                writer.writerow([
                    item.get("code") or "",
                    community_service.channel_label(item.get("channel") or "mail"),
                    item.get("credits_amount") or 0,
                    item.get("max_uses") or 0,
                    item.get("used_count") or 0,
                    remaining_uses,
                    status,
                    fmt_ts(item.get("expires_at")),
                    fmt_ts(item.get("created_at")),
                    item.get("description") or "",
                ])

            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            page += 1

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/invite-codes")
async def create_invite_codes(
    data: InviteCodeCreateRequest,
    admin_user: User = Depends(get_admin_user_required)
):
    """Create registration invite codes."""
    import time

    expires_at = None
    if data.expires_in_days:
        expires_at = time.time() + (max(1, int(data.expires_in_days)) * 86400)

    items = await community_service.create_invite_codes(
        count=data.count,
        channel=data.channel,
        credits_amount=data.credits_amount,
        max_uses=data.max_uses,
        created_by=admin_user.id,
        expires_at=expires_at,
        description=data.description,
    )
    logger.info(f"Admin {admin_user.username} created {len(items)} invite codes")
    return {
        "success": True,
        "items": items,
    }


@router.patch("/api/invite-codes/{invite_code_id}")
async def update_invite_code(
    invite_code_id: int,
    data: InviteCodeUpdateRequest,
    admin_user: User = Depends(get_admin_user_required)
):
    """Update one invite code."""
    import time

    payload = data.model_dump(exclude_none=True)
    if data.clear_expiration:
        payload["expires_at"] = None
    elif data.expires_in_days is not None:
        payload["expires_at"] = time.time() + (max(1, int(data.expires_in_days)) * 86400)

    payload.pop("expires_in_days", None)
    payload.pop("clear_expiration", None)

    try:
        item = await community_service.update_invite_code(invite_code_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "item": item,
    }


@router.delete("/api/invite-codes/{invite_code_id}")
async def delete_invite_code(
    invite_code_id: int,
    admin_user: User = Depends(get_admin_user_required)
):
    """Delete one unused invite code."""
    try:
        success = await community_service.delete_invite_code(invite_code_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not success:
        raise HTTPException(status_code=404, detail="邀请码不存在")

    return {
        "success": True,
        "message": "邀请码已删除",
    }


@router.get("/api/sponsors")
async def list_sponsors(
    admin_user: User = Depends(get_admin_user_required)
):
    """List sponsor profiles for admin."""
    items = await community_service.list_sponsors(include_inactive=True)
    return {
        "success": True,
        "items": items,
    }


@router.post("/api/sponsors")
async def create_sponsor(
    data: SponsorCreateRequest,
    admin_user: User = Depends(get_admin_user_required)
):
    """Create sponsor profile."""
    try:
        item = await community_service.create_sponsor(data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "item": item,
    }


@router.put("/api/sponsors/{sponsor_id}")
async def update_sponsor(
    sponsor_id: int,
    data: SponsorUpdateRequest,
    admin_user: User = Depends(get_admin_user_required)
):
    """Update sponsor profile."""
    try:
        item = await community_service.update_sponsor(sponsor_id, data.model_dump(exclude_unset=True))
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "不存在" in message else 400
        raise HTTPException(status_code=status_code, detail=message)

    return {
        "success": True,
        "item": item,
    }


@router.delete("/api/sponsors/{sponsor_id}")
async def delete_sponsor(
    sponsor_id: int,
    admin_user: User = Depends(get_admin_user_required)
):
    """Delete sponsor profile."""
    success = await community_service.delete_sponsor(sponsor_id)
    if not success:
        raise HTTPException(status_code=404, detail="赞助人不存在")

    return {
        "success": True,
        "message": "赞助人已删除",
    }
