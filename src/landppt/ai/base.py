"""
Base classes for AI providers
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator, Union
from pydantic import BaseModel
from enum import Enum

class MessageRole(str, Enum):
    """Message roles for AI conversations"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

class MessageContentType(str, Enum):
    """Message content types for multimodal support"""
    TEXT = "text"
    IMAGE_URL = "image_url"

class ImageContent(BaseModel):
    """Image content for multimodal messages"""
    type: MessageContentType = MessageContentType.IMAGE_URL
    image_url: Dict[str, str]  # {"url": "data:image/jpeg;base64,..." or "http://..."}

class TextContent(BaseModel):
    """Text content for multimodal messages"""
    type: MessageContentType = MessageContentType.TEXT
    text: str

class AIMessage(BaseModel):
    """AI message model with multimodal support"""
    role: MessageRole
    content: Union[str, List[Union[TextContent, ImageContent]]]  # Support both simple string and multimodal content
    name: Optional[str] = None

class AIResponse(BaseModel):
    """AI response model"""
    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: Optional[str] = None
    metadata: Dict[str, Any] = {}

class AIProvider(ABC):
    """Abstract base class for AI providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get("model", "unknown")
    
    @abstractmethod
    async def chat_completion(
        self,
        messages: List[AIMessage],
        **kwargs
    ) -> AIResponse:
        """Generate chat completion"""
        pass
    
    @abstractmethod
    async def text_completion(
        self,
        prompt: str,
        **kwargs
    ) -> AIResponse:
        """Generate text completion"""
        pass
    
    async def stream_chat_completion(
        self,
        messages: List[AIMessage],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion (optional)"""
        # Default implementation: return full response at once
        response = await self.chat_completion(messages, **kwargs)
        yield response.content
    
    async def stream_text_completion(
        self,
        prompt: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream text completion (optional)"""
        # Default implementation: return full response at once
        response = await self.text_completion(prompt, **kwargs)
        yield response.content
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information"""
        return {
            "model": self.model,
            "provider": self.__class__.__name__,
            "config": {k: v for k, v in self.config.items() if "key" not in k.lower()}
        }
    
    def _calculate_usage(self, prompt: str, response: str) -> Dict[str, int]:
        """Calculate token usage (simplified)"""
        # Simplified calculation
        prompt_tokens = len(prompt.split())
        completion_tokens = len(response.split())
        
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    
    def _merge_config(self, **kwargs) -> Dict[str, Any]:
        """
        Merge provider config with request parameters.

        Note:
        - In this project, `MAX_TOKENS/max_tokens` refers to the *chunking/splitting* limit.
          It must not be forwarded to model providers as an output length constraint.
        - Use `max_output_tokens` to control model output length when needed.
        """
        merged = self.config.copy()
        merged.pop("max_tokens", None)

        # Drop ambiguous / legacy parameter to avoid accidentally coupling chunking to model output.
        kwargs.pop("max_tokens", None)

        max_output_tokens = kwargs.pop("max_output_tokens", None)
        merged.update(kwargs)
        if max_output_tokens is not None:
            merged["max_output_tokens"] = max_output_tokens

        return merged
