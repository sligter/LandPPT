"""
Enhanced PPT Service with real AI integration and project management
"""

import json
import re
import logging
import uuid
import asyncio
import time
import os
import tempfile
import base64
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..api.models import (
    PPTGenerationRequest, PPTOutline, EnhancedPPTOutline,
    SlideContent, PPTProject, TodoBoard, FileOutlineGenerationResponse
)
from ..ai import get_ai_provider, get_role_provider, AIMessage, MessageRole
from ..ai.base import TextContent, ImageContent
from ..core.config import ai_config, app_config
from .runtime.ai_execution import ExecutionContext
from .slide.creative_design_service import CreativeDesignService
from .outline.outline_workflow_service import OutlineWorkflowService
from .ppt_service import PPTService
from .db_project_manager import DatabaseProjectManager
from .template.global_master_template_service import GlobalMasterTemplateService
from .slide.layout_repair_service import LayoutRepairService
from .outline.project_outline_workflow_service import ProjectOutlineWorkflowService
from .prompts import prompts_manager
from .template.template_selection_service import TemplateSelectionService
from .slide.slide_generation_service import SlideGenerationService
from .runtime.runtime_support_service import RuntimeSupportService
from .slide.slide_authoring_service import SlideAuthoringService

from .research.enhanced_research_service import EnhancedResearchService
from .research.enhanced_report_generator import EnhancedReportGenerator
from .pyppeteer_pdf_converter import get_pdf_converter
from .image.image_service import ImageService
from .image.adapters.ppt_prompt_adapter import PPTSlideContext
from ..utils.thread_pool import run_blocking_io, to_thread

# Configure logger for this module
logger = logging.getLogger(__name__)

class EnhancedPPTService(PPTService):
    """Enhanced PPT service with real AI integration and project management"""

    def __init__(self, provider_name: Optional[str] = None, user_id: Optional[int] = None):
        super().__init__()
        self.provider_name = provider_name
        self.user_id = user_id  # User ID for per-user config isolation
        self.project_manager = DatabaseProjectManager()
        self.global_template_service = GlobalMasterTemplateService(provider_name, user_id=user_id)
        self.runtime_support = RuntimeSupportService(self)

        # 配置属性，用于summeryanyfile集成
        # 初始化配置（将在需要时实时更新）
        self.config = self.runtime_support._get_current_ai_config()

        # 初始化文件缓存管理器 - 设置缓存目录到项目根目录下的temp文件夹，每个模式的缓存分开管理
        try:
            from summeryanyfile.core.file_cache_manager import FileCacheManager
            import os
            from pathlib import Path

            # 获取项目根目录
            project_root = Path(__file__).parent.parent.parent.parent

            # 为不同模式创建分离的缓存目录
            base_cache_dir = project_root / "temp"

            # 创建分模式的缓存目录结构
            cache_dirs = {
                'summeryanyfile': base_cache_dir / "summeryanyfile_cache",
                'style_genes': base_cache_dir / "style_genes_cache",
                'ai_responses': base_cache_dir / "ai_responses_cache",
                'templates': base_cache_dir / "templates_cache"
            }

            # 确保所有缓存目录存在
            for cache_type, cache_path in cache_dirs.items():
                cache_path.mkdir(parents=True, exist_ok=True)

            # 初始化文件缓存管理器（用于summeryanyfile），按处理模式分开管理
            # 注意：summeryanyfile 的 PDF “高质量处理(MinerU)” 对应 processing_mode=magic_pdf
            base_summery_cache_dir = str(cache_dirs['summeryanyfile'])
            self.file_cache_managers = {
                "markitdown": FileCacheManager(cache_dir=base_summery_cache_dir, processing_mode="markitdown"),
                "magic_pdf": FileCacheManager(cache_dir=base_summery_cache_dir, processing_mode="magic_pdf"),
            }
            # Backward-compatible attribute (legacy code may read a single manager)
            self.file_cache_manager = self.file_cache_managers.get("markitdown")

            # 存储缓存目录配置供其他功能使用
            self.cache_dirs = cache_dirs

            logger.info(f"文件缓存目录已初始化（按类型）: {cache_dirs}")
        except ImportError as e:
            logger.warning(f"无法导入文件缓存管理器: {e}")
            self.file_cache_manager = None
            self.file_cache_managers = None
            self.cache_dirs = None

        # 初始化研究服务
        self.research_service = None
        self.report_generator = None
        self.runtime_support._initialize_research_services()

        # 初始化图片服务
        self.image_service = None
        self.runtime_support._initialize_image_service()
        self.outline_workflow = OutlineWorkflowService(self)
        self.creative_design = CreativeDesignService(self)
        self.template_selection = TemplateSelectionService(self)
        self.slide_generation = SlideGenerationService(self)
        self.layout_repair = LayoutRepairService(self)
        self.project_outline_workflow = ProjectOutlineWorkflowService(self)
        self.slide_authoring = SlideAuthoringService(self)

        # Per-project lock to avoid duplicate free-template generation under parallel slide generation
        self._free_template_generation_locks: Dict[str, asyncio.Lock] = {}
        
        # Per-project lock and tracking to prevent duplicate slide generation
        self._slide_generation_locks: Dict[str, asyncio.Lock] = {}
        self._active_slide_generations: Dict[str, bool] = {}
        # Background slide generation tasks (decouple generation from SSE connection lifetime)
        self._slides_generation_tasks: Dict[str, asyncio.Task] = {}
        # Local cancellation flags (best-effort when distributed cache is unavailable)
        self._slides_generation_cancel_flags: Dict[str, bool] = {}

    @staticmethod
    def _build_current_time_prompt_context() -> str:
        """Build current-time context so prompts can reason about present time explicitly."""
        now = datetime.now().astimezone()
        quarter = (now.month - 1) // 3 + 1
        timezone_name = now.tzname() or "Local"
        return "\n".join([
            f"- 当前本地时间：{now:%Y-%m-%d %H:%M:%S} ({timezone_name})",
        ])

    def _get_auto_layout_debug_dir(self) -> Path:
        """Directory to persist auto layout repair debug artifacts (HTML & screenshots)."""
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        debug_dir = project_root / "temp" / "auto_layout_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        return debug_dir

    @property
    def ai_provider(self):
        return self.runtime_support.ai_provider



    def _get_preferred_outline_research_runtime(self) -> Dict[str, Any]:
        return self.runtime_support._get_preferred_outline_research_runtime()


    def _create_research_context(self, research_report: Any) -> str:
        return self.runtime_support._create_research_context(research_report)


    def iter_research_stream_payloads(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.runtime_support.iter_research_stream_payloads(event)


    def reload_research_config(self):
        return self.runtime_support.reload_research_config()


    def _get_current_ai_config(self, role: str = "default"):
        return self.runtime_support._get_current_ai_config(role)

    
    
    async def _get_current_ai_config_async(self, role: str = "default"):
        return await self.runtime_support._get_current_ai_config_async(role)


    async def _get_current_mineru_config_async(self) -> Dict[str, Optional[str]]:
        return await self.runtime_support._get_current_mineru_config_async()


    

    def _get_role_provider(self, role: str):
        return self.runtime_support._get_role_provider(role)


    async def _get_role_provider_async(self, role: str):
        return await self.runtime_support._get_role_provider_async(role)


    def get_role_provider(self, role: str):
        return self.runtime_support.get_role_provider(role)


    async def get_role_provider_async(self, role: str):
        return await self.runtime_support.get_role_provider_async(role)


    async def _text_completion_for_role(self, role: str, *, prompt: str, **kwargs):
        return await self.runtime_support._text_completion_for_role(role, prompt=prompt, **kwargs)


    async def _stream_text_completion_for_role(self, role: str, *, prompt: str, **kwargs):
        async for item in self.runtime_support._stream_text_completion_for_role(role, prompt=prompt, **kwargs):
            yield item


    async def _chat_completion_for_role(self, role: str, *, messages: List[AIMessage], **kwargs):
        return await self.runtime_support._chat_completion_for_role(role, messages=messages, **kwargs)


    async def _get_user_generation_config(self) -> Dict[str, Any]:
        return await self.runtime_support._get_user_generation_config()

    def update_ai_config(self):
        return self.runtime_support.update_ai_config()


    def _build_execution_context(
        self,
        role: str,
        current_ai_config: Optional[Dict[str, Any]] = None,
    ) -> ExecutionContext:
        return self.runtime_support._build_execution_context(role, current_ai_config)


    def _build_summeryanyfile_processing_config(
        self,
        *,
        processing_config_cls,
        execution_context: ExecutionContext,
        target_language: str,
        min_slides: int,
        max_slides: int,
        chunk_size: int,
        chunk_strategy: Any,
    ):
        return self.runtime_support._build_summeryanyfile_processing_config(processing_config_cls=processing_config_cls, execution_context=execution_context, target_language=target_language, min_slides=min_slides, max_slides=max_slides, chunk_size=chunk_size, chunk_strategy=chunk_strategy)


    def get_cache_stats(self) -> Dict[str, Any]:
        return self.runtime_support.get_cache_stats()


    def cleanup_cache(self):
        return self.runtime_support.cleanup_cache()



    async def generate_outline(self, request: PPTGenerationRequest, page_count_settings: Dict[str, Any] = None) -> PPTOutline:
        return await self.project_outline_workflow.generate_outline(request, page_count_settings)

    
    async def generate_slides_parallel(self, slide_requests: List[Dict[str, Any]], scenario: str, topic: str, language: str = "zh") -> List[str]:
        return await self.slide_authoring.generate_slides_parallel(slide_requests, scenario, topic, language)

    
    async def generate_slide_content(self, slide_title: str, scenario: str, topic: str, language: str = "zh") -> str:
        return await self.slide_authoring.generate_slide_content(slide_title, scenario, topic, language)

    
    async def enhance_content_with_ai(self, content: str, scenario: str, language: str = "zh") -> str:
        return await self.slide_authoring.enhance_content_with_ai(content, scenario, language)

    
    
    def _create_slide_content_prompt(self, slide_title: str, scenario: str, topic: str, language: str) -> str:
        """Create prompt for slide content generation"""
        if language == "zh":
            return prompts_manager.get_slide_content_prompt_zh(slide_title, scenario, topic)
        else:
            return prompts_manager.get_slide_content_prompt_en(slide_title, scenario, topic)
    
    def _create_enhancement_prompt(self, content: str, scenario: str, language: str) -> str:
        """Create prompt for content enhancement"""
        if language == "zh":
            return prompts_manager.get_enhancement_prompt_zh(content, scenario)
        else:
            return prompts_manager.get_enhancement_prompt_en(content, scenario)
    
    
    # New project-based methods
    async def create_project_with_workflow(self, request: PPTGenerationRequest) -> PPTProject:
        return await self.project_outline_workflow.create_project_with_workflow(request)

    async def _execute_project_workflow(self, project_id: str,
                                      request: PPTGenerationRequest,
                                      user_id: Optional[int] = None):
        return await self.project_outline_workflow._execute_project_workflow(project_id, request, user_id)


    async def generate_outline_streaming(self, project_id: str):
        async for item in self.project_outline_workflow.generate_outline_streaming(project_id):
            yield item


    async def _validate_and_repair_outline_json(self, outline_data: Dict[str, Any], confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
        return await self.project_outline_workflow._validate_and_repair_outline_json(outline_data, confirmed_requirements)


    async def _update_outline_generation_stage(self, project_id: str, outline_data: Dict[str, Any]):
        return await self.project_outline_workflow._update_outline_generation_stage(project_id, outline_data)


    async def update_project_outline(self, project_id: str, outline_content: str) -> bool:
        return await self.project_outline_workflow.update_project_outline(project_id, outline_content)


    async def confirm_project_outline(self, project_id: str) -> bool:
        return await self.project_outline_workflow.confirm_project_outline(project_id)


    async def confirm_requirements_and_update_workflow(self, project_id: str, confirmed_requirements: Dict[str, Any]) -> bool:
        return await self.project_outline_workflow.confirm_requirements_and_update_workflow(project_id, confirmed_requirements)


    def _load_prompts_md_system_prompt(self) -> str:
        """Load system prompt from prompts.md file"""
        return prompts_manager.load_prompts_md_system_prompt()

    def _load_keynote_style_prompt(self) -> str:
        """Load keynote style prompt from keynote_style_prompt.md file"""
        return prompts_manager.get_keynote_style_prompt()

    def _get_style_prompt(self, confirmed_requirements: Dict[str, Any]) -> str:
        """Get style prompt based on confirmed requirements"""
        if not confirmed_requirements:
            return self._load_prompts_md_system_prompt()

        ppt_style = confirmed_requirements.get('ppt_style', 'general')

        if ppt_style == 'keynote':
            return self._load_keynote_style_prompt()
        elif ppt_style == 'custom':
            custom_prompt = confirmed_requirements.get('custom_style_prompt', '')
            if custom_prompt:
                return prompts_manager.get_custom_style_prompt(custom_prompt)
            else:
                return self._load_prompts_md_system_prompt()
        else:
            # Default to general style (prompts.md)
            return self._load_prompts_md_system_prompt()

    def _get_default_ppt_system_prompt(self) -> str:
        """Get default PPT generation system prompt"""
        return prompts_manager.get_default_ppt_system_prompt()


    async def _execute_ppt_creation(self, project_id: str, confirmed_requirements: Dict[str, Any], system_prompt: str) -> str:
        return await self.slide_authoring._execute_ppt_creation(project_id, confirmed_requirements, system_prompt)


    async def request_cancel_slides_generation(self, project_id: str) -> bool:
        return await self.slide_authoring.request_cancel_slides_generation(project_id)

    async def clear_cancel_slides_generation(self, project_id: str) -> bool:
        return await self.slide_authoring.clear_cancel_slides_generation(project_id)

    async def generate_slides_streaming(self, project_id: str):
        async for item in self.slide_authoring.generate_slides_streaming(project_id):
            yield item


    async def _generate_slides_streaming_impl(self, project_id: str):
        async for chunk in self.slide_generation._generate_slides_streaming_impl(project_id):
            yield chunk


    async def _generate_single_slide_html_with_prompts(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
                                                     system_prompt: str, page_number: int, total_pages: int,
                                                     all_slides: List[Dict[str, Any]] = None, existing_slides_data: List[Dict[str, Any]] = None,
                                                     project_id: str = None) -> str:
        return await self.slide_authoring._generate_single_slide_html_with_prompts(slide_data, confirmed_requirements, system_prompt, page_number, total_pages, all_slides, existing_slides_data, project_id)


    async def _process_slide_image(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
                                 page_number: int, total_pages: int, template_html: str = ""):
        return await self.slide_authoring._process_slide_image(slide_data, confirmed_requirements, page_number, total_pages, template_html)


    async def _ensure_slide_images_context(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
                                         page_number: int, total_pages: int, template_html: str = "") -> None:
        return await self.slide_authoring._ensure_slide_images_context(slide_data, confirmed_requirements, page_number, total_pages, template_html)


    def _build_creative_slides_summary(self, all_slides: Optional[List[Dict[str, Any]]]) -> str:
        return self.creative_design._build_creative_slides_summary(all_slides)

    async def _generate_slide_with_template(self, slide_data: Dict[str, Any], template: Dict[str, Any],
                                          page_number: int, total_pages: int,
                                          confirmed_requirements: Dict[str, Any], all_slides: List[Dict[str, Any]] = None,
                                          project_id: str = None) -> str:
        return await self.creative_design._generate_slide_with_template(
            slide_data,
            template,
            page_number,
            total_pages,
            confirmed_requirements,
            all_slides=all_slides,
            project_id=project_id,
        )

    async def _build_creative_template_context(self, slide_data: Dict[str, Any], template_html: str,
                                       template_name: str, page_number: int, total_pages: int,
                                       confirmed_requirements: Dict[str, Any], all_slides: List[Dict[str, Any]] = None,
                                       project_id: str = None) -> str:
        return await self.creative_design._build_creative_template_context(
            slide_data,
            template_html,
            template_name,
            page_number,
            total_pages,
            confirmed_requirements,
            all_slides=all_slides,
            project_id=project_id,
        )

    async def _extract_style_genes(self, template_html: str) -> str:
        return await self.creative_design._extract_style_genes(template_html)

    def _extract_fallback_style_genes(self, template_html: str) -> str:
        return self.creative_design._extract_fallback_style_genes(template_html)

    async def _get_or_extract_style_genes(self, project_id: str, template_html: str, page_number: int) -> str:
        return await self.creative_design._get_or_extract_style_genes(project_id, template_html, page_number)

    async def _prepare_project_creative_guidance(self, project_id: str, slide_data: Dict[str, Any],
                                                 confirmed_requirements: Optional[Dict[str, Any]] = None,
                                                 all_slides: Optional[List[Dict[str, Any]]] = None,
                                                 total_pages: int = 1,
                                                 template_html: str = "",
                                                 prewarm_slide_guides: int = 0,
                                                 async_prewarm_remaining_slide_guides: bool = False) -> str:
        return await self.creative_design._prepare_project_creative_guidance(
            project_id,
            slide_data,
            confirmed_requirements=confirmed_requirements,
            all_slides=all_slides,
            total_pages=total_pages,
            template_html=template_html,
            prewarm_slide_guides=prewarm_slide_guides,
            async_prewarm_remaining_slide_guides=async_prewarm_remaining_slide_guides,
        )

    async def _get_creative_design_inputs(self, project_id: str, template_html: str, slide_data: Dict[str, Any],
                                          page_number: int, total_pages: int,
                                          confirmed_requirements: Optional[Dict[str, Any]] = None,
                                          all_slides: Optional[List[Dict[str, Any]]] = None) -> tuple[str, str, str]:
        return await self.creative_design._get_creative_design_inputs(
            project_id,
            template_html,
            slide_data,
            page_number,
            total_pages,
            confirmed_requirements=confirmed_requirements,
            all_slides=all_slides,
        )

    async def _extract_style_genes_and_guide(self, template_html: str, slide_data: Dict[str, Any],
                                              page_number: int, total_pages: int) -> tuple:
        return await self.creative_design._extract_style_genes_and_guide(
            template_html,
            slide_data,
            page_number,
            total_pages,
        )

    async def _get_or_extract_style_genes_and_guide(self, project_id: str, template_html: str,
                                                     slide_data: Dict[str, Any],
                                                     page_number: int, total_pages: int) -> tuple:
        return await self.creative_design._get_or_extract_style_genes_and_guide(
            project_id,
            template_html,
            slide_data,
            page_number,
            total_pages,
        )

    def _generate_fallback_unified_guide(self, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        return self.creative_design._generate_fallback_unified_guide(slide_data, page_number, total_pages)

    def _build_slide_context(self, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        return self.creative_design._build_slide_context(slide_data, page_number, total_pages)

    def _extract_style_template(self, existing_slides: List[Dict[str, Any]]) -> List[str]:
        return self.creative_design._extract_style_template(existing_slides)

    def _extract_detailed_style_info(self, html_content: str) -> Dict[str, List[str]]:
        return self.creative_design._extract_detailed_style_info(html_content)

    def _analyze_common_layout(self, layout_patterns: List[str]) -> str:
        return self.creative_design._analyze_common_layout(layout_patterns)

    async def _generate_html_with_retry(self, context: str, system_prompt: str, slide_data: Dict[str, Any],
                                      page_number: int, total_pages: int, max_retries: int = 3) -> str:
        return await self.slide_authoring._generate_html_with_retry(context, system_prompt, slide_data, page_number, total_pages, max_retries)

    @staticmethod
    def _strip_think_tags(raw_content: Optional[str]) -> str:
        """Remove <think>...</think> sections that some providers prepend."""
        if not raw_content:
            return ""

        import re

        cleaned = re.sub(
            r"<\s*think[^>]*>.*?<\s*/\s*think\s*>",
            "",
            raw_content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return cleaned.strip()

    @staticmethod
    def _should_skip_layout_repair(inspection_report: str) -> bool:
        return LayoutRepairService._should_skip_layout_repair(inspection_report)

    def _clean_html_response(self, raw_content: str) -> str:
        return self.slide_authoring._clean_html_response(raw_content)

    def _inject_anti_overflow_css(self, html_content: str) -> str:
        return self.layout_repair._inject_anti_overflow_css(html_content)

    async def _apply_auto_layout_repair(
        self,
        html_content: str,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
    ) -> str:
        return await self.layout_repair._apply_auto_layout_repair(
            html_content,
            slide_data,
            page_number,
            total_pages,
        )

    def _build_layout_inspection_prompt(
        self,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
    ) -> str:
        return self.layout_repair._build_layout_inspection_prompt(slide_data, page_number, total_pages)

    def _build_layout_repair_prompt(self, original_html: str, inspection_report: str) -> str:
        return self.layout_repair._build_layout_repair_prompt(original_html, inspection_report)

    def _generate_fallback_slide_html(self, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        return self.slide_authoring._generate_fallback_slide_html(slide_data, page_number, total_pages)

    def _combine_slides_to_full_html(self, slides_data: List[Dict[str, Any]], title: str) -> str:
        return self.slide_authoring._combine_slides_to_full_html(slides_data, title)

    async def generate_slide_image(self,
                                 slide_title: str,
                                 slide_content: str,
                                 scenario: str,
                                 topic: str,
                                 page_number: int = 1,
                                 total_pages: int = 1,
                                 provider: str = "dalle") -> Optional[str]:
        return await self.slide_authoring.generate_slide_image(slide_title, slide_content, scenario, topic, page_number, total_pages, provider)


    async def create_image_prompt_for_slide(self,
                                          slide_title: str,
                                          slide_content: str,
                                          scenario: str,
                                          topic: str,
                                          page_number: int = 1,
                                          total_pages: int = 1) -> str:
        return await self.slide_authoring.create_image_prompt_for_slide(slide_title, slide_content, scenario, topic, page_number, total_pages)



    # Project management integration methods
    async def get_project_todo_board(self, project_id: str, user_id: Optional[int] = None) -> Optional[TodoBoard]:
        return await self.project_outline_workflow.get_project_todo_board(project_id, user_id)


    async def update_project_stage(self, project_id: str, stage_id: str, status: str,
                                 progress: float = None, result: Dict[str, Any] = None,
                                 user_id: Optional[int] = None) -> bool:
        return await self.project_outline_workflow.update_project_stage(project_id, stage_id, status, progress, result, user_id)


    async def reset_stages_from(self, project_id: str, stage_id: str, user_id: Optional[int] = None) -> bool:
        return await self.project_outline_workflow.reset_stages_from(project_id, stage_id, user_id)


    async def start_workflow_from_stage(self, project_id: str, stage_id: str, user_id: Optional[int] = None) -> bool:
        return await self.project_outline_workflow.start_workflow_from_stage(project_id, stage_id, user_id)


    async def regenerate_slide(self, project_id: str, slide_index: int,
                             request: PPTGenerationRequest) -> Optional[SlideContent]:
        return await self.slide_authoring.regenerate_slide(project_id, slide_index, request)


    async def lock_slide(self, project_id: str, slide_index: int, user_id: Optional[int] = None) -> bool:
        return await self.slide_authoring.lock_slide(project_id, slide_index, user_id)


    async def unlock_slide(self, project_id: str, slide_index: int, user_id: Optional[int] = None) -> bool:
        return await self.slide_authoring.unlock_slide(project_id, slide_index, user_id)


    def _standardize_summeryfile_outline(self, summeryfile_outline: Dict[str, Any]) -> Dict[str, Any]:
        return self.project_outline_workflow._standardize_summeryfile_outline(summeryfile_outline)


    async def conduct_research_and_merge_with_files(
        self,
        topic: str,
        language: str,
        file_paths: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        event_callback=None,
    ) -> str:
        return await self.project_outline_workflow.conduct_research_and_merge_with_files(topic, language, file_paths, context, event_callback)


    def _extract_summeryanyfile_llm_call_count(self, generator) -> int:
        return self.project_outline_workflow._extract_summeryanyfile_llm_call_count(generator)


    async def generate_outline_from_file_streaming(self, request):
        async for event in self.outline_workflow.generate_outline_from_file_streaming(request):
            yield event

    async def generate_outline_from_file(self, request) -> FileOutlineGenerationResponse:
        return await self.outline_workflow.generate_outline_from_file(request)

    async def _ensure_global_master_template_selected(self, project_id: str) -> Optional[Dict[str, Any]]:
        return await self.template_selection._ensure_global_master_template_selected(project_id)

    async def _save_selected_template_to_project(self, project_id: str, template_id: int):
        return await self.template_selection._save_selected_template_to_project(project_id, template_id)

    async def select_global_template_for_project(self, project_id: str, template_id: Optional[int] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
        return await self.template_selection.select_global_template_for_project(project_id, template_id, user_id=user_id)

    async def select_free_template_for_project(self, project_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        return await self.template_selection.select_free_template_for_project(project_id, user_id=user_id)

    async def get_selected_global_template(self, project_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        return await self.template_selection.get_selected_global_template(project_id, user_id=user_id)

    async def stream_free_template_generation(self, project_id: str, user_id: Optional[int] = None, force: bool = False):
        async for event in self.template_selection.stream_free_template_generation(project_id, user_id=user_id, force=force):
            yield event

    def clear_cached_style_genes(self, project_id: Optional[str] = None):
        return self.creative_design.clear_cached_style_genes(project_id)

    def get_cached_style_genes_info(self) -> Dict[str, Any]:
        return self.creative_design.get_cached_style_genes_info()


    def _read_file_with_fallback_encoding(self, file_path: str) -> str:
        """使用多种编码尝试读取文件（在线程池中运行）"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    return f.read()
            except:
                with open(file_path, 'r', encoding='latin-1') as f:
                    return f.read()

    def _save_research_to_temp_file(self, research_content: str) -> str:
        """将研究内容保存到临时文件（在线程池中运行）"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as temp_file:
            temp_file.write(research_content)
            return temp_file.name

    def _cleanup_temp_file(self, file_path: str) -> None:
        """清理临时文件（在线程池中运行）"""
        import os
        if os.path.exists(file_path):
            os.unlink(file_path)
