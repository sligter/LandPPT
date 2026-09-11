"""SVG 页面生成服务与提示词的测试：循环、修复轮、降级、报告、模式解析。"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.services.prompts import prompts_manager
from landppt.services.prompts.svg_page_prompts import SvgPagePrompts
from landppt.services.slide.slide_svg_page_service import (
    SVG_PAGE_MAX_ATTEMPTS,
    SlideSvgPageService,
    collect_image_urls,
)
from landppt.services.slide.svg_page.constants import CANVAS_CONTRACT_TEXT
from landppt.services.slide.svg_page.defs_library import SYMBOL_IDS
from landppt.services.slide.svg_page.render_mode import (
    RENDER_MODE_HTML,
    RENDER_MODE_SVG,
    attach_render_mode,
    normalize_render_mode,
    render_mode_from_requirements,
    resolve_project_render_mode,
)


def page(body: str) -> str:
    return (
        "```svg\n"
        '<svg viewBox="0 0 1280 720" width="1280" height="720">'
        '<g data-role="background"><rect width="1280" height="720" fill="#0f172a"/></g>'
        '<g data-role="title"><text x="96" y="110" font-size="44" fill="#fff">标题</text></g>'
        f'<g data-role="stage">{body}</g>'
        '<g data-role="footer"><text x="1200" y="690" font-size="16" fill="#aaa" text-anchor="end">2 / 5</text></g>'
        "</svg>\n```"
    )


CLEAN = page(
    '<text x="96" y="240" font-size="28" fill="#fff" data-box-w="1000">华东区域营收同比增长十八个百分点。</text>'
)
OVERLAPPING = page(
    '<text id="a" x="96" y="240" font-size="28" fill="#fff">三季度营收十二点四亿元</text>'
    '<text id="b" x="96" y="246" font-size="28" fill="#fff">同比增长十八点四个百分点</text>'
)


def make_owner(responses, tmp_path, *, metadata=None):
    replies = [
        SimpleNamespace(
            content=text,
            model="test-model",
            finish_reason="stop",
            usage={"total_tokens": 100 + i},
        )
        for i, text in enumerate(responses)
    ]
    project = SimpleNamespace(
        project_metadata=metadata if metadata is not None else {"render_mode": "svg"}
    )
    return SimpleNamespace(
        user_id=7,
        cache_dirs={"style_genes": tmp_path},
        project_manager=SimpleNamespace(get_project=AsyncMock(return_value=project)),
        _text_completion_for_role=AsyncMock(side_effect=replies),
        _get_creative_design_inputs=AsyncMock(
            return_value=("- 深色科技感", "全局规则", "本页聚焦增长驱动")
        ),
        _process_slide_image=AsyncMock(return_value=None),
        _build_slide_context=lambda slide, page_number, total: "**普通内容页**",
        get_selected_global_template=AsyncMock(return_value=None),
    )


def slide():
    return {
        "title": "季度营收",
        "content_points": ["华东 +18%", "华南 +9%"],
        "slide_type": "content",
    }


@pytest.mark.asyncio
async def test_clean_page_is_accepted_first_try_and_reported(tmp_path):
    owner = make_owner([CLEAN], tmp_path)
    service = SlideSvgPageService(owner)
    data = slide()
    html = await service._generate_single_slide_svg_with_prompts(
        data, {"topic": "营收"}, "system", 2, 5, project_id="proj"
    )

    assert html.startswith("<!DOCTYPE html>") and 'data-render-mode="svg"' in html
    assert "<tspan" not in html or "data-lines" in html
    assert data["render_mode"] == RENDER_MODE_SVG
    assert "_generation_degraded" not in data
    report = data["svg_report"]
    assert report["outcome"] == "ok" and len(report["attempts"]) == 1
    assert report["attempts"][0]["blocking"] == 0 and report["attempts"][0][
        "usage"
    ] == {"total_tokens": 100}
    first = report["attempts"][0]
    assert "before_repair" in first
    assert Path(first["artifacts"]["raw"]).is_file()
    assert Path(first["artifacts"]["repaired"]).is_file()
    owner._text_completion_for_role.assert_awaited_once()
    call = owner._text_completion_for_role.await_args
    assert call.kwargs["system_prompt"].startswith("你是幻灯片页面的 SVG 绘制器")
    assert (
        "SVG 画布契约" in call.kwargs["prompt"]
        and "本页聚焦增长驱动" in call.kwargs["prompt"]
    )
    lines = (tmp_path / "proj_svg_pages.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["outcome"] == "ok"


@pytest.mark.asyncio
async def test_blocking_defects_trigger_targeted_repair_round(tmp_path):
    owner = make_owner([OVERLAPPING, CLEAN], tmp_path)
    service = SlideSvgPageService(owner)
    data = slide()
    await service._generate_single_slide_svg_with_prompts(
        data, {}, "system", 2, 5, project_id="proj"
    )

    assert owner._text_completion_for_role.await_count == 2
    repair_prompt = owner._text_completion_for_role.await_args_list[1].kwargs["prompt"]
    assert "必须修复" in repair_prompt and "[overlap]" in repair_prompt
    assert "```svg" in repair_prompt and 'id="a"' in repair_prompt
    report = data["svg_report"]
    assert report["outcome"] == "ok"
    assert (
        report["attempts"][0]["blocking"] == 1
        and report["attempts"][1]["blocking"] == 0
    )
    assert "_generation_degraded" not in data


@pytest.mark.asyncio
async def test_persistent_defects_keep_best_candidate_but_mark_degraded(tmp_path):
    owner = make_owner([OVERLAPPING] * SVG_PAGE_MAX_ATTEMPTS, tmp_path)
    service = SlideSvgPageService(owner)
    data = slide()
    html = await service._generate_single_slide_svg_with_prompts(
        data, {}, "system", 2, 5, project_id="proj"
    )

    assert owner._text_completion_for_role.await_count == SVG_PAGE_MAX_ATTEMPTS
    assert data["_generation_degraded"] is True
    assert data["svg_report"]["outcome"] == "accepted-with-defects"
    assert "三季度营收十二点四亿元" in html  # 保留最好的候选，而不是占位页


@pytest.mark.asyncio
async def test_unusable_replies_fall_back_to_placeholder(tmp_path):
    owner = make_owner(
        [
            "抱歉，我无法完成。",
            "```svg\n<svg viewBox='0 0 1 1'><rect",
            "<svg><rect width=1></svg>",
        ],
        tmp_path,
    )
    service = SlideSvgPageService(owner)
    data = slide()
    html = await service._generate_single_slide_svg_with_prompts(
        data, {}, "system", 4, 5, project_id="proj"
    )

    report = data["svg_report"]
    assert data["_generation_degraded"] is True and report["outcome"] == "placeholder"
    errors = [attempt["error"] for attempt in report["attempts"]]
    assert (
        errors[0] == "no-svg"
        and errors[1] == "truncated"
        and errors[2].startswith("sanitize:")
    )
    assert "季度营收" in html and "请重新生成" in html and "华东 +18%" in html
    second_prompt = owner._text_completion_for_role.await_args_list[1].kwargs["prompt"]
    assert "没有包含完整的 <svg>" in second_prompt
    third_prompt = owner._text_completion_for_role.await_args_list[2].kwargs["prompt"]
    assert "被截断" in third_prompt


@pytest.mark.asyncio
async def test_model_exceptions_are_recorded_and_do_not_abort_the_loop(tmp_path):
    owner = make_owner([CLEAN], tmp_path)
    owner._text_completion_for_role = AsyncMock(
        side_effect=[
            RuntimeError("boom"),
            SimpleNamespace(content=CLEAN, model="m", finish_reason="stop", usage=None),
        ]
    )
    service = SlideSvgPageService(owner)
    data = slide()
    await service._generate_single_slide_svg_with_prompts(
        data, {}, "system", 1, 1, project_id="proj"
    )
    assert data["svg_report"]["outcome"] == "ok"
    assert data["svg_report"]["attempts"][0]["error"].startswith("model:")


@pytest.mark.asyncio
async def test_image_urls_are_offered_and_enforced(tmp_path):
    owner = make_owner(
        [
            page(
                '<image href="https://cdn.example.com/other.png" x="96" y="200" width="200" height="120"/><image href="https://cdn.example.com/ok.png" x="400" y="200" width="200" height="120"/>'
            )
        ],
        tmp_path,
    )
    images = SimpleNamespace(
        total_count=1,
        to_dict=lambda: {
            "images": [
                {
                    "absolute_url": "https://cdn.example.com/ok.png",
                    "url": "/static/ok.png",
                }
            ]
        },
        get_summary_for_ai=lambda: "一张图",
    )
    owner._process_slide_image = AsyncMock(return_value=images)
    service = SlideSvgPageService(owner)
    data = slide()
    html = await service._generate_single_slide_svg_with_prompts(
        data, {}, "system", 2, 5, project_id="proj"
    )
    prompt = owner._text_completion_for_role.await_args.kwargs["prompt"]
    assert "https://cdn.example.com/ok.png" in prompt
    assert "other.png" not in html and "ok.png" in html


@pytest.mark.asyncio
async def test_no_supplied_images_means_no_external_images(tmp_path):
    owner = make_owner(
        [
            page(
                '<text x="100" y="220">Content</text><image href="https://invented.test/a.png" width="100" height="100"/>'
            )
        ],
        tmp_path,
    )
    html = await SlideSvgPageService(owner)._generate_single_slide_svg_with_prompts(
        slide(), {}, "", 1, 1, project_id="proj"
    )
    assert "invented.test" not in html


@pytest.mark.asyncio
async def test_resolve_render_mode_prefers_runtime_key_then_project_metadata(tmp_path):
    owner = make_owner([], tmp_path, metadata={"render_mode": "svg"})
    service = SlideSvgPageService(owner)
    assert (
        await service._resolve_render_mode("proj", {"_render_mode": "html"})
        == RENDER_MODE_HTML
    )
    requirements = {}
    assert await service._resolve_render_mode("proj", requirements) == RENDER_MODE_SVG
    assert requirements["_render_mode"] == "svg"
    owner.project_manager.get_project.assert_awaited_once()
    assert await service._resolve_render_mode(None, {}) == RENDER_MODE_HTML


def test_render_mode_helpers():
    assert (
        normalize_render_mode(" SVG ") == "svg"
        and normalize_render_mode("weird") == "html"
        and normalize_render_mode(None) == "html"
    )
    assert resolve_project_render_mode(SimpleNamespace(project_metadata=None)) == "html"
    assert (
        resolve_project_render_mode({"project_metadata": {"render_mode": "svg"}})
        == "svg"
    )
    requirements = {"topic": "x"}
    assert (
        attach_render_mode(
            requirements, SimpleNamespace(project_metadata={"render_mode": "svg"})
        )
        == "svg"
    )
    assert (
        requirements["_render_mode"] == "svg"
        and render_mode_from_requirements(requirements) == "svg"
    )
    assert (
        render_mode_from_requirements({}) is None
        and render_mode_from_requirements(None) is None
    )


def test_collect_image_urls_walks_nested_structures():
    info = {
        "images": [
            {
                "absolute_url": "https://a/x.png",
                "url": "/x.png",
                "meta": {"url": "https://a/y.png"},
            }
        ],
        "cover": {"absolute_url": "https://a/x.png"},
    }
    assert collect_image_urls(info) == ["https://a/x.png", "/x.png", "https://a/y.png"]
    assert collect_image_urls(None) == []


# ----------------------------------------------------------------------
# prompts
# ----------------------------------------------------------------------
def test_single_slide_svg_prompt_contains_contract_symbols_and_brief():
    prompt = prompts_manager.get_single_slide_svg_prompt(
        {
            "title": "增长",
            "content_points": ["a"],
            "_internal": 1,
            "images_info": {"big": True},
        },
        {"topic": "营收", "target_audience": "管理层", "include_page_numbers": True},
        3,
        8,
        "**普通内容页**",
        "- 深色",
        global_constitution="规则",
        current_page_brief="聚焦",
        image_urls=["https://cdn/x.png"],
    )
    assert CANVAS_CONTRACT_TEXT.strip().splitlines()[0] in prompt
    assert all(sid in prompt for sid in SYMBOL_IDS[:5])
    assert (
        "https://cdn/x.png" in prompt
        and "_internal" not in prompt
        and "'big'" not in prompt
    )
    assert (
        "聚焦" in prompt
        and "CSS 手段" in prompt
        and "输出前自检" in prompt
        and "```svg" in prompt
    )
    assert "第3页" in prompt


def test_single_slide_svg_prompt_without_images_forbids_image_elements():
    prompt = SvgPagePrompts.get_single_slide_svg_prompt(
        {"title": "t"}, {}, 1, 1, "", ""
    )
    assert "本页没有可用图片" in prompt


def test_repair_prompt_lists_blocking_and_advisory_sections():
    prompt = prompts_manager.get_svg_page_repair_prompt(
        "<svg/>", ["[overlap] a 与 b"], ["[empty_band] y 300–600"], 2, 5
    )
    assert "必须修复" in prompt and "[overlap] a 与 b" in prompt
    assert "建议改善" in prompt and "[empty_band]" in prompt
    # 指令段提到一次 ```svg 代码块，当前 SVG 只回显一次。
    assert prompt.count("```svg\n<svg/>\n```") == 1


def test_system_prompt_overrides_html_specific_guidance():
    system = prompts_manager.get_svg_page_system_prompt()
    assert "SVG" in system and "不允许任何脚本" in system and "Chart.js" in system
