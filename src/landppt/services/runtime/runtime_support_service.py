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
from .ai_execution import ExecutionContext
from ..prompts import prompts_manager
from ..research.enhanced_research_service import EnhancedResearchService
from ..research.enhanced_report_generator import EnhancedReportGenerator
from ..pyppeteer_pdf_converter import get_pdf_converter
from ..image.image_service import ImageService
from ..image.adapters.ppt_prompt_adapter import PPTSlideContext
from ...utils.thread_pool import run_blocking_io, to_thread


logger = logging.getLogger(__name__)
from .runtime_ai_service import RuntimeAIService
from .runtime_image_service import RuntimeImageService
from .runtime_research_service import RuntimeResearchService

if TYPE_CHECKING:
    from ..enhanced_ppt_service import EnhancedPPTService


class RuntimeSupportService:
    """Facade over runtime research, AI config, and image support services."""

    def __init__(self, service: "EnhancedPPTService"):
        self._service = service
        self._research_runtime = RuntimeResearchService(self)
        self._ai_runtime = RuntimeAIService(self)
        self._image_runtime = RuntimeImageService(self)

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    @property
    def ai_provider(self):
        return self._ai_runtime.ai_provider

    @staticmethod
    def _trim_research_preview_text(text: str, limit: int = 16000) -> str:
        return RuntimeResearchService._trim_research_preview_text(text, limit)

    @staticmethod
    def _chunk_research_preview_text(text: str, chunk_size: int = 900) -> List[str]:
        return RuntimeResearchService._chunk_research_preview_text(text, chunk_size)

    @staticmethod
    def _excerpt_research_preview_text(text: str, limit: int = 320) -> str:
        return RuntimeResearchService._excerpt_research_preview_text(text, limit)

    def _initialize_research_services(self):
        return self._research_runtime._initialize_research_services()

    def _get_preferred_outline_research_runtime(self) -> Dict[str, Any]:
        return self._research_runtime._get_preferred_outline_research_runtime()

    def _create_research_context(self, research_report: Any) -> str:
        return self._research_runtime._create_research_context(research_report)

    def _build_research_preview_payloads(self, header: str, body: str, *, status: Optional[Dict[str, Any]]=None) -> List[Dict[str, Any]]:
        return self._research_runtime._build_research_preview_payloads(header, body, status=status)

    def iter_research_stream_payloads(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._research_runtime.iter_research_stream_payloads(event)

    def reload_research_config(self):
        return self._research_runtime.reload_research_config()

    def _initialize_image_service(self):
        return self._image_runtime._initialize_image_service()

    async def _async_initialize_image_service(self):
        return await self._image_runtime._async_initialize_image_service()

    def _get_current_ai_config(self, role: str='default'):
        return self._ai_runtime._get_current_ai_config(role)

    def _get_current_ai_config_sync_impl(self, role: str='default'):
        return self._ai_runtime._get_current_ai_config_sync_impl(role)

    async def _get_current_ai_config_async(self, role: str='default'):
        return await self._ai_runtime._get_current_ai_config_async(role)

    async def _get_current_mineru_config_async(self) -> Dict[str, Optional[str]]:
        return await self._ai_runtime._get_current_mineru_config_async()

    def _extract_ai_config_from_user_config(self, user_config: dict, role: str='default'):
        return self._ai_runtime._extract_ai_config_from_user_config(user_config, role)

    def _get_fallback_ai_config(self, role: str='default'):
        return self._ai_runtime._get_fallback_ai_config(role)

    def _get_role_provider(self, role: str):
        return self._ai_runtime._get_role_provider(role)

    async def _get_role_provider_async(self, role: str):
        return await self._ai_runtime._get_role_provider_async(role)

    def get_role_provider(self, role: str):
        return self._ai_runtime.get_role_provider(role)

    async def get_role_provider_async(self, role: str):
        return await self._ai_runtime.get_role_provider_async(role)

    async def _text_completion_for_role(self, role: str, *, prompt: str, **kwargs):
        return await self._ai_runtime._text_completion_for_role(role, prompt=prompt, **kwargs)

    async def _stream_text_completion_for_role(self, role: str, *, prompt: str, **kwargs):
        async for item in self._ai_runtime._stream_text_completion_for_role(role, prompt=prompt, **kwargs):
            yield item

    async def _chat_completion_for_role(self, role: str, *, messages: List[AIMessage], **kwargs):
        return await self._ai_runtime._chat_completion_for_role(role, messages=messages, **kwargs)

    async def _get_user_generation_config(self) -> Dict[str, Any]:
        return await self._ai_runtime._get_user_generation_config()

    def update_ai_config(self):
        return self._ai_runtime.update_ai_config()

    def _configure_summeryfile_api(self, generator, role: str='default'):
        return self._ai_runtime._configure_summeryfile_api(generator, role)

    def _build_execution_context(self, role: str, current_ai_config: Optional[Dict[str, Any]]=None) -> ExecutionContext:
        return self._ai_runtime._build_execution_context(role, current_ai_config)

    def _build_summeryanyfile_processing_config(self, *, processing_config_cls, execution_context: ExecutionContext, target_language: str, min_slides: int, max_slides: int, chunk_size: int, chunk_strategy: Any):
        return self._ai_runtime._build_summeryanyfile_processing_config(processing_config_cls=processing_config_cls, execution_context=execution_context, target_language=target_language, min_slides=min_slides, max_slides=max_slides, chunk_size=chunk_size, chunk_strategy=chunk_strategy)

    def get_cache_stats(self) -> Dict[str, Any]:
        return self._ai_runtime.get_cache_stats()

    def cleanup_cache(self):
        return self._ai_runtime.cleanup_cache()

    def _cleanup_style_genes_cache(self, max_age_days: int=7):
        return self._ai_runtime._cleanup_style_genes_cache(max_age_days)
