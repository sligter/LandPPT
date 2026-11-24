import pytest


@pytest.mark.asyncio
async def test_dequeue_task_treats_valkey_timeout_as_empty_queue(monkeypatch):
    from valkey.exceptions import TimeoutError as ValkeyTimeoutError

    from landppt.tasks import queue

    class TimeoutClient:
        async def brpop(self, key, timeout):
            raise ValkeyTimeoutError("Timeout reading from landppt-valkey:6379")

    async def fake_connected_client():
        return TimeoutClient()

    monkeypatch.setattr(queue, "_connected_client", fake_connected_client)

    assert await queue.dequeue_task("default", timeout_seconds=1) is None


@pytest.mark.asyncio
async def test_submit_queued_task_enqueues_when_queue_mode_enabled(monkeypatch):
    from landppt.core.config import app_config
    from landppt.services.background_tasks import BackgroundTaskManager, TaskStatus

    manager = BackgroundTaskManager()
    enqueued = []

    async def fake_enqueue(task_id, task_type, queue_name=None):
        enqueued.append((task_id, task_type, queue_name))

    monkeypatch.setattr(app_config, "task_execution_mode", "queue")
    monkeypatch.setattr("landppt.tasks.queue.enqueue_task", fake_enqueue)
    monkeypatch.setattr(manager, "_save_task_to_cache", lambda task: _noop())

    task_id = await manager.submit_queued_task("pdf_generation", {"project_id": "p1"}, queue_name="export")

    assert enqueued == [(task_id, "pdf_generation", "export")]
    assert manager.tasks[task_id].status == TaskStatus.PENDING
    assert manager.running_tasks == {}


def test_worker_handlers_are_registered():
    from landppt.tasks.registry import get_handler

    assert get_handler("pdf_generation").__name__ == "export_pdf"
    assert get_handler("pdf_to_pptx_conversion").__name__ == "export_pptx"
    assert get_handler("html_to_pptx_screenshot").__name__ == "export_html_screenshot_pptx"
    assert get_handler("narration_audio_export").__name__ == "export_narration_audio"
    assert get_handler("narration_video_export").__name__ == "export_narration_video"


async def _noop():
    return True
