"""Persistent storage for background task state."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..database.database import AsyncSessionLocal
from ..database.models import AsyncTask

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"pending", "running"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _datetime_to_timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return float(value or 0)
    except Exception:
        return datetime.now().timestamp()


def _timestamp_to_datetime(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(float(value))
    except Exception:
        return datetime.now()


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


class TaskStore:
    """PostgreSQL/SQLite backed task state store."""

    async def save_task(self, task) -> bool:
        """Persist a task row.

        Returns True when the row was committed successfully, False when any
        step failed. Callers that must gate enqueueing on durability rely on this
        return value instead of the swallowed exception.
        """
        payload = task.to_dict()
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        status = str(payload.get("status") or "pending")
        now_ts = _datetime_to_timestamp(payload.get("updated_at"))
        created_ts = _datetime_to_timestamp(payload.get("created_at"))

        try:
            async with AsyncSessionLocal() as session:
                task_id = str(payload["task_id"])
                existing = await session.get(AsyncTask, task_id)
                if existing is None:
                    existing = AsyncTask(
                        id=task_id,
                        task_type=str(payload.get("task_type") or "unknown"),
                        status=status,
                        created_at=created_ts,
                        updated_at=now_ts,
                    )
                    session.add(existing)
                    try:
                        await session.flush()
                    except IntegrityError:
                        await session.rollback()
                        existing = await session.get(AsyncTask, task_id)
                        if existing is None:
                            raise

                existing.task_type = str(payload.get("task_type") or existing.task_type or "unknown")
                existing.status = status
                existing.user_id = _coerce_int(metadata.get("user_id"))
                existing.project_id = str(metadata.get("project_id")) if metadata.get("project_id") else None
                existing.progress = float(payload.get("progress") or 0.0)
                existing.input_data = metadata
                existing.result = payload.get("result")
                existing.error = payload.get("error")
                existing.updated_at = now_ts
                if status == "running" and existing.started_at is None:
                    existing.started_at = now_ts
                if status in TERMINAL_STATUSES and existing.finished_at is None:
                    existing.finished_at = now_ts
                await session.commit()
            return True
        except Exception as exc:
            logger.warning("Failed to persist task state to database: %s", exc)
            return False

    async def get_task(self, task_id: str):
        try:
            async with AsyncSessionLocal() as session:
                row = await session.get(AsyncTask, str(task_id))
                return self._row_to_background_task(row) if row else None
        except Exception as exc:
            logger.debug("Failed to load task state from database: %s", exc)
            return None

    async def find_active_task(self, task_type: str, metadata_filter: Optional[Dict[str, Any]] = None):
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AsyncTask)
                    .where(AsyncTask.task_type == task_type)
                    .where(AsyncTask.status.in_(ACTIVE_STATUSES))
                    .order_by(AsyncTask.updated_at.desc())
                    .limit(50)
                )
                for row in result.scalars():
                    task = self._row_to_background_task(row)
                    if task and self._metadata_matches(task.metadata, metadata_filter):
                        return task
        except Exception as exc:
            logger.debug("Failed to find active task in database: %s", exc)
        return None

    @staticmethod
    def _metadata_matches(metadata: Dict[str, Any], metadata_filter: Optional[Dict[str, Any]]) -> bool:
        if not metadata_filter:
            return True
        return all(metadata.get(key) == value for key, value in metadata_filter.items())

    @staticmethod
    def _row_to_background_task(row: AsyncTask | None):
        if row is None:
            return None
        from .background_tasks import BackgroundTask, TaskStatus

        status_value = str(row.status or "pending")
        try:
            status = TaskStatus(status_value)
        except ValueError:
            status = TaskStatus.PENDING
        return BackgroundTask(
            task_id=row.id,
            task_type=row.task_type,
            status=status,
            progress=float(row.progress or 0.0),
            result=row.result,
            error=row.error,
            created_at=_timestamp_to_datetime(row.created_at),
            updated_at=_timestamp_to_datetime(row.updated_at),
            metadata=row.input_data or {},
        )


_task_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    global _task_store
    if _task_store is None:
        _task_store = TaskStore()
    return _task_store
