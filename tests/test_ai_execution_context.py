from landppt.services.runtime.ai_execution import ExecutionContext, ProviderConfig


def test_execution_context_maps_processing_config_kwargs():
    context = ExecutionContext.from_mapping(
        "outline",
        {
            "llm_provider": "openai",
            "llm_model": "gpt-5.4",
            "api_key": "test-key",
            "base_url": "https://example.com/v1",
            "temperature": 0.2,
            "max_tokens": 4096,
            "use_responses_api": True,
            "enable_reasoning": True,
            "reasoning_effort": "high",
        },
        user_id=7,
        source="user_db",
    )

    assert context.role == "outline"
    assert context.user_id == 7
    assert context.source == "user_db"
    assert context.to_processing_config_kwargs() == {
        "llm_model": "gpt-5.4",
        "llm_provider": "openai",
        "temperature": 0.2,
        "max_tokens": 4096,
        "api_key": "test-key",
        "base_url": "https://example.com/v1",
        "use_responses_api": True,
        "enable_reasoning": True,
        "reasoning_effort": "high",
    }


def test_provider_config_preserves_unmodeled_fields_as_extras():
    provider = ProviderConfig.from_mapping(
        {
            "provider": "anthropic",
            "model": "claude-test",
            "timeout_seconds": 120,
            "region": "us-east-1",
        }
    )

    assert provider.provider == "anthropic"
    assert provider.model == "claude-test"
    assert provider.extras == {
        "timeout_seconds": 120,
        "region": "us-east-1",
    }
