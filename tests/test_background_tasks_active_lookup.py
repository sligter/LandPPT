import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _task(task_id, status, *, updated_at=None, metadata=None):
    from landppt.services.background_tasks import BackgroundTask

    return BackgroundTask(
        task_id=task_id,
        task_type="slides_batch_regeneration",
        status=status,
        updated_at=updated_at or datetime.now(),
        metadata=metadata or {"project_id": "project-1", "user_id": 7},
    )


@pytest.mark.asyncio
async def test_find_active_task_async_ignores_local_task_completed_in_cache(monkeypatch):
    from landppt.services.background_tasks import BackgroundTaskManager, TaskStatus

    manager = BackgroundTaskManager()
    local_task = _task(
        "task-1",
        TaskStatus.RUNNING,
        updated_at=datetime.now() - timedelta(seconds=10),
    )
    cached_task = _task(
        "task-1",
        TaskStatus.COMPLETED,
        updated_at=datetime.now(),
    )
    manager.tasks[local_task.task_id] = local_task

    removed = []

    async def fake_get_task_from_cache(task_id):
        assert task_id == "task-1"
        return cached_task

    async def fake_remove_from_active_index(task_id):
        removed.append(task_id)

    monkeypatch.setattr(manager, "_get_task_from_cache", fake_get_task_from_cache)
    monkeypatch.setattr(manager, "_get_task_from_db", AsyncMock(return_value=None))
    monkeypatch.setattr(manager, "_remove_from_active_index", fake_remove_from_active_index)
    monkeypatch.setattr(manager, "_get_active_tasks_from_cache", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "landppt.services.task_store.get_task_store",
        lambda: SimpleNamespace(find_active_task=AsyncMock(return_value=None)),
    )

    result = await manager.find_active_task_async(
        "slides_batch_regeneration",
        metadata_filter={"project_id": "project-1", "user_id": 7},
    )

    assert result is None
    assert manager.tasks["task-1"].status == TaskStatus.COMPLETED
    assert removed == ["task-1"]


@pytest.mark.asyncio
async def test_find_active_task_async_returns_refreshed_active_task(monkeypatch):
    from landppt.services.background_tasks import BackgroundTaskManager, TaskStatus

    manager = BackgroundTaskManager()
    local_task = _task(
        "task-1",
        TaskStatus.RUNNING,
        updated_at=datetime.now() - timedelta(seconds=10),
    )
    cached_task = _task(
        "task-1",
        TaskStatus.RUNNING,
        updated_at=datetime.now(),
    )
    manager.tasks[local_task.task_id] = local_task

    async def fake_get_task_from_cache(task_id):
        assert task_id == "task-1"
        return cached_task

    monkeypatch.setattr(manager, "_get_task_from_cache", fake_get_task_from_cache)
    monkeypatch.setattr(
        manager,
        "_get_task_from_db",
        AsyncMock(return_value=_task("task-1", TaskStatus.PENDING, updated_at=local_task.updated_at)),
    )

    result = await manager.find_active_task_async(
        "slides_batch_regeneration",
        metadata_filter={"project_id": "project-1", "user_id": 7},
    )

    assert result is cached_task
    assert manager.tasks["task-1"] is cached_task


@pytest.mark.asyncio
async def test_get_task_async_falls_back_to_persistent_store(monkeypatch):
    from landppt.services.background_tasks import BackgroundTaskManager, TaskStatus

    manager = BackgroundTaskManager()
    persisted_task = _task(
        "task-1",
        TaskStatus.COMPLETED,
        updated_at=datetime.now(),
    )

    async def fake_get_task_from_cache(task_id):
        assert task_id == "task-1"
        return None

    async def fake_get_task_from_db(task_id):
        assert task_id == "task-1"
        return persisted_task

    monkeypatch.setattr(manager, "_get_task_from_cache", fake_get_task_from_cache)
    monkeypatch.setattr(manager, "_get_task_from_db", fake_get_task_from_db)
    save_task = AsyncMock()
    monkeypatch.setattr(manager, "_save_task_to_cache", save_task)

    result = await manager.get_task_async("task-1")

    assert result is persisted_task
    assert manager.tasks["task-1"] is persisted_task
    save_task.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_clock_offset", [-10, 10])
async def test_get_task_async_keeps_database_completion_when_cache_is_pending(
    monkeypatch, cache_clock_offset
):
    from landppt.services.background_tasks import BackgroundTaskManager, TaskStatus

    manager = BackgroundTaskManager()
    completed = _task("task-1", TaskStatus.COMPLETED)
    completed.result = {"artifact_id": "export-1"}
    pending = _task(
        "task-1",
        TaskStatus.PENDING,
        updated_at=completed.updated_at + timedelta(seconds=cache_clock_offset),
    )
    manager.tasks[pending.task_id] = pending

    monkeypatch.setattr(manager, "_get_task_from_cache", AsyncMock(return_value=pending))
    monkeypatch.setattr(manager, "_get_task_from_db", AsyncMock(return_value=completed))
    save_task = AsyncMock()
    monkeypatch.setattr(manager, "_save_task_to_cache", save_task)

    assert await manager.get_task_async("task-1") is completed
    assert manager.tasks["task-1"] is completed
    save_task.assert_not_called()


@pytest.mark.asyncio
async def test_find_active_task_async_removes_cached_reference_to_completed_task(monkeypatch):
    from landppt.services.background_tasks import BackgroundTaskManager, TaskStatus

    manager = BackgroundTaskManager()
    completed = _task("task-1", TaskStatus.COMPLETED)
    pending = _task("task-1", TaskStatus.PENDING)
    client = SimpleNamespace(
        hgetall=AsyncMock(return_value={"task-1": json.dumps({"task_id": "task-1"})}),
        hdel=AsyncMock(),
    )
    manager._cache_service = SimpleNamespace(is_connected=True, _client=client)
    monkeypatch.setattr(manager, "_get_task_from_cache", AsyncMock(return_value=pending))
    monkeypatch.setattr(manager, "_get_task_from_db", AsyncMock(return_value=completed))
    monkeypatch.setattr(
        "landppt.services.task_store.get_task_store",
        lambda: SimpleNamespace(find_active_task=AsyncMock(return_value=None)),
    )
    save_task = AsyncMock()
    monkeypatch.setattr(manager, "_save_task_to_cache", save_task)

    assert await manager.find_active_task_async(completed.task_type, completed.metadata) is None
    client.hdel.assert_awaited_once_with(f"bg_active_tasks:{completed.task_type}", "task-1")
    save_task.assert_not_called()
