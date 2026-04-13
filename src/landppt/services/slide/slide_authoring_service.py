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
from .slide_html_service import SlideHtmlService
from .slide_streaming_service import SlideStreamingService

if TYPE_CHECKING:
    from ..enhanced_ppt_service import EnhancedPPTService


class SlideAuthoringService:
    """Facade over slide HTML and streaming services."""

    def __init__(self, service: "EnhancedPPTService"):
        self._service = service
        self._html_service = SlideHtmlService(self)
        self._streaming_service = SlideStreamingService(self)

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def generate_slides_parallel(self, slide_requests: List[Dict[str, Any]], scenario: str, topic: str, language: str='zh') -> List[str]:
        return await self._html_service.generate_slides_parallel(slide_requests, scenario, topic, language)

    async def generate_slide_content(self, slide_title: str, scenario: str, topic: str, language: str='zh') -> str:
        return await self._html_service.generate_slide_content(slide_title, scenario, topic, language)

    async def enhance_content_with_ai(self, content: str, scenario: str, language: str='zh') -> str:
        return await self._html_service.enhance_content_with_ai(content, scenario, language)

    async def _execute_general_subtask(self, project_id: str, stage, subtask: str, confirmed_requirements: Dict[str, Any], system_prompt: str) -> str:
        return await self._html_service._execute_general_subtask(project_id, stage, subtask, confirmed_requirements, system_prompt)

    async def _generate_single_slide_html_with_prompts(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any], system_prompt: str, page_number: int, total_pages: int, all_slides: List[Dict[str, Any]]=None, existing_slides_data: List[Dict[str, Any]]=None, project_id: str=None) -> str:
        return await self._html_service._generate_single_slide_html_with_prompts(slide_data, confirmed_requirements, system_prompt, page_number, total_pages, all_slides, existing_slides_data, project_id)

    async def _process_slide_image(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any], page_number: int, total_pages: int, template_html: str=''):
        return await self._html_service._process_slide_image(slide_data, confirmed_requirements, page_number, total_pages, template_html)

    async def _ensure_slide_images_context(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any], page_number: int, total_pages: int, template_html: str='') -> None:
        return await self._html_service._ensure_slide_images_context(slide_data, confirmed_requirements, page_number, total_pages, template_html)

    def _get_innovation_guidelines(self, slide_type: str, page_number: int, total_pages: int) -> List[str]:
        return self._html_service._get_innovation_guidelines(slide_type, page_number, total_pages)

    def _extract_style_info(self, html_content: str) -> List[str]:
        return self._html_service._extract_style_info(html_content)

    def _clean_html_response(self, raw_content: str) -> str:
        return self._html_service._clean_html_response(raw_content)

    def _validate_html_completeness(self, html_content: str) -> Dict[str, Any]:
        return self._html_service._validate_html_completeness(html_content)

    def _check_html_well_formedness(self, html_content: str, validation_result: Dict[str, Any]) -> None:
        return self._html_service._check_html_well_formedness(html_content, validation_result)

    def _auto_fix_html_with_parser(self, html_content: str) -> str:
        return self._html_service._auto_fix_html_with_parser(html_content)

    def _basic_html_syntax_check(self, html_content: str, validation_result: Dict[str, Any]) -> None:
        return self._html_service._basic_html_syntax_check(html_content, validation_result)

    async def _generate_html_with_retry(self, context: str, system_prompt: str, slide_data: Dict[str, Any], page_number: int, total_pages: int, max_retries: int=3) -> str:
        return await self._html_service._generate_html_with_retry(context, system_prompt, slide_data, page_number, total_pages, max_retries)

    def _fix_incomplete_html(self, html_content: str, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        return self._html_service._fix_incomplete_html(html_content, slide_data, page_number, total_pages)

    def _generate_fallback_slide_html(self, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        return self._html_service._generate_fallback_slide_html(slide_data, page_number, total_pages)

    def _combine_slides_to_full_html(self, slides_data: List[Dict[str, Any]], title: str) -> str:
        return self._html_service._combine_slides_to_full_html(slides_data, title)

    def _generate_empty_presentation_html(self, title: str) -> str:
        return self._html_service._generate_empty_presentation_html(title)

    def _encode_html_for_iframe(self, html_content: str) -> str:
        return self._html_service._encode_html_for_iframe(html_content)

    def _encode_html_to_base64(self, html_content: str) -> str:
        return self._html_service._encode_html_to_base64(html_content)

    async def _design_theme(self, scenario: str, language: str) -> Dict[str, Any]:
        return await self._html_service._design_theme(scenario, language)

    def _normalize_slide_type(self, slide_type: str) -> str:
        return self._html_service._normalize_slide_type(slide_type)

    async def _generate_enhanced_content(self, outline: PPTOutline, request: PPTGenerationRequest) -> List[SlideContent]:
        return await self._html_service._generate_enhanced_content(outline, request)

    async def _verify_layout(self, slides: List[SlideContent], theme_config: Dict[str, Any]) -> List[SlideContent]:
        return await self._html_service._verify_layout(slides, theme_config)

    async def _generate_html_output(self, slides: List[SlideContent], theme_config: Dict[str, Any]) -> str:
        return await self._html_service._generate_html_output(slides, theme_config)

    def _extract_bullet_points(self, content: str) -> List[str]:
        return self._html_service._extract_bullet_points(content)

    async def _suggest_images(self, slide_title: str, scenario: str, content: str='', topic: str='', page_number: int=1, total_pages: int=1) -> List[str]:
        return await self._html_service._suggest_images(slide_title, scenario, content, topic, page_number, total_pages)

    async def generate_slide_image(self, slide_title: str, slide_content: str, scenario: str, topic: str, page_number: int=1, total_pages: int=1, provider: str='dalle') -> Optional[str]:
        return await self._html_service.generate_slide_image(slide_title, slide_content, scenario, topic, page_number, total_pages, provider)

    async def create_image_prompt_for_slide(self, slide_title: str, slide_content: str, scenario: str, topic: str, page_number: int=1, total_pages: int=1) -> str:
        return await self._html_service.create_image_prompt_for_slide(slide_title, slide_content, scenario, topic, page_number, total_pages)

    def _generate_basic_html(self, slides: List[SlideContent], theme_config: Dict[str, Any]) -> str:
        return self._html_service._generate_basic_html(slides, theme_config)

    async def _execute_ppt_creation(self, project_id: str, confirmed_requirements: Dict[str, Any], system_prompt: str) -> str:
        return await self._streaming_service._execute_ppt_creation(project_id, confirmed_requirements, system_prompt)

    def _slides_generation_cancel_key(self, project_id: str) -> str:
        return self._streaming_service._slides_generation_cancel_key(project_id)

    async def request_cancel_slides_generation(self, project_id: str) -> bool:
        return await self._streaming_service.request_cancel_slides_generation(project_id)

    async def clear_cancel_slides_generation(self, project_id: str) -> bool:
        return await self._streaming_service.clear_cancel_slides_generation(project_id)

    async def _is_slides_generation_cancelled(self, project_id: str, cache=None) -> bool:
        return await self._streaming_service._is_slides_generation_cancelled(project_id, cache)

    async def _renew_valkey_lock(self, cache, lock_key: str, ttl: int):
        return await self._streaming_service._renew_valkey_lock(cache, lock_key, ttl)

    async def _try_acquire_slides_generation_lock(self, project_id: str) -> dict:
        return await self._streaming_service._try_acquire_slides_generation_lock(project_id)

    async def _release_slides_generation_lock(self, lock_info: dict):
        return await self._streaming_service._release_slides_generation_lock(lock_info)

    async def _background_generate_slides(self, project_id: str, lock_info: dict):
        return await self._streaming_service._background_generate_slides(project_id, lock_info)

    async def _stream_slides_from_db(self, project_id: str, total_slides: int):
        async for item in self._streaming_service._stream_slides_from_db(project_id, total_slides):
            yield item

    async def generate_slides_streaming(self, project_id: str):
        async for item in self._streaming_service.generate_slides_streaming(project_id):
            yield item

    async def _generate_slides_streaming_direct(self, project_id: str):
        async for item in self._streaming_service._generate_slides_streaming_direct(project_id):
            yield item

    async def regenerate_slide(self, project_id: str, slide_index: int, request: PPTGenerationRequest) -> Optional[SlideContent]:
        return await self._streaming_service.regenerate_slide(project_id, slide_index, request)

    async def lock_slide(self, project_id: str, slide_index: int, user_id: Optional[int]=None) -> bool:
        return await self._streaming_service.lock_slide(project_id, slide_index, user_id)

    async def unlock_slide(self, project_id: str, slide_index: int, user_id: Optional[int]=None) -> bool:
        return await self._streaming_service.unlock_slide(project_id, slide_index, user_id)
