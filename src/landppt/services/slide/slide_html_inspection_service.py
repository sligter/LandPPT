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

class SlideHtmlInspectionService:
    """Extracted logic from SlideHtmlValidationService."""

    def __init__(self, service: 'SlideHtmlValidationService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _extract_style_info(self, html_content: str) -> List[str]:
        """Extract style information from HTML content for consistency reference"""
        import re
        style_info = []
        try:
            bg_colors = re.findall('background[^:]*:\\s*([^;]+)', html_content, re.IGNORECASE)
            if bg_colors:
                style_info.append(f'背景色调：{bg_colors[0][:50]}')
            colors = re.findall('color[^:]*:\\s*([^;]+)', html_content, re.IGNORECASE)
            if colors:
                unique_colors = list(set(colors[:3]))
                style_info.append(f"主要颜色：{', '.join(unique_colors)}")
            fonts = re.findall('font-family[^:]*:\\s*([^;]+)', html_content, re.IGNORECASE)
            if fonts:
                style_info.append(f'字体：{fonts[0][:50]}')
            font_sizes = re.findall('font-size[^:]*:\\s*([^;]+)', html_content, re.IGNORECASE)
            if font_sizes:
                unique_sizes = list(set(font_sizes[:3]))
                style_info.append(f"字体大小：{', '.join(unique_sizes)}")
            border_radius = re.findall('border-radius[^:]*:\\s*([^;]+)', html_content, re.IGNORECASE)
            if border_radius:
                style_info.append(f'圆角样式：{border_radius[0]}')
            box_shadow = re.findall('box-shadow[^:]*:\\s*([^;]+)', html_content, re.IGNORECASE)
            if box_shadow:
                style_info.append(f'阴影效果：{box_shadow[0][:50]}')
            if 'display: flex' in html_content:
                style_info.append('布局方式：Flexbox布局')
            elif 'display: grid' in html_content:
                style_info.append('布局方式：Grid布局')
            paddings = re.findall('padding[^:]*:\\s*([^;]+)', html_content, re.IGNORECASE)
            if paddings:
                style_info.append(f'内边距：{paddings[0]}')
        except Exception as e:
            logger.warning(f'Error extracting style info: {e}')
        return style_info[:8]

    def _validate_html_completeness(self, html_content: str) -> Dict[str, Any]:
        """
                    Validate HTML format correctness and tag closure using BeautifulSoup and lxml.
        
                    This validator checks for:
                    1. Presence of essential elements (<!DOCTYPE>, <html>, <head>, <body>) as warnings
                    2. Correct structural order (<head> before <body>) as a warning
                    3. Well-formedness and tag closure using strict parsing, reported as errors
                    4. Unescaped special characters ('<' or '>') in text content as a warning
        
                    Returns:
                        Dict with 'is_complete', 'errors', 'warnings', 'missing_elements' keys
                    """
        from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
        import warnings
        validation_result = {'is_complete': False, 'errors': [], 'warnings': [], 'missing_elements': []}
        if not html_content or not html_content.strip():
            validation_result['errors'].append('HTML内容为空或仅包含空白字符')
            return validation_result
        self._check_html_well_formedness(html_content, validation_result)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=MarkupResemblesLocatorWarning)
                try:
                    soup = BeautifulSoup(html_content, 'lxml')
                except:
                    soup = BeautifulSoup(html_content, 'html.parser')
            if not html_content.strip().lower().startswith('<!doctype'):
                validation_result['missing_elements'].append('doctype')
            essential_tags = {'html', 'head', 'body'}
            for tag_name in essential_tags:
                if not soup.find(tag_name):
                    validation_result['missing_elements'].append(tag_name)
            head_tag = soup.find('head')
            body_tag = soup.find('body')
            if head_tag and body_tag:
                if not body_tag.find_previous_sibling('head'):
                    validation_result['warnings'].append('HTML结构顺序不正确：<body>标签出现在<head>标签之前')
            text_content = soup.get_text()
            if '<' in text_content or '>' in text_content:
                validation_result['warnings'].append("文本内容中可能包含未转义的特殊字符（'<'或'>'）")
        except Exception as e:
            validation_result['errors'].append(f'BeautifulSoup解析过程中发生意外错误: {e}')
        validation_result['is_complete'] = len(validation_result['errors']) == 0
        return validation_result

    def _check_html_well_formedness(self, html_content: str, validation_result: Dict[str, Any]) -> None:
        """
                    Uses lxml's strict parser to check if the HTML is well-formed.
                    This is the definitive check for syntax errors like unclosed tags.
                    Modifies the validation_result dictionary in place.
                    """
        try:
            from lxml import etree
            encoded_html = html_content.encode('utf-8')
            parser = etree.HTMLParser(recover=False, encoding='utf-8')
            etree.fromstring(encoded_html, parser)
        except ImportError:
            logger.warning('lxml not available, using basic HTML validation')
            self._basic_html_syntax_check(html_content, validation_result)
        except Exception as e:
            validation_result['errors'].append(f'HTML语法错误: {str(e)}')

    def _auto_fix_html_with_parser(self, html_content: str) -> str:
        """
                    使用 lxml 的恢复解析器自动修复 HTML 错误
        
                    Args:
                        html_content: 原始 HTML 内容
        
                    Returns:
                        修复后的 HTML 内容，如果修复失败则返回原始内容
                    """
        try:
            from lxml import etree
            try:
                encoded_html = html_content.encode('utf-8')
                strict_parser = etree.HTMLParser(recover=False, encoding='utf-8')
                etree.fromstring(encoded_html, strict_parser)
                logger.debug('HTML 已经是有效的，无需修复')
                return html_content
            except:
                pass
            parser = etree.HTMLParser(recover=True, encoding='utf-8')
            tree = etree.fromstring(encoded_html, parser)
            doctype_match = None
            import re
            doctype_pattern = '<!DOCTYPE[^>]*>'
            doctype_match = re.search(doctype_pattern, html_content, re.IGNORECASE)
            fixed_html = etree.tostring(tree, encoding='unicode', method='html', pretty_print=True)
            if doctype_match:
                doctype = doctype_match.group(0)
                if not fixed_html.lower().startswith('<!doctype'):
                    fixed_html = doctype + '\n' + fixed_html
            logger.info('使用 lxml 解析器自动修复 HTML 成功')
            return fixed_html
        except ImportError:
            logger.warning('lxml 不可用，无法使用解析器自动修复')
            return html_content
        except Exception as e:
            logger.warning(f'解析器自动修复失败: {str(e)}')
            return html_content

    def _basic_html_syntax_check(self, html_content: str, validation_result: Dict[str, Any]) -> None:
        """
                    Basic HTML syntax checking when lxml is not available.
                    Uses regex patterns to detect common HTML syntax errors.
                    """
        import re
        from collections import Counter
        malformed_tags = re.findall('<[^>]*<[^>]*>', html_content)
        if malformed_tags:
            validation_result['errors'].append('发现格式错误的标签')
        critical_tags = {'html', 'head', 'body', 'div', 'p', 'span'}
        open_tags = re.findall('<([a-zA-Z][a-zA-Z0-9]*)[^>]*>', html_content)
        close_tags = re.findall('</([a-zA-Z][a-zA-Z0-9]*)>', html_content)
        self_closing_tags = {'meta', 'link', 'img', 'br', 'hr', 'input', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}
        open_tags_filtered = [tag.lower() for tag in open_tags if tag.lower() in critical_tags and tag.lower() not in self_closing_tags]
        close_tags_lower = [tag.lower() for tag in close_tags if tag.lower() in critical_tags]
        open_tag_counts = Counter(open_tags_filtered)
        close_tag_counts = Counter(close_tags_lower)
        unclosed_critical_tags = []
        for tag, open_count in open_tag_counts.items():
            close_count = close_tag_counts.get(tag, 0)
            if open_count > close_count:
                unclosed_critical_tags.append(f'{tag}({open_count - close_count}个未闭合)')
        if unclosed_critical_tags:
            validation_result['errors'].append(f"未闭合的关键HTML标签: {', '.join(unclosed_critical_tags)}")
