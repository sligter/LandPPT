from __future__ import annotations

from typing import Any, Dict, Tuple


DEFAULT_GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_GOOGLE_MODEL = "gemini-2.5-flash"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"


def normalize_provider_name(provider: Any) -> str:
    """统一提供商名称，避免 gemini/google 别名在配置键和路由分支上跑偏。"""
    normalized = str(provider or "").strip().lower()
    return "google" if normalized == "gemini" else normalized


def normalize_google_test_base_url(base_url: str) -> str:
    """Google 连接测试必须使用 API 根路径，不能把 /v1 或 /v1beta 再拼一层。"""
    normalized = str(base_url or "").strip()
    if not normalized:
        return DEFAULT_GOOGLE_BASE_URL

    if "://" not in normalized:
        normalized = f"https://{normalized}"

    normalized = normalized.rstrip("/")
    lowered = normalized.lower()
    for suffix in ("/v1beta", "/v1"):
        if lowered.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized.rstrip("/")


def build_google_generate_content_url(base_url: str, model: str) -> str:
    """统一生成 Gemini generateContent 地址，兼容官方域名和带前缀的代理地址。"""
    normalized_base_url = normalize_google_test_base_url(base_url)
    normalized_model = str(model or DEFAULT_GOOGLE_MODEL).strip() or DEFAULT_GOOGLE_MODEL
    return f"{normalized_base_url}/v1beta/models/{normalized_model}:generateContent"


def build_google_test_payload(prompt: str, max_output_tokens: int = 500) -> Dict[str, Any]:
    """Google 测试请求走原生 Gemini 格式，避免误用 OpenAI 兼容协议。"""
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "temperature": 0,
        },
    }


def extract_google_test_result(data: Dict[str, Any]) -> Tuple[str, Dict[str, int]]:
    """抽取 Gemini 文本与用量，兼容官方字段和少量代理的变体字段。"""
    response_text = ""

    candidates = data.get("candidates") or []
    if candidates:
        candidate = candidates[0] or {}
        candidate_content = candidate.get("content") or {}
        parts = candidate_content.get("parts") or []
        texts = [part.get("text", "") for part in parts if isinstance(part, dict) and part.get("text")]
        if texts:
            response_text = "".join(texts)
        else:
            response_text = candidate.get("text") or ""

    usage_metadata = data.get("usageMetadata") or data.get("usage_metadata") or {}
    usage = {
        "prompt_tokens": int(usage_metadata.get("promptTokenCount") or 0),
        "completion_tokens": int(usage_metadata.get("candidatesTokenCount") or 0),
        "total_tokens": int(usage_metadata.get("totalTokenCount") or 0),
    }
    return response_text, usage


def normalize_anthropic_test_base_url(base_url: str) -> str:
    """Anthropic 测试固定走 /v1/messages，避免不同入口各自拼接造成偏差。"""
    normalized = str(base_url or "").strip()
    if not normalized:
        normalized = DEFAULT_ANTHROPIC_BASE_URL

    if "://" not in normalized:
        normalized = f"https://{normalized}"

    normalized = normalized.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def build_anthropic_messages_url(base_url: str) -> str:
    """统一生成 Anthropic messages 地址。"""
    return f"{normalize_anthropic_test_base_url(base_url)}/messages"


def build_anthropic_test_payload(prompt: str, max_tokens: int = 1024) -> Dict[str, Any]:
    """Anthropic 测试使用官方 messages 协议。"""
    return {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }


def extract_anthropic_test_result(data: Dict[str, Any]) -> Tuple[str, Dict[str, int]]:
    """把 Anthropic 响应统一转换成前端可复用的文本和 token 统计结构。"""
    content = data.get("content") or []
    response_text = ""
    if content and isinstance(content[0], dict):
        response_text = str(content[0].get("text") or "")

    usage_data = data.get("usage") or {}
    prompt_tokens = int(usage_data.get("input_tokens") or 0)
    completion_tokens = int(usage_data.get("output_tokens") or 0)
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    return response_text, usage


def extract_openai_compatible_test_result(
    data: Dict[str, Any],
    *,
    use_responses_api: bool,
) -> Tuple[str, Dict[str, int]]:
    """把 OpenAI 兼容响应统一成前端需要的预览文本与用量结构。"""
    if use_responses_api:
        usage_data = data.get("usage") or {}
        usage = {
            "prompt_tokens": int(usage_data.get("input_tokens") or 0),
            "completion_tokens": int(usage_data.get("output_tokens") or 0),
            "total_tokens": int(usage_data.get("total_tokens") or 0),
        }
        return str(data.get("output_text") or ""), usage

    response_text = ""
    choices = data.get("choices") or []
    if choices and isinstance(choices[0], dict):
        response_text = str(((choices[0].get("message") or {}).get("content")) or "")

    usage_data = data.get("usage") or {}
    usage = {
        "prompt_tokens": int(usage_data.get("prompt_tokens") or 0),
        "completion_tokens": int(usage_data.get("completion_tokens") or 0),
        "total_tokens": int(usage_data.get("total_tokens") or 0),
    }
    return response_text, usage
