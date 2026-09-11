"""按 ``data-box-w`` 分行、按 ``data-box-h`` 缩字。

浏览器不会折 SVG 文本。模型只声明可用宽高，这里用真实字宽把 ``<text>``
重写成多行 ``<tspan>``；装不下时按阶梯缩字到下限，仍装不下就记为缺陷，不截断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from lxml import etree

from .constants import (
    BOX_HEIGHT_ATTR,
    BOX_WIDTH_ATTR,
    FONT_FLOOR,
    FONT_SHRINK_STEP,
    LINE_HEIGHT,
    LINES_ATTR,
    LONG_TEXT_CJK_CHARS,
    LONG_TEXT_LATIN_CHARS,
    MAX_LINES_ATTR,
    NON_RENDERING_CONTAINERS,
    SVG_NS,
)
from .geometry import parse_length
from .metrics import TextMeasurer, count_text_kinds, iter_break_units
from .sanitize import element_font_size, inherited_attribute, local_name


@dataclass
class TextLayoutResult:
    element_id: str
    text: str
    font_size: float
    original_font_size: float
    lines: List[str]
    box_width: Optional[float]
    box_height: Optional[float]
    needed_width: float
    overflow: bool = False
    shrunk: bool = False
    rewritten: bool = False
    missing_box: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return len(self.lines)


def wrap_text(
    text: str,
    max_width: float,
    font_size: float,
    measurer: TextMeasurer,
    weight="normal",
) -> List[str]:
    """贪心分行：中文逐字、拉丁按词，单个超宽单元按字符硬切。"""
    lines: List[str] = []
    current = ""
    current_width = 0.0

    def unit_width(unit: str) -> float:
        return measurer.text_width(unit, font_size, weight)

    for unit in iter_break_units(text):
        if unit == " ":
            if current:
                current += " "
                current_width += unit_width(" ")
            continue
        width = unit_width(unit)
        if current and current_width + width > max_width:
            lines.append(current.rstrip())
            current, current_width = "", 0.0
        if current_width + width <= max_width or not current:
            if width > max_width and not current:
                # 单个单元超宽：按字符硬切
                for ch in unit:
                    ch_width = unit_width(ch)
                    if current and current_width + ch_width > max_width:
                        lines.append(current.rstrip())
                        current, current_width = "", 0.0
                    current += ch
                    current_width += ch_width
                continue
            current += unit
            current_width += width
        else:
            lines.append(current.rstrip())
            current, current_width = unit, width
    if current.strip():
        lines.append(current.rstrip())
    return lines or [""]


def _collect_paragraphs(text_el: etree._Element) -> Optional[List[str]]:
    """把 text 的内容折成段落列表；含内联样式 tspan 的复杂文本返回 None。"""
    paragraphs: List[str] = []
    buffer = text_el.text or ""
    for child in text_el:
        if not isinstance(child.tag, str):
            continue
        if local_name(child) != "tspan":
            return None
        has_break = child.get("x") is not None or child.get("dy") is not None
        styled = any(
            attr in child.attrib
            for attr in (
                "fill",
                "font-weight",
                "font-size",
                "font-style",
                "style",
                "class",
            )
        )
        if styled and not has_break:
            return None
        if has_break:
            if buffer.strip():
                paragraphs.append(buffer.strip())
            buffer = ""
        buffer += (child.text or "") + "".join(
            (grand.text or "") + (grand.tail or "")
            for grand in child
            if isinstance(grand.tag, str)
        )
        buffer += child.tail or ""
    if buffer.strip():
        paragraphs.append(buffer.strip())
    return paragraphs


def _plain_text(text_el: etree._Element) -> str:
    return " ".join("".join(text_el.itertext()).split())


def _in_non_rendering(element: etree._Element) -> bool:
    parent = element.getparent()
    while parent is not None:
        if local_name(parent) in NON_RENDERING_CONTAINERS:
            return True
        parent = parent.getparent()
    return False


def is_long_text(text: str) -> bool:
    cjk, other = count_text_kinds(text)
    return (
        cjk > LONG_TEXT_CJK_CHARS
        or other > LONG_TEXT_LATIN_CHARS
        or (cjk + other / 2) > LONG_TEXT_CJK_CHARS
    )


def layout_text_elements(
    root: etree._Element, measurer: TextMeasurer, *, apply_layout: bool = True
) -> List[TextLayoutResult]:
    results: List[TextLayoutResult] = []
    for text_el in list(root.iter(f"{{{SVG_NS}}}text", "text")):
        if _in_non_rendering(text_el):
            continue
        result = _layout_single(text_el, measurer, apply_layout=apply_layout)
        if result is not None:
            results.append(result)
    return results


def _layout_single(
    text_el: etree._Element, measurer: TextMeasurer, *, apply_layout: bool = True
) -> Optional[TextLayoutResult]:
    element_id = text_el.get("id") or ""
    plain = _plain_text(text_el)
    if not plain:
        return None
    font_size = element_font_size(text_el)
    weight = inherited_attribute(text_el, "font-weight", "normal")
    box_width = max(0.0, parse_length(text_el.get(BOX_WIDTH_ATTR), 0.0)) or None
    box_height = max(0.0, parse_length(text_el.get(BOX_HEIGHT_ATTR), 0.0)) or None
    max_lines_raw = text_el.get(MAX_LINES_ATTR)
    max_lines = int(parse_length(max_lines_raw, 0.0)) if max_lines_raw else None

    result = TextLayoutResult(
        element_id=element_id,
        text=plain,
        font_size=font_size,
        original_font_size=font_size,
        lines=[plain],
        box_width=box_width,
        box_height=box_height,
        needed_width=measurer.text_width(plain, font_size, weight),
    )

    if not apply_layout:
        result.lines = text_lines(text_el)
        result.needed_width = max(
            (measurer.text_width(line, font_size, weight) for line in result.lines),
            default=0.0,
        )
        result.missing_box = box_width is None and is_long_text(plain)
        result.overflow = bool(
            (box_width is not None and result.needed_width > box_width + 0.5)
            or (
                box_height is not None
                and _block_height(len(result.lines), font_size) > box_height + 0.5
            )
            or (max_lines is not None and len(result.lines) > max_lines)
        )
        return result

    paragraphs = _collect_paragraphs(text_el)
    if paragraphs is None:
        result.notes.append("styled-spans-left-untouched")
        return result

    if box_width is None:
        if is_long_text(plain):
            result.missing_box = True
            result.notes.append("long-text-without-box")
        if len(paragraphs) > 1:
            result.lines = paragraphs
        return result

    size = font_size
    while True:
        lines: List[str] = []
        for paragraph in paragraphs:
            lines.extend(wrap_text(paragraph, box_width, size, measurer, weight))
        needed_height = _block_height(len(lines), size)
        fits_height = box_height is None or needed_height <= box_height + 0.5
        fits_lines = max_lines is None or len(lines) <= max_lines
        widest = max(
            (measurer.text_width(line, size, weight) for line in lines), default=0.0
        )
        fits_width = widest <= box_width + 0.5
        if (
            fits_height and fits_lines and fits_width
        ) or size - FONT_SHRINK_STEP < FONT_FLOOR:
            break
        size -= FONT_SHRINK_STEP

    result.lines = lines
    result.font_size = size
    result.shrunk = size < font_size
    result.needed_width = widest
    result.overflow = not (fits_height and fits_lines and fits_width)
    if result.overflow:
        result.notes.append("does-not-fit-after-shrink")

    _rewrite_lines(text_el, lines, size, font_size)
    result.rewritten = True
    return result


def _block_height(line_count: int, size: float) -> float:
    if line_count <= 0:
        return 0.0
    return size + (line_count - 1) * size * LINE_HEIGHT


def _rewrite_lines(
    text_el: etree._Element, lines: List[str], size: float, original_size: float
) -> None:
    x = text_el.get("x") or "0"
    if size != original_size:
        text_el.set("font-size", f"{size:g}")
    for child in list(text_el):
        text_el.remove(child)
    text_el.text = None
    if len(lines) == 1:
        text_el.text = lines[0]
        text_el.set(LINES_ATTR, "1")
        return
    for index, line in enumerate(lines):
        tspan = etree.SubElement(text_el, f"{{{SVG_NS}}}tspan")
        tspan.set("x", x)
        tspan.set("dy", "0" if index == 0 else f"{size * LINE_HEIGHT:g}")
        tspan.text = line
    text_el.set(LINES_ATTR, str(len(lines)))


def _parse_dy(raw: Optional[str], element: etree._Element) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text.endswith("em"):
        try:
            return float(text[:-2]) * element_font_size(element)
        except ValueError:
            return None
    return parse_length(text, 0.0)


def line_units(text_el: etree._Element) -> List[Tuple[str, Optional[float]]]:
    """按行拆出 (行文本, 该行 tspan 声明的 dy 或 None)。

    带 x 或 dy 的 tspan 开启新行；纯样式 tspan 视为行内片段。检查器据此逐行推
    基线：有 dy 就加 dy，否则第二行起加一个行高。
    """
    units: List[Tuple[str, Optional[float]]] = []
    buffer = text_el.text or ""
    pending_dy: Optional[float] = None
    for child in text_el:
        if not isinstance(child.tag, str):
            continue
        is_break = local_name(child) == "tspan" and (
            child.get("x") is not None or child.get("dy") is not None
        )
        if is_break:
            if buffer.strip():
                units.append((buffer.strip(), pending_dy))
            buffer = ""
            pending_dy = _parse_dy(child.get("dy"), child)
        buffer += "".join(child.itertext()) + (child.tail or "")
    if buffer.strip():
        units.append((buffer.strip(), pending_dy))
    return units or [("", None)]


def text_lines(text_el: etree._Element) -> List[str]:
    """检查器用：读出当前文本的各行内容。"""
    return [unit[0] for unit in line_units(text_el)]
