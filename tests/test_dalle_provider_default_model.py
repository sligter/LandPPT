import asyncio

import pytest

from landppt.services.image.config.image_config import ImageServiceConfig
from landppt.services.image.models import ImageGenerationRequest
from landppt.services.image.providers.dalle_provider import DalleProvider

# OpenAI shut down dall-e-3 on May 12, 2026.
RETIRED_IMAGE_MODEL = "dall-e-3"


@pytest.fixture(autouse=True)
def event_loop_for_provider():
    # The provider base class reads the current loop's clock when it is built.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    asyncio.set_event_loop(None)
    loop.close()


def _request(**kwargs):
    return ImageGenerationRequest(prompt="a red fox", width=1536, height=1024, **kwargs)


def test_dalle_provider_default_model_is_not_retired():
    provider = DalleProvider({"api_key": "test-key"})

    assert provider.model != RETIRED_IMAGE_MODEL


def test_image_service_config_dalle_default_model_is_not_retired():
    assert ImageServiceConfig()._config["dalle"]["model"] != RETIRED_IMAGE_MODEL


def test_dalle_provider_lists_its_default_model():
    provider = DalleProvider({"api_key": "test-key"})

    models = asyncio.get_event_loop().run_until_complete(provider.get_available_models())

    assert provider.model in [model["id"] for model in models]


def test_gpt_image_request_omits_response_format_and_style():
    provider = DalleProvider({"api_key": "test-key"})

    api_request = provider._prepare_api_request(_request(quality="hd"))

    assert "response_format" not in api_request
    assert "style" not in api_request
    assert api_request["quality"] == "auto"


@pytest.mark.parametrize("quality", ["xhigh", "max"])
@pytest.mark.parametrize("model", ["gpt-image-2.5-sunburst", "gpt-image-2.5-sunburst-2026-10-01"])
def test_extended_qualities_are_kept_for_models_that_support_them(model, quality):
    provider = DalleProvider({"api_key": "test-key", "model": model})

    api_request = provider._prepare_api_request(_request(quality=quality))

    assert api_request["quality"] == quality


@pytest.mark.parametrize("quality", ["xhigh", "max"])
def test_extended_qualities_are_not_sent_to_other_gpt_image_models(quality):
    provider = DalleProvider({"api_key": "test-key", "model": "gpt-image-1.5"})

    api_request = provider._prepare_api_request(_request(quality=quality))

    assert api_request["quality"] == "auto"


def test_dall_e_3_request_keeps_url_format_and_style():
    provider = DalleProvider({"api_key": "test-key", "model": "dall-e-3"})

    api_request = provider._prepare_api_request(_request(quality="hd"))

    assert api_request["response_format"] == "url"
    assert api_request["style"] == "vivid"
    assert api_request["quality"] == "hd"


def test_gpt_image_base64_response_is_saved(tmp_path, monkeypatch):
    import base64

    monkeypatch.chdir(tmp_path)
    provider = DalleProvider({"api_key": "test-key"})
    payload = base64.b64encode(b"png-bytes").decode()

    result = asyncio.get_event_loop().run_until_complete(
        provider._process_api_response({"data": [{"b64_json": payload}]}, _request())
    )

    assert result.success
    assert (tmp_path / result.image_info.local_path).read_bytes() == b"png-bytes"
