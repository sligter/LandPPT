"""严格 XML 解析与白名单清洗。

必须用 XML 解析器：``html.parser`` 与 lxml 的 HTML 模式都会把 ``viewBox``、
``linearGradient``、``clipPath`` 转成小写。放进 HTML 壳后浏览器能按外来内容
规则纠正回来，但服务端的任何后处理都会因此失真，所以这里只走 lxml 的 XML 路径。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from lxml import etree

from . import defs_library
from .constants import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_ELEMENTS,
    ALLOWED_STYLE_PROPERTIES,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    DRAWABLE_ELEMENTS,
    MAX_HAND_PATHS,
    MAX_PATH_DATA_LENGTH,
    NON_RENDERING_CONTAINERS,
    SVG_NS,
    XLINK_NS,
    XML_NS,
)
from .geometry import parse_length

_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
_DOCTYPE_RE = re.compile(r"<!DOCTYPE|<!ENTITY", re.IGNORECASE)
_ROOT_TAG_RE = re.compile(r"<svg\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_FONT_SIZE_RE = re.compile(
    r"^\s*([-+]?\d*\.?\d+)\s*(px|pt|em|rem|%)?\s*$", re.IGNORECASE
)
_URL_REF_RE = re.compile(r"url\(\s*['\"]?\s*([^'\")]*)", re.IGNORECASE)
_EXTERNAL_URL_RE = re.compile(r"^(https?:)?//", re.IGNORECASE)
_SAFE_IMAGE_PREFIXES = ("data:image/", "/", "./", "../", "http://", "https://")


class SvgSanitizeError(ValueError):
    """输入不是可用的 SVG 文档。"""


@dataclass
class SanitizedSvg:
    root: etree._Element
    issues: List[str] = field(default_factory=list)
    removed_elements: int = 0
    hand_path_count: int = 0

    @property
    def markup(self) -> str:
        return serialize(self.root)


def serialize(root: etree._Element) -> str:
    return etree.tostring(root, encoding="unicode")


def make_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
        recover=False,
    )


def local_name(element: etree._Element) -> str:
    if not isinstance(element.tag, str):
        return ""
    return etree.QName(element).localname


def namespace_of(element: etree._Element) -> Optional[str]:
    if not isinstance(element.tag, str):
        return None
    return etree.QName(element).namespace


def _ensure_namespaces(markup: str) -> str:
    """根元素缺 xmlns 时补上，模型经常省略；用了 xlink: 前缀也补声明。"""
    match = _ROOT_TAG_RE.search(markup)
    if not match:
        raise SvgSanitizeError("no <svg> root element")
    attrs = match.group(1)
    additions = ""
    if not re.search(r"\sxmlns\s*=", attrs):
        additions += f' xmlns="{SVG_NS}"'
    if "xlink:" in markup and not re.search(r"\sxmlns:xlink\s*=", attrs):
        additions += f' xmlns:xlink="{XLINK_NS}"'
    if not additions:
        return markup
    start, end = match.span(1)
    return markup[:start] + attrs + additions + markup[end:]


def parse_svg(markup: str) -> etree._Element:
    text = _XML_DECL_RE.sub("", markup or "", count=1).strip()
    if not text:
        raise SvgSanitizeError("empty svg markup")
    if _DOCTYPE_RE.search(text):
        raise SvgSanitizeError("DOCTYPE and entity declarations are not allowed")
    text = _ensure_namespaces(text)
    try:
        root = etree.fromstring(text.encode("utf-8"), make_parser())
    except etree.XMLSyntaxError as exc:
        raise SvgSanitizeError(f"svg is not well-formed xml: {exc}") from exc
    if local_name(root) != "svg":
        raise SvgSanitizeError("root element is not <svg>")
    if namespace_of(root) not in (SVG_NS, None):
        raise SvgSanitizeError("root element is not in the SVG namespace")
    return root


# ----------------------------------------------------------------------
def normalize_font_size(
    value: Optional[str], inherited: float = 16.0
) -> Optional[float]:
    if value is None:
        return None
    match = _FONT_SIZE_RE.match(str(value))
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    if unit == "px":
        return number
    if unit == "pt":
        return number * 4 / 3
    if unit in ("em", "rem"):
        return number * inherited
    if unit == "%":
        return number / 100 * inherited
    return number


def _format_number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_style(style: Optional[str]) -> Dict[str, str]:
    declarations: Dict[str, str] = {}
    for item in (style or "").split(";"):
        if ":" not in item:
            continue
        prop, value = item.split(":", 1)
        prop = prop.strip().lower()
        value = value.strip()
        if prop and value:
            declarations[prop] = value
    return declarations


def _value_is_unsafe(value: str) -> bool:
    # CSS escapes/comments can disguise url() and protocols from simple checks.
    if "\\" in value or "/*" in value:
        return True
    lowered = re.sub(r"[\x00-\x20]+", "", value).lower()
    if (
        "javascript:" in lowered
        or "data:text" in lowered
        or "expression(" in lowered
        or "@import" in lowered
    ):
        return True
    for match in _URL_REF_RE.finditer(value):
        target = match.group(1).strip()
        if target and not target.startswith("#"):
            return True
    return False


def _is_allowed_image_href(href: str, allowed_image_urls: Optional[Set[str]]) -> bool:
    candidate = href.strip()
    if not candidate or _value_is_unsafe(candidate):
        return False
    if allowed_image_urls is not None:
        return candidate in allowed_image_urls
    return candidate.lower().startswith(_SAFE_IMAGE_PREFIXES)


def _in_non_rendering_container(element: etree._Element) -> bool:
    parent = element.getparent()
    while parent is not None:
        if local_name(parent) in NON_RENDERING_CONTAINERS:
            return True
        parent = parent.getparent()
    return False


# ----------------------------------------------------------------------
def sanitize_svg(
    markup: str,
    *,
    allowed_image_urls: Optional[Iterable[str]] = None,
    extra_symbol_ids: Optional[Iterable[str]] = None,
) -> SanitizedSvg:
    """解析并清洗一段 SVG。不可用的输入抛 ``SvgSanitizeError``。

    清洗后的树满足：根元素带固定 viewBox；元素与属性都在白名单内；没有脚本、
    样式表、外部引用；``use`` 只引用符号库或文档内 id；所有可绘制元素都有 id；
    font-size 等排版属性已从 style 提升为属性并归一成 px 数字。
    """
    root = parse_svg(markup)
    result = SanitizedSvg(root=root)
    image_allowlist = (
        set(allowed_image_urls) if allowed_image_urls is not None else None
    )

    _strip_disallowed_elements(root, result)
    _strip_disallowed_attributes(root, result, image_allowlist)
    _normalize_root(root)
    _lift_style_declarations(root)
    _normalize_font_sizes(root)
    defined_ids = _assign_ids(root)
    _validate_use_references(root, result, defined_ids, set(extra_symbol_ids or ()))
    result.hand_path_count = _count_hand_paths(root, result)
    return result


def _strip_disallowed_elements(root: etree._Element, result: SanitizedSvg) -> None:
    for element in list(root.iter()):
        if element is root:
            continue
        if not isinstance(element.tag, str):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
            continue
        name = local_name(element)
        namespace = namespace_of(element)
        allowed = name in ALLOWED_ELEMENTS and namespace in (SVG_NS, None)
        if allowed and name == "svg":
            allowed = False  # 不允许嵌套 svg
        if allowed:
            continue
        parent = element.getparent()
        if parent is None:
            continue
        # 保留尾随文本，避免 <text>a<b/>c</text> 丢掉 c
        if element.tail:
            previous = element.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + element.tail
            else:
                parent.text = (parent.text or "") + element.tail
        parent.remove(element)
        result.removed_elements += 1
        result.issues.append(f"removed-element:{name or 'unknown'}")


def _strip_disallowed_attributes(
    root: etree._Element, result: SanitizedSvg, image_allowlist: Optional[Set[str]]
) -> None:
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = local_name(element)
        for attr in list(element.attrib):
            value = element.attrib[attr]
            qname = etree.QName(attr)
            attr_name = qname.localname
            attr_ns = qname.namespace
            if attr_ns == XLINK_NS and attr_name == "href":
                del element.attrib[attr]
                if "href" not in element.attrib:
                    element.set("href", value)
                attr = "href"
                attr_name = "href"
                attr_ns = None
            elif attr_ns == XML_NS and attr_name == "space":
                continue
            elif attr_ns not in (None, "") and attr_name != "href":
                if attr_ns == "http://www.w3.org/2000/xmlns/":
                    continue
                del element.attrib[attr]
                result.issues.append(f"removed-attribute:{attr_name}")
                continue

            lowered = attr_name.lower()
            if lowered.startswith("on"):
                del element.attrib[attr]
                result.issues.append(f"removed-attribute:{attr_name}")
                continue
            if lowered.startswith("data-") or lowered.startswith("aria-"):
                if _value_is_unsafe(value):
                    del element.attrib[attr]
                    result.issues.append(f"removed-attribute:{attr_name}")
                continue
            if attr_name not in ALLOWED_ATTRIBUTES:
                del element.attrib[attr]
                result.issues.append(f"removed-attribute:{attr_name}")
                continue
            if attr_name == "href":
                if name == "image":
                    if not _is_allowed_image_href(value, image_allowlist):
                        del element.attrib[attr]
                        result.issues.append(f"removed-image-href:{value[:80]}")
                    continue
                if not value.strip().startswith("#"):
                    del element.attrib[attr]
                    result.issues.append(f"removed-external-href:{value[:80]}")
                    continue
            if attr_name == "style":
                continue  # 单独处理
            if _value_is_unsafe(value):
                del element.attrib[attr]
                result.issues.append(f"removed-attribute:{attr_name}")

        if name == "image" and "href" not in element.attrib:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
                result.removed_elements += 1
                result.issues.append("removed-element:image-without-source")


def _normalize_root(root: etree._Element) -> None:
    root.set("viewBox", f"0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}")
    root.set("width", str(CANVAS_WIDTH))
    root.set("height", str(CANVAS_HEIGHT))
    for attr in ("x", "y", "transform", "preserveAspectRatio"):
        root.attrib.pop(attr, None)


def _lift_style_declarations(root: etree._Element) -> None:
    """把 style 属性里的排版声明提到属性上，几何检查才看得见。"""
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        style = element.get("style")
        if not style:
            continue
        declarations = parse_style(style)
        for prop, value in declarations.items():
            if prop not in ALLOWED_STYLE_PROPERTIES or _value_is_unsafe(value):
                continue
            # Inline CSS wins over presentation attributes in the browser.
            # Lift declarations so inspection sees the same values.
            element.set(prop, value)
        del element.attrib["style"]


def _normalize_font_sizes(root: etree._Element) -> None:
    def walk(element: etree._Element, inherited: float) -> None:
        raw = element.get("font-size")
        current = inherited
        if raw is not None:
            parsed = normalize_font_size(raw, inherited)
            if parsed is None or parsed <= 0:
                del element.attrib["font-size"]
            else:
                if parsed > 512:
                    raise SvgSanitizeError("font-size exceeds the 512px page limit")
                element.set("font-size", _format_number(parsed))
                current = parsed
        for child in element:
            if isinstance(child.tag, str):
                walk(child, current)

    walk(root, 16.0)


def _assign_ids(root: etree._Element) -> Set[str]:
    """给可绘制元素分配稳定 id；重复 id 改名。返回文档内所有 id。"""
    seen: Set[str] = set()
    counter = 0
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        existing = element.get("id")
        if existing:
            if existing in seen or not re.fullmatch(r"[A-Za-z_][\w.:-]*", existing):
                counter += 1
                while f"n{counter}" in seen:
                    counter += 1
                element.set("id", f"n{counter}")
                seen.add(f"n{counter}")
            else:
                seen.add(existing)
            continue
        if local_name(element) in DRAWABLE_ELEMENTS and not _in_non_rendering_container(
            element
        ):
            counter += 1
            while f"n{counter}" in seen:
                counter += 1
            element.set("id", f"n{counter}")
            seen.add(f"n{counter}")
    return seen


def _validate_use_references(
    root: etree._Element,
    result: SanitizedSvg,
    defined_ids: Set[str],
    extra_symbol_ids: Set[str],
) -> None:
    for use in list(root.iter(f"{{{SVG_NS}}}use", "use")):
        href = (use.get("href") or "").strip()
        target = href[1:] if href.startswith("#") else ""
        if target and (
            defs_library.is_library_symbol(target)
            or target in defined_ids
            or target in extra_symbol_ids
        ):
            continue
        parent = use.getparent()
        if parent is not None:
            parent.remove(use)
            result.removed_elements += 1
            result.issues.append(f"unknown-symbol:{href or '(empty)'}")


def _count_hand_paths(root: etree._Element, result: SanitizedSvg) -> int:
    count = 0
    for path in root.iter(f"{{{SVG_NS}}}path", "path"):
        if _in_non_rendering_container(path):
            continue
        count += 1
        if len(path.get("d") or "") > MAX_PATH_DATA_LENGTH:
            result.issues.append(f"path-too-long:{path.get('id') or '?'}")
    if count > MAX_HAND_PATHS:
        result.issues.append(f"too-many-paths:{count}")
    return count


def referenced_symbol_ids(root: etree._Element) -> List[str]:
    ids: List[str] = []
    for use in root.iter(f"{{{SVG_NS}}}use", "use"):
        href = (use.get("href") or "").strip()
        if href.startswith("#") and defs_library.is_library_symbol(href[1:]):
            ids.append(href[1:])
    return list(dict.fromkeys(ids))


def inject_symbol_library(root: etree._Element) -> List[str]:
    """把引用到的符号注入为根元素的第一个 defs。返回注入的 id 列表。"""
    ids = referenced_symbol_ids(root)
    for existing in list(root):
        if (
            isinstance(existing.tag, str)
            and existing.get("data-landppt") == "symbol-library"
        ):
            root.remove(existing)
    if not ids:
        return []
    for element in list(root.iter()):
        if element is not root and element.get("id") in ids:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
    defs = defs_library.library_defs_element(ids)
    if defs is not None:
        root.insert(0, defs)
        etree.cleanup_namespaces(root)
    return ids


def element_font_size(element: etree._Element, default: float = 16.0) -> float:
    current: Optional[etree._Element] = element
    while current is not None:
        raw = current.get("font-size")
        if raw is not None:
            parsed = parse_length(raw, default)
            if parsed > 0:
                return parsed
        current = current.getparent()
    return default


def inherited_attribute(
    element: etree._Element, name: str, default: Optional[str] = None
) -> Optional[str]:
    current: Optional[etree._Element] = element
    while current is not None:
        value = current.get(name)
        if value is not None:
            return value
        current = current.getparent()
    return default
