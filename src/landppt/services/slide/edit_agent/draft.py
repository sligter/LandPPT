"""可增量编辑的幻灯片草稿。

旧实现每次工具调用都把整页 HTML 用 BeautifulSoup 重新 parse 一遍再 dump 回字符串，
并且靠往草稿里注入 `data-agent-id`、最后再剥掉来定位元素——既慢，又让 diff 里出现
大量与用户意图无关的属性噪声。

这里改成：整个 run 期间持有同一棵树，元素引用（ref）只存在于服务端的引用表里，
永远不写进 HTML。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from bs4.element import Tag

from .html_safety import (
    AGENT_ID_ATTRS,
    compute_slide_html_hash,
    strip_agent_ids,
    validate_slide_html,
)

_MAX_UNDO_SNAPSHOTS = 20
_OUTLINE_MAX_NODES = 120
_OUTLINE_MAX_DEPTH = 6
_OUTLINE_TEXT_PREVIEW = 60


class DraftRefError(LookupError):
    """元素引用无法解析（不存在，或已被此前的编辑摘除）。"""


@dataclass
class ElementSummary:
    ref: str
    tag: str
    element_id: str
    classes: List[str]
    text: str
    child_element_count: int

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ref": self.ref, "tag": self.tag}
        if self.element_id:
            payload["id"] = self.element_id
        if self.classes:
            payload["classes"] = self.classes
        if self.text:
            payload["text"] = self.text
        if self.child_element_count:
            payload["child_elements"] = self.child_element_count
        return payload


class SlideDraft:
    """幻灯片草稿：一棵持久的 DOM 树 + 引用表 + 撤销栈。"""

    def __init__(self, base_html: str):
        self._base_html = (base_html or "").strip()
        self._soup = BeautifulSoup(self._base_html, "html.parser")
        self._refs: Dict[str, Tag] = {}
        self._ref_by_node_id: Dict[int, str] = {}
        self._next_ref_index = 1
        self._revision = 0
        self._snapshots: List[str] = []
        self._cached_html: Optional[str] = self._base_html

    # ------------------------------------------------------------------
    # 基本状态
    # ------------------------------------------------------------------
    @property
    def base_html(self) -> str:
        return self._base_html

    @property
    def soup(self) -> BeautifulSoup:
        """当前草稿树，供只读检查使用；不要在外部直接改它。"""
        return self._soup

    @property
    def base_hash(self) -> str:
        return compute_slide_html_hash(self._base_html)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def html(self) -> str:
        if self._cached_html is None:
            self._cached_html = str(self._soup).strip()
        return self._cached_html

    @property
    def changed(self) -> bool:
        return self.html != self._base_html

    def clean_html(self) -> str:
        """给用户/落库用的 HTML：去掉历史遗留的 agent 定位属性。"""
        html = self.html
        if not any(attr in html for attr in AGENT_ID_ATTRS):
            return html
        return strip_agent_ids(html)

    # ------------------------------------------------------------------
    # 引用表
    # ------------------------------------------------------------------
    def ref_for(self, node: Tag) -> str:
        existing = self._ref_by_node_id.get(id(node))
        if existing and self._refs.get(existing) is node:
            return existing
        ref = f"e{self._next_ref_index}"
        self._next_ref_index += 1
        self._refs[ref] = node
        self._ref_by_node_id[id(node)] = ref
        return ref

    def resolve(self, *, ref: str = "", selector: str = "") -> Tag:
        """按 ref 优先、selector 兜底的顺序解析出唯一元素。"""
        ref = (ref or "").strip()
        selector = (selector or "").strip()

        if ref:
            node = self._refs.get(ref)
            if node is None:
                raise DraftRefError(f'unknown element ref "{ref}"; call find_elements again')
            if not self._is_attached(node):
                raise DraftRefError(
                    f'element ref "{ref}" was removed by an earlier edit; call find_elements again'
                )
            return node

        if selector:
            try:
                node = self._soup.select_one(selector)
            except Exception as exc:  # bs4 抛的选择器语法错误类型不稳定
                raise DraftRefError(f"invalid selector {selector}: {exc}") from exc
            if node is None:
                raise DraftRefError(f"selector matched nothing: {selector}")
            return node

        raise DraftRefError("either ref or selector is required")

    def _is_attached(self, node: Tag) -> bool:
        current: Any = node
        while current is not None:
            if current is self._soup:
                return True
            current = getattr(current, "parent", None)
        return False

    def _invalidate_refs(self) -> None:
        self._refs.clear()
        self._ref_by_node_id.clear()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def find(self, *, selector: str = "", text: str = "", limit: int = 20) -> List[ElementSummary]:
        selector = (selector or "").strip()
        needle = (text or "").strip().lower()

        try:
            candidates = self._soup.select(selector) if selector else self._soup.find_all(True)
        except Exception as exc:
            raise DraftRefError(f"invalid selector {selector}: {exc}") from exc

        results: List[ElementSummary] = []
        for node in candidates:
            if len(results) >= max(1, limit):
                break
            node_text = node.get_text(" ", strip=True)
            if needle and needle not in node_text.lower():
                continue
            results.append(self._summarize(node, node_text))
        return results

    def _summarize(self, node: Tag, node_text: Optional[str] = None) -> ElementSummary:
        text = node_text if node_text is not None else node.get_text(" ", strip=True)
        classes = node.get("class") or []
        if isinstance(classes, str):
            classes = classes.split()
        return ElementSummary(
            ref=self.ref_for(node),
            tag=node.name,
            element_id=str(node.get("id") or ""),
            classes=[str(item) for item in classes][:8],
            text=text[:200],
            child_element_count=sum(1 for child in node.children if isinstance(child, Tag)),
        )

    def outline(self) -> List[Dict[str, Any]]:
        """结构树概览：给每个节点分配 ref，让模型看一眼就能直接下手编辑。"""
        lines: List[Dict[str, Any]] = []
        budget = _OUTLINE_MAX_NODES

        def walk(node: Tag, depth: int) -> None:
            nonlocal budget
            for child in node.children:
                if budget <= 0:
                    return
                if not isinstance(child, Tag):
                    continue
                budget -= 1
                own_text = "".join(
                    str(part) for part in child.children if not isinstance(part, Tag)
                ).strip()
                own_text = re.sub(r"\s+", " ", own_text)
                entry: Dict[str, Any] = {
                    "ref": self.ref_for(child),
                    "depth": depth,
                    "tag": child.name,
                }
                if child.get("id"):
                    entry["id"] = str(child.get("id"))
                classes = child.get("class") or []
                if isinstance(classes, str):
                    classes = classes.split()
                if classes:
                    entry["classes"] = [str(item) for item in classes][:6]
                if own_text:
                    entry["text"] = own_text[:_OUTLINE_TEXT_PREVIEW]
                if child.name == "img":
                    entry["src"] = str(child.get("src") or "")[:120]
                lines.append(entry)
                if depth < _OUTLINE_MAX_DEPTH:
                    walk(child, depth + 1)

        walk(self._soup, 0)
        return lines

    def element_html(self, node: Tag, max_chars: int = 4000) -> str:
        html = str(node)
        if len(html) <= max_chars:
            return html
        return html[: max_chars - 3] + "..."

    def diff(self, max_lines: int = 160) -> Dict[str, Any]:
        base_lines = _diff_lines(self._base_html)
        draft_lines = _diff_lines(self.html)
        diff = list(
            difflib.unified_diff(
                base_lines,
                draft_lines,
                fromfile="base",
                tofile="draft",
                lineterm="",
                n=2,
            )
        )
        truncated = len(diff) > max_lines
        return {
            "changed": self.changed,
            "revision": self._revision,
            "base_hash": self.base_hash,
            "draft_hash": compute_slide_html_hash(self.html),
            "diff": "\n".join(diff[:max_lines]),
            "truncated": truncated,
        }

    # ------------------------------------------------------------------
    # 变更
    # ------------------------------------------------------------------
    def begin_mutation(self) -> None:
        self._snapshots.append(self.html)
        if len(self._snapshots) > _MAX_UNDO_SNAPSHOTS:
            self._snapshots.pop(0)

    def commit_mutation(self) -> int:
        self._cached_html = None
        self._revision += 1
        return self._revision

    def rollback_mutation(self) -> None:
        """放弃最近一次尚未 commit 的改动。"""
        if not self._snapshots:
            return
        self._restore(self._snapshots.pop())

    def undo(self) -> bool:
        if not self._snapshots:
            return False
        self._restore(self._snapshots.pop())
        self._revision += 1
        return True

    def _restore(self, html: str) -> None:
        self._soup = BeautifulSoup(html, "html.parser")
        self._cached_html = html.strip()
        self._invalidate_refs()

    def replace_all(self, html: str) -> None:
        self.begin_mutation()
        self._soup = BeautifulSoup(html, "html.parser")
        self._invalidate_refs()
        self.commit_mutation()

    def parse_fragment(self, html: str) -> List[Tag]:
        """把待插入的 HTML 片段清洗后解析成节点列表。"""
        validation = validate_slide_html(html)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors) or "fragment html failed validation")
        fragment = BeautifulSoup(validation.sanitized_html, "html.parser")
        nodes = [child for child in fragment.children if isinstance(child, Tag)]
        if not nodes:
            raise ValueError("fragment html contains no element")
        return nodes


def _diff_lines(html: str) -> List[str]:
    """把 HTML 按标签边界折行，让 diff 落在有意义的粒度上。"""
    spaced = re.sub(r">\s*<", ">\n<", (html or "").strip())
    return [line for line in (item.rstrip() for item in spaced.split("\n")) if line]
