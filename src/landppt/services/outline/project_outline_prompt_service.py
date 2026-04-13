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
    from .project_outline_creation_service import ProjectOutlineCreationService

class ProjectOutlinePromptService:
    """Extracted logic from ProjectOutlineCreationService."""

    def __init__(self, service: 'ProjectOutlineCreationService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _create_outline_prompt(self, request: PPTGenerationRequest, research_context: str='', page_count_settings: Dict[str, Any]=None) -> str:
        """Create prompt for AI outline generation - Enhanced with professional templates"""
        language = getattr(request, 'language', None) or 'zh'
        if language == 'en':
            scenario_descriptions = {'general': 'General Presentation', 'tourism': 'Tourism and Travel Introduction', 'education': 'Educational Science for Children', 'analysis': 'In-depth Data Analysis', 'history': 'Historical and Cultural Topics', 'technology': 'Technology Showcase', 'business': 'Business Proposal Report'}
            default_scenario = 'General Presentation'
        else:
            scenario_descriptions = {'general': '通用演示', 'tourism': '旅游观光介绍', 'education': '儿童科普教育', 'analysis': '深入数据分析', 'history': '历史文化主题', 'technology': '科技技术展示', 'business': '方案汇报'}
            default_scenario = '通用演示'
        scenario_desc = scenario_descriptions.get(request.scenario, default_scenario)
        page_count_instruction = ''
        expected_page_count = 10
        if page_count_settings:
            page_count_mode = page_count_settings.get('mode', 'ai_decide')
            if page_count_mode == 'custom_range':
                min_pages = page_count_settings.get('min_pages', 8)
                max_pages = page_count_settings.get('max_pages', 15)
                if language == 'en':
                    page_count_instruction = f'- Page Count: Must strictly generate a PPT with {min_pages}-{max_pages} pages'
                else:
                    page_count_instruction = f'- 页数要求：必须严格生成{min_pages}-{max_pages}页的PPT，确保页数在此范围内'
                expected_page_count = max_pages
            elif page_count_mode == 'fixed':
                fixed_pages = page_count_settings.get('fixed_pages', 10)
                if language == 'en':
                    page_count_instruction = f'- Page Count: Must generate exactly {fixed_pages} pages'
                else:
                    page_count_instruction = f'- 页数要求：必须生成恰好{fixed_pages}页的PPT'
                expected_page_count = fixed_pages
            else:
                if language == 'en':
                    page_count_instruction = '- Page Count: Determine appropriate page count based on content complexity'
                else:
                    page_count_instruction = '- 页数要求：根据内容复杂度自主决定合适的页数'
                expected_page_count = 12
        else:
            if language == 'en':
                page_count_instruction = '- Page Count: Determine appropriate page count based on content complexity'
            else:
                page_count_instruction = '- 页数要求：根据内容复杂度自主决定合适的页数'
            expected_page_count = 12
        logger.debug(f'Page count instruction: {page_count_instruction}')
        research_section = ''
        if research_context:
            if language == 'en':
                research_section = f'\n\n    Background information based on in-depth research:\n    {research_context}\n\n    Please fully utilize the above research information to enrich the PPT content, ensuring accuracy, authority, and depth.'
            else:
                research_section = f'\n\n    基于深度研究的背景信息：\n    {research_context}\n\n    请充分利用以上研究信息来丰富PPT内容，确保信息准确、权威、具有深度。'
        if language == 'en':
            default_audience = 'General Public'
        else:
            default_audience = '普通大众'
        target_audience = getattr(request, 'target_audience', None) or default_audience
        ppt_style = getattr(request, 'ppt_style', None) or 'general'
        custom_style_prompt = getattr(request, 'custom_style_prompt', None)
        description = getattr(request, 'description', None)
        if language == 'en':
            style_descriptions = {'general': 'General style, detailed and professional', 'conference': 'Academic conference style, rigorous and formal', 'custom': custom_style_prompt or 'Custom style'}
            default_style = 'General style'
        else:
            style_descriptions = {'general': '通用风格，详细专业', 'conference': '学术会议风格，严谨正式', 'custom': custom_style_prompt or '自定义风格'}
            default_style = '通用风格'
        style_desc = style_descriptions.get(ppt_style, default_style)
        if custom_style_prompt and ppt_style != 'custom':
            style_desc += f'，{custom_style_prompt}' if language == 'zh' else f', {custom_style_prompt}'
        if request.language == 'zh':
            return prompts_manager.get_outline_prompt_zh(topic=request.topic, scenario_desc=scenario_desc, target_audience=target_audience, style_desc=style_desc, requirements=request.requirements or '', description=description or '', research_section=research_section, page_count_instruction=page_count_instruction, expected_page_count=expected_page_count, language=language or 'zh')
        else:
            return prompts_manager.get_outline_prompt_en(topic=request.topic, scenario_desc=scenario_desc, target_audience=target_audience, style_desc=style_desc, requirements=request.requirements or '', description=description or '', research_section=research_section, page_count_instruction=page_count_instruction, expected_page_count=expected_page_count, language=language or 'en')

    def _parse_ai_outline(self, ai_response: str, request: PPTGenerationRequest) -> PPTOutline:
        """Parse AI response to create structured outline"""
        try:
            standardized_data = self._parse_outline_content(
                ai_response,
                PPTProject(
                    project_id="outline-parse",
                    title=request.topic,
                    scenario=request.scenario,
                    topic=request.topic,
                ),
            )
            metadata = standardized_data.get('metadata', {})
            metadata.update({
                'scenario': request.scenario,
                'language': request.language,
                'total_slides': len(standardized_data.get('slides', [])),
                'generated_with_ai': True,
                'ai_provider': self.provider_name,
            })
            return PPTOutline(
                title=standardized_data.get('title', request.topic),
                slides=standardized_data.get('slides', []),
                metadata=metadata,
            )
        except Exception as e:
            logger.error(f'Error parsing AI outline: {str(e)}')
            raise Exception(f'AI生成的大纲格式无效，无法解析：{str(e)}')

    def _create_default_slides(self, title: str, request: PPTGenerationRequest) -> List[Dict[str, Any]]:
        """Create default slide structure when AI parsing fails (legacy format)"""
        return [{'id': 1, 'type': 'title', 'title': title, 'subtitle': '专业演示' if request.language == 'zh' else 'Professional Presentation', 'content': ''}, {'id': 2, 'type': 'agenda', 'title': '目录' if request.language == 'zh' else 'Agenda', 'subtitle': '', 'content': '• 主要内容概览\n• 核心要点分析\n• 总结与展望'}, {'id': 3, 'type': 'content', 'title': '主要内容' if request.language == 'zh' else 'Main Content', 'subtitle': '', 'content': f'• 关于{title}的核心要点\n• 详细分析和说明\n• 实际应用案例'}, {'id': 4, 'type': 'thankyou', 'title': '谢谢' if request.language == 'zh' else 'Thank You', 'subtitle': '感谢聆听' if request.language == 'zh' else 'Thank you for your attention', 'content': ''}]

    def _create_default_slides_compatible(self, title: str, request: PPTGenerationRequest) -> List[Dict[str, Any]]:
        """Create default slide structure compatible with file generation format"""
        return [{'page_number': 1, 'title': title, 'content_points': ['专业演示' if request.language == 'zh' else 'Professional Presentation'], 'slide_type': 'title', 'type': 'title', 'description': 'PPT标题页'}, {'page_number': 2, 'title': '目录' if request.language == 'zh' else 'Agenda', 'content_points': ['主要内容概览', '核心要点分析', '总结与展望'], 'slide_type': 'agenda', 'type': 'agenda', 'description': 'PPT目录页'}, {'page_number': 3, 'title': '主要内容' if request.language == 'zh' else 'Main Content', 'content_points': [f'关于{title}的核心要点', '详细分析和说明', '实际应用案例'], 'slide_type': 'content', 'type': 'content', 'description': '主要内容页'}, {'page_number': 4, 'title': '谢谢' if request.language == 'zh' else 'Thank You', 'content_points': ['感谢聆听' if request.language == 'zh' else 'Thank you for your attention'], 'slide_type': 'thankyou', 'type': 'thankyou', 'description': 'PPT结束页'}]

    def _create_default_outline(self, request: PPTGenerationRequest) -> PPTOutline:
        """Create default outline when AI generation fails"""
        slides = self._create_default_slides(request.topic, request)
        return PPTOutline(title=request.topic, slides=slides, metadata={'scenario': request.scenario, 'language': request.language, 'total_slides': len(slides), 'generated_with_ai': False, 'fallback_used': True})
