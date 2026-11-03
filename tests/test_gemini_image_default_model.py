import asyncio

import pytest

from landppt.services.config_service import ConfigService
from landppt.services.db_config_service import DatabaseConfigService
from landppt.services.image.config.image_config import ImageServiceConfig
from landppt.services.image.providers.gemini_provider import GeminiImageProvider

# Google shut the 2.0 Flash image-generation models down; requests to them fail.
RETIRED_IMAGE_MODEL = "gemini-2.0-flash-exp-image-generation"


@pytest.fixture(autouse=True)
def event_loop_for_provider():
    # The provider base class reads the current loop's clock when it is built.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    asyncio.set_event_loop(None)
    loop.close()


def test_gemini_image_provider_default_model_is_not_retired():
    assert GeminiImageProvider({"api_key": "test-key"}).model != RETIRED_IMAGE_MODEL


def test_gemini_image_provider_lists_its_default_model():
    provider = GeminiImageProvider({"api_key": "test-key"})

    models = asyncio.get_event_loop().run_until_complete(provider.get_available_models())

    assert provider.model in [model["id"] for model in models]


def test_gemini_image_service_config_default_model_is_not_retired():
    assert ImageServiceConfig().get_provider_config("gemini")["model"] != RETIRED_IMAGE_MODEL


def test_gemini_image_schema_defaults_match_the_provider_default(tmp_path):
    provider_default = GeminiImageProvider({"api_key": "test-key"}).model

    file_schema = ConfigService(env_file=str(tmp_path / ".env")).get_config_schema()
    db_schema = DatabaseConfigService().get_config_schema()

    assert file_schema["gemini_image_model"]["default"] == provider_default
    assert db_schema["gemini_image_model"]["default"] == provider_default
