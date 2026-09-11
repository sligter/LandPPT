"""HTML 安全与校验原语。

这一层不关心 agent 循环，只负责回答两个问题：
1. 这段 HTML 能不能安全地写进幻灯片？
2. 清洗后的 HTML 是什么？
"""

from __future__ import annotations

import copy
import functools
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple, Union

from bs4 import BeautifulSoup
from bs4.element import Tag

AGENT_ID_ATTRS = ("data-agent-id", "data-quick-ai-id")

_UNSAFE_CSS_MARKERS = (
    "expression(",
    "javascript:",
    "-moz-binding",
    "@import",
)
_CSS_PROPERTY_RE = re.compile(r"^-?[a-zA-Z][a-zA-Z0-9-]*$")
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]*)", re.IGNORECASE)
_SAFE_URL_SCHEMES = ("http:", "https:", "data:image/", "/", "./", "../", "#")


@dataclass
class SlideEditValidationResult:
    valid: bool
    errors: List[str]
    warnings: List[str]
    sanitized_html: str


def compute_slide_html_hash(html: str) -> str:
    normalized = (html or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def strip_agent_ids(html: str) -> str:
    from ..svg_page.edit import is_svg_document, strip_svg_agent_ids

    if is_svg_document(html):
        return strip_svg_agent_ids(html)
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.find_all(True):
        for attr in AGENT_ID_ATTRS:
            if attr in node.attrs:
                del node.attrs[attr]
    return str(soup).strip()


def _attribute_value_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _attribute_value_scheme_text(value: Any) -> str:
    return re.sub(r"[\x00-\x20]+", "", _attribute_value_text(value)).lower()


def _has_javascript_attribute_value(soup: BeautifulSoup) -> bool:
    for node in soup.find_all(True):
        for value in getattr(node, "attrs", {}).values():
            if "javascript:" in _attribute_value_scheme_text(value):
                return True
    return False


def _has_srcdoc_attribute(soup: BeautifulSoup) -> bool:
    return any(
        attr.lower() == "srcdoc"
        for tag in soup.find_all(True)
        for attr in getattr(tag, "attrs", {})
    )


#: 比较"脚本是否原样保留"时忽略的属性。agent 定位属性不是脚本内容；
#: integrity / crossorigin 只是 SRI/CORS 元数据：编辑器预览渲染前会剥掉它们
#: （生成的 integrity 哈希经常不可靠），基于预览 DOM 的草稿因此可能缺少这两个
#: 属性。src 与脚本正文仍必须逐字一致，所以这不会放行任何新的可执行代码。
_SCRIPT_METADATA_ATTRS = AGENT_ID_ATTRS + ("integrity", "crossorigin")


def _node_signature(node: Tag) -> str:
    node = copy.copy(node)
    for attr in _SCRIPT_METADATA_ATTRS:
        node.attrs.pop(attr, None)
    return str(node)


def _is_executable_attribute(attr: str, value: Any) -> bool:
    lowered = (attr or "").lower()
    return (
        lowered.startswith("on")
        or lowered == "srcdoc"
        or "javascript:" in _attribute_value_scheme_text(value)
    )


def _executable_attribute_key(node: Tag, attr: str, value: Any) -> Tuple[str, str, str]:
    return (node.name or "", (attr or "").lower(), _attribute_value_text(value))


@functools.lru_cache(maxsize=32)
def _baseline_executable_content(
    baseline_html: str,
) -> Tuple[Tuple[str, ...], Tuple[str, ...], Counter]:
    """基线里已有的可执行内容：<base> 签名、<script> 签名、带脚本的属性计数。

    同一个 run 里每次工具调用都要对照基线，缓存后不用反复解析整页。
    """
    baseline = BeautifulSoup(baseline_html, "html.parser")
    attributes: Counter = Counter(
        _executable_attribute_key(node, attr, value)
        for node in baseline.find_all(True)
        for attr, value in node.attrs.items()
        if _is_executable_attribute(attr, value)
    )
    return (
        tuple(_node_signature(node) for node in baseline.find_all("base")),
        tuple(_node_signature(node) for node in baseline.find_all("script")),
        attributes,
    )


@dataclass
class _PreservedContent:
    """草稿里可以原样保留的可执行内容，按节点身份 id() 记录（bs4 Tag 不可哈希）。"""

    scripts: set = field(default_factory=set)
    attributes: set = field(default_factory=set)


def _preserved_content(soup: BeautifulSoup, baseline_html: Optional[str]) -> _PreservedContent:
    """Match executable content that already exists unchanged in the baseline.

    Scripts must form an ordered subset of the baseline scripts (attributes and
    body included). Event handlers, ``javascript:`` values and ``srcdoc`` must
    each match a baseline occurrence on the same tag name, and every baseline
    occurrence can be claimed only once. Callers at the persistence boundary must
    supply the server's stored HTML, never a client-provided allowlist. This never
    admits new or modified executable code.
    """
    preserved = _PreservedContent()
    if baseline_html is None:
        return preserved
    base_signatures, originals, attribute_budget = _baseline_executable_content(baseline_html)

    # Changing <base> can redirect an otherwise unchanged relative script URL.
    if tuple(_node_signature(node) for node in soup.find_all("base")) == base_signatures:
        position = 0
        for script in soup.find_all("script"):
            try:
                index = originals.index(_node_signature(script), position)
            except ValueError:
                continue
            preserved.scripts.add(id(script))
            position = index + 1

    budget = Counter(attribute_budget)
    for node in soup.find_all(True):
        for attr, value in node.attrs.items():
            if not _is_executable_attribute(attr, value):
                continue
            key = _executable_attribute_key(node, attr, value)
            if budget[key] > 0:
                budget[key] -= 1
                preserved.attributes.add((id(node), attr))
    return preserved


def has_new_executable_content(html: Union[str, BeautifulSoup], baseline_html: str) -> bool:
    """草稿里是否出现了基线中没有的脚本或带脚本的属性。

    接受 HTML 字符串或已解析的草稿树；后者让每次编辑后的检查不必重新序列化再解析。
    """
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html or "", "html.parser")
    preserved = _preserved_content(soup, baseline_html)
    if len(soup.find_all("script")) != len(preserved.scripts):
        return True
    return any(
        (id(node), attr) not in preserved.attributes
        for node in soup.find_all(True)
        for attr, value in node.attrs.items()
        if _is_executable_attribute(attr, value)
    )


def sanitize_slide_html(html: str, *, baseline_html: Optional[str] = None) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    preserved = _preserved_content(soup, baseline_html)

    for script in soup.find_all("script"):
        if id(script) not in preserved.scripts:
            script.decompose()

    for node in soup.find_all(True):
        if id(node) in preserved.scripts:
            continue
        for attr in list(getattr(node, "attrs", {}).keys()):
            if (id(node), attr) in preserved.attributes:
                continue
            attr_lower = (attr or "").lower()
            value = node.attrs.get(attr)
            if attr_lower.startswith("on"):
                del node.attrs[attr]
                continue
            if attr_lower == "srcdoc":
                del node.attrs[attr]
                continue
            if "javascript:" in _attribute_value_scheme_text(value):
                del node.attrs[attr]
                continue
            if attr_lower == "data-agent-id":
                del node.attrs[attr]

    return str(soup).strip()


class _SlideHtmlStructureParser(HTMLParser):
    _VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: List[str] = []
        self.errors: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_name = tag.lower()
        if tag_name not in self._VOID_ELEMENTS:
            self.stack.append(tag_name)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in self._VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append("html is malformed")
            return
        if self.stack[-1] == tag_name:
            self.stack.pop()
            return
        self.errors.append("html is malformed")

    def close(self) -> None:
        super().close()
        if self.stack:
            self.errors.append("html is malformed")


def _find_html_structure_errors(html: str) -> List[str]:
    parser = _SlideHtmlStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ["html is malformed"]
    return list(dict.fromkeys(parser.errors))


def validate_slide_html(html: str, *, baseline_html: Optional[str] = None) -> SlideEditValidationResult:
    from ..svg_page.edit import is_svg_document, validate_svg_edit

    if is_svg_document(html) or is_svg_document(baseline_html):
        return validate_svg_edit(html, baseline_html)
    errors: List[str] = []
    warnings: List[str] = []
    original = html or ""

    if not original.strip():
        errors.append("html content is required")
        return SlideEditValidationResult(False, errors, warnings, "")

    original_soup = BeautifulSoup(original, "html.parser")
    preserved = _preserved_content(original_soup, baseline_html)
    scripts = original_soup.find_all("script")
    if any(id(script) not in preserved.scripts for script in scripts):
        errors.append("script tags are not allowed")

    # Unchanged executable content from the stored slide is opaque to the checks
    # below: a preserved script may mention javascript: in its source, and a
    # preserved handler is by definition an on* attribute. Drop them from the
    # working copy so only new or modified content can raise an error.
    for script in scripts:
        if id(script) in preserved.scripts:
            script.extract()
    for node in original_soup.find_all(True):
        for attr in list(node.attrs):
            if (id(node), attr) in preserved.attributes:
                del node.attrs[attr]
    original_lower = str(original_soup).lower()
    if any(attr.lower().startswith("on") for tag in original_soup.find_all(True) for attr in tag.attrs):
        errors.append("inline event handlers are not allowed")

    if "javascript:" in original_lower or _has_javascript_attribute_value(original_soup):
        errors.append("javascript urls are not allowed")

    if _has_srcdoc_attribute(original_soup):
        errors.append("srcdoc attributes are not allowed")

    errors.extend(_find_html_structure_errors(original))

    sanitized = sanitize_slide_html(original, baseline_html=baseline_html)
    soup = BeautifulSoup(sanitized, "html.parser")
    if not soup.find(True):
        errors.append("html must contain at least one element")

    root_text = soup.get_text(" ", strip=True)
    has_media = bool(soup.find(["img", "svg", "canvas", "video", "picture"]))
    if not root_text and not has_media:
        warnings.append("slide has no visible text or media")

    return SlideEditValidationResult(
        valid=not errors,
        errors=list(dict.fromkeys(errors)),
        warnings=warnings,
        sanitized_html=sanitized,
    )


def is_safe_attribute(name: str, value: Any) -> bool:
    """属性级安全判断，供 set_attributes 工具使用。"""
    lowered = (name or "").strip().lower()
    if not lowered or not re.fullmatch(r"[a-zA-Z_:][-a-zA-Z0-9_:.]*", lowered):
        return False
    if lowered.startswith("on") or lowered in {"srcdoc", "data-agent-id"}:
        return False
    return "javascript:" not in _attribute_value_scheme_text(value)


def css_declaration_error(prop: str, value: str) -> Optional[str]:
    """返回不安全 CSS 声明的原因，安全则返回 None。

    这里用黑名单替代旧的属性白名单：白名单会挡掉 gap / flex /
    grid-template-columns 等大量正常排版属性，逼着模型改用整块 HTML 替换，
    反而放大了改动面。安全边界交给取值检查和最终 sanitize。
    """
    name = (prop or "").strip().lower()
    raw_value = (value or "").strip()

    if not name or not _CSS_PROPERTY_RE.fullmatch(name):
        return f"invalid css property: {prop}"
    if not raw_value:
        return f"empty css value for {name}"

    collapsed = re.sub(r"[\x00-\x20]+", "", raw_value).lower()
    for marker in _UNSAFE_CSS_MARKERS:
        if marker.replace(" ", "") in collapsed:
            return f"unsafe css value for {name}"

    for match in _CSS_URL_RE.finditer(raw_value):
        target = re.sub(r"[\x00-\x20]+", "", match.group(1)).lower()
        if target and not target.startswith(_SAFE_URL_SCHEMES):
            return f"unsafe css url in {name}"

    return None


def _split_style_declarations(style: str) -> List[str]:
    """Split on top-level ';' only.

    A plain ``style.split(";")`` cut inline ``url(data:image/svg+xml;base64,...)``
    values in half, so merging any unrelated property re-serialised the element
    with a broken background.
    """
    items: List[str] = []
    current: List[str] = []
    depth = 0
    quote: Optional[str] = None

    for char in style or "":
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            items.append("".join(current))
            current = []
            continue
        current.append(char)

    if current:
        items.append("".join(current))
    return items


def parse_style_declarations(style: str) -> Dict[str, str]:
    declarations: Dict[str, str] = {}
    for item in _split_style_declarations(style):
        if ":" not in item:
            continue
        prop, value = item.split(":", 1)
        prop = prop.strip().lower()
        value = value.strip()
        if prop and value:
            declarations[prop] = value
    return declarations


def serialize_style_declarations(declarations: Dict[str, str]) -> str:
    return "; ".join(f"{prop}: {value}" for prop, value in declarations.items())
