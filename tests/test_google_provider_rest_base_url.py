import pytest


@pytest.mark.asyncio
async def test_google_provider_uses_configured_base_url_for_rest(monkeypatch):
    # Import inside test so conftest adds src/ to sys.path first.
    from landppt.ai.providers import GoogleProvider

    calls = []

    class FakeResponse:
        def __init__(self, status, json_data=None, text_data=""):
            self.status = status
            self._json_data = json_data or {}
            self._text_data = text_data

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._json_data

        async def text(self):
            return self._text_data

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, params=None, json=None, headers=None):
            calls.append({"url": url, "params": params, "json": json, "headers": headers})
            return FakeResponse(
                200,
                json_data={
                    "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
                    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2, "totalTokenCount": 3},
                },
            )

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)

    provider = GoogleProvider(
        {
            "api_key": "test-key",
            # Include a path prefix to force REST mode and validate URL construction.
            "base_url": "https://mirror.example.com/prefix",
            "model": "gemini-1.5-flash",
        }
    )

    resp = await provider.text_completion("hello", temperature=0, top_p=1.0, max_output_tokens=16)

    assert resp.content == "ok"
    assert resp.metadata.get("transport") == "rest"
    assert calls, "expected at least one HTTP call"
    assert calls[0]["url"] == "https://mirror.example.com/prefix/v1beta/models/gemini-1.5-flash:generateContent"
    assert calls[0]["params"] == {"key": "test-key"}

