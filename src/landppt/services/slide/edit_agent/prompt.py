"""Agent 的提示词与首轮上下文构造。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .draft import SlideDraft
from .protocol import ToolProtocol
from .schema import SlideEditAgentContext, SlideEditAgentRequest
from .tools import SlideEditToolbox

MAX_CONVERSATION_HISTORY_MESSAGES = 10
MAX_CONVERSATION_HISTORY_TOTAL_CHARS = 6000
MAX_CONVERSATION_HISTORY_MESSAGE_CHARS = 1200

#: 首轮直接内联整页 HTML 的上限。超了就只给结构树，让模型按需 read_slide。
INLINE_HTML_BUDGET = 8000

_BASE_SYSTEM_PROMPT = """你是 LandPPT 的幻灯片编辑 agent，通过工具直接修改单页 HTML 草稿。

工作方式：
- 先用 read_slide 或 find_elements 看清结构，再动手；结构树里的 ref 可以直接用于编辑工具。
- 优先做最小改动：改文字用 set_text，改样式用 set_style，改属性用 set_attributes，
  局部结构用 replace_element / insert_html / remove_element。
- 只有在整页排版必须重做时才用 replace_slide，它会让所有 ref 失效且改动面很大。
- 保持页面原有的设计语言：配色、字体、间距节奏、栅格与 16:9 画布尺寸。
- SVG 页面用 set_attributes 调整 x/y、transform、fill、font-size、data-box-w 等属性；不要用 CSS left/top 移动 SVG。保留 viewBox、linearGradient、clipPath 等大小写以及 defs/use 引用。多行文字可修改各 tspan，或 replace_children=true 重写 text 后自行补齐换行；不要引入 HTML、脚本或 foreignObject。
- 工具返回 ok=false 时读懂原因再重试，不要重复同一个失败调用；改错了可以 undo_last_edit。
- 不要写 <script>、内联事件处理器或 javascript: 链接，它们会被安全校验拦下。
- 页面原有的脚本和内联事件处理器是只读资源，调整文字或布局时保留原样；不要修改其内容、属性、顺序，也不要复制或新增。
- 改完后调用 validate_draft 自查；未通过时继续修复，无法修复则明确说明尚不能保存，不要宣称已完成。

结束条件：草稿达到用户要求后，用用户所用的语言给出一句话总结（说明改了什么），
不要再调用任何工具。总结会直接显示给用户，不要在里面粘贴 HTML。"""

_TEXT_PROTOCOL_PROMPT = """
当前 provider 不支持原生工具调用，改用 JSON 文本协议：每轮只输出一个 JSON 对象，
不要输出其它内容、不要加解释文字。

调用工具：
{"thought": "为什么这么做", "action": "工具名", "action_input": {...}}

结束：
{"thought": "...", "action": "final", "action_input": {"summary": "一句话总结"}}

可用工具：
"""


def build_system_prompt(protocol: ToolProtocol) -> str:
    if protocol is ToolProtocol.NATIVE:
        return _BASE_SYSTEM_PROMPT
    reference = json.dumps(SlideEditToolbox.text_reference(), ensure_ascii=False, indent=2)
    return _BASE_SYSTEM_PROMPT + "\n" + _TEXT_PROTOCOL_PROMPT + reference


def build_initial_context(
    context: SlideEditAgentContext,
    draft: SlideDraft,
    *,
    max_iterations: int,
) -> Dict[str, Any]:
    request = context.request
    html = draft.html
    inline_html = len(html) <= INLINE_HTML_BUDGET

    payload: Dict[str, Any] = {
        "project": context.project_info,
        "slide_index": context.slide_index,
        "slide_title": context.slide_data.get("title"),
        "slide_outline": context.slide_outline,
        "edit_mode": context.mode,
        "max_iterations": max_iterations,
        "conversation_history": conversation_history_context(request),
        "vision": vision_context(request),
    }

    if context.mode == "element":
        payload["selected_element"] = {
            "id": context.selected_element_id,
            "html": _clip(context.selected_element_html or "", 4000),
            "note": "用户已选中这个元素，未指定 ref/selector 的编辑工具默认作用于它。",
        }

    if inline_html:
        payload["slide_html"] = html
    else:
        payload["slide_structure"] = draft.outline()
        payload["slide_html_note"] = (
            f"整页 HTML 约 {len(html)} 字符，未内联。需要原文时调用 "
            "read_slide({include_html: true}) 或 read_element。"
        )

    return payload


def build_initial_user_message(
    context: SlideEditAgentContext,
    draft: SlideDraft,
    *,
    max_iterations: int,
) -> str:
    payload = build_initial_context(context, draft, max_iterations=max_iterations)
    return (
        f"用户的最新编辑要求：{context.request.userRequest}\n\n"
        "以下是当前页面的上下文（JSON）：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def conversation_history_context(request: SlideEditAgentRequest) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    total_chars = 0

    for item in reversed(request.chatHistory or []):
        if len(cleaned) >= MAX_CONVERSATION_HISTORY_MESSAGES:
            break
        if not isinstance(item, dict):
            continue

        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue

        content = str(item.get("content") or "").strip()
        if not content:
            continue

        remaining_chars = MAX_CONVERSATION_HISTORY_TOTAL_CHARS - total_chars
        if remaining_chars <= 0:
            break

        content = _clip(content, min(remaining_chars, MAX_CONVERSATION_HISTORY_MESSAGE_CHARS))
        if not content:
            continue

        cleaned.append({"role": role, "content": content})
        total_chars += len(content)

    cleaned.reverse()
    return cleaned


def vision_image_urls(request: SlideEditAgentRequest) -> List[str]:
    urls = [str(url) for url in (request.slideScreenshot, request.elementScreenshot) if url]
    for image in request.images or []:
        if not isinstance(image, dict):
            continue
        url = image.get("url")
        if url:
            urls.append(str(url))
    return urls


def vision_context(request: SlideEditAgentRequest) -> Dict[str, Any]:
    attachments: List[Dict[str, Any]] = []
    if request.slideScreenshot:
        attachments.append(
            {
                "source": "slide_screenshot",
                "attached": request.visionEnabled,
                "url": _prompt_safe_image_url(request.slideScreenshot),
            }
        )
    if request.elementScreenshot:
        attachments.append(
            {
                "source": "element_screenshot",
                "attached": request.visionEnabled,
                "url": _prompt_safe_image_url(request.elementScreenshot),
            }
        )
    for index, image in enumerate(request.images or [], start=1):
        if not isinstance(image, dict):
            continue
        url = str(image.get("url") or "")
        attachments.append(
            {
                "source": f"reference_image_{index}",
                "name": image.get("name"),
                "size": image.get("size"),
                "attached": bool(request.visionEnabled and url),
                "url": _prompt_safe_image_url(url),
            }
        )

    urls = vision_image_urls(request)
    return {
        "enabled": request.visionEnabled,
        "uses_vision_model": bool(request.visionEnabled and urls),
        "attached_image_count": len(urls) if request.visionEnabled else 0,
        "attachments": attachments,
        "instruction": (
            "存在视觉附件时，先观察布局、文字、配色与间距，再决定改哪里。"
        ),
    }


def build_messages(
    context: SlideEditAgentContext,
    draft: SlideDraft,
    *,
    protocol: ToolProtocol,
    max_iterations: int,
) -> List[Any]:
    from .protocol import _message

    request = context.request
    prompt = build_initial_user_message(context, draft, max_iterations=max_iterations)
    messages = [_message("system", build_system_prompt(protocol))]

    urls = vision_image_urls(request)
    if request.visionEnabled and urls:
        from ....ai.base import ImageContent, TextContent

        content: List[Any] = [TextContent(text=prompt)]
        content.extend(ImageContent(image_url={"url": url}) for url in urls)
        messages.append(_message("user", content))
    else:
        messages.append(_message("user", prompt))
    return messages


def _prompt_safe_image_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("data:image"):
        return "[attached data URL omitted from text prompt]"
    return url


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def truncate_history_content(content: str, max_chars: int) -> str:
    return _clip(content, max_chars)
