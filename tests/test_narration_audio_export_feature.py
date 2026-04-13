from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NARRATION_ROUTES = ROOT / "src/landppt/web/route_modules/narration_routes.py"
EXPORT_ROUTES = ROOT / "src/landppt/web/route_modules/export_routes.py"
BACKGROUND_TASKS = ROOT / "src/landppt/services/background_tasks.py"
NARRATION_JS = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectEditorNarration.js"
SPEECH_MANAGE_JS = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.speechScriptsManage.js"
TEMPLATE_FILE = ROOT / "src/landppt/web/templates/pages/project/project_slides_editor.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_narration_audio_export_route_and_download_support_are_wired():
    narration_routes_text = _read(NARRATION_ROUTES)
    export_routes_text = _read(EXPORT_ROUTES)
    background_tasks_text = _read(BACKGROUND_TASKS)

    assert '@router.post("/api/projects/{project_id}/export/narration-audio")' in narration_routes_text
    assert "async def export_narration_audio(" in narration_routes_text
    assert 'task_type="narration_audio_export"' in narration_routes_text
    assert '"audio_path": zip_path' in narration_routes_text
    assert "narration_audio_export" in background_tasks_text
    assert "narration_audio_export" in export_routes_text
    assert '"audio_path"' in export_routes_text
    assert "X-Export-Method\": \"Narration-Audio\"" in export_routes_text


def test_narration_audio_export_ui_is_wired():
    narration_js_text = _read(NARRATION_JS)
    speech_manage_js_text = _read(SPEECH_MANAGE_JS)
    template_text = _read(TEMPLATE_FILE)

    assert "async function exportNarrationAudio()" in narration_js_text
    assert "/export/narration-audio" in narration_js_text
    assert "triggerFileDownload(downloadUrl)" in narration_js_text
    assert "导出讲解音频" in speech_manage_js_text
    assert 'onclick="exportNarrationAudio()"' in speech_manage_js_text
    assert "projectEditorNarration.js?v=20260409-narration-audio-export-v1" in template_text
