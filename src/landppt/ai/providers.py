"""
AI provider implementations
"""

import asyncio
import json
import logging
import re
import hashlib
import threading
import uuid
from importlib.metadata import PackageNotFoundError, version as package_version
from urllib.parse import urlparse
from collections import OrderedDict
from typing import List, Dict, Any, Optional, AsyncGenerator, Union, Tuple

from .base import AIProvider, AIMessage, AIResponse, MessageRole, TextContent, ImageContent, MessageContentType
from ..core.config import ai_config, resolve_timeout_seconds
from ..services.provider_test_utils import google_model_accepts_sampling_params

logger = logging.getLogger(__name__)


def build_opencode_session_headers(
    base_url: Optional[str],
    conversation_id: Optional[str],
) -> Dict[str, str]:
    """Build OpenCode Go's session header without affecting other providers."""
    session_id = str(conversation_id or "").strip()
    if not session_id or len(session_id) > 256 or any(char in session_id for char in "\r\n"):
        return {}

    try:
        parsed = urlparse(str(base_url or "").strip())
    except ValueError:
        return {}

    hostname = (parsed.hostname or "").lower().rstrip(".")
    path = (parsed.path or "").rstrip("/")
    if parsed.scheme not in {"http", "https"} or hostname != "opencode.ai":
        return {}
    if path != "/zen/go" and not path.startswith("/zen/go/"):
        return {}

    return {"x-opencode-session": session_id}


def build_opencode_client_headers(base_url: Optional[str]) -> Dict[str, str]:
    """Identify LandPPT honestly on OpenCode Go without changing other providers."""
    if not build_opencode_session_headers(base_url, "landppt-client-check"):
        return {}
    try:
        client_version = package_version("landppt")
    except PackageNotFoundError:
        client_version = "unknown"
    return {"User-Agent": f"LandPPT/{client_version}"}


def build_opencode_test_session_headers(base_url: Optional[str]) -> Dict[str, str]:
    """Create a fresh session for one provider connectivity-test lifecycle."""
    return build_opencode_session_headers(base_url, uuid.uuid4().hex)

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


# Reasoning / "think" block markers emitted by some models (DeepSeek-R1, QwQ, etc.).
# Covers <think>/<thinking>, full-width ＜think＞ and bracket 【think】 variants, with
# optional attributes on the opening tag.
_THINK_BLOCK_RE = re.compile(
    r'[<＜【]\s*think(?:ing)?[^>＞】]*[>＞】][\s\S]*?[<＜【]\s*/\s*think(?:ing)?\s*[>＞】]',
    re.IGNORECASE,
)
_THINK_OPEN_RE = re.compile(r'[<＜【]\s*think(?:ing)?[^>＞】]*[>＞】]', re.IGNORECASE)
_THINK_LONE_CLOSE_RE = re.compile(
    r'^[\s\S]*?[<＜【]\s*/\s*think(?:ing)?\s*[>＞】]', re.IGNORECASE
)


def strip_think_content(content: str) -> str:
    """Remove model reasoning/think blocks so internal reasoning never reaches the user.

    Handles well-formed <think>...</think> blocks (plus <thinking>, full-width ＜think＞
    and bracket 【think】 variants), and the common case where a gateway strips the
    opening tag but leaves the reasoning followed by a lone closing tag.
    """
    if not content:
        return content

    cleaned = _THINK_BLOCK_RE.sub('', content)

    # Opening tag was stripped upstream but reasoning + lone "</think>" remain before the
    # real answer: drop everything up to and including that closing tag.
    if not _THINK_OPEN_RE.search(cleaned):
        cleaned = _THINK_LONE_CLOSE_RE.sub('', cleaned, count=1)

    return cleaned.strip()


# OpenAI reasoning models (gpt-5.x and later, o1/o3/o4) answer 400 to a non-default
# temperature/top_p, so those fields have to be left out of the request.
_OPENAI_REASONING_MODEL_RE = re.compile(
    r"(?:^|/)(?:gpt-(?:[5-9]|\d{2,})(?!-chat)|o[134](?![0-9a-z]))", re.IGNORECASE
)
# gpt-5.1 and later accept temperature/top_p again when the request sets reasoning
# effort to ``none``. Not every model has that effort: gpt-5, gpt-5-mini and the
# o-series, the codex/pro variants, gpt-6-astra and gpt-6.1-sol always reject them.
_OPENAI_NONE_EFFORT_MODEL_RE = re.compile(
    r"(?:^|/)gpt-(?:5\.[1-9]\d*|[6-9]|\d{2,})(?![0-9])(?!-(?:chat|codex|pro|astra)|\.\d+-sol)",
    re.IGNORECASE,
)
# gpt-5.1 defaults to ``none`` when no effort is sent; the other models default to medium.
_OPENAI_DEFAULT_NONE_MODEL_RE = re.compile(r"(?:^|/)gpt-5\.1(?:-\d{4}-\d{2}-\d{2})?$", re.IGNORECASE)


def _openai_rejects_sampling(model: Any, reasoning_effort: Optional[str] = None) -> bool:
    if not isinstance(model, str) or _OPENAI_REASONING_MODEL_RE.search(model) is None:
        return False
    if reasoning_effort is None and _OPENAI_DEFAULT_NONE_MODEL_RE.search(model) is not None:
        reasoning_effort = "none"
    if reasoning_effort == "none" and _OPENAI_NONE_EFFORT_MODEL_RE.search(model) is not None:
        return False
    return True


class OpenAIProvider(AIProvider):
    """OpenAI API provider"""

    SUPPORTED_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.use_responses_api = self._coerce_bool(config.get("use_responses_api"))
        self.enable_reasoning = self._coerce_bool(config.get("enable_reasoning"))
        self.reasoning_effort = self._normalize_reasoning_effort(config.get("reasoning_effort")) or "medium"
        try:
            import openai
            timeout = _build_httpx_timeout(config)
            client_kwargs = {
                "api_key": config.get("api_key"),
                "base_url": config.get("base_url"),
                "timeout": timeout,
            }
            if config.get("managed_provider"):
                import httpx
                client_kwargs["http_client"] = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
            client_headers = build_opencode_client_headers(config.get("base_url"))
            if client_headers:
                client_kwargs["default_headers"] = client_headers
            try:
                self.client = openai.AsyncOpenAI(**client_kwargs)
            except TypeError:
                client_kwargs.pop("timeout", None)
                try:
                    self.client = openai.AsyncOpenAI(**client_kwargs)
                except TypeError:
                    client_kwargs.pop("default_headers", None)
                    self.client = openai.AsyncOpenAI(**client_kwargs)
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

    def _effective_reasoning_effort(self, config: Dict[str, Any]) -> Optional[str]:
        """The effort the request will carry, or None when no reasoning is sent."""
        if not self._should_enable_reasoning(config):
            return None
        return self._get_reasoning_effort(config)

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
        if message.tool_call_id:
            openai_message["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            openai_message["tool_calls"] = message.tool_calls

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
        tools = config.pop("tools", None)
        tool_choice = config.pop("tool_choice", None)
        parallel_tool_calls = config.pop("parallel_tool_calls", None)
        request_kwargs: Dict[str, Any] = {
            "model": config.get("model", self.model),
            "messages": openai_messages,
        }
        if not _openai_rejects_sampling(
            request_kwargs["model"], self._effective_reasoning_effort(config)
        ):
            request_kwargs["temperature"] = config.get("temperature", 0.7)
            request_kwargs["top_p"] = config.get("top_p", 1.0)
        if stream:
            request_kwargs["stream"] = True
        if tools:
            request_kwargs["tools"] = tools
        if tool_choice is not None:
            request_kwargs["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            request_kwargs["parallel_tool_calls"] = parallel_tool_calls

        self._apply_reasoning_config(request_kwargs, config, responses_api=False)

        from ..services.runtime.ai_execution import get_current_ai_conversation_id
        extra_headers = build_opencode_session_headers(
            config.get("base_url"),
            config.get("conversation_id") or get_current_ai_conversation_id(),
        )
        if extra_headers:
            request_kwargs["extra_headers"] = extra_headers

        return request_kwargs

    def _extract_openai_tool_calls(self, message: Any) -> List[Dict[str, Any]]:
        tool_calls = getattr(message, "tool_calls", None) or []
        normalized: List[Dict[str, Any]] = []
        for call in tool_calls:
            function = getattr(call, "function", None)
            normalized.append(
                {
                    "id": getattr(call, "id", None) or "",
                    "type": getattr(call, "type", None) or "function",
                    "function": {
                        "name": getattr(function, "name", None) or "",
                        "arguments": getattr(function, "arguments", None) or "{}",
                    },
                }
            )
        return normalized

    def _build_responses_request(
        self,
        config: Dict[str, Any],
        responses_input: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        request_kwargs: Dict[str, Any] = {
            "model": config.get("model", self.model),
            "input": responses_input,
        }
        if not _openai_rejects_sampling(
            request_kwargs["model"], self._effective_reasoning_effort(config)
        ):
            request_kwargs["temperature"] = config.get("temperature", 0.7)
            request_kwargs["top_p"] = config.get("top_p", 1.0)

        self._apply_reasoning_config(request_kwargs, config, responses_api=True)

        from ..services.runtime.ai_execution import get_current_ai_conversation_id
        extra_headers = build_opencode_session_headers(
            config.get("base_url"),
            config.get("conversation_id") or get_current_ai_conversation_id(),
        )
        if extra_headers:
            request_kwargs["extra_headers"] = extra_headers

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

    @staticmethod
    def _longest_partial_marker_suffix(text: str, markers: Tuple[str, ...]) -> int:
        """Length of the trailing text that could still grow into a marker.

        Streaming chunks split anywhere, so a buffer ending in ``"...<thi"`` must be
        held back rather than emitted or discarded.
        """
        lowered = text.lower()
        longest = 0
        for marker in markers:
            marker_lower = marker.lower()
            # Try the longest prefix of the marker that the text ends with.
            for length in range(min(len(marker_lower) - 1, len(lowered)), 0, -1):
                if lowered.endswith(marker_lower[:length]):
                    longest = max(longest, length)
                    break
        return longest

    async def _filter_think_chunks(self, chunks: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
        """Strip <think> blocks from a stream without losing or leaking content.

        Markers are matched across chunk boundaries: a split ``</think>`` used to
        leave ``in_think_tag`` permanently true and silently swallow the rest of the
        response, and text preceding a ``<think>`` in the same chunk was dropped.
        """
        buffer = ""
        in_think_tag = False
        open_markers = ("<think", "＜think")
        close_markers = ("</think>", "＜/think＞")

        async for chunk_content in chunks:
            if not chunk_content:
                continue

            buffer += chunk_content
            emit = ""

            while buffer:
                if not in_think_tag:
                    match = self._find_first_match(buffer, open_markers)
                    if match is None:
                        # Keep back anything that might be the start of a marker.
                        hold = self._longest_partial_marker_suffix(buffer, open_markers)
                        if hold:
                            emit += buffer[:-hold]
                            buffer = buffer[-hold:]
                        else:
                            emit += buffer
                            buffer = ""
                        break

                    think_start, _ = match
                    emit += buffer[:think_start]
                    candidate = buffer[think_start:]

                    # Wait for the tag to actually close before skipping it: the
                    # opening tag itself may be split across chunks.
                    tag_end_candidates = [candidate.find(">"), candidate.find("＞")]
                    tag_end_candidates = [idx for idx in tag_end_candidates if idx != -1]
                    if not tag_end_candidates:
                        buffer = candidate
                        break

                    in_think_tag = True
                    buffer = candidate[min(tag_end_candidates) + 1:]
                else:
                    match = self._find_first_match(buffer, close_markers)
                    if match is None:
                        # Discard reasoning text, but retain a possible partial
                        # closing marker so the next chunk can complete it.
                        hold = self._longest_partial_marker_suffix(buffer, close_markers)
                        buffer = buffer[-hold:] if hold else ""
                        break

                    think_end, close_marker = match
                    in_think_tag = False
                    buffer = buffer[think_end + len(close_marker):]

            if emit:
                yield emit

        # Flush anything held back that never became a marker.
        if buffer and not in_think_tag:
            yield buffer

    def _filter_think_content(self, content: str) -> str:
        """Filter out model reasoning/think blocks before exposing output.

        Delegates to the shared ``strip_think_content`` helper. Supports
        <think>/<thinking>, full-width ＜think＞ and bracket 【think】 variants.
        """
        return strip_think_content(content or "")

    async def _chat_completion_via_chat_completions(
        self,
        config: Dict[str, Any],
        openai_messages: List[Dict[str, Any]],
    ) -> AIResponse:
        request_kwargs = self._build_chat_completions_request(config, openai_messages)
        response = await self.client.chat.completions.create(**request_kwargs)

        choice = response.choices[0]
        tool_calls = self._extract_openai_tool_calls(choice.message)
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
            tool_calls=tool_calls,
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
    
    async def collect_streamed_chat_completion(
        self, messages: List[AIMessage], **kwargs
    ) -> AIResponse:
        from .streaming_completion import collect_openai_completion

        return await collect_openai_completion(self, messages, **kwargs)

    async def chat_completion(self, messages: List[AIMessage], **kwargs) -> AIResponse:
        """Generate chat completion using OpenAI"""
        if not self.client:
            raise RuntimeError("OpenAI client not available")

        config = self._merge_config(**kwargs)
        use_responses_api = self._should_use_responses_api(config) and not config.get("tools")
        
        try:
            if use_responses_api:
                responses_input = [self._convert_message_to_responses_input(msg) for msg in messages]
                return await self._chat_completion_via_responses(config, responses_input)

            openai_messages = [self._convert_message_to_openai(msg) for msg in messages]
            return await self._chat_completion_via_chat_completions(config, openai_messages)
            
        except Exception as e:
            # 提供更详细的错误信息
            if self.config.get("managed_provider"):
                from ..services.managed_provider_service import ManagedProviderError
                logger.warning("Managed AI request failed (%s)", type(e).__name__)
                raise ManagedProviderError("AI 提供商调用失败，请检查密钥、模型和接口地址，或稍后重试") from None
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
            if self.config.get("managed_provider"):
                from ..services.managed_provider_service import ManagedProviderError
                logger.warning("Managed AI stream failed (%s)", type(e).__name__)
                raise ManagedProviderError("AI 提供商流式调用失败，请检查配置或稍后重试") from None
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


# Claude 4.7 and later (Opus 4.7+, the 5.x families, Mythos Preview) answer 400 to
# a non-default temperature/top_p/top_k, so the field has to be left out.
_CLAUDE_FIXED_SAMPLING_RE = re.compile(
    r"claude-(?:opus-4-(?:[7-9]|[1-9]\d)(?!\d)"
    r"|(?:opus|sonnet|haiku|fable|mythos)-(?:[5-9]|[1-9]\d)(?!\d)"
    r"|mythos-preview)",
    re.IGNORECASE,
)


def _claude_rejects_temperature(model: Any) -> bool:
    return isinstance(model, str) and _CLAUDE_FIXED_SAMPLING_RE.search(model) is not None


class AnthropicProvider(AIProvider):
    """Anthropic Claude API provider"""

    SUPPORTED_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.enable_reasoning = OpenAIProvider._coerce_bool(config.get("enable_reasoning"))
        self.reasoning_effort = self._normalize_reasoning_effort(config.get("reasoning_effort")) or "high"
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

    @classmethod
    def _normalize_reasoning_effort(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized if normalized in cls.SUPPORTED_REASONING_EFFORTS else None

    def _apply_reasoning_config(self, request_kwargs: Dict[str, Any], config: Dict[str, Any]) -> None:
        if not OpenAIProvider._coerce_bool(config.get("enable_reasoning", self.enable_reasoning)):
            return

        effort = (
            self._normalize_reasoning_effort(config.get("reasoning_effort"))
            or self.reasoning_effort
            or "high"
        )
        request_kwargs["output_config"] = {"effort": effort}

    def _convert_message_to_anthropic(self, message: AIMessage) -> Dict[str, Any]:
        """Convert AIMessage to Anthropic format, supporting multimodal content"""
        if message.role == MessageRole.TOOL:
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id or "",
                        "content": message.content if isinstance(message.content, str) else str(message.content),
                    }
                ],
            }

        anthropic_message = {"role": message.role.value}

        if message.tool_calls:
            content_parts: List[Dict[str, Any]] = []
            if isinstance(message.content, str) and message.content:
                content_parts.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                function = call.get("function") or {}
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                content_parts.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id") or "",
                        "name": function.get("name") or "",
                        "input": arguments if isinstance(arguments, dict) else {},
                    }
                )
            anthropic_message["content"] = content_parts
            return anthropic_message

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

    def _convert_tools_to_anthropic(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        converted: List[Dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function") if tool.get("type") == "function" else tool
            if not isinstance(function, dict):
                continue
            converted.append(
                {
                    "name": function.get("name"),
                    "description": function.get("description") or "",
                    "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return converted or None

    def _extract_anthropic_response(self, response: Any) -> tuple[str, List[Dict[str, Any]], str, Dict[str, int]]:
        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        for part in getattr(response, "content", None) or []:
            part_type = getattr(part, "type", None)
            if part_type == "text":
                text_parts.append(getattr(part, "text", "") or "")
            elif part_type == "tool_use":
                tool_calls.append(
                    {
                        "id": getattr(part, "id", "") or "",
                        "type": "function",
                        "function": {
                            "name": getattr(part, "name", "") or "",
                            "arguments": json.dumps(getattr(part, "input", {}) or {}, ensure_ascii=False),
                        },
                    }
                )
        usage_obj = getattr(response, "usage", None)
        input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
        return (
            "".join(text_parts),
            tool_calls,
            str(getattr(response, "stop_reason", None) or "stop"),
            {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )
    
    async def chat_completion(self, messages: List[AIMessage], **kwargs) -> AIResponse:
        """Generate chat completion using Anthropic Claude (uses streaming internally to avoid timeout)"""
        if not self.client:
            raise RuntimeError("Anthropic client not available")

        config = self._merge_config(**kwargs)

        # 使用流式响应来避免 SDK 的 10 分钟超时限制
        # 收集所有流式块后返回完整响应
        tools = config.pop("tools", None)
        tool_choice = config.pop("tool_choice", None)

        if tools:
            system_message = None
            claude_messages = []
            for msg in messages:
                if msg.role == MessageRole.SYSTEM:
                    system_message = msg.content if isinstance(msg.content, str) else str(msg.content)
                else:
                    claude_messages.append(self._convert_message_to_anthropic(msg))

            request_kwargs: Dict[str, Any] = {
                "model": config.get("model", self.model),
                "messages": claude_messages,
                "max_tokens": int(config.get("anthropic_max_tokens") or config.get("max_completion_tokens") or 4096),
                "tools": self._convert_tools_to_anthropic(tools),
            }
            if not _claude_rejects_temperature(request_kwargs["model"]):
                request_kwargs["temperature"] = config.get("temperature", 0.7)
            if system_message:
                request_kwargs["system"] = system_message
            if tool_choice and isinstance(tool_choice, dict):
                function = tool_choice.get("function") or {}
                name = function.get("name") or tool_choice.get("name")
                if name:
                    request_kwargs["tool_choice"] = {"type": "tool", "name": name}

            self._apply_reasoning_config(request_kwargs, config)

            try:
                response = await self.client.messages.create(**request_kwargs)
                content, tool_calls, finish_reason, usage = self._extract_anthropic_response(response)
                return AIResponse(
                    content=content,
                    model=getattr(response, "model", None) or config.get("model", self.model),
                    usage=usage,
                    finish_reason=finish_reason,
                    tool_calls=tool_calls,
                    metadata={"provider": "anthropic", "transport": "messages"},
                )
            except Exception as e:
                logger.error(f"Anthropic API error: {e}")
                raise

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

            # Build request body. max_tokens is REQUIRED by the Anthropic Messages
            # API — omitting it makes every streaming request fail with 400.
            body = {
                "model": model,
                "messages": claude_messages,
                "max_tokens": int(
                    config.get("anthropic_max_tokens")
                    or config.get("max_completion_tokens")
                    or 8192
                ),
                "stream": True
            }
            if not _claude_rejects_temperature(model):
                body["temperature"] = temperature
            if system_message:
                body["system"] = system_message
            self._apply_reasoning_config(body, config)

            # Try both authentication methods
            auth_methods = [
                ("x-api-key", {"x-api-key": api_key}),  # Official Anthropic style
                ("Authorization", {"Authorization": f"Bearer {api_key}"})  # MiniMax/other compatible APIs
            ]

            last_error: Optional[str] = None
            yielded_text = False

            for index, (auth_name, auth_header) in enumerate(auth_methods):
                is_last_method = index == len(auth_methods) - 1
                try:
                    headers = {
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    }
                    headers.update(auth_header)

                    async with aiohttp.ClientSession(timeout=_build_aiohttp_timeout(config)) as session:
                        async with session.post(url, headers=headers, json=body) as response:
                            if response.status != 200:
                                error_text = await response.text()
                                last_error = f"API error {response.status}: {error_text}"
                                if not is_last_method:
                                    # NOTE: `continue`, not `break` — the enclosing
                                    # `async with` blocks are not loops, so `break`
                                    # left the auth loop and the remaining methods
                                    # (used by MiniMax and other compatible APIs)
                                    # were never attempted.
                                    logger.debug(
                                        f"{auth_name} auth failed ({response.status}), trying next auth method"
                                    )
                                    continue
                                raise Exception(last_error)

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
                                                    yielded_text = True
                                                    yield text
                                        elif event_data.get('type') == 'error':
                                            # overloaded_error / api_error mid-stream: the reply is cut short
                                            error = event_data.get('error') or {}
                                            raise Exception(
                                                f"Stream error {error.get('type', 'unknown')}: {error.get('message', '')}"
                                            )
                                    except json.JSONDecodeError:
                                        pass
                            return  # Success, exit the function

                except Exception as auth_error:
                    last_error = str(auth_error)
                    logger.debug(f"Auth method {auth_name} failed: {auth_error}")
                    if is_last_method or yielded_text:
                        # retrying after text went out would repeat it
                        raise
                    continue  # Try next auth method

            raise Exception(f"All authentication methods failed: {last_error}")

        except Exception as e:
            logger.error(f"Anthropic streaming API error: {e}")
            raise

# Placeholder ids for function calls Gemini returned without one; never sent back to the API.
_GEMINI_SYNTHETIC_CALL_ID = "gemini-tool-call-"


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
            self.model_instance = genai.GenerativeModel(config.get("model", "gemini-3.8-flash"))
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

    def _content_to_text(self, content: Any) -> str:
        """Text of a message body; images degrade to placeholders."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            msg_parts: List[str] = []
            for part in content:
                if isinstance(part, TextContent):
                    msg_parts.append(part.text)
                elif isinstance(part, ImageContent):
                    url = part.image_url.get("url", "")
                    msg_parts.append(f"[Image: {url}]" if url else "[Image]")
            return " ".join(p for p in msg_parts if p)
        return str(content)

    def _messages_to_plaintext_prompt(self, messages: List[AIMessage]) -> str:
        """Best-effort conversion for REST API (keeps text, degrades images to placeholders)."""
        return "\n\n".join(
            f"[{msg.role.value.upper()}]: " + self._content_to_text(msg.content) for msg in messages
        )

    async def _rest_generate_content(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        generation_config: Dict[str, Any],
        timeout_seconds: float,
        tools: Optional[List[Dict[str, Any]]] = None,
        contents: Optional[List[Dict[str, Any]]] = None,
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
            "contents": contents or [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
            "safetySettings": safety_settings,
        }
        gemini_tools = self._convert_tools_to_gemini(tools)
        if gemini_tools:
            # `parameters` is Gemini's restricted Schema type (no additionalProperties etc.);
            # full JSON schemas such as the editor tools' go in `parametersJsonSchema`.
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": declaration["name"],
                            "description": declaration["description"],
                            "parametersJsonSchema": declaration["parameters"],
                        }
                        for declaration in group["function_declarations"]
                    ]
                }
                for group in gemini_tools
            ]

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
            # Thinking tokens are billed as output but not counted in candidatesTokenCount
            "completion_tokens": int(usage_meta.get("candidatesTokenCount") or 0)
            + int(usage_meta.get("thoughtsTokenCount") or 0),
            "total_tokens": int(usage_meta.get("totalTokenCount") or 0),
        }
        return content, str(finish_reason), usage

    @staticmethod
    def _gemini_sdk_usage(response: Any) -> Dict[str, int]:
        """Token usage of an SDK response; thinking tokens count as output."""
        meta = getattr(response, "usage_metadata", None)
        return {
            "prompt_tokens": getattr(meta, "prompt_token_count", None) or 0,
            "completion_tokens": (getattr(meta, "candidates_token_count", None) or 0)
            + (getattr(meta, "thoughts_token_count", None) or 0),
            "total_tokens": getattr(meta, "total_token_count", None) or 0,
        }

    def _extract_rest_tool_calls(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract function calls from a REST response, in the shape the SDK path returns."""
        tool_calls: List[Dict[str, Any]] = []
        candidates = data.get("candidates") or []
        parts = ((candidates[0] or {}).get("content") or {}).get("parts") or [] if candidates else []
        for part in parts:
            function_call = part.get("functionCall") or part.get("function_call") if isinstance(part, dict) else None
            if not function_call:
                continue
            tool_call: Dict[str, Any] = {
                # Gemini 3 returns an id that the functionResponse must echo back.
                "id": function_call.get("id") or f"{_GEMINI_SYNTHETIC_CALL_ID}{len(tool_calls) + 1}",
                "type": "function",
                "function": {
                    "name": function_call.get("name") or "",
                    "arguments": json.dumps(function_call.get("args") or {}, ensure_ascii=False),
                },
            }
            signature = part.get("thoughtSignature") or part.get("thought_signature")
            if signature:
                tool_call["thought_signature"] = signature
            tool_calls.append(tool_call)
        return tool_calls

    def _messages_to_rest_contents(self, messages: List[AIMessage]) -> Optional[List[Dict[str, Any]]]:
        """Structured `contents` for a tool round trip; None when no message carries tool state.

        Replays assistant functionCall parts (with their original id and thoughtSignature)
        and tool results as functionResponse parts, instead of flattening them to text.
        """
        if not any(msg.tool_calls or msg.role == MessageRole.TOOL for msg in messages):
            return None

        call_names: Dict[str, str] = {}
        contents: List[Dict[str, Any]] = []

        def add(role: str, parts: List[Dict[str, Any]]) -> None:
            if not parts:
                return
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": role, "parts": parts})

        for msg in messages:
            if msg.role == MessageRole.TOOL:
                try:
                    response = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                except json.JSONDecodeError:
                    response = msg.content
                if not isinstance(response, dict):
                    response = {"result": response}
                function_response: Dict[str, Any] = {
                    "name": call_names.get(msg.tool_call_id or "") or msg.name or "",
                    "response": response,
                }
                if msg.tool_call_id and not msg.tool_call_id.startswith(_GEMINI_SYNTHETIC_CALL_ID):
                    function_response["id"] = msg.tool_call_id
                add("user", [{"functionResponse": function_response}])
            elif msg.role == MessageRole.ASSISTANT:
                parts: List[Dict[str, Any]] = []
                body = self._content_to_text(msg.content)
                if body:
                    parts.append({"text": body})
                for call in msg.tool_calls or []:
                    function = call.get("function") or {}
                    try:
                        args = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    call_id = call.get("id") or ""
                    call_names[call_id] = function.get("name") or ""
                    function_call: Dict[str, Any] = {"name": function.get("name") or "", "args": args}
                    if call_id and not call_id.startswith(_GEMINI_SYNTHETIC_CALL_ID):
                        function_call["id"] = call_id
                    part: Dict[str, Any] = {"functionCall": function_call}
                    if call.get("thought_signature"):
                        part["thoughtSignature"] = call["thought_signature"]
                    parts.append(part)
                add("model", parts)
            else:
                text = self._messages_to_plaintext_prompt([msg])
                add("user", [{"text": text}])
        return contents

    def _convert_tools_to_gemini(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        declarations: List[Dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function") if tool.get("type") == "function" else tool
            if not isinstance(function, dict):
                continue
            declarations.append(
                {
                    "name": function.get("name"),
                    "description": function.get("description") or "",
                    "parameters": function.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return [{"function_declarations": declarations}] if declarations else None

    def _extract_gemini_tool_calls_from_response(self, response: Any) -> List[Dict[str, Any]]:
        tool_calls: List[Dict[str, Any]] = []
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return tool_calls
        parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
        for index, part in enumerate(parts, start=1):
            function_call = getattr(part, "function_call", None)
            if not function_call:
                continue
            args = getattr(function_call, "args", {}) or {}
            tool_calls.append(
                {
                    "id": f"gemini-tool-call-{index}",
                    "type": "function",
                    "function": {
                        "name": getattr(function_call, "name", "") or "",
                        "arguments": json.dumps(dict(args), ensure_ascii=False),
                    },
                }
            )
        return tool_calls

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
        tools = config.pop("tools", None)
        base_url = config.get("base_url") or self.base_url

        # Use direct REST for mirrors/proxies to honor base_url.
        if self._should_use_rest_api(base_url) or not self.client or not self.model_instance:
            api_key = config.get("api_key") or self.config.get("api_key")
            if not api_key:
                raise RuntimeError("Google Gemini API key not configured")

            model = config.get("model", self.model) or self.model
            generation_config: Dict[str, Any] = {}
            if google_model_accepts_sampling_params(model):
                generation_config["temperature"] = config.get("temperature", 0.7)
                generation_config["topP"] = config.get("top_p", 1.0)

            prompt_text = self._messages_to_plaintext_prompt(messages)
            data = await self._rest_generate_content(
                base_url=base_url,
                api_key=api_key,
                model=model,
                prompt=prompt_text,
                generation_config=generation_config,
                timeout_seconds=_get_llm_timeout_seconds(config),
                tools=tools,
                contents=self._messages_to_rest_contents(messages),
            )
            content, finish_reason, usage = self._extract_rest_text(data)
            return AIResponse(
                content=content,
                model=model,
                usage=usage,
                finish_reason=finish_reason,
                tool_calls=self._extract_rest_tool_calls(data),
                metadata={"provider": "google", "transport": "rest"},
            )

        # Convert messages to Gemini format with multimodal support
        prompt = self._convert_messages_to_gemini(messages)

        try:
            # Configure generation parameters
            generation_config = {}
            if google_model_accepts_sampling_params(self.model_instance.model_name):
                generation_config["temperature"] = config.get("temperature", 0.7)
                generation_config["top_p"] = config.get("top_p", 1.0)
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
                tools=self._convert_tools_to_gemini(tools),
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
                usage=self._gemini_sdk_usage(response),
                finish_reason=finish_reason,
                tool_calls=self._extract_gemini_tool_calls_from_response(response),
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
        tools=None,
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
            if tools:
                kwargs["tools"] = tools

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
        tools = config.pop("tools", None)
        
        # Convert messages to Ollama format with multimodal support
        ollama_messages = []
        for msg in messages:
            if isinstance(msg.content, str):
                # Simple text message
                message = {"role": msg.role.value, "content": msg.content}
                if msg.tool_call_id:
                    message["tool_call_id"] = msg.tool_call_id
                if msg.tool_calls:
                    message["tool_calls"] = msg.tool_calls
                ollama_messages.append(message)
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

            response = await asyncio.wait_for(
                self.client.chat(
                    model=config.get("model", self.model),
                    messages=ollama_messages,
                    tools=tools,
                    options=options,
                ),
                timeout=_get_llm_timeout_seconds(config),
            )
            
            response_message = response.get("message", {}) or {}
            content = response_message.get("content", "") or ""
            tool_calls = response_message.get("tool_calls") or []
            
            prompt_tokens = response.get("prompt_eval_count")
            completion_tokens = response.get("eval_count")
            if prompt_tokens is not None and completion_tokens is not None:
                usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                }
            else:
                usage = self._calculate_usage(
                    " ".join([msg.content for msg in messages if isinstance(msg.content, str)]),
                    content
                )

            return AIResponse(
                content=content,
                model=config.get("model", self.model),
                usage=usage,
                finish_reason=response.get("done_reason") or "stop",
                tool_calls=tool_calls,
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

    _provider_cache: "OrderedDict[str, AIProvider]" = OrderedDict()
    _provider_cache_lock = threading.RLock()
    _max_cached_providers = 128

    @staticmethod
    def _config_fingerprint(config: Dict[str, Any]) -> str:
        def _default(value: Any) -> str:
            return repr(value)

        payload = json.dumps(config, sort_keys=True, ensure_ascii=False, default=_default)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def create_provider(
        cls,
        provider_name: str,
        config: Optional[Dict[str, Any]] = None,
        *,
        use_cache: bool = True,
    ) -> AIProvider:
        """Create an AI provider instance"""
        if config is None:
            config = ai_config.get_provider_config(provider_name)

        # Built-in providers
        managed = provider_name.startswith("custom:")
        if provider_name not in cls._providers and not managed:
            raise ValueError(f"Unknown provider: {provider_name}")
        if managed and not (config.get("api_key") and config.get("base_url")):
            from ..services.managed_provider_service import ManagedProviderError
            raise ManagedProviderError("AI 提供商配置不完整，请重新配置")
        if managed:
            config = {**config, "managed_provider": True}

        if use_cache:
            cache_key = f"{provider_name}:{cls._config_fingerprint(config)}"
            with cls._provider_cache_lock:
                cached = cls._provider_cache.get(cache_key)
                if cached is not None:
                    cls._provider_cache.move_to_end(cache_key)
                    return cached

        provider_class = OpenAIProvider if managed else cls._providers[provider_name]
        provider = provider_class(dict(config))

        if use_cache:
            with cls._provider_cache_lock:
                cached = cls._provider_cache.get(cache_key)
                if cached is not None:
                    cls._provider_cache.move_to_end(cache_key)
                    return cached
                cls._provider_cache[cache_key] = provider
                cls._provider_cache.move_to_end(cache_key)
                while len(cls._provider_cache) > cls._max_cached_providers:
                    cls._provider_cache.popitem(last=False)

        return provider
    
    @classmethod
    def get_available_providers(cls) -> List[str]:
        """Get list of available providers"""
        return list(cls._providers.keys())

    @classmethod
    def clear_cache(cls):
        """Clear cached provider instances."""
        with cls._provider_cache_lock:
            cls._provider_cache.clear()

class AIProviderManager:
    """Manager for AI provider instances with caching and reloading"""

    def __init__(self):
        self._provider_cache = {}
        self._config_cache = {}

    def get_provider(self, provider_name: Optional[str] = None) -> AIProvider:
        """Get AI provider instance with caching"""
        if provider_name is None:
            provider_name = ai_config.default_ai_provider
        if provider_name.startswith("custom:"):
            from ..services.managed_provider_service import ManagedProviderError
            raise ManagedProviderError("AI 提供商需要通过当前用户配置解析")
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
        AIProviderFactory.clear_cache()

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
