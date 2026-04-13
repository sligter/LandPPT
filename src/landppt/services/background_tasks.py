"""
后台任务管理器
用于处理耗时的异步任务，如PDF转PPTX转换
支持Valkey存储以实现多worker进程间的任务共享
"""

import asyncio
import logging
import uuid
import json
import os
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
import traceback

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """后台任务"""
    task_id: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackgroundTask":
        """Create from dictionary"""
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = TaskStatus(status)
        
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()
            
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now()
        
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            status=status,
            progress=data.get("progress", 0.0),
            result=data.get("result"),
            error=data.get("error"),
            created_at=created_at,
            updated_at=updated_at,
            metadata=data.get("metadata", {})
        )


class BackgroundTaskManager:
    """后台任务管理器 - 支持Valkey存储"""
    
    TASK_TTL = 86400  # 24 hours in seconds

    def __init__(self):
        self.tasks: Dict[str, BackgroundTask] = {}  # Local cache
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self._cache_service = None
        self.stale_active_task_seconds = self._parse_int_env("BG_TASK_STALE_SECONDS", 3600)
        self.heartbeat_seconds = self._parse_int_env("BG_TASK_HEARTBEAT_SECONDS", 30)

    @staticmethod
    def _parse_int_env(name: str, default: int) -> int:
        try:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            return max(1, int(raw))
        except Exception:
            return default

    def _is_task_stale(self, task: BackgroundTask) -> bool:
        cutoff = datetime.now() - timedelta(seconds=self.stale_active_task_seconds)
        try:
            return task.updated_at < cutoff
        except Exception:
            return False

    async def _touch_task(self, task_id: str):
        """Heartbeat: update task.updated_at to keep distributed liveness."""
        task = self.tasks.get(task_id)
        if task is None:
            task = await self._get_task_from_cache(task_id)
            if task is None:
                return

        if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
            return

        task.updated_at = datetime.now()
        await self._save_task_to_cache(task)

    async def _heartbeat(self, task_id: str):
        """Periodic heartbeat for RUNNING tasks, prevents stale locks in Valkey."""
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            await self._touch_task(task_id)
    
    async def _get_cache(self):
        """Get cache service lazily"""
        if self._cache_service is None:
            try:
                from .cache_service import get_cache_service
                self._cache_service = await get_cache_service()
            except Exception as e:
                logger.warning(f"Failed to get cache service: {e}")
                self._cache_service = None
        return self._cache_service
    
    async def _save_task_to_cache(self, task: BackgroundTask):
        """Save task to Valkey cache"""
        cache = await self._get_cache()
        if cache and cache.is_connected:
            try:
                key = f"bg_task:{task.task_id}"
                value = json.dumps(task.to_dict())
                await cache.set(key, value, self.TASK_TTL)
                logger.debug(f"Task saved to cache: {task.task_id}")
                
                # Also add to active tasks index if task is active
                if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                    await self._add_to_active_index(task)
                else:
                    await self._remove_from_active_index(task.task_id)
            except Exception as e:
                logger.warning(f"Failed to save task to cache: {e}")
    
    async def _add_to_active_index(self, task: BackgroundTask):
        """Add task to active tasks index in Valkey (for multi-worker lookup)"""
        cache = await self._get_cache()
        if cache and cache.is_connected:
            try:
                # Store active task reference with metadata for filtering
                index_key = f"bg_active_tasks:{task.task_type}"
                task_ref = json.dumps({
                    "task_id": task.task_id,
                    "metadata": task.metadata,
                    "created_at": task.created_at.isoformat() if isinstance(task.created_at, datetime) else task.created_at
                })
                # Use hash to store multiple active tasks per type
                await cache._client.hset(index_key, task.task_id, task_ref)
                await cache._client.expire(index_key, self.TASK_TTL)
            except Exception as e:
                logger.warning(f"Failed to add task to active index: {e}")
    
    async def _remove_from_active_index(self, task_id: str):
        """Remove task from all active task indexes"""
        cache = await self._get_cache()
        if cache and cache.is_connected:
            try:
                # We need to scan all task type indexes - check known types
                # NOTE: Keep this list updated when new task types are added.
                task_types = [
                    "pdf_to_pptx_conversion",
                    "pdf_generation",
                    "html_to_pptx_screenshot",
                    "slide_regeneration",
                    "slides_batch_regeneration",
                    "narration_generation",
                    "narration_audio_export",
                    "narration_video_export",
                ]
                for task_type in task_types:
                    index_key = f"bg_active_tasks:{task_type}"
                    await cache._client.hdel(index_key, task_id)
            except Exception as e:
                logger.warning(f"Failed to remove task from active index: {e}")
    
    async def _get_active_tasks_from_cache(self, task_type: str) -> list:
        """Get all active tasks of a type from Valkey"""
        cache = await self._get_cache()
        if cache and cache.is_connected:
            try:
                index_key = f"bg_active_tasks:{task_type}"
                all_refs = await cache._client.hgetall(index_key)
                tasks = []
                for task_id, task_ref in all_refs.items():
                    try:
                        ref_data = json.loads(task_ref)
                        # Verify task is still active by checking its actual status
                        ref_task_id = ref_data.get("task_id")
                        if not ref_task_id:
                            await cache._client.hdel(index_key, task_id)
                            continue

                        task = await self._get_task_from_cache(ref_task_id)
                        if not task:
                            await cache._client.hdel(index_key, task_id)
                            continue

                        if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                            # Release stale task locks (e.g., worker crashed or scaled down).
                            if self._is_task_stale(task):
                                task.status = TaskStatus.FAILED
                                task.error = "stale_active_task_released"
                                task.updated_at = datetime.now()
                                await self._save_task_to_cache(task)
                                await cache._client.hdel(index_key, task_id)
                                continue

                            tasks.append(task)
                        else:
                            await cache._client.hdel(index_key, task_id)
                    except Exception:
                        continue
                return tasks
            except Exception as e:
                logger.warning(f"Failed to get active tasks from cache: {e}")
        return []
    
    async def _get_task_from_cache(self, task_id: str) -> Optional[BackgroundTask]:
        """Get task from Valkey cache"""
        cache = await self._get_cache()
        if cache and cache.is_connected:
            try:
                key = f"bg_task:{task_id}"
                value = await cache.get(key)
                if value:
                    data = json.loads(value)
                    return BackgroundTask.from_dict(data)
            except Exception as e:
                logger.warning(f"Failed to get task from cache: {e}")
        return None

    def create_task(self, task_type: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """创建新任务

        Args:
            task_type: 任务类型
            metadata: 任务元数据

        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        task = BackgroundTask(
            task_id=task_id,
            task_type=task_type,
            metadata=metadata or {}
        )
        self.tasks[task_id] = task
        
        # Save to cache asynchronously (fire and forget in sync context)
        asyncio.create_task(self._save_task_to_cache(task))
        
        logger.info(f"创建后台任务: {task_id} (类型: {task_type})")
        return task_id

    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
        """获取任务信息 (同步版本，优先从本地缓存获取)"""
        return self.tasks.get(task_id)
    
    async def get_task_async(self, task_id: str) -> Optional[BackgroundTask]:
        """获取任务信息 (异步版本，从Valkey获取)"""
        # In multi-worker setups, local memory is not shared and can become stale.
        # Prefer Valkey when available, but return the newest version across both.
        cached = await self._get_task_from_cache(task_id)
        local = self.tasks.get(task_id)

        if cached is None:
            return local
        if local is None:
            self.tasks[task_id] = cached
            return cached

        # Both exist: return newer one (by updated_at).
        try:
            cached_ts = cached.updated_at.timestamp() if isinstance(cached.updated_at, datetime) else float(cached.updated_at or 0)
        except Exception:
            cached_ts = 0.0
        try:
            local_ts = local.updated_at.timestamp() if isinstance(local.updated_at, datetime) else float(local.updated_at or 0)
        except Exception:
            local_ts = 0.0

        if cached_ts >= local_ts:
            self.tasks[task_id] = cached
            return cached

        # Local is newer; ensure Valkey is updated (best-effort).
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_task_to_cache(local))
        except RuntimeError:
            pass
        return local

    def _apply_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress: Optional[float] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> Optional[BackgroundTask]:
        if task_id not in self.tasks:
            logger.warning(f"任务不存在: {task_id}")
            return None

        task = self.tasks[task_id]
        task.status = status
        task.updated_at = datetime.now()

        if progress is not None:
            task.progress = progress
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error

        logger.info(f"任务状态更新: {task_id} -> {status} (进度: {task.progress}%)")
        return task

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress: Optional[float] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None
    ):
        """更新任务状态"""
        task = self._apply_task_status(task_id, status, progress=progress, result=result, error=error)
        if task is None:
            return

        # Save to cache asynchronously
        asyncio.create_task(self._save_task_to_cache(task))

    async def update_task_status_async(
        self,
        task_id: str,
        status: TaskStatus,
        progress: Optional[float] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ):
        """异步更新任务状态，并等待缓存与活跃索引完成同步。"""
        task = self._apply_task_status(task_id, status, progress=progress, result=result, error=error)
        if task is None:
            return
        await self._save_task_to_cache(task)

    async def execute_task(
        self,
        task_id: str,
        func: Callable,
        *args,
        **kwargs
    ):
        """执行任务

        Args:
            task_id: 任务ID
            func: 要执行的函数（可以是同步或异步）
            *args: 函数参数
            **kwargs: 函数关键字参数
        """
        heartbeat_task: Optional[asyncio.Task] = None
        try:
            await self.update_task_status_async(task_id, TaskStatus.RUNNING, progress=0.0)
            heartbeat_task = asyncio.create_task(self._heartbeat(task_id))

            # 检查函数是否是协程
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                # 同步函数，在线程池中执行
                from ..utils.thread_pool import run_blocking_io
                result = await run_blocking_io(func, *args, **kwargs)

            # If the task returns a structured result with `success: false`, treat it as FAILED.
            # This avoids "completed but not downloadable" states for export tasks.
            if isinstance(result, dict) and result.get("success") is False:
                err = result.get("error") or result.get("message") or "Task reported success=false"
                await self.update_task_status_async(
                    task_id,
                    TaskStatus.FAILED,
                    progress=100.0,
                    result=result,
                    error=str(err),
                )
            else:
                await self.update_task_status_async(
                    task_id,
                    TaskStatus.COMPLETED,
                    progress=100.0,
                    result=result
                )

        except asyncio.CancelledError:
            await self.update_task_status_async(
                task_id,
                TaskStatus.CANCELLED,
                error="任务被取消"
            )
            logger.info(f"任务被取消: {task_id}")

        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            await self.update_task_status_async(
                task_id,
                TaskStatus.FAILED,
                error=error_msg
            )
            logger.error(f"任务执行失败: {task_id}\n{error_msg}")

        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # 清理运行中的任务引用
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]

    def submit_task(
        self,
        task_type: str,
        func: Callable,
        *args,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """提交任务到后台执行

        Args:
            task_type: 任务类型
            func: 要执行的函数
            *args: 函数参数
            metadata: 任务元数据
            **kwargs: 函数关键字参数

        Returns:
            任务ID
        """
        # 创建任务
        task_id = self.create_task(task_type, metadata)

        # 创建异步任务并开始执行
        async_task = asyncio.create_task(
            self.execute_task(task_id, func, *args, **kwargs)
        )
        self.running_tasks[task_id] = async_task

        logger.info(f"提交后台任务: {task_id}")
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """取消任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功取消
        """
        if task_id in self.running_tasks:
            self.running_tasks[task_id].cancel()
            logger.info(f"取消任务: {task_id}")
            return True
        return False

    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务

        Args:
            max_age_hours: 任务保留时间（小时）
        """
        from datetime import timedelta
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        tasks_to_remove = [
            task_id for task_id, task in self.tasks.items()
            if task.updated_at < cutoff_time and task.status in [
                TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
            ]
        ]

        for task_id in tasks_to_remove:
            del self.tasks[task_id]

        if tasks_to_remove:
            logger.info(f"清理了 {len(tasks_to_remove)} 个过期任务")

    def find_active_task(self, task_type: str, metadata_filter: Optional[Dict[str, Any]] = None) -> Optional[BackgroundTask]:
        """查找指定类型的活跃任务（同步版本，仅检查本地缓存）
        
        注意：在多worker环境下，请使用 find_active_task_async 方法
        
        Args:
            task_type: 任务类型
            metadata_filter: 元数据过滤条件（如 {"project_id": "xxx"}）
            
        Returns:
            找到的活跃任务，如果没有则返回 None
        """
        for task in self.tasks.values():
            # 只检查活跃任务（pending 或 running）
            if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                continue
            
            # 检查任务类型匹配
            if task.task_type != task_type:
                continue
            
            # 检查元数据过滤条件
            if metadata_filter:
                match = True
                for key, value in metadata_filter.items():
                    if task.metadata.get(key) != value:
                        match = False
                        break
                if not match:
                    continue
            
            return task
        
        return None
    
    async def find_active_task_async(self, task_type: str, metadata_filter: Optional[Dict[str, Any]] = None) -> Optional[BackgroundTask]:
        """查找指定类型的活跃任务（异步版本，检查本地缓存和Valkey）
        
        在多worker环境下推荐使用此方法
        
        Args:
            task_type: 任务类型
            metadata_filter: 元数据过滤条件（如 {"project_id": "xxx"}）
            
        Returns:
            找到的活跃任务，如果没有则返回 None
        """
        # First check local cache
        local_task = self.find_active_task(task_type, metadata_filter)
        if local_task:
            return local_task
        
        # Then check Valkey for tasks from other workers
        try:
            cached_tasks = await self._get_active_tasks_from_cache(task_type)
            for task in cached_tasks:
                # 检查任务类型匹配（应该已经匹配，但double-check）
                if task.task_type != task_type:
                    continue
                
                # 检查元数据过滤条件
                if metadata_filter:
                    match = True
                    for key, value in metadata_filter.items():
                        if task.metadata.get(key) != value:
                            match = False
                            break
                    if not match:
                        continue
                
                # Found matching active task in Valkey
                logger.info(f"Found active task in Valkey from another worker: {task.task_id}")
                return task
        except Exception as e:
            logger.warning(f"Failed to check Valkey for active tasks: {e}")
        
        return None

    def get_task_stats(self) -> Dict[str, int]:
        """获取任务统计信息"""
        stats = {
            "total": len(self.tasks),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0
        }

        for task in self.tasks.values():
            stats[task.status.value] += 1

        return stats


# 全局任务管理器实例
_task_manager = None

def get_task_manager() -> BackgroundTaskManager:
    """获取全局任务管理器实例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = BackgroundTaskManager()
    return _task_manager
