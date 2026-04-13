from pathlib import Path

from landppt.services.prompts.speech_script_prompts import SpeechScriptPrompts


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "src/landppt/web/route_modules/speech_script_routes.py"
SERVICE_FILE = ROOT / "src/landppt/services/speech_script_service.py"
JS_FILE = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.speechScriptsManage.js"
TEMPLATE_FILE = ROOT / "src/landppt/web/templates/pages/project/project_slides_editor.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_humanize_prompt_contains_humanizer_constraints():
    prompt = SpeechScriptPrompts.get_humanized_script_prompt(
        "这是一段偏模板化的演讲稿，请帮我改得更自然。",
        {
            "language": "zh",
            "tone": "conversational",
            "target_audience": "general_public",
            "language_complexity": "moderate",
            "speaking_pace": "normal",
            "custom_style_prompt": "",
        },
    )

    assert "Humanizer-zh" in prompt
    assert "宣传腔" in prompt
    assert "只输出改写后的纯文本" in prompt
    assert "删除填充短语" in prompt
    assert "打破公式结构" in prompt
    assert "快速检查清单" in prompt
    assert "不要以“好”“好的”“那么”“接下来”“下面我来讲”等口头起手式开场" in prompt


def test_single_slide_prompt_discourages_filler_openers():
    prompt = SpeechScriptPrompts.get_single_slide_script_prompt(
        {
            "title": "增长分析",
            "html_content": "<p>本季度收入同比增长20%，核心来自老客户复购。</p>",
        },
        0,
        5,
        {
            "topic": "季度经营复盘",
            "scenario": "内部汇报",
        },
        "",
        {
            "language": "zh",
            "tone": "conversational",
            "target_audience": "general_public",
            "language_complexity": "moderate",
            "include_transitions": True,
            "speaking_pace": "normal",
            "custom_style_prompt": "",
        },
    )

    assert "开头直接进入当前页核心内容" in prompt
    assert "不要先说“好”“好的”“那么”“接下来”“下面我来讲”等口头起手式" in prompt


def test_speech_script_humanize_route_and_ui_are_wired():
    route_text = _read(ROUTE_FILE)
    service_text = _read(SERVICE_FILE)
    js_text = _read(JS_FILE)
    template_text = _read(TEMPLATE_FILE)

    assert '@router.post("/api/projects/{project_id}/speech-scripts/humanize")' in route_text
    assert "async def humanize_speech_scripts(" in route_text
    assert "class SpeechScriptHumanizeRequest(BaseModel):" in route_text
    assert "progress_tracker.create_task_async(" in route_text
    assert 'asyncio.create_task(humanize_async())' in route_text
    assert "演讲稿一键人话已开始，请查看进度" in route_text
    assert "async def humanize_script(" in service_text
    assert "get_humanized_script_prompt(" in service_text
    assert "function humanizeSingleSpeechScript(" in js_text
    assert "function humanizeAllSpeechScripts(" in js_text
    assert "function startSpeechHumanizeProgressTracking(" in js_text
    assert "speech-scripts/progress/${taskId}" in js_text
    assert "showProgressToast(`正在处理第${slideIndex + 1}页演讲稿人话化...`, 0)" in js_text
    assert "speech-script-humanize-btn" in js_text
    assert "speechHumanizeAllBtn" in js_text
    assert "projectSlidesEditor.speechScriptsManage.js?v=20260409-speech-humanize-v3" in template_text
