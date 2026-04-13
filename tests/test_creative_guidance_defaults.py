import asyncio
import json
from pathlib import Path
from types import SimpleNamespace


def test_config_service_defaults_enable_per_slide_creative_guidance():
    from landppt.services.config_service import ConfigService

    service = ConfigService(env_file=".env.example")

    assert service.config_schema["enable_per_slide_creative_guidance"]["default"] == "true"


def test_db_config_service_defaults_enable_per_slide_creative_guidance():
    from landppt.services.db_config_service import DatabaseConfigService

    service = DatabaseConfigService()

    assert service.config_schema["enable_per_slide_creative_guidance"]["default"] == "true"


def test_apryse_standard_pptx_export_is_admin_only_in_config_schema():
    from landppt.services.config_service import ConfigService
    from landppt.services.db_config_service import DatabaseConfigService

    env_service = ConfigService(env_file=".env.example")
    db_service = DatabaseConfigService()

    assert env_service.config_schema["enable_apryse_pptx_export"]["default"] == "false"
    assert env_service.config_schema["enable_apryse_pptx_export"]["admin_only"] is True
    assert env_service.config_schema["apryse_license_key"]["admin_only"] is True
    assert db_service.config_schema["enable_apryse_pptx_export"]["default"] == "false"
    assert db_service.config_schema["enable_apryse_pptx_export"]["admin_only"] is True
    assert db_service.config_schema["apryse_license_key"]["admin_only"] is True


def test_db_config_service_filters_and_resolves_admin_only_apryse_config(monkeypatch):
    from landppt.services.db_config_service import DatabaseConfigService

    service = DatabaseConfigService()
    public_schema = service.get_config_schema(include_admin_only=False)
    resolved = service._resolve_config_values(
        {
            "apryse_license_key": {"value": "user-license", "type": "password", "category": "generation_params"},
            "enable_apryse_pptx_export": {"value": "false", "type": "boolean", "category": "generation_params"},
        },
        {
            "apryse_license_key": {"value": "system-license", "type": "password", "category": "generation_params"},
            "enable_apryse_pptx_export": {"value": "true", "type": "boolean", "category": "generation_params"},
        },
    )

    async def fake_get_all_config(user_id=None):
        return {
            "apryse_license_key": "system-license",
            "enable_apryse_pptx_export": True,
            "openai_model": "gpt-4.1",
        }

    monkeypatch.setattr(service, "get_all_config", fake_get_all_config)
    filtered = asyncio.run(service.get_all_config_for_user(user_id=1, is_admin=False))

    assert "apryse_license_key" not in public_schema
    assert "enable_apryse_pptx_export" not in public_schema
    assert resolved["apryse_license_key"] == "system-license"
    assert resolved["enable_apryse_pptx_export"] is True
    assert "apryse_license_key" not in filtered
    assert "enable_apryse_pptx_export" not in filtered
    assert filtered["openai_model"] == "gpt-4.1"


def test_db_config_service_resolves_system_scope_admin_only_config_from_merged_rows():
    from landppt.services.db_config_service import DatabaseConfigService

    service = DatabaseConfigService()
    resolved = service._resolve_config_values(
        {
            "apryse_license_key": {
                "value": "system-license",
                "type": "password",
                "category": "generation_params",
                "is_user_override": False,
            },
            "enable_apryse_pptx_export": {
                "value": "true",
                "type": "boolean",
                "category": "generation_params",
                "is_user_override": False,
            },
        },
        {},
    )

    assert resolved["apryse_license_key"] == "system-license"
    assert resolved["enable_apryse_pptx_export"] is True


def test_db_config_service_ignores_user_override_for_admin_only_when_no_system_default():
    from landppt.services.db_config_service import DatabaseConfigService

    service = DatabaseConfigService()
    resolved = service._resolve_config_values(
        {
            "apryse_license_key": {
                "value": "legacy-user-license",
                "type": "password",
                "category": "generation_params",
                "is_user_override": True,
            },
            "enable_apryse_pptx_export": {
                "value": "true",
                "type": "boolean",
                "category": "generation_params",
                "is_user_override": True,
            },
        },
        {},
    )

    assert resolved["apryse_license_key"] in (None, "")
    assert resolved["enable_apryse_pptx_export"] is False


def test_db_config_service_migrates_legacy_system_default_to_true(monkeypatch):
    import landppt.database.database as database_mod
    import landppt.database.repositories as repo_mod
    from landppt.services.db_config_service import DatabaseConfigService

    captured = {"set_calls": []}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    class FakeRepo:
        def __init__(self, session):
            self.session = session

        async def get_all_configs(self, user_id=None):
            return {
                "enable_per_slide_creative_guidance": {"value": "false"},
            }

        async def set_config(self, **kwargs):
            captured["set_calls"].append(kwargs)

    monkeypatch.setattr(database_mod, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(repo_mod, "UserConfigRepository", FakeRepo)

    service = DatabaseConfigService()
    updated = asyncio.run(service.initialize_system_defaults())

    assert updated >= 1
    assert any(
        call["key"] == "enable_per_slide_creative_guidance" and call["value"] == "true"
        for call in captured["set_calls"]
    )


def test_creative_design_service_uses_slide_prompt_when_per_slide_guidance_enabled(tmp_path):
    from landppt.services.slide.creative_design_service import CreativeDesignService

    class _DummyService:
        def __init__(self):
            self.user_id = 1
            self.cache_dirs = {"style_genes": tmp_path}
            self._cached_style_genes = {}
            self._cached_global_constitutions = {}
            self._cached_page_creative_briefs = {}
            self._cached_slide_creative_guides = {}
            self._style_genes_ready_events = {}
            self._global_constitution_ready_events = {}
            self._page_creative_brief_ready_events = {}
            self._slide_creative_guide_ready_events = {}

        async def _get_user_generation_config(self):
            return {"enable_per_slide_creative_guidance": True}

    owner = _DummyService()
    service = CreativeDesignService(owner)

    async def fake_style_genes(project_id, template_html, page_number):
        return "STYLE-GENES"

    async def fake_constitution(*args, **kwargs):
        return "GLOBAL-CONSTITUTION"

    async def fail_page_briefs(*args, **kwargs):
        raise AssertionError("page-type briefs should not be used when per-slide guidance is enabled")

    async def fake_slide_guide(*args, **kwargs):
        return "SLIDE-GUIDE"

    service._get_or_extract_style_genes = fake_style_genes
    service._get_or_generate_global_constitution = fake_constitution
    service._get_or_generate_page_creative_briefs = fail_page_briefs
    service._get_or_generate_slide_creative_guide = fake_slide_guide

    result = asyncio.run(
        service._get_creative_design_inputs(
            project_id="proj-1",
            template_html="<div></div>",
            slide_data={"title": "增长机会"},
            page_number=2,
            total_pages=5,
            confirmed_requirements={"topic": "年度复盘"},
            all_slides=[{"title": "封面"}, {"title": "增长机会"}],
        )
    )

    assert result == ("STYLE-GENES", "GLOBAL-CONSTITUTION", "SLIDE-GUIDE")


def test_creative_design_service_uses_page_type_briefs_when_per_slide_guidance_disabled(tmp_path):
    from landppt.services.slide.creative_design_service import CreativeDesignService

    class _DummyService:
        def __init__(self):
            self.user_id = 1
            self.cache_dirs = {"style_genes": tmp_path}
            self._cached_style_genes = {}
            self._cached_global_constitutions = {}
            self._cached_page_creative_briefs = {}
            self._cached_slide_creative_guides = {}
            self._style_genes_ready_events = {}
            self._global_constitution_ready_events = {}
            self._page_creative_brief_ready_events = {}
            self._slide_creative_guide_ready_events = {}

        async def _get_user_generation_config(self):
            return {"enable_per_slide_creative_guidance": False}

    owner = _DummyService()
    service = CreativeDesignService(owner)

    async def fake_style_genes(project_id, template_html, page_number):
        return "STYLE-GENES"

    async def fake_constitution(*args, **kwargs):
        return "GLOBAL-CONSTITUTION"

    async def fake_page_briefs(*args, **kwargs):
        return [
            {"page": 1, "creative_brief": "封面指导"},
            {"page": 2, "creative_brief": "PAGE-BRIEF"},
        ]

    async def fail_slide_guide(*args, **kwargs):
        raise AssertionError("slide-level prompt should not be used when per-slide guidance is disabled")

    service._get_or_extract_style_genes = fake_style_genes
    service._get_or_generate_global_constitution = fake_constitution
    service._get_or_generate_page_creative_briefs = fake_page_briefs
    service._get_or_generate_slide_creative_guide = fail_slide_guide

    result = asyncio.run(
        service._get_creative_design_inputs(
            project_id="proj-1",
            template_html="<div></div>",
            slide_data={"title": "增长机会"},
            page_number=2,
            total_pages=5,
            confirmed_requirements={"topic": "年度复盘"},
            all_slides=[{"title": "封面"}, {"title": "增长机会"}],
        )
    )

    assert result == ("STYLE-GENES", "GLOBAL-CONSTITUTION", "PAGE-BRIEF")


def test_creative_design_service_persists_slide_creative_guide_cache(tmp_path, monkeypatch):
    from landppt.services.slide.creative_design_service import CreativeDesignService

    class _DummyService:
        def __init__(self):
            self.user_id = 1
            self.cache_dirs = {"style_genes": tmp_path}
            self._cached_slide_creative_guides = {}
            self._slide_creative_guide_ready_events = {}

    owner = _DummyService()
    service = CreativeDesignService(owner)
    recorded = []

    async def fake_generate(*args, **kwargs):
        recorded.append((args, kwargs))
        return "REALTIME-GUIDE"

    monkeypatch.setattr(service, "_generate_slide_creative_guide", fake_generate)

    guide = asyncio.run(
        service._get_or_generate_slide_creative_guide(
            project_id="proj-cache",
            slide_data={"title": "当前页"},
            page_number=3,
            total_pages=8,
            confirmed_requirements={"topic": "项目汇报"},
            all_slides=[{"title": "封面"}, {"title": "目录"}, {"title": "当前页"}],
            template_html="<div class='page'></div>",
        )
    )

    cache_file = Path(tmp_path) / "proj-cache_slide_3_creative_guide.json"
    cache_data = json.loads(cache_file.read_text(encoding="utf-8"))

    assert guide == "REALTIME-GUIDE"
    assert len(recorded) == 1
    assert owner._cached_slide_creative_guides["proj-cache:3"] == "REALTIME-GUIDE"
    assert cache_data["creative_guide"] == "REALTIME-GUIDE"


def test_creative_guidance_runtime_pipeline_wires_per_slide_prompt_and_cache_cleanup():
    root = Path(__file__).resolve().parents[1]
    service_text = (root / "src/landppt/services/slide/creative_design_service.py").read_text(encoding="utf-8")

    assert 'enable_per_slide_creative_guidance' in service_text
    assert 'get_slide_design_guide_prompt(' in service_text
    assert '_get_or_generate_slide_creative_guide(' in service_text
    assert '_cached_slide_creative_guides' in service_text
    assert '_slide_creative_guide_ready_events' in service_text
    assert '_slide_*_creative_guide.json' in service_text
