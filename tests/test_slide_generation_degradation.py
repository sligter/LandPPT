import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.services.slide.slide_document_service import SlideDocumentService
from landppt.services.slide.slide_generation_service import SlideGenerationService
from landppt.services.slide.slide_html_recovery_service import SlideHtmlRecoveryService


@pytest.mark.asyncio
async def test_html_retry_exhaustion_marks_fallback_and_success_clears_it():
    owner = SimpleNamespace(
        _text_completion_for_role=AsyncMock(return_value=SimpleNamespace(content="")),
        _clean_html_response=lambda content: content,
        _inject_anti_overflow_css=lambda content: content,
        _apply_auto_layout_repair=AsyncMock(side_effect=lambda html, *args: html),
        _validate_html_completeness=lambda html: {
            "is_complete": True,
            "missing_elements": [],
            "errors": [],
        },
    )
    owner._generate_fallback_slide_html = SlideDocumentService(
        owner
    )._generate_fallback_slide_html
    recovery = SlideHtmlRecoveryService(owner)
    slide = {"title": "Title", "content_points": ["Existing fact"]}
    fallback = await recovery._generate_html_with_retry(
        "prompt", "system", slide, 1, 2, max_retries=2
    )
    assert slide["_generation_degraded"] is True
    assert "Existing fact" in fallback
    assert owner._text_completion_for_role.await_count == 2
    owner._text_completion_for_role.return_value.content = (
        "<!DOCTYPE html><html><head></head><body><h1>Title</h1></body></html>"
    )
    await recovery._generate_html_with_retry("prompt", "system", slide, 1, 2)
    assert "_generation_degraded" not in slide


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_degraded_slides_are_persisted_reported_and_retryable(
    tmp_path, monkeypatch, parallel
):
    import landppt.services.db_project_manager as db_module
    import landppt.services.cache_service as cache_module

    outline_slides = [{"title": "A"}, {"title": "B"}]
    project = SimpleNamespace(
        outline={"slides": outline_slides},
        slides_data=[],
        title="Deck",
        confirmed_requirements={"topic": "Deck"},
    )
    saved = {}
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
    generate_calls = []
    should_degrade = True

    async def generate(slide, requirements, system, page, *args):
        generate_calls.append(page)
        slide.pop("_generation_degraded", None)
        if page == 2 and should_degrade:
            slide["_generation_degraded"] = True
        slide["composition_brief"] = {"layout_family": "flow"}
        return "<html><body>Readable content</body></html>"

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

    async def run():
        return [
            json.loads(event.removeprefix("data: "))
            async for event in service._generate_slides_streaming_impl("project")
        ]

    events = await run()
    assert events[-1]["type"] == "complete", events
    assert events[-1]["partial"] is True
    assert events[-1]["failed_pages"] == [2]
    assert saved[1]["generation_failed"] is True
    assert saved[1]["composition_brief"] == {"layout_family": "flow"}
    assert "generation_failed" not in saved[0]
    should_degrade = False
    generate_calls.clear()
    events = await run()
    assert generate_calls == [2]
    assert events[-1]["partial"] is False
    assert "generation_failed" not in saved[1]


def test_plan_and_degradation_metadata_survive_database_roundtrip():
    from landppt.database.service import DatabaseService
    from landppt.services.db_project_manager import DatabaseProjectManager

    data = {
        "title": "Title",
        "html_content": "fallback",
        "generation_failed": True,
        "generation_error": "retry",
        "composition_brief": {"layout_family": "flow"},
    }
    record = DatabaseService._slide_record_from_payload("project", 0, data)
    loaded = DatabaseProjectManager._slide_row_to_payload(SimpleNamespace(**record))
    assert loaded["generation_failed"] is True
    assert loaded["composition_brief"] == data["composition_brief"]
    metadata = DatabaseService._get_slide_metadata(
        {
            "html_content": "success",
            "metadata": record["slide_metadata"],
        }
    )
    assert "generation_failed" not in metadata
    assert "generation_error" not in metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("system_prompt", ["", "SYSTEM"])
async def test_completion_telemetry_records_response_without_prompt_contents(
    caplog, system_prompt
):
    from landppt.services.runtime.runtime_provider_service import RuntimeProviderService

    response = SimpleNamespace(
        model="test-model", finish_reason="length", usage={"completion_tokens": 123}
    )
    provider = SimpleNamespace(
        chat_completion=AsyncMock(return_value=response),
        text_completion=AsyncMock(return_value=response),
    )
    service = RuntimeProviderService(SimpleNamespace())
    service._get_role_provider_async = AsyncMock(
        return_value=(provider, {"provider": "test"})
    )
    with caplog.at_level("INFO"):
        result = await service._text_completion_for_role(
            "slide_generation",
            prompt="PRIVATE_PROMPT",
            system_prompt=system_prompt,
            temperature=0.5,
            top_p=1,
        )
    assert result is response
    assert "finish_reason=length" in caplog.text
    assert "completion_tokens" in caplog.text
    assert "elapsed_seconds=" in caplog.text
    assert "PRIVATE_PROMPT" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_kind", ["single", "template", "missing"])
async def test_composition_submission_log_checks_real_html_prompt(
    prompt_kind, monkeypatch, caplog
):
    from landppt.services.prompts import design_prompts

    monkeypatch.setattr(design_prompts, "_is_image_service_enabled", lambda: False)
    slide = {
        "title": "流程",
        "content_points": ["准备", "执行"],
        "composition_brief": {"layout_family": "flow", "focal": "执行"},
        "_composition_project_id": "project",
    }
    if prompt_kind == "single":
        context = design_prompts.DesignPrompts.get_single_slide_html_prompt(
            slide_data=slide,
            confirmed_requirements={},
            page_number=2,
            total_pages=3,
            context_info="",
            style_genes="",
            template_html="<main></main>",
        )
    elif prompt_kind == "template":
        context = design_prompts.DesignPrompts.get_creative_template_context_prompt(
            slide_data=slide,
            template_html="<main></main>",
            slide_title="流程",
            slide_type="content",
            page_number=2,
            total_pages=3,
            context_info="",
            style_genes="",
        )
    else:
        context = "Generate a slide without a composition brief."
    html = "<!DOCTYPE html><html><head></head><body><h1>Title</h1></body></html>"
    owner = SimpleNamespace(
        _text_completion_for_role=AsyncMock(return_value=SimpleNamespace(content=html)),
        _clean_html_response=lambda content: content,
        _inject_anti_overflow_css=lambda content: content,
        _apply_auto_layout_repair=AsyncMock(side_effect=lambda html, *args: html),
        _validate_html_completeness=lambda html: {
            "is_complete": True,
            "missing_elements": [],
            "errors": [],
        },
    )
    with caplog.at_level("INFO"):
        assert (
            await SlideHtmlRecoveryService(owner)._generate_html_with_retry(
                context, "system", slide, 2, 3
            )
            == html
        )
    actual_prompt = owner._text_completion_for_role.call_args.kwargs["prompt"]
    assert actual_prompt == context
    assert "Composition prompt submission project=project page=2" in caplog.text
    if prompt_kind == "missing":
        assert "attached=False brief_fingerprint=none" in caplog.text
    else:
        assert "执行" in actual_prompt
        assert "attached=True brief_fingerprint=" in caplog.text
    assert "执行" not in caplog.text
