from landppt.services.db_config_service import get_user_ai_provider_config_sync
from landppt.services.image.config.image_config import ImageServiceConfig
from landppt.services.pdf_to_pptx_converter import PDFToPPTXConverter


def test_get_user_ai_provider_config_sync_uses_sync_config_map(monkeypatch):
    class FakeDBConfigService:
        def get_all_config_sync(self, user_id=None):
            assert user_id == 7
            return {
                "default_ai_provider": "openai",
                "openai_api_key": "sync-openai-key",
                "openai_base_url": "https://api.example.com/v1",
                "openai_model": "gpt-sync",
                "openai_use_responses_api": True,
                "openai_enable_reasoning": True,
                "openai_reasoning_effort": "high",
                "landppt_api_key": "system-landppt-key",
                "landppt_base_url": "https://landppt.example.com/v1",
                "landppt_model": "MODEL1",
            }

    import landppt.services.db_config_service as db_mod

    monkeypatch.setattr(db_mod, "get_db_config_service", lambda: FakeDBConfigService(), raising=True)

    config = get_user_ai_provider_config_sync(7)

    assert config["provider_name"] == "openai"
    assert config["api_key"] == "sync-openai-key"
    assert config["base_url"] == "https://api.example.com/v1"
    assert config["model"] == "gpt-sync"
    assert config["use_responses_api"] is True
    assert config["enable_reasoning"] is True
    assert config["reasoning_effort"] == "high"


def test_image_service_config_load_config_from_db_sync(monkeypatch):
    class FakeDBConfigService:
        def get_all_config_sync(self, user_id=None):
            assert user_id == 9
            return {
                "siliconflow_api_key": "sf-key",
                "siliconflow_image_size": "1536x1024",
                "siliconflow_steps": 28,
                "siliconflow_guidance_scale": 8.5,
                "openai_image_api_key": "img-key",
                "openai_image_model": "gpt-image-sync",
                "openai_image_quality": "high",
                "pollinations_api_key": "poll-key",
                "pollinations_model": "flux-pro",
                "searxng_host": "https://searx.example.com",
            }

    import landppt.services.db_config_service as db_mod

    monkeypatch.setattr(db_mod, "get_db_config_service", lambda: FakeDBConfigService(), raising=True)

    config = ImageServiceConfig()
    config.load_config_from_db_sync(user_id=9)

    assert config.get_provider_config("siliconflow")["api_key"] == "sf-key"
    assert config.get_provider_config("siliconflow")["default_size"] == "1536x1024"
    assert config.get_provider_config("siliconflow")["default_steps"] == 28
    assert config.get_provider_config("siliconflow")["default_guidance_scale"] == 8.5
    assert config.get_provider_config("openai_image")["api_key"] == "img-key"
    assert config.get_provider_config("openai_image")["model"] == "gpt-image-sync"
    assert config.get_provider_config("openai_image")["default_quality"] == "high"
    assert config.get_provider_config("pollinations")["api_key"] == "poll-key"
    assert config.get_provider_config("pollinations")["model"] == "flux-pro"
    assert config.get_provider_config("searxng")["host"] == "https://searx.example.com"


def test_pdf_to_pptx_converter_license_key_uses_sync_db_config(monkeypatch):
    class FakeDBConfigService:
        def get_config_value_sync(self, key, user_id=None):
            assert key == "apryse_license_key"
            assert user_id == 12
            return "sync-license-key"

    import landppt.services.db_config_service as db_mod

    monkeypatch.setattr(db_mod, "get_db_config_service", lambda: FakeDBConfigService(), raising=True)

    converter = PDFToPPTXConverter(user_id=12)

    assert converter.license_key == "sync-license-key"
    assert converter.license_key == "sync-license-key"


def test_database_config_service_get_config_value_sync(monkeypatch):
    from landppt.services.db_config_service import DatabaseConfigService

    class FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt):
            return FakeResult("gpt-sync-from-db")

    import landppt.database.database as db_database_mod

    monkeypatch.setattr(db_database_mod, "SessionLocal", lambda: FakeSession(), raising=True)

    service = DatabaseConfigService()

    assert service.get_config_value_sync("openai_model", user_id=23) == "gpt-sync-from-db"
