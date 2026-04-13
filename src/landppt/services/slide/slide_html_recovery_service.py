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
    from .slide_html_validation_service import SlideHtmlValidationService

class SlideHtmlRecoveryService:
    """Extracted logic from SlideHtmlValidationService."""

    def __init__(self, service: 'SlideHtmlValidationService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _generate_html_with_retry(self, context: str, system_prompt: str, slide_data: Dict[str, Any], page_number: int, total_pages: int, max_retries: int=3) -> str:
        """Generate HTML with retry mechanism for incomplete responses"""
        for attempt in range(max_retries):
            try:
                logger.info(f'Generating HTML for slide {page_number}, attempt {attempt + 1}/{max_retries}')
                retry_context = context
                if attempt > 0:
                    retry_context += f'\n\n    **重要提醒（第{attempt + 1}次尝试）：**\n    - 前面的尝试可能生成了不完整的HTML，请确保这次生成完整的HTML文档\n    - 必须包含完整的HTML结构：<!DOCTYPE html>, <html>, <head>, <body>等标签\n    - 确保所有标签都正确闭合\n    - 使用markdown代码块格式：```html\n[完整HTML代码]\n```\n    - 不要截断HTML代码，确保以</html>结束\n    '
                response = await self._text_completion_for_role('slide_generation', prompt=retry_context, system_prompt=system_prompt, temperature=max(0.1, ai_config.temperature))
                try:
                    html_content = self._clean_html_response(response.content)
                    html_content = self._inject_anti_overflow_css(html_content)
                    if not html_content or len(html_content.strip()) < 50:
                        logger.warning(f'AI returned empty or too short HTML content for slide {page_number}')
                        continue
                except Exception as e:
                    logger.error(f'Error cleaning HTML response for slide {page_number}: {e}')
                    continue
                validation_result = self._validate_html_completeness(html_content)
                logger.info(f"HTML validation result for slide {page_number}, attempt {attempt + 1}: Complete: {validation_result['is_complete']}, Errors: {len(validation_result['errors'])}, Missing elements: {len(validation_result['missing_elements'])}")
                if validation_result['is_complete']:
                    if validation_result['missing_elements']:
                        logger.warning(f"Missing elements (warnings only): {', '.join(validation_result['missing_elements'])}")
                    logger.info(f'Successfully generated complete HTML for slide {page_number} on attempt {attempt + 1}')
                    return await self._apply_auto_layout_repair(html_content, slide_data, page_number, total_pages)
                else:
                    if validation_result['missing_elements']:
                        logger.warning(f"Missing elements (warnings only): {', '.join(validation_result['missing_elements'])}")
                    if validation_result['errors']:
                        logger.error(f"Validation errors: {'; '.join(validation_result['errors'])}")
                    if validation_result['errors']:
                        logger.info(f'🔧 Attempting automatic parser fix for slide {page_number}')
                        parser_fixed_html = self._auto_fix_html_with_parser(html_content)
                        if parser_fixed_html != html_content:
                            logger.info(f'✅ Successfully fixed HTML with parser for slide {page_number}, returning fixed result')
                            return await self._apply_auto_layout_repair(parser_fixed_html, slide_data, page_number, total_pages)
                        else:
                            logger.info(f'🔧 Parser did not change HTML for slide {page_number}')
                        if attempt < max_retries - 1:
                            logger.info(f'🔄 HTML has errors after parser fix, retrying fresh generation for slide {page_number}...')
                            continue
                        else:
                            logger.warning(f'❌ All generation and parser fix attempts failed, using fallback for slide {page_number}')
                            fallback_html = self._generate_fallback_slide_html(slide_data, page_number, total_pages)
                            return await self._apply_auto_layout_repair(fallback_html, slide_data, page_number, total_pages)
                    else:
                        logger.info(f'✅ HTML is valid with only missing element warnings for slide {page_number}')
                        return await self._apply_auto_layout_repair(html_content, slide_data, page_number, total_pages)
            except Exception as e:
                error_msg = str(e)
                logger.error(f'Error in HTML generation attempt {attempt + 1} for slide {page_number}: {error_msg}')
                if 'Expecting value' in error_msg or 'JSON' in error_msg:
                    logger.warning(f'JSON parsing error detected, this might be due to malformed AI response')
                    if attempt < max_retries - 1:
                        logger.info('Waiting 1 second before retry due to JSON parsing error...')
                        await asyncio.sleep(1)
                        continue
                if attempt == max_retries - 1:
                    logger.error(f'All attempts failed with errors, using fallback for slide {page_number}')
                    fallback_html = self._generate_fallback_slide_html(slide_data, page_number, total_pages)
                    return await self._apply_auto_layout_repair(fallback_html, slide_data, page_number, total_pages)
                continue
        fallback_html = self._generate_fallback_slide_html(slide_data, page_number, total_pages)
        return await self._apply_auto_layout_repair(fallback_html, slide_data, page_number, total_pages)

    def _fix_incomplete_html(self, html_content: str, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """Try to fix incomplete HTML by adding missing elements"""
        import re
        html_content = html_content.strip()
        if len(html_content) < 50:
            return self._generate_fallback_slide_html(slide_data, page_number, total_pages)
        if not html_content.lower().startswith('<!doctype'):
            html_content = '<!DOCTYPE html>\n' + html_content
        if not re.search('<html[^>]*>', html_content, re.IGNORECASE):
            html_content = html_content.replace('<!DOCTYPE html>', '<!DOCTYPE html>\n<html lang="zh-CN">')
        if not re.search('</html>', html_content, re.IGNORECASE):
            html_content += '\n</html>'
        if not re.search('<head[^>]*>', html_content, re.IGNORECASE):
            head_section = '<head>\n        <meta charset="UTF-8">\n        <meta name="viewport" content="width=device-width, initial-scale=1.0">\n        <title>{}</title>\n    </head>'.format(slide_data.get('title', f'第{page_number}页'))
            html_content = re.sub('(<html[^>]*>)', '\\1\\n' + head_section, html_content, flags=re.IGNORECASE)
        elif not re.search('</head>', html_content, re.IGNORECASE):
            head_match = re.search('<head[^>]*>', html_content, re.IGNORECASE)
            if head_match:
                head_start = head_match.end()
                if not re.search('<meta[^>]*charset[^>]*>', html_content, re.IGNORECASE):
                    charset_meta = '\n    <meta charset="UTF-8">'
                    html_content = html_content[:head_start] + charset_meta + html_content[head_start:]
                if '<body' in html_content.lower():
                    html_content = re.sub('(<body[^>]*>)', '</head>\\n\\1', html_content, flags=re.IGNORECASE)
                elif '</title>' in html_content.lower():
                    html_content = re.sub('(</title>)', '\\1\\n</head>', html_content, flags=re.IGNORECASE)
                else:
                    html_content = re.sub('(<html[^>]*>.*?<head[^>]*>.*?)(<body|$)', '\\1\\n</head>\\n\\2', html_content, flags=re.IGNORECASE | re.DOTALL)
        if not re.search('<body[^>]*>', html_content, re.IGNORECASE):
            if '</head>' in html_content.lower():
                html_content = re.sub('(</head>)', '\\1\\n<body>', html_content, flags=re.IGNORECASE)
            else:
                html_content = re.sub('(<html[^>]*>)', '\\1\\n<body>', html_content, flags=re.IGNORECASE)
        if not re.search('</body>', html_content, re.IGNORECASE):
            html_content = re.sub('(</html>)', '</body>\\n\\1', html_content, flags=re.IGNORECASE)
        return html_content
