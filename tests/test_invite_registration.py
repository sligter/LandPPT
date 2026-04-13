import asyncio
import importlib
import sys
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request


def _create_db():
    from landppt.database.models import (
        Base,
        CreditTransaction,
        InviteCode,
        InviteCodeUsage,
        UserConfig,
        User,
    )

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            CreditTransaction.__table__,
            InviteCode.__table__,
            InviteCodeUsage.__table__,
            UserConfig.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def _create_invite(db, *, code: str, channel: str, credits_amount: int = 0, max_uses: int = 1):
    from landppt.database.models import InviteCode

    invite = InviteCode(
        code=code,
        channel=channel,
        credits_amount=credits_amount,
        max_uses=max_uses,
        used_count=0,
        is_active=True,
        created_by=1,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def _create_user(db, username: str, email: str):
    from landppt.database.models import User

    user = User(username=username, email=email, is_admin=False, is_active=True, credits_balance=100)
    user.set_password("pw")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _set_community_setting(db, key: str, value: str, value_type: str = "boolean"):
    from landppt.database.models import UserConfig

    item = UserConfig(
        user_id=None,
        config_key=key,
        config_value=value,
        config_type=value_type,
        category="community_ops",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _make_request(path: str = "/auth/api/send-code"):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def _import_auth_routes(monkeypatch):
    import fastapi.templating

    class _DummyTemplates:
        def __init__(self, *args, **kwargs):
            self.env = types.SimpleNamespace(globals={})

        def TemplateResponse(self, *args, **kwargs):
            raise AssertionError("TemplateResponse should not be used in this test")

    monkeypatch.setattr(fastapi.templating, "Jinja2Templates", _DummyTemplates)
    sys.modules.pop("landppt.auth.routes", None)
    return importlib.import_module("landppt.auth.routes")


def test_apply_invite_code_records_reward_usage_and_channel():
    from landppt.database.models import CreditTransaction, InviteCodeUsage
    from landppt.services.community_service import community_service

    db = _create_db()
    try:
        user = _create_user(db, "mail_user", "mail@example.com")
        invite = _create_invite(db, code="MAILCODE1", channel="mail", credits_amount=25, max_uses=2)

        community_service.apply_invite_code_to_user(db, user, invite, "mail")
        db.commit()
        db.refresh(user)
        db.refresh(invite)

        usage = db.query(InviteCodeUsage).filter(InviteCodeUsage.user_id == user.id).one()
        tx = db.query(CreditTransaction).filter(CreditTransaction.user_id == user.id).one()

        assert user.registration_channel == "mail"
        assert user.invite_code_id == invite.id
        assert user.credits_balance == 125
        assert invite.used_count == 1
        assert usage.invite_code_id == invite.id
        assert usage.credits_granted == 25
        assert tx.transaction_type == "invite_reward"
        assert tx.amount == 25
    finally:
        db.close()


def test_validate_invite_code_rejects_wrong_channel():
    from landppt.services.community_service import community_service

    db = _create_db()
    try:
        _create_user(db, "admin", "admin@example.com")
        _create_invite(db, code="GHCODE1", channel="github", credits_amount=10, max_uses=1)

        try:
            community_service.validate_invite_code(db, "GHCODE1", "mail")
        except ValueError as exc:
            assert "仅限" in str(exc)
        else:
            raise AssertionError("Expected validate_invite_code to reject mismatched channel")
    finally:
        db.close()


def test_validate_invite_code_accepts_universal_channel_for_multiple_registration_methods():
    from landppt.services.community_service import community_service

    db = _create_db()
    try:
        _create_user(db, "admin", "admin@example.com")
        invite = _create_invite(db, code="UNIVCODE1", channel="universal", credits_amount=10, max_uses=2)

        mail_invite = community_service.validate_invite_code(db, invite.code, "mail")
        github_invite = community_service.validate_invite_code(db, invite.code, "github")
        linuxdo_invite = community_service.validate_invite_code(db, invite.code, "linuxdo")

        assert mail_invite.id == invite.id
        assert github_invite.id == invite.id
        assert linuxdo_invite.id == invite.id
    finally:
        db.close()


def test_apply_universal_invite_code_records_actual_registration_channel():
    from landppt.database.models import InviteCodeUsage
    from landppt.services.community_service import community_service

    db = _create_db()
    try:
        user = _create_user(db, "universal_user", "universal@example.com")
        invite = _create_invite(db, code="UNIVMAIL1", channel="universal", credits_amount=18, max_uses=3)

        community_service.apply_invite_code_to_user(db, user, invite, "mail")
        db.commit()
        db.refresh(user)
        db.refresh(invite)

        usage = db.query(InviteCodeUsage).filter(InviteCodeUsage.user_id == user.id).one()

        assert user.registration_channel == "mail"
        assert usage.channel == "mail"
        assert user.invite_code_id == invite.id
        assert invite.used_count == 1
    finally:
        db.close()


def test_api_send_code_register_rejects_invalid_invite_before_email_send(monkeypatch):
    from landppt.services import email_service, turnstile_service
    from landppt.utils import rate_limiter

    auth_routes = _import_auth_routes(monkeypatch)

    db = _create_db()
    sent = []

    async def fake_send_verification_email(email, code_type):
        sent.append((email, code_type))
        return True, "ok"

    async def fake_rate_limit_hit(**kwargs):
        return True, None, None

    try:
        monkeypatch.setattr(email_service, "send_verification_email", fake_send_verification_email)
        monkeypatch.setattr(turnstile_service, "is_turnstile_active", lambda: False)
        monkeypatch.setattr(rate_limiter, "hit", fake_rate_limit_hit)

        result = asyncio.run(
            auth_routes.api_send_code(
                _make_request(),
                auth_routes.SendCodeRequest(
                    email="new@example.com",
                    code_type="register",
                    invite_code="BADCODE",
                ),
                db,
            )
        )

        assert result["success"] is False
        assert sent == []
    finally:
        db.close()


def test_api_send_code_register_sends_email_after_valid_invite_check(monkeypatch):
    from landppt.services import email_service, turnstile_service
    from landppt.utils import rate_limiter

    auth_routes = _import_auth_routes(monkeypatch)

    db = _create_db()
    sent = []

    async def fake_send_verification_email(email, code_type):
        sent.append((email, code_type))
        return True, "sent"

    async def fake_rate_limit_hit(**kwargs):
        return True, None, None

    try:
        _create_user(db, "admin", "admin@example.com")
        invite = _create_invite(db, code="MAILSEND1", channel="mail", credits_amount=0, max_uses=2)

        monkeypatch.setattr(email_service, "send_verification_email", fake_send_verification_email)
        monkeypatch.setattr(turnstile_service, "is_turnstile_active", lambda: False)
        monkeypatch.setattr(rate_limiter, "hit", fake_rate_limit_hit)

        result = asyncio.run(
            auth_routes.api_send_code(
                _make_request(),
                auth_routes.SendCodeRequest(
                    email="valid@example.com",
                    code_type="register",
                    invite_code=invite.code,
                ),
                db,
            )
        )

        assert result["success"] is True
        assert sent == [("valid@example.com", "register")]
    finally:
        db.close()


def test_api_send_code_reset_rejects_when_turnstile_verification_fails(monkeypatch):
    from landppt.services import email_service, turnstile_service

    auth_routes = _import_auth_routes(monkeypatch)

    db = _create_db()
    sent = []

    async def fake_send_verification_email(email, code_type):
        sent.append((email, code_type))
        return True, "sent"

    async def fake_verify_turnstile(token, remote_ip):
        return False, "请先完成人机验证"

    try:
        _create_user(db, "reset_user", "reset@example.com")

        monkeypatch.setattr(email_service, "send_verification_email", fake_send_verification_email)
        monkeypatch.setattr(turnstile_service, "is_turnstile_active", lambda: True)
        monkeypatch.setattr(turnstile_service, "verify_turnstile", fake_verify_turnstile)

        result = asyncio.run(
            auth_routes.api_send_code(
                _make_request(),
                auth_routes.SendCodeRequest(
                    email="reset@example.com",
                    code_type="reset",
                ),
                db,
            )
        )

        assert result["success"] is False
        assert "人机验证" in result["message"]
        assert sent == []
    finally:
        db.close()


def test_api_send_code_reset_sends_email_after_turnstile_check(monkeypatch):
    from landppt.services import email_service, turnstile_service

    auth_routes = _import_auth_routes(monkeypatch)

    db = _create_db()
    sent = []
    verify_calls = []

    async def fake_send_verification_email(email, code_type):
        sent.append((email, code_type))
        return True, "sent"

    async def fake_verify_turnstile(token, remote_ip):
        verify_calls.append((token, remote_ip))
        return True, "ok"

    try:
        _create_user(db, "reset_user_ok", "reset-ok@example.com")

        monkeypatch.setattr(email_service, "send_verification_email", fake_send_verification_email)
        monkeypatch.setattr(turnstile_service, "is_turnstile_active", lambda: True)
        monkeypatch.setattr(turnstile_service, "verify_turnstile", fake_verify_turnstile)

        result = asyncio.run(
            auth_routes.api_send_code(
                _make_request(),
                auth_routes.SendCodeRequest(
                    email="reset-ok@example.com",
                    code_type="reset",
                    turnstile_token="turnstile-token-ok",
                ),
                db,
            )
        )

        assert result["success"] is True
        assert verify_calls == [("turnstile-token-ok", "127.0.0.1")]
        assert sent == [("reset-ok@example.com", "reset")]
    finally:
        db.close()


def test_resolve_registration_invite_allows_blank_when_switch_disabled():
    from landppt.services.community_service import community_service

    db = _create_db()
    try:
        _set_community_setting(db, "invite_code_required_for_registration", "false")
        invite = community_service.resolve_registration_invite(db, "", "mail")
        assert invite is None
        assert community_service.is_invite_code_required_for_registration(db) is False
    finally:
        db.close()


def test_github_oauth_new_user_requires_and_consumes_invite_code():
    from landppt.auth.github_oauth_service import get_or_create_user_by_github
    from landppt.core.config import app_config
    from landppt.database.models import InviteCodeUsage

    db = _create_db()
    try:
        _create_user(db, "admin", "admin@example.com")
        invite = _create_invite(db, code="GITHUB01", channel="github", credits_amount=15, max_uses=1)

        user, created, error = get_or_create_user_by_github(
            db=db,
            github_id="gh-001",
            github_login="octocat",
            email="octocat@example.com",
            name="Octo Cat",
            avatar_url=None,
            invite_code=None,
        )
        assert user is None
        assert created is False
        assert "邀请码" in (error or "")

        user, created, error = get_or_create_user_by_github(
            db=db,
            github_id="gh-001",
            github_login="octocat",
            email="octocat@example.com",
            name="Octo Cat",
            avatar_url=None,
            invite_code=invite.code,
        )
        assert error is None
        assert created is True
        assert user is not None
        assert user.registration_channel == "github"
        assert user.credits_balance == app_config.default_credits_for_new_users + 15
        assert db.query(InviteCodeUsage).filter(InviteCodeUsage.user_id == user.id).count() == 1
    finally:
        db.close()


def test_github_oauth_new_user_can_register_without_invite_when_switch_disabled():
    from landppt.auth.github_oauth_service import get_or_create_user_by_github
    from landppt.core.config import app_config
    from landppt.database.models import InviteCodeUsage

    db = _create_db()
    try:
        _create_user(db, "admin", "admin@example.com")
        _set_community_setting(db, "invite_code_required_for_registration", "false")

        user, created, error = get_or_create_user_by_github(
            db=db,
            github_id="gh-002",
            github_login="hubot",
            email="hubot@example.com",
            name="Hubot",
            avatar_url=None,
            invite_code=None,
        )

        assert error is None
        assert created is True
        assert user is not None
        assert user.registration_channel == "github"
        assert user.invite_code_id is None
        assert user.credits_balance == app_config.default_credits_for_new_users
        assert db.query(InviteCodeUsage).filter(InviteCodeUsage.user_id == user.id).count() == 0
    finally:
        db.close()
