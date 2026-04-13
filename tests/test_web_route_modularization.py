from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_main_router_registers_extracted_route_modules():
    routes_text = _read("src/landppt/web/routes.py")

    assert 'from .route_modules.ai_edit_routes import router as ai_edit_router' in routes_text
    assert 'from .route_modules.config_routes import router as config_router' in routes_text
    assert 'from .route_modules.export_routes import router as export_router' in routes_text
    assert 'from .route_modules.outline_routes import router as outline_router' in routes_text
    assert 'from .route_modules.project_routes import router as project_router' in routes_text
    assert 'from .route_modules.share_routes import router as share_router' in routes_text
    assert 'from .route_modules.slide_routes import router as slide_router' in routes_text
    assert 'from .route_modules.speech_script_routes import router as speech_script_router' in routes_text
    assert 'from .route_modules.narration_routes import router as narration_router' in routes_text
    assert 'from .route_modules.template_routes import router as template_router' in routes_text

    assert "router.include_router(config_router)" in routes_text
    assert "router.include_router(project_router)" in routes_text
    assert "router.include_router(export_router)" in routes_text
    assert "router.include_router(outline_router)" in routes_text
    assert "router.include_router(share_router)" in routes_text
    assert "router.include_router(slide_router)" in routes_text
    assert "router.include_router(ai_edit_router)" in routes_text
    assert "router.include_router(speech_script_router)" in routes_text
    assert "router.include_router(narration_router)" in routes_text
    assert "router.include_router(template_router)" in routes_text


def test_legacy_route_handlers_were_removed_from_main_router_file():
    routes_text = _read("src/landppt/web/routes.py")

    assert "_legacy_router" not in routes_text
    assert "async def web_shared_presentation(" not in routes_text
    assert "async def generate_share_link(" not in routes_text
    assert "async def generate_narration_audio(" not in routes_text
    assert "async def get_selected_global_template(" not in routes_text
    assert "async def generate_file_outline(" not in routes_text
    assert "async def confirm_project_requirements(" not in routes_text
    assert "async def export_project_pdf(" not in routes_text
    assert "async def export_project_pptx(" not in routes_text
    assert "async def download_task_result(" not in routes_text
    assert "async def web_dashboard(" not in routes_text
    assert "async def batch_regenerate_slides(" not in routes_text
    assert "async def ai_slide_edit(" not in routes_text
    assert "async def generate_speech_script(" not in routes_text
    assert "class AISlideEditRequest" not in routes_text
    assert "class SlideBatchRegenerateRequest" not in routes_text
    assert '@router.get("/share/{share_token}"' not in routes_text
    assert '@router.post("/api/projects/{project_id}/narration/generate")' not in routes_text
    assert '@router.get("/api/projects/{project_id}/selected-global-template")' not in routes_text
    assert '@router.post("/projects/{project_id}/generate-file-outline")' not in routes_text
    assert '@router.post("/projects/{project_id}/confirm-requirements")' not in routes_text
    assert '@router.get("/api/projects/{project_id}/export/pdf")' not in routes_text
    assert '@router.get("/api/projects/{project_id}/export/pptx")' not in routes_text
    assert '@router.get("/api/landppt/tasks/{task_id}/download")' not in routes_text
    assert '@router.get("/dashboard"' not in routes_text
    assert '@router.post("/api/projects/{project_id}/slides/batch-regenerate")' not in routes_text
    assert '@router.post("/api/ai/slide-edit")' not in routes_text
    assert '@router.post("/api/projects/{project_id}/speech-script/generate")' not in routes_text


def test_extracted_route_modules_keep_expected_public_paths():
    config_text = _read("src/landppt/web/route_modules/config_routes.py")
    export_text = _read("src/landppt/web/route_modules/export_routes.py")
    outline_text = _read("src/landppt/web/route_modules/outline_routes.py")
    outline_generation_text = _read("src/landppt/web/route_modules/outline_generation_routes.py")
    outline_requirements_text = _read("src/landppt/web/route_modules/outline_requirements_routes.py")
    outline_support_text = _read("src/landppt/web/route_modules/outline_support.py")
    project_text = _read("src/landppt/web/route_modules/project_routes.py")
    project_lifecycle_text = _read("src/landppt/web/route_modules/project_lifecycle_routes.py")
    project_workspace_text = _read("src/landppt/web/route_modules/project_workspace_routes.py")
    project_library_text = _read("src/landppt/web/route_modules/project_library_routes.py")
    share_text = _read("src/landppt/web/route_modules/share_routes.py")
    slide_text = _read("src/landppt/web/route_modules/slide_routes.py")
    speech_text = _read("src/landppt/web/route_modules/speech_script_routes.py")
    ai_edit_text = _read("src/landppt/web/route_modules/ai_edit_routes.py")
    narration_text = _read("src/landppt/web/route_modules/narration_routes.py")
    template_text = _read("src/landppt/web/route_modules/template_routes.py")

    for marker in [
        '@router.get("/home"',
        '@router.get("/ai-config"',
        '@router.get("/api/config/all")',
        '@router.post("/api/ai/providers/test")',
        '@router.post("/api/ai/providers/openai/test")',
    ]:
        assert marker in config_text

    for marker in [
        '@router.get("/api/projects/{project_id}/export/pdf")',
        '@router.post("/api/projects/{project_id}/export/pdf/async")',
        '@router.get("/api/projects/{project_id}/export/pptx")',
        '@router.post("/api/projects/{project_id}/export/pptx-images")',
        '@router.get("/api/landppt/tasks/{task_id}")',
        '@router.get("/api/landppt/tasks/{task_id}/download")',
        '@router.get("/api/projects/{project_id}/export/html")',
    ]:
        assert marker in export_text

    for marker in [
        "from .outline_generation_routes import router as outline_generation_router",
        "from .outline_requirements_routes import router as outline_requirements_router",
        "router.include_router(outline_requirements_router)",
        "router.include_router(outline_generation_router)",
    ]:
        assert marker in outline_text

    for marker in [
        '@router.get("/projects/{project_id}/todo-editor")',
        '@router.post("/projects/{project_id}/confirm-requirements")',
    ]:
        assert marker in outline_requirements_text

    for marker in [
        "from .project_lifecycle_routes import router as project_lifecycle_router",
        "from .project_workspace_routes import router as project_workspace_router",
        "from .project_library_routes import router as project_library_router",
        "router.include_router(project_lifecycle_router)",
        "router.include_router(project_workspace_router)",
        "router.include_router(project_library_router)",
    ]:
        assert marker in project_text

    for marker in [
        '@router.get("/scenarios"',
        '@router.get("/research"',
        '@router.get("/dashboard"',
        '@router.get("/projects"',
        '@router.post("/projects/create"',
        '@router.post("/projects/{project_id}/start-workflow")',
    ]:
        assert marker in project_lifecycle_text

    for marker in [
        '@router.get("/projects/{project_id}/todo"',
        '@router.get("/projects/{project_id}/edit"',
        '@router.get("/projects/{project_id}/fullscreen"',
        '@router.get("/temp/{file_path:path}")',
    ]:
        assert marker in project_workspace_text

    for marker in [
        '@router.get("/image-gallery"',
        '@router.get("/global-master-templates"',
        '@router.get("/projects/{project_id}/template-selection"',
    ]:
        assert marker in project_library_text

    for marker in [
        '@router.post("/api/projects/{project_id}/slides/{slide_number}/regenerate/async")',
        '@router.post("/api/projects/{project_id}/slides/batch-regenerate")',
        '@router.get("/api/projects/{project_id}/slides/stream")',
        '@router.post("/api/projects/{project_id}/slides/batch-save")',
    ]:
        assert marker in slide_text

    for marker in [
        '@router.post("/api/ai/slide-edit")',
        '@router.post("/api/ai/element-edit")',
        '@router.post("/api/ai/slide-edit/stream")',
        '@router.post("/api/ai/optimize-outline")',
        '@router.post("/api/ai/auto-generate-slide-images")',
    ]:
        assert marker in ai_edit_text
    assert "from bs4 import BeautifulSoup" in ai_edit_text

    for marker in [
        '@router.post("/api/projects/{project_id}/speech-script/generate")',
        '@router.post("/api/projects/{project_id}/speech-script/export")',
        '@router.get("/api/projects/{project_id}/speech-scripts")',
        '@router.put("/api/projects/{project_id}/speech-scripts/slide/{slide_index}")',
    ]:
        assert marker in speech_text

    for marker in [
        '@router.get("/projects/{project_id}/outline-stream")',
        '@router.post("/projects/{project_id}/generate-outline")',
        '@router.post("/projects/{project_id}/regenerate-outline")',
        '@router.post("/projects/{project_id}/generate-file-outline")',
    ]:
        assert marker in outline_generation_text
    assert "from ...api.models import FileOutlineGenerationRequest, PPTProject" in outline_support_text

    for marker in [
        '@router.get("/share/{share_token}"',
        '@router.get("/api/share/{share_token}/slides-data")',
        '@router.post("/api/projects/{project_id}/share/generate")',
    ]:
        assert marker in share_text

    for marker in [
        '@router.post("/api/projects/{project_id}/narration/generate")',
        '@router.get("/api/projects/{project_id}/narration/audio/{slide_index}")',
        '@router.post("/api/projects/{project_id}/export/narration-audio")',
        '@router.post("/api/projects/{project_id}/export/narration-video")',
    ]:
        assert marker in narration_text

    for marker in [
        '@router.get("/api/projects/{project_id}/selected-global-template")',
        '@router.get("/api/projects/{project_id}/free-template")',
        '@router.post("/api/projects/{project_id}/free-template/generate")',
    ]:
        assert marker in template_text


def test_outline_routes_delegate_helpers_to_outline_support_module():
    export_routes_text = _read("src/landppt/web/route_modules/export_routes.py")
    export_support_text = _read("src/landppt/web/route_modules/export_support.py")
    outline_routes_text = _read("src/landppt/web/route_modules/outline_routes.py")
    outline_generation_text = _read("src/landppt/web/route_modules/outline_generation_routes.py")
    outline_requirements_text = _read("src/landppt/web/route_modules/outline_requirements_routes.py")
    outline_support_text = _read("src/landppt/web/route_modules/outline_support.py")

    assert "from .export_support import (" in export_routes_text

    for marker in [
        "class ImagePPTXExportRequest(BaseModel):",
        "def _resolve_export_base_url(",
        "async def _generate_pdf_with_pyppeteer(",
        "def _generate_html_export_sync(",
    ]:
        assert marker not in export_routes_text
        assert marker in export_support_text

    assert "@router.get(" not in outline_routes_text
    assert "@router.post(" not in outline_routes_text
    assert "async def " not in outline_routes_text
    assert "from .outline_support import (" in outline_generation_text
    assert "from .outline_support import (" in outline_requirements_text

    for marker in [
        "def _save_uploaded_files_for_confirmed_requirements(",
        "async def _stream_outline_from_confirmed_sources_v2(",
        "async def _process_url_sources_for_outline(",
        "async def _process_uploaded_files_for_outline(",
    ]:
        assert marker not in outline_generation_text
        assert marker not in outline_requirements_text
        assert marker in outline_support_text


def test_main_router_is_now_aggregator_shell():
    routes_text = _read("src/landppt/web/routes.py")

    assert "@router.get(" not in routes_text
    assert "@router.post(" not in routes_text
    assert "@router.put(" not in routes_text
    assert "@router.delete(" not in routes_text
    assert "class AISlideEditRequest" not in routes_text
    assert "class SpeechScriptExportRequest" not in routes_text


def test_project_routes_are_now_aggregator_shell():
    project_text = _read("src/landppt/web/route_modules/project_routes.py")

    assert "@router.get(" not in project_text
    assert "@router.post(" not in project_text
    assert "async def " not in project_text


def test_frontend_template_grouping_is_applied_to_route_handlers():
    auth_text = _read("src/landppt/auth/routes.py")
    admin_text = _read("src/landppt/web/admin_routes.py")
    community_text = _read("src/landppt/web/community_routes.py")
    credits_text = _read("src/landppt/web/credits_routes.py")
    config_text = _read("src/landppt/web/route_modules/config_routes.py")

    for marker in [
        'pages/auth/login.html',
        'pages/auth/register.html',
        'pages/auth/forgot_password.html',
        'pages/account/profile.html',
    ]:
        assert marker in auth_text

    for marker in [
        'pages/admin/users.html',
        'pages/admin/credits.html',
        'pages/admin/smtp.html',
        'pages/admin/community.html',
    ]:
        assert marker in admin_text

    assert 'pages/community/sponsor_thanks.html' in community_text
    assert 'pages/account/user_credits.html' in credits_text
    assert 'pages/home/index.html' in config_text
    assert 'pages/settings/ai_config.html' in config_text


def test_admin_env_editor_surface_was_removed_but_db_config_routes_remain():
    admin_text = _read("src/landppt/web/admin_routes.py")
    admin_body_text = _read("src/landppt/web/templates/components/admin/community/body_1.html")
    admin_script_text = _read("src/landppt/web/templates/components/admin/community/script_1.html")
    config_api_text = _read("src/landppt/api/config_api.py")

    for marker in [
        'EnvFileUpdateRequest',
        'def _get_env_file_path(',
        'async def _reload_runtime_from_env(',
        '@router.get("/api/system-env-file")',
        '@router.post("/api/system-env-file")',
    ]:
        assert marker not in admin_text

    for marker in [
        '系统环境配置（.env）',
        'systemEnvSummary',
        'systemEnvPath',
        'system_env_editor',
        'reloadEnvEditorBtn',
        'saveEnvEditorBtn',
    ]:
        assert marker not in admin_body_text

    for marker in [
        'systemEnvLoaded',
        'systemEnvPath',
        'updateSystemEnvSummary',
        'loadSystemEnvFile',
        'saveSystemEnvFile',
        '/admin/api/system-env-file',
    ]:
        assert marker not in admin_script_text

    for marker in [
        '@router.get("/api/config/system")',
        '@router.post("/api/config/system")',
        '@router.get("/api/config/all")',
        '@router.post("/api/config/all")',
    ]:
        assert marker in config_api_text


def test_component_templates_replace_legacy_partials_directories():
    template_expectations = {
        "src/landppt/web/templates/pages/settings/ai_config.html": "components/settings/ai_config/",
        "src/landppt/web/templates/pages/admin/community.html": "components/admin/community/",
        "src/landppt/web/templates/pages/project/project_detail.html": "components/project/detail/",
        "src/landppt/web/templates/pages/project/project_fullscreen_presentation.html": "components/project/fullscreen_presentation/",
        "src/landppt/web/templates/pages/project/todo_board.html": "components/project/todo_board/",
        "src/landppt/web/templates/pages/project/todo_board_with_editor.html": "components/project/todo_board_with_editor/",
        "src/landppt/web/templates/pages/template/global_master_templates.html": "components/template/global_master_templates/",
        "src/landppt/web/templates/pages/template/template_selection.html": "components/template/template_selection/",
    }

    for relative_path, marker in template_expectations.items():
        content = _read(relative_path)
        assert marker in content
        assert "partials/" not in content


def test_compatibility_entrypoints_and_templates_were_removed():
    project_lifecycle_text = _read("src/landppt/web/route_modules/project_lifecycle_routes.py")
    outline_requirements_text = _read("src/landppt/web/route_modules/outline_requirements_routes.py")
    error_template_text = _read("src/landppt/web/templates/error.html")

    for marker in [
        '@router.get("/upload"',
        '@router.post("/upload"',
        '@router.get("/demo"',
        'pages/project/upload.html',
        'pages/project/upload_result.html',
        'pages/project/demo.html',
    ]:
        assert marker not in project_lifecycle_text

    assert '@router.get("/projects/{project_id}/requirements"' not in outline_requirements_text
    assert "pages/project/project_requirements.html" not in outline_requirements_text
    assert "/demo" not in error_template_text

    for relative_path in [
        "src/landppt/web/templates/pages/project/demo.html",
        "src/landppt/web/templates/pages/project/project_requirements.html",
        "src/landppt/web/templates/pages/project/upload.html",
        "src/landppt/web/templates/pages/project/upload_result.html",
    ]:
        assert not (ROOT / relative_path).exists()


def test_project_slides_editor_template_uses_extracted_assets():
    template_text = _read("src/landppt/web/templates/pages/project/project_slides_editor.html")

    assert '/static/css/pages/project/slides_editor/projectSlidesEditor.css' in template_text
    assert 'id="projectEditorConfigScript"' in template_text
    assert '/static/js/pages/project/slides_editor/projectEditorShareExport.js' in template_text
    assert '/static/js/pages/project/slides_editor/projectSlidesEditor.core.js' in template_text
    assert '/static/js/pages/project/slides_editor/projectSlidesEditor.tools.js' in template_text
    assert '/static/js/pages/project/slides_editor/projectEditorNarration.js' in template_text

    assert "<style>" not in template_text

    inline_script_marker = '<script>\n        let currentSlideIndex = 0;'
    assert inline_script_marker not in template_text


def test_extracted_editor_assets_do_not_embed_template_syntax():
    for relative_path in [
        "src/landppt/web/static/css/pages/project/slides_editor/projectSlidesEditor.css",
        "src/landppt/web/static/js/pages/project/slides_editor/projectEditorShareExport.js",
        "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.core.js",
        "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.tools.js",
        "src/landppt/web/static/js/pages/project/slides_editor/projectEditorNarration.js",
    ]:
        content = _read(relative_path)
        assert "{{" not in content
        assert "{%" not in content


def test_editor_page_modules_own_their_responsibilities():
    core_text = _read("src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.core.js")
    tools_text = _read("src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.tools.js")
    share_text = _read("src/landppt/web/static/js/pages/project/slides_editor/projectEditorShareExport.js")
    narration_text = _read("src/landppt/web/static/js/pages/project/slides_editor/projectEditorNarration.js")

    for marker in [
        "function downloadHTML()",
        "function showNotification(message, type = 'info')",
        "async function showShareDialog()",
        "async function exportToPDF()",
        "async function exportToPPTX()",
        "async function exportToPPTXAsImages()",
    ]:
        assert marker not in core_text
        assert marker in share_text

    for marker in [
        "function getNarrationLanguage()",
        "function handleNarrationProviderChange()",
        "async function generateNarrationAudio()",
        "async function exportNarrationAudio()",
        "async function exportNarrationVideo()",
    ]:
        assert marker not in tools_text
        assert marker in narration_text


def test_enhanced_ppt_service_delegates_file_outline_workflow_to_extracted_service():
    service_text = _read("src/landppt/services/enhanced_ppt_service.py")

    assert "from .outline.outline_workflow_service import OutlineWorkflowService" in service_text
    assert "self.outline_workflow = OutlineWorkflowService(self)" in service_text
    assert "async for event in self.outline_workflow.generate_outline_from_file_streaming(request):" in service_text
    assert "return await self.outline_workflow.generate_outline_from_file(request)" in service_text

    for marker in [
        "def _build_validation_requirements(",
        "def _build_file_info(",
        "def _build_processing_stats(",
        "def _get_slides_range_from_request(",
        "def _get_chunk_size_from_request(",
        "def _get_chunk_strategy_from_request(",
        "def _is_enhanced_research_file(",
        "def _create_outline_from_file_content(",
    ]:
        assert marker not in service_text
