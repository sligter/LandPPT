import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from landppt.services.slide.creative_design_service import CreativeDesignService
from landppt.services.template.global_master_template_service import GlobalMasterTemplateService
from landppt.services.slide.layout_repair_service import LayoutRepairService
from landppt.services.slide.slide_html_cleanup_service import SlideHtmlCleanupService
from landppt.services.slide.slide_generation_service import SlideGenerationService
from landppt.services.template.template_selection_service import TemplateSelectionService


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _direct_class_methods(relative_path: str, class_name: str) -> set[str]:
    tree = ast.parse(_read(relative_path))
    top_level_funcs = [
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert top_level_funcs == []

    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name for node in class_node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _load_class_method(relative_path: str, class_name: str, method_name: str):
    tree = ast.parse(_read(relative_path))
    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method_node = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    module = ast.Module(body=[method_node], type_ignores=[])
    ast.fix_missing_locations(module)

    class _Logger:
        def debug(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

    namespace = {"logger": _Logger(), "re": re}
    exec(compile(module, relative_path, "exec"), namespace)
    return namespace[method_name]


def test_enhanced_ppt_service_delegates_extracted_service_logic():
    service_text = _read("src/landppt/services/enhanced_ppt_service.py")
    creative_text = _read("src/landppt/services/slide/creative_design_service.py")
    layout_text = _read("src/landppt/services/slide/layout_repair_service.py")
    outline_text = _read("src/landppt/services/outline/project_outline_workflow_service.py")
    outline_generation_text = _read("src/landppt/services/outline/project_outline_generation_service.py")
    outline_creation_text = _read("src/landppt/services/outline/project_outline_creation_service.py")
    outline_research_text = _read("src/landppt/services/outline/project_outline_research_service.py")
    runtime_text = _read("src/landppt/services/runtime/runtime_support_service.py")
    slide_authoring_text = _read("src/landppt/services/slide/slide_authoring_service.py")
    slide_stream_text = _read("src/landppt/services/slide/slide_streaming_service.py")
    slide_generation_text = _read("src/landppt/services/slide/slide_generation_service.py")
    template_text = _read("src/landppt/services/template/template_selection_service.py")

    assert "from .slide.creative_design_service import CreativeDesignService" in service_text
    assert "from .slide.layout_repair_service import LayoutRepairService" in service_text
    assert "from .outline.project_outline_workflow_service import ProjectOutlineWorkflowService" in service_text
    assert "from .runtime.runtime_support_service import RuntimeSupportService" in service_text
    assert "from .slide.slide_authoring_service import SlideAuthoringService" in service_text
    assert "from .slide.slide_generation_service import SlideGenerationService" in service_text
    assert "from .template.template_selection_service import TemplateSelectionService" in service_text

    assert "import asyncio" in slide_generation_text
    assert "self.creative_design = CreativeDesignService(self)" in service_text
    assert "self.runtime_support = RuntimeSupportService(self)" in service_text
    assert "self.project_outline_workflow = ProjectOutlineWorkflowService(self)" in service_text
    assert "self.slide_authoring = SlideAuthoringService(self)" in service_text
    assert "self.slide_generation = SlideGenerationService(self)" in service_text
    assert "self.layout_repair = LayoutRepairService(self)" in service_text
    assert "self.template_selection = TemplateSelectionService(self)" in service_text
    assert "self.runtime_support._initialize_research_services()" in service_text
    assert "self.runtime_support._initialize_image_service()" in service_text

    assert "async for chunk in self.slide_generation._generate_slides_streaming_impl(project_id):" in service_text
    assert "return await self.creative_design._generate_slide_with_template(" in service_text
    assert "return await self.creative_design._get_creative_design_inputs(" in service_text
    assert "return LayoutRepairService._should_skip_layout_repair(inspection_report)" in service_text
    assert "return await self.layout_repair._apply_auto_layout_repair(" in service_text
    assert "return await self.template_selection.get_selected_global_template(project_id, user_id=user_id)" in service_text
    assert "return self.creative_design.clear_cached_style_genes(project_id)" in service_text
    assert "return self.runtime_support._build_execution_context(role, current_ai_config)" in service_text
    assert "return self.runtime_support.iter_research_stream_payloads(event)" in service_text
    assert "return await self.project_outline_workflow.create_project_with_workflow(request)" in service_text
    assert "async for item in self.project_outline_workflow.generate_outline_streaming(project_id):" in service_text
    assert "async for item in self.slide_authoring.generate_slides_streaming(project_id):" in service_text
    assert "return self.slide_authoring._clean_html_response(raw_content)" in service_text
    assert "return await self.slide_authoring.regenerate_slide(project_id, slide_index, request)" in service_text
    assert len(service_text.splitlines()) < 1000

    for marker in [
        "get_combined_style_genes_and_guide_prompt(",
        "current_time_context = self._build_current_time_prompt_context()",
        "credits_should_bill = False",
        "with tempfile.TemporaryDirectory() as tmp_dir:",
        "conduct_enhanced_research(",
        "self._slides_generation_cancel_key(project_id)",
    ]:
        assert marker not in service_text

    assert "get_combined_style_genes_and_guide_prompt(" in creative_text
    assert "with tempfile.TemporaryDirectory() as tmp_dir:" in layout_text
    assert "conduct_enhanced_research(" in outline_research_text
    assert "def _build_execution_context(" in runtime_text
    assert "self._slides_generation_cancel_key(project_id)" in slide_stream_text
    assert "async def generate_slides_streaming(self, project_id: str):" in slide_authoring_text
    assert "credits_should_bill = False" in slide_generation_text
    assert 'template_name=f"自由模板-' in template_text


def test_split_workflow_runtime_and_slide_services_are_class_based_and_delegated():
    project_wrapper_text = _read("src/landppt/services/outline/project_outline_workflow_service.py")
    project_generation_text = _read("src/landppt/services/outline/project_outline_generation_service.py")
    project_stage_text = _read("src/landppt/services/project_workflow_stage_service.py")
    slide_wrapper_text = _read("src/landppt/services/slide/slide_authoring_service.py")
    slide_html_text = _read("src/landppt/services/slide/slide_html_service.py")
    slide_cleanup_text = _read("src/landppt/services/slide/slide_html_cleanup_service.py")
    slide_stream_text = _read("src/landppt/services/slide/slide_streaming_service.py")
    runtime_wrapper_text = _read("src/landppt/services/runtime/runtime_support_service.py")
    runtime_research_text = _read("src/landppt/services/runtime/runtime_research_service.py")
    runtime_ai_text = _read("src/landppt/services/runtime/runtime_ai_service.py")
    runtime_image_text = _read("src/landppt/services/runtime/runtime_image_service.py")

    assert "from .project_outline_generation_service import ProjectOutlineGenerationService" in project_wrapper_text
    assert "from ..project_workflow_stage_service import ProjectWorkflowStageService" in project_wrapper_text
    assert "self._outline_generation = ProjectOutlineGenerationService(self)" in project_wrapper_text
    assert "self._workflow_stage = ProjectWorkflowStageService(self)" in project_wrapper_text

    assert "from .slide_html_service import SlideHtmlService" in slide_wrapper_text
    assert "from .slide_streaming_service import SlideStreamingService" in slide_wrapper_text
    assert "self._html_service = SlideHtmlService(self)" in slide_wrapper_text
    assert "self._streaming_service = SlideStreamingService(self)" in slide_wrapper_text
    assert "return self._html_service._clean_html_response(raw_content)" in slide_wrapper_text
    assert "from .slide_html_cleanup_service import SlideHtmlCleanupService" in slide_html_text
    assert "self._cleanup_service = SlideHtmlCleanupService(self)" in slide_html_text

    assert "from .runtime_research_service import RuntimeResearchService" in runtime_wrapper_text
    assert "from .runtime_ai_service import RuntimeAIService" in runtime_wrapper_text
    assert "from .runtime_image_service import RuntimeImageService" in runtime_wrapper_text
    assert "self._research_runtime = RuntimeResearchService(self)" in runtime_wrapper_text
    assert "self._ai_runtime = RuntimeAIService(self)" in runtime_wrapper_text
    assert "self._image_runtime = RuntimeImageService(self)" in runtime_wrapper_text
    assert "def _owner(self):" in runtime_image_text
    assert "return self._service._service" in runtime_image_text
    assert "self._owner.image_service = ImageService(image_config)" in runtime_image_text

    assert len(project_wrapper_text.splitlines()) < 250
    assert len(slide_wrapper_text.splitlines()) < 250
    assert len(runtime_wrapper_text.splitlines()) < 220

    project_methods = _direct_class_methods(
        "src/landppt/services/outline/project_outline_workflow_service.py",
        "ProjectOutlineWorkflowService",
    )
    slide_methods = _direct_class_methods(
        "src/landppt/services/slide/slide_authoring_service.py",
        "SlideAuthoringService",
    )
    runtime_methods = _direct_class_methods(
        "src/landppt/services/runtime/runtime_support_service.py",
        "RuntimeSupportService",
    )

    assert {"generate_outline_streaming", "_execute_outline_generation", "confirm_project_outline"} <= project_methods
    assert {"generate_slides_streaming", "_generate_fallback_slide_html", "regenerate_slide"} <= slide_methods
    assert {"iter_research_stream_payloads", "_build_execution_context", "_initialize_image_service"} <= runtime_methods

    assert "async def generate_outline_streaming" in project_generation_text
    assert "async def confirm_project_outline" in project_stage_text
    assert "def _generate_fallback_slide_html" in slide_html_text
    assert "def _clean_html_response" in slide_cleanup_text
    assert "async def generate_slides_streaming" in slide_stream_text
    assert "def iter_research_stream_payloads" in runtime_research_text
    assert "def _build_execution_context" in runtime_ai_text
    assert "def _initialize_image_service" in runtime_image_text


def test_second_level_service_splits_are_facades_and_subservices_are_class_based():
    project_generation_text = _read("src/landppt/services/outline/project_outline_generation_service.py")
    project_creation_text = _read("src/landppt/services/outline/project_outline_creation_service.py")
    project_streaming_text = _read("src/landppt/services/outline/project_outline_streaming_service.py")
    project_validation_text = _read("src/landppt/services/outline/project_outline_validation_service.py")
    project_page_count_text = _read("src/landppt/services/outline/project_outline_page_count_service.py")

    slide_html_text = _read("src/landppt/services/slide/slide_html_service.py")
    slide_cleanup_text = _read("src/landppt/services/slide/slide_html_cleanup_service.py")
    slide_content_text = _read("src/landppt/services/slide/slide_content_service.py")
    slide_media_text = _read("src/landppt/services/slide/slide_media_service.py")
    slide_validation_text = _read("src/landppt/services/slide/slide_html_validation_service.py")
    slide_document_text = _read("src/landppt/services/slide/slide_document_service.py")

    runtime_ai_text = _read("src/landppt/services/runtime/runtime_ai_service.py")
    runtime_provider_text = _read("src/landppt/services/runtime/runtime_provider_service.py")
    runtime_config_text = _read("src/landppt/services/runtime/runtime_config_service.py")
    runtime_maintenance_text = _read("src/landppt/services/runtime/runtime_maintenance_service.py")

    assert "from .project_outline_creation_service import ProjectOutlineCreationService" in project_generation_text
    assert "from .project_outline_streaming_service import ProjectOutlineStreamingService" in project_generation_text
    assert "from .project_outline_validation_service import ProjectOutlineValidationService" in project_generation_text
    assert "from .project_outline_page_count_service import ProjectOutlinePageCountService" in project_generation_text
    assert "self._creation_service = ProjectOutlineCreationService(self)" in project_generation_text
    assert "self._streaming_service = ProjectOutlineStreamingService(self)" in project_generation_text
    assert "self._validation_service = ProjectOutlineValidationService(self)" in project_generation_text
    assert "self._page_count_service = ProjectOutlinePageCountService(self)" in project_generation_text

    assert "from .slide_content_service import SlideContentService" in slide_html_text
    assert "from .slide_media_service import SlideMediaService" in slide_html_text
    assert "from .slide_html_cleanup_service import SlideHtmlCleanupService" in slide_html_text
    assert "from .slide_html_validation_service import SlideHtmlValidationService" in slide_html_text
    assert "from .slide_document_service import SlideDocumentService" in slide_html_text
    assert "self._content_service = SlideContentService(self)" in slide_html_text
    assert "self._media_service = SlideMediaService(self)" in slide_html_text
    assert "self._cleanup_service = SlideHtmlCleanupService(self)" in slide_html_text
    assert "self._validation_service = SlideHtmlValidationService(self)" in slide_html_text
    assert "self._document_service = SlideDocumentService(self)" in slide_html_text
    assert "def _clean_html_response(self, raw_content: str) -> str:" in slide_cleanup_text

    assert "from .runtime_provider_service import RuntimeProviderService" in runtime_ai_text
    assert "from .runtime_config_service import RuntimeConfigService" in runtime_ai_text
    assert "from .runtime_maintenance_service import RuntimeMaintenanceService" in runtime_ai_text
    assert "self._provider_service = RuntimeProviderService(self)" in runtime_ai_text
    assert "self._config_service = RuntimeConfigService(self)" in runtime_ai_text
    assert "self._maintenance_service = RuntimeMaintenanceService(self)" in runtime_ai_text
    assert "@property" in runtime_ai_text
    assert "return self._provider_service.ai_provider" in runtime_ai_text

    assert len(project_generation_text.splitlines()) < 180
    assert len(slide_html_text.splitlines()) < 200
    assert len(slide_cleanup_text.splitlines()) < 120
    assert len(runtime_ai_text.splitlines()) < 160

    project_generation_methods = _direct_class_methods(
        "src/landppt/services/outline/project_outline_generation_service.py",
        "ProjectOutlineGenerationService",
    )
    slide_html_methods = _direct_class_methods(
        "src/landppt/services/slide/slide_html_service.py",
        "SlideHtmlService",
    )
    runtime_ai_methods = _direct_class_methods(
        "src/landppt/services/runtime/runtime_ai_service.py",
        "RuntimeAIService",
    )

    assert {"generate_outline_streaming", "_execute_outline_generation", "_validate_outline_structure"} <= project_generation_methods
    assert {"_generate_single_slide_html_with_prompts", "_generate_fallback_slide_html", "_generate_html_with_retry"} <= slide_html_methods
    assert {"ai_provider", "_text_completion_for_role", "_configure_summeryfile_api"} <= runtime_ai_methods

    assert "async def generate_outline" in project_creation_text
    assert "async def generate_outline_streaming" in project_streaming_text
    assert "async def _validate_and_repair_outline_json" in project_validation_text
    assert "async def _execute_outline_generation" in project_page_count_text

    assert "async def generate_slides_parallel" in slide_content_text
    assert "async def _generate_single_slide_html_with_prompts" in slide_media_text
    assert "async def _generate_html_with_retry" in slide_validation_text
    assert "def _generate_fallback_slide_html" in slide_document_text
    assert "def _clean_html_response" in slide_cleanup_text

    assert "@property" in runtime_provider_text
    assert "async def _get_current_ai_config_async" in runtime_config_text
    assert "def get_cache_stats" in runtime_maintenance_text

    _direct_class_methods("src/landppt/services/outline/project_outline_creation_service.py", "ProjectOutlineCreationService")
    _direct_class_methods("src/landppt/services/outline/project_outline_streaming_service.py", "ProjectOutlineStreamingService")
    _direct_class_methods("src/landppt/services/outline/project_outline_validation_service.py", "ProjectOutlineValidationService")
    _direct_class_methods("src/landppt/services/outline/project_outline_page_count_service.py", "ProjectOutlinePageCountService")
    _direct_class_methods("src/landppt/services/slide/slide_content_service.py", "SlideContentService")
    _direct_class_methods("src/landppt/services/slide/slide_media_service.py", "SlideMediaService")
    _direct_class_methods("src/landppt/services/slide/slide_html_cleanup_service.py", "SlideHtmlCleanupService")
    _direct_class_methods("src/landppt/services/slide/slide_html_validation_service.py", "SlideHtmlValidationService")
    _direct_class_methods("src/landppt/services/slide/slide_document_service.py", "SlideDocumentService")
    _direct_class_methods("src/landppt/services/runtime/runtime_provider_service.py", "RuntimeProviderService")
    _direct_class_methods("src/landppt/services/runtime/runtime_config_service.py", "RuntimeConfigService")
    _direct_class_methods("src/landppt/services/runtime/runtime_maintenance_service.py", "RuntimeMaintenanceService")


def test_third_level_service_splits_keep_creation_validation_and_html_validation_thin():
    project_creation_text = _read("src/landppt/services/outline/project_outline_creation_service.py")
    project_prompt_text = _read("src/landppt/services/outline/project_outline_prompt_service.py")
    project_research_text = _read("src/landppt/services/outline/project_outline_research_service.py")

    project_validation_text = _read("src/landppt/services/outline/project_outline_validation_service.py")
    project_repair_text = _read("src/landppt/services/outline/project_outline_repair_service.py")
    project_normalization_text = _read("src/landppt/services/outline/project_outline_normalization_service.py")

    slide_validation_text = _read("src/landppt/services/slide/slide_html_validation_service.py")
    slide_inspection_text = _read("src/landppt/services/slide/slide_html_inspection_service.py")
    slide_recovery_text = _read("src/landppt/services/slide/slide_html_recovery_service.py")

    assert "from .project_outline_prompt_service import ProjectOutlinePromptService" in project_creation_text
    assert "from .project_outline_research_service import ProjectOutlineResearchService" in project_creation_text
    assert "self._prompt_service = ProjectOutlinePromptService(self)" in project_creation_text
    assert "self._research_service = ProjectOutlineResearchService(self)" in project_creation_text

    assert "from .project_outline_repair_service import ProjectOutlineRepairService" in project_validation_text
    assert "from .project_outline_normalization_service import ProjectOutlineNormalizationService" in project_validation_text
    assert "self._repair_service = ProjectOutlineRepairService(self)" in project_validation_text
    assert "self._normalization_service = ProjectOutlineNormalizationService(self)" in project_validation_text

    assert "from .slide_html_inspection_service import SlideHtmlInspectionService" in slide_validation_text
    assert "from .slide_html_recovery_service import SlideHtmlRecoveryService" in slide_validation_text
    assert "self._inspection_service = SlideHtmlInspectionService(self)" in slide_validation_text
    assert "self._recovery_service = SlideHtmlRecoveryService(self)" in slide_validation_text

    assert len(project_creation_text.splitlines()) < 120
    assert len(project_validation_text.splitlines()) < 120
    assert len(slide_validation_text.splitlines()) < 100

    project_creation_methods = _direct_class_methods(
        "src/landppt/services/outline/project_outline_creation_service.py",
        "ProjectOutlineCreationService",
    )
    project_validation_methods = _direct_class_methods(
        "src/landppt/services/outline/project_outline_validation_service.py",
        "ProjectOutlineValidationService",
    )
    slide_validation_methods = _direct_class_methods(
        "src/landppt/services/slide/slide_html_validation_service.py",
        "SlideHtmlValidationService",
    )

    assert {"generate_outline", "_create_outline_prompt", "conduct_research_and_merge_with_files"} <= project_creation_methods
    assert {"_validate_and_repair_outline_json", "_parse_outline_content", "_update_outline_generation_stage"} <= project_validation_methods
    assert {"_validate_html_completeness", "_generate_html_with_retry", "_fix_incomplete_html"} <= slide_validation_methods

    assert "def _create_outline_prompt" in project_prompt_text
    assert "async def generate_outline" in project_research_text
    assert "async def _validate_and_repair_outline_json" in project_repair_text
    assert "def _parse_outline_content" in project_normalization_text
    assert "def _validate_html_completeness" in slide_inspection_text
    assert "async def _generate_html_with_retry" in slide_recovery_text

    _direct_class_methods("src/landppt/services/outline/project_outline_prompt_service.py", "ProjectOutlinePromptService")
    _direct_class_methods("src/landppt/services/outline/project_outline_research_service.py", "ProjectOutlineResearchService")
    _direct_class_methods("src/landppt/services/outline/project_outline_repair_service.py", "ProjectOutlineRepairService")
    _direct_class_methods("src/landppt/services/outline/project_outline_normalization_service.py", "ProjectOutlineNormalizationService")
    _direct_class_methods("src/landppt/services/slide/slide_html_inspection_service.py", "SlideHtmlInspectionService")
    _direct_class_methods("src/landppt/services/slide/slide_html_recovery_service.py", "SlideHtmlRecoveryService")


class _DummyProjectManager:
    def __init__(self, project):
        self.project = project
        self.updated = []

    async def get_project(self, project_id, user_id=None):
        del project_id, user_id
        return self.project

    async def update_project_metadata(self, project_id, metadata):
        self.updated.append((project_id, dict(metadata)))
        self.project.project_metadata = dict(metadata)


class _DummyGlobalTemplateService:
    def __init__(self):
        self.incremented = []
        self.generated_kwargs = []

    async def get_template_by_id(self, template_id):
        return {"id": template_id, "template_name": "Global", "is_active": True}

    async def get_default_template(self):
        return {"id": 9, "template_name": "Default", "is_active": True}

    async def increment_template_usage(self, template_id):
        self.incremented.append(template_id)

    async def generate_template_with_ai(self, **kwargs):
        self.generated_kwargs.append(dict(kwargs))
        return {
            "template_name": kwargs["template_name"],
            "html_template": "<!DOCTYPE html><html></html>",
        }


@pytest.mark.asyncio
async def test_template_selection_service_updates_project_metadata_and_returns_cached_free_template():
    project = SimpleNamespace(
        project_metadata={"selected_global_template_id": 1},
        outline={"slides": []},
        confirmed_requirements={},
        topic="Quarterly Review",
        scenario="general",
    )

    owner = SimpleNamespace(
        project_manager=_DummyProjectManager(project),
        global_template_service=_DummyGlobalTemplateService(),
        _free_template_generation_locks={},
        cleared_projects=[],
    )

    def _clear_cached_style_genes(project_id=None):
        owner.cleared_projects.append(project_id)

    owner.clear_cached_style_genes = _clear_cached_style_genes
    owner._build_current_time_prompt_context = lambda: "2026-03-28 12:00:00 CST"

    service = TemplateSelectionService(owner)

    result = await service.select_free_template_for_project("proj-1", user_id=7)

    assert result["success"] is True
    assert owner.project_manager.updated[-1][1]["template_mode"] == "free"
    assert owner.project_manager.updated[-1][1]["free_template_status"] == "pending"
    assert owner.cleared_projects == ["proj-1"]

    project.project_metadata = {
        "template_mode": "free",
        "free_template_name": "AI Free",
        "free_template_html": "<section>ok</section>",
    }

    selected = await service.get_selected_global_template("proj-1")

    assert selected["template_name"] == "AI Free"
    assert selected["html_template"] == "<section>ok</section>"
    assert selected["created_by"] == "ai_free"


@pytest.mark.asyncio
async def test_template_selection_service_uses_prebuilt_free_template_prompt_once():
    project = SimpleNamespace(
        project_metadata={"template_mode": "free"},
        outline={"slides": [{"title": "封面", "content_points": ["目标", "进展"]}]},
        confirmed_requirements={"target_audience": "管理层"},
        topic="Quarterly Review",
        scenario="general",
    )

    global_template_service = _DummyGlobalTemplateService()
    owner = SimpleNamespace(
        project_manager=_DummyProjectManager(project),
        global_template_service=global_template_service,
        _free_template_generation_locks={},
        cleared_projects=[],
    )
    owner.clear_cached_style_genes = lambda project_id=None: owner.cleared_projects.append(project_id)
    owner._build_current_time_prompt_context = lambda: "2026-03-28 12:00:00 CST"

    service = TemplateSelectionService(owner)

    selected = await service.get_selected_global_template("proj-2")

    assert selected["template_name"].startswith("自由模板-")
    assert global_template_service.generated_kwargs
    kwargs = global_template_service.generated_kwargs[-1]
    assert kwargs["prompt_is_ready"] is True
    assert kwargs["generation_mode"] == "text_only"
    assert kwargs["prompt"].count("**创意要求**") == 1
    assert kwargs["prompt"].count("**技术要求**") == 1
    assert kwargs["prompt"].count("直接输出完整 HTML 模板") == 1


def test_creative_design_service_clears_owner_caches_and_files(tmp_path):
    cache_dir = tmp_path / "style_genes"
    cache_dir.mkdir()
    for filename in [
        "proj-1_style_genes.json",
        "proj-1_combined_genes_guide.json",
        "proj-1_creative_guide.json",
    ]:
        (cache_dir / filename).write_text("{}", encoding="utf-8")

    owner = SimpleNamespace(
        cache_dirs={"style_genes": cache_dir},
        _cached_style_genes={"proj-1": "genes"},
        _cached_style_genes_and_guide={"proj-1": {"style_genes": "genes", "design_guide": "guide"}},
        _cached_project_creative_guides={"proj-1": {"design_guide": "guide", "source_hash": "hash"}},
        _cached_slide_creative_guides={"proj-1:1": "slide-guide"},
        _style_genes_ready_events={"proj-1": object()},
        _project_creative_guidance_ready_events={"proj-1": object()},
        _slide_creative_guide_ready_events={"proj-1:1": object()},
    )

    service = CreativeDesignService(owner)

    summary = service._build_creative_slides_summary(
        [
            {"title": "Intro", "slide_type": "title", "content_points": ["A", "B"]},
            {"title": "Data", "slide_type": "content", "content_points": ["C"]},
        ]
    )
    assert "1. Intro" in summary
    assert "2. Data" in summary

    service.clear_cached_style_genes("proj-1")

    assert owner._cached_style_genes == {}
    assert owner._cached_style_genes_and_guide == {}
    assert owner._cached_project_creative_guides == {}
    assert owner._cached_slide_creative_guides == {}
    assert owner._style_genes_ready_events == {}
    assert owner._project_creative_guidance_ready_events == {}
    assert owner._slide_creative_guide_ready_events == {}
    assert not any(cache_dir.iterdir())
    assert service.get_cached_style_genes_info()["total_count"] == 0


def test_layout_repair_service_helpers_keep_skip_logic_and_prompt_contract():
    service = LayoutRepairService(SimpleNamespace())

    low_report = "- severity: low"
    mixed_report = "- severity: medium"
    html = "<html><head></head><body><div>Body</div></body></html>"
    injected_html = service._inject_anti_overflow_css(html)

    assert service._should_skip_layout_repair(low_report) is True
    assert service._should_skip_layout_repair(mixed_report) is False
    assert "anti-overflow-fix" in injected_html
    assert "text-overflow: unset" in injected_html
    assert '[class*="card"] > *' in injected_html
    assert ".content-layer," in injected_html

    prompt = service._build_layout_repair_prompt("<html></html>", "- issues: overflow")
    assert "```html" in prompt
    assert "overflow" in prompt
    assert "只有当页码越界、贴边、换行、漂移、被遮挡或安全区被侵占时" in prompt
    assert "不得改回 flex/grid 正文流" in prompt
    assert "inline style 表达了与上述相同的页码独立定位关系" in prompt


def test_template_generation_prompts_require_stable_page_number_anchor():
    owner = SimpleNamespace(_build_current_time_prompt_context=lambda: "2026-03-28 12:00:00 CST")
    service = TemplateSelectionService(owner)

    prompt = service._build_free_template_prompt(
        project=SimpleNamespace(topic="年度复盘", scenario="general"),
        outline={"slides": [{"title": "封面", "content_points": ["目标", "进展"]}]},
        confirmed={},
    )

    assert "页码结构必须兼容“页码 absolute 脱离文档流 + 内容层预留安全区”的固定画布骨架" in prompt
    assert "类名仅用于说明结构关系，使用 inline style 做等价实现同样有效" in prompt
    assert "母版/设计系统骨架" in prompt
    assert "不要把整页 body 做成只能容纳一种构图的大面板" in prompt
    assert prompt.count("**创意要求**") == 1
    assert prompt.count("**技术要求**") == 1

    template_prompt = GlobalMasterTemplateService._get_template_annotation_prompt_text()
    assert "页码结构必须兼容“页码 absolute 脱离文档流 + 内容层预留安全区”的固定画布骨架" in template_prompt
    assert "使用 inline style 做等价实现同样有效" in template_prompt
    assert "画布根容器负责 `position:relative` 与 1280x720 裁切" in template_prompt

    creative_prompt = GlobalMasterTemplateService._get_template_generation_creative_prompt_text()
    assert "稳定框架 + 灵活主舞台" in creative_prompt
    assert "避免所有页面共享同一块主体外框和背景实现" in creative_prompt


def test_slide_generation_service_delegates_owner_attributes():
    owner = SimpleNamespace(example_value="ok")
    service = SlideGenerationService(owner)

    assert service.example_value == "ok"


def test_slide_html_service_cleans_markdown_wrapped_html_response():
    clean_html_response = _load_class_method(
        "src/landppt/services/slide/slide_html_cleanup_service.py",
        "SlideHtmlCleanupService",
        "_clean_html_response",
    )
    owner = SimpleNamespace(_strip_think_tags=lambda raw: raw.replace("<think>internal</think>", "").strip())

    cleaned = clean_html_response(
        owner,
        "<think>internal</think>\nHere's the HTML code:\n```html\n<!DOCTYPE html>\n<html><body><div>ok</div></body></html>\n```"
    )

    assert cleaned.startswith("<!DOCTYPE html>")
    assert cleaned.endswith("</html>")
    assert "internal" not in cleaned


def test_slide_html_cleanup_does_not_warn_for_valid_html_with_error_like_text(caplog):
    owner = SimpleNamespace(_strip_think_tags=lambda raw: raw.strip())
    service = SlideHtmlCleanupService(owner)
    response = """```html
<!DOCTYPE html>
<html>
  <body>
    <div class="metric">Runtime error rate dropped to 0.2%</div>
  </body>
</html>
```"""

    with caplog.at_level("WARNING", logger="landppt.services.slide.slide_html_cleanup_service"):
        cleaned = service._clean_html_response(response)

    assert "Runtime error rate dropped" in cleaned
    assert "AI response appears to be an error message instead of HTML" not in caplog.text


def test_slide_html_cleanup_warns_for_plain_error_text(caplog):
    owner = SimpleNamespace(_strip_think_tags=lambda raw: raw.strip())
    service = SlideHtmlCleanupService(owner)

    with caplog.at_level("WARNING", logger="landppt.services.slide.slide_html_cleanup_service"):
        cleaned = service._clean_html_response("Sorry, I cannot generate HTML for this slide.")

    assert cleaned == ""
    assert "AI response appears to be an error message instead of HTML" in caplog.text


def _test_template_generation_prompts_require_stable_page_number_anchor_current():
    owner = SimpleNamespace(_build_current_time_prompt_context=lambda: "2026-03-28 12:00:00 CST")
    service = TemplateSelectionService(owner)

    prompt = service._build_free_template_prompt(
        project=SimpleNamespace(topic="Annual review", scenario="general"),
        outline={"slides": [{"title": "Cover", "content_points": ["Goal", "Progress"]}]},
        confirmed={},
    )

    assert "请显式区分标题锚点区、主舞台区、编号锚点区三类职责层" in prompt
    assert "编号锚点可以 `absolute` 脱流，也可以嵌入稳定容器" in prompt
    assert "主舞台不能被固定大外框锁死" in prompt
    assert "固定 1280x720" in prompt

    template_prompt = GlobalMasterTemplateService._get_template_annotation_prompt_text()
    assert "母版必须建立三个职责层：标题锚点区、主舞台区、编号锚点区" in template_prompt
    assert "类名仅用于说明结构关系，使用 inline style 做等价实现同样有效" in template_prompt
    assert "根容器固定 `1280x720` 且 `overflow:hidden`" in template_prompt

    creative_prompt = GlobalMasterTemplateService._get_template_generation_creative_prompt_text()
    assert "有辨识度的标题表达 + 灵活主舞台" in creative_prompt
    assert "不是千篇一律的左对齐加横线" in creative_prompt


test_template_generation_prompts_require_stable_page_number_anchor = (
    _test_template_generation_prompts_require_stable_page_number_anchor_current
)
