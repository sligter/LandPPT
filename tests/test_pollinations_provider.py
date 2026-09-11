import unittest
from urllib.parse import parse_qs, urlsplit

from landppt.services.image.models import ImageGenerationRequest, ImageProvider
from landppt.services.image.providers.pollinations_provider import PollinationsProvider


class PollinationsQualityTest(unittest.IsolatedAsyncioTestCase):
    async def test_gpt_image_quality_with_catalog_names_and_aliases(self):
        provider = PollinationsProvider({"api_key": "test-key"})
        for model in ("gptimage", "gptimage-large", "openai/gpt-image-1-mini", "openai/gpt-image-1.5"):
            for quality, expected in (("hd", "hd"), ("standard", "medium")):
                with self.subTest(model=model, quality=quality):
                    request = ImageGenerationRequest(
                        prompt="presentation background", provider=ImageProvider.POLLINATIONS,
                        model=model, quality=quality,
                    )
                    query = parse_qs(urlsplit(provider._build_api_url(request)).query)
                    self.assertEqual(query["model"], [model])
                    self.assertEqual(query.get("quality"), [expected])

    async def test_other_models_do_not_receive_gpt_quality(self):
        provider = PollinationsProvider({"api_key": "test-key"})
        request = ImageGenerationRequest(
            prompt="presentation background", provider=ImageProvider.POLLINATIONS,
            model="black-forest-labs/flux-1-schnell", quality="hd",
        )
        self.assertNotIn("quality", parse_qs(urlsplit(provider._build_api_url(request)).query))
