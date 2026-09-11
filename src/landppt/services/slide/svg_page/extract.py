"""从模型回复中取出 ``<svg>`` 文档。"""

from __future__ import annotations

import re
from typing import List, Optional

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(
    r"```[ \t]*(?:svg|xml|html|markup)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE
)
_SVG_RE = re.compile(r"<svg\b.*?</svg\s*>", re.DOTALL | re.IGNORECASE)
_SVG_OPEN_RE = re.compile(r"<svg\b", re.IGNORECASE)


def _strip_reasoning(raw: str) -> str:
    return _THINK_RE.sub("", raw or "")


def extract_svg_markup(raw: str) -> Optional[str]:
    """返回回复中最完整的一段 ``<svg …>…</svg>``，没有则返回 None。

    先看代码围栏，再看全文；多段候选取最长的一段。修复提示词会把原 SVG 回显
    在提示里，但那只出现在请求中，不在回复里，所以取最长是安全的。
    """
    text = _strip_reasoning(raw)
    if not text.strip():
        return None

    candidates: List[str] = []
    for match in _FENCE_RE.finditer(text):
        candidates.extend(_SVG_RE.findall(match.group(1)))
    candidates.extend(_SVG_RE.findall(text))

    best = max((candidate.strip() for candidate in candidates), key=len, default=None)
    return best or None


def looks_truncated(raw: str) -> bool:
    """有 ``<svg`` 起始却没有闭合：多半是输出被截断。"""
    text = _strip_reasoning(raw)
    return bool(_SVG_OPEN_RE.search(text)) and not _SVG_RE.search(text)
