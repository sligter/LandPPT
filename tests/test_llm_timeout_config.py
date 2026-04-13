def test_config_service_defaults_llm_timeout_seconds():
    from landppt.services.config_service import ConfigService

    service = ConfigService(env_file=".env.example")

    assert service.config_schema["llm_timeout_seconds"]["default"] == "600"


def test_db_config_service_defaults_llm_timeout_seconds():
    from landppt.services.db_config_service import DatabaseConfigService

    service = DatabaseConfigService()

    assert service.config_schema["llm_timeout_seconds"]["default"] == "600"


def test_get_user_ai_provider_config_sync_includes_llm_timeout_seconds(monkeypatch):
    class FakeDBConfigService:
        def get_all_config_sync(self, user_id=None):
            assert user_id == 7
            return {
                "default_ai_provider": "openai",
                "openai_api_key": "sync-openai-key",
                "openai_base_url": "https://api.example.com/v1",
                "openai_model": "gpt-sync",
                "llm_timeout_seconds": "900",
            }

    import landppt.services.db_config_service as db_mod

    monkeypatch.setattr(db_mod, "get_db_config_service", lambda: FakeDBConfigService(), raising=True)

    config = db_mod.get_user_ai_provider_config_sync(7)

    assert config["provider_name"] == "openai"
    assert config["llm_timeout_seconds"] == "900"


def test_openai_compatible_timeout_uses_unified_llm_timeout():
    from landppt.ai.providers import _get_httpx_timeout_seconds

    assert _get_httpx_timeout_seconds({}) == 600.0
    assert _get_httpx_timeout_seconds({"llm_timeout_seconds": "900"}) == 900.0
    assert _get_httpx_timeout_seconds({"timeout": 45}) == 45.0
