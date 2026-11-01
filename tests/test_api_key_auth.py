from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from types import SimpleNamespace
import time
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


@pytest.fixture
def key_db(monkeypatch):
    from landppt.auth.auth_service import AuthService
    from landppt.core.config import app_config
    from landppt.database.models import User

    monkeypatch.setattr(app_config, "api_key", None)
    monkeypatch.setattr(app_config, "api_keys", None)
    db = _create_db()
    alice = User(username="alice", password_hash="unused", is_active=True)
    bob = User(username="bob", password_hash="unused", is_active=True)
    db.add_all([alice, bob])
    db.commit()
    yield SimpleNamespace(db=db, auth=AuthService(), alice=alice, bob=bob)
    db.close()
    db.get_bind().dispose()


def _legacy_key(state, user, key, name="legacy", **kwargs):
    from landppt.database.models import UserAPIKey

    salt = f"legacy-{user.id}-{name}"
    record = UserAPIKey(
        user_id=user.id,
        name=name,
        salt=salt,
        key_prefix=key[:12],
        key_hash=state.auth.hash_api_key(key, salt),
        **kwargs,
    )
    state.db.add(record)
    state.db.commit()
    return record


@pytest.mark.parametrize("same_user", [False, True])
@pytest.mark.parametrize("active", [False, True])
def test_duplicate_plaintext_keys_are_rejected(key_db, same_user, active):
    state = key_db
    record, key = state.auth.create_or_update_user_api_key(state.db, state.alice)
    record.is_active = active
    state.db.commit()
    owner = state.alice if same_user else state.bob
    with pytest.raises(ValueError, match="already in use"):
        state.auth.create_or_update_user_api_key(
            state.db, owner, key_name="other", raw_api_key=key
        )


def test_rotation_conflict_does_not_invalidate_current_key(key_db):
    state = key_db
    alice_record, alice_key = state.auth.create_or_update_user_api_key(
        state.db, state.alice
    )
    _, bob_key = state.auth.create_or_update_user_api_key(state.db, state.bob)
    with pytest.raises(ValueError, match="already in use"):
        state.auth.create_or_update_user_api_key(
            state.db, state.alice, raw_api_key=bob_key
        )
    assert state.auth.get_user_by_api_key(state.db, alice_key).id == state.alice.id
    same_record, _ = state.auth.create_or_update_user_api_key(
        state.db, state.alice, raw_api_key=alice_key
    )
    assert same_record.id == alice_record.id
    assert same_record.key_fingerprint == state.auth.fingerprint_api_key(alice_key)


def test_environment_keys_cannot_be_registered_as_personal_keys(key_db, monkeypatch):
    from landppt.core.config import app_config

    key = "test-environment-key-0001"
    monkeypatch.setattr(app_config, "api_key", key)
    monkeypatch.setattr(app_config, "api_key_user", "alice")
    with pytest.raises(ValueError, match="already in use"):
        key_db.auth.create_or_update_user_api_key(
            key_db.db, key_db.bob, raw_api_key=key
        )
    assert key_db.auth.get_user_by_api_key(key_db.db, key).id == key_db.alice.id


def test_legacy_salted_keys_are_checked_and_upgraded_without_rotation(key_db):
    key = "test-legacy-key-00000001"
    record = _legacy_key(key_db, key_db.alice, key)
    assert record.key_fingerprint is None
    with pytest.raises(ValueError, match="already in use"):
        key_db.auth.create_or_update_user_api_key(
            key_db.db, key_db.bob, raw_api_key=key
        )
    assert key_db.auth.get_user_by_api_key(key_db.db, key).id == key_db.alice.id
    assert record.key_fingerprint == key_db.auth.fingerprint_api_key(key)
    assert record.last_used_at is not None


@pytest.mark.parametrize("same_user", [False, True])
def test_legacy_duplicate_keys_fail_closed(key_db, same_user):
    key = "test-legacy-duplicate-0001"
    first = _legacy_key(key_db, key_db.alice, key)
    second = _legacy_key(
        key_db, key_db.alice if same_user else key_db.bob, key, name="other"
    )
    assert key_db.auth.get_user_by_api_key(key_db.db, key) is None
    assert first.last_used_at is None
    assert second.last_used_at is None


@pytest.mark.parametrize("username", ["alice", "bob"])
def test_environment_collision_does_not_shadow_personal_key(
    key_db, monkeypatch, username
):
    from landppt.core.config import app_config

    _, key = key_db.auth.create_or_update_user_api_key(key_db.db, key_db.bob)
    monkeypatch.setattr(app_config, "api_key", key)
    monkeypatch.setattr(app_config, "api_key_user", username)
    assert key_db.auth.get_user_by_api_key(key_db.db, key) is None


def test_ambiguous_environment_bindings_fail_closed(key_db, monkeypatch):
    from landppt.core.config import app_config

    key = "test-shared-environment-key"
    monkeypatch.setattr(app_config, "api_keys", f"alice:{key},bob:{key}")
    assert key_db.auth.get_user_by_api_key(key_db.db, key) is None


@pytest.mark.parametrize("reason", ["expired", "revoked", "inactive_user"])
def test_unusable_legacy_keys_do_not_acquire_fingerprints(key_db, reason):
    key = "test-unusable-legacy-key-0001"
    record = _legacy_key(key_db, key_db.alice, key)
    if reason == "expired":
        record.expires_at = time.time() - 1
    elif reason == "revoked":
        record.is_active = False
    else:
        key_db.alice.is_active = False
    key_db.db.commit()
    assert key_db.auth.get_user_by_api_key(key_db.db, key) is None
    assert record.key_fingerprint is None
    assert record.last_used_at is None


def test_distinct_keys_with_same_prefix_keep_their_owners(key_db):
    first = "test-common-prefix-00000001"
    second = "test-common-prefix-00000002"
    for user, key in ((key_db.alice, first), (key_db.bob, second)):
        key_db.auth.create_or_update_user_api_key(key_db.db, user, raw_api_key=key)
    assert key_db.auth.get_user_by_api_key(key_db.db, first).id == key_db.alice.id
    assert key_db.auth.get_user_by_api_key(key_db.db, second).id == key_db.bob.id


def test_database_uniqueness_handles_a_stale_conflict_check(key_db, monkeypatch):
    from landppt.database.models import UserAPIKey

    record, key = key_db.auth.create_or_update_user_api_key(key_db.db, key_db.alice)
    # Simulate a request whose conflict read preceded the winning transaction.
    monkeypatch.setattr(key_db.auth, "_matching_api_key_records", lambda *args: [])
    with pytest.raises(ValueError, match="already in use"):
        key_db.auth.create_or_update_user_api_key(
            key_db.db, key_db.bob, raw_api_key=key
        )
    assert key_db.db.query(UserAPIKey).count() == 1
    assert key_db.db.query(UserAPIKey).one().id == record.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/private", "/v1/models", "/projects/test/confirm-requirements", "/"]
)
@pytest.mark.parametrize("header", ["authorization", "x-api-key"])
@pytest.mark.parametrize("validity", ["valid", "invalid", "empty"])
async def test_explicit_key_wins_over_cached_cookie(
    key_db, monkeypatch, path, header, validity
):
    from unittest.mock import AsyncMock
    from starlette.requests import Request
    from starlette.responses import Response
    import landppt.auth.middleware as module
    from landppt.database.models import UserSession

    state = key_db
    _, key = state.auth.create_or_update_user_api_key(state.db, state.bob)
    state.db.add(
        UserSession(
            session_id="alice-session",
            user_id=state.alice.id,
            expires_at=time.time() + 300,
        )
    )
    state.db.commit()
    middleware = module.AuthMiddleware()
    middleware.auth_service = state.auth
    cache = AsyncMock(
        side_effect=AssertionError("Key requests must not use the session cache")
    )
    monkeypatch.setattr(middleware, "_get_user_from_session_cache", cache)

    def get_db():
        yield state.db

    monkeypatch.setattr(module, "get_db", get_db)
    token = (
        key if validity == "valid" else "invalid-key" if validity == "invalid" else ""
    )
    value = f"Bearer {token}" if header == "authorization" else token
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "server": ("localhost", 8000),
            "headers": [
                (b"host", b"localhost"),
                (b"cookie", b"session_id=alice-session"),
                (header.encode(), value.encode()),
            ],
        }
    )
    seen = []

    async def call_next(req):
        seen.append(req.state.user.id if req.state.user else None)
        return Response(status_code=204)

    response = await middleware(request, call_next)
    cache.assert_not_awaited()
    if validity == "valid":
        assert response.status_code == 204
        assert seen == [state.bob.id]
    elif path == "/":
        assert response.status_code == 204
        assert seen == [None]
    else:
        assert response.status_code == 401
        assert seen == []


@pytest.mark.parametrize("header", ["authorization", "x-api-key"])
@pytest.mark.parametrize("token", ["invalid-key", ""])
def test_optional_dependency_does_not_fall_back_to_cookie(key_db, header, token):
    from landppt.auth.middleware import get_current_user_optional
    from landppt.database.models import UserSession

    state = key_db
    state.db.add(
        UserSession(
            session_id="alice-session",
            user_id=state.alice.id,
            expires_at=time.time() + 300,
        )
    )
    state.db.commit()
    value = f"Bearer {token}" if header == "authorization" else token
    req = _build_request(
        headers={header: value}, cookies={"session_id": "alice-session"}
    )
    assert get_current_user_optional(req, state.db) is None


@pytest.mark.asyncio
async def test_key_management_http_rejects_duplicates_and_keeps_secrets_private(
    key_db, monkeypatch
):
    import httpx
    from fastapi import FastAPI
    from landppt.auth import auth_router
    import landppt.auth.middleware as middleware_module
    from landppt.database.database import get_db

    state = key_db
    _, alice_key = state.auth.create_or_update_user_api_key(state.db, state.alice)
    _, bob_key = state.auth.create_or_update_user_api_key(state.db, state.bob)

    def request_db():
        yield state.db

    monkeypatch.setattr(middleware_module, "get_db", request_db)
    middleware = middleware_module.AuthMiddleware()
    app = FastAPI()
    app.middleware("http")(middleware)
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = request_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        alice_headers = {"Authorization": f"Bearer {alice_key}"}
        bob_headers = {"X-API-Key": bob_key}
        shared = "test-http-custom-key-00000001"
        created = await client.post(
            "/api/auth/api-keys",
            headers=alice_headers,
            json={"name": "automation", "api_key": shared},
        )
        assert created.status_code == 200
        assert created.json()["api_key"] == shared
        key_id = created.json()["api_key_record"]["id"]
        duplicate = await client.post(
            "/api/auth/api-keys",
            headers=bob_headers,
            json={"name": "automation", "api_key": shared},
        )
        assert duplicate.status_code == 400
        listed = await client.get("/api/auth/api-keys", headers=alice_headers)
        for record in listed.json()["api_keys"]:
            assert not {"api_key", "key_hash", "salt", "key_fingerprint"}.intersection(
                record
            )
        assert shared not in listed.text
        denied = await client.delete(
            f"/api/auth/api-keys/{key_id}", headers=bob_headers
        )
        assert denied.status_code == 404
        revoked = await client.delete(
            f"/api/auth/api-keys/{key_id}", headers=alice_headers
        )
        assert revoked.status_code == 200
        assert (
            await client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {shared}"}
            )
        ).status_code == 401
