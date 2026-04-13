"""
Linux Do OAuth service for LandPPT
Based on Linux Do Connect API: https://connect.linux.do
Uses Valkey for state storage with in-memory fallback
"""

import secrets
import hashlib
import time
import httpx
import logging
from urllib.parse import urlencode
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from ..database.models import User
from ..core.config import app_config

logger = logging.getLogger(__name__)

# Linux Do OAuth endpoints
LINUXDO_AUTHORIZE_URL = "https://connect.linux.do/oauth2/authorize"
LINUXDO_TOKEN_URL = "https://connect.linux.do/oauth2/token"
LINUXDO_USER_URL = "https://connect.linux.do/api/user"

# In-memory state storage (fallback when Valkey unavailable)
_oauth_states_fallback: Dict[str, Dict[str, Any]] = {}

# OAuth state TTL in seconds (30 minutes)
OAUTH_STATE_TTL = 1800


def generate_state() -> str:
    """Generate a random state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


def _get_system_oauth_config_sync() -> Dict[str, Any]:
    """Best-effort read of system OAuth config from DB with app_config fallback."""
    config: Dict[str, Any] = {}
    try:
        from ..services.db_config_service import get_db_config_service

        config_service = get_db_config_service()
        config = config_service.get_all_config_sync(user_id=None)
    except Exception as exc:
        logger.warning("Failed to load Linux Do OAuth config from DB: %s", exc)
    return config


async def store_oauth_state(
    state: str,
    redirect_url: str = "/dashboard",
    invite_code: Optional[str] = None,
) -> None:
    """
    Store OAuth state for later verification.
    Uses Valkey with in-memory fallback.
    
    Args:
        state: The state parameter
        redirect_url: URL to redirect after successful login
    """
    state_data = {
        "redirect_url": redirect_url,
        "invite_code": (str(invite_code or "").strip().upper() or None),
        "created_at": time.time()
    }
    
    # Try Valkey first
    try:
        from ..services.cache_service import get_cache_service
        cache = await get_cache_service()
        
        if cache.is_connected:
            success = await cache.set_oauth_state("linuxdo", state, state_data, OAUTH_STATE_TTL)
            if success:
                logger.debug(f"Linux Do OAuth state stored in Valkey: {state[:8]}...")
                return
    except Exception as e:
        logger.warning(f"Failed to store OAuth state in Valkey: {e}")
    
    # Fallback to in-memory storage
    _oauth_states_fallback[state] = state_data
    logger.debug(f"Linux Do OAuth state stored in memory (fallback): {state[:8]}...")
    
    # Clean up old states from memory fallback
    _cleanup_old_states_fallback()


async def get_and_consume_oauth_state(state: str) -> Optional[Dict[str, Any]]:
    """
    Get and remove OAuth state data.
    Checks Valkey first, then falls back to in-memory storage.
    
    Args:
        state: The state parameter to look up
        
    Returns:
        State data dict if found, None otherwise
    """
    # Try Valkey first
    try:
        from ..services.cache_service import get_cache_service
        cache = await get_cache_service()
        
        if cache.is_connected:
            data = await cache.get_and_consume_oauth_state("linuxdo", state)
            if data:
                logger.debug(f"Linux Do OAuth state retrieved from Valkey: {state[:8]}...")
                return data
    except Exception as e:
        logger.warning(f"Failed to get OAuth state from Valkey: {e}")
    
    # Fallback to in-memory storage
    data = _oauth_states_fallback.pop(state, None)
    if data:
        logger.debug(f"Linux Do OAuth state retrieved from memory (fallback): {state[:8]}...")
        # Validate expiration for memory fallback
        if time.time() - data.get("created_at", 0) > OAUTH_STATE_TTL:
            logger.warning(f"OAuth state expired in memory fallback: {state[:8]}...")
            return None
    
    return data


def _cleanup_old_states_fallback() -> None:
    """Remove expired OAuth states from memory fallback."""
    current_time = time.time()
    expired_states = [
        state for state, data in _oauth_states_fallback.items()
        if current_time - data.get("created_at", 0) > OAUTH_STATE_TTL
    ]
    for state in expired_states:
        _oauth_states_fallback.pop(state, None)


def get_callback_url() -> str:
    """Get the OAuth callback URL based on current configuration."""
    system_config = _get_system_oauth_config_sync()
    configured_callback = str(system_config.get("linuxdo_callback_url") or app_config.linuxdo_callback_url or "").strip()
    if configured_callback:
        return configured_callback
    
    # Fallback to localhost for development
    host = app_config.host
    port = app_config.port
    
    if host == "0.0.0.0":
        host = "localhost"
    
    return f"http://{host}:{port}/auth/linuxdo/callback"


def build_authorization_url(state: str) -> str:
    """Build Linux Do OAuth authorization URL."""
    system_config = _get_system_oauth_config_sync()
    params = {
        "client_id": str(system_config.get("linuxdo_client_id") or app_config.linuxdo_client_id or "").strip(),
        "redirect_uri": get_callback_url(),
        "response_type": "code",
        "scope": "user",
        "state": state
    }
    
    query_string = urlencode(params)
    return f"{LINUXDO_AUTHORIZE_URL}?{query_string}"


async def exchange_code_for_token(code: str) -> Optional[str]:
    """Exchange authorization code for access token."""
    system_config = _get_system_oauth_config_sync()
    client_id = str(system_config.get("linuxdo_client_id") or app_config.linuxdo_client_id or "").strip()
    client_secret = str(system_config.get("linuxdo_client_secret") or app_config.linuxdo_client_secret or "").strip()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                LINUXDO_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": get_callback_url(),
                    "grant_type": "authorization_code"
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                },
                timeout=30.0
            )
            
            if response.status_code != 200:
                logger.error(f"Linux Do token exchange failed: {response.status_code} - {response.text}")
                return None
            
            data = response.json()
            
            if "error" in data:
                logger.error(f"Linux Do OAuth error: {data.get('error')} - {data.get('error_description')}")
                return None
            
            return data.get("access_token")
            
    except Exception as e:
        logger.error(f"Failed to exchange code for token: {e}")
        return None


async def get_linuxdo_user_info(access_token: str) -> Optional[Dict[str, Any]]:
    """Fetch Linux Do user information using access token."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                LINUXDO_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                },
                timeout=30.0
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get Linux Do user: {response.status_code}")
                return None
            
            user_data = response.json()
            
            return {
                "id": str(user_data.get("id")),
                "username": user_data.get("username"),
                "name": user_data.get("name"),
                "email": user_data.get("email"),
                "avatar_url": user_data.get("avatar_url"),
                "trust_level": user_data.get("trust_level"),
                "active": user_data.get("active", True)
            }
            
    except Exception as e:
        logger.error(f"Failed to get Linux Do user info: {e}")
        return None


def get_or_create_user_by_linuxdo(
    db: Session,
    linuxdo_id: str,
    username: str,
    email: Optional[str],
    name: Optional[str],
    avatar_url: Optional[str],
    invite_code: Optional[str] = None,
) -> tuple[Optional[User], bool, Optional[str]]:
    """
    Get existing user or create new user from Linux Do OAuth.
    
    Logic:
    1. If user with linuxdo_id exists -> return that user
    2. If email exists and matches a local user -> link Linux Do to that user
    3. Otherwise -> create new user
    """
    try:
        # Check if user with this linuxdo_id already exists
        existing_linuxdo_user = db.query(User).filter(User.linuxdo_id == linuxdo_id).first()
        if existing_linuxdo_user:
            existing_linuxdo_user.last_login = time.time()
            if avatar_url:
                existing_linuxdo_user.avatar = avatar_url
            db.commit()
            return existing_linuxdo_user, False, None
        
        # Check if user with this email exists (link accounts)
        if email:
            existing_email_user = db.query(User).filter(User.email == email).first()
            if existing_email_user:
                existing_email_user.linuxdo_id = linuxdo_id
                existing_email_user.oauth_provider = "linuxdo"
                existing_email_user.last_login = time.time()
                if avatar_url and not existing_email_user.avatar:
                    existing_email_user.avatar = avatar_url
                db.commit()
                logger.info(f"Linked Linux Do account {username} to existing user {existing_email_user.username}")
                return existing_email_user, False, None

        from ..services.community_service import community_service

        try:
            validated_invite = community_service.resolve_registration_invite(db, invite_code, "linuxdo")
        except ValueError as exc:
            return None, False, str(exc)
        
        # Create new user
        new_username = username
        existing_username = db.query(User).filter(User.username == new_username).first()
        if existing_username:
            new_username = f"{username}_{secrets.token_hex(4)}"
        
        # Get default credits for new users
        default_credits = 0
        if app_config.enable_credits_system:
            default_credits = app_config.default_credits_for_new_users
        
        new_user = User(
            username=new_username,
            email=email,
            avatar=avatar_url,
            linuxdo_id=linuxdo_id,
            oauth_provider="linuxdo",
            registration_channel="linuxdo",
            is_active=True,
            is_admin=False,
            credits_balance=default_credits,
            created_at=time.time(),
            last_login=time.time()
        )
        # Set a random password hash (can't be used for login)
        new_user.password_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        
        db.add(new_user)
        db.flush()
        if validated_invite is not None:
            community_service.apply_invite_code_to_user(db, new_user, validated_invite, "linuxdo")
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"Created new user from Linux Do OAuth: {new_username} (Linux Do: {username})")
        return new_user, True, None
        
    except Exception as e:
        logger.error(f"Failed to get or create user from Linux Do: {e}")
        db.rollback()
        return None, False, "LinuxDo 注册失败，请稍后重试"


def is_linuxdo_oauth_enabled() -> bool:
    """Check if Linux Do OAuth is properly configured and enabled."""
    system_config = _get_system_oauth_config_sync()
    enabled = bool(system_config.get("linuxdo_oauth_enabled", app_config.linuxdo_oauth_enabled))
    client_id = str(system_config.get("linuxdo_client_id") or app_config.linuxdo_client_id or "").strip()
    client_secret = str(system_config.get("linuxdo_client_secret") or app_config.linuxdo_client_secret or "").strip()
    return (
        enabled
        and bool(client_id)
        and bool(client_secret)
    )
