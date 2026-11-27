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
from ..runtime.ai_execution import (
    ExecutionContext,
    is_provider_protocol_error,
    scoped_ai_conversation,
)
from ..prompts import prompts_manager
from ..audience_content import is_production_direction
from ..video_explainer import VIDEO_SCENE_TYPES, is_video_explainer
from ..research.enhanced_research_service import EnhancedResearchService
from ..research.enhanced_report_generator import EnhancedReportGenerator
from ..pyppeteer_pdf_converter import get_pdf_converter
from ..image.image_service import ImageService
from ..image.adapters.ppt_prompt_adapter import PPTSlideContext
from ...utils.thread_pool import run_blocking_io, to_thread
from .outline_errors import OutlineRepairFailedError


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .project_outline_validation_service import ProjectOutlineValidationService


class ProjectOutlineRepairService:
    """Extracted logic from ProjectOutlineValidationService."""

    def __init__(self, service: 'ProjectOutlineValidationService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _validate_and_repair_outline_json(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        """验证大纲JSON数据的正确性，如果有错误则调用AI修复，最多修复10次"""
        try:
            logger.info(f'outline_data: {outline_data}')
            validation_errors = self._validate_outline_structure(outline_data, confirmed_requirements)
            if not validation_errors:
                logger.info('大纲JSON验证通过，无需修复')
                return outline_data
            logger.warning(f'大纲JSON验证发现 {len(validation_errors)} 个错误，开始AI修复')
            max_repair_attempts = 10
            current_attempt = 1
            while current_attempt <= max_repair_attempts:
                logger.info(f'第 {current_attempt} 次AI修复尝试')
                try:
                    repaired_outline = await self._repair_outline_with_ai(outline_data, validation_errors, confirmed_requirements)
                    repair_validation_errors = self._validate_outline_structure(repaired_outline, confirmed_requirements)
                    if not repair_validation_errors:
                        logger.info(f'AI修复成功，第 {current_attempt} 次尝试通过验证')
                        return repaired_outline
                    else:
                        logger.warning(f'第 {current_attempt} 次AI修复后仍有 {len(repair_validation_errors)} 个错误')
                        validation_errors = repair_validation_errors
                        outline_data = repaired_outline
                except Exception as repair_error:
                    logger.error(f'第 {current_attempt} 次AI修复失败: {str(repair_error)}')
                    if is_provider_protocol_error(repair_error):
                        raise
                current_attempt += 1
            logger.error(
                'AI修复达到最大尝试次数(%d次)，大纲仍不合法: %s',
                max_repair_attempts, '; '.join(validation_errors)
            )
            # Surface the failure. Returning the invalid outline let callers save it
            # and emit success, leaving the project "completed" with an unusable
            # (sometimes zero-slide) outline.
            raise OutlineRepairFailedError(validation_errors)
        except OutlineRepairFailedError:
            raise
        except Exception as e:
            logger.error(f'验证和修复过程出错: {str(e)}')
            raise OutlineRepairFailedError([str(e)]) from e

    def _validate_outline_structure(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> List[str]:
        """验证大纲结构，返回错误列表"""
        errors = []
        try:
            if not isinstance(outline_data, dict):
                errors.append('大纲数据必须是字典格式')
                return errors
            if 'slides' not in outline_data:
                errors.append('缺少必需字段: slides')
                return errors
            if 'title' not in outline_data:
                errors.append('缺少必需字段: title')
            elif isinstance(outline_data["title"], str) and is_production_direction(outline_data["title"]):
                errors.append("大纲标题含制作说明，请改成主题本身")
            slides = outline_data.get('slides', [])
            if not isinstance(slides, list):
                errors.append('slides字段必须是列表格式')
                return errors
            if len(slides) == 0:
                errors.append('slides列表不能为空')
                return errors
            page_count_settings = confirmed_requirements.get('page_count_settings', {})
            page_count_mode = page_count_settings.get('mode', 'ai_decide')
            actual_page_count = len(slides)
            # `or default` rather than get(key, default): callers routinely pass the
            # keys explicitly set to None, and `actual_page_count < None` raised a
            # TypeError that was swallowed as a generic validation error — burning
            # all 10 repair attempts on a comparison bug.
            if page_count_mode == 'custom_range':
                min_pages = page_count_settings.get('min_pages') or 8
                max_pages = page_count_settings.get('max_pages') or 15
                if actual_page_count < min_pages:
                    errors.append(f'页数不足：当前{actual_page_count}页，要求至少{min_pages}页')
                elif actual_page_count > max_pages:
                    errors.append(f'页数过多：当前{actual_page_count}页，要求最多{max_pages}页')
            elif page_count_mode == 'fixed':
                fixed_pages = page_count_settings.get('fixed_pages') or 10
                if actual_page_count != fixed_pages:
                    errors.append(f'页数不匹配：当前{actual_page_count}页，要求恰好{fixed_pages}页')
            for i, slide in enumerate(slides):
                slide_errors = self._validate_slide_structure(slide, i + 1)
                errors.extend(slide_errors)
            if is_video_explainer(confirmed_requirements):
                for i, slide in enumerate(slides):
                    if isinstance(slide, dict) and slide.get("slide_type") not in VIDEO_SCENE_TYPES:
                        errors.append(f"第{i + 1}镜：用有实质内容的 content 或 conclusion 镜头")
                if isinstance(slides[0], dict) and slides[0].get("slide_type") == "conclusion":
                    errors.append("第一镜必须是直接展示问题的 content 镜头")
            page_numbers = [slide.get('page_number', 0) for slide in slides]
            expected_numbers = list(range(1, len(slides) + 1))
            if page_numbers != expected_numbers:
                expected_str = ', '.join(map(str, expected_numbers))
                actual_str = ', '.join(map(str, page_numbers))
                errors.append(f'页码不连续：期望[{expected_str}]，实际[{actual_str}]')
            return errors
        except Exception as e:
            errors.append(f'验证过程出错: {str(e)}')
            return errors

    def _validate_slide_structure(self, slide: Dict[str, Any], slide_index: int) -> List[str]:
        """验证单个slide的结构"""
        errors = []
        try:
            if not isinstance(slide, dict):
                errors.append(f'第{slide_index}页：slide必须是字典格式')
                return errors
            required_fields = ['page_number', 'title', 'content_points', 'slide_type']
            for field in required_fields:
                if field not in slide:
                    errors.append(f'第{slide_index}页：缺少必需字段 {field}')
            if 'page_number' in slide:
                page_num = slide['page_number']
                if not isinstance(page_num, int) or page_num != slide_index:
                    errors.append(f'第{slide_index}页：page_number应为{slide_index}，实际为{page_num}')
            if 'title' in slide:
                title = slide['title']
                if not isinstance(title, str) or not title.strip():
                    errors.append(f'第{slide_index}页：title必须是非空字符串')
                elif is_production_direction(title):
                    errors.append(f"第{slide_index}页：标题含制作说明，请写主题相关的问题或结论")
            description = slide.get("description")
            if isinstance(description, str) and is_production_direction(description):
                errors.append(f"第{slide_index}页：description 含制作说明，请移入 production_notes")
            if 'content_points' in slide:
                content_points = slide['content_points']
                if not isinstance(content_points, list):
                    errors.append(f'第{slide_index}页：content_points必须是列表格式')
                elif len(content_points) == 0:
                    errors.append(f'第{slide_index}页：content_points不能为空')
                else:
                    for j, point in enumerate(content_points):
                        if not isinstance(point, str) or not point.strip():
                            errors.append(f'第{slide_index}页：content_points[{j}]必须是非空字符串')
                        elif is_production_direction(point):
                            errors.append(
                                f"第{slide_index}页：content_points[{j}] 含制作说明，请写主题本身的事实或结论"
                            )
            if 'slide_type' in slide:
                slide_type = slide['slide_type']
                valid_types = ['title', 'content', 'agenda', 'transition', 'thankyou', 'conclusion']
                if slide_type not in valid_types:
                    valid_types_str = ', '.join(valid_types)
                    errors.append(f'第{slide_index}页：slide_type必须是{valid_types_str}中的一个，实际为{slide_type}')
            return errors
        except Exception as e:
            errors.append(f'第{slide_index}页验证出错: {str(e)}')
            return errors

    @scoped_ai_conversation("outline-repair")
    async def _repair_outline_with_ai(self, outline_data: Dict[str, Any], validation_errors: List[str], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        """使用AI修复大纲JSON数据"""
        try:
            repair_prompt = self._build_repair_prompt(outline_data, validation_errors, confirmed_requirements)
            response = await self._text_completion_for_role('outline', prompt=repair_prompt, temperature=0.7)
            repaired_outline = self._parse_outline_content(
                response.content.strip(),
                PPTProject(
                    project_id="outline-repair",
                    title=str(outline_data.get("title") or confirmed_requirements.get("topic") or "PPT大纲"),
                    scenario=str(confirmed_requirements.get("type") or "general"),
                    topic=str(outline_data.get("title") or confirmed_requirements.get("topic") or "PPT大纲"),
                ),
            )
            logger.info('AI修复完成，返回修复后的大纲')
            return repaired_outline
        except Exception as e:
            logger.error(f'AI修复过程出错: {str(e)}')
            if is_provider_protocol_error(e):
                raise
            return outline_data

    def _build_repair_prompt(self, outline_data: Dict[str, Any], validation_errors: List[str], confirmed_requirements: Dict[str, Any]) -> str:
        """构建AI修复提示词"""
        return prompts_manager.get_repair_prompt(outline_data, validation_errors, confirmed_requirements)

    @staticmethod
    def _outline_signature(outline_data: Optional[Dict[str, Any]]) -> Optional[tuple]:
        """Identity of the slide plan that generated slides were built from."""
        if not isinstance(outline_data, dict):
            return None
        slides = outline_data.get('slides')
        if not isinstance(slides, list):
            return None
        titles = []
        for slide in slides:
            if isinstance(slide, dict):
                titles.append(str(slide.get('title', '')))
            else:
                titles.append(str(slide))
        return (len(slides), tuple(titles))

    async def _invalidate_slides_for_new_outline(self, project_id: str, db_manager) -> None:
        """Drop slides and reset ppt_creation after the outline plan changed.

        Without this the slide-generation skip check sees the old slides as
        "already generated" and replays the previous deck against the new outline.
        """
        try:
            cleared = await db_manager.clear_project_slides(project_id)
            if not cleared:
                logger.error(
                    'Failed to clear stale slides for project %s after outline change',
                    project_id
                )
                return
            await db_manager.update_stage_status(
                project_id, 'ppt_creation', 'pending', 0.0, None
            )
            logger.info(
                'Cleared stale slides and reset ppt_creation for project %s '
                '(outline plan changed)', project_id
            )
        except Exception as invalidate_error:
            logger.error(
                'Error invalidating slides after outline change for %s: %s',
                project_id, invalidate_error
            )

    async def _update_outline_generation_stage(self, project_id: str, outline_data: Dict[str, Any]):
        """Update outline generation stage status and save to database"""
        try:
            from ..db_project_manager import DatabaseProjectManager
            db_manager = DatabaseProjectManager()
            project = await self.project_manager.get_project(project_id)
            if not project:
                logger.error(f'❌ Project not found in memory for project {project_id}')
                return
            previous_signature = self._outline_signature(project.outline)
            new_signature = self._outline_signature(outline_data)
            outline_plan_changed = (
                previous_signature is not None
                and new_signature is not None
                and previous_signature != new_signature
            )
            if not project.outline:
                logger.info(f'Project outline is None, setting outline from outline_data')
                project.outline = outline_data
                project.updated_at = time.time()
            save_success = await db_manager.save_project_outline(project_id, outline_data)
            if save_success:
                logger.info(f'✅ Successfully saved outline to database for project {project_id}')
                saved_project = await db_manager.get_project(project_id)
                if saved_project and saved_project.outline:
                    saved_slides_count = len(saved_project.outline.get('slides', []))
                    logger.info(f'✅ Verified: outline saved with {saved_slides_count} slides')
                    project.outline = saved_project.outline
                    project.updated_at = saved_project.updated_at
                    logger.info(f'✅ Updated memory project with database outline')
                else:
                    logger.error(f'❌ Verification failed: outline not found in database')
            else:
                logger.error(f'❌ Failed to save outline to database for project {project_id}')
            await self.project_manager.update_project_status(project_id, 'in_progress')
            if outline_plan_changed:
                await self._invalidate_slides_for_new_outline(project_id, db_manager)
                if project.todo_board:
                    for stage in project.todo_board.stages:
                        if stage.id == 'ppt_creation':
                            stage.status = 'pending'
                            stage.progress = 0.0
                            stage.result = None
                            break
            if project.todo_board:
                for stage in project.todo_board.stages:
                    if stage.id == 'outline_generation':
                        stage.status = 'completed'
                        stage.result = {'outline_data': outline_data}
                        break
                await self.project_manager.update_stage_status(project_id, 'outline_generation', 'completed', progress=100.0, result={'outline_data': outline_data})
        except Exception as e:
            logger.error(f'Error updating outline generation stage: {str(e)}')
            import traceback
            traceback.print_exc()
