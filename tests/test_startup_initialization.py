from contextlib import contextmanager

import pytest


@contextmanager
def _owner_gate(*args, **kwargs):
    yield True


@contextmanager
def _follower_gate(*args, **kwargs):
    yield False


@pytest.mark.asyncio
async def test_run_startup_initialization_runs_once_for_owner(monkeypatch):
    import landppt.database.startup_initialization as mod

    calls = []

    async def fake_init_db():
        calls.append("init_db")

    async def fake_run_startup_migrations():
        calls.append("migrate")
        return True

    async def fake_ensure_default_templates_exist():
        calls.append("templates")
        return [1, 2]

    monkeypatch.setattr(mod, "_startup_owner_gate", _owner_gate)
    monkeypatch.setattr(mod, "init_db", fake_init_db)
    monkeypatch.setattr(mod, "run_startup_migrations", fake_run_startup_migrations)
    monkeypatch.setattr(mod, "ensure_default_templates_exist", fake_ensure_default_templates_exist)

    result = await mod.run_startup_initialization()

    assert result is True
    assert calls == ["init_db", "migrate", "templates"]


@pytest.mark.asyncio
async def test_run_startup_initialization_skips_for_follower(monkeypatch):
    import landppt.database.startup_initialization as mod

    calls = []

    async def fake_init_db():
        calls.append("init_db")

    async def fake_run_startup_migrations():
        calls.append("migrate")
        return True

    async def fake_ensure_default_templates_exist():
        calls.append("templates")
        return [1]

    monkeypatch.setattr(mod, "_startup_owner_gate", _follower_gate)
    monkeypatch.setattr(mod, "init_db", fake_init_db)
    monkeypatch.setattr(mod, "run_startup_migrations", fake_run_startup_migrations)
    monkeypatch.setattr(mod, "ensure_default_templates_exist", fake_ensure_default_templates_exist)

    result = await mod.run_startup_initialization()

    assert result is False
    assert calls == []
