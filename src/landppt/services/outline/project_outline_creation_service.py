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
from .project_outline_prompt_service import ProjectOutlinePromptService
from .project_outline_research_service import ProjectOutlineResearchService

if TYPE_CHECKING:
    from .project_outline_generation_service import ProjectOutlineGenerationService


class ProjectOutlineCreationService:
    """Facade over extracted subservices for ProjectOutlineCreationService."""

    def __init__(self, service: "ProjectOutlineGenerationService"):
        self._service = service
        self._prompt_service = ProjectOutlinePromptService(self)
        self._research_service = ProjectOutlineResearchService(self)

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _create_outline_prompt(self, request: PPTGenerationRequest, research_context: str='', page_count_settings: Dict[str, Any]=None) -> str:
        return self._prompt_service._create_outline_prompt(request, research_context, page_count_settings)

    def _parse_ai_outline(self, ai_response: str, request: PPTGenerationRequest) -> PPTOutline:
        return self._prompt_service._parse_ai_outline(ai_response, request)

    def _create_default_slides(self, title: str, request: PPTGenerationRequest) -> List[Dict[str, Any]]:
        return self._prompt_service._create_default_slides(title, request)

    def _create_default_slides_compatible(self, title: str, request: PPTGenerationRequest) -> List[Dict[str, Any]]:
        return self._prompt_service._create_default_slides_compatible(title, request)

    def _create_default_outline(self, request: PPTGenerationRequest) -> PPTOutline:
        return self._prompt_service._create_default_outline(request)

    async def generate_outline(self, request: PPTGenerationRequest, page_count_settings: Dict[str, Any]=None) -> PPTOutline:
        return await self._research_service.generate_outline(request, page_count_settings)

    def _standardize_summeryfile_outline(self, summeryfile_outline: Dict[str, Any]) -> Dict[str, Any]:
        return self._research_service._standardize_summeryfile_outline(summeryfile_outline)

    async def conduct_research_and_merge_with_files(self, topic: str, language: str, file_paths: Optional[List[str]]=None, context: Optional[Dict[str, Any]]=None, event_callback=None) -> str:
        return await self._research_service.conduct_research_and_merge_with_files(topic, language, file_paths, context, event_callback)

    def _extract_summeryanyfile_llm_call_count(self, generator) -> int:
        return self._research_service._extract_summeryanyfile_llm_call_count(generator)
