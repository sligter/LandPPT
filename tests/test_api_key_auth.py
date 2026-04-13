from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from types import SimpleNamespace
import pytest


class _HeaderMap(dict):
    def __init__(self, values: dict | None = None):
        super().__init__()
        for key, value in (values or {}).items():
            self[str(key).lower()] = str(value)

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _FakeRequest:
    def __init__(self, headers: dict | None = None, cookies: dict | None = None):
        self.headers = _HeaderMap(headers)
        self.cookies = dict(cookies or {})
        self.state = SimpleNamespace()


def _build_request(headers: dict | None = None, cookies: dict | None = None):
    return _FakeRequest(headers=headers, cookies=cookies)


def _create_db():
    from landppt.database.models import Base, User, UserSession, UserAPIKey

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__, UserAPIKey.__table__])
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def _create_user(db, username: str, email: str):
    from landppt.database.models import User

    user = User(username=username, email=email, is_admin=False, is_active=True, credits_balance=0)
    user.set_password("pw")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_auth_service_supports_single_api_key(monkeypatch):
    from landppt.auth.auth_service import AuthService
    from landppt.core.config import app_config

    db = _create_db()
    try:
        admin = _create_user(db, "admin", "admin@example.com")
        auth = AuthService()

        monkeypatch.setattr(app_config, "api_key", "n8n-single-key")
        monkeypatch.setattr(app_config, "api_key_user", "admin")
        monkeypatch.setattr(app_config, "api_keys", None)

        resolved = auth.get_user_by_api_key(db, "n8n-single-key")
        assert resolved is not None
        assert resolved.id == admin.id
        assert auth.get_user_by_api_key(db, "wrong-key") is None
    finally:
        db.close()


def test_auth_service_supports_multiple_api_key_bindings(monkeypatch):
    from landppt.auth.auth_service import AuthService
    from landppt.core.config import app_config

    db = _create_db()
    try:
        admin = _create_user(db, "admin", "admin@example.com")
        alice = _create_user(db, "alice", "alice@example.com")
        auth = AuthService()

        monkeypatch.setattr(app_config, "api_key", None)
        monkeypatch.setattr(app_config, "api_key_user", "admin")
        monkeypatch.setattr(app_config, "api_keys", "alice:key-a,admin:key-admin,key-default")

        resolved_alice = auth.get_user_by_api_key(db, "key-a")
        assert resolved_alice is not None
        assert resolved_alice.id == alice.id

        resolved_admin = auth.get_user_by_api_key(db, "key-admin")
        assert resolved_admin is not None
        assert resolved_admin.id == admin.id

        # Key without user binding falls back to LANDPPT_API_KEY_USER
        resolved_default = auth.get_user_by_api_key(db, "key-default")
        assert resolved_default is not None
        assert resolved_default.id == admin.id
    finally:
        db.close()


def test_get_current_user_optional_reads_api_key_header(monkeypatch):
    pytest.importorskip("fastapi")
    from landppt.auth.middleware import get_current_user_optional
    from landppt.core.config import app_config

    db = _create_db()
    try:
        admin = _create_user(db, "admin", "admin@example.com")

        monkeypatch.setattr(app_config, "api_key", "n8n-header-key")
        monkeypatch.setattr(app_config, "api_key_user", "admin")
        monkeypatch.setattr(app_config, "api_keys", None)

        request = _build_request(headers={"x-api-key": "n8n-header-key"})
        resolved = get_current_user_optional(request, db)
        assert resolved is not None
        assert resolved.id == admin.id
        assert getattr(request.state, "user", None) is not None
    finally:
        db.close()


def test_get_current_user_optional_ignores_x_session_id_when_disabled(monkeypatch):
    pytest.importorskip("fastapi")
    from landppt.auth.auth_service import AuthService
    from landppt.auth.middleware import get_current_user_optional
    from landppt.core.config import app_config

    db = _create_db()
    try:
        admin = _create_user(db, "admin", "admin@example.com")
        auth = AuthService()
        session_id = auth.create_session(db, admin)

        monkeypatch.setattr(app_config, "allow_header_session_auth", False)
        request = _build_request(headers={"x-session-id": session_id})
        resolved = get_current_user_optional(request, db)
        assert resolved is None
    finally:
        db.close()


def test_get_current_user_optional_reads_x_session_id(monkeypatch):
    pytest.importorskip("fastapi")
    from landppt.auth.auth_service import AuthService
    from landppt.auth.middleware import get_current_user_optional
    from landppt.core.config import app_config

    db = _create_db()
    try:
        admin = _create_user(db, "admin", "admin@example.com")
        auth = AuthService()
        session_id = auth.create_session(db, admin)

        monkeypatch.setattr(app_config, "allow_header_session_auth", True)
        request = _build_request(headers={"x-session-id": session_id})
        resolved = get_current_user_optional(request, db)
        assert resolved is not None
        assert resolved.id == admin.id
    finally:
        db.close()


def test_auth_service_supports_user_managed_api_key(monkeypatch):
    from landppt.auth.auth_service import AuthService
    from landppt.core.config import app_config

    db = _create_db()
    try:
        user = _create_user(db, "bob", "bob@example.com")
        auth = AuthService()

        monkeypatch.setattr(app_config, "api_key", None)
        monkeypatch.setattr(app_config, "api_key_user", "admin")
        monkeypatch.setattr(app_config, "api_keys", None)

        _, plaintext = auth.create_or_update_user_api_key(
            db=db,
            user=user,
            key_name="n8n",
            raw_api_key="bob-n8n-api-key-0001",
        )

        resolved = auth.get_user_by_api_key(db, plaintext)
        assert resolved is not None
        assert resolved.id == user.id
    finally:
        db.close()


def test_user_managed_api_key_rotation_and_revoke(monkeypatch):
    from landppt.auth.auth_service import AuthService
    from landppt.core.config import app_config

    db = _create_db()
    try:
        user = _create_user(db, "carol", "carol@example.com")
        auth = AuthService()

        monkeypatch.setattr(app_config, "api_key", None)
        monkeypatch.setattr(app_config, "api_key_user", "admin")
        monkeypatch.setattr(app_config, "api_keys", None)

        first_record, first_key = auth.create_or_update_user_api_key(
            db=db,
            user=user,
            key_name="default",
            raw_api_key="carol-initial-api-key-0001",
        )
        assert auth.get_user_by_api_key(db, first_key) is not None

        second_record, second_key = auth.create_or_update_user_api_key(
            db=db,
            user=user,
            key_name="default",
            raw_api_key="carol-rotated-api-key-0002",
        )
        assert first_record.id == second_record.id
        assert auth.get_user_by_api_key(db, first_key) is None
        assert auth.get_user_by_api_key(db, second_key) is not None

        revoked = auth.revoke_user_api_key(db=db, user_id=user.id, key_id=second_record.id)
        assert revoked is True
        assert auth.get_user_by_api_key(db, second_key) is None
    finally:
        db.close()
