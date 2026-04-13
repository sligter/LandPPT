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
    from .slide_html_service import SlideHtmlService

class SlideContentService:
    """Extracted logic from SlideHtmlService."""

    def __init__(self, service: 'SlideHtmlService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def generate_slides_parallel(self, slide_requests: List[Dict[str, Any]], scenario: str, topic: str, language: str='zh') -> List[str]:
        """并行生成多个幻灯片内容
                
                Args:
                    slide_requests: 幻灯片请求列表，每个包含slide_title等信息
                    scenario: 场景
                    topic: 主题
                    language: 语言
                    
                Returns:
                    生成的幻灯片内容列表
                """
        try:
            if not ai_config.enable_parallel_generation:
                results = []
                for req in slide_requests:
                    content = await self.generate_slide_content(req.get('slide_title', req.get('title', '')), scenario, topic, language)
                    results.append(content)
                return results
            tasks = []
            for req in slide_requests:
                task = self.generate_slide_content(req.get('slide_title', req.get('title', '')), scenario, topic, language)
                tasks.append(task)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f'生成第 {i + 1} 个幻灯片时出错: {str(result)}')
                    slide_title = slide_requests[i].get('slide_title', slide_requests[i].get('title', ''))
                    processed_results.append(f'• {slide_title}的相关内容\n• 详细说明和分析\n• 实际应用案例')
                else:
                    processed_results.append(result)
            logger.info(f'并行生成完成：成功生成 {len([r for r in results if not isinstance(r, Exception)])} / {len(results)} 个幻灯片')
            return processed_results
        except Exception as e:
            logger.error(f'并行生成幻灯片失败: {str(e)}')
            results = []
            for req in slide_requests:
                try:
                    content = await self.generate_slide_content(req.get('slide_title', req.get('title', '')), scenario, topic, language)
                    results.append(content)
                except Exception as slide_error:
                    logger.error(f'生成幻灯片失败: {str(slide_error)}')
                    slide_title = req.get('slide_title', req.get('title', ''))
                    results.append(f'• {slide_title}的相关内容\n• 详细说明和分析\n• 实际应用案例')
            return results

    async def generate_slide_content(self, slide_title: str, scenario: str, topic: str, language: str='zh') -> str:
        """Generate slide content using AI"""
        try:
            prompt = self._create_slide_content_prompt(slide_title, scenario, topic, language)
            response = await self._text_completion_for_role('slide_generation', prompt=prompt, temperature=ai_config.temperature)
            return response.content.strip()
        except Exception as e:
            logger.error(f'Error generating slide content: {str(e)}')
            return self._generate_slide_content(topic, slide_title, scenario, language)

    async def enhance_content_with_ai(self, content: str, scenario: str, language: str='zh') -> str:
        """Enhance existing content using AI"""
        try:
            prompt = self._create_enhancement_prompt(content, scenario, language)
            response = await self._text_completion_for_role('outline', prompt=prompt, temperature=max(ai_config.temperature - 0.1, 0.1))
            return response.content.strip()
        except Exception as e:
            logger.error(f'Error enhancing content: {str(e)}')
            return content

    async def _execute_general_subtask(self, project_id: str, stage, subtask: str, confirmed_requirements: Dict[str, Any], system_prompt: str) -> str:
        """Execute general subtask"""
        context = prompts_manager.get_general_subtask_prompt(confirmed_requirements=confirmed_requirements, stage_name=stage.name, subtask=subtask)
        response = await self._text_completion_for_role('default', prompt=context, system_prompt=system_prompt, temperature=ai_config.temperature)
        return response.content

    async def _design_theme(self, scenario: str, language: str) -> Dict[str, Any]:
        """Design theme configuration based on scenario"""
        theme_configs = {'general': {'primary_color': '#3498db', 'secondary_color': '#2c3e50', 'accent_color': '#e74c3c', 'background': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', 'font_family': 'Arial, sans-serif', 'style': 'professional'}, 'tourism': {'primary_color': '#27ae60', 'secondary_color': '#16a085', 'accent_color': '#f39c12', 'background': 'linear-gradient(135deg, #74b9ff 0%, #0984e3 100%)', 'font_family': 'Georgia, serif', 'style': 'vibrant'}, 'education': {'primary_color': '#9b59b6', 'secondary_color': '#8e44ad', 'accent_color': '#f1c40f', 'background': 'linear-gradient(135deg, #a29bfe 0%, #6c5ce7 100%)', 'font_family': 'Comic Sans MS, cursive', 'style': 'playful'}, 'analysis': {'primary_color': '#34495e', 'secondary_color': '#2c3e50', 'accent_color': '#e67e22', 'background': 'linear-gradient(135deg, #636e72 0%, #2d3436 100%)', 'font_family': 'Helvetica, sans-serif', 'style': 'analytical'}, 'history': {'primary_color': '#8b4513', 'secondary_color': '#a0522d', 'accent_color': '#daa520', 'background': 'linear-gradient(135deg, #d63031 0%, #74b9ff 100%)', 'font_family': 'Times New Roman, serif', 'style': 'classical'}, 'technology': {'primary_color': '#6c5ce7', 'secondary_color': '#a29bfe', 'accent_color': '#00cec9', 'background': 'linear-gradient(135deg, #00cec9 0%, #6c5ce7 100%)', 'font_family': 'Roboto, sans-serif', 'style': 'modern'}, 'business': {'primary_color': '#1f4e79', 'secondary_color': '#2980b9', 'accent_color': '#f39c12', 'background': 'linear-gradient(135deg, #2980b9 0%, #1f4e79 100%)', 'font_family': 'Arial, sans-serif', 'style': 'corporate'}}
        return theme_configs.get(scenario, theme_configs['general'])

    def _normalize_slide_type(self, slide_type: str) -> str:
        """Normalize slide type to supported values"""
        type_mapping = {'agenda': 'agenda', 'section': 'section', 'conclusion': 'conclusion', 'thankyou': 'thankyou', 'title': 'title', 'content': 'content', 'image': 'image', 'chart': 'chart', 'list': 'list', 'overview': 'content', 'summary': 'conclusion', 'intro': 'content', 'ending': 'thankyou'}
        return type_mapping.get(slide_type, 'content')

    async def _generate_enhanced_content(self, outline: PPTOutline, request: PPTGenerationRequest) -> List[SlideContent]:
        """Generate enhanced content for each slide"""
        enhanced_slides = []
        for i, slide_data in enumerate(outline.slides):
            try:
                content = await self.generate_slide_content(slide_data['title'], request.scenario, request.topic, request.language)
                slide_content = SlideContent(type=self._normalize_slide_type(slide_data.get('type', 'content')), title=slide_data['title'], subtitle=slide_data.get('subtitle', ''), content=content, bullet_points=self._extract_bullet_points(content), image_suggestions=await self._suggest_images(slide_data['title'], request.scenario, content, request.topic, i + 1, len(outline.slides)), layout='default')
                enhanced_slides.append(slide_content)
            except Exception as e:
                logger.error(f"Error generating content for slide {slide_data['title']}: {e}")
                slide_content = SlideContent(type=self._normalize_slide_type(slide_data.get('type', 'content')), title=slide_data['title'], subtitle=slide_data.get('subtitle', ''), content=slide_data.get('content', ''), layout='default')
                enhanced_slides.append(slide_content)
        return enhanced_slides

    async def _verify_layout(self, slides: List[SlideContent], theme_config: Dict[str, Any]) -> List[SlideContent]:
        """Verify and optimize slide layouts"""
        verified_slides = []
        for slide in slides:
            verified_slide = SlideContent(**slide.model_dump())
            if slide.type == 'title':
                verified_slide.layout = 'title_layout'
            elif slide.type == 'agenda':
                verified_slide.layout = 'agenda_layout'
            elif slide.type == 'section':
                verified_slide.layout = 'section_layout'
            elif slide.type == 'conclusion':
                verified_slide.layout = 'conclusion_layout'
            elif slide.type == 'thankyou':
                verified_slide.layout = 'thankyou_layout'
            elif slide.type == 'content' and slide.bullet_points:
                verified_slide.layout = 'bullet_layout'
            elif slide.type == 'content' and slide.image_suggestions:
                verified_slide.layout = 'image_content_layout'
            elif slide.type == 'list':
                verified_slide.layout = 'list_layout'
            elif slide.type == 'chart':
                verified_slide.layout = 'chart_layout'
            elif slide.type == 'image':
                verified_slide.layout = 'image_layout'
            else:
                verified_slide.layout = 'default_layout'
            if verified_slide.content and len(verified_slide.content) > 500:
                verified_slide.content = verified_slide.content[:500] + '...'
            verified_slides.append(verified_slide)
        return verified_slides

    async def _generate_html_output(self, slides: List[SlideContent], theme_config: Dict[str, Any]) -> str:
        """Generate HTML output for slides"""
        try:
            slides_dict = []
            for i, slide in enumerate(slides):
                slide_dict = {'id': i + 1, 'type': slide.type, 'title': slide.title, 'subtitle': slide.subtitle or '', 'content': slide.content or '', 'bullet_points': slide.bullet_points or [], 'layout': slide.layout}
                slides_dict.append(slide_dict)
            from ...api.models import PPTOutline
            temp_outline = PPTOutline(title='Generated PPT', slides=slides_dict, metadata={'theme_config': theme_config})
            html_content = await self.generate_slides_from_outline(temp_outline, 'general')
            return html_content
        except Exception as e:
            logger.error(f'Error generating HTML output: {e}')
            return self._generate_basic_html(slides, theme_config)

    def _extract_bullet_points(self, content: str) -> List[str]:
        """Extract bullet points from content"""
        if not content:
            return []
        bullet_points = []
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('•') or line.startswith('-') or line.startswith('*'):
                bullet_points.append(line[1:].strip())
            elif re.match('^\\d+\\.', line):
                bullet_points.append(line.split('.', 1)[1].strip())
        return bullet_points[:5]
