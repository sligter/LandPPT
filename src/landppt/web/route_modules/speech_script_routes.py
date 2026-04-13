"""
Generated route module extracted from the legacy web router.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from ...ai import AIMessage, MessageRole, get_ai_provider, get_role_provider
from ...api.models import FileOutlineGenerationRequest, PPTGenerationRequest, PPTProject, TodoBoard
from ...auth.middleware import get_current_user_optional, get_current_user_required
from ...core.config import ai_config, app_config, resolve_timeout_seconds
from ...database.database import AsyncSessionLocal, get_db
from ...database.models import User
from ...services.enhanced_ppt_service import EnhancedPPTService
from ...services.pdf_to_pptx_converter import get_pdf_to_pptx_converter
from ...services.pyppeteer_pdf_converter import get_pdf_converter
from ...utils.thread_pool import run_blocking_io, to_thread
from .support import (
    _apply_no_store_headers,
    check_credits_for_operation,
    consume_credits_for_operation,
    get_ppt_service_for_user,
    logger,
    ppt_service,
    templates,
)

router = APIRouter()


def _is_billable_provider(provider_name: str | None) -> bool:
    return (provider_name or "").strip().lower() == "landppt"


class SpeechScriptGenerationRequest(BaseModel):
    generation_type: str  # "single", "multi", "full"
    slide_indices: Optional[List[int]] = None  # For single and multi generation
    customization: Dict[str, Any] = {}  # Customization options
    language: str = "zh"


class SpeechScriptExportRequest(BaseModel):
    export_format: str  # "docx", "markdown"
    scripts_data: List[Dict[str, Any]]
    include_metadata: bool = True


class SpeechScriptHumanizeItem(BaseModel):
    slide_index: int
    slide_title: Optional[str] = None
    script_content: str


class SpeechScriptHumanizeRequest(BaseModel):
    scripts: List[SpeechScriptHumanizeItem]
    language: str = "zh"


def _safe_speech_enum(enum_cls, raw_value, default_value):
    try:
        return enum_cls(raw_value)
    except Exception:
        return default_value


@router.post("/api/projects/{project_id}/speech-script/generate")
async def generate_speech_script(
    project_id: str,
    request: SpeechScriptGenerationRequest,
    user: User = Depends(get_current_user_required)
):
    """Generate speech scripts for presentation slides"""
    try:
        import uuid
        import asyncio

        # Generate task ID for progress tracking
        task_id = str(uuid.uuid4())

        # Get project
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }

        # Check if slides data exists
        if not project.slides_data or len(project.slides_data) == 0:
            return {
                "success": False,
                "error": "No slides data available"
            }

        # Import speech script service
        from ...services.speech_script_service import SpeechScriptService, SpeechScriptCustomization
        from ...services.speech_script_service import SpeechTone, TargetAudience, LanguageComplexity

        # Initialize service with user_id for database AI config lookup
        speech_service = SpeechScriptService(user_id=user.id)
        await speech_service.initialize_async()


        # Parse customization options
        customization_data = request.customization
        customization = SpeechScriptCustomization(
            language=(request.language or "zh"),
            tone=SpeechTone(customization_data.get('tone', 'conversational')),
            target_audience=TargetAudience(customization_data.get('target_audience', 'general_public')),
            language_complexity=LanguageComplexity(customization_data.get('language_complexity', 'moderate')),
            custom_style_prompt=customization_data.get('custom_style_prompt'),
            include_transitions=customization_data.get('include_transitions', True),
            include_timing_notes=customization_data.get('include_timing_notes', False),
            speaking_pace=customization_data.get('speaking_pace', 'normal')
        )

        # Validate request parameters
        if request.generation_type == "single":
            if not request.slide_indices or len(request.slide_indices) != 1:
                return {
                    "success": False,
                    "error": "Single generation requires exactly one slide index"
                }
        elif request.generation_type == "multi":
            if not request.slide_indices:
                return {
                    "success": False,
                    "error": "Multi generation requires slide indices"
                }
        elif request.generation_type != "full":
            return {
                "success": False,
                "error": "Invalid generation type"
            }

        # Create progress task immediately (Valkey-backed) to avoid first-poll "Task not found" in multi-worker setups.
        if request.generation_type == "full":
            slide_indices = list(range(len(project.slides_data)))
        else:
            slide_indices = request.slide_indices or []

        # Check credits before scheduling any AI work (only billable for LandPPT provider).
        speech_provider_name = (speech_service.provider_settings or {}).get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_other", len(slide_indices), provider_name=speech_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "error": f"积分不足，演讲稿生成需要 {required} 积分，当前余额 {balance} 积分",
            }

        from ...services.progress_tracker import progress_tracker
        await progress_tracker.create_task_async(
            task_id=task_id,
            project_id=project_id,
            total_slides=len(slide_indices),
            overwrite=True,
        )

        # Start async generation task
        async def generate_async():
            try:
                logger.info(f"Starting async generation for task {task_id}")

                # Generate scripts based on type
                if request.generation_type == "single":
                    # Use multi_slide_scripts_with_retry for single slide to get progress tracking
                    result = await speech_service.generate_multi_slide_scripts_with_retry(
                        project, slide_indices, customization, task_id=task_id
                    )
                elif request.generation_type == "multi":
                    result = await speech_service.generate_multi_slide_scripts_with_retry(
                        project, slide_indices, customization, task_id=task_id
                    )
                elif request.generation_type == "full":
                    result = await speech_service.generate_full_presentation_scripts(
                        project, customization, progress_callback=None, task_id=task_id
                    )

                # Save scripts to database if successful
                if result.success:
                    logger.info(f"Generation successful for task {task_id}, saving to database")
                    from ...services.speech_script_repository import SpeechScriptRepository
                    repo = SpeechScriptRepository()

                    generation_params = {
                        'generation_type': request.generation_type,
                        'tone': customization.tone.value,
                        'target_audience': customization.target_audience.value,
                        'language_complexity': customization.language_complexity.value,
                        'custom_audience': request.customization.get('custom_audience'),
                        'custom_style_prompt': customization.custom_style_prompt,
                        'include_transitions': customization.include_transitions,
                        'include_timing_notes': customization.include_timing_notes,
                        'speaking_pace': customization.speaking_pace
                    }

                    saved_count = 0
                    for script in result.scripts:
                        await repo.save_speech_script(
                            project_id=project_id,
                            slide_index=script.slide_index,
                            language=(request.language or "zh"),
                            slide_title=script.slide_title,
                            script_content=script.script_content,
                            generation_params=generation_params,
                            estimated_duration=script.estimated_duration
                        )
                        saved_count += 1
                        logger.debug(f"Saved script {saved_count}/{len(result.scripts)} for slide {script.slide_index}")

                    # Ensure all changes are committed before closing
                    repo.db.commit()
                    repo.close()
                    logger.info(f"All {saved_count} scripts saved and committed to database for task {task_id}")

                    if saved_count > 0:
                        billed, bill_message = await consume_credits_for_operation(
                            user.id,
                            "ai_other",
                            saved_count,
                            description=f"演讲稿生成: {saved_count}页",
                            reference_id=project_id,
                            provider_name=speech_provider_name,
                        )
                        if not billed and _is_billable_provider(speech_provider_name):
                            logger.error(f"Speech script billing failed for task {task_id}: {bill_message}")

                    # NOW mark the task as completed after database save
                    await progress_tracker.complete_task_async(task_id, f"生成完成！成功 {saved_count} 页")
                    logger.info(f"Task {task_id} marked as completed")
                else:
                    logger.error(f"Generation failed for task {task_id}: {result.error_message}")
                    await progress_tracker.fail_task_async(task_id, result.error_message or "生成失败")

            except Exception as e:
                logger.error(f"Async speech script generation failed for task {task_id}: {e}")
                await progress_tracker.fail_task_async(task_id, str(e))

        # Start the async task
        asyncio.create_task(generate_async())

        # Return immediately with task_id
        return {
            "success": True,
            "task_id": task_id,
            "message": "演讲稿生成已开始，请查看进度"
        }

    except Exception as e:
        logger.error(f"Speech script generation failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/api/projects/{project_id}/speech-script/export")
async def export_speech_script(
    project_id: str,
    request: SpeechScriptExportRequest,
    user: User = Depends(get_current_user_required)
):
    """Export speech scripts to document format"""
    try:
        # Get project for title
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }

        # Import exporter
        from ...services.speech_script_exporter import get_speech_script_exporter
        from ...services.speech_script_service import SlideScriptData

        exporter = get_speech_script_exporter()

        # Validate scripts data
        if not request.scripts_data or len(request.scripts_data) == 0:
            return {
                "success": False,
                "error": "No speech scripts data provided"
            }

        # Convert scripts data to SlideScriptData objects
        scripts = []
        for script_data in request.scripts_data:
            # Validate required fields
            if not script_data.get('script_content'):
                continue  # Skip empty scripts

            script = SlideScriptData(
                slide_index=script_data.get('slide_index', 0),
                slide_title=script_data.get('slide_title', ''),
                script_content=script_data.get('script_content', ''),
                estimated_duration=script_data.get('estimated_duration'),
                speaker_notes=script_data.get('speaker_notes')
            )
            scripts.append(script)

        # Check if we have any valid scripts after filtering
        if not scripts:
            return {
                "success": False,
                "error": "No valid speech scripts found"
            }

        # Prepare metadata
        metadata = {}
        if request.include_metadata:
            # Calculate total estimated duration from all scripts
            total_duration = None
            if scripts:
                total_minutes = 0
                for script in scripts:
                    if script.estimated_duration and '分钟' in script.estimated_duration:
                        try:
                            minutes = float(script.estimated_duration.replace('分钟', ''))
                            total_minutes += minutes
                        except ValueError:
                            pass
                if total_minutes > 0:
                    total_duration = f"{total_minutes:.1f}分钟"

            metadata = {
                'generation_time': time.time(),
                'total_estimated_duration': total_duration,
                'customization': {}
            }

        # Export based on format
        if request.export_format == "docx":
            if not exporter.is_docx_available():
                return {
                    "success": False,
                    "error": "DOCX export not available. Please install python-docx."
                }

            docx_content = await exporter.export_to_docx(
                scripts, project.topic, metadata
            )

            # Return file response
            import urllib.parse
            filename = f"{project.topic}_演讲稿.docx"
            safe_filename = urllib.parse.quote(filename, safe='')

            from fastapi.responses import Response
            return Response(
                content=docx_content,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"
                }
            )

        elif request.export_format == "markdown":
            markdown_content = await exporter.export_to_markdown(
                scripts, project.topic, metadata
            )

            # Return file response
            import urllib.parse
            filename = f"{project.topic}_演讲稿.md"
            safe_filename = urllib.parse.quote(filename, safe='')

            from fastapi.responses import Response
            return Response(
                content=markdown_content.encode('utf-8'),
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"
                }
            )

        else:
            return {
                "success": False,
                "error": "Unsupported export format"
            }

    except Exception as e:
        logger.error(f"Speech script export failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/api/projects/{project_id}/speech-scripts")
async def get_current_speech_scripts(
    project_id: str,
    language: str = "zh",
    user: User = Depends(get_current_user_required)
):
    """获取项目的当前演讲稿"""
    try:
        from ...services.speech_script_repository import SpeechScriptRepository

        # 检查项目是否存在
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }

        repo = SpeechScriptRepository()

        # Expire all objects to ensure fresh data from database
        repo.db.expire_all()

        # 获取项目的当前演讲稿
        scripts = await repo.get_current_speech_scripts_by_project(project_id, language=language)
        logger.info(f"Found {len(scripts)} speech scripts for project {project_id}")

        # 转换为JSON格式
        scripts_data = []
        for script in scripts:
            scripts_data.append({
                "id": script.id,
                "slide_index": script.slide_index,
                "language": getattr(script, "language", "zh"),
                "slide_title": script.slide_title,
                "script_content": script.script_content,
                "estimated_duration": script.estimated_duration,
                "speaker_notes": script.speaker_notes,
                "generation_type": script.generation_type,
                "tone": script.tone,
                "target_audience": script.target_audience,
                "custom_audience": script.custom_audience,
                "language_complexity": script.language_complexity,
                "speaking_pace": script.speaking_pace,
                "custom_style_prompt": script.custom_style_prompt,
                "include_transitions": script.include_transitions,
                "include_timing_notes": script.include_timing_notes,
                "created_at": script.created_at,
                "updated_at": script.updated_at
            })

        repo.close()

        return {
            "success": True,
            "scripts": scripts_data
        }

    except Exception as e:
        logger.error(f"Get current speech scripts failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/api/projects/{project_id}/speech-scripts/humanize")
async def humanize_speech_scripts(
    project_id: str,
    request: SpeechScriptHumanizeRequest,
    user: User = Depends(get_current_user_required)
):
    """按 Humanizer-zh 风格将演讲稿改写为更自然的人话表达。"""
    try:
        from ...services.speech_script_repository import SpeechScriptRepository
        from ...services.speech_script_service import (
            LanguageComplexity,
            SpeechScriptCustomization,
            SpeechScriptService,
            SpeechTone,
            TargetAudience,
        )
        from ...services.progress_tracker import progress_tracker

        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }

        requested_language = ((request.language or "zh").strip().lower() or "zh")
        normalized_items: List[SpeechScriptHumanizeItem] = []
        seen_slide_indices = set()
        for item in request.scripts or []:
            content = (item.script_content or "").strip()
            if not content:
                continue
            if item.slide_index in seen_slide_indices:
                continue
            seen_slide_indices.add(item.slide_index)
            normalized_items.append(item)

        if not normalized_items:
            return {
                "success": False,
                "error": "没有可人话化的演讲稿内容"
            }

        user_id = user.id
        speech_service = SpeechScriptService(user_id=user.id)
        await speech_service.initialize_async()

        speech_provider_name = (speech_service.provider_settings or {}).get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user_id, "ai_other", len(normalized_items), provider_name=speech_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "error": f"积分不足，演讲稿一键人话需要 {required} 积分，当前余额 {balance} 积分",
            }

        task_id = str(uuid.uuid4())
        await progress_tracker.create_task_async(
            task_id=task_id,
            project_id=project_id,
            total_slides=len(normalized_items),
            overwrite=True,
        )
        await progress_tracker.update_progress_async(task_id, message="开始一键人话...")

        async def humanize_async():
            repo = None
            try:
                repo = SpeechScriptRepository()
                updated_scripts: List[Dict[str, Any]] = []
                failed_slides: List[Dict[str, Any]] = []

                for item in normalized_items:
                    fallback_title = (item.slide_title or f"第{item.slide_index + 1}页").strip()
                    await progress_tracker.update_progress_async(
                        task_id,
                        current_slide=item.slide_index,
                        current_slide_title=fallback_title,
                        message=f"正在处理第{item.slide_index + 1}页演讲稿...",
                    )

                    existing_script = await repo.get_speech_script_by_slide(
                        project_id,
                        item.slide_index,
                        language=requested_language,
                    )
                    if not existing_script:
                        missing_error = "演讲稿不存在"
                        failed_slides.append({
                            "slide_index": item.slide_index,
                            "error": missing_error,
                        })
                        await progress_tracker.add_slide_failed_async(
                            task_id,
                            item.slide_index,
                            fallback_title,
                            missing_error,
                        )
                        continue

                    custom_style_prompt = (getattr(existing_script, "custom_style_prompt", None) or "").strip()
                    custom_audience = (getattr(existing_script, "custom_audience", None) or "").strip()
                    if custom_audience:
                        audience_prompt = f"额外受众要求：{custom_audience}"
                        custom_style_prompt = (
                            f"{custom_style_prompt}\n{audience_prompt}".strip()
                            if custom_style_prompt
                            else audience_prompt
                        )

                    customization = SpeechScriptCustomization(
                        language=requested_language,
                        tone=_safe_speech_enum(
                            SpeechTone,
                            getattr(existing_script, "tone", None),
                            SpeechTone.CONVERSATIONAL,
                        ),
                        target_audience=_safe_speech_enum(
                            TargetAudience,
                            getattr(existing_script, "target_audience", None),
                            TargetAudience.GENERAL_PUBLIC,
                        ),
                        language_complexity=_safe_speech_enum(
                            LanguageComplexity,
                            getattr(existing_script, "language_complexity", None),
                            LanguageComplexity.MODERATE,
                        ),
                        custom_style_prompt=custom_style_prompt or None,
                        include_transitions=bool(getattr(existing_script, "include_transitions", True)),
                        include_timing_notes=bool(getattr(existing_script, "include_timing_notes", False)),
                        speaking_pace=(getattr(existing_script, "speaking_pace", None) or "normal"),
                    )

                    try:
                        humanized_content = await speech_service.humanize_script(item.script_content, customization)
                        if not humanized_content:
                            raise ValueError("AI 未返回可用内容")

                        existing_script.script_content = humanized_content
                        existing_script.slide_title = (
                            item.slide_title
                            or existing_script.slide_title
                            or f"第{item.slide_index + 1}页"
                        ).strip()
                        existing_script.estimated_duration = speech_service._estimate_speaking_duration(humanized_content)
                        existing_script.updated_at = time.time()

                        updated_scripts.append({
                            "id": existing_script.id,
                            "slide_index": existing_script.slide_index,
                            "language": existing_script.language,
                            "slide_title": existing_script.slide_title,
                            "script_content": existing_script.script_content,
                            "estimated_duration": existing_script.estimated_duration,
                            "speaker_notes": existing_script.speaker_notes,
                            "updated_at": existing_script.updated_at,
                        })
                        await progress_tracker.add_slide_completed_async(
                            task_id,
                            item.slide_index,
                            existing_script.slide_title,
                        )
                    except Exception as humanize_error:
                        error_text = str(humanize_error)
                        failed_slides.append({
                            "slide_index": item.slide_index,
                            "error": error_text,
                        })
                        await progress_tracker.add_slide_failed_async(
                            task_id,
                            item.slide_index,
                            getattr(existing_script, "slide_title", None) or fallback_title,
                            error_text,
                        )

                if not updated_scripts:
                    if repo and repo.db:
                        repo.db.rollback()
                    await progress_tracker.fail_task_async(
                        task_id,
                        failed_slides[0]["error"] if failed_slides else "一键人话失败",
                    )
                    return

                repo.db.commit()

                billed, bill_message = await consume_credits_for_operation(
                    user_id,
                    "ai_other",
                    len(updated_scripts),
                    description=f"演讲稿一键人话: {len(updated_scripts)}页",
                    reference_id=project_id,
                    provider_name=speech_provider_name,
                )
                if not billed and _is_billable_provider(speech_provider_name):
                    logger.error(
                        "Speech script humanize billing failed for project %s: %s",
                        project_id,
                        bill_message,
                    )

                message = f"一键人话完成！成功 {len(updated_scripts)} 页"
                if failed_slides:
                    message += f"，失败 {len(failed_slides)} 页"
                await progress_tracker.complete_task_async(task_id, message)
            except Exception as e:
                if repo and repo.db:
                    repo.db.rollback()
                logger.error(f"Humanize speech scripts async task failed: {e}")
                await progress_tracker.fail_task_async(task_id, str(e))
            finally:
                if repo:
                    repo.close()

        asyncio.create_task(humanize_async())

        return {
            "success": True,
            "task_id": task_id,
            "message": "演讲稿一键人话已开始，请查看进度",
        }

    except Exception as e:
        logger.error(f"Humanize speech scripts failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@router.delete("/api/projects/{project_id}/speech-scripts/slide/{slide_index}")
async def delete_speech_script_by_slide(
    project_id: str,
    slide_index: int,
    language: str = "zh",
    user: User = Depends(get_current_user_required)
):
    """删除指定幻灯片的演讲稿"""
    try:
        from ...services.speech_script_repository import SpeechScriptRepository

        # 检查项目是否存在
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }

        repo = SpeechScriptRepository()

        # 获取并删除指定幻灯片的演讲稿
        script = await repo.get_speech_script_by_slide(project_id, slide_index, language=language)
        if not script:
            return {
                "success": False,
                "error": "Speech script not found"
            }

        success = await repo.delete_speech_script(script.id)

        return {
            "success": success,
            "message": f"第{slide_index + 1}页演讲稿已删除" if success else "删除演讲稿失败"
        }

    except Exception as e:
        logger.error(f"Delete speech script failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/api/projects/{project_id}/speech-scripts/result/{task_id}")
async def get_speech_script_result(
    project_id: str,
    task_id: str,
    language: str = "zh",
    user: User = Depends(get_current_user_required)
):
    """获取演讲稿生成结果"""
    try:
        from ...services.progress_tracker import progress_tracker
        from ...services.speech_script_repository import SpeechScriptRepository

        # 检查项目是否存在
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }

        # 获取进度信息（多worker下从Valkey读取）
        progress_info = await progress_tracker.get_progress_async(task_id)

        if not progress_info:
            return {
                "success": False,
                "error": "Task not found"
            }

        # 验证任务是否属于该项目
        if progress_info.project_id != project_id:
            return {
                "success": False,
                "error": "Access denied"
            }

        # 如果任务还未完成，返回进度信息
        if progress_info.status != "completed":
            return {
                "success": False,
                "error": "Task not completed yet",
                "status": progress_info.status,
                "progress": progress_info.to_dict()
            }

        # 获取生成的演讲稿
        repo = SpeechScriptRepository()
        scripts = await repo.get_current_speech_scripts_by_project(project_id, language=language)

        # 转换为API格式
        scripts_data = []
        total_duration_seconds = 0

        for script in scripts:
            script_data = {
                "slide_index": script.slide_index,
                "slide_title": script.slide_title,
                "script_content": script.script_content,
                "estimated_duration": script.estimated_duration,
                "speaker_notes": getattr(script, 'speaker_notes', None)
            }
            scripts_data.append(script_data)

            # 计算总时长
            if script.estimated_duration:
                try:
                    if '分钟' in script.estimated_duration:
                        minutes = float(script.estimated_duration.replace('分钟', ''))
                        total_duration_seconds += minutes * 60
                    elif '秒' in script.estimated_duration:
                        seconds = float(script.estimated_duration.replace('秒', ''))
                        total_duration_seconds += seconds
                except:
                    pass

        # 格式化总时长
        if total_duration_seconds < 60:
            total_duration = f"{int(total_duration_seconds)}秒"
        else:
            minutes = total_duration_seconds / 60
            total_duration = f"{minutes:.1f}分钟"

        repo.close()

        return {
            "success": True,
            "scripts": scripts_data,
            "total_estimated_duration": total_duration,
            "generation_metadata": {
                "task_id": task_id,
                "completed_at": progress_info.last_update,
                "total_slides": progress_info.total_slides,
                "completed_slides": progress_info.completed_slides,
                "failed_slides": progress_info.failed_slides,
                "skipped_slides": progress_info.skipped_slides
            }
        }

    except Exception as e:
        logger.error(f"Get speech script result failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/api/projects/{project_id}/speech-scripts/progress/{task_id}")
async def get_speech_script_progress(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user_required)
):
    """获取演讲稿生成进度"""
    try:
        from ...services.progress_tracker import progress_tracker

        # 检查项目是否存在
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }

        # 获取进度信息（多worker下从Valkey读取）
        progress_info = await progress_tracker.get_progress_async(task_id)

        if not progress_info:
            return {
                "success": False,
                "error": "Task not found"
            }

        # 验证任务是否属于该项目
        if progress_info.project_id != project_id:
            return {
                "success": False,
                "error": "Access denied"
            }

        return {
            "success": True,
            "progress": progress_info.to_dict()
        }

    except Exception as e:
        logger.error(f"Get speech script progress failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.put("/api/projects/{project_id}/speech-scripts/slide/{slide_index}")
async def update_speech_script_content(
    project_id: str,
    slide_index: int,
    request: dict,
    language: str = "zh",
    user: User = Depends(get_current_user_required)
):
    """更新演讲稿内容"""
    try:
        from ...services.speech_script_repository import SpeechScriptRepository

        # 检查项目是否存在
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }

        # 获取请求数据
        script_content = request.get('script_content', '').strip()
        slide_title = request.get('slide_title', f'第{slide_index + 1}页')
        estimated_duration = request.get('estimated_duration')
        speaker_notes = request.get('speaker_notes')

        if not script_content:
            return {
                "success": False,
                "error": "演讲稿内容不能为空"
            }

        repo = SpeechScriptRepository()

        # 获取现有演讲稿
        existing_script = await repo.get_speech_script_by_slide(project_id, slide_index, language=language)
        if not existing_script:
            return {
                "success": False,
                "error": "演讲稿不存在"
            }

        # 更新内容
        existing_script.script_content = script_content
        existing_script.slide_title = slide_title
        if estimated_duration:
            existing_script.estimated_duration = estimated_duration
        if speaker_notes is not None:
            existing_script.speaker_notes = speaker_notes
        existing_script.updated_at = time.time()

        repo.db.commit()
        repo.db.refresh(existing_script)
        repo.close()

        return {
            "success": True,
            "message": "演讲稿已更新",
            "script": {
                "id": existing_script.id,
                "slide_index": existing_script.slide_index,
                "slide_title": existing_script.slide_title,
                "script_content": existing_script.script_content,
                "estimated_duration": existing_script.estimated_duration,
                "speaker_notes": existing_script.speaker_notes,
                "updated_at": existing_script.updated_at
            }
        }

    except Exception as e:
        logger.error(f"Update speech script content failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }
