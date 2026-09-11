"""render_mode 贯通生成链路、落库与配置的测试。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.services.slide.slide_generation_service import SlideGenerationService
from landppt.services.slide.slide_media_service import SlideMediaService


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("previous_html", [False, True])
async def test_streaming_generator_injects_render_mode_and_persists_it(
    tmp_path, monkeypatch, parallel, previous_html
):
    import landppt.services.cache_service as cache_module
    import landppt.services.db_project_manager as db_module

    outline_slides = [{"title": "A"}, {"title": "B"}]
    project = SimpleNamespace(
        outline={"slides": outline_slides},
        slides_data=[],
        title="Deck",
        confirmed_requirements={"topic": "Deck"},
        project_metadata={"render_mode": "svg", "language": "zh"},
    )
    saved = {}
    if previous_html:
        saved.update(
            {
                i: {
                    "page_number": i + 1,
                    "render_mode": "html",
                    "html_content": "<html>Old</html>",
                }
                for i in range(2)
            }
        )
    db = SimpleNamespace(
        update_stage_status=AsyncMock(),
        update_project_data=AsyncMock(),
        get_single_slide=AsyncMock(side_effect=lambda pid, idx: saved.get(idx)),
    )

    async def save(pid, idx, data, **kwargs):
        saved[idx] = dict(data)

    db.save_single_slide = AsyncMock(side_effect=save)
    monkeypatch.setattr(db_module, "DatabaseProjectManager", lambda: db)
    monkeypatch.setattr(cache_module, "get_cache_service", AsyncMock(return_value=None))
    seen_modes = []

    async def generate(slide, requirements, system, page, *args, **kwargs):
        seen_modes.append(requirements.get("_render_mode"))
        slide["render_mode"] = "svg"
        slide["svg_report"] = {"outcome": "ok", "page": page}
        return '<!DOCTYPE html><html data-render-mode="svg"><body><svg viewBox="0 0 1280 720"></svg></body></html>'

    owner = SimpleNamespace(
        user_id=None,
        project_manager=SimpleNamespace(get_project=AsyncMock(return_value=project)),
        _get_user_generation_config=AsyncMock(
            return_value={
                "enable_parallel_generation": parallel,
                "parallel_slides_count": 2,
            }
        ),
        _load_prompts_md_system_prompt=lambda: "system",
        _is_slides_generation_cancelled=AsyncMock(return_value=False),
        _prepare_project_creative_guidance=AsyncMock(),
        _generate_single_slide_html_with_prompts=generate,
        _combine_slides_to_full_html=lambda *args: "combined",
    )
    service = SlideGenerationService(owner)
    events = [
        json.loads(event.removeprefix("data: "))
        async for event in service._generate_slides_streaming_impl("project")
    ]

    assert events[-1]["type"] == "complete"
    assert seen_modes == ["svg", "svg"]
    assert project.confirmed_requirements["_render_mode"] == "svg"
    assert saved[0]["render_mode"] == "svg" and saved[1]["render_mode"] == "svg"
    assert saved[0]["svg_report"]["outcome"] == "ok"
    slide_events = [e for e in events if e["type"] == "slide"]
    assert all(e["slide_data"]["render_mode"] == "svg" for e in slide_events)


@pytest.mark.asyncio
async def test_media_service_dispatches_svg_mode_before_template_lookup():
    svg_service = SimpleNamespace(
        _resolve_render_mode=AsyncMock(return_value="svg"),
        _generate_single_slide_svg_with_prompts=AsyncMock(
            return_value="<html data-render-mode='svg'></html>"
        ),
    )
    owner = SimpleNamespace(
        _svg_page_service=svg_service,
        get_selected_global_template=AsyncMock(
            side_effect=AssertionError("template lookup must not run in svg mode")
        ),
    )
    media = SlideMediaService(owner)
    slide = {"title": "A"}
    result = await media._generate_single_slide_html_with_prompts(
        slide, {"project_id": "p1"}, "system", 1, 3, all_slides=[slide], project_id=None
    )

    assert result == "<html data-render-mode='svg'></html>"
    svg_service._resolve_render_mode.assert_awaited_once_with(
        "p1", {"project_id": "p1"}
    )
    call = svg_service._generate_single_slide_svg_with_prompts.await_args
    assert (
        call.args[0] is slide
        and call.kwargs["project_id"] == "p1"
        and call.kwargs["all_slides"] == [slide]
    )


@pytest.mark.asyncio
async def test_media_service_keeps_html_path_for_html_mode():
    svg_service = SimpleNamespace(
        _resolve_render_mode=AsyncMock(return_value="html"),
        _generate_single_slide_svg_with_prompts=AsyncMock(
            side_effect=AssertionError("must not be called")
        ),
    )
    selected_template = {"template_name": "T", "html_template": "<main/>"}
    owner = SimpleNamespace(
        _svg_page_service=svg_service,
        get_selected_global_template=AsyncMock(return_value=selected_template),
        _generate_slide_with_template=AsyncMock(return_value="<html>template</html>"),
    )
    media = SlideMediaService(owner)
    requirements = {"project_id": "p1"}
    result = await media._generate_single_slide_html_with_prompts(
        {"title": "A"}, requirements, "system", 1, 3
    )
    assert result == "<html>template</html>"
    assert requirements["_cached_selected_global_template"] is selected_template


def test_render_mode_and_report_survive_database_round_trip():
    from landppt.database.service import DatabaseService
    from landppt.services.db_project_manager import DatabaseProjectManager

    data = {
        "title": "T",
        "html_content": "<html/>",
        "render_mode": "svg",
        "svg_report": {"outcome": "ok"},
    }
    record = DatabaseService._slide_record_from_payload("project", 0, data)
    assert record["slide_metadata"]["render_mode"] == "svg"
    assert record["slide_metadata"]["svg_report"] == {"outcome": "ok"}
    loaded = DatabaseProjectManager._slide_row_to_payload(SimpleNamespace(**record))
    assert loaded["render_mode"] == "svg"
    html_only = DatabaseProjectManager._slide_row_to_payload(
        SimpleNamespace(
            **DatabaseService._slide_record_from_payload(
                "project", 0, {"title": "T", "html_content": "<html/>"}
            )
        )
    )
    assert "render_mode" not in html_only


def test_anthropic_output_budget_is_configurable():
    from landppt.core.config import ai_config
    from landppt.services.db_config_service import _build_user_ai_provider_config

    env_config = ai_config.get_provider_config("anthropic")
    assert int(env_config["anthropic_max_tokens"]) >= 16384
    default = _build_user_ai_provider_config({}, "anthropic")
    assert int(default["anthropic_max_tokens"]) == int(ai_config.anthropic_max_tokens)
    custom = _build_user_ai_provider_config({"anthropic_max_tokens": 8192}, "anthropic")
    assert custom["anthropic_max_tokens"] == 8192


def test_requirements_route_accepts_render_mode_field():
    import inspect

    from landppt.web.route_modules import outline_requirements_routes as routes

    signature = inspect.signature(routes.confirm_project_requirements)
    assert "render_mode" in signature.parameters
    source = inspect.getsource(routes.confirm_project_requirements)
    assert (
        "normalize_render_mode(render_mode)" in source
        and "update_project_metadata" in source
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("degraded", [False, True])
async def test_batch_regeneration_preserves_svg_and_refreshes_failure_status(
    monkeypatch, degraded
):
    from landppt.web.route_modules import slide_routes as routes
    import landppt.services.db_project_manager as db_module

    outline_slide = {"title": "A", "content_points": ["Existing fact"]}
    project = SimpleNamespace(
        title="Deck",
        outline={"slides": [outline_slide]},
        confirmed_requirements={"topic": "Deck"},
        project_metadata={"render_mode": "svg"},
        slides_data=[
            {
                "page_number": 1,
                "title": "Old",
                "generation_failed": True,
                "generation_error": "old",
                "html_content": "old",
            }
        ],
    )

    async def generate(slide, requirements, *args, **kwargs):
        assert requirements["_render_mode"] == "svg"
        slide["render_mode"] = "svg"
        slide["svg_report"] = {"outcome": "accepted-with-defects" if degraded else "ok"}
        if degraded:
            slide["_generation_degraded"] = True
        return '<html data-render-mode="svg"><body><svg></svg></body></html>'

    owner = SimpleNamespace(
        project_manager=SimpleNamespace(get_project=AsyncMock(return_value=project)),
        get_locked_slide_indices=AsyncMock(return_value=[]),
        get_role_provider_async=AsyncMock(return_value=(None, {"provider": "test"})),
        _load_prompts_md_system_prompt=lambda: "",
        _ensure_global_master_template_selected=AsyncMock(
            side_effect=AssertionError("SVG must not create HTML master")
        ),
        _generate_single_slide_html_with_prompts=generate,
        _combine_slides_to_full_html=lambda *args: "combined",
    )
    db = SimpleNamespace(
        save_single_slide=AsyncMock(return_value=True), update_project_data=AsyncMock()
    )
    monkeypatch.setattr(db_module, "DatabaseProjectManager", lambda: db)
    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda uid: owner)
    monkeypatch.setattr(
        routes, "check_credits_for_operation", AsyncMock(return_value=(True, 0, 0))
    )
    monkeypatch.setattr(routes, "consume_credits_for_operation", AsyncMock())
    response = await routes._do_batch_regenerate(
        "p",
        routes.SlideBatchRegenerateRequest(regenerate_all=True),
        SimpleNamespace(id=1),
    )
    assert response["success"], response
    saved = db.save_single_slide.await_args.args[2]
    assert saved["render_mode"] == "svg"
    assert saved["svg_report"]["outcome"] == (
        "accepted-with-defects" if degraded else "ok"
    )
    assert bool(saved.get("generation_failed")) == degraded
    assert saved.get("generation_error") != "old"


@pytest.mark.asyncio
async def test_agent_cannot_apply_html_mutations_to_svg_baseline(monkeypatch):
    from fastapi import HTTPException
    from landppt.web.route_modules import slide_edit_agent_routes as routes
    from landppt.services.slide.slide_edit_agent_service import (
        SlideEditAgentApplyRequest,
        compute_slide_html_hash,
    )

    baseline = '<html data-render-mode="svg"><body><svg></svg></body></html>'
    project = SimpleNamespace(
        slides_data=[{"render_mode": "svg", "html_content": baseline}]
    )
    owner = SimpleNamespace(
        project_manager=SimpleNamespace(get_project=AsyncMock(return_value=project))
    )
    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda uid: owner)
    request = SlideEditAgentApplyRequest(
        proposalId="p",
        projectId="project",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(baseline),
        htmlContent="<html><body>Changed</body></html>",
    )
    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(request, SimpleNamespace(id=1))
    assert exc.value.status_code == 400 and "SVG" in str(exc.value.detail)
