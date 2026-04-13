import pytest


@pytest.mark.asyncio
async def test_clear_user_cache_deletes_only_current_user_entries():
    from landppt.auth.request_context import current_user_id
    from landppt.services.image.image_service import ImageService
    from landppt.services.image.models import ImageCacheInfo

    service = ImageService({"cache": {}})

    class _FakeCacheManager:
        def __init__(self):
            self._cache_index = {
                "u1_hash1": ImageCacheInfo(
                    cache_key="u1_hash1",
                    file_path="/tmp/u1_hash1.png",
                    file_size=10,
                    created_at=1,
                    last_accessed=1,
                    access_count=1,
                ),
                "u1_hash2": ImageCacheInfo(
                    cache_key="u1_hash2",
                    file_path="/tmp/u1_hash2.png",
                    file_size=12,
                    created_at=1,
                    last_accessed=1,
                    access_count=1,
                ),
                "u2_hash1": ImageCacheInfo(
                    cache_key="u2_hash1",
                    file_path="/tmp/u2_hash1.png",
                    file_size=14,
                    created_at=1,
                    last_accessed=1,
                    access_count=1,
                ),
                "public_hash": ImageCacheInfo(
                    cache_key="public_hash",
                    file_path="/tmp/public_hash.png",
                    file_size=16,
                    created_at=1,
                    last_accessed=1,
                    access_count=1,
                ),
            }
            self.removed = []

        def _load_cache_index(self):
            return None

        async def remove_from_cache(self, cache_key):
            self.removed.append(cache_key)
            self._cache_index.pop(cache_key, None)

    original_cache_manager = service.cache_manager
    original_initialized = service.initialized
    token = current_user_id.set(1)
    try:
        service.cache_manager = _FakeCacheManager()
        service.initialized = True

        deleted_count = await service.clear_user_cache()

        assert deleted_count == 2
        assert service.cache_manager.removed == ["u1_hash1", "u1_hash2"]
        assert sorted(service.cache_manager._cache_index.keys()) == ["public_hash", "u2_hash1"]
    finally:
        current_user_id.reset(token)
        service.cache_manager = original_cache_manager
        service.initialized = original_initialized


@pytest.mark.asyncio
async def test_clear_all_images_uses_user_scoped_clear_for_normal_users(monkeypatch):
    from landppt.api import image_api
    from landppt.auth.request_context import current_user_id
    from types import SimpleNamespace

    class _FakeImageService:
        def __init__(self):
            self.clear_user_calls = []
            self.clear_all_calls = 0

        async def get_cache_stats(self):
            return {"total_entries": 3}

        async def clear_user_cache(self, user_id=None):
            self.clear_user_calls.append(user_id)
            return 3

        async def clear_all_cache(self):
            self.clear_all_calls += 1
            return 99

    fake_service = _FakeImageService()
    monkeypatch.setattr(image_api, "get_image_service", lambda: fake_service)

    token = current_user_id.set(7)
    try:
        result = await image_api.clear_all_images(user=SimpleNamespace(id=7, is_admin=False))
    finally:
        current_user_id.reset(token)

    assert result["success"] is True
    assert result["deleted_count"] == 3
    assert result["message"] == "成功清空你的图库，删除了 3 张图片"
    assert fake_service.clear_user_calls == [7]
    assert fake_service.clear_all_calls == 0


@pytest.mark.asyncio
async def test_clear_all_images_preserves_global_clear_for_explicit_admin_scope(monkeypatch):
    from landppt.api import image_api
    from landppt.auth.request_context import USER_SCOPE_ALL, current_user_id
    from types import SimpleNamespace

    class _FakeImageService:
        def __init__(self):
            self.clear_user_calls = []
            self.clear_all_calls = 0

        async def get_cache_stats(self):
            return {"total_entries": 5}

        async def clear_user_cache(self, user_id=None):
            self.clear_user_calls.append(user_id)
            return 0

        async def clear_all_cache(self):
            self.clear_all_calls += 1
            return 5

    fake_service = _FakeImageService()
    monkeypatch.setattr(image_api, "get_image_service", lambda: fake_service)

    token = current_user_id.set(USER_SCOPE_ALL)
    try:
        result = await image_api.clear_all_images(user=SimpleNamespace(id=1, is_admin=True))
    finally:
        current_user_id.reset(token)

    assert result["success"] is True
    assert result["deleted_count"] == 5
    assert result["message"] == "成功清空全局图库，删除了 5 张图片"
    assert fake_service.clear_user_calls == []
    assert fake_service.clear_all_calls == 1
