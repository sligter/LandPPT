from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.services.outline.project_outline_repair_service import ProjectOutlineRepairService
from landppt.services.outline.project_outline_normalization_service import ProjectOutlineNormalizationService
from landppt.services.prompts.design_prompts import DesignPrompts
from landppt.services.prompts.outline_prompts import OutlinePrompts
from landppt.services.prompts.speech_script_prompts import SpeechScriptPrompts
from landppt.services.template.template_selection_service import TemplateSelectionService
from landppt.services.video_explainer import build_reveal_schedule, video_cue_labels
from landppt.services import video_export_service


VIDEO_REQUIREMENTS = {
    "content_mode": "video_explainer",
    "custom_style_prompt": "石墨色字与青蓝连线",
}
STEP_HTML = """
<svg>
  <g data-video-cue="旧值" data-video-step="2"></g>
  <g data-video-step="2"></g>
  <g data-video-step="1" data-video-cue="数据库"></g>
  <g data-video-step="3" data-video-cue="缓存失效"></g>
</svg>
"""


def test_storyboard_prompt_carries_narrative_visual_and_research_context():
    prompt = OutlinePrompts.get_video_storyboard_prompt(
        topic="一致性",
        target_audience="第一次接触缓存的开发者",
        requirements="用一次库存更新贯穿全片",
        visual_style=VIDEO_REQUIREMENTS["custom_style_prompt"],
        page_count_instruction="最多 4 镜",
        research_context="缓存策略原始资料",
    )
    for text in ("库存更新", "青蓝连线", "最多 4 镜", "缓存策略原始资料", '"slide_type": "content"'):
        assert text in prompt


def test_video_storyboard_rejects_presentation_pages():
    repair = ProjectOutlineRepairService(None)
    slide = {"page_number": 1, "title": "为什么卖完了还有库存？", "content_points": ["库存"]}
    agenda = {"title": "库存", "slides": [{**slide, "slide_type": "agenda"}]}
    content = {"title": "库存", "slides": [{**slide, "slide_type": "content"}]}
    conclusion = {"title": "库存", "slides": [{**slide, "slide_type": "conclusion"}]}
    assert not repair._validate_outline_structure(agenda, {})
    assert repair._validate_outline_structure(agenda, VIDEO_REQUIREMENTS)
    assert repair._validate_outline_structure(conclusion, VIDEO_REQUIREMENTS)
    assert not repair._validate_outline_structure(content, VIDEO_REQUIREMENTS)


def test_storyboard_reserves_viewer_fields_for_content_and_keeps_drawing_notes():
    normalizer = ProjectOutlineNormalizationService(None)
    outline = normalizer._standardize_outline_format({
        "title": "收入的两种口径",
        "slides": [{
            "page_number": 1,
            "title": "同一条 SQL，为什么算出了两个收入数字？",
            "description": "上方绘制发票和收款两条连线。",
            "production_notes": "发票先出现。",
            "content_points": [
                "已开票收入和已收款收入按不同事件统计。",
                "阅读框架：先核验口径，再组织内容。",
            ],
            "slide_type": "content",
        }],
    })
    scene = outline["slides"][0]
    assert scene["description"] == ""
    assert scene["production_notes"] == "发票先出现。\n上方绘制发票和收款两条连线。"
    repair = ProjectOutlineRepairService(None)
    assert any("content_points[1] 含制作说明" in error for error in repair._validate_outline_structure(
        outline, VIDEO_REQUIREMENTS,
    ))
    prompt = DesignPrompts.get_single_slide_html_prompt(scene, VIDEO_REQUIREMENTS, 1, 2, "", "")
    visible, production = prompt.split("**仅供生成画面的制作备注**", 1)
    assert "已开票收入和已收款收入按不同事件统计。" in visible
    assert "绘制发票" not in visible and "阅读框架：" not in visible
    assert "绘制发票" in production


def test_video_template_and_slide_design_use_shared_explainer_rules():
    template_service = TemplateSelectionService(None)
    project = SimpleNamespace(topic="缓存")
    outline = {"slides": [{"title": "旧库存从哪来？", "slide_type": "content"}]}
    prompt = template_service._build_free_template_prompt(project, outline, VIDEO_REQUIREMENTS)
    assert "{{ page_content }}" in prompt
    assert "旧库存从哪来？" in prompt
    assert "字幕安全区" in prompt
    assert "青蓝连线" in prompt
    assert "创意愿景" in template_service._build_free_template_prompt(project, outline, {})
    brief = DesignPrompts._build_project_brief(VIDEO_REQUIREMENTS)
    assert "data-video-step" in brief
    assert "data-video-cue" in brief
    assert "data-video-step" not in DesignPrompts._build_project_brief({})
    final_prompt = DesignPrompts.get_creative_template_context_prompt(
        outline["slides"][0], "<main></main>", "旧库存从哪来？", "content",
        1, 3, "", "", **VIDEO_REQUIREMENTS,
    )
    assert "data-video-step" in final_prompt
    assert "青蓝连线" in final_prompt
    design_system = DesignPrompts.get_global_visual_constitution_prompt(
        VIDEO_REQUIREMENTS, "<main></main>", 3,
    )
    assert "所有镜头共享标题、主图和字幕安全区锚点" in design_system


def test_narration_uses_the_scene_cues_in_order():
    prompt = SpeechScriptPrompts.get_single_slide_script_prompt(
        {"title": "库存", "html_content": STEP_HTML},
        1,
        3,
        {**VIDEO_REQUIREMENTS, "video_requirements": "沿用库存例子"},
        "数据库已写入新库存",
        {"language": "zh"},
    )
    assert "数据库 → 旧值 → 缓存失效" in prompt
    assert "沿用库存例子" in prompt
    assert "数据库已写入新库存" in prompt


def test_reveal_schedule_prefers_spoken_cues_and_spaces_missing_cues():
    assert video_cue_labels(STEP_HTML) == ["数据库", "旧值", "缓存失效"]
    assert build_reveal_schedule(STEP_HTML, [(0, "数据库写入"), (2100, "接口还返回旧 值")], 6000) == {
        1: 0,
        2: 2100,
        3: 4000,
    }
    assert build_reveal_schedule(STEP_HTML, [(5900, "旧值")], 6000) == {
        1: 0,
        2: 2000,
        3: 4000,
    }
    assert build_reveal_schedule("<p>普通页面</p>", [], 3000) == {}


def test_explainer_subtitle_defaults_use_a_thin_outline():
    style = video_export_service._resolve_subtitle_style(
        video_export_service.EXPLAINER_SUBTITLE_DEFAULTS, height=1080, render_mode="live",
    )
    assert style.bold == 0
    assert style.outline == 1
    assert style.font_size == 14


@pytest.mark.asyncio
async def test_video_export_uses_live_mode_and_surfaces_recording_failure(monkeypatch):
    service = video_export_service.NarrationVideoExportService()
    monkeypatch.setattr(video_export_service, "is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(service, "_get_html_render_service", lambda: SimpleNamespace(is_available=lambda: True))
    failure = {"success": False, "error": "recording failed"}
    live = AsyncMock(return_value=failure)
    static = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(service, "_export_project_video_live", live)
    monkeypatch.setattr(service, "_export_project_video_static", static)
    explainer = SimpleNamespace(slides_data=[{}], confirmed_requirements=VIDEO_REQUIREMENTS)
    assert await service.export_project_video(project=explainer, render_mode="static") == failure
    live.assert_awaited_once()
    static.assert_not_awaited()

    presentation = SimpleNamespace(slides_data=[{}], confirmed_requirements={})
    assert await service.export_project_video(project=presentation) == {"success": True}
    static.assert_awaited_once()
