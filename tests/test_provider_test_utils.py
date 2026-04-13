from landppt.services.provider_test_utils import (
    build_anthropic_messages_url,
    build_google_generate_content_url,
    extract_anthropic_test_result,
    extract_google_test_result,
    extract_openai_compatible_test_result,
    normalize_provider_name,
)


def test_normalize_provider_name_maps_gemini_alias():
    assert normalize_provider_name("gemini") == "google"
    assert normalize_provider_name(" GOOGLE ") == "google"


def test_build_google_generate_content_url_normalizes_version_suffix_and_keeps_prefix():
    url = build_google_generate_content_url(
        "https://mirror.example.com/prefix/v1beta",
        "gemini-2.5-flash",
    )

    assert url == "https://mirror.example.com/prefix/v1beta/models/gemini-2.5-flash:generateContent"


def test_extract_google_test_result_reads_text_and_usage():
    response_text, usage = extract_google_test_result(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hello"},
                            {"text": " Gemini"},
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 5,
                "totalTokenCount": 8,
            },
        }
    )

    assert response_text == "Hello Gemini"
    assert usage == {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}


def test_build_anthropic_messages_url_appends_v1_messages():
    assert build_anthropic_messages_url("api.anthropic.com") == "https://api.anthropic.com/v1/messages"


def test_extract_anthropic_test_result_converts_usage_shape():
    response_text, usage = extract_anthropic_test_result(
        {
            "content": [{"text": "hello from claude"}],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }
    )

    assert response_text == "hello from claude"
    assert usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


def test_extract_openai_compatible_test_result_supports_chat_and_responses_api():
    chat_text, chat_usage = extract_openai_compatible_test_result(
        {
            "choices": [{"message": {"content": "hello from chat"}}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21},
        },
        use_responses_api=False,
    )
    responses_text, responses_usage = extract_openai_compatible_test_result(
        {
            "output_text": "hello from responses",
            "usage": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
        },
        use_responses_api=True,
    )

    assert chat_text == "hello from chat"
    assert chat_usage == {"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21}
    assert responses_text == "hello from responses"
    assert responses_usage == {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}
