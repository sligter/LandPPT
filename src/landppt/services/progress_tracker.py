"""
Progress Tracker for Speech Script Generation
"""

import asyncio
import json
import logging
import time
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ProgressInfo:
    """Progress information for speech script generation"""
    task_id: str
    project_id: str
    total_slides: int
    completed_slides: int
    failed_slides: int
    skipped_slides: int
    current_slide: Optional[int] = None
    current_slide_title: Optional[str] = None
    status: str = "running"  # running, completed, failed
    message: str = ""
    start_time: float = 0
    last_update: float = 0
    error_details: list = None
    
    def __post_init__(self):
        if self.start_time == 0:
            self.start_time = time.time()
        if self.last_update == 0:
            self.last_update = time.time()
        if self.error_details is None:
            self.error_details = []

    def to_persist_dict(self) -> Dict[str, Any]:
        """Convert to dictionary suitable for persistence (no computed fields)."""
        return asdict(self)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Add computed properties
        data['processed_slides'] = self.processed_slides
        data['progress_percentage'] = self.progress_percentage
        data['elapsed_time'] = self.elapsed_time
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProgressInfo":
        """Create ProgressInfo from dict (ignores unknown/computed fields)."""
        required_fields = [
            "task_id",
            "project_id",
            "total_slides",
            "completed_slides",
            "failed_slides",
            "skipped_slides",
        ]
        missing = [k for k in required_fields if k not in data]
        if missing:
            raise ValueError(f"Missing progress fields: {missing}")

        field_names = set(cls.__dataclass_fields__.keys())
        init_kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in field_names}
        return cls(**init_kwargs)
    
    @property
    def processed_slides(self) -> int:
        """Get total processed slides including success/failure/skip."""
        processed = self.completed_slides + self.failed_slides + self.skipped_slides
        if self.total_slides <= 0:
            return 0
        return min(processed, self.total_slides)

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage"""
        if self.total_slides == 0:
            return 0
        return (self.processed_slides / self.total_slides) * 100
    
    @property
    def elapsed_time(self) -> float:
        """Get elapsed time in seconds"""
        return time.time() - self.start_time


class ProgressTracker:
    """Progress tracker for speech script generation (supports Valkey for multi-worker deployments)."""

    TASK_TTL = 86400  # 24 hours
    KEY_PREFIX = "speech_script_progress:"
    
    def __init__(self):
        self._progress_data: Dict[str, ProgressInfo] = {}
        self._lock = threading.Lock()
        self._cache_service = None

    def _cache_key(self, task_id: str) -> str:
        return f"{self.KEY_PREFIX}{task_id}"

    async def _get_cache(self):
        """Get cache service lazily."""
        if self._cache_service is None:
            try:
                from .cache_service import get_cache_service

                self._cache_service = await get_cache_service()
            except Exception as e:
                logger.warning(f"Failed to get cache service: {e}")
                self._cache_service = None
        return self._cache_service

    async def _save_progress_to_cache(self, progress: ProgressInfo) -> None:
        cache = await self._get_cache()
        if cache and cache.is_connected:
            try:
                await cache.set(
                    self._cache_key(progress.task_id),
                    json.dumps(progress.to_persist_dict(), ensure_ascii=False),
                    self.TASK_TTL,
                )
            except Exception as e:
                logger.warning(f"Failed to save progress to cache: {e}")

    async def _get_progress_from_cache(self, task_id: str) -> Optional[ProgressInfo]:
        cache = await self._get_cache()
        if cache and cache.is_connected:
            try:
                value = await cache.get(self._cache_key(task_id))
                if value:
                    data = json.loads(value)
                    return ProgressInfo.from_dict(data)
            except Exception as e:
                logger.warning(f"Failed to get progress from cache: {e}")
        return None

    async def _delete_progress_from_cache(self, task_id: str) -> None:
        cache = await self._get_cache()
        if cache and cache.is_connected:
            try:
                await cache.delete(self._cache_key(task_id))
            except Exception as e:
                logger.warning(f"Failed to delete progress from cache: {e}")
    
    def create_task(self, task_id: str, project_id: str, total_slides: int) -> ProgressInfo:
        """Create a new progress tracking task"""
        with self._lock:
            progress = ProgressInfo(
                task_id=task_id,
                project_id=project_id,
                total_slides=total_slides,
                completed_slides=0,
                failed_slides=0,
                skipped_slides=0,
                status="running",
                message="开始生成演讲稿..."
            )
            self._progress_data[task_id] = progress

        # Best-effort cache persistence (async, non-blocking for sync callers)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_progress_to_cache(progress))
        except RuntimeError:
            pass

        return progress

    def update_progress(self, task_id: str, **kwargs) -> Optional[ProgressInfo]:
        """Update progress for a task"""
        with self._lock:
            if task_id not in self._progress_data:
                return None
            
            progress = self._progress_data[task_id]
            
            # Update fields
            for key, value in kwargs.items():
                if hasattr(progress, key):
                    setattr(progress, key, value)
            
            progress.last_update = time.time()

        # Best-effort cache persistence (async, non-blocking for sync callers)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_progress_to_cache(progress))
        except RuntimeError:
            pass

        return progress
    
    def get_progress(self, task_id: str) -> Optional[ProgressInfo]:
        """Get progress for a task"""
        with self._lock:
            return self._progress_data.get(task_id)

    async def get_progress_async(self, task_id: str) -> Optional[ProgressInfo]:
        """Get progress for a task (async, cross-worker via Valkey)."""
        # In multi-worker setups, local memory is not shared and can also become stale if
        # another worker advances the task. Prefer Valkey when available, but keep local
        # as a fallback and to serve the newest version.

        cached = await self._get_progress_from_cache(task_id)
        with self._lock:
            local = self._progress_data.get(task_id)

        if cached is None:
            return local

        if local is None:
            with self._lock:
                self._progress_data[task_id] = cached
            return cached

        # Both exist: return the newer one (by last_update).
        try:
            local_ts = float(local.last_update or 0)
        except Exception:
            local_ts = 0.0
        try:
            cached_ts = float(cached.last_update or 0)
        except Exception:
            cached_ts = 0.0

        if cached_ts >= local_ts:
            with self._lock:
                self._progress_data[task_id] = cached
            return cached

        # Local is newer; ensure Valkey is updated (best-effort).
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_progress_to_cache(local))
        except RuntimeError:
            pass
        return local

    async def create_task_async(
        self,
        task_id: str,
        project_id: str,
        total_slides: int,
        overwrite: bool = False,
    ) -> ProgressInfo:
        """Create a new progress tracking task and persist it (async)."""
        if not overwrite:
            existing = await self.get_progress_async(task_id)
            if existing:
                return existing

        with self._lock:
            progress = ProgressInfo(
                task_id=task_id,
                project_id=project_id,
                total_slides=total_slides,
                completed_slides=0,
                failed_slides=0,
                skipped_slides=0,
                status="running",
                message="开始生成演讲稿...",
            )
            self._progress_data[task_id] = progress

        await self._save_progress_to_cache(progress)
        return progress

    async def update_progress_async(self, task_id: str, **kwargs) -> Optional[ProgressInfo]:
        """Update progress for a task and persist it (async)."""
        progress = self.update_progress(task_id, **kwargs)
        if progress:
            await self._save_progress_to_cache(progress)
        return progress

    async def complete_task_async(self, task_id: str, message: str = "生成完成") -> Optional[ProgressInfo]:
        """Mark task as completed and persist it (async)."""
        progress = self.complete_task(task_id, message=message)
        if progress:
            await self._save_progress_to_cache(progress)
        return progress

    async def fail_task_async(self, task_id: str, error_message: str) -> Optional[ProgressInfo]:
        """Mark task as failed and persist it (async)."""
        progress = self.fail_task(task_id, error_message=error_message)
        if progress:
            await self._save_progress_to_cache(progress)
        return progress

    async def add_slide_completed_async(self, task_id: str, slide_index: int, slide_title: str) -> Optional[ProgressInfo]:
        """Mark a slide as completed and persist it (async)."""
        progress = self.add_slide_completed(task_id, slide_index, slide_title)
        if progress:
            await self._save_progress_to_cache(progress)
        return progress

    async def add_slide_failed_async(
        self, task_id: str, slide_index: int, slide_title: str, error: str
    ) -> Optional[ProgressInfo]:
        """Mark a slide as failed and persist it (async)."""
        progress = self.add_slide_failed(task_id, slide_index, slide_title, error)
        if progress:
            await self._save_progress_to_cache(progress)
        return progress

    async def add_slide_skipped_async(
        self, task_id: str, slide_index: int, slide_title: str, reason: str
    ) -> Optional[ProgressInfo]:
        """Mark a slide as skipped and persist it (async)."""
        progress = self.add_slide_skipped(task_id, slide_index, slide_title, reason)
        if progress:
            await self._save_progress_to_cache(progress)
        return progress
    
    def complete_task(self, task_id: str, message: str = "生成完成") -> Optional[ProgressInfo]:
        """Mark task as completed"""
        return self.update_progress(
            task_id,
            status="completed",
            message=message
        )
    
    def fail_task(self, task_id: str, error_message: str) -> Optional[ProgressInfo]:
        """Mark task as failed"""
        return self.update_progress(
            task_id,
            status="failed",
            message=f"生成失败: {error_message}"
        )
    
    def add_slide_completed(self, task_id: str, slide_index: int, slide_title: str) -> Optional[ProgressInfo]:
        """Mark a slide as completed"""
        with self._lock:
            if task_id not in self._progress_data:
                return None
            
            progress = self._progress_data[task_id]
            progress.completed_slides += 1
            progress.current_slide = slide_index
            progress.current_slide_title = slide_title
            progress.message = f"已完成第{slide_index + 1}页: {slide_title}"
            progress.last_update = time.time()
            
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_progress_to_cache(progress))
        except RuntimeError:
            pass

        return progress
    
    def add_slide_failed(self, task_id: str, slide_index: int, slide_title: str, error: str) -> Optional[ProgressInfo]:
        """Mark a slide as failed"""
        with self._lock:
            if task_id not in self._progress_data:
                return None
            
            progress = self._progress_data[task_id]
            progress.failed_slides += 1
            progress.current_slide = slide_index
            progress.current_slide_title = slide_title
            progress.message = f"第{slide_index + 1}页生成失败: {slide_title}"
            progress.error_details.append({
                'slide_index': slide_index,
                'slide_title': slide_title,
                'error': error
            })
            progress.last_update = time.time()
            
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_progress_to_cache(progress))
        except RuntimeError:
            pass

        return progress
    
    def add_slide_skipped(self, task_id: str, slide_index: int, slide_title: str, reason: str) -> Optional[ProgressInfo]:
        """Mark a slide as skipped"""
        with self._lock:
            if task_id not in self._progress_data:
                return None
            
            progress = self._progress_data[task_id]
            progress.skipped_slides += 1
            progress.current_slide = slide_index
            progress.current_slide_title = slide_title
            progress.message = f"第{slide_index + 1}页已跳过: {slide_title}"
            progress.last_update = time.time()
            
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_progress_to_cache(progress))
        except RuntimeError:
            pass

        return progress
    
    def cleanup_old_tasks(self, max_age_seconds: int = 3600):
        """Clean up old completed/failed tasks"""
        current_time = time.time()
        with self._lock:
            to_remove = []
            for task_id, progress in self._progress_data.items():
                if (progress.status in ["completed", "failed"] and 
                    current_time - progress.last_update > max_age_seconds):
                    to_remove.append(task_id)
            
            for task_id in to_remove:
                del self._progress_data[task_id]
    
    def remove_task(self, task_id: str) -> bool:
        """Remove a specific task"""
        with self._lock:
            if task_id in self._progress_data:
                del self._progress_data[task_id]
                removed = True
            else:
                removed = False

        # Best-effort cache delete (async, non-blocking for sync callers)
        if removed:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._delete_progress_from_cache(task_id))
            except RuntimeError:
                pass
        return removed


# Global progress tracker instance
progress_tracker = ProgressTracker()
