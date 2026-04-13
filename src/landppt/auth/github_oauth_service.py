"""
GitHub OAuth service with PKCE support for LandPPT
Uses Valkey for state storage with in-memory fallback
"""

import secrets
import hashlib
import base64
import time
import httpx
import logging
from urllib.parse import urlencode
from typing import Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session

from ..database.models import User
from ..core.config import app_config

logger = logging.getLogger(__name__)

# GitHub OAuth endpoints
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"

# In-memory state storage (fallback when Valkey unavailable)
_oauth_states_fallback: Dict[str, Dict[str, Any]] = {}

# OAuth state TTL in seconds (30 minutes)
OAUTH_STATE_TTL = 1800

def _strip_default_port(host: str, scheme: str) -> str:
    if not host:
        return host
    normalized_scheme = (scheme or "").strip().lower()
    if normalized_scheme not in {"http", "https"}:
        return host

    default_port = "443" if normalized_scheme == "https" else "80"
    raw_host = host.strip()

    # IPv6 with port, e.g. [::1]:8000
    if raw_host.startswith("["):
        end = raw_host.find("]")
        if end > 0 and len(raw_host) > end + 2 and raw_host[end + 1] == ":":
            port = raw_host[end + 2 :]
            if port.isdigit() and port == default_port:
                return raw_host[: end + 1]
        return raw_host

    # hostname:port / ipv4:port
    if raw_host.count(":") == 1:
        hostname, port = raw_host.rsplit(":", 1)
        if port.isdigit() and port == default_port:
            return hostname
    return raw_host


def _build_callback_url_from_request(request) -> Optional[str]:
    """
    Build callback URL from incoming request/proxy headers when available.
    """
    if not request:
        return None
    try:
        headers = request.headers
        host = (headers.get("x-forwarded-host") or headers.get("host") or request.url.netloc or "").strip()
        if "," in host:
            host = host.split(",", 1)[0].strip()

        scheme = (headers.get("x-forwarded-proto") or request.url.scheme or "http").strip()
        if "," in scheme:
            scheme = scheme.split(",", 1)[0].strip()
        scheme = scheme.lower()

        if not host:
            return None
        host = _strip_default_port(host, scheme)
        return f"{scheme}://{host}/auth/github/callback"
    except Exception:
        return None


def _get_system_oauth_config_sync() -> Dict[str, Any]:
    """Best-effort read of system OAuth config from DB with app_config fallback."""
    config: Dict[str, Any] = {}
    try:
        from ..services.db_config_service import get_db_config_service

        config_service = get_db_config_service()
        config = config_service.get_all_config_sync(user_id=None)
    except Exception as exc:
        logger.warning("Failed to load GitHub OAuth config from DB: %s", exc)
    return config


def generate_pkce_pair() -> Tuple[str, str]:
    """
    Generate PKCE code_verifier and code_challenge pair.
    
    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    # Generate a random 43-128 character string for code_verifier
    code_verifier = secrets.token_urlsafe(32)  # Generates ~43 chars
    
    # Create code_challenge = BASE64URL(SHA256(code_verifier))
    code_challenge_bytes = hashlib.sha256(code_verifier.encode('ascii')).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge_bytes).rstrip(b'=').decode('ascii')
    
    return code_verifier, code_challenge


def generate_state() -> str:
    """Generate a random state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


async def store_oauth_state(
    state: str,
    code_verifier: str,
    redirect_url: str = "/dashboard",
    callback_url: Optional[str] = None,
    invite_code: Optional[str] = None,
) -> None:
    """
    Store OAuth state with code_verifier for later verification.
    Uses Valkey with in-memory fallback.
    
    Args:
        state: The state parameter
        code_verifier: The PKCE code verifier
        redirect_url: URL to redirect after successful login
    """
    state_data = {
        "code_verifier": code_verifier,
        "redirect_url": redirect_url,
        "callback_url": callback_url,
        "invite_code": (str(invite_code or "").strip().upper() or None),
        "created_at": time.time()
    }
    
    # Try Valkey first
    try:
        from ..services.cache_service import get_cache_service
        cache = await get_cache_service()
        
        logger.info(f"GitHub OAuth: Valkey connected={cache.is_connected}")
        
        if cache.is_connected:
            success = await cache.set_oauth_state("github", state, state_data, OAUTH_STATE_TTL)
            if success:
                logger.info(f"GitHub OAuth state stored in Valkey: {state[:8]}...")
                return
            else:
                logger.warning(f"GitHub OAuth: Valkey set_oauth_state returned False")
    except Exception as e:
        logger.warning(f"Failed to store OAuth state in Valkey: {e}")
    
    # Fallback to in-memory storage
    _oauth_states_fallback[state] = state_data
    logger.info(f"GitHub OAuth state stored in memory (fallback): {state[:8]}... (total in memory: {len(_oauth_states_fallback)})")
    
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
        
        logger.info(f"GitHub OAuth callback: Valkey connected={cache.is_connected}")
        
        if cache.is_connected:
            data = await cache.get_and_consume_oauth_state("github", state)
            if data:
                logger.info(f"GitHub OAuth state retrieved from Valkey: {state[:8]}...")
                return data
            else:
                logger.warning(f"GitHub OAuth: state not found in Valkey: {state[:8]}...")
    except Exception as e:
        logger.warning(f"Failed to get OAuth state from Valkey: {e}")
    
    # Fallback to in-memory storage
    logger.info(f"GitHub OAuth: checking memory fallback (total stored: {len(_oauth_states_fallback)})")
    data = _oauth_states_fallback.pop(state, None)
    if data:
        logger.info(f"GitHub OAuth state retrieved from memory (fallback): {state[:8]}...")
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


def build_authorization_url(state: str, code_challenge: str, callback_url: Optional[str] = None) -> str:
    """
    Build GitHub OAuth authorization URL with PKCE.
    
    Args:
        state: CSRF protection state parameter
        code_challenge: PKCE code challenge
        
    Returns:
        Full authorization URL
    """
    system_config = _get_system_oauth_config_sync()
    params = {
        "client_id": str(system_config.get("github_client_id") or app_config.github_client_id or "").strip(),
        "redirect_uri": callback_url or get_callback_url(),
        "scope": "read:user user:email",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "allow_signup": "true"
    }
    
    query_string = urlencode(params)
    return f"{GITHUB_AUTHORIZE_URL}?{query_string}"


def get_callback_url(request=None) -> str:
    """Get the OAuth callback URL based on current configuration."""
    system_config = _get_system_oauth_config_sync()
    request_callback = _build_callback_url_from_request(request)

    # Use configured callback URL if available (for domain deployments)
    configured_callback = str(system_config.get("github_callback_url") or app_config.github_callback_url or "").strip()
    callback_use_request_host = bool(
        system_config.get("github_callback_use_request_host", getattr(app_config, "github_callback_use_request_host", False))
    )
    if configured_callback:
        if request_callback and callback_use_request_host:
            logger.info(
                "GitHub OAuth callback uses request host because GITHUB_CALLBACK_USE_REQUEST_HOST=true: %s",
                request_callback,
            )
            return request_callback
        return configured_callback

    if request_callback:
        return request_callback
    
    # Fallback to localhost for development
    host = app_config.host
    port = app_config.port
    
    if host == "0.0.0.0":
        host = "localhost"
    
    return f"http://{host}:{port}/auth/github/callback"


async def exchange_code_for_token(
    code: str,
    code_verifier: str,
    callback_url: Optional[str] = None
) -> Optional[str]:
    """
    Exchange authorization code for access token using PKCE.
    
    Args:
        code: Authorization code from GitHub
        code_verifier: PKCE code verifier
        
    Returns:
        Access token if successful, None otherwise
    """
    system_config = _get_system_oauth_config_sync()
    client_id = str(system_config.get("github_client_id") or app_config.github_client_id or "").strip()
    client_secret = str(system_config.get("github_client_secret") or app_config.github_client_secret or "").strip()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": callback_url or get_callback_url(),
                    "code_verifier": code_verifier
                },
                headers={
                    "Accept": "application/json"
                },
                timeout=30.0
            )
            
            if response.status_code != 200:
                logger.error(f"GitHub token exchange failed: {response.status_code} - {response.text}")
                return None
            
            data = response.json()
            
            if "error" in data:
                logger.error(f"GitHub OAuth error: {data.get('error')} - {data.get('error_description')}")
                return None
            
            return data.get("access_token")
            
    except Exception as e:
        logger.error(f"Failed to exchange code for token: {e}")
        return None


async def get_github_user_info(access_token: str) -> Optional[Dict[str, Any]]:
    """
    Fetch GitHub user information using access token.
    
    Args:
        access_token: GitHub access token
        
    Returns:
        User info dict if successful, None otherwise
    """
    try:
        async with httpx.AsyncClient() as client:
            # Get user profile
            user_response = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                },
                timeout=30.0
            )
            
            if user_response.status_code != 200:
                logger.error(f"Failed to get GitHub user: {user_response.status_code}")
                return None
            
            user_data = user_response.json()
            
            # Get user emails if email is not public
            email = user_data.get("email")
            if not email:
                emails_response = await client.get(
                    GITHUB_EMAILS_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json"
                    },
                    timeout=30.0
                )
                
                if emails_response.status_code == 200:
                    emails = emails_response.json()
                    # Find primary verified email
                    for e in emails:
                        if e.get("primary") and e.get("verified"):
                            email = e.get("email")
                            break
                    # Fallback to first verified email
                    if not email:
                        for e in emails:
                            if e.get("verified"):
                                email = e.get("email")
                                break
            
            return {
                "id": str(user_data.get("id")),
                "login": user_data.get("login"),
                "email": email,
                "name": user_data.get("name"),
                "avatar_url": user_data.get("avatar_url")
            }
            
    except Exception as e:
        logger.error(f"Failed to get GitHub user info: {e}")
        return None


def get_or_create_user_by_github(
    db: Session,
    github_id: str,
    github_login: str,
    email: Optional[str],
    name: Optional[str],
    avatar_url: Optional[str],
    invite_code: Optional[str] = None,
) -> tuple[Optional[User], bool, Optional[str]]:
    """
    Get existing user or create new user from GitHub OAuth.
    
    Logic:
    1. If user with github_id exists -> return that user
    2. If email exists and matches a local user -> link GitHub to that user
    3. Otherwise -> create new user
    
    Args:
        db: Database session
        github_id: GitHub user ID
        github_login: GitHub username
        email: User's email
        name: User's display name
        avatar_url: User's avatar URL
        
    Returns:
        User object if successful, None otherwise
    """
    try:
        # Check if user with this github_id already exists
        existing_github_user = db.query(User).filter(User.github_id == github_id).first()
        if existing_github_user:
            # Update last login
            existing_github_user.last_login = time.time()
            if avatar_url:
                existing_github_user.avatar = avatar_url
            db.commit()
            return existing_github_user, False, None
        
        # Check if user with this email exists (link accounts)
        if email:
            existing_email_user = db.query(User).filter(User.email == email).first()
            if existing_email_user:
                # Link GitHub account to existing user
                existing_email_user.github_id = github_id
                existing_email_user.oauth_provider = "github"
                existing_email_user.last_login = time.time()
                if avatar_url and not existing_email_user.avatar:
                    existing_email_user.avatar = avatar_url
                db.commit()
                logger.info(f"Linked GitHub account {github_login} to existing user {existing_email_user.username}")
                return existing_email_user, False, None

        from ..services.community_service import community_service

        try:
            validated_invite = community_service.resolve_registration_invite(db, invite_code, "github")
        except ValueError as exc:
            return None, False, str(exc)
        
        # Create new user
        # Generate unique username (append random suffix if needed)
        username = github_login
        existing_username = db.query(User).filter(User.username == username).first()
        if existing_username:
            username = f"{github_login}_{secrets.token_hex(4)}"
        
        # Get default credits for new users if credits system is enabled
        default_credits = 0
        if app_config.enable_credits_system:
            default_credits = app_config.default_credits_for_new_users
        
        # Create user with a random password (OAuth users can't login with password)
        new_user = User(
            username=username,
            email=email,
            avatar=avatar_url,
            github_id=github_id,
            oauth_provider="github",
            registration_channel="github",
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
            community_service.apply_invite_code_to_user(db, new_user, validated_invite, "github")
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"Created new user from GitHub OAuth: {username} (GitHub: {github_login})")
        return new_user, True, None
        
    except Exception as e:
        logger.error(f"Failed to get or create user from GitHub: {e}")
        db.rollback()
        return None, False, "GitHub 注册失败，请稍后重试"


def is_github_oauth_enabled() -> bool:
    """Check if GitHub OAuth is properly configured and enabled."""
    system_config = _get_system_oauth_config_sync()
    enabled = bool(system_config.get("github_oauth_enabled", app_config.github_oauth_enabled))
    client_id = str(system_config.get("github_client_id") or app_config.github_client_id or "").strip()
    client_secret = str(system_config.get("github_client_secret") or app_config.github_client_secret or "").strip()
    return (
        enabled
        and bool(client_id)
        and bool(client_secret)
    )
