"""
Authentication service for LandPPT
"""

import asyncio
import logging
import time
import secrets
import hashlib
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..database.models import User, UserSession, UserAPIKey
from ..core.config import app_config

logger = logging.getLogger(__name__)


class AuthService:
    """Authentication service"""

    SESSION_CACHE_USER_FIELDS = (
        "id",
        "username",
        "password_hash",
        "email",
        "phone",
        "avatar",
        "is_active",
        "is_admin",
        "credits_balance",
        "created_at",
        "last_login",
        "register_ip",
        "last_login_ip",
        "registration_channel",
        "invite_code_id",
        "github_id",
        "linuxdo_id",
        "oauth_provider",
    )
    NEVER_EXPIRE_TIMESTAMP = time.mktime(time.strptime("2099-01-01 00:00:00", "%Y-%m-%d %H:%M:%S"))

    def __init__(self):
        self.session_expire_minutes = app_config.access_token_expire_minutes

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except Exception:
            return None

    def build_session_cache_payload(self, user: User, expires_at: float) -> Dict[str, Any]:
        """Serialize the authenticated user for cache-backed session auth."""
        payload: Dict[str, Any] = {
            field: getattr(user, field, None)
            for field in self.SESSION_CACHE_USER_FIELDS
        }
        payload["user_id"] = getattr(user, "id", None)
        payload["expires_at"] = expires_at
        return payload

    def user_from_session_cache(self, payload: Optional[Dict[str, Any]]) -> Optional[User]:
        """Rehydrate a lightweight detached User from cached session payload."""
        if not isinstance(payload, dict):
            return None

        user_id = self._coerce_int(payload.get("user_id", payload.get("id")))
        username = str(payload.get("username") or "").strip()
        if not user_id or not username:
            return None

        user = User(
            username=username,
            password_hash=str(payload.get("password_hash") or ""),
            email=payload.get("email"),
            phone=payload.get("phone"),
            avatar=payload.get("avatar"),
            is_active=bool(payload.get("is_active", True)),
            is_admin=bool(payload.get("is_admin", False)),
            credits_balance=int(payload.get("credits_balance") or 0),
            created_at=float(payload.get("created_at") or time.time()),
            last_login=self._coerce_float(payload.get("last_login")),
            register_ip=payload.get("register_ip"),
            last_login_ip=payload.get("last_login_ip"),
            registration_channel=payload.get("registration_channel"),
            invite_code_id=self._coerce_int(payload.get("invite_code_id")),
            github_id=payload.get("github_id"),
            linuxdo_id=payload.get("linuxdo_id"),
            oauth_provider=payload.get("oauth_provider"),
        )
        user.id = user_id
        return user

    def is_session_expired_timestamp(self, expires_at: Any) -> bool:
        """Check if a session expiration timestamp has passed."""
        value = self._coerce_float(expires_at)
        if value is None:
            return False
        if value >= self.NEVER_EXPIRE_TIMESTAMP:
            return False
        return time.time() > value

    def is_cached_session_valid(self, payload: Optional[Dict[str, Any]], user: Optional[User]) -> bool:
        """Validate cached session data before trusting it for auth."""
        if not payload or not user:
            return False
        if not getattr(user, "is_active", False):
            return False
        if self._coerce_float(payload.get("expires_at")) is None:
            return False
        return not self.is_session_expired_timestamp(payload.get("expires_at"))

    def get_session_cache_ttl(self, expires_at: Any) -> int:
        """Compute cache TTL from the session's absolute expiration."""
        value = self._coerce_float(expires_at)
        if value is None:
            return 1
        if value >= self.NEVER_EXPIRE_TIMESTAMP:
            from ..services.cache_service import CacheService
            return CacheService.SESSION_TTL
        return max(1, int(value - time.time()))

    @staticmethod
    def _log_background_task_result(task: asyncio.Task) -> None:
        try:
            task.result()
        except Exception as exc:
            logger.debug("Auth cache background task failed: %s", exc)

    def _schedule_cache_task(self, coro_factory) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        task = loop.create_task(coro_factory())
        task.add_done_callback(self._log_background_task_result)

    async def cache_session(self, session_id: str, user: User, expires_at: float) -> bool:
        """Persist session auth payload in cache for low-latency auth reads."""
        try:
            from ..services.cache_service import get_cache_service

            cache = await get_cache_service()
            if not cache or not cache.is_connected:
                return False

            payload = self.build_session_cache_payload(user, expires_at)
            ttl = self.get_session_cache_ttl(expires_at)
            return await cache.set_session(session_id, payload, ttl=ttl)
        except Exception as exc:
            logger.debug("Failed to cache session %s: %s", session_id, exc)
            return False

    async def invalidate_session_cache(self, session_id: str) -> bool:
        """Delete one session from cache."""
        try:
            from ..services.cache_service import get_cache_service

            cache = await get_cache_service()
            if not cache or not cache.is_connected:
                return False
            return await cache.delete_session(session_id)
        except Exception as exc:
            logger.debug("Failed to invalidate cached session %s: %s", session_id, exc)
            return False

    async def invalidate_user_sessions_cache(self, user_id: int) -> bool:
        """Delete all cached sessions for a user."""
        try:
            from ..services.cache_service import get_cache_service

            cache = await get_cache_service()
            if not cache or not cache.is_connected:
                return False
            return await cache.delete_user_sessions(user_id)
        except Exception as exc:
            logger.debug("Failed to invalidate cached sessions for user %s: %s", user_id, exc)
            return False

    def _schedule_session_cache_write(self, session_id: str, user: User, expires_at: float) -> None:
        self._schedule_cache_task(
            lambda: self.cache_session(session_id, user, expires_at)
        )

    def _schedule_session_cache_invalidation(self, session_id: str) -> None:
        self._schedule_cache_task(
            lambda: self.invalidate_session_cache(session_id)
        )

    def _schedule_user_sessions_cache_invalidation(self, user_id: Optional[int]) -> None:
        normalized_user_id = self._coerce_int(user_id)
        if not normalized_user_id:
            return
        self._schedule_cache_task(
            lambda: self.invalidate_user_sessions_cache(normalized_user_id)
        )

    def _get_current_expire_minutes(self) -> int:
        """Get current session expire minutes from config (for real-time updates)"""
        return app_config.access_token_expire_minutes
    
    def create_user(
        self,
        db: Session,
        username: str,
        password: str,
        email: Optional[str] = None,
        is_admin: bool = False,
        commit: bool = True,
    ) -> User:
        """Create a new user"""
        # Check if user already exists
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            raise ValueError("用户名已存在")
        
        if email:
            existing_email = db.query(User).filter(User.email == email).first()
            if existing_email:
                raise ValueError("邮箱已存在")
        
        # Get default credits for new users if credits system is enabled
        default_credits = 0
        if app_config.enable_credits_system:
            default_credits = app_config.default_credits_for_new_users
        
        # Create new user
        user = User(
            username=username,
            email=email,
            is_admin=is_admin,
            credits_balance=default_credits
        )
        user.set_password(password)
        
        db.add(user)
        if commit:
            db.commit()
            db.refresh(user)
        else:
            db.flush()
        
        return user

    
    def authenticate_user(self, db: Session, username: str, password: str) -> Optional[User]:
        """Authenticate user with username and password"""
        user = db.query(User).filter(
            and_(User.username == username, User.is_active == True)
        ).first()
        
        if user and user.check_password(password):
            # Update last login time
            user.last_login = time.time()
            db.commit()
            return user
        
        return None
    
    def create_session(self, db: Session, user: User) -> str:
        """Create a new session for user"""
        # Generate session ID
        session_id = secrets.token_urlsafe(64)

        # Get current expire minutes (for real-time config updates)
        current_expire_minutes = self._get_current_expire_minutes()

        # Calculate expiration time
        # If session_expire_minutes is 0, set to a very far future date (never expire)
        if current_expire_minutes == 0:
            # Set expiration to year 2099 (effectively never expires)
            expires_at = time.mktime(time.strptime("2099-12-31 23:59:59", "%Y-%m-%d %H:%M:%S"))
        else:
            expires_at = time.time() + (current_expire_minutes * 60)

        # Create session record
        session = UserSession(
            session_id=session_id,
            user_id=user.id,
            expires_at=expires_at
        )

        db.add(session)
        db.commit()
        self._schedule_session_cache_write(session_id, user, expires_at)

        return session_id

    @staticmethod
    def generate_api_key() -> str:
        """Generate a high-entropy user API key."""
        return f"lp_{secrets.token_urlsafe(48)}"

    @staticmethod
    def hash_api_key(api_key: str, salt: str) -> str:
        """Hash API key with per-key salt."""
        return hashlib.sha256(f"{salt}:{api_key}".encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_api_key(raw_key: str) -> str:
        key = str(raw_key or "").strip()
        if len(key) < 16:
            raise ValueError("API key must be at least 16 characters")
        if len(key) > 512:
            raise ValueError("API key is too long")
        return key

    def create_or_update_user_api_key(
        self,
        db: Session,
        user: User,
        key_name: str = "default",
        raw_api_key: Optional[str] = None,
        expires_at: Optional[float] = None,
    ) -> Tuple[UserAPIKey, str]:
        """
        Create or rotate a named API key for a user.
        Returns (record, plaintext_api_key). Plaintext should be shown once then discarded.
        """
        if not user or not user.id:
            raise ValueError("Invalid user")

        name = str(key_name or "default").strip() or "default"
        if len(name) > 100:
            raise ValueError("API key name is too long")

        plaintext = self._validate_api_key(raw_api_key) if raw_api_key else self.generate_api_key()
        salt = secrets.token_hex(16)
        key_hash = self.hash_api_key(plaintext, salt)
        key_prefix = plaintext[:12]
        now = time.time()

        existing = db.query(UserAPIKey).filter(
            and_(UserAPIKey.user_id == user.id, UserAPIKey.name == name)
        ).first()
        conflict = db.query(UserAPIKey).filter(UserAPIKey.key_hash == key_hash).first()
        if conflict and (not existing or conflict.id != existing.id):
            raise ValueError("API key already in use, choose another key")

        if existing:
            existing.key_prefix = key_prefix
            existing.key_hash = key_hash
            existing.salt = salt
            existing.is_active = True
            existing.expires_at = expires_at
            existing.last_used_at = None
            existing.created_at = now
            db.commit()
            db.refresh(existing)
            return existing, plaintext

        record = UserAPIKey(
            user_id=user.id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            salt=salt,
            is_active=True,
            created_at=now,
            expires_at=expires_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record, plaintext

    def get_user_api_key_by_name(self, db: Session, user_id: int, key_name: str) -> Optional[UserAPIKey]:
        """Get one API key record by user and name."""
        name = str(key_name or "").strip()
        if not name:
            return None
        return db.query(UserAPIKey).filter(
            and_(UserAPIKey.user_id == user_id, UserAPIKey.name == name)
        ).first()

    def list_user_api_keys(self, db: Session, user_id: int, include_inactive: bool = True) -> List[UserAPIKey]:
        """List all API keys for a user."""
        query = db.query(UserAPIKey).filter(UserAPIKey.user_id == user_id)
        if not include_inactive:
            query = query.filter(UserAPIKey.is_active == True)
        return query.order_by(UserAPIKey.created_at.desc()).all()

    def delete_user_api_key(self, db: Session, user_id: int, key_id: int) -> bool:
        """Delete a user API key permanently."""
        record = db.query(UserAPIKey).filter(
            and_(UserAPIKey.id == key_id, UserAPIKey.user_id == user_id)
        ).first()
        if not record:
            return False
        db.delete(record)
        db.commit()
        return True

    def revoke_user_api_key(self, db: Session, user_id: int, key_id: int) -> bool:
        """Backward-compatible alias for deleting a user API key."""
        return self.delete_user_api_key(db=db, user_id=user_id, key_id=key_id)
    
    def get_user_by_session(self, db: Session, session_id: str) -> Optional[User]:
        """Get user by session ID"""
        session = db.query(UserSession).filter(
            and_(
                UserSession.session_id == session_id,
                UserSession.is_active == True
            )
        ).first()
        
        if not session or session.is_expired():
            if session:
                # Mark session as inactive
                session.is_active = False
                db.commit()
            self._schedule_session_cache_invalidation(session_id)
            return None

        # If the user has been deactivated after the session was issued, revoke the session.
        try:
            if not session.user or not getattr(session.user, "is_active", False):
                session.is_active = False
                db.commit()
                self._schedule_session_cache_invalidation(session_id)
                return None
        except Exception:
            # Be conservative: if we can't validate user status, do not authenticate.
            try:
                session.is_active = False
                db.commit()
            except Exception:
                pass
            self._schedule_session_cache_invalidation(session_id)
            return None

        self._schedule_session_cache_write(session_id, session.user, session.expires_at)
        return session.user

    def get_user_by_api_key(self, db: Session, api_key: Optional[str]) -> Optional[User]:
        """
        Authenticate machine-to-machine API key and return bound active user.
        Auth sources:
        1) Environment bindings from AppConfig (global keys)
        2) User-managed keys persisted in database (hashed)
        """
        candidate = str(api_key or "").strip()
        if not candidate:
            return None

        # 1) Global env-based API keys
        bindings = app_config.get_api_key_bindings()
        if bindings:
            matched_username: Optional[str] = None
            for username, configured_key in bindings:
                configured = str(configured_key or "").strip()
                if configured and secrets.compare_digest(candidate, configured):
                    matched_username = str(username or "").strip()
                    break

            if matched_username:
                return db.query(User).filter(
                    and_(User.username == matched_username, User.is_active == True)
                ).first()

        # 2) User-managed API keys (hashed + salted)
        if len(candidate) < 16 or len(candidate) > 512:
            return None

        now = time.time()
        prefix = candidate[:12]
        records = db.query(UserAPIKey).filter(
            and_(UserAPIKey.key_prefix == prefix, UserAPIKey.is_active == True)
        ).all()

        matched_user: Optional[User] = None
        matched_record: Optional[UserAPIKey] = None
        expired_records: List[UserAPIKey] = []

        for record in records:
            if record.expires_at is not None and record.expires_at <= now:
                record.is_active = False
                expired_records.append(record)
                continue

            expected_hash = self.hash_api_key(candidate, record.salt)
            if not secrets.compare_digest(expected_hash, record.key_hash):
                continue

            user = db.query(User).filter(
                and_(User.id == record.user_id, User.is_active == True)
            ).first()
            if not user:
                return None

            matched_user = user
            matched_record = record
            break

        if not matched_user:
            if expired_records:
                try:
                    db.commit()
                except Exception:
                    db.rollback()
            return None

        if matched_record:
            matched_record.last_used_at = now
        try:
            db.commit()
        except Exception:
            db.rollback()
        return matched_user
    
    def logout_user(self, db: Session, session_id: str) -> bool:
        """Logout user by deactivating session"""
        session = db.query(UserSession).filter(
            UserSession.session_id == session_id
        ).first()

        if session:
            session.is_active = False
            db.commit()
            self._schedule_session_cache_invalidation(session_id)
            return True

        self._schedule_session_cache_invalidation(session_id)
        return False
    
    def cleanup_expired_sessions(self, db: Session) -> int:
        """Clean up expired sessions"""
        current_time = time.time()
        # Don't clean up sessions that are set to never expire (year 2099 or later)
        year_2099_timestamp = time.mktime(time.strptime("2099-01-01 00:00:00", "%Y-%m-%d %H:%M:%S"))

        expired_sessions = db.query(UserSession).filter(
            and_(
                UserSession.expires_at < current_time,
                UserSession.expires_at < year_2099_timestamp  # Exclude never-expire sessions
            )
        ).all()

        count = len(expired_sessions)
        for session in expired_sessions:
            session.is_active = False

        db.commit()
        for session in expired_sessions:
            self._schedule_session_cache_invalidation(session.session_id)
        return count
    
    def get_user_by_id(self, db: Session, user_id: int) -> Optional[User]:
        """Get user by ID"""
        return db.query(User).filter(
            and_(User.id == user_id, User.is_active == True)
        ).first()
    
    def get_user_by_username(self, db: Session, username: str) -> Optional[User]:
        """Get user by username"""
        return db.query(User).filter(
            and_(User.username == username, User.is_active == True)
        ).first()
    
    def update_user_password(self, db: Session, user: User, new_password: str) -> bool:
        """Update user password"""
        try:
            target = db.query(User).filter(User.id == user.id).first()
            if not target:
                return False
            target.set_password(new_password)
            db.commit()
            self._schedule_user_sessions_cache_invalidation(target.id)
            return True
        except Exception:
            db.rollback()
            return False
    
    def deactivate_user(self, db: Session, user: User) -> bool:
        """Deactivate user account"""
        try:
            target = db.query(User).filter(User.id == user.id).first()
            if not target:
                return False
            target.is_active = False
            # Deactivate all user sessions
            sessions = db.query(UserSession).filter(UserSession.user_id == target.id).all()
            for session in sessions:
                session.is_active = False
            db.commit()
            self._schedule_user_sessions_cache_invalidation(target.id)
            return True
        except Exception:
            db.rollback()
            return False
    
    def list_users(self, db: Session, skip: int = 0, limit: int = 100) -> list[User]:
        """List all users"""
        return db.query(User).offset(skip).limit(limit).all()
    
    def get_user_sessions(self, db: Session, user: User) -> list[UserSession]:
        """Get all active sessions for a user"""
        return db.query(UserSession).filter(
            and_(
                UserSession.user_id == user.id,
                UserSession.is_active == True
            )
        ).all()


# Global auth service instance
auth_service = AuthService()


def get_auth_service() -> AuthService:
    """Get auth service instance"""
    return auth_service


def init_default_admin(db: Session) -> None:
    """Optionally bootstrap an admin user when explicitly configured."""
    if not app_config.bootstrap_admin_enabled:
        return

    user_count = db.query(User).count()
    if user_count != 0:
        return

    bootstrap_username = (app_config.bootstrap_admin_username or "").strip()
    bootstrap_password = app_config.bootstrap_admin_password or ""

    if not bootstrap_username or not bootstrap_password:
        logger.warning(
            "Skipping admin bootstrap because LANDPPT_BOOTSTRAP_ADMIN_USERNAME or "
            "LANDPPT_BOOTSTRAP_ADMIN_PASSWORD is missing."
        )
        return

    try:
        auth_service.create_user(
            db=db,
            username=bootstrap_username,
            password=bootstrap_password,
            is_admin=True
        )
        logger.info("Bootstrapped initial admin user: %s", bootstrap_username)
    except Exception as e:
        logger.error("Failed to bootstrap initial admin user: %s", e)


def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return hash_password(password) == hashed
