"""
Authentik OAuth service for LandPPT
Uses Valkey for state storage with in-memory fallback
"""

import hashlib
import logging
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from ..core.config import app_config
from ..database.models import User

logger = logging.getLogger(__name__)

# In-memory state storage (fallback when Valkey unavailable)
_oauth_states_fallback: Dict[str, Dict[str, Any]] = {}

# OAuth state TTL in seconds (30 minutes)
OAUTH_STATE_TTL = 1800


def _get_system_oauth_config_sync() -> Dict[str, Any]:
    """Best-effort read of system OAuth config from DB with app_config fallback."""
    config: Dict[str, Any] = {}
    try:
        from ..services.db_config_service import get_db_config_service

        config_service = get_db_config_service()
        config = config_service.get_all_config_sync(user_id=None)
    except Exception as exc:
        logger.warning("Failed to load Authentik OAuth config from DB: %s", exc)
    return config


def _normalize_issuer_url(value: Optional[str]) -> str:
    return str(value or "").strip().rstrip("/")


def _issuer_url(system_config: Dict[str, Any]) -> str:
    return _normalize_issuer_url(system_config.get("authentik_issuer_url") or app_config.authentik_issuer_url)


def _oauth_endpoints(system_config: Dict[str, Any]) -> Dict[str, str]:
    issuer = _issuer_url(system_config)
    return {
        "authorize": f"{issuer}/application/o/authorize/",
        "token": f"{issuer}/application/o/token/",
        "userinfo": f"{issuer}/application/o/userinfo/",
    }


def generate_state() -> str:
    """Generate a random state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


async def store_oauth_state(
    state: str,
    redirect_url: str = "/dashboard",
    invite_code: Optional[str] = None,
) -> None:
    """Store OAuth state for later verification."""
    state_data = {
        "redirect_url": redirect_url,
        "invite_code": (str(invite_code or "").strip().upper() or None),
        "created_at": time.time(),
    }

    try:
        from ..services.cache_service import get_cache_service

        cache = await get_cache_service()
        if cache.is_connected:
            success = await cache.set_oauth_state("authentik", state, state_data, OAUTH_STATE_TTL)
            if success:
                logger.debug("Authentik OAuth state stored in Valkey: %s...", state[:8])
                return
    except Exception as e:
        logger.warning("Failed to store OAuth state in Valkey: %s", e)

    _oauth_states_fallback[state] = state_data
    logger.debug("Authentik OAuth state stored in memory (fallback): %s...", state[:8])
    _cleanup_old_states_fallback()


async def get_and_consume_oauth_state(state: str) -> Optional[Dict[str, Any]]:
    """Get and remove OAuth state data."""
    try:
        from ..services.cache_service import get_cache_service

        cache = await get_cache_service()
        if cache.is_connected:
            data = await cache.get_and_consume_oauth_state("authentik", state)
            if data:
                logger.debug("Authentik OAuth state retrieved from Valkey: %s...", state[:8])
                return data
    except Exception as e:
        logger.warning("Failed to get OAuth state from Valkey: %s", e)

    data = _oauth_states_fallback.pop(state, None)
    if data:
        if time.time() - data.get("created_at", 0) > OAUTH_STATE_TTL:
            logger.warning("OAuth state expired in memory fallback: %s...", state[:8])
            return None

    return data


def _cleanup_old_states_fallback() -> None:
    """Remove expired OAuth states from memory fallback."""
    current_time = time.time()
    expired_states = [
        state
        for state, data in _oauth_states_fallback.items()
        if current_time - data.get("created_at", 0) > OAUTH_STATE_TTL
    ]
    for state in expired_states:
        _oauth_states_fallback.pop(state, None)


def get_callback_url() -> str:
    """Get the OAuth callback URL based on current configuration."""
    system_config = _get_system_oauth_config_sync()
    configured_callback = str(system_config.get("authentik_callback_url") or app_config.authentik_callback_url or "").strip()
    if configured_callback:
        return configured_callback

    host = app_config.host
    port = app_config.port
    if host == "0.0.0.0":
        host = "localhost"

    return f"http://{host}:{port}/auth/authentik/callback"


def build_authorization_url(state: str) -> str:
    """Build Authentik OAuth authorization URL."""
    system_config = _get_system_oauth_config_sync()
    endpoints = _oauth_endpoints(system_config)

    params = {
        "client_id": str(system_config.get("authentik_client_id") or app_config.authentik_client_id or "").strip(),
        "redirect_uri": get_callback_url(),
        "response_type": "code",
        "scope": "openid profile email",
        "state": state,
    }

    return f"{endpoints['authorize']}?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> Optional[str]:
    """Exchange authorization code for access token."""
    system_config = _get_system_oauth_config_sync()
    endpoints = _oauth_endpoints(system_config)
    client_id = str(system_config.get("authentik_client_id") or app_config.authentik_client_id or "").strip()
    client_secret = str(system_config.get("authentik_client_secret") or app_config.authentik_client_secret or "").strip()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoints["token"],
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": get_callback_url(),
                    "grant_type": "authorization_code",
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error("Authentik token exchange failed: %s - %s", response.status_code, response.text)
                return None

            data = response.json()
            if "error" in data:
                logger.error("Authentik OAuth error: %s - %s", data.get("error"), data.get("error_description"))
                return None

            return data.get("access_token")
    except Exception as e:
        logger.error("Failed to exchange code for token: %s", e)
        return None


async def get_authentik_user_info(access_token: str) -> Optional[Dict[str, Any]]:
    """Fetch Authentik user information using access token."""
    system_config = _get_system_oauth_config_sync()
    endpoints = _oauth_endpoints(system_config)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoints["userinfo"],
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error("Failed to get Authentik user: %s", response.status_code)
                return None

            user_data = response.json()
            sub = str(user_data.get("sub") or "").strip()
            if not sub:
                logger.error("Authentik userinfo missing sub")
                return None

            username = (
                user_data.get("preferred_username")
                or user_data.get("nickname")
                or user_data.get("name")
                or user_data.get("email")
                or f"authentik_{sub[:8]}"
            )

            return {
                "sub": sub,
                "username": str(username).strip(),
                "email": user_data.get("email"),
                "name": user_data.get("name"),
                "avatar_url": user_data.get("picture"),
            }
    except Exception as e:
        logger.error("Failed to get Authentik user info: %s", e)
        return None


def get_or_create_user_by_authentik(
    db: Session,
    authentik_sub: str,
    username: str,
    email: Optional[str],
    name: Optional[str],
    avatar_url: Optional[str],
    invite_code: Optional[str] = None,
) -> tuple[Optional[User], bool, Optional[str]]:
    """Get existing user or create new user from Authentik OAuth."""
    try:
        existing_authentik_user = db.query(User).filter(User.authentik_sub == authentik_sub).first()
        if existing_authentik_user:
            existing_authentik_user.last_login = time.time()
            if avatar_url:
                existing_authentik_user.avatar = avatar_url
            db.commit()
            return existing_authentik_user, False, None

        if email:
            existing_email_user = db.query(User).filter(User.email == email).first()
            if existing_email_user:
                existing_email_user.authentik_sub = authentik_sub
                existing_email_user.oauth_provider = "authentik"
                existing_email_user.last_login = time.time()
                if avatar_url and not existing_email_user.avatar:
                    existing_email_user.avatar = avatar_url
                db.commit()
                logger.info("Linked Authentik account %s to existing user %s", username, existing_email_user.username)
                return existing_email_user, False, None

        from ..services.community_service import community_service

        try:
            validated_invite = community_service.resolve_registration_invite(db, invite_code, "authentik")
        except ValueError as exc:
            return None, False, str(exc)

        new_username = username
        existing_username = db.query(User).filter(User.username == new_username).first()
        if existing_username:
            new_username = f"{username}_{secrets.token_hex(4)}"

        default_credits = app_config.default_credits_for_new_users if app_config.enable_credits_system else 0

        new_user = User(
            username=new_username,
            email=email,
            avatar=avatar_url,
            authentik_sub=authentik_sub,
            oauth_provider="authentik",
            registration_channel="authentik",
            is_active=True,
            is_admin=False,
            credits_balance=default_credits,
            created_at=time.time(),
            last_login=time.time(),
        )
        new_user.password_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()

        db.add(new_user)
        db.flush()
        if validated_invite is not None:
            community_service.apply_invite_code_to_user(db, new_user, validated_invite, "authentik")
        db.commit()
        db.refresh(new_user)

        logger.info("Created new user from Authentik OAuth: %s (sub=%s)", new_username, authentik_sub)
        return new_user, True, None
    except Exception as e:
        logger.error("Failed to get or create user from Authentik: %s", e)
        db.rollback()
        return None, False, "Authentik 注册失败，请稍后重试"


def is_authentik_oauth_enabled() -> bool:
    """Check if Authentik OAuth is properly configured and enabled."""
    system_config = _get_system_oauth_config_sync()
    enabled = bool(system_config.get("authentik_oauth_enabled", app_config.authentik_oauth_enabled))
    client_id = str(system_config.get("authentik_client_id") or app_config.authentik_client_id or "").strip()
    client_secret = str(system_config.get("authentik_client_secret") or app_config.authentik_client_secret or "").strip()
    issuer_url = _issuer_url(system_config)
    return enabled and bool(client_id) and bool(client_secret) and bool(issuer_url)
