"""
AI provider implementations
"""

import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional, AsyncGenerator, Union, Tuple

from .base import AIProvider, AIMessage, AIResponse, MessageRole, TextContent, ImageContent, MessageContentType
from ..core.config import ai_config, resolve_timeout_seconds

logger = logging.getLogger(__name__)

def _get_llm_timeout_seconds(config: Dict[str, Any], *, default_seconds: float = 600.0) -> float:
    raw_timeout = config.get("llm_timeout_seconds")
    if raw_timeout is not None:
        return float(resolve_timeout_seconds(raw_timeout, int(default_seconds)))

    for key in ("http_timeout_seconds", "request_timeout_seconds", "timeout_seconds", "http_timeout", "timeout"):
        value = config.get(key)
        if value is None:
            continue
        try:
            seconds = float(value)
            if seconds > 0:
                return seconds
        except Exception:
            continue
    return float(resolve_timeout_seconds(None, int(default_seconds)))


def _get_httpx_timeout_seconds(config: Dict[str, Any], *, default_seconds: float = 600.0) -> float:
    """
    Get per-request HTTP timeout for OpenAI-compatible SDKs (which use httpx under the hood).

    Notes:
    - This is the *client-side* timeout. If the upstream gateway returns 504, increasing this
      won't override the gateway's own timeout, but it avoids local read timeouts for slower models.
    """
    return _get_llm_timeout_seconds(config, default_seconds=default_seconds)


def _build_aiohttp_timeout(config: Dict[str, Any], *, default_seconds: float = 600.0):
    try:
        import aiohttp
    except Exception:
        return None

    total = _get_llm_timeout_seconds(config, default_seconds=default_seconds)
    return aiohttp.ClientTimeout(total=total)


def _build_httpx_timeout(config: Dict[str, Any]):
    try:
        import httpx
    except Exception:
        return None

    total = _get_httpx_timeout_seconds(config, default_seconds=600.0)
    connect = min(30.0, total)
    write = min(30.0, total)
    pool = min(30.0, total)
    return httpx.Timeout(total, connect=connect, read=total, write=write, pool=pool)


class OpenAIProvider(AIProvider):
    """OpenAI API provider"""

    SUPPORTED_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.use_responses_api = self._coerce_bool(config.get("use_responses_api"))
        self.enable_reasoning = self._coerce_bool(config.get("enable_reasoning"))
        self.reasoning_effort = self._normalize_reasoning_effort(config.get("reasoning_effort")) or "medium"
        try:
            import openai
            timeout = _build_httpx_timeout(config)
            try:
                self.client = openai.AsyncOpenAI(
                    api_key=config.get("api_key"),
                    base_url=config.get("base_url"),
                    timeout=timeout,
                )
            except TypeError:
                self.client = openai.AsyncOpenAI(
                    api_key=config.get("api_key"),
                    base_url=config.get("base_url"),
                )
        except ImportError:
            logger.warning("OpenAI library not installed. Install with: pip install openai")
            self.client = None

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _should_use_responses_api(self, config: Dict[str, Any]) -> bool:
        return self._coerce_bool(config.get("use_responses_api", self.use_responses_api))

    @classmethod
    def _normalize_reasoning_effort(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized if normalized in cls.SUPPORTED_REASONING_EFFORTS else None

    def _should_enable_reasoning(self, config: Dict[str, Any]) -> bool:
        return self._coerce_bool(config.get("enable_reasoning", self.enable_reasoning))

    def _get_reasoning_effort(self, config: Dict[str, Any]) -> str:
        return (
            self._normalize_reasoning_effort(config.get("reasoning_effort"))
            or self.reasoning_effort
            or "medium"
        )

    def _apply_reasoning_config(
        self,
        request_kwargs: Dict[str, Any],
        config: Dict[str, Any],
        *,
        responses_api: bool,
    ) -> None:
        if not self._should_enable_reasoning(config):
            return

        reasoning_effort = self._get_reasoning_effort(config)
        if responses_api:
            request_kwargs["reasoning"] = {"effort": reasoning_effort}
        else:
            request_kwargs["reasoning_effort"] = reasoning_effort

    def _convert_message_to_openai(self, message: AIMessage) -> Dict[str, Any]:
        """Convert AIMessage to OpenAI format, supporting multimodal content"""
        openai_message = {"role": message.role.value}

        if isinstance(message.content, str):
            # Simple text message
            openai_message["content"] = message.content
        elif isinstance(message.content, list):
            # Multimodal message
            content_parts = []
            for part in message.content:
                if isinstance(part, TextContent):
                    content_parts.append({
                        "type": "text",
                        "text": part.text
                    })
                elif isinstance(part, ImageContent):
                    content_parts.append({
                        "type": "image_url",
                        "image_url": part.image_url
                    })
            openai_message["content"] = content_parts
        else:
            # Fallback to string representation
            openai_message["content"] = str(message.content)

        if message.name:
            openai_message["name"] = message.name

        return openai_message

    def _convert_message_to_responses_input(self, message: AIMessage) -> Dict[str, Any]:
        """Convert AIMessage to OpenAI Responses API input format."""
        responses_message: Dict[str, Any] = {"role": message.role.value}

        if isinstance(message.content, str):
            responses_message["content"] = message.content
            return responses_message

        if isinstance(message.content, list):
            content_parts = []
            for part in message.content:
                if isinstance(part, TextContent):
                    content_parts.append({
                        "type": "input_text",
                        "text": part.text,
                    })
                elif isinstance(part, ImageContent):
                    image_url = part.image_url.get("url") if isinstance(part.image_url, dict) else None
                    if image_url:
                        content_parts.append({
                            "type": "input_image",
                            "image_url": image_url,
                            "detail": "auto",
                        })
            responses_message["content"] = content_parts or str(message.content)
            return responses_message

        responses_message["content"] = str(message.content)
        return responses_message

    def _build_chat_completions_request(
        self,
        config: Dict[str, Any],
        openai_messages: List[Dict[str, Any]],
        *,
        stream: bool = False,
    ) -> Dict[str, Any]:
        request_kwargs: Dict[str, Any] = {
            "model": config.get("model", self.model),
            "messages": openai_messages,
            "temperature": config.get("temperature", 0.7),
            "top_p": config.get("top_p", 1.0),
        }
        if stream:
            request_kwargs["stream"] = True

        max_output_tokens = config.get("max_output_tokens")
        if max_output_tokens is not None:
            request_kwargs["max_tokens"] = max_output_tokens

        self._apply_reasoning_config(request_kwargs, config, responses_api=False)

        return request_kwargs

    def _build_responses_request(
        self,
        config: Dict[str, Any],
        responses_input: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        request_kwargs: Dict[str, Any] = {
            "model": config.get("model", self.model),
            "input": responses_input,
            "temperature": config.get("temperature", 0.7),
            "top_p": config.get("top_p", 1.0),
        }

        max_output_tokens = config.get("max_output_tokens")
        if max_output_tokens is not None:
            request_kwargs["max_output_tokens"] = max_output_tokens

        self._apply_reasoning_config(request_kwargs, config, responses_api=True)

        return request_kwargs

    @staticmethod
    def _extract_usage(usage: Any, *, prompt_key: str, completion_key: str, total_key: str) -> Dict[str, int]:
        return {
            "prompt_tokens": int(getattr(usage, prompt_key, 0) or 0),
            "completion_tokens": int(getattr(usage, completion_key, 0) or 0),
            "total_tokens": int(getattr(usage, total_key, 0) or 0),
        }

    @staticmethod
    def _find_first_match(text: str, markers: Tuple[str, ...]) -> Optional[Tuple[int, str]]:
        matches = []
        lowered = text.lower()
        for marker in markers:
            pos = lowered.find(marker.lower())
            if pos != -1:
                matches.append((pos, marker))
        if not matches:
            return None
        return min(matches, key=lambda item: item[0])

    async def _filter_think_chunks(self, chunks: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
        buffer = ""
        in_think_tag = False
        open_markers = ("<think", "＜think")
        close_markers = ("</think>", "＜/think＞")

        async for chunk_content in chunks:
            if not chunk_content:
                continue

            buffer += chunk_content
            processed_content = ""
            remaining_buffer = buffer

            while remaining_buffer:
                if not in_think_tag:
                    match = self._find_first_match(remaining_buffer, open_markers)
                    if match is None:
                        processed_content += remaining_buffer
                        remaining_buffer = ""
                        break

                    think_start, _ = match
                    processed_content += remaining_buffer[:think_start]
                    in_think_tag = True
                    remaining_buffer = remaining_buffer[think_start:]

                    tag_end_candidates = [remaining_buffer.find(">"), remaining_buffer.find("＞")]
                    tag_end_candidates = [idx for idx in tag_end_candidates if idx != -1]
                    if tag_end_candidates:
                        remaining_buffer = remaining_buffer[min(tag_end_candidates) + 1:]
                    else:
                        remaining_buffer = ""
                        break
                else:
                    match = self._find_first_match(remaining_buffer, close_markers)
                    if match is None:
                        remaining_buffer = ""
                        break

                    think_end, close_marker = match
                    in_think_tag = False
                    remaining_buffer = remaining_buffer[think_end + len(close_marker):]

            buffer = remaining_buffer

            if not in_think_tag and processed_content:
                yield processed_content

    def _filter_think_content(self, content: str) -> str:
        """
        Filter out content within think tags in all forms
        Supports: <think>, <think>, ＜think＞, 【think】 and their closing tags
        This prevents internal reasoning from being exposed in the output
        """
        if not content:
            return content

        import re

        # Pattern to match different forms of think tags (opening and closing)
        # Matches: <think>...</think>, <think>...</think>, ＜think＞...＜/think＞, 【think】...【/think】
        # Also handles self-closing and nested tags
        patterns = [
            r'<think[\s\S]*?></think>',           # <think>...</think>
        ]

        # Apply all patterns
        filtered_content = content
        for pattern in patterns:
            filtered_content = re.sub(pattern, '', filtered_content, flags=re.IGNORECASE)

        # # Clean up any extra whitespace that might be left behind
        # # Remove multiple consecutive empty lines
        # filtered_content = re.sub(r'\n\s*\n\s*\n\s*\n', '', filtered_content)

        # # Remove empty lines at the beginning and end
        # filtered_content = filtered_content.strip()

        # # Clean up extra spaces within lines
        # filtered_content = re.sub(r' +', ' ', filtered_content)

        return filtered_content

    async def _chat_completion_via_chat_completions(
        self,
        config: Dict[str, Any],
        openai_messages: List[Dict[str, Any]],
    ) -> AIResponse:
        request_kwargs = self._build_chat_completions_request(config, openai_messages)
        response = await self.client.chat.completions.create(**request_kwargs)

        choice = response.choices[0]
        filtered_content = self._filter_think_content(choice.message.content or "")

        return AIResponse(
            content=filtered_content,
            model=response.model,
            usage=self._extract_usage(
                response.usage,
                prompt_key="prompt_tokens",
                completion_key="completion_tokens",
                total_key="total_tokens",
            ),
            finish_reason=choice.finish_reason,
            metadata={"provider": "openai", "transport": "chat_completions"},
        )

    async def _chat_completion_via_responses(
        self,
        config: Dict[str, Any],
        responses_input: List[Dict[str, Any]],
    ) -> AIResponse:
        request_kwargs = self._build_responses_request(config, responses_input)
        response = await self.client.responses.create(**request_kwargs)

        incomplete_details = getattr(response, "incomplete_details", None)
        finish_reason = getattr(incomplete_details, "reason", None)
        if finish_reason is None and getattr(response, "status", None) == "completed":
            finish_reason = "stop"

        return AIResponse(
            content=self._filter_think_content(response.output_text or ""),
            model=response.model,
            usage=self._extract_usage(
                getattr(response, "usage", None),
                prompt_key="input_tokens",
                completion_key="output_tokens",
                total_key="total_tokens",
            ),
            finish_reason=finish_reason,
            metadata={"provider": "openai", "transport": "responses"},
        )
    
    async def chat_completion(self, messages: List[AIMessage], **kwargs) -> AIResponse:
        """Generate chat completion using OpenAI"""
        if not self.client:
            raise RuntimeError("OpenAI client not available")

        config = self._merge_config(**kwargs)
        use_responses_api = self._should_use_responses_api(config)
        
        try:
            if use_responses_api:
                responses_input = [self._convert_message_to_responses_input(msg) for msg in messages]
                return await self._chat_completion_via_responses(config, responses_input)

            openai_messages = [self._convert_message_to_openai(msg) for msg in messages]
            return await self._chat_completion_via_chat_completions(config, openai_messages)
            
        except Exception as e:
            # 提供更详细的错误信息
            error_msg = str(e)
            if "Expecting value" in error_msg:
                logger.error(f"OpenAI API JSON parsing error: {error_msg}. This usually indicates the API returned malformed JSON.")
            elif "timeout" in error_msg.lower():
                logger.error(f"OpenAI API timeout error: {error_msg}")
            elif "rate limit" in error_msg.lower():
                logger.error(f"OpenAI API rate limit error: {error_msg}")
            else:
                logger.error(f"OpenAI API error: {error_msg}")
            raise
    
    async def text_completion(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text completion using OpenAI chat format"""
        messages = [AIMessage(role=MessageRole.USER, content=prompt)]
        return await self.chat_completion(messages, **kwargs)

    async def stream_chat_completion(self, messages: List[AIMessage], **kwargs) -> AsyncGenerator[str, None]:
        """Stream chat completion using OpenAI with think tag filtering"""
        if not self.client:
            raise RuntimeError("OpenAI client not available")

        config = self._merge_config(**kwargs)
        use_responses_api = self._should_use_responses_api(config)

        try:
            if use_responses_api:
                responses_input = [self._convert_message_to_responses_input(msg) for msg in messages]
                request_kwargs = self._build_responses_request(config, responses_input)

                async def _responses_chunks() -> AsyncGenerator[str, None]:
                    async with self.client.responses.stream(**request_kwargs) as stream:
                        async for event in stream:
                            if getattr(event, "type", None) == "response.output_text.delta" and getattr(event, "delta", None):
                                yield event.delta

                async for visible_chunk in self._filter_think_chunks(_responses_chunks()):
                    yield visible_chunk
                return

            openai_messages = [self._convert_message_to_openai(msg) for msg in messages]
            request_kwargs = self._build_chat_completions_request(config, openai_messages, stream=True)
            stream = await self.client.chat.completions.create(**request_kwargs)

            async def _chat_completion_chunks() -> AsyncGenerator[str, None]:
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

            async for visible_chunk in self._filter_think_chunks(_chat_completion_chunks()):
                yield visible_chunk

        except Exception as e:
            logger.error(f"OpenAI streaming error: {e}")
            raise

    async def stream_text_completion(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream text completion using OpenAI chat format"""
        messages = [AIMessage(role=MessageRole.USER, content=prompt)]
        async for chunk in self.stream_chat_completion(messages, **kwargs):
            yield chunk


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI provider (OpenAI Python SDK AsyncAzureOpenAI)"""

    def __init__(self, config: Dict[str, Any]):
        # Do not call OpenAIProvider.__init__ (it would create AsyncOpenAI).
        AIProvider.__init__(self, config)
        try:
            import openai
            timeout = _build_httpx_timeout(config)

            try:
                self.client = openai.AsyncAzureOpenAI(
                    api_key=config.get("api_key"),
                    azure_endpoint=config.get("azure_endpoint"),
                    api_version=config.get("api_version"),
                    timeout=timeout,
                )
            except TypeError:
                self.client = openai.AsyncAzureOpenAI(
                    api_key=config.get("api_key"),
                    azure_endpoint=config.get("azure_endpoint"),
                    api_version=config.get("api_version"),
                )
        except ImportError:
            logger.warning("OpenAI library not installed. Install with: pip install openai")
            self.client = None


class AnthropicProvider(AIProvider):
    """Anthropic Claude API provider"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        try:
            import anthropic
            base_url = config.get("base_url")
            base_url = base_url.strip() if isinstance(base_url, str) else None

            timeout = _get_llm_timeout_seconds(config)

            try:
                if base_url:
                    self.client = anthropic.AsyncAnthropic(
                        api_key=config.get("api_key"),
                        base_url=base_url,
                        timeout=timeout,
                    )
                else:
                    self.client = anthropic.AsyncAnthropic(
                        api_key=config.get("api_key"),
                        timeout=timeout,
                    )
            except TypeError:
                # Backwards compatibility with older anthropic SDK versions
                self.client = anthropic.AsyncAnthropic(api_key=config.get("api_key"))
        except ImportError:
            logger.warning("Anthropic library not installed. Install with: pip install anthropic")
            self.client = None

    def _convert_message_to_anthropic(self, message: AIMessage) -> Dict[str, Any]:
        """Convert AIMessage to Anthropic format, supporting multimodal content"""
        anthropic_message = {"role": message.role.value}

        if isinstance(message.content, str):
            # Simple text message
            anthropic_message["content"] = message.content
        elif isinstance(message.content, list):
            # Multimodal message
            content_parts = []
            for part in message.content:
                if isinstance(part, TextContent):
                    content_parts.append({
                        "type": "text",
                        "text": part.text
                    })
                elif isinstance(part, ImageContent):
                    # Anthropic expects base64 data without the data URL prefix
                    image_url = part.image_url.get("url", "")
                    if image_url.startswith("data:image/"):
                        # Extract base64 data and media type
                        header, base64_data = image_url.split(",", 1)
                        media_type = header.split(":")[1].split(";")[0]
                        content_parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_data
                            }
                        })
                    else:
                        # For URL-based images, we'd need to fetch and convert to base64
                        # For now, skip or convert to text description
                        content_parts.append({
                            "type": "text",
                            "text": f"[Image: {image_url}]"
                        })
            anthropic_message["content"] = content_parts
        else:
            # Fallback to string representation
            anthropic_message["content"] = str(message.content)

        return anthropic_message
    
    async def chat_completion(self, messages: List[AIMessage], **kwargs) -> AIResponse:
        """Generate chat completion using Anthropic Claude (uses streaming internally to avoid timeout)"""
        if not self.client:
            raise RuntimeError("Anthropic client not available")

        config = self._merge_config(**kwargs)

        # 使用流式响应来避免 SDK 的 10 分钟超时限制
        # 收集所有流式块后返回完整响应
        try:
            full_content = ""
            async for chunk in self.stream_chat_completion(messages, **kwargs):
                full_content += chunk
            
            return AIResponse(
                content=full_content,
                model=config.get("model", self.model),
                usage={
                    "prompt_tokens": 0,  # 流式响应不提供精确的 token 统计
                    "completion_tokens": 0,
                    "total_tokens": 0
                },
                finish_reason="stop",
                metadata={"provider": "anthropic"}
            )
            
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise
    
    async def text_completion(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text completion using Anthropic chat format"""
        messages = [AIMessage(role=MessageRole.USER, content=prompt)]
        return await self.chat_completion(messages, **kwargs)

    async def stream_text_completion(
        self,
        prompt: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream text completion using Anthropic Claude for long-running requests"""
        messages = [AIMessage(role=MessageRole.USER, content=prompt)]
        async for chunk in self.stream_chat_completion(messages, **kwargs):
            yield chunk

    async def stream_chat_completion(
        self,
        messages: List[AIMessage],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion using Anthropic Claude with proper streaming support"""
        config = self._merge_config(**kwargs)
        api_key = config.get("api_key", "")
        base_url = config.get("base_url", "https://api.anthropic.com")
        model = config.get("model", self.model)
        # NOTE: `MAX_TOKENS` in this project refers to chunking/splitting, not model output length.
        # Anthropic Messages API requires `max_tokens`, so we use a conservative fixed default here.
        max_output_tokens = config.get("max_output_tokens", 32768)
        temperature = config.get("temperature", 0.7)

        # Convert messages to Anthropic format
        system_message = None
        claude_messages = []

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_message = msg.content if isinstance(msg.content, str) else str(msg.content)
            else:
                claude_messages.append(self._convert_message_to_anthropic(msg))

        try:
            import aiohttp

            # Build URL
            base_url = base_url.rstrip('/')
            if not base_url.endswith('/v1'):
                base_url = base_url + '/v1'
            url = f"{base_url}/messages"

            # Build request body
            body = {
                "model": model,
                "messages": claude_messages,
                "max_tokens": max_output_tokens,
                "temperature": temperature,
                "stream": True
            }
            if system_message:
                body["system"] = system_message

            # Try both authentication methods
            auth_methods = [
                ("x-api-key", {"x-api-key": api_key}),  # Official Anthropic style
                ("Authorization", {"Authorization": f"Bearer {api_key}"})  # MiniMax/other compatible APIs
            ]

            for auth_name, auth_header in auth_methods:
                try:
                    headers = {
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    }
                    headers.update(auth_header)

                    async with aiohttp.ClientSession(timeout=_build_aiohttp_timeout(config)) as session:
                        async with session.post(url, headers=headers, json=body) as response:
                            if response.status == 401 and auth_name == "x-api-key":
                                # x-api-key failed, try Authorization header
                                logger.debug("x-api-key auth failed, trying Authorization header")
                                break  # Exit inner loop to try next auth method

                            if response.status != 200:
                                error_text = await response.text()
                                if auth_name == "x-api-key":
                                    # Try next auth method
                                    logger.debug(f"x-api-key auth failed ({response.status}), trying Authorization")
                                    break  # Exit inner loop to try next auth method
                                raise Exception(f"API error {response.status}: {error_text}")

                            # Parse streaming response (SSE format)
                            async for line in response.content:
                                line = line.decode('utf-8').strip()
                                if line.startswith('data: '):
                                    data = line[6:]
                                    if data == '[DONE]':
                                        break
                                    try:
                                        import json
                                        event_data = json.loads(data)
                                        if event_data.get('type') == 'content_block_delta':
                                            delta = event_data.get('delta', {})
                                            if delta.get('type') == 'text_delta':
                                                text = delta.get('text', '')
                                                if text:
                                                    yield text
                                    except json.JSONDecodeError:
                                        pass
                            return  # Success, exit the function

                except Exception as auth_error:
                    logger.debug(f"Auth method {auth_name} failed: {auth_error}")
                    continue  # Try next auth method

            # If we get here, all auth methods failed
            raise Exception("All authentication methods failed")

        except Exception as e:
            logger.error(f"Anthropic streaming API error: {e}")
            raise

class GoogleProvider(AIProvider):
    """Google Gemini API provider"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Base URL can be a mirror/proxy endpoint. Frontend config test hits:
        #   {base_url}/v1beta/models/{model}:generateContent?key=...
        # The google-generativeai SDK defaults to the official endpoint unless configured,
        # so we keep the base_url and (when it's non-default) use direct REST calls.
        self.base_url = config.get("base_url", "https://generativelanguage.googleapis.com")
        try:
            import google.generativeai as genai

            # Configure the API key
            genai.configure(api_key=config.get("api_key"))

            self.client = genai
            self.model_instance = genai.GenerativeModel(config.get("model", "gemini-1.5-flash"))
        except ImportError:
            logger.warning("Google Generative AI library not installed. Install with: pip install google-generativeai")
            self.client = None
            self.model_instance = None

    def _should_use_rest_api(self, base_url: Optional[str]) -> bool:
        """
        Decide whether to use direct REST calls instead of the google-generativeai SDK.

        We must use REST when base_url points to a mirror/proxy (possibly with a path prefix),
        because the SDK may ignore it and attempt to connect to the official endpoint.
        """
        from urllib.parse import urlparse

        if not base_url:
            base_url = self.base_url

        base_url = str(base_url).strip()
        if not base_url:
            return False

        default_host = urlparse("https://generativelanguage.googleapis.com").netloc

        # If base_url doesn't look like an URL, treat it as a host[:port][/prefix].
        # Use REST for any non-default host, or when a path prefix is present.
        if "://" not in base_url:
            stripped = base_url.strip().lstrip("/")
            host = stripped.split("/", 1)[0]
            if host and host.lower() != default_host.lower():
                return True
            return "/" in stripped

        parsed = urlparse(base_url)
        # Any non-root path implies a prefix that the SDK cannot represent reliably.
        if parsed.path and parsed.path not in ("", "/"):
            return True

        # Non-default host implies mirror/proxy.
        return parsed.netloc and parsed.netloc.lower() != default_host.lower()

    def _normalize_gemini_base_url(self, base_url: str) -> str:
        """Normalize base_url to the API root without trailing /v1(/beta) suffix."""
        base_url = (base_url or "").strip()
        if not base_url:
            return "https://generativelanguage.googleapis.com"

        if not base_url.startswith("http"):
            base_url = "https://" + base_url

        base_url = base_url.rstrip("/")
        for suffix in ("/v1beta", "/v1"):
            if base_url.lower().endswith(suffix):
                base_url = base_url[: -len(suffix)]
                break
        return base_url.rstrip("/")

    def _messages_to_plaintext_prompt(self, messages: List[AIMessage]) -> str:
        """Best-effort conversion for REST API (keeps text, degrades images to placeholders)."""
        parts: List[str] = []
        for msg in messages:
            role_prefix = f"[{msg.role.value.upper()}]: "
            if isinstance(msg.content, str):
                parts.append(role_prefix + msg.content)
            elif isinstance(msg.content, list):
                msg_parts: List[str] = []
                for part in msg.content:
                    if isinstance(part, TextContent):
                        msg_parts.append(part.text)
                    elif isinstance(part, ImageContent):
                        url = part.image_url.get("url", "")
                        msg_parts.append(f"[Image: {url}]" if url else "[Image]")
                parts.append(role_prefix + " ".join(p for p in msg_parts if p))
            else:
                parts.append(role_prefix + str(msg.content))
        return "\n\n".join(parts)

    async def _rest_generate_content(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        generation_config: Dict[str, Any],
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        import aiohttp

        base_url = self._normalize_gemini_base_url(base_url)
        url = f"{base_url}/v1beta/models/{model}:generateContent"

        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
        ]

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
            "safetySettings": safety_settings,
        }

        timeout = _build_aiohttp_timeout(
            {"llm_timeout_seconds": timeout_seconds},
            default_seconds=600.0,
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Most mirrors and the official API support `?key=...`. Try that first.
            async with session.post(url, params={"key": api_key}, json=payload) as resp:
                if resp.status == 200:
                    return await resp.json()
                error_text = await resp.text()

            # Fallback: some proxies prefer header auth.
            headers = {"x-goog-api-key": api_key}
            async with session.post(url, headers=headers, json=payload) as resp2:
                if resp2.status == 200:
                    return await resp2.json()
                error_text2 = await resp2.text()

        raise RuntimeError(f"Gemini REST API request failed: {error_text.strip() or error_text2.strip()}")

    def _extract_rest_text(self, data: Dict[str, Any]) -> tuple[str, str, Dict[str, int]]:
        """Extract content, finish_reason, and usage from REST response JSON."""
        finish_reason = "stop"
        content = ""

        try:
            candidates = data.get("candidates") or []
            if candidates:
                candidate = candidates[0] or {}
                finish_reason = candidate.get("finishReason") or candidate.get("finish_reason") or finish_reason

                # Prefer the modern structure: candidate.content.parts[].text
                candidate_content = candidate.get("content") or {}
                candidate_parts = candidate_content.get("parts") or []
                texts = [p.get("text", "") for p in candidate_parts if isinstance(p, dict) and p.get("text")]
                if texts:
                    content = "".join(texts)
                else:
                    # Fallback: some mirrors may return `text` directly.
                    content = candidate.get("text") or ""
        except Exception:
            content = ""

        usage_meta = data.get("usageMetadata") or data.get("usage_metadata") or {}
        usage = {
            "prompt_tokens": int(usage_meta.get("promptTokenCount") or 0),
            "completion_tokens": int(usage_meta.get("candidatesTokenCount") or 0),
            "total_tokens": int(usage_meta.get("totalTokenCount") or 0),
        }
        return content, str(finish_reason), usage

    def _convert_messages_to_gemini(self, messages: List[AIMessage]):
        """Convert AIMessage list to Gemini format, supporting multimodal content"""
        import google.generativeai as genai
        import base64

        # Try to import genai types for proper image handling
        try:
            from google.genai import types
            GENAI_TYPES_AVAILABLE = True
        except ImportError:
            try:
                # Fallback to older API structure
                from google.generativeai import types
                GENAI_TYPES_AVAILABLE = True
            except ImportError:
                logger.warning("Google GenAI types not available for proper image processing")
                GENAI_TYPES_AVAILABLE = False

        # Check if we have any images
        has_images = any(
            isinstance(msg.content, list) and
            any(isinstance(part, ImageContent) for part in msg.content)
            for msg in messages
        )

        if not has_images:
            # Text-only mode - return string
            parts = []
            for msg in messages:
                role_prefix = f"[{msg.role.value.upper()}]: "
                if isinstance(msg.content, str):
                    parts.append(role_prefix + msg.content)
                elif isinstance(msg.content, list):
                    message_parts = [role_prefix]
                    for part in msg.content:
                        if isinstance(part, TextContent):
                            message_parts.append(part.text)
                    parts.append(" ".join(message_parts))
                else:
                    parts.append(role_prefix + str(msg.content))
            return "\n\n".join(parts)
        else:
            # Multimodal mode - return list of parts for Gemini
            content_parts = []

            for msg in messages:
                role_prefix = f"[{msg.role.value.upper()}]: "

                if isinstance(msg.content, str):
                    content_parts.append(role_prefix + msg.content)
                elif isinstance(msg.content, list):
                    text_parts = [role_prefix]

                    for part in msg.content:
                        if isinstance(part, TextContent):
                            text_parts.append(part.text)
                        elif isinstance(part, ImageContent):
                            # Add accumulated text first
                            if len(text_parts) > 1 or text_parts[0]:
                                content_parts.append(" ".join(text_parts))
                                text_parts = []

                            # Process image for Gemini
                            image_url = part.image_url.get("url", "")
                            if image_url.startswith("data:image/") and GENAI_TYPES_AVAILABLE:
                                try:
                                    # Extract base64 data and mime type
                                    header, base64_data = image_url.split(",", 1)
                                    mime_type = header.split(":")[1].split(";")[0]  # Extract mime type like 'image/jpeg'
                                    image_data = base64.b64decode(base64_data)

                                    # Create Gemini-compatible part from base64 image data
                                    image_part = None
                                    if GENAI_TYPES_AVAILABLE:
                                        if hasattr(types, 'Part') and hasattr(types.Part, 'from_bytes'):
                                            image_part = types.Part.from_bytes(
                                                data=image_data,
                                                mime_type=mime_type
                                            )
                                        elif hasattr(types, 'to_part'):
                                            image_part = types.to_part({
                                                'inline_data': {
                                                    'mime_type': mime_type,
                                                    'data': image_data
                                                }
                                            })
                                    if image_part is None:
                                        image_part = {
                                            'inline_data': {
                                                'mime_type': mime_type,
                                                'data': image_data
                                            }
                                        }
                                    content_parts.append(image_part)
                                    logger.info(f"Successfully processed image for Gemini: {mime_type}, {len(image_data)} bytes")
                                except Exception as e:
                                    logger.error(f"Failed to process image for Gemini: {e}")
                                    content_parts.append("请参考上传的图片进行设计。图片包含了重要的设计参考信息，请根据图片的风格、色彩、布局等元素来生成模板。")
                            else:
                                # Fallback when genai types not available or not base64 image
                                if image_url.startswith("data:image/"):
                                    content_parts.append("请参考上传的图片进行设计。图片包含了重要的设计参考信息，请根据图片的风格、色彩、布局等元素来生成模板。")
                                else:
                                    content_parts.append(f"请参考图片 {image_url} 进行设计")

                    # Add remaining text
                    if len(text_parts) > 1 or (len(text_parts) == 1 and text_parts[0]):
                        content_parts.append(" ".join(text_parts))
                else:
                    content_parts.append(role_prefix + str(msg.content))

            return content_parts

    async def chat_completion(self, messages: List[AIMessage], **kwargs) -> AIResponse:
        """Generate chat completion using Google Gemini"""
        config = self._merge_config(**kwargs)
        base_url = config.get("base_url") or self.base_url

        # Use direct REST for mirrors/proxies to honor base_url.
        if self._should_use_rest_api(base_url) or not self.client or not self.model_instance:
            api_key = config.get("api_key") or self.config.get("api_key")
            if not api_key:
                raise RuntimeError("Google Gemini API key not configured")

            model = config.get("model", self.model) or self.model
            generation_config: Dict[str, Any] = {
                "temperature": config.get("temperature", 0.7),
                "topP": config.get("top_p", 1.0),
            }
            max_output_tokens = config.get("max_output_tokens")
            if max_output_tokens is not None:
                generation_config["maxOutputTokens"] = max_output_tokens

            prompt_text = self._messages_to_plaintext_prompt(messages)
            data = await self._rest_generate_content(
                base_url=base_url,
                api_key=api_key,
                model=model,
                prompt=prompt_text,
                generation_config=generation_config,
                timeout_seconds=_get_llm_timeout_seconds(config),
            )
            content, finish_reason, usage = self._extract_rest_text(data)
            return AIResponse(
                content=content,
                model=model,
                usage=usage,
                finish_reason=finish_reason,
                metadata={"provider": "google", "transport": "rest"},
            )

        # Convert messages to Gemini format with multimodal support
        prompt = self._convert_messages_to_gemini(messages)

        try:
            # Configure generation parameters
            # 确保max_tokens不会太小，至少1000个token用于生成内容
            generation_config = {
                "temperature": config.get("temperature", 0.7),
                "top_p": config.get("top_p", 1.0),
            }
            max_output_tokens = config.get("max_output_tokens")
            if max_output_tokens is not None:
                generation_config["max_output_tokens"] = max_output_tokens

            # 配置安全设置 - 设置为较宽松的安全级别以减少误拦截
            safety_settings = [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_ONLY_HIGH"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_ONLY_HIGH"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_ONLY_HIGH"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_ONLY_HIGH"
                }
            ]


            response = await self._generate_async(
                prompt,
                generation_config,
                safety_settings,
                timeout_seconds=_get_llm_timeout_seconds(config),
            )
            logger.debug(f"Google Gemini API response: {response}")

            # 检查响应状态和安全过滤
            finish_reason = "stop"
            content = ""

            if response.candidates:
                candidate = response.candidates[0]
                finish_reason = candidate.finish_reason.name if hasattr(candidate.finish_reason, 'name') else str(candidate.finish_reason)

                # 检查是否被安全过滤器阻止或其他问题
                if finish_reason == "SAFETY":
                    logger.warning("Content was blocked by safety filters")
                    content = "[内容被安全过滤器阻止]"
                elif finish_reason == "RECITATION":
                    logger.warning("Content was blocked due to recitation")
                    content = "[内容因重复而被阻止]"
                elif finish_reason == "MAX_TOKENS":
                    logger.warning("Response was truncated due to max tokens limit")
                    # 尝试获取部分内容
                    try:
                        if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts') and candidate.content.parts:
                            content = candidate.content.parts[0].text if candidate.content.parts[0].text else "[响应因token限制被截断，无内容]"
                        else:
                            content = "[响应因token限制被截断，无内容]"
                    except Exception as text_error:
                        logger.warning(f"Failed to get truncated response text: {text_error}")
                        content = "[响应因token限制被截断，无法获取内容]"
                elif finish_reason == "OTHER":
                    logger.warning("Content was blocked for other reasons")
                    content = "[内容被其他原因阻止]"
                else:
                    # 正常情况下获取文本
                    try:
                        if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts') and candidate.content.parts:
                            content = candidate.content.parts[0].text if candidate.content.parts[0].text else ""
                        else:
                            # 回退到response.text
                            content = response.text if hasattr(response, 'text') and response.text else ""
                    except Exception as text_error:
                        logger.warning(f"Failed to get response text: {text_error}")
                        content = "[无法获取响应内容]"
            else:
                logger.warning("No candidates in response")
                content = "[响应中没有候选内容]"

            return AIResponse(
                content=content,
                model=self.model,
                usage={
                    "prompt_tokens": response.usage_metadata.prompt_token_count if hasattr(response, 'usage_metadata') else 0,
                    "completion_tokens": response.usage_metadata.candidates_token_count if hasattr(response, 'usage_metadata') else 0,
                    "total_tokens": response.usage_metadata.total_token_count if hasattr(response, 'usage_metadata') else 0
                },
                finish_reason=finish_reason,
                metadata={"provider": "google"}
            )

        except Exception as e:
            logger.error(f"Google Gemini API error: {e}")
            raise

    async def _generate_async(
        self,
        prompt,
        generation_config: Dict[str, Any],
        safety_settings=None,
        *,
        timeout_seconds: float = 600.0,
    ):
        """Async wrapper for Gemini generation - supports both text and multimodal content"""
        import asyncio
        loop = asyncio.get_event_loop()

        def _generate_sync():
            kwargs = {
                "generation_config": generation_config
            }
            if safety_settings:
                kwargs["safety_settings"] = safety_settings

            return self.model_instance.generate_content(
                prompt,  # Can be string or list of parts
                **kwargs
            )

        return await asyncio.wait_for(
            loop.run_in_executor(None, _generate_sync),
            timeout=timeout_seconds,
        )

    async def text_completion(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text completion using Google Gemini"""
        messages = [AIMessage(role=MessageRole.USER, content=prompt)]
        return await self.chat_completion(messages, **kwargs)

class OllamaProvider(AIProvider):
    """Ollama local model provider"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        try:
            import ollama
            self.client = ollama.AsyncClient(host=config.get("base_url", "http://localhost:11434"))
        except ImportError:
            logger.warning("Ollama library not installed. Install with: pip install ollama")
            self.client = None
    
    async def chat_completion(self, messages: List[AIMessage], **kwargs) -> AIResponse:
        """Generate chat completion using Ollama"""
        if not self.client:
            raise RuntimeError("Ollama client not available")
        
        config = self._merge_config(**kwargs)
        
        # Convert messages to Ollama format with multimodal support
        ollama_messages = []
        for msg in messages:
            if isinstance(msg.content, str):
                # Simple text message
                ollama_messages.append({"role": msg.role.value, "content": msg.content})
            elif isinstance(msg.content, list):
                # Multimodal message - convert to text description for Ollama
                content_parts = []
                for part in msg.content:
                    if isinstance(part, TextContent):
                        content_parts.append(part.text)
                    elif isinstance(part, ImageContent):
                        # Ollama doesn't support images directly, add text description
                        image_url = part.image_url.get("url", "")
                        if image_url.startswith("data:image/"):
                            content_parts.append("[Image provided - base64 data]")
                        else:
                            content_parts.append(f"[Image: {image_url}]")
                ollama_messages.append({
                    "role": msg.role.value,
                    "content": " ".join(content_parts)
                })
            else:
                # Fallback to string representation
                ollama_messages.append({"role": msg.role.value, "content": str(msg.content)})
        
        try:
            options: Dict[str, Any] = {
                "temperature": config.get("temperature", 0.7),
                "top_p": config.get("top_p", 1.0),
            }
            max_output_tokens = config.get("max_output_tokens")
            if max_output_tokens is not None:
                options["num_predict"] = max_output_tokens

            response = await asyncio.wait_for(
                self.client.chat(
                    model=config.get("model", self.model),
                    messages=ollama_messages,
                    options=options,
                ),
                timeout=_get_llm_timeout_seconds(config),
            )
            
            content = response.get("message", {}).get("content", "")
            
            return AIResponse(
                content=content,
                model=config.get("model", self.model),
                usage=self._calculate_usage(
                    " ".join([msg.content for msg in messages]),
                    content
                ),
                finish_reason="stop",
                metadata={"provider": "ollama"}
            )
            
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            raise
    
    async def text_completion(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text completion using Ollama"""
        messages = [AIMessage(role=MessageRole.USER, content=prompt)]
        return await self.chat_completion(messages, **kwargs)

class AIProviderFactory:
    """Factory for creating AI providers"""

    _providers = {
        "openai": OpenAIProvider,
        "azure_openai": AzureOpenAIProvider,
        "azure": AzureOpenAIProvider,  # Alias for azure_openai
        "anthropic": AnthropicProvider,
        "google": GoogleProvider,
        "gemini": GoogleProvider,  # Alias for google
        "ollama": OllamaProvider,
        "302ai": OpenAIProvider,  # 302.AI uses OpenAI-compatible API
        "landppt": OpenAIProvider,  # LandPPT Official uses OpenAI-compatible API
    }

    @classmethod
    def create_provider(cls, provider_name: str, config: Optional[Dict[str, Any]] = None) -> AIProvider:
        """Create an AI provider instance"""
        if config is None:
            config = ai_config.get_provider_config(provider_name)

        # Built-in providers
        if provider_name not in cls._providers:
            raise ValueError(f"Unknown provider: {provider_name}")

        provider_class = cls._providers[provider_name]
        return provider_class(config)
    
    @classmethod
    def get_available_providers(cls) -> List[str]:
        """Get list of available providers"""
        return list(cls._providers.keys())

class AIProviderManager:
    """Manager for AI provider instances with caching and reloading"""

    def __init__(self):
        self._provider_cache = {}
        self._config_cache = {}

    def get_provider(self, provider_name: Optional[str] = None) -> AIProvider:
        """Get AI provider instance with caching"""
        if provider_name is None:
            provider_name = ai_config.default_ai_provider
        if provider_name not in AIProviderFactory._providers:
            logger.warning(f"Unknown provider '{provider_name}', falling back to 'openai'")
            provider_name = "openai"

        # Get current config for the provider
        current_config = ai_config.get_provider_config(provider_name)

        # Check if we have a cached provider and if config has changed
        cache_key = provider_name
        if (cache_key in self._provider_cache and
            cache_key in self._config_cache and
            self._config_cache[cache_key] == current_config):
            return self._provider_cache[cache_key]

        # Create new provider instance
        provider = AIProviderFactory.create_provider(provider_name, current_config)

        # Cache the provider and config
        self._provider_cache[cache_key] = provider
        self._config_cache[cache_key] = current_config

        return provider

    def clear_cache(self):
        """Clear provider cache to force reload"""
        self._provider_cache.clear()
        self._config_cache.clear()

    def reload_provider(self, provider_name: str):
        """Reload a specific provider"""
        cache_key = provider_name
        if cache_key in self._provider_cache:
            del self._provider_cache[cache_key]
        if cache_key in self._config_cache:
            del self._config_cache[cache_key]

# Global provider manager
_provider_manager = AIProviderManager()

def get_ai_provider(provider_name: Optional[str] = None) -> AIProvider:
    """Get AI provider instance"""
    return _provider_manager.get_provider(provider_name)


def get_role_provider(role: str, provider_override: Optional[str] = None) -> Tuple[AIProvider, Dict[str, Optional[str]]]:
    """Get provider and settings for a specific task role"""
    settings = ai_config.get_model_config_for_role(role, provider_override=provider_override)
    provider = get_ai_provider(settings["provider"])
    return provider, settings

def reload_ai_providers():
    """Reload all AI providers (clear cache)"""
    _provider_manager.clear_cache()
