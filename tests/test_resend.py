import pytest


@pytest.mark.asyncio
async def test_send_email_uses_resend_provider(monkeypatch):
    # Import inside test so conftest adds src/ to sys.path first.
    from landppt.core.config import app_config
    from landppt.services.email_service import send_email

    monkeypatch.setattr(app_config, "email_provider", "resend")
    monkeypatch.setattr(app_config, "resend_api_key", "re_test_key")
    monkeypatch.setattr(app_config, "resend_from_email", "noreply@example.com")
    monkeypatch.setattr(app_config, "resend_from_name", "Acme")

    import sys
    import types

    calls = []

    fake_resend = types.ModuleType("resend")
    fake_resend.api_key = None

    class FakeEmails:
        @staticmethod
        def send(params):
            calls.append(params)
            return {"id": "email_test_id"}

    fake_resend.Emails = FakeEmails
    monkeypatch.setitem(sys.modules, "resend", fake_resend)

    ok, message = await send_email("user@example.com", "Hello", "<strong>it works</strong>")

    assert ok is True
    assert message == "发送成功"
    assert calls, "expected Resend to be called"
    assert calls[0]["from"] == "Acme <noreply@example.com>"
    assert calls[0]["to"] == ["user@example.com"]
    assert calls[0]["subject"] == "Hello"
    assert calls[0]["html"] == "<strong>it works</strong>"
