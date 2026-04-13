from contextlib import contextmanager

import pytest


@contextmanager
def _noop_lock(*args, **kwargs):
    yield


def test_app_config_parses_startup_migration_settings(monkeypatch):
    from landppt.core.config import AppConfig

    monkeypatch.delenv("DATABASE_URL", raising=False)

    config = AppConfig(
        auto_migrate_on_startup="false",
        auto_migrate_fail_fast="true",
        auto_migrate_lock_timeout_seconds="15",
        auto_migrate_lock_stale_seconds="45",
        allow_header_session_auth="false",
        bootstrap_admin_enabled="true",
        enable_api_docs="false",
    )

    assert config.port == 8000
    assert config.database_url == "sqlite:///./landppt.db"
    assert config.auto_migrate_on_startup is False
    assert config.auto_migrate_fail_fast is True
    assert config.auto_migrate_lock_timeout_seconds == 15
    assert config.auto_migrate_lock_stale_seconds == 45
    assert config.allow_header_session_auth is False
    assert config.bootstrap_admin_enabled is True
    assert config.enable_api_docs is False


@pytest.mark.asyncio
async def test_run_startup_migrations_skips_when_disabled(monkeypatch):
    import landppt.database.startup_migrations as mod
    from landppt.core.config import app_config

    monkeypatch.setattr(app_config, "auto_migrate_on_startup", False)

    result = await mod.run_startup_migrations()

    assert result is False


@pytest.mark.asyncio
async def test_run_startup_migrations_runs_pending_migrations(monkeypatch):
    import landppt.database.startup_migrations as mod
    from landppt.core.config import app_config

    class FakeManager:
        def __init__(self):
            self.calls = []

        async def get_migration_status(self):
            self.calls.append("status")
            return {"pending_migrations": ["012"]}

        async def migrate_up(self):
            self.calls.append("migrate")
            return True

    fake_manager = FakeManager()

    monkeypatch.setattr(app_config, "auto_migrate_on_startup", True)
    monkeypatch.setattr(app_config, "auto_migrate_fail_fast", True)
    monkeypatch.setattr(app_config, "auto_migrate_lock_timeout_seconds", 1)
    monkeypatch.setattr(app_config, "auto_migrate_lock_stale_seconds", 1)
    monkeypatch.setattr(mod, "_file_lock", _noop_lock)
    monkeypatch.setattr(mod, "_get_migration_manager", lambda: fake_manager)

    result = await mod.run_startup_migrations()

    assert result is True
    assert fake_manager.calls == ["status", "migrate"]


@pytest.mark.asyncio
async def test_run_startup_migrations_can_fail_soft(monkeypatch):
    import landppt.database.startup_migrations as mod
    from landppt.core.config import app_config

    class FakeManager:
        async def get_migration_status(self):
            return {"pending_migrations": ["012"]}

        async def migrate_up(self):
            return False

    monkeypatch.setattr(app_config, "auto_migrate_on_startup", True)
    monkeypatch.setattr(app_config, "auto_migrate_fail_fast", False)
    monkeypatch.setattr(app_config, "auto_migrate_lock_timeout_seconds", 1)
    monkeypatch.setattr(app_config, "auto_migrate_lock_stale_seconds", 1)
    monkeypatch.setattr(mod, "_file_lock", _noop_lock)
    monkeypatch.setattr(mod, "_get_migration_manager", lambda: FakeManager())

    result = await mod.run_startup_migrations()

    assert result is False
