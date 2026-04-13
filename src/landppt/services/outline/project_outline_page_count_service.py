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
    from .project_outline_generation_service import ProjectOutlineGenerationService

class ProjectOutlinePageCountService:
    """Extracted logic from ProjectOutlineGenerationService."""

    def __init__(self, service: 'ProjectOutlineGenerationService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _execute_outline_generation(self, project_id: str, confirmed_requirements: Dict[str, Any], system_prompt: str) -> str:
        """Execute outline generation as a complete task"""
        try:
            project = await self.project_manager.get_project(project_id)
            existing_outline = project.outline if project and isinstance(project.outline, dict) else None
            existing_slides = existing_outline.get('slides', []) if existing_outline else []
            if existing_slides:
                logger.info('Project %s already has outline with %s slides, reusing existing outline', project_id, len(existing_slides))
                try:
                    await self._update_outline_generation_stage(project_id, existing_outline)
                except Exception as stage_error:
                    logger.warning('Failed to mark reused outline generation stage as completed for project %s: %s', project_id, stage_error)
                return f"✅ PPT大纲已存在，跳过重复生成。\n\n标题：{existing_outline.get('title', confirmed_requirements.get('topic', '未知'))}\n页数：{len(existing_slides)}页\n已复用现有大纲"

            page_count_settings = confirmed_requirements.get('page_count_settings', {})
            page_count_mode = page_count_settings.get('mode', 'ai_decide')
            page_count_instruction = ''
            expected_page_count = None
            if page_count_mode == 'custom_range':
                min_pages = page_count_settings.get('min_pages', 8)
                max_pages = page_count_settings.get('max_pages', 15)
                page_count_instruction = f'- 页数要求：必须严格生成{min_pages}-{max_pages}页的PPT。请确保生成的幻灯片数量在此范围内，不能超出或不足。'
                expected_page_count = {'min': min_pages, 'max': max_pages, 'mode': 'range'}
                logger.info(f'Custom page count range set: {min_pages}-{max_pages} pages')
            else:
                page_count_instruction = '- 页数要求：请根据主题内容的复杂度、深度和逻辑结构，自主决定最合适的页数，确保内容充实且逻辑清晰'
                expected_page_count = {'mode': 'ai_decide'}
                logger.info('AI decide mode set for page count')
            topic = confirmed_requirements['topic']
            target_audience = confirmed_requirements.get('target_audience', '普通大众')
            ppt_style = confirmed_requirements.get('ppt_style', 'general')
            custom_style = confirmed_requirements.get('custom_style_prompt', '无')
            description = confirmed_requirements.get('description', '无')
            context = prompts_manager.get_outline_generation_context(topic=topic, target_audience=target_audience, page_count_instruction=page_count_instruction, ppt_style=ppt_style, custom_style=custom_style, description=description, page_count_mode=page_count_mode)
            response = await self._text_completion_for_role('outline', prompt=context, system_prompt=system_prompt, temperature=ai_config.temperature)
            import json
            import re
            try:
                content = response.content.strip()
                json_str = None
                json_block_match = re.search('```json\\s*(\\{.*?\\})\\s*```', content, re.DOTALL)
                if json_block_match:
                    json_str = json_block_match.group(1)
                    logger.info('从```json```代码块中提取JSON')
                else:
                    code_block_match = re.search('```\\s*(\\{.*?\\})\\s*```', content, re.DOTALL)
                    if code_block_match:
                        json_str = code_block_match.group(1)
                        logger.info('从```代码块中提取JSON')
                    else:
                        json_match = re.search('\\{[^{}]*(?:\\{[^{}]*\\}[^{}]*)*\\}', content, re.DOTALL)
                        if json_match:
                            json_str = json_match.group()
                            logger.info('使用正则表达式提取JSON')
                        else:
                            json_str = content
                            logger.info('将整个响应内容作为JSON处理')
                if json_str:
                    json_str = json_str.strip()
                    json_str = re.sub(',\\s*}', '}', json_str)
                    json_str = re.sub(',\\s*]', ']', json_str)
                outline_data = json.loads(json_str)
                outline_data = await self._validate_and_repair_outline_json(outline_data, confirmed_requirements)
                if expected_page_count and 'slides' in outline_data:
                    actual_page_count = len(outline_data['slides'])
                    logger.info(f'Generated outline has {actual_page_count} pages')
                    if expected_page_count['mode'] == 'range':
                        min_pages = expected_page_count['min']
                        max_pages = expected_page_count['max']
                        if actual_page_count < min_pages or actual_page_count > max_pages:
                            logger.warning(f'Generated outline has {actual_page_count} pages, but expected {min_pages}-{max_pages} pages. Adjusting...')
                            outline_data = await self._adjust_outline_page_count(outline_data, min_pages, max_pages, confirmed_requirements)
                            adjusted_page_count = len(outline_data.get('slides', []))
                            logger.info(f'Adjusted outline to {adjusted_page_count} pages')
                            if adjusted_page_count < min_pages or adjusted_page_count > max_pages:
                                logger.error(f'Failed to adjust page count to required range {min_pages}-{max_pages}')
                                target_pages = (min_pages + max_pages) // 2
                                outline_data = await self._force_page_count(outline_data, target_pages, confirmed_requirements)
                        else:
                            logger.info(f'Page count {actual_page_count} is within required range {min_pages}-{max_pages}')
                    if 'metadata' not in outline_data:
                        outline_data['metadata'] = {}
                    outline_data['metadata']['page_count_settings'] = expected_page_count
                    outline_data['metadata']['actual_page_count'] = len(outline_data.get('slides', []))
                project = await self.project_manager.get_project(project_id)
                if project:
                    project.outline = outline_data
                    project.updated_at = time.time()
                    logger.info(f'Successfully saved outline to memory for project {project_id}')
                try:
                    from ..db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()
                    save_success = await db_manager.save_project_outline(project_id, outline_data)
                    if save_success:
                        logger.info(f'✅ Successfully saved outline to database for project {project_id}')
                        saved_project = await db_manager.get_project(project_id)
                        if saved_project and saved_project.outline:
                            saved_slides_count = len(saved_project.outline.get('slides', []))
                            logger.info(f'✅ Verified: outline saved with {saved_slides_count} slides')
                        else:
                            logger.error(f'❌ Verification failed: outline not found in database')
                            return f'❌ 大纲保存失败：数据库验证失败'
                    else:
                        logger.error(f'❌ Failed to save outline to database for project {project_id}')
                        return f'❌ 大纲保存失败：数据库写入失败'
                except Exception as save_error:
                    logger.error(f'❌ Exception while saving outline to database: {save_error}')
                    import traceback
                    traceback.print_exc()
                    return f'❌ 大纲保存失败：{str(save_error)}'
                try:
                    from ..db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()
                    await db_manager.update_stage_status(project_id, 'outline_generation', 'completed', 100.0, {'outline_title': outline_data.get('title', '未知'), 'slides_count': len(outline_data.get('slides', [])), 'completed_at': time.time()})
                    logger.info(f'Successfully updated outline generation stage to completed for project {project_id}')
                except Exception as stage_error:
                    logger.error(f'Failed to update outline generation stage status: {stage_error}')
                final_page_count = len(outline_data.get('slides', []))
                return f"✅ PPT大纲生成完成！\n\n标题：{outline_data.get('title', '未知')}\n页数：{final_page_count}页\n已保存到数据库\n\n{response.content}"
            except Exception as e:
                logger.error(f'Error parsing outline JSON: {e}')
                logger.error(f'Response content: {response.content[:500]}...')
                try:
                    fallback_outline = {'title': confirmed_requirements.get('topic', 'AI生成的PPT大纲'), 'slides': [{'page_number': 1, 'title': confirmed_requirements.get('topic', '标题页'), 'content_points': ['项目介绍', '主要内容', '核心价值'], 'slide_type': 'title'}, {'page_number': 2, 'title': '主要内容', 'content_points': ['内容要点1', '内容要点2', '内容要点3'], 'slide_type': 'content'}, {'page_number': 3, 'title': '谢谢观看', 'content_points': ['感谢聆听', '欢迎提问'], 'slide_type': 'thankyou'}]}
                    fallback_outline = await self._validate_and_repair_outline_json(fallback_outline, confirmed_requirements)
                    project = await self.project_manager.get_project(project_id)
                    if project:
                        project.outline = fallback_outline
                        project.updated_at = time.time()
                        logger.info(f'Saved fallback outline for project {project_id}')
                    try:
                        from ..db_project_manager import DatabaseProjectManager
                        db_manager = DatabaseProjectManager()
                        save_success = await db_manager.save_project_outline(project_id, fallback_outline)
                        if save_success:
                            logger.info(f'Successfully saved fallback outline to database for project {project_id}')
                        else:
                            logger.error(f'Failed to save fallback outline to database for project {project_id}')
                    except Exception as save_error:
                        logger.error(f'Exception while saving fallback outline to database: {save_error}')
                    final_page_count = len(fallback_outline.get('slides', []))
                    return f"✅ PPT大纲生成完成！（使用备用方案）\n\n标题：{fallback_outline.get('title', '未知')}\n页数：{final_page_count}页\n已保存到数据库"
                except Exception as fallback_error:
                    logger.error(f'Error creating fallback outline: {fallback_error}')
                    return f'❌ 大纲生成失败：{str(e)}\n\n{response.content}'
        except Exception as e:
            logger.error(f'Error in outline generation: {e}')
            raise

    async def _adjust_outline_page_count(self, outline_data: Dict[str, Any], min_pages: int, max_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Adjust outline page count to meet requirements"""
        try:
            current_slides = outline_data.get('slides', [])
            current_count = len(current_slides)
            if current_count < min_pages:
                logger.info(f'Adding slides to meet minimum requirement: {current_count} -> {min_pages}')
                outline_data = await self._expand_outline(outline_data, min_pages, confirmed_requirements)
            elif current_count > max_pages:
                logger.info(f'Reducing slides to meet maximum requirement: {current_count} -> {max_pages}')
                outline_data = await self._condense_outline(outline_data, max_pages)
            return outline_data
        except Exception as e:
            logger.error(f'Error adjusting outline page count: {e}')
            return outline_data

    async def _expand_outline(self, outline_data: Dict[str, Any], target_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Expand outline to reach target page count"""
        try:
            slides = outline_data.get('slides', [])
            current_count = len(slides)
            needed_slides = target_pages - current_count
            topic = confirmed_requirements.get('topic', outline_data.get('title', ''))
            focus_content = confirmed_requirements.get('focus_content', [])
            conclusion_slide = None
            if slides and slides[-1].get('slide_type') in ['thankyou', 'conclusion']:
                conclusion_slide = slides.pop()
            for i in range(needed_slides):
                page_number = len(slides) + 1
                if i < len(focus_content):
                    new_slide = {'page_number': page_number, 'title': focus_content[i], 'content_points': [f'{focus_content[i]}的详细介绍', '核心要点', '实际应用'], 'slide_type': 'content', 'description': f'详细介绍{focus_content[i]}相关内容'}
                else:
                    new_slide = {'page_number': page_number, 'title': f'{topic} - 补充内容 {i + 1}', 'content_points': ['补充要点1', '补充要点2', '补充要点3'], 'slide_type': 'content', 'description': f'关于{topic}的补充内容'}
                slides.append(new_slide)
            if conclusion_slide:
                conclusion_slide['page_number'] = len(slides) + 1
                slides.append(conclusion_slide)
            for i, slide in enumerate(slides):
                slide['page_number'] = i + 1
            outline_data['slides'] = slides
            return outline_data
        except Exception as e:
            logger.error(f'Error expanding outline: {e}')
            return outline_data

    async def _condense_outline(self, outline_data: Dict[str, Any], target_pages: int) -> Dict[str, Any]:
        """Condense outline to reach target page count"""
        try:
            slides = outline_data.get('slides', [])
            current_count = len(slides)
            if current_count <= target_pages:
                return outline_data
            title_slides = [s for s in slides if s.get('slide_type') in ['title', 'cover']]
            conclusion_slides = [s for s in slides if s.get('slide_type') in ['thankyou', 'conclusion']]
            content_slides = [s for s in slides if s.get('slide_type') not in ['title', 'cover', 'thankyou', 'conclusion']]
            reserved_slots = len(title_slides) + len(conclusion_slides)
            available_content_slots = target_pages - reserved_slots
            if available_content_slots > 0 and len(content_slides) > available_content_slots:
                content_slides = content_slides[:available_content_slots]
            new_slides = title_slides + content_slides + conclusion_slides
            for i, slide in enumerate(new_slides):
                slide['page_number'] = i + 1
            outline_data['slides'] = new_slides
            return outline_data
        except Exception as e:
            logger.error(f'Error condensing outline: {e}')
            return outline_data

    async def _force_page_count(self, outline_data: Dict[str, Any], target_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Force outline to exact page count"""
        try:
            slides = outline_data.get('slides', [])
            current_count = len(slides)
            logger.info(f'Forcing page count from {current_count} to {target_pages}')
            if current_count == target_pages:
                return outline_data
            title_slides = [s for s in slides if s.get('slide_type') in ['title', 'cover']]
            conclusion_slides = [s for s in slides if s.get('slide_type') in ['thankyou', 'conclusion']]
            content_slides = [s for s in slides if s.get('slide_type') not in ['title', 'cover', 'thankyou', 'conclusion']]
            reserved_slots = len(title_slides) + len(conclusion_slides)
            content_slots_needed = target_pages - reserved_slots
            if content_slots_needed <= 0:
                new_slides = title_slides[:1] if title_slides else []
            else:
                if len(content_slides) > content_slots_needed:
                    content_slides = content_slides[:content_slots_needed]
                elif len(content_slides) < content_slots_needed:
                    topic = confirmed_requirements.get('topic', outline_data.get('title', ''))
                    focus_content = confirmed_requirements.get('focus_content', [])
                    for i in range(content_slots_needed - len(content_slides)):
                        page_number = len(content_slides) + i + 1
                        if i < len(focus_content):
                            new_slide = {'page_number': page_number, 'title': focus_content[i], 'content_points': [f'{focus_content[i]}的详细介绍', '核心要点', '实际应用'], 'slide_type': 'content', 'description': f'详细介绍{focus_content[i]}相关内容'}
                        else:
                            new_slide = {'page_number': page_number, 'title': f'{topic} - 内容 {i + 1}', 'content_points': ['要点1', '要点2', '要点3'], 'slide_type': 'content', 'description': f'关于{topic}的内容'}
                        content_slides.append(new_slide)
                new_slides = title_slides + content_slides + conclusion_slides
            for i, slide in enumerate(new_slides):
                slide['page_number'] = i + 1
            outline_data['slides'] = new_slides
            logger.info(f'Successfully forced page count to {len(new_slides)} pages')
            return outline_data
        except Exception as e:
            logger.error(f'Error forcing page count: {e}')
            return outline_data
