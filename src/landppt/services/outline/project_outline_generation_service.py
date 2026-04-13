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
from .project_outline_creation_service import ProjectOutlineCreationService
from .project_outline_streaming_service import ProjectOutlineStreamingService
from .project_outline_validation_service import ProjectOutlineValidationService
from .project_outline_page_count_service import ProjectOutlinePageCountService

if TYPE_CHECKING:
    from .project_outline_workflow_service import ProjectOutlineWorkflowService


class ProjectOutlineGenerationService:
    """Facade over extracted subservices for ProjectOutlineGenerationService."""

    def __init__(self, service: "ProjectOutlineWorkflowService"):
        self._service = service
        self._creation_service = ProjectOutlineCreationService(self)
        self._streaming_service = ProjectOutlineStreamingService(self)
        self._validation_service = ProjectOutlineValidationService(self)
        self._page_count_service = ProjectOutlinePageCountService(self)

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def generate_outline(self, request: PPTGenerationRequest, page_count_settings: Dict[str, Any]=None) -> PPTOutline:
        return await self._creation_service.generate_outline(request, page_count_settings)

    def _create_outline_prompt(self, request: PPTGenerationRequest, research_context: str='', page_count_settings: Dict[str, Any]=None) -> str:
        return self._creation_service._create_outline_prompt(request, research_context, page_count_settings)

    def _parse_ai_outline(self, ai_response: str, request: PPTGenerationRequest) -> PPTOutline:
        return self._creation_service._parse_ai_outline(ai_response, request)

    def _create_default_slides(self, title: str, request: PPTGenerationRequest) -> List[Dict[str, Any]]:
        return self._creation_service._create_default_slides(title, request)

    def _create_default_slides_compatible(self, title: str, request: PPTGenerationRequest) -> List[Dict[str, Any]]:
        return self._creation_service._create_default_slides_compatible(title, request)

    def _create_default_outline(self, request: PPTGenerationRequest) -> PPTOutline:
        return self._creation_service._create_default_outline(request)

    def _standardize_summeryfile_outline(self, summeryfile_outline: Dict[str, Any]) -> Dict[str, Any]:
        return self._creation_service._standardize_summeryfile_outline(summeryfile_outline)

    async def conduct_research_and_merge_with_files(self, topic: str, language: str, file_paths: Optional[List[str]]=None, context: Optional[Dict[str, Any]]=None, event_callback=None) -> str:
        return await self._creation_service.conduct_research_and_merge_with_files(topic, language, file_paths, context, event_callback)

    def _extract_summeryanyfile_llm_call_count(self, generator) -> int:
        return self._creation_service._extract_summeryanyfile_llm_call_count(generator)

    async def generate_outline_streaming(self, project_id: str):
        async for item in self._streaming_service.generate_outline_streaming(project_id):
            yield item

    async def _validate_and_repair_outline_json(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._validation_service._validate_and_repair_outline_json(outline_data, confirmed_requirements)

    def _validate_outline_structure(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> List[str]:
        return self._validation_service._validate_outline_structure(outline_data, confirmed_requirements)

    def _validate_slide_structure(self, slide: Dict[str, Any], slide_index: int) -> List[str]:
        return self._validation_service._validate_slide_structure(slide, slide_index)

    async def _repair_outline_with_ai(self, outline_data: Dict[str, Any], validation_errors: List[str], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._validation_service._repair_outline_with_ai(outline_data, validation_errors, confirmed_requirements)

    def _build_repair_prompt(self, outline_data: Dict[str, Any], validation_errors: List[str], confirmed_requirements: Dict[str, Any]) -> str:
        return self._validation_service._build_repair_prompt(outline_data, validation_errors, confirmed_requirements)

    async def _update_outline_generation_stage(self, project_id: str, outline_data: Dict[str, Any]):
        return await self._validation_service._update_outline_generation_stage(project_id, outline_data)

    def _parse_outline_content(self, content: str, project: PPTProject) -> Dict[str, Any]:
        return self._validation_service._parse_outline_content(content, project)

    def _standardize_outline_format(self, outline_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._validation_service._standardize_outline_format(outline_data)

    def _create_default_slides_from_content(self, content: str, project: PPTProject) -> List[Dict[str, Any]]:
        return self._validation_service._create_default_slides_from_content(content, project)

    async def _execute_outline_generation(self, project_id: str, confirmed_requirements: Dict[str, Any], system_prompt: str) -> str:
        return await self._page_count_service._execute_outline_generation(project_id, confirmed_requirements, system_prompt)

    async def _adjust_outline_page_count(self, outline_data: Dict[str, Any], min_pages: int, max_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._page_count_service._adjust_outline_page_count(outline_data, min_pages, max_pages, confirmed_requirements)

    async def _expand_outline(self, outline_data: Dict[str, Any], target_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._page_count_service._expand_outline(outline_data, target_pages, confirmed_requirements)

    async def _condense_outline(self, outline_data: Dict[str, Any], target_pages: int) -> Dict[str, Any]:
        return await self._page_count_service._condense_outline(outline_data, target_pages)

    async def _force_page_count(self, outline_data: Dict[str, Any], target_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._page_count_service._force_page_count(outline_data, target_pages, confirmed_requirements)
