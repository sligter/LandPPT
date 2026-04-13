"""
Explicit execution context objects for provider-bound workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    use_responses_api: bool = False
    enable_reasoning: bool = False
    reasoning_effort: str = "medium"
    extras: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "ProviderConfig":
        return cls(
            provider=str(data.get("llm_provider") or data.get("provider") or "openai"),
            model=data.get("llm_model") or data.get("model"),
            api_key=data.get("api_key"),
            base_url=data.get("base_url"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            use_responses_api=bool(data.get("use_responses_api")),
            enable_reasoning=bool(data.get("enable_reasoning")),
            reasoning_effort=str(data.get("reasoning_effort") or "medium"),
            extras={
                key: value
                for key, value in data.items()
                if key
                not in {
                    "llm_provider",
                    "provider",
                    "llm_model",
                    "model",
                    "api_key",
                    "base_url",
                    "temperature",
                    "max_tokens",
                    "use_responses_api",
                    "enable_reasoning",
                    "reasoning_effort",
                }
            },
        )


@dataclass(frozen=True)
class ExecutionContext:
    role: str
    provider: ProviderConfig
    user_id: Optional[int] = None
    source: str = "resolved"

    @classmethod
    def from_mapping(
        cls,
        role: str,
        data: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
        source: str = "resolved",
    ) -> "ExecutionContext":
        return cls(
            role=role,
            provider=ProviderConfig.from_mapping(data),
            user_id=user_id,
            source=source,
        )

    def to_processing_config_kwargs(self) -> Dict[str, Any]:
        return {
            "llm_model": self.provider.model,
            "llm_provider": self.provider.provider,
            "temperature": self.provider.temperature,
            "max_tokens": self.provider.max_tokens,
            "api_key": self.provider.api_key,
            "base_url": self.provider.base_url,
            "use_responses_api": self.provider.use_responses_api,
            "enable_reasoning": self.provider.enable_reasoning,
            "reasoning_effort": self.provider.reasoning_effort,
        }

