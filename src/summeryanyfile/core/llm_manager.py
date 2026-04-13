"""
LLM manager for SummeryAnyFile.

This module intentionally delegates all real model invocation to the unified
LandPPT AI provider layer (src/landppt/ai/*) to avoid maintaining two separate
client stacks in this repository.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from landppt.ai.langchain_adapter import get_langchain_chat_model

logger = logging.getLogger(__name__)


class LLMManager:
    """Create LangChain chat models backed by the unified LandPPT AI providers."""

    SUPPORTED_PROVIDERS: Dict[str, str] = {
        "openai": "landppt_ai",
        "anthropic": "landppt_ai",
        "azure": "landppt_ai",  # Azure OpenAI (alias of azure_openai)
        "azure_openai": "landppt_ai",
        "ollama": "landppt_ai",
        "google": "landppt_ai",
        "gemini": "landppt_ai",
        "landppt": "landppt_ai",  # OpenAI-compatible
        "302ai": "landppt_ai",  # OpenAI-compatible
    }

    SUPPORTED_MODELS: Dict[str, list[str]] = {
        "openai": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
        ],
        "anthropic": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ],
        "azure": [],  # Deployment names are user-defined
        "azure_openai": [],
        "ollama": [],
        "gemini": [
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-1.0-pro",
            "gemini-pro-vision",
        ],
        "google": [
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-1.0-pro",
            "gemini-pro-vision",
        ],
        "landppt": [],
        "302ai": [],
    }

    def __init__(self) -> None:
        self._llm_cache: Dict[str, BaseChatModel] = {}

    def get_llm(
        self,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        **kwargs: Any,
    ) -> BaseChatModel:
        provider_key = (provider or "openai").strip().lower()
        if provider_key not in self.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider: {provider}. Supported: {list(self.SUPPORTED_PROVIDERS.keys())}"
            )

        api_key = str(kwargs.get("api_key") or "")
        base_url = str(kwargs.get("base_url") or "")
        azure_endpoint = str(kwargs.get("azure_endpoint") or "")
        api_version = str(kwargs.get("api_version") or "")
        use_responses_api = bool(kwargs.get("use_responses_api"))
        enable_reasoning = bool(kwargs.get("enable_reasoning"))
        reasoning_effort = str(kwargs.get("reasoning_effort") or "")
        api_key_hash = hash(api_key) if api_key else "none"
        cache_key = (
            f"{provider_key}:{model}:{temperature}:{max_tokens}:"
            f"{api_key_hash}:{base_url}:{azure_endpoint}:{api_version}:{use_responses_api}:"
            f"{enable_reasoning}:{reasoning_effort}"
        )

        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]

        supported_models = self.SUPPORTED_MODELS.get(provider_key, [])
        if supported_models and model not in supported_models:
            logger.info(f"Using custom model for provider {provider_key}: {model}")

        llm = get_langchain_chat_model(
            provider=provider_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        self._llm_cache[cache_key] = llm
        return llm

    def validate_configuration(self, provider: str, **kwargs: Any) -> bool:
        provider_key = (provider or "").strip().lower()

        if provider_key in ("openai", "landppt", "302ai"):
            api_key = kwargs.get("api_key") or os.getenv("OPENAI_API_KEY") or os.getenv("302AI_API_KEY")
            return bool(api_key)
        if provider_key == "anthropic":
            api_key = kwargs.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
            return bool(api_key)
        if provider_key in ("azure", "azure_openai"):
            api_key = kwargs.get("api_key") or os.getenv("AZURE_OPENAI_API_KEY")
            endpoint = kwargs.get("azure_endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT")
            return bool(api_key and endpoint)
        if provider_key in ("google", "gemini"):
            api_key = kwargs.get("api_key") or os.getenv("GOOGLE_API_KEY")
            return bool(api_key)
        if provider_key == "ollama":
            base_url = kwargs.get("base_url") or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            return bool(base_url)

        return False

    def list_available_models(self, provider: str) -> list[str]:
        provider_key = (provider or "").strip().lower()
        return self.SUPPORTED_MODELS.get(provider_key, [])

    def clear_cache(self) -> None:
        self._llm_cache.clear()
