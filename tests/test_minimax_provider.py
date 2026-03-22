"""
Tests for MiniMax provider configuration, factory registration,
temperature clamping, and reload_ai_config() support.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Unit tests – configuration defaults
# ---------------------------------------------------------------------------


class TestMiniMaxConfigDefaults:
    """Verify that the AIConfig singleton ships the correct MiniMax defaults."""

    def test_default_base_url(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key")
        assert cfg.minimax_base_url == "https://api.minimax.io/v1"

    def test_default_model(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key")
        assert cfg.minimax_model == "MiniMax-M2.7"

    def test_custom_model_via_env(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.5-highspeed")
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key")
        assert cfg.minimax_model == "MiniMax-M2.5-highspeed"

    def test_custom_base_url_via_env(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_BASE_URL", "https://custom.proxy.example/v1")
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key")
        assert cfg.minimax_base_url == "https://custom.proxy.example/v1"


# ---------------------------------------------------------------------------
# Unit tests – provider availability
# ---------------------------------------------------------------------------


class TestMiniMaxProviderAvailability:
    """Provider should be available only when an API key is configured."""

    def test_available_with_api_key(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key")
        assert cfg.is_provider_available("minimax") is True

    def test_unavailable_without_api_key(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key=None)
        assert cfg.is_provider_available("minimax") is False

    def test_appears_in_available_list(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key")
        providers = cfg.get_available_providers()
        assert "minimax" in providers

    def test_absent_from_available_list_without_key(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key=None)
        providers = cfg.get_available_providers()
        assert "minimax" not in providers


# ---------------------------------------------------------------------------
# Unit tests – temperature clamping
# ---------------------------------------------------------------------------


class TestMiniMaxTemperatureClamping:
    """MiniMax API requires temperature <= 1.0."""

    def test_temperature_clamped_to_1(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key", temperature=1.5)
        config = cfg.get_provider_config("minimax")
        assert config["temperature"] <= 1.0

    def test_temperature_not_altered_when_valid(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key", temperature=0.7)
        config = cfg.get_provider_config("minimax")
        assert config["temperature"] == 0.7

    def test_temperature_zero_allowed(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key", temperature=0.0)
        config = cfg.get_provider_config("minimax")
        assert config["temperature"] == 0.0

    def test_openai_temperature_not_clamped(self):
        """Other providers should not be affected by MiniMax clamping."""
        from landppt.core.config import AIConfig

        cfg = AIConfig(openai_api_key="test-key", temperature=1.5)
        config = cfg.get_provider_config("openai")
        assert config["temperature"] == 1.5


# ---------------------------------------------------------------------------
# Unit tests – get_provider_config contents
# ---------------------------------------------------------------------------


class TestMiniMaxProviderConfig:
    """Verify the dictionary returned by get_provider_config('minimax')."""

    def test_config_keys(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key")
        config = cfg.get_provider_config("minimax")
        assert "api_key" in config
        assert "base_url" in config
        assert "model" in config
        assert "max_tokens" in config
        assert "temperature" in config

    def test_config_values(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(minimax_api_key="test-key")
        config = cfg.get_provider_config("minimax")
        assert config["api_key"] == "test-key"
        assert config["base_url"] == "https://api.minimax.io/v1"
        assert config["model"] == "MiniMax-M2.7"


# ---------------------------------------------------------------------------
# Unit tests – model role resolution
# ---------------------------------------------------------------------------


class TestMiniMaxRoleResolution:
    """Role-based model config should resolve MiniMax correctly."""

    def test_default_role_with_minimax_provider(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(
            minimax_api_key="test-key",
            default_ai_provider="minimax",
        )
        role_cfg = cfg.get_model_config_for_role("default")
        assert role_cfg["provider"] == "minimax"
        assert role_cfg["model"] == "MiniMax-M2.7"

    def test_role_override_to_minimax(self):
        from landppt.core.config import AIConfig

        cfg = AIConfig(
            minimax_api_key="test-key",
            default_ai_provider="openai",
        )
        role_cfg = cfg.get_model_config_for_role("default", provider_override="minimax")
        assert role_cfg["provider"] == "minimax"
        assert role_cfg["model"] == "MiniMax-M2.7"


# ---------------------------------------------------------------------------
# Unit tests – reload_ai_config
# ---------------------------------------------------------------------------


class TestMiniMaxReloadConfig:
    """reload_ai_config() should pick up MiniMax env var changes."""

    def test_reload_updates_minimax_model(self, monkeypatch):
        from landppt.core.config import ai_config, reload_ai_config

        monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.5")
        reload_ai_config()
        assert ai_config.minimax_model == "MiniMax-M2.5"

    def test_reload_updates_minimax_base_url(self, monkeypatch):
        from landppt.core.config import ai_config, reload_ai_config

        monkeypatch.setenv("MINIMAX_BASE_URL", "https://proxy.example/v1")
        reload_ai_config()
        assert ai_config.minimax_base_url == "https://proxy.example/v1"

    def test_reload_updates_minimax_api_key(self, monkeypatch):
        from landppt.core.config import ai_config, reload_ai_config

        monkeypatch.setenv("MINIMAX_API_KEY", "new-test-key")
        reload_ai_config()
        assert ai_config.minimax_api_key == "new-test-key"


# ---------------------------------------------------------------------------
# Unit tests – factory registration
# ---------------------------------------------------------------------------


class TestMiniMaxFactoryRegistration:
    """MiniMax must be registered in the AIProviderFactory."""

    def test_minimax_in_factory_providers(self):
        from landppt.ai.providers import AIProviderFactory

        available = AIProviderFactory.get_available_providers()
        assert "minimax" in available

    def test_factory_creates_openai_provider(self):
        from landppt.ai.providers import AIProviderFactory, OpenAIProvider

        config = {
            "api_key": "test-key",
            "base_url": "https://api.minimax.io/v1",
            "model": "MiniMax-M2.7",
            "max_tokens": 16384,
            "temperature": 0.7,
            "top_p": 1.0,
        }
        provider = AIProviderFactory.create_provider("minimax", config)
        assert isinstance(provider, OpenAIProvider)


# ---------------------------------------------------------------------------
# Integration tests – MiniMax API calls (requires MINIMAX_API_KEY)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("MINIMAX_API_KEY"),
    reason="MINIMAX_API_KEY not set – skipping live API tests",
)
class TestMiniMaxIntegration:
    """Live integration tests against the MiniMax API."""

    @pytest.mark.asyncio
    async def test_chat_completion(self):
        from landppt.ai.providers import AIProviderFactory

        config = {
            "api_key": os.environ["MINIMAX_API_KEY"],
            "base_url": "https://api.minimax.io/v1",
            "model": "MiniMax-M2.7",
            "max_tokens": 64,
            "temperature": 0.7,
            "top_p": 1.0,
        }
        provider = AIProviderFactory.create_provider("minimax", config)

        from landppt.ai.base import AIMessage, MessageRole

        messages = [AIMessage(role=MessageRole.USER, content="Say hello in one word.")]
        response = await provider.chat_completion(messages)
        assert response.content
        assert len(response.content) > 0

    @pytest.mark.asyncio
    async def test_stream_chat_completion(self):
        from landppt.ai.providers import AIProviderFactory

        config = {
            "api_key": os.environ["MINIMAX_API_KEY"],
            "base_url": "https://api.minimax.io/v1",
            "model": "MiniMax-M2.7",
            "max_tokens": 64,
            "temperature": 0.7,
            "top_p": 1.0,
        }
        provider = AIProviderFactory.create_provider("minimax", config)

        from landppt.ai.base import AIMessage, MessageRole

        messages = [AIMessage(role=MessageRole.USER, content="Say hello in one word.")]
        chunks = []
        async for chunk in provider.stream_chat_completion(messages):
            chunks.append(chunk)
        full = "".join(chunks)
        assert len(full) > 0

    @pytest.mark.asyncio
    async def test_temperature_zero(self):
        """MiniMax should accept temperature=0."""
        from landppt.ai.providers import AIProviderFactory

        config = {
            "api_key": os.environ["MINIMAX_API_KEY"],
            "base_url": "https://api.minimax.io/v1",
            "model": "MiniMax-M2.7",
            "max_tokens": 32,
            "temperature": 0.0,
            "top_p": 1.0,
        }
        provider = AIProviderFactory.create_provider("minimax", config)

        from landppt.ai.base import AIMessage, MessageRole

        messages = [AIMessage(role=MessageRole.USER, content="Reply OK.")]
        response = await provider.chat_completion(messages)
        assert response.content
