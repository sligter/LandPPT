import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...api.models import (
    PPTGenerationRequest,
    PPTOutline,
    EnhancedPPTOutline,
    SlideContent,
    PPTProject,
    TodoBoard,
    FileOutlineGenerationResponse,
)
from ...ai import get_ai_provider, get_role_provider, AIMessage, MessageRole
from ...ai.base import TextContent, ImageContent
from ...core.config import ai_config, app_config
from ..runtime.ai_execution import ExecutionContext
from ..prompts import prompts_manager
from ..research.enhanced_research_service import EnhancedResearchService
from ..research.enhanced_report_generator import EnhancedReportGenerator
from ..pyppeteer_pdf_converter import get_pdf_converter
from ..image.image_service import ImageService
from ..image.adapters.ppt_prompt_adapter import PPTSlideContext
from ...utils.thread_pool import run_blocking_io, to_thread


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .slide_authoring_service import SlideAuthoringService


class SlideStreamingService:
    """Slide streaming and lifecycle orchestration extracted from SlideAuthoringService."""

    def __init__(self, service: "SlideAuthoringService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _execute_ppt_creation(self, project_id: str, confirmed_requirements: Dict[str, Any], system_prompt: str) -> str:
            """Execute PPT creation by generating HTML pages individually with streaming"""
            try:
                project = await self.project_manager.get_project(project_id)
                if not project or not project.outline:
                    return "❌ 错误：未找到PPT大纲，请先完成大纲生成步骤"

                outline = project.outline
                slides = outline.get('slides', [])

                if not slides:
                    return "❌ 错误：大纲中没有幻灯片信息"

                # 验证大纲页数与需求一致性
                if project.confirmed_requirements:
                    page_count_settings = project.confirmed_requirements.get('page_count_settings', {})
                    if page_count_settings.get('mode') == 'custom_range':
                        min_pages = page_count_settings.get('min_pages', 8)
                        max_pages = page_count_settings.get('max_pages', 15)
                        actual_pages = len(slides)

                        if actual_pages < min_pages or actual_pages > max_pages:
                            logger.warning(f"Outline has {actual_pages} pages, but requirements specify {min_pages}-{max_pages} pages")
                            return f"⚠️ 错误：大纲有{actual_pages}页，但需求要求{min_pages}-{max_pages}页。请重新生成大纲以符合页数要求。"

                # Initialize slides data - 确保与大纲页数完全一致
                project.slides_data = []
                project.updated_at = time.time()

                # 确保confirmed_requirements包含项目ID，用于模板选择
                if confirmed_requirements:
                    confirmed_requirements['project_id'] = project_id

                # 验证slides数据结构
                if not slides or len(slides) == 0:
                    return "❌ 错误：大纲中没有有效的幻灯片数据"

                logger.info(f"Starting PPT generation for {len(slides)} slides based on outline")

                # 确保每个slide都有必要的字段
                for i, slide in enumerate(slides):
                    if not slide.get('title'):
                        slide['title'] = f"幻灯片 {i+1}"
                    if not slide.get('page_number'):
                        slide['page_number'] = i + 1

                return f"🚀 开始PPT制作...\n\n将严格按照大纲为 {len(slides)} 页幻灯片逐页生成HTML内容\n大纲页数：{len(slides)}页\n请在编辑器中查看实时生成过程"

            except Exception as e:
                logger.error(f"Error in PPT creation: {e}")
                raise

    def _slides_generation_cancel_key(self, project_id: str) -> str:
            return f"ppt_generation_cancel:{project_id}"

    async def request_cancel_slides_generation(self, project_id: str) -> bool:
            """Request cancellation for an in-progress slide generation (cooperative best-effort)."""
            self._slides_generation_cancel_flags[project_id] = True
            try:
                from ..cache_service import get_cache_service
                cache = await get_cache_service()
                if cache and cache.is_connected:
                    await cache.set(self._slides_generation_cancel_key(project_id), "1", ttl=3600)
            except Exception as e:
                logger.warning(f"Failed to set distributed cancel flag for {project_id}: {e}")
            return True

    async def clear_cancel_slides_generation(self, project_id: str) -> bool:
            """Clear the cancellation flag so a paused generation can resume."""
            self._slides_generation_cancel_flags[project_id] = False
            try:
                from ..cache_service import get_cache_service
                cache = await get_cache_service()
                if cache and cache.is_connected:
                    await cache.delete(self._slides_generation_cancel_key(project_id))
            except Exception as e:
                logger.warning(f"Failed to clear cancel flag for {project_id}: {e}")
            return True

    async def _is_slides_generation_cancelled(self, project_id: str, cache=None) -> bool:
            if self._slides_generation_cancel_flags.get(project_id, False):
                return True
            try:
                if cache is None:
                    from ..cache_service import get_cache_service
                    cache = await get_cache_service()
                if cache and cache.is_connected:
                    return bool(await cache.get(self._slides_generation_cancel_key(project_id)))
            except Exception:
                return self._slides_generation_cancel_flags.get(project_id, False)
            return False

    async def _renew_valkey_lock(self, cache, lock_key: str, ttl: int):
            """Best-effort: refresh Valkey lock TTL while generation is running."""
            refresh_every = max(5, ttl // 3)
            while True:
                await asyncio.sleep(refresh_every)
                try:
                    await cache._client.expire(lock_key, ttl)
                except Exception:
                    pass

    async def _try_acquire_slides_generation_lock(self, project_id: str) -> dict:
            """Try to acquire a cross-worker lock; fall back to DB advisory lock, then local lock."""
            import hashlib

            lock_ttl = 600  # seconds
            lock_key = f"ppt_generation_lock:{project_id}"

            # Preferred: Valkey (Redis-compatible)
            try:
                from ..cache_service import get_cache_service
                cache = await get_cache_service()
                if cache and cache.is_connected:
                    acquired = await cache._client.set(lock_key, "locked", ex=lock_ttl, nx=True)
                    return {
                        "acquired": bool(acquired),
                        "kind": "valkey",
                        "cache": cache,
                        "lock_key": lock_key,
                        "lock_ttl": lock_ttl,
                    }
            except Exception as e:
                logger.warning(f"Valkey lock acquisition failed, falling back: {e}")

            # Fallback: PostgreSQL advisory lock (when cache is unavailable)
            try:
                from ...core.config import app_config
                if str(app_config.database_url).startswith(("postgresql://", "postgres://")):
                    from sqlalchemy import text
                    from ...database.database import async_engine

                    raw = hashlib.blake2b(project_id.encode("utf-8"), digest_size=8).digest()
                    key = int.from_bytes(raw, "big", signed=False)
                    if key >= 2**63:
                        key -= 2**64

                    conn = await async_engine.connect()
                    res = await conn.execute(text("SELECT pg_try_advisory_lock(:key) AS locked"), {"key": key})
                    acquired = bool(res.scalar())
                    if acquired:
                        return {"acquired": True, "kind": "db_advisory", "db_conn": conn, "db_key": key}
                    await conn.close()
                    return {"acquired": False, "kind": "db_advisory"}
            except Exception as e:
                logger.warning(f"DB advisory lock acquisition failed, falling back: {e}")

            # Last resort: local in-process lock (single worker only)
            if project_id not in self._slide_generation_locks:
                self._slide_generation_locks[project_id] = asyncio.Lock()
            local_lock = self._slide_generation_locks[project_id]
            if local_lock.locked() or self._active_slide_generations.get(project_id, False):
                return {"acquired": False, "kind": "local"}
            return {"acquired": True, "kind": "local", "local_lock": local_lock}

    async def _release_slides_generation_lock(self, lock_info: dict):
            kind = lock_info.get("kind")
            if kind == "valkey":
                cache = lock_info.get("cache")
                lock_key = lock_info.get("lock_key")
                if cache and lock_key and getattr(cache, "is_connected", False):
                    try:
                        await cache.delete(lock_key)
                    except Exception:
                        pass
            elif kind == "db_advisory":
                conn = lock_info.get("db_conn")
                key = lock_info.get("db_key")
                if conn is not None and key is not None:
                    try:
                        from sqlalchemy import text
                        await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    except Exception:
                        pass
                    try:
                        await conn.close()
                    except Exception:
                        pass

    async def _background_generate_slides(self, project_id: str, lock_info: dict):
            """Run slide generation in background and ensure lock TTL/release."""
            renew_task = None
            local_lock = lock_info.get("local_lock")

            try:
                self._active_slide_generations[project_id] = True
                self._slides_generation_cancel_flags[project_id] = False

                # Mark stage as running early to avoid "cancelled" race on resume/reconnect.
                try:
                    import time
                    from ..db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()
                    await db_manager.update_stage_status(
                        project_id,
                        "ppt_creation",
                        "running",
                        0.0,
                        {"started_at": time.time()}
                    )
                except Exception:
                    pass

                cache = lock_info.get("cache")
                if cache and getattr(cache, "is_connected", False):
                    try:
                        await cache.delete(self._slides_generation_cancel_key(project_id))
                    except Exception:
                        pass

                if lock_info.get("kind") == "valkey" and cache and getattr(cache, "is_connected", False):
                    renew_task = asyncio.create_task(
                        self._renew_valkey_lock(cache, lock_info.get("lock_key"), int(lock_info.get("lock_ttl", 600))),
                        name=f"ppt-lock-renew:{project_id}",
                    )

                async def _consume():
                    async for _ in self._generate_slides_streaming_impl(project_id):
                        pass

                if local_lock is not None:
                    async with local_lock:
                        await _consume()
                else:
                    await _consume()

            except Exception as e:
                logger.error(f"Background slide generation failed for {project_id}: {e}", exc_info=True)
            finally:
                if renew_task is not None:
                    renew_task.cancel()
                    try:
                        await renew_task
                    except Exception:
                        pass

                self._active_slide_generations[project_id] = False
                await self._release_slides_generation_lock(lock_info)
                self._slides_generation_tasks.pop(project_id, None)

    async def _stream_slides_from_db(self, project_id: str, total_slides: int):
            """Stream newly saved slides from DB so reconnects won't restart from page 1."""
            import json
            import time

            from ..db_project_manager import DatabaseProjectManager
            db_manager = DatabaseProjectManager()

            sent_indices = set()
            last_keepalive = 0.0
            started_at = time.time()
            max_wait_seconds = 3 * 60 * 60  # 3h safety net

            # Send any existing slides immediately (resume / reconnect).
            try:
                existing = await db_manager.list_slides(project_id)
                for slide in existing:
                    idx = int(slide.get("page_number", 0)) - 1
                    if idx < 0 or idx >= total_slides:
                        continue
                    if idx in sent_indices:
                        continue
                    if slide.get("html_content"):
                        yield f"data: {json.dumps({'type': 'progress', 'current': idx + 1, 'total': total_slides, 'message': f'已生成第{idx+1}页'})}\n\n"
                        yield f"data: {json.dumps({'type': 'slide', 'slide_data': slide})}\n\n"
                        sent_indices.add(idx)
            except Exception:
                pass

            while len(sent_indices) < total_slides:
                if time.time() - started_at > max_wait_seconds:
                    yield f"data: {json.dumps({'type': 'error', 'message': '生成超时，请稍后重试或检查服务日志。'})}\n\n"
                    return

                # If stage signals cancel/failed, stop streaming.
                try:
                    stage = await db_manager.get_stage_status(project_id, "ppt_creation")
                    # Give newly-started generation a short grace period to flip stage to running.
                    if stage and stage.get("status") in ("failed", "cancelled") and (time.time() - started_at) > 5:
                        default_message = "生成已停止" if stage.get("status") == "cancelled" else "生成失败"
                        message = default_message
                        result = stage.get("result")
                        if isinstance(result, dict) and result.get("message"):
                            message = result["message"]
                        yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
                        return
                except Exception:
                    pass

                try:
                    slides = await db_manager.list_slides(project_id)
                    for slide in slides:
                        idx = int(slide.get("page_number", 0)) - 1
                        if idx < 0 or idx >= total_slides:
                            continue
                        if idx in sent_indices:
                            continue
                        if slide.get("html_content"):
                            yield f"data: {json.dumps({'type': 'progress', 'current': idx + 1, 'total': total_slides, 'message': f'已生成第{idx+1}页'})}\n\n"
                            yield f"data: {json.dumps({'type': 'slide', 'slide_data': slide})}\n\n"
                            sent_indices.add(idx)
                except Exception:
                    pass

                now = time.time()
                if now - last_keepalive > 10:
                    # SSE keepalive (ignored by EventSource but helps proxies).
                    yield ": keepalive\n\n"
                    last_keepalive = now

                await asyncio.sleep(1)

            yield f"data: {json.dumps({'type': 'complete', 'message': f'✅PPT制作完成！成功生成 {total_slides} 页幻灯片', 'total': total_slides})}\n\n"

    async def generate_slides_streaming(self, project_id: str):
            """Generate slides with streaming output.

            Generation is started idempotently in a background task protected by a distributed lock.
            The SSE response streams newly saved slides from DB to survive reconnects and multi-worker.
            """
            import json

            # Cleanup finished task records
            existing_task = self._slides_generation_tasks.get(project_id)
            if existing_task is not None and existing_task.done():
                self._slides_generation_tasks.pop(project_id, None)

            project = await self.project_manager.get_project(project_id)
            if not project or not project.outline:
                yield f"data: {json.dumps({'type': 'error', 'message': '未找到项目或大纲，请先生成大纲。'})}\n\n"
                return

            outline = project.outline if isinstance(project.outline, dict) else {}
            slides = outline.get("slides", []) if isinstance(outline, dict) else []
            total_slides = len(slides)
            if total_slides <= 0:
                yield f"data: {json.dumps({'type': 'error', 'message': '大纲中没有幻灯片信息。'})}\n\n"
                return

            # If slides are not complete yet, try to start generation (idempotent).
            needs_generation = True
            try:
                from ..db_project_manager import DatabaseProjectManager
                db_manager = DatabaseProjectManager()
                existing_slides = await db_manager.list_slides(project_id)
                existing_indices = {
                    int(s.get("page_number", 0)) - 1
                    for s in existing_slides
                    if s and s.get("html_content") and int(s.get("page_number", 0)) > 0
                }
                needs_generation = len(existing_indices) < total_slides
            except Exception:
                pass

            if needs_generation and (project_id not in self._slides_generation_tasks or self._slides_generation_tasks[project_id].done()):
                lock_info = await self._try_acquire_slides_generation_lock(project_id)
                if lock_info.get("acquired"):
                    task = asyncio.create_task(
                        self._background_generate_slides(project_id, lock_info),
                        name=f"ppt-generate:{project_id}",
                    )
                    self._slides_generation_tasks[project_id] = task
                    yield f"data: {json.dumps({'type': 'info', 'message': '已开始后台生成，支持断线重连。'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'info', 'message': '检测到其他进程正在生成，已进入跟随模式（断线可重连）。'})}\n\n"

            async for chunk in self._stream_slides_from_db(project_id, total_slides):
                yield chunk

    async def _generate_slides_streaming_direct(self, project_id: str):
            """Generate slides with streaming output for real-time display
            
            Uses distributed lock via Valkey for multi-worker deployments.
            """
            try:
                import json
                import time
                
                # Use distributed lock via Valkey for multi-worker deployments
                lock_key = f"ppt_generation_lock:{project_id}"
                lock_ttl = 600  # 10 minutes max lock time (auto-release if worker crashes)
                
                # Try to acquire distributed lock via Valkey
                from ..cache_service import get_cache_service
                cache = await get_cache_service()
                
                lock_acquired = False
                if cache.is_connected:
                    # Try to set lock with NX (only set if not exists)
                    try:
                        # Use SET with NX and EX for atomic lock acquisition
                        lock_acquired = await cache._client.set(lock_key, "locked", ex=lock_ttl, nx=True)
                        if lock_acquired:
                            logger.info(f"🔒 获取项目 {project_id} 的分布式生成锁成功")
                        else:
                            # Lock exists, check if generation is truly in progress
                            logger.info(f"⚠️ 项目 {project_id} 的分布式锁已被其他worker占用，跳过重复请求")
                            info_data = {
                                'type': 'info',
                                'message': '幻灯片生成已在其他进程中进行，请等待当前生成完成...'
                            }
                            yield f"data: {json.dumps(info_data)}\n\n"
                            return
                    except Exception as lock_error:
                        logger.warning(f"分布式锁获取失败，回退到本地锁: {lock_error}")
                        cache = None  # Fall back to local lock
                
                # Fallback to local in-process lock if Valkey is unavailable
                if not lock_acquired and not cache.is_connected if cache else True:
                    # Use local lock as fallback
                    if project_id not in self._slide_generation_locks:
                        self._slide_generation_locks[project_id] = asyncio.Lock()
                    
                    generation_lock = self._slide_generation_locks[project_id]
                    
                    # Check local lock
                    if self._active_slide_generations.get(project_id, False):
                        logger.info(f"⚠️ 项目 {project_id} 的本地生成锁已被占用，跳过重复请求")
                        info_data = {
                            'type': 'info',
                            'message': '幻灯片生成已在进行中，请等待当前生成完成...'
                        }
                        yield f"data: {json.dumps(info_data)}\n\n"
                        return
                    
                    # Try to acquire local lock
                    if not generation_lock.locked():
                        async with generation_lock:
                            self._active_slide_generations[project_id] = True
                            try:
                                async for chunk in self._generate_slides_streaming_impl(project_id):
                                    yield chunk
                            finally:
                                self._active_slide_generations[project_id] = False
                    else:
                        logger.info(f"⚠️ 项目 {project_id} 的本地锁已被占用，跳过请求")
                        info_data = {
                            'type': 'info',
                            'message': '幻灯片生成已在进行中，请等待当前生成完成...'
                        }
                        yield f"data: {json.dumps(info_data)}\n\n"
                    return
                
                # Distributed lock acquired, proceed with generation
                try:
                    self._active_slide_generations[project_id] = True
                    async for chunk in self._generate_slides_streaming_impl(project_id):
                        yield chunk
                finally:
                    # Release distributed lock
                    self._active_slide_generations[project_id] = False
                    if cache and cache.is_connected:
                        try:
                            await cache.delete(lock_key)
                            logger.info(f"🔓 释放项目 {project_id} 的分布式生成锁")
                        except Exception as unlock_error:
                            logger.warning(f"释放分布式锁失败: {unlock_error}")
                            
            except Exception as e:
                logger.error(f"Error in streaming PPT generation wrapper: {e}")
                error_message = f'生成过程中出现错误：{str(e)}'
                error_response = {'type': 'error', 'message': error_message}
                yield f"data: {json.dumps(error_response)}\n\n"

    async def regenerate_slide(self, project_id: str, slide_index: int,
                                 request: PPTGenerationRequest) -> Optional[SlideContent]:
            """Regenerate a specific slide"""
            try:
                project = await self.project_manager.get_project(project_id)
                if not project or not project.outline:
                    return None

                if slide_index >= len(project.outline.slides):
                    return None

                slide_data = project.outline.slides[slide_index]

                # Generate new content
                content = await self.generate_slide_content(
                    slide_data["title"],
                    request.scenario,
                    request.topic,
                    request.language
                )

                # Create new slide content
                new_slide = SlideContent(
                    type=self._normalize_slide_type(slide_data.get("type", "content")),
                    title=slide_data["title"],
                    subtitle=slide_data.get("subtitle", ""),
                    content=content,
                    bullet_points=self._extract_bullet_points(content),
                    image_suggestions=await self._suggest_images(slide_data["title"], request.scenario),
                    layout="default"
                )

                return new_slide

            except Exception as e:
                logger.error(f"Error regenerating slide: {e}")
                return None

    async def lock_slide(self, project_id: str, slide_index: int, user_id: Optional[int] = None) -> bool:
            """Lock a slide to prevent regeneration. If user_id is provided, enforces ownership."""
            # Verify project ownership first if user_id is provided
            if user_id is not None:
                project = await self.project_manager.get_project(project_id, user_id=user_id)
                if not project:
                    return False
            # This would be implemented with proper slide state management
            # For now, return True as placeholder
            return True

    async def unlock_slide(self, project_id: str, slide_index: int, user_id: Optional[int] = None) -> bool:
            """Unlock a slide to allow regeneration. If user_id is provided, enforces ownership."""
            # Verify project ownership first if user_id is provided
            if user_id is not None:
                project = await self.project_manager.get_project(project_id, user_id=user_id)
                if not project:
                    return False
            # This would be implemented with proper slide state management
            # For now, return True as placeholder
            return True
