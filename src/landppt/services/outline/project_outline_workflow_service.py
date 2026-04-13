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
from .project_outline_generation_service import ProjectOutlineGenerationService
from ..project_workflow_stage_service import ProjectWorkflowStageService

if TYPE_CHECKING:
    from ..enhanced_ppt_service import EnhancedPPTService


class ProjectOutlineWorkflowService:
    """Facade over outline generation and workflow stage services."""

    def __init__(self, service: "EnhancedPPTService"):
        self._service = service
        self._outline_generation = ProjectOutlineGenerationService(self)
        self._workflow_stage = ProjectWorkflowStageService(self)

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def generate_outline(self, request: PPTGenerationRequest, page_count_settings: Dict[str, Any]=None) -> PPTOutline:
        return await self._outline_generation.generate_outline(request, page_count_settings)

    def _create_outline_prompt(self, request: PPTGenerationRequest, research_context: str='', page_count_settings: Dict[str, Any]=None) -> str:
        return self._outline_generation._create_outline_prompt(request, research_context, page_count_settings)

    def _parse_ai_outline(self, ai_response: str, request: PPTGenerationRequest) -> PPTOutline:
        return self._outline_generation._parse_ai_outline(ai_response, request)

    def _create_default_slides(self, title: str, request: PPTGenerationRequest) -> List[Dict[str, Any]]:
        return self._outline_generation._create_default_slides(title, request)

    def _create_default_slides_compatible(self, title: str, request: PPTGenerationRequest) -> List[Dict[str, Any]]:
        return self._outline_generation._create_default_slides_compatible(title, request)

    def _create_default_outline(self, request: PPTGenerationRequest) -> PPTOutline:
        return self._outline_generation._create_default_outline(request)

    async def generate_outline_streaming(self, project_id: str):
        async for item in self._outline_generation.generate_outline_streaming(project_id):
            yield item

    async def _validate_and_repair_outline_json(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._outline_generation._validate_and_repair_outline_json(outline_data, confirmed_requirements)

    def _validate_outline_structure(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> List[str]:
        return self._outline_generation._validate_outline_structure(outline_data, confirmed_requirements)

    def _validate_slide_structure(self, slide: Dict[str, Any], slide_index: int) -> List[str]:
        return self._outline_generation._validate_slide_structure(slide, slide_index)

    async def _repair_outline_with_ai(self, outline_data: Dict[str, Any], validation_errors: List[str], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._outline_generation._repair_outline_with_ai(outline_data, validation_errors, confirmed_requirements)

    def _build_repair_prompt(self, outline_data: Dict[str, Any], validation_errors: List[str], confirmed_requirements: Dict[str, Any]) -> str:
        return self._outline_generation._build_repair_prompt(outline_data, validation_errors, confirmed_requirements)

    async def _update_outline_generation_stage(self, project_id: str, outline_data: Dict[str, Any]):
        return await self._outline_generation._update_outline_generation_stage(project_id, outline_data)

    def _parse_outline_content(self, content: str, project: PPTProject) -> Dict[str, Any]:
        return self._outline_generation._parse_outline_content(content, project)

    def _standardize_outline_format(self, outline_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._outline_generation._standardize_outline_format(outline_data)

    def _create_default_slides_from_content(self, content: str, project: PPTProject) -> List[Dict[str, Any]]:
        return self._outline_generation._create_default_slides_from_content(content, project)

    async def _execute_outline_generation(self, project_id: str, confirmed_requirements: Dict[str, Any], system_prompt: str) -> str:
        return await self._outline_generation._execute_outline_generation(project_id, confirmed_requirements, system_prompt)

    async def _adjust_outline_page_count(self, outline_data: Dict[str, Any], min_pages: int, max_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._outline_generation._adjust_outline_page_count(outline_data, min_pages, max_pages, confirmed_requirements)

    async def _expand_outline(self, outline_data: Dict[str, Any], target_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._outline_generation._expand_outline(outline_data, target_pages, confirmed_requirements)

    async def _condense_outline(self, outline_data: Dict[str, Any], target_pages: int) -> Dict[str, Any]:
        return await self._outline_generation._condense_outline(outline_data, target_pages)

    async def _force_page_count(self, outline_data: Dict[str, Any], target_pages: int, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._outline_generation._force_page_count(outline_data, target_pages, confirmed_requirements)

    def _standardize_summeryfile_outline(self, summeryfile_outline: Dict[str, Any]) -> Dict[str, Any]:
        return self._outline_generation._standardize_summeryfile_outline(summeryfile_outline)

    async def conduct_research_and_merge_with_files(self, topic: str, language: str, file_paths: Optional[List[str]]=None, context: Optional[Dict[str, Any]]=None, event_callback=None) -> str:
        return await self._outline_generation.conduct_research_and_merge_with_files(topic, language, file_paths, context, event_callback)

    def _extract_summeryanyfile_llm_call_count(self, generator) -> int:
        return self._outline_generation._extract_summeryanyfile_llm_call_count(generator)

    async def create_project_with_workflow(self, request: PPTGenerationRequest) -> PPTProject:
        return await self._workflow_stage.create_project_with_workflow(request)

    async def _execute_project_workflow(self, project_id: str, request: PPTGenerationRequest, user_id: Optional[int]=None):
        return await self._workflow_stage._execute_project_workflow(project_id, request, user_id)

    async def _execute_complete_stage(self, project_id: str, stage_id: str, request: PPTGenerationRequest):
        return await self._workflow_stage._execute_complete_stage(project_id, stage_id, request)

    async def _execute_general_stage(self, project_id: str, stage_id: str, confirmed_requirements: Dict[str, Any]):
        return await self._workflow_stage._execute_general_stage(project_id, stage_id, confirmed_requirements)

    async def _complete_stage(self, project_id: str, stage_id: str, request: PPTGenerationRequest) -> Dict[str, Any]:
        return await self._workflow_stage._complete_stage(project_id, stage_id, request)

    async def update_project_outline(self, project_id: str, outline_content: str) -> bool:
        return await self._workflow_stage.update_project_outline(project_id, outline_content)

    async def confirm_project_outline(self, project_id: str) -> bool:
        return await self._workflow_stage.confirm_project_outline(project_id)

    def _get_default_suggestions(self, project: PPTProject) -> Dict[str, Any]:
        return self._workflow_stage._get_default_suggestions(project)

    def _get_default_todo_structure(self, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return self._workflow_stage._get_default_todo_structure(confirmed_requirements)

    async def _update_project_todo_board(self, project_id: str, todo_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]):
        return await self._workflow_stage._update_project_todo_board(project_id, todo_data, confirmed_requirements)

    async def confirm_requirements_and_update_workflow(self, project_id: str, confirmed_requirements: Dict[str, Any]) -> bool:
        return await self._workflow_stage.confirm_requirements_and_update_workflow(project_id, confirmed_requirements)

    async def get_project_todo_board(self, project_id: str, user_id: Optional[int]=None) -> Optional[TodoBoard]:
        return await self._workflow_stage.get_project_todo_board(project_id, user_id)

    async def update_project_stage(self, project_id: str, stage_id: str, status: str, progress: float=None, result: Dict[str, Any]=None, user_id: Optional[int]=None) -> bool:
        return await self._workflow_stage.update_project_stage(project_id, stage_id, status, progress, result, user_id)

    async def reset_stages_from(self, project_id: str, stage_id: str, user_id: Optional[int]=None) -> bool:
        return await self._workflow_stage.reset_stages_from(project_id, stage_id, user_id)

    async def start_workflow_from_stage(self, project_id: str, stage_id: str, user_id: Optional[int]=None) -> bool:
        return await self._workflow_stage.start_workflow_from_stage(project_id, stage_id, user_id)
