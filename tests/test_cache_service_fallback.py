import pytest


@pytest.mark.asyncio
async def test_get_cache_service_disables_valkey_after_connection_failure(monkeypatch):
    import landppt.services.cache_service as mod
    from landppt.core.config import app_config

    await mod.close_cache_service()
    monkeypatch.setattr(app_config, "cache_backend", "valkey")
    monkeypatch.setattr(app_config, "valkey_url", "valkey://valkey:6379")

    attempts = {"count": 0}

    async def fake_connect(self):
        attempts["count"] += 1
        self.enabled = False
        self._connected = False
        self._client = None
        return False

    monkeypatch.setattr(mod.CacheService, "connect", fake_connect)

    cache1 = await mod.get_cache_service()
    cache2 = await mod.get_cache_service()

    assert attempts["count"] == 1
    assert cache1 is cache2
    assert cache1.enabled is False
    assert cache1.is_connected is False

    await mod.close_cache_service()


@pytest.mark.asyncio
async def test_get_cache_service_keeps_memory_backend_without_connect_attempt(monkeypatch):
    import landppt.services.cache_service as mod
    from landppt.core.config import app_config

    await mod.close_cache_service()
    monkeypatch.setattr(app_config, "cache_backend", "memory")

    attempts = {"count": 0}

    async def fake_connect(self):
        attempts["count"] += 1
        return False

    monkeypatch.setattr(mod.CacheService, "connect", fake_connect)

    cache = await mod.get_cache_service()

    assert attempts["count"] == 0
    assert cache.enabled is False
    assert cache.is_connected is False

    await mod.close_cache_service()
