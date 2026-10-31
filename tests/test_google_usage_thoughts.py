from types import SimpleNamespace


def test_sdk_usage_counts_thinking_tokens_as_completion():
    # Import inside test so conftest adds src/ to sys.path first.
    from landppt.ai.providers import GoogleProvider

    meta = SimpleNamespace(
        prompt_token_count=3,
        candidates_token_count=5,
        thoughts_token_count=20,
        total_token_count=28,
    )

    usage = GoogleProvider._gemini_sdk_usage(SimpleNamespace(usage_metadata=meta))

    assert usage == {"prompt_tokens": 3, "completion_tokens": 25, "total_tokens": 28}


def test_sdk_usage_tolerates_missing_counts():
    from landppt.ai.providers import GoogleProvider

    meta = SimpleNamespace(
        prompt_token_count=None,
        candidates_token_count=None,
        thoughts_token_count=None,
        total_token_count=None,
    )

    assert GoogleProvider._gemini_sdk_usage(SimpleNamespace(usage_metadata=meta)) == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert GoogleProvider._gemini_sdk_usage(SimpleNamespace(usage_metadata=None))[
        "completion_tokens"
    ] == 0


def test_rest_usage_counts_thinking_tokens_as_completion():
    from landppt.ai.providers import GoogleProvider

    provider = GoogleProvider.__new__(GoogleProvider)
    _, _, usage = provider._extract_rest_text(
        {
            "candidates": [{"content": {"parts": [{"text": "Hi"}]}, "finishReason": "STOP"}],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 5,
                "thoughtsTokenCount": 20,
                "totalTokenCount": 28,
            },
        }
    )

    assert usage["completion_tokens"] == 25
