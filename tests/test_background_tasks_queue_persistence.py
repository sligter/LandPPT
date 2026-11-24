"""Regression tests for queue-mode task submission durability.

Guarantees the fix requested upstream: a task is only enqueued after at least
one worker-readable store (Valkey or the database) has durably accepted it. When
both writes fail, submitting must raise and the task must NOT reach the queue.
"""

import pytest


class _FakeCache:
    """Minimal stand-in for CacheService that lets us control the Valkey outcome."""

    def __init__(self, set_ok: bool):
        self._set_ok = set_ok
        self._client = None

    @property
    def is_connected(self) -> bool:
        return True

    async def set(self, key, value, ttl):
        return self._set_ok

    async def get(self, key):
        return None


class _OkTaskStore:
    async def save_task(self, task):
        return True


class _FailingTaskStore:
    async def save_task(self, task):
        raise RuntimeError("database unavailable")


@pytest.mark.asyncio
async def test_submit_queued_task_does_not_enqueue_when_all_stores_fail(monkeypatch):
    """Both Valkey write and DB write fail -> raise and never LPUSH."""
    from landppt.core.config import app_config
    from landppt.services.background_tasks import (
        BackgroundTaskManager,
        TaskPersistenceError,
    )
    from landppt.tasks import queue as queue_module

    manager = BackgroundTaskManager()
    # Valkey reports connected but its SET returns False; DB raises on save.
    manager._cache_service = _FakeCache(set_ok=False)
    monkeypatch.setattr(
        "landppt.services.task_store.get_task_store",
        lambda: _FailingTaskStore(),
    )

    async def noop_add_to_active_index(task):
        return None

    monkeypatch.setattr(manager, "_add_to_active_index", noop_add_to_active_index)
    monkeypatch.setattr(app_config, "task_execution_mode", "queue")

    enqueued = []

    async def fake_enqueue_task(task_id, task_type, queue_name=None):
        enqueued.append(task_id)

    monkeypatch.setattr(queue_module, "enqueue_task", fake_enqueue_task)

    with pytest.raises(TaskPersistenceError):
        await manager.submit_queued_task("pdf_generation", metadata={"project_id": "p1"})

    # Nothing must reach the queue, and no dangling local task should remain.
    assert enqueued == []
    assert manager.tasks == {}


@pytest.mark.asyncio
async def test_submit_queued_task_enqueues_after_cache_write_succeeds(monkeypatch):
    """Valkey write succeeds -> task is returned and enqueued exactly once."""
    from landppt.core.config import app_config
    from landppt.services.background_tasks import BackgroundTaskManager
    from landppt.tasks import queue as queue_module

    manager = BackgroundTaskManager()
    manager._cache_service = _FakeCache(set_ok=True)
    monkeypatch.setattr(
        "landppt.services.task_store.get_task_store",
        lambda: _OkTaskStore(),
    )

    async def noop_add_to_active_index(task):
        return None

    monkeypatch.setattr(manager, "_add_to_active_index", noop_add_to_active_index)
    monkeypatch.setattr(app_config, "task_execution_mode", "queue")

    enqueued = []

    async def fake_enqueue_task(task_id, task_type, queue_name=None):
        enqueued.append(task_id)

    monkeypatch.setattr(queue_module, "enqueue_task", fake_enqueue_task)

    task_id = await manager.submit_queued_task("pdf_generation", metadata={"project_id": "p1"})

    assert task_id
    assert enqueued == [task_id]


@pytest.mark.asyncio
async def test_submit_queued_task_enqueues_when_only_db_write_succeeds(monkeypatch):
    """Valkey write fails but DB succeeds -> still durable for the worker, so enqueue."""
    from landppt.core.config import app_config
    from landppt.services.background_tasks import BackgroundTaskManager
    from landppt.tasks import queue as queue_module

    manager = BackgroundTaskManager()
    # Valkey SET fails, but the database write succeeds.
    manager._cache_service = _FakeCache(set_ok=False)
    monkeypatch.setattr(
        "landppt.services.task_store.get_task_store",
        lambda: _OkTaskStore(),
    )

    monkeypatch.setattr(app_config, "task_execution_mode", "queue")

    enqueued = []

    async def fake_enqueue_task(task_id, task_type, queue_name=None):
        enqueued.append(task_id)

    monkeypatch.setattr(queue_module, "enqueue_task", fake_enqueue_task)

    task_id = await manager.submit_queued_task("pdf_to_pptx_conversion", metadata={"project_id": "p1"})

    assert task_id
    assert enqueued == [task_id]
