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
from .project_outline_repair_service import ProjectOutlineRepairService
from .project_outline_normalization_service import ProjectOutlineNormalizationService

if TYPE_CHECKING:
    from .project_outline_generation_service import ProjectOutlineGenerationService


class ProjectOutlineValidationService:
    """Facade over extracted subservices for ProjectOutlineValidationService."""

    def __init__(self, service: "ProjectOutlineGenerationService"):
        self._service = service
        self._repair_service = ProjectOutlineRepairService(self)
        self._normalization_service = ProjectOutlineNormalizationService(self)

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _validate_and_repair_outline_json(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._repair_service._validate_and_repair_outline_json(outline_data, confirmed_requirements)

    def _validate_outline_structure(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> List[str]:
        return self._repair_service._validate_outline_structure(outline_data, confirmed_requirements)

    def _validate_slide_structure(self, slide: Dict[str, Any], slide_index: int) -> List[str]:
        return self._repair_service._validate_slide_structure(slide, slide_index)

    async def _repair_outline_with_ai(self, outline_data: Dict[str, Any], validation_errors: List[str], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self._repair_service._repair_outline_with_ai(outline_data, validation_errors, confirmed_requirements)

    def _build_repair_prompt(self, outline_data: Dict[str, Any], validation_errors: List[str], confirmed_requirements: Dict[str, Any]) -> str:
        return self._repair_service._build_repair_prompt(outline_data, validation_errors, confirmed_requirements)

    async def _update_outline_generation_stage(self, project_id: str, outline_data: Dict[str, Any]):
        return await self._repair_service._update_outline_generation_stage(project_id, outline_data)

    def _parse_outline_content(self, content: str, project: PPTProject) -> Dict[str, Any]:
        return self._normalization_service._parse_outline_content(content, project)

    def _standardize_outline_format(self, outline_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._normalization_service._standardize_outline_format(outline_data)

    def _create_default_slides_from_content(self, content: str, project: PPTProject) -> List[Dict[str, Any]]:
        return self._normalization_service._create_default_slides_from_content(content, project)
