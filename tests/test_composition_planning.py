import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.services.slide.composition_planning_service import (
    CompositionPlanningService,
    guidance_fingerprint,
    parse_composition_briefs,
)
from landppt.services.slide.creative_design_service import CreativeDesignService


SLIDES = [
    {"title": "概览", "content_points": ["背景"]},
    {"title": "执行", "content_points": ["准备", "实施", "验证"]},
]
PLAN = [
    {
        "page": page,
        "composition_brief": {
            "intent": "介绍主题" if page == 1 else "说明执行步骤",
            "relation": "主题" if page == 1 else "先后",
            "layout_family": "焦点排版" if page == 1 else "流程",
            "focal": "概览" if page == 1 else "执行",
            "content_sufficiency": "focus" if page == 1 else "sufficient",
            "rhythm": "先聚焦主题，再展开流程",
        },
    }
    for page in (1, 2)
]


def make_owner(tmp_path):
    return SimpleNamespace(
        user_id=1,
        cache_dirs={"style_genes": tmp_path},
        _text_completion_for_role=AsyncMock(
            return_value=SimpleNamespace(content=json.dumps(PLAN))
        ),
    )


@pytest.mark.asyncio
async def test_plan_is_shared_across_concurrent_pages_and_process_cache(tmp_path):
    owner = make_owner(tmp_path)
    planner = CompositionPlanningService(owner)
    args = ("project", {}, SLIDES, 2, "<main>template</main>")
    results = await asyncio.gather(*(planner.get_or_generate(*args) for _ in range(5)))
    assert results == [PLAN] * 5
    owner._text_completion_for_role.assert_awaited_once()
    fresh_owner = make_owner(tmp_path)
    assert await CompositionPlanningService(fresh_owner).get_or_generate(*args) == PLAN
    fresh_owner._text_completion_for_role.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_invalidates_for_outline_template_and_prompt_changes(
    tmp_path, monkeypatch
):
    from landppt.services.slide import composition_planning_service as module

    owner = make_owner(tmp_path)
    planner = CompositionPlanningService(owner)
    slides = copy.deepcopy(SLIDES)
    await planner.get_or_generate("project", {}, slides, 2, "template-a")
    slides[1]["content_points"].append("复盘")
    await planner.get_or_generate("project", {}, slides, 2, "template-a")
    await planner.get_or_generate("project", {}, slides, 2, "template-b")
    monkeypatch.setattr(module, "GUIDANCE_VERSION", "next-version")
    await planner.get_or_generate("project", {}, slides, 2, "template-b")
    assert owner._text_completion_for_role.await_count == 4
    # Runtime media and status changes must not trigger another planning call.
    slides[0].update(
        images_collection=object(), _generation_degraded=True, composition_brief={}
    )
    await planner.get_or_generate("project", {}, slides, 2, "template-b")
    assert owner._text_completion_for_role.await_count == 4


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.pop(),
        lambda data: data[1].update(page=1),
        lambda data: data[1].update(page=3),
        lambda data: data[0].update(page=True),
        lambda data: data[1]["composition_brief"].pop("focal"),
        lambda data: data[1]["composition_brief"].update(content_sufficiency="high"),
        lambda data: data[1]["composition_brief"].update(relation=[]),
    ],
)
def test_malformed_plan_cannot_be_assigned_to_pages(change):
    data = copy.deepcopy(PLAN)
    change(data)
    with pytest.raises(ValueError):
        parse_composition_briefs(json.dumps(data), 2)


def test_json_fences_and_out_of_order_pages_are_supported():
    raw = (
        "<think>analysis</think>\n```json\n"
        + json.dumps({"slides": PLAN[::-1]})
        + "\n```"
    )
    assert parse_composition_briefs(raw, 2) == PLAN


def test_numeric_page_strings_and_enum_case_are_normalized():
    data = copy.deepcopy(PLAN)
    for entry in data:
        entry["page"] = f" 0{entry['page']} "
        entry["composition_brief"]["content_sufficiency"] = (
            " " + entry["composition_brief"]["content_sufficiency"].upper() + " "
        )
    assert parse_composition_briefs(json.dumps(data), 2) == PLAN


@pytest.mark.parametrize("page", ["1.0", "1e0", "-1", "", 1.0, True])
def test_ambiguous_page_values_remain_invalid(page):
    data = copy.deepcopy(PLAN)
    data[0]["page"] = page
    with pytest.raises(ValueError):
        parse_composition_briefs(json.dumps(data), 2)


def test_duplicate_pages_after_normalization_remain_invalid():
    data = copy.deepcopy(PLAN)
    data[1]["page"] = "01"
    with pytest.raises(ValueError):
        parse_composition_briefs(json.dumps(data), 2)


@pytest.mark.asyncio
async def test_parse_failure_retries_once_with_same_prompt_and_shares_result(
    tmp_path, caplog
):
    owner = make_owner(tmp_path)
    owner._text_completion_for_role.side_effect = [
        SimpleNamespace(content='{"slides": []}'),
        SimpleNamespace(content=json.dumps(PLAN)),
    ]
    planner = CompositionPlanningService(owner)
    args = ("project", {}, SLIDES, 2, "")
    with caplog.at_level("INFO"):
        results = await asyncio.gather(
            *(planner.get_or_generate(*args) for _ in range(4))
        )
    assert results == [PLAN] * 4
    calls = owner._text_completion_for_role.await_args_list
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert "attempt=1/2" in caplog.text
    assert "source=generated planned_pages=2 expected_pages=2" in caplog.text
    data = json.loads(
        (tmp_path / "project_composition_briefs.json").read_text(encoding="utf-8")
    )
    assert data["slides"] == PLAN


@pytest.mark.asyncio
async def test_two_parse_failures_fall_back_without_persisting(tmp_path, caplog):
    owner = make_owner(tmp_path)
    owner._text_completion_for_role.return_value.content = "not json"
    planner = CompositionPlanningService(owner)
    with caplog.at_level("INFO"):
        assert await planner.get_or_generate("project", {}, SLIDES, 2, "") == []
        assert await planner.get_or_generate("project", {}, SLIDES, 2, "") == []
    assert owner._text_completion_for_role.await_count == 2
    assert not list(tmp_path.glob("*composition*"))
    assert "source=fallback planned_pages=0 expected_pages=2" in caplog.text
    assert "source=memory_cache planned_pages=0 expected_pages=2" in caplog.text


@pytest.mark.asyncio
async def test_disk_cache_reports_validated_page_coverage(tmp_path, caplog):
    args = ("project", {}, SLIDES, 2, "")
    await CompositionPlanningService(make_owner(tmp_path)).get_or_generate(*args)
    owner = make_owner(tmp_path)
    with caplog.at_level("INFO"):
        assert await CompositionPlanningService(owner).get_or_generate(*args) == PLAN
    owner._text_completion_for_role.assert_not_awaited()
    assert "source=disk_cache planned_pages=2 expected_pages=2" in caplog.text


@pytest.mark.asyncio
async def test_planning_failure_falls_back_without_persisting_or_retry_storm(
    tmp_path, monkeypatch
):
    from landppt.services.slide import composition_planning_service as module

    owner = make_owner(tmp_path)
    owner._text_completion_for_role.side_effect = RuntimeError("unavailable")
    planner = CompositionPlanningService(owner)
    args = ("project", {}, SLIDES, 2, "")
    assert await planner.get_or_generate(*args) == []
    assert await planner.get_or_generate(*args) == []
    owner._text_completion_for_role.assert_awaited_once()
    assert not list(tmp_path.glob("*composition*"))
    owner._text_completion_for_role.side_effect = None
    now = module.time.monotonic()
    monkeypatch.setattr(module.time, "monotonic", lambda: now + 31)
    assert await planner.get_or_generate(*args) == PLAN


@pytest.mark.asyncio
async def test_partial_outline_does_not_request_global_plan(tmp_path):
    owner = make_owner(tmp_path)
    assert (
        await CompositionPlanningService(owner).get_or_generate(
            "project", {}, SLIDES, 5, ""
        )
        == []
    )
    owner._text_completion_for_role.assert_not_awaited()


@pytest.mark.asyncio
async def test_corrupt_cache_and_timeout_do_not_block_existing_generation(
    tmp_path, monkeypatch
):
    from landppt.services.slide import composition_planning_service as module

    (tmp_path / "project_composition_briefs.json").write_text("[]")
    owner = make_owner(tmp_path)

    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    owner._text_completion_for_role.side_effect = stalled
    monkeypatch.setattr(module, "resolve_timeout_seconds", lambda *args: 0.01)
    assert (
        await CompositionPlanningService(owner).get_or_generate(
            "project", {}, SLIDES, 2, ""
        )
        == []
    )


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_other_pages_plan(tmp_path):
    owner = make_owner(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    async def generate(*args, **kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(content=json.dumps(PLAN))

    owner._text_completion_for_role.side_effect = generate
    planner = CompositionPlanningService(owner)
    args = ("project", {}, SLIDES, 2, "")
    first = asyncio.create_task(planner.get_or_generate(*args))
    await started.wait()
    second = asyncio.create_task(planner.get_or_generate(*args))
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == PLAN
    owner._text_completion_for_role.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_cleanup_removes_plans_and_cancels_inflight_planning(tmp_path):
    owner = make_owner(tmp_path)
    service = CreativeDesignService(owner)
    await service._composition_planner.get_or_generate("project", {}, SLIDES, 2, "")
    service.clear_cached_style_genes("project")
    assert owner._cached_composition_briefs == {}
    assert not list(tmp_path.glob("*composition*"))
    started = asyncio.Event()

    async def stalled(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    owner._text_completion_for_role.side_effect = stalled
    task = asyncio.create_task(
        service._composition_planner.get_or_generate("project", {}, SLIDES, 2, "")
    )
    await started.wait()
    service.clear_cached_style_genes()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not owner._composition_ready_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("per_slide", [True, False])
async def test_both_guidance_modes_pass_actual_page_plan_to_html(tmp_path, per_slide):
    owner = make_owner(tmp_path)
    owner._get_user_generation_config = AsyncMock(
        return_value={"enable_per_slide_creative_guidance": per_slide}
    )
    service = CreativeDesignService(owner)
    service._get_or_extract_style_genes = AsyncMock(return_value="STYLE")
    service._get_or_generate_global_constitution = AsyncMock(return_value="GLOBAL")
    service._generate_slide_creative_guide = AsyncMock(return_value="SINGLE")
    service._get_or_generate_page_creative_briefs = AsyncMock(
        return_value=[{"page": 2, "creative_brief": "TYPE"}]
    )
    slide = copy.deepcopy(SLIDES[1])
    result = await service._get_creative_design_inputs(
        "project", "", slide, 2, 2, {}, SLIDES
    )
    assert result[:2] == ("STYLE", "GLOBAL")
    assert ("SINGLE" if per_slide else "TYPE") in result[2]
    assert '"layout_family": "流程"' in result[2]
    assert slide["composition_brief"] == PLAN[1]["composition_brief"]
    if per_slide:
        passed = service._generate_slide_creative_guide.call_args.kwargs["slide_data"]
        assert passed["composition_brief"] == PLAN[1]["composition_brief"]


@pytest.mark.asyncio
async def test_existing_guidance_caches_reject_legacy_and_changed_inputs(tmp_path):
    owner = make_owner(tmp_path)
    service = CreativeDesignService(owner)
    (tmp_path / "project_global_constitution.json").write_text(
        json.dumps({"constitution": "OLD"})
    )
    service._generate_global_constitution = AsyncMock(return_value="NEW")
    args = {
        "project_id": "project",
        "template_html": "template",
        "first_slide_data": SLIDES[0],
    }
    assert await service._get_or_generate_global_constitution(**args) == "NEW"
    assert await service._get_or_generate_global_constitution(**args) == "NEW"
    service._generate_global_constitution.assert_awaited_once()
    await service._get_or_generate_global_constitution(
        **{**args, "template_html": "changed"}
    )
    assert service._generate_global_constitution.await_count == 2


def test_runtime_requirement_cache_does_not_affect_guidance_identity():
    assert guidance_fingerprint({"topic": "A"}) == guidance_fingerprint(
        {"topic": "A", "_cached_selected_global_template": object()}
    )
    assert guidance_fingerprint({"topic": "A"}) != guidance_fingerprint({"topic": "B"})


def test_composition_prompt_preserves_all_points_and_rejects_padding():
    from landppt.services.prompts.design_prompts import DesignPrompts

    points = ["x" * 100 + str(i) for i in range(8)]
    prompt = DesignPrompts.get_composition_briefs_prompt(
        {}, [{"content_points": points}], 1
    )
    assert all(point in prompt for point in points)
    canvas = DesignPrompts._build_canvas_system_context()
    assert "align-items:start" not in canvas
    assert "不设统一填充率或字数门槛" in canvas
    assert "禁止为凑满页面编造事实" in canvas
