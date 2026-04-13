"""
LangChain adapter for LandPPT AI providers.

This allows LangChain pipelines (prompt | llm | parser) to reuse the unified
LandPPT provider layer (src/landppt/ai/providers.py) instead of maintaining a
separate LLM client stack.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import Field

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage as LangChainAIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from .base import AIMessage, MessageRole
from .providers import AIProviderFactory
from ..core.config import ai_config


_ROLE_MAP: Dict[str, MessageRole] = {
    "system": MessageRole.SYSTEM,
    "human": MessageRole.USER,
    "user": MessageRole.USER,
    "ai": MessageRole.ASSISTANT,
    "assistant": MessageRole.ASSISTANT,
}


class LandPPTChatModel(BaseChatModel):
    """
    A LangChain BaseChatModel backed by LandPPT AIProvider implementations.

    Supports provider-specific overrides via kwargs (api_key/base_url/azure_endpoint/api_version).
    """

    provider: str = Field(default="openai")
    model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=8192)

    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    azure_endpoint: Optional[str] = Field(default=None)
    api_version: Optional[str] = Field(default=None)
    use_responses_api: bool = Field(default=False)
    enable_reasoning: bool = Field(default=False)
    reasoning_effort: Optional[str] = Field(default=None)

    @property
    def _llm_type(self) -> str:  # noqa: D401
        return "landppt_ai_provider"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "base_url": self.base_url,
            "azure_endpoint": self.azure_endpoint,
            "api_version": self.api_version,
            "use_responses_api": self.use_responses_api,
            "enable_reasoning": self.enable_reasoning,
            "reasoning_effort": self.reasoning_effort,
        }

    @staticmethod
    def _to_landppt_messages(messages: List[Any]) -> List[AIMessage]:
        converted: List[AIMessage] = []
        for msg in messages:
            msg_type = getattr(msg, "type", None) or getattr(msg, "role", None) or "user"
            role = _ROLE_MAP.get(str(msg_type).lower(), MessageRole.USER)
            content = getattr(msg, "content", "")
            converted.append(AIMessage(role=role, content=content))
        return converted

    def _build_provider_config(self, **kwargs: Any) -> Dict[str, Any]:
        provider_name = (kwargs.get("provider") or self.provider or ai_config.default_ai_provider).strip()
        base_config = ai_config.get_provider_config(provider_name)
        merged = dict(base_config)
        merged.update({k: v for k, v in kwargs.items() if v is not None and k != "provider"})

        # Allow instance-level overrides (useful for DB/user-scoped credentials).
        if self.api_key:
            merged["api_key"] = self.api_key
        if self.base_url:
            merged["base_url"] = self.base_url
        if self.azure_endpoint:
            merged["azure_endpoint"] = self.azure_endpoint
        if self.api_version:
            merged["api_version"] = self.api_version
        if self.use_responses_api:
            merged["use_responses_api"] = True
        if self.enable_reasoning:
            merged["enable_reasoning"] = True
        if self.reasoning_effort:
            merged["reasoning_effort"] = self.reasoning_effort

        return merged

    async def _agenerate(
        self,
        messages: List[Any],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        provider_name = (kwargs.get("provider") or self.provider or ai_config.default_ai_provider).strip()
        config = self._build_provider_config(**kwargs)
        provider = AIProviderFactory.create_provider(provider_name, config=config)

        landppt_messages = self._to_landppt_messages(messages)
        request_overrides: Dict[str, Any] = {
            "messages": landppt_messages,
            "model": kwargs.get("model") or self.model,
            "temperature": kwargs.get("temperature") if kwargs.get("temperature") is not None else self.temperature,
        }
        max_tokens_override = kwargs.get("max_tokens")
        request_overrides["max_output_tokens"] = (
            max_tokens_override if max_tokens_override is not None else self.max_tokens
        )
        if kwargs.get("top_p") is not None:
            request_overrides["top_p"] = kwargs.get("top_p")

        response = await provider.chat_completion(**request_overrides)

        return ChatResult(
            generations=[ChatGeneration(message=LangChainAIMessage(content=response.content))],
            llm_output={
                "token_usage": response.usage,
                "model": response.model,
                "provider": provider_name,
            },
        )

    async def _astream(
        self,
        messages: List[Any],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        provider_name = (kwargs.get("provider") or self.provider or ai_config.default_ai_provider).strip()
        config = self._build_provider_config(**kwargs)
        provider = AIProviderFactory.create_provider(provider_name, config=config)

        landppt_messages = self._to_landppt_messages(messages)
        request_overrides: Dict[str, Any] = {
            "messages": landppt_messages,
            "model": kwargs.get("model") or self.model,
            "temperature": kwargs.get("temperature") if kwargs.get("temperature") is not None else self.temperature,
        }
        max_tokens_override = kwargs.get("max_tokens")
        request_overrides["max_output_tokens"] = (
            max_tokens_override if max_tokens_override is not None else self.max_tokens
        )
        if kwargs.get("top_p") is not None:
            request_overrides["top_p"] = kwargs.get("top_p")

        async for token in provider.stream_chat_completion(**request_overrides):
            if not token:
                continue
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
            if run_manager:
                await run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk

    def _generate(
        self,
        messages: List[Any],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs))


def get_langchain_chat_model(
    *,
    provider: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    **kwargs: Any,
) -> BaseChatModel:
    """
    Factory used by src/summeryanyfile to obtain a LangChain LLM using the unified provider layer.
    """

    return LandPPTChatModel(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=kwargs.get("api_key"),
        base_url=kwargs.get("base_url"),
        azure_endpoint=kwargs.get("azure_endpoint"),
        api_version=kwargs.get("api_version"),
        use_responses_api=bool(kwargs.get("use_responses_api")),
        enable_reasoning=bool(kwargs.get("enable_reasoning")),
        reasoning_effort=kwargs.get("reasoning_effort"),
    )
