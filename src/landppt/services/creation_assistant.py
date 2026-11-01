"""Conversational requirement intake for the project creation composer.

The model only proposes values; everything it returns is checked against the
same option sets the creation form offers before it reaches the browser.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from ..ai import AIMessage, MessageRole

AUDIENCE_OPTIONS = [
    "企业管理层", "技术团队", "销售团队", "学生群体", "学术研究者", "投资人",
    "客户群体", "培训学员", "项目团队", "行业专家", "普通大众", "自定义",
]
PAGE_MODES = {"ai_decide", "custom_range"}
STYLES = {"general", "keynote", "custom"}
LANGUAGES = {"zh", "en"}
BOOLEAN_FIELDS = ("network_mode", "include_transition_pages", "include_page_numbers")
TEXT_LIMITS = {"topic": 200, "requirements": 4000, "custom_audience": 200, "custom_style_prompt": 1000}
MAX_URLS = 50

_URL = re.compile(r"https?://[^\s<>\"'，。；、）)\]】]+", re.IGNORECASE)


def extract_urls(texts: Iterable[str]) -> List[str]:
    found: List[str] = []
    for text in texts:
        for url in _URL.findall(text or ""):
            url = url.rstrip(".,;:!?")
            if url not in found:
                found.append(url)
    return found[:MAX_URLS]


def build_messages(
    history: List[Dict[str, str]],
    fields: Dict[str, Any],
    attachments: List[str],
    links: List[str],
    scenarios: List[Dict[str, Any]],
) -> List[AIMessage]:
    scenario_text = "、".join(f"{item['id']}（{item['name']}）" for item in scenarios)
    system = f"""你是 LandPPT 的演示需求顾问，通过简短的多轮对话帮用户把想法整理成可直接生成 PPT 的需求。

工作方式：
- 每轮先理解用户意图，把已能确定的信息写入 fields；不确定的项保持缺省，不要编造。
- 每轮最多追问 1~2 个最关键的问题（如受众、用途/场景、重点内容、页数、风格），并给出可直接采纳的建议，用户也可以说“你决定”。
- topic 是简洁有力的演示标题；requirements 汇总用户提到的重点内容、章节思路、数据素材与风格偏好，用要点写清楚，每轮在已有内容基础上更新而不是覆盖丢失。
- 用户提到需要最新数据、行业现状、实时资讯时，把 network_mode 设为 true。
- 用户给出的网页链接会作为参考资料；content_urls 只能从用户消息中出现过的链接里选择，用户要求移除的链接不要再列出。
- 主题明确且用户没有待回答的关键问题，或用户表示“可以/开始/就这样”时，ready 设为 true，并在 reply 中简要复述最终方案，提示用户点击“开始生成”。
- reply 使用用户使用的语言，简洁友好，不超过 150 字，不要使用 Markdown 标题。

fields 可用键与取值：
- topic: 字符串
- requirements: 字符串
- scenario: {scenario_text}
- audience_type: {"、".join(AUDIENCE_OPTIONS)}；不在列表中时用“自定义”并填写 custom_audience
- custom_audience: 字符串
- page_count_mode: ai_decide | custom_range；custom_range 时给出 min_pages、max_pages（5~50 的整数）
- ppt_style: general（通用）| keynote（发布会）| custom（自定义，需填写 custom_style_prompt）
- custom_style_prompt: 字符串
- language: zh | en（演示内容语言）
- network_mode / include_transition_pages / include_page_numbers: 布尔值

只输出一个 JSON 对象，不要输出解释或 Markdown 代码块：
{{"reply": "...", "ready": false, "fields": {{...}}, "content_urls": []}}"""
    context = {
        "current_fields": {key: value for key, value in fields.items() if value not in (None, "")},
        "attached_files": attachments,
        "current_links": links,
    }
    messages = [
        AIMessage(role=MessageRole.SYSTEM, content=system),
        AIMessage(role=MessageRole.SYSTEM, content="当前表单状态（用户可能已手动修改，以此为准）：\n" + json.dumps(context, ensure_ascii=False)),
    ]
    for item in history:
        role = MessageRole.ASSISTANT if item.get("role") == "assistant" else MessageRole.USER
        messages.append(AIMessage(role=role, content=item.get("content", "")))
    return messages


def _json_object(text: str) -> Optional[Dict[str, Any]]:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _boolean(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None


def _pages(value: Any) -> Optional[int]:
    try:
        return min(50, max(5, int(value)))
    except (TypeError, ValueError):
        return None


def sanitize_fields(raw: Any, scenario_ids: Iterable[str]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    fields: Dict[str, Any] = {}
    for key, limit in TEXT_LIMITS.items():
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            fields[key] = value.strip()[:limit]
    choices = {
        "scenario": set(scenario_ids),
        "page_count_mode": PAGE_MODES,
        "ppt_style": STYLES,
        "language": LANGUAGES,
    }
    for key, allowed in choices.items():
        value = raw.get(key)
        if isinstance(value, str) and value.strip() in allowed:
            fields[key] = value.strip()
    audience = raw.get("audience_type")
    if isinstance(audience, str) and audience.strip():
        audience = audience.strip()
        if audience in AUDIENCE_OPTIONS:
            fields["audience_type"] = audience
        else:
            fields["audience_type"] = "自定义"
            fields.setdefault("custom_audience", audience[:TEXT_LIMITS["custom_audience"]])
    if fields.get("audience_type") == "自定义" and not fields.get("custom_audience"):
        fields.pop("audience_type")
    if fields.get("ppt_style") == "custom" and not fields.get("custom_style_prompt"):
        fields.pop("ppt_style")
    low, high = _pages(raw.get("min_pages")), _pages(raw.get("max_pages"))
    if low is not None and high is not None:
        fields["min_pages"], fields["max_pages"] = min(low, high), max(low, high)
    elif fields.get("page_count_mode") == "custom_range":
        fields.pop("page_count_mode")
    for key in BOOLEAN_FIELDS:
        value = _boolean(raw.get(key))
        if value is not None:
            fields[key] = value
    return fields


def parse_reply(text: str, user_urls: List[str], scenario_ids: Iterable[str], current_topic: str = "") -> Dict[str, Any]:
    data = _json_object(text)
    if data is None:
        # Plain-text answers still keep the conversation going; only the form stays untouched.
        reply = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
        return {"reply": reply[:2000] or "抱歉，我没有理解，请换个说法再试一次。", "ready": False, "fields": {}, "content_urls": user_urls, "mentioned_urls": user_urls}
    proposed = data.get("content_urls")
    urls = user_urls if not isinstance(proposed, list) else [url for url in user_urls if url in proposed]
    fields = sanitize_fields(data.get("fields"), scenario_ids)
    reply = data.get("reply") if isinstance(data.get("reply"), str) else ""
    return {
        "reply": reply.strip()[:2000] or "已根据你的描述更新需求。",
        "ready": _boolean(data.get("ready")) is True and bool(fields.get("topic") or current_topic.strip()),
        "fields": fields,
        "content_urls": urls,
        "mentioned_urls": user_urls,
    }
