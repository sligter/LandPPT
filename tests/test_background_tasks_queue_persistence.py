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


@pytest.mark.asyncio
async def test_terminal_task_removes_from_active_index_even_when_cache_write_fails(monkeypatch):
    """When Valkey SET fails but DB succeeds, the task is still durably persisted
    so it can be returned; however, for terminal states the active index MUST be
    cleaned regardless of the SET outcome (otherwise a stale entry causes 409)."""
    from landppt.services.background_tasks import BackgroundTaskManager, TaskStatus, BackgroundTask

    manager = BackgroundTaskManager()
    manager._cache_service = _FakeCache(set_ok=False)

    monkeypatch.setattr(
        "landppt.services.task_store.get_task_store",
        lambda: _OkTaskStore(),
    )

    removed_ids = []

    async def spy_remove(task_id):
        removed_ids.append(task_id)

    monkeypatch.setattr(manager, "_remove_from_active_index", spy_remove)

    # Simulate updating a task to a terminal state.
    task = BackgroundTask(task_id="t-terminal", task_type="pdf_generation")
    task.status = TaskStatus.COMPLETED
    manager.tasks["t-terminal"] = task

    result = await manager._save_task_to_cache(task)

    # DB write succeeded, so overall durable write is True.
    assert result is True
    # Critical: _remove_from_active_index was called despite cache_written=False.
    assert "t-terminal" in removed_ids


@pytest.mark.asyncio
async def test_pending_task_added_to_active_index_even_when_cache_write_fails(monkeypatch):
    """Symmetrically, a PENDING/RUNNING task should still be added to the active
    index even when the task metadata SET to Valkey failed (index uses separate
    Valkey commands hset/expire)."""
    from landppt.services.background_tasks import BackgroundTaskManager, TaskStatus, BackgroundTask

    manager = BackgroundTaskManager()
    manager._cache_service = _FakeCache(set_ok=False)

    monkeypatch.setattr(
        "landppt.services.task_store.get_task_store",
        lambda: _OkTaskStore(),
    )

    added_tasks = []

    async def spy_add(task):
        added_tasks.append(task.task_id)

    monkeypatch.setattr(manager, "_add_to_active_index", spy_add)

    task = BackgroundTask(task_id="t-pending", task_type="pdf_generation")
    task.status = TaskStatus.PENDING
    manager.tasks["t-pending"] = task

    result = await manager._save_task_to_cache(task)

    assert result is True
    assert "t-pending" in added_tasks
