from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.api.models import PPTProject
from landppt.services.prompts.speech_script_prompts import SpeechScriptPrompts
from landppt.services.speech_script_service import SpeechScriptCustomization, SpeechScriptService


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


def test_single_slide_prompt_keeps_cohesion_without_explicit_transitions():
    prompt = SpeechScriptPrompts.get_single_slide_script_prompt(
        {
            "title": "增长分析",
            "html_content": "<p>本季度收入同比增长20%，核心来自老客户复购。</p>",
        },
        1,
        5,
        {
            "topic": "季度经营复盘",
            "scenario": "内部汇报",
            "slide_sequence": "第1页：经营目标；当前页：增长分析；第3页：成本结构",
            "previous_slide_context": "经营目标：本季度优先提升续费与复购。",
            "previous_script_context": "上一页我们先明确了本季度的经营目标，重点是把续费率和复购率拉起来。",
            "next_slide_context": "成本结构：获客成本下降，但交付成本上升。",
        },
        "经营目标：本季度优先提升续费与复购。",
        {
            "language": "zh",
            "tone": "conversational",
            "target_audience": "general_public",
            "language_complexity": "moderate",
            "include_transitions": False,
            "speaking_pace": "normal",
            "custom_style_prompt": "",
        },
    )

    assert "包含过渡语句：否" in prompt
    assert "过渡语句已关闭" in prompt
    assert "隐性承接" in prompt
    assert "不要把本页写成孤立段落" in prompt
    assert "上一页演讲稿参考：上一页我们先明确了本季度的经营目标" in prompt
    assert "下一页内容概要：成本结构" in prompt


def test_service_prompt_includes_previous_generated_script_context():
    service = SpeechScriptService(user_id=1)
    project = PPTProject(
        project_id="demo-project",
        title="季度经营复盘",
        scenario="内部汇报",
        topic="季度经营复盘",
        slides_data=[
            {
                "title": "经营目标",
                "html_content": "<p>本季度优先提升续费与复购。</p>",
            },
            {
                "title": "增长分析",
                "html_content": "<p>本季度收入同比增长20%，核心来自老客户复购。</p>",
            },
            {
                "title": "成本结构",
                "html_content": "<p>获客成本下降，但交付成本上升。</p>",
            },
        ],
    )

    prompt = service._create_speech_script_prompt(
        project.slides_data[1],
        1,
        3,
        project,
        "经营目标：本季度优先提升续费与复购。",
        SpeechScriptCustomization(include_transitions=False),
        previous_script_context="上一页我们明确了目标：续费和复购是这次复盘的主线。",
    )

    assert "页序概览：第1页：经营目标；当前页：增长分析；第3页：成本结构" in prompt
    assert "上一页内容概要：经营目标：本季度优先提升续费与复购。" in prompt
    assert "上一页演讲稿参考：上一页我们明确了目标：续费和复购是这次复盘的主线。" in prompt
    assert "下一页内容概要：成本结构: 获客成本下降，但交付成本上升。" in prompt


@pytest.mark.asyncio
async def test_video_narration_uses_outline_facts_and_retries_a_leaked_direction(monkeypatch):
    service = SpeechScriptService(user_id=1)
    spoken = "开票和收款是两个不同的事件，所以同一张表可以算出两种收入。"
    provider = SimpleNamespace(text_completion=AsyncMock(side_effect=[
        SimpleNamespace(content="制作说明：先画发票，再画收款。"),
        SimpleNamespace(content=f"<think>草稿</think>{spoken}"),
    ]))
    monkeypatch.setattr(service, "ai_provider", provider)
    project = PPTProject(
        project_id="demo",
        title="收入",
        topic="为什么有两个收入数字？",
        scenario="general",
        confirmed_requirements={"content_mode": "video_explainer"},
        outline={"slides": [{
            "title": "为什么有两个收入数字？",
            "content_points": ["已开票收入按发票统计，已收款收入按到款统计。"],
            "production_notes": "上方绘制发票图标。",
        }]},
    )
    slide = {
        "title": project.topic,
        "html_content": "<style>/* 渲染私有变量 */</style><p>画面说明：画发票图标。</p>",
    }
    script = await service._generate_script_for_slide(
        slide, 0, 1, project, "", SpeechScriptCustomization(),
    )
    assert script == spoken
    first_prompt = provider.text_completion.await_args_list[0].kwargs["prompt"]
    assert "已开票收入按发票统计，已收款收入按到款统计。" in first_prompt
    for leaked in ("渲染私有变量", "画发票图标", "上方绘制发票图标"):
        assert leaked not in first_prompt
    assert "上次输出有制作说明" in provider.text_completion.await_args.kwargs["prompt"]


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
    assert "projectSlidesEditor.speechScriptsManage.js?v=20260802-auto-result-v1" in template_text
