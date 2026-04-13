import asyncio
import json
import sys
import types
from types import SimpleNamespace

import httpx
import pytest

from summeryanyfile.core.mineru_api_client import MineruAPIClient


def test_mineru_api_key_sanitization():
    assert MineruAPIClient(api_key="Bearer abc").api_key == "abc"
    assert MineruAPIClient(api_key="Authorization: Bearer abc").api_key == "abc"
    assert MineruAPIClient(api_key=" 'abc' ").api_key == "abc"


def test_apply_upload_url_for_file_posts_to_batch_endpoint_and_stores_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/file-urls/batch")

        body = json.loads(request.content.decode("utf-8"))
        assert body["files"][0]["name"] == "demo.pdf"
        assert body["model_version"] == "pipeline"
        assert body["enable_formula"] is True
        assert body["enable_table"] is True
        assert body["language"] == "ch"

        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"batch_id": "b1", "file_urls": ["https://upload.test/presigned"]},
            },
        )

    transport = httpx.MockTransport(handler)
    client = MineruAPIClient(api_key="abc", base_url="https://mineru.net/api/v4")

    async def run() -> str:
        client._client = httpx.AsyncClient(
            base_url=client.base_url, headers=client._get_headers(), transport=transport
        )
        batch_id = await client._apply_upload_url_for_file(
            file_name="demo.pdf",
            enable_ocr=True,
            enable_formula=True,
            enable_table=True,
            language="ch",
        )
        await client.close()
        return batch_id

    batch_id = asyncio.run(run())
    assert batch_id == "b1"
    assert client._pending_file_urls["b1"]["demo.pdf"] == "https://upload.test/presigned"


@pytest.mark.asyncio
async def test_upload_zip_images_rewrites_markdown_image_with_size(monkeypatch):
    uploaded = []

    class FakeImageService:
        async def upload_image(self, upload_request, data):
            uploaded.append((upload_request, data))
            return SimpleNamespace(
                success=True,
                image_info=SimpleNamespace(
                    image_id="public_demo",
                    metadata=SimpleNamespace(width=320, height=180),
                ),
            )

    class FakeImageUploadRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    image_service_module = types.ModuleType("landppt.services.image.image_service")
    image_service_module.get_image_service = lambda: FakeImageService()
    image_models_module = types.ModuleType("landppt.services.image.models")
    image_models_module.ImageUploadRequest = FakeImageUploadRequest
    url_service_module = types.ModuleType("landppt.services.url_service")
    url_service_module.build_image_url = (
        lambda image_id, width=None, height=None:
        f"http://localhost:8001/api/image/view/{image_id}"
        + (
            f"?width={width}px&height={height}px"
            if width and height
            else ""
        )
    )

    monkeypatch.setitem(sys.modules, "landppt.services.image.image_service", image_service_module)
    monkeypatch.setitem(sys.modules, "landppt.services.image.models", image_models_module)
    monkeypatch.setitem(sys.modules, "landppt.services.url_service", url_service_module)

    client = MineruAPIClient(api_key="abc")
    markdown = "段落\n![感知与指令腐蚀概况](images/demo.png)\n结尾"

    result = await client._upload_zip_images_to_local_gallery_and_replace_links(
        markdown_content=markdown,
        images={"images/demo.png": b"fake-image-bytes"},
    )

    assert uploaded
    assert (
        "![感知与指令腐蚀概况（图片大小：320x180px）]"
        "(http://localhost:8001/api/image/view/public_demo?width=320px&height=180px)"
    ) in result
    assert "images/http://" not in result
