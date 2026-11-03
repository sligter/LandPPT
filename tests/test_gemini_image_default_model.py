import asyncio
import base64
import os

import pytest

from landppt.services.config_service import ConfigService
from landppt.services.db_config_service import DatabaseConfigService
from landppt.services.image.config.image_config import ImageServiceConfig
from landppt.services.image.models import ImageGenerationRequest
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


class _FakeResponse:
    status = 200

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    calls = []
    payload = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None, timeout=None):
        _FakeSession.calls.append({"url": url, "json": json})
        return _FakeResponse(_FakeSession.payload)


def _request(**kwargs):
    return ImageGenerationRequest(prompt="a red cube", width=1920, height=1080, **kwargs)


def test_gemini_request_puts_image_options_in_image_config():
    api_request = GeminiImageProvider({"api_key": "test-key"})._prepare_api_request(_request())

    config = api_request["generationConfig"]
    assert config["responseModalities"] == ["IMAGE"]
    assert config["imageConfig"] == {"aspectRatio": "16:9", "imageSize": "2K"}
    # Not part of generateContent's generationConfig.
    for unsupported in ("aspectRatio", "imageSize", "numberOfImages", "personGeneration"):
        assert unsupported not in config


def test_gemini_generate_sends_image_config_and_saves_the_image(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aiohttp.ClientSession", _FakeSession)
    _FakeSession.calls = []
    _FakeSession.payload = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"png-bytes").decode()}}]}}
        ]
    }
    provider = GeminiImageProvider({"api_key": "test-key"})

    result = asyncio.get_event_loop().run_until_complete(provider.generate(_request()))

    assert result.success, result.message
    assert len(_FakeSession.calls) == 1
    call = _FakeSession.calls[0]
    assert call["url"].endswith(f"/models/{provider.model}:generateContent?key=test-key")
    assert call["json"]["contents"] == [{"parts": [{"text": "a red cube"}]}]
    assert call["json"]["generationConfig"]["imageConfig"] == {"aspectRatio": "16:9", "imageSize": "2K"}
    assert os.path.getsize(result.image_info.local_path) == len(b"png-bytes")


def test_gemini_generate_rejects_multiple_images_without_calling_the_api(monkeypatch):
    monkeypatch.setattr("aiohttp.ClientSession", _FakeSession)
    _FakeSession.calls = []
    provider = GeminiImageProvider({"api_key": "test-key"})

    result = asyncio.get_event_loop().run_until_complete(provider.generate(_request(num_images=2)))

    assert not result.success
    assert result.error_code == "unsupported_num_images"
    assert _FakeSession.calls == []


def test_gemini_listed_max_resolution_matches_the_sizes_the_provider_requests():
    provider = GeminiImageProvider({"api_key": "test-key"})
    models = asyncio.get_event_loop().run_until_complete(provider.get_available_models())

    # _map_image_size asks for the 2K tier for requests whose longest side is >= 1400 px.
    assert models[0]["max_resolution"] == "2048x2048"
