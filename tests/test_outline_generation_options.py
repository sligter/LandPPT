from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from landppt.api.models import PPTOutline, PPTProject
from landppt.web.route_modules import outline_generation_routes as routes


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["manual", "mixed"])
async def test_outline_search_override_keeps_saved_project_settings(monkeypatch, source):
    project = PPTProject(
        project_id="p1",
        title="example",
        scenario="general",
        topic="example",
        requirements="original",
        project_metadata={"network_mode": False, "language": "zh"},
        confirmed_requirements={"content_source": source, "page_count_settings": {"fixed_pages": 8}},
    )
    service = SimpleNamespace(
        get_role_provider_async=AsyncMock(return_value=(None, {})),
        generate_outline=AsyncMock(return_value=PPTOutline(
            title="example", slides=[{"title": "slide"}], metadata={"llm_call_count": 1},
        )),
        _update_outline_generation_stage=AsyncMock(),
    )
    monkeypatch.setattr(routes.ppt_service.project_manager, "get_project", AsyncMock(return_value=project))
    monkeypatch.setattr(routes, "get_ppt_service_for_user", lambda _user: service)
    monkeypatch.setattr(routes, "check_credits_for_operation", AsyncMock(return_value=(True, 1, 5)))
    monkeypatch.setattr(routes, "consume_credits_for_operation", AsyncMock())

    async def source_outline(project_id, copied_project, requirements, *, user_id, requirements_override):
        assert project_id == "p1"
        assert copied_project.project_metadata["network_mode"] is True
        assert requirements_override == "original\n\nextra"
        yield 'data: {"outline":{"title":"example","slides":[{"title":"slide"}],"metadata":{"llm_call_count":1}}}\n\n'

    monkeypatch.setattr(routes, "_stream_outline_from_confirmed_sources_v2", source_outline)
    result = await routes.generate_outline(
        "p1", SimpleNamespace(id=1),
        routes.OutlineGenerationOptions(network_mode=True, custom_requirements="extra"),
    )

    assert result["status"] == "success"
    assert result["network_mode"] is True
    assert project.project_metadata["network_mode"] is False
    assert project.requirements == "original"
    if source == "manual":
        request, page_count = service.generate_outline.await_args.args
        assert request.network_mode is True
        assert request.requirements == "original\n\nextra"
        assert page_count == {"fixed_pages": 8}
    else:
        service.generate_outline.assert_not_awaited()
