from datetime import datetime, timedelta

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
    monkeypatch.setattr(manager, "_remove_from_active_index", fake_remove_from_active_index)

    result = await manager.find_active_task_async(
        "slides_batch_regeneration",
        metadata_filter={"project_id": "project-1", "user_id": 7},
    )

    assert result is None
    assert manager.tasks["task-1"].status == TaskStatus.COMPLETED
    assert "task-1" in removed


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

    async def fake_save_task_to_cache(task):
        assert task is persisted_task

    monkeypatch.setattr(manager, "_get_task_from_cache", fake_get_task_from_cache)
    monkeypatch.setattr(manager, "_get_task_from_db", fake_get_task_from_db)
    monkeypatch.setattr(manager, "_save_task_to_cache", fake_save_task_to_cache)

    result = await manager.get_task_async("task-1")

    assert result is persisted_task
    assert manager.tasks["task-1"] is persisted_task
