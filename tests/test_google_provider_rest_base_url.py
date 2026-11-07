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
    assert "maxOutputTokens" not in calls[0]["json"]["generationConfig"]



@pytest.mark.asyncio
async def test_google_provider_rest_sends_tools_and_returns_function_calls(monkeypatch):
    from landppt.ai.providers import GoogleProvider

    calls = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return {
                "candidates": [
                    {
                        "content": {"parts": [{"functionCall": {"name": "get_time", "args": {"tz": "UTC"}}}]},
                        "finishReason": "STOP",
                    }
                ]
            }

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, params=None, json=None, headers=None):
            calls.append(json)
            return FakeResponse()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)

    provider = GoogleProvider(
        {"api_key": "test-key", "base_url": "https://mirror.example.com/prefix", "model": "gemini-1.5-flash"}
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get the time",
                "parameters": {"type": "object", "properties": {"tz": {"type": "string"}}},
            },
        }
    ]

    resp = await provider.text_completion("what time is it", tools=tools)

    assert calls[0]["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "get_time",
                    "description": "Get the time",
                    "parametersJsonSchema": {"type": "object", "properties": {"tz": {"type": "string"}}},
                }
            ]
        }
    ]
    assert resp.tool_calls == [
        {
            "id": "gemini-tool-call-1",
            "type": "function",
            "function": {"name": "get_time", "arguments": '{"tz": "UTC"}'},
        }
    ]


def _fake_rest_session(monkeypatch, responses):
    """Patch aiohttp so each POST returns the next canned JSON body; returns the captured payloads."""
    payloads = []

    class FakeResponse:
        status = 200

        def __init__(self, body):
            self._body = body

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return self._body

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, params=None, json=None, headers=None):
            payloads.append(json)
            return FakeResponse(responses[len(payloads) - 1])

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    return payloads


def _rest_provider():
    from landppt.ai.providers import GoogleProvider

    return GoogleProvider(
        {"api_key": "test-key", "base_url": "https://mirror.example.com/prefix", "model": "gemini-3.8-flash"}
    )


@pytest.mark.asyncio
async def test_google_provider_rest_sends_editor_tool_schemas_as_json_schema(monkeypatch):
    from landppt.services.slide.edit_agent.tools import SlideEditToolbox

    payloads = _fake_rest_session(
        monkeypatch, [{"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}]
    )
    schemas = SlideEditToolbox.native_schemas()
    assert any("additionalProperties" in (s.get("function") or s).get("parameters", {}) for s in schemas)

    await _rest_provider().text_completion("edit", tools=schemas)

    declarations = payloads[0]["tools"][0]["functionDeclarations"]
    assert len(declarations) == len(schemas)
    for declaration, schema in zip(declarations, schemas):
        function = schema.get("function") or schema
        # Gemini's restricted `parameters` Schema rejects additionalProperties; the full
        # JSON schema must travel in `parametersJsonSchema` unchanged.
        assert "parameters" not in declaration
        assert declaration["parametersJsonSchema"] == function["parameters"]


@pytest.mark.asyncio
async def test_google_provider_rest_tool_round_trip_keeps_call_id_and_signature(monkeypatch):
    from landppt.services.slide.edit_agent.protocol import NativeToolProtocolAdapter
    from landppt.services.slide.edit_agent.tools import SlideEditToolbox
    from landppt.ai.base import AIMessage, MessageRole

    first_turn = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {"id": "call_abc123", "name": "read_slide", "args": {"x": 1}},
                            "thoughtSignature": "sig-xyz",
                        }
                    ],
                },
                "finishReason": "STOP",
            }
        ]
    }
    second_turn = {"candidates": [{"content": {"parts": [{"text": "done"}]}, "finishReason": "STOP"}]}
    payloads = _fake_rest_session(monkeypatch, [first_turn, second_turn])
    provider = _rest_provider()

    async def chat(*, messages, **kwargs):
        return await provider.chat_completion(messages, **kwargs)

    adapter = NativeToolProtocolAdapter(
        chat,
        [AIMessage(role=MessageRole.USER, content="shorten slide 2")],
        SlideEditToolbox.native_schemas(),
    )

    turn = await adapter.next_turn()
    assert turn.tool_calls[0].id == "call_abc123"
    adapter.record_turn(turn)
    adapter.record_tool_result(turn.tool_calls[0], {"ok": True, "summary": "read"})

    await adapter.next_turn()

    contents = payloads[1]["contents"]
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[0]["parts"] == [{"text": "[USER]: shorten slide 2"}]
    assert contents[1]["parts"] == [
        {
            "functionCall": {"id": "call_abc123", "name": "read_slide", "args": {"x": 1}},
            "thoughtSignature": "sig-xyz",
        }
    ]
    assert contents[2]["parts"] == [
        {
            "functionResponse": {
                "id": "call_abc123",
                "name": "read_slide",
                "response": {"ok": True, "summary": "read"},
            }
        }
    ]


@pytest.mark.asyncio
async def test_google_provider_rest_round_trip_omits_synthetic_ids(monkeypatch):
    from landppt.ai.base import AIMessage, MessageRole

    payloads = _fake_rest_session(
        monkeypatch, [{"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}]
    )
    messages = [
        AIMessage(role=MessageRole.USER, content="go"),
        AIMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[
                {"id": "gemini-tool-call-1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                {"id": "gemini-tool-call-2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
            ],
        ),
        AIMessage(role=MessageRole.TOOL, content='{"r": 1}', tool_call_id="gemini-tool-call-1"),
        AIMessage(role=MessageRole.TOOL, content="plain", tool_call_id="gemini-tool-call-2"),
    ]

    await _rest_provider().chat_completion(messages)

    contents = payloads[0]["contents"]
    assert contents[1]["parts"] == [
        {"functionCall": {"name": "a", "args": {}}},
        {"functionCall": {"name": "b", "args": {}}},
    ]
    # Parallel results go back in a single user turn, matched to their calls by name.
    assert contents[2]["parts"] == [
        {"functionResponse": {"name": "a", "response": {"r": 1}}},
        {"functionResponse": {"name": "b", "response": {"result": "plain"}}},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("block_reason", ["SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "OTHER"])
async def test_google_provider_rest_reports_blocked_prompt(monkeypatch, block_reason):
    _fake_rest_session(monkeypatch, [{"promptFeedback": {"blockReason": block_reason}}])

    response = await _rest_provider().text_completion("hello")

    assert response.content == "[内容被安全过滤器阻止]"
    assert response.finish_reason == block_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("feedback", [{}, {"safetyRatings": []}])
async def test_google_provider_rest_allows_unblocked_prompt_feedback(monkeypatch, feedback):
    _fake_rest_session(
        monkeypatch,
        [{
            "promptFeedback": feedback,
            "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
        }],
    )

    response = await _rest_provider().text_completion("hello")

    assert response.content == "ok"
    assert response.finish_reason == "STOP"
