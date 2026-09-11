"""几何信号：越界、文本超框、压叠、空白带、等大矩形组。

能精确算的才算：包围盒来自属性与 transform，文字宽度来自真实字体。
手写 path 按控制点外壳保守估计。填充率不作门槛，只进指标。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from lxml import etree

from .constants import (
    BACKGROUND_AREA_RATIO,
    BOX_WIDTH_ATTR,
    CANVAS_HEIGHT,
    CANVAS_TOLERANCE,
    CANVAS_WIDTH,
    DECOR_OPACITY,
    EMPTY_BAND_RATIO,
    EMPTY_COLUMN_RATIO,
    FONT_FLOOR,
    LINE_HEIGHT,
    MAX_HAND_PATHS,
    NON_RENDERING_CONTAINERS,
    OVERLAP_RATIO,
    ROLE_ATTR,
    ROLE_BACKGROUND,
    ROLE_FOOTER,
    ROLE_STAGE,
    ROLE_TITLE,
    SAFE_BOTTOM,
    SAFE_LEFT,
    SAFE_RIGHT,
    SAFE_TOP,
)
from .geometry import (
    IDENTITY,
    BBox,
    Matrix,
    apply_bbox,
    bbox_union,
    multiply,
    parse_length,
    parse_points,
    parse_transform,
    matrix_scale,
    path_bbox,
    points_bbox,
)
from .layout import TextLayoutResult, line_units
from .metrics import TextMeasurer
from .sanitize import element_font_size, inherited_attribute, local_name

BLOCKING_DEFECT_TYPES = frozenset(
    {"out_of_canvas", "text_overflow", "overlap", "empty_page", "min_font_size"}
)
CANVAS_BOX = BBox(0.0, 0.0, float(CANVAS_WIDTH), float(CANVAS_HEIGHT))
SAFE_BOX = BBox(
    float(SAFE_LEFT), float(SAFE_TOP), float(SAFE_RIGHT), float(SAFE_BOTTOM)
)


@dataclass
class ElementBox:
    element_id: str
    tag: str
    bbox: BBox
    role: str
    is_text: bool = False
    is_media: bool = False
    is_background: bool = False
    opacity: float = 1.0
    font_size: float = 0.0
    text: str = ""
    element: Optional[etree._Element] = None

    @property
    def counts_as_content(self) -> bool:
        return not self.is_background and self.opacity > DECOR_OPACITY


@dataclass
class SvgInspection:
    defects: List[Dict] = field(default_factory=list)
    metrics: Dict = field(default_factory=dict)
    boxes: List[ElementBox] = field(default_factory=list)

    @property
    def blocking(self) -> List[Dict]:
        return [d for d in self.defects if d.get("type") in BLOCKING_DEFECT_TYPES]

    @property
    def advisory(self) -> List[Dict]:
        return [d for d in self.defects if d.get("type") not in BLOCKING_DEFECT_TYPES]


# ----------------------------------------------------------------------
# 包围盒收集
# ----------------------------------------------------------------------
def _opacity_of(element: etree._Element) -> float:
    value = 1.0
    current: Optional[etree._Element] = element
    while current is not None:
        for attr in ("opacity",):
            raw = current.get(attr)
            if raw is not None:
                try:
                    value *= max(0.0, min(1.0, float(raw)))
                except ValueError:
                    pass
        current = current.getparent()
    own_fill = element.get("fill-opacity")
    if own_fill is not None and local_name(element) != "text":
        try:
            value *= max(0.0, min(1.0, float(own_fill)))
        except ValueError:
            pass
    return value


def _role_of(element: etree._Element) -> str:
    current: Optional[etree._Element] = element
    while current is not None:
        role = current.get(ROLE_ATTR)
        if role:
            return role
        current = current.getparent()
    return ""


def _stroke_padding(element: etree._Element) -> float:
    stroke = inherited_attribute(element, "stroke", "none") or "none"
    if stroke.strip().lower() in ("none", ""):
        return 0.0
    return parse_length(inherited_attribute(element, "stroke-width", "1"), 1.0) / 2


def _text_box(
    element: etree._Element, measurer: TextMeasurer
) -> Optional[Tuple[BBox, float, str]]:
    size = element_font_size(element)
    weight = inherited_attribute(element, "font-weight", "normal")
    anchor = (inherited_attribute(element, "text-anchor", "start") or "start").strip()
    baseline_mode = (
        inherited_attribute(element, "dominant-baseline", "auto") or "auto"
    ).strip()
    x = parse_length(element.get("x"), 0.0)
    y = parse_length(element.get("y"), 0.0)
    units = line_units(element)
    plain = " ".join(unit[0] for unit in units).strip()
    if not plain:
        return None

    shift = 0.0
    if baseline_mode in ("middle", "central"):
        shift = 0.35 * size
    elif baseline_mode in ("hanging", "text-before-edge"):
        shift = measurer.ascent(size)

    boxes: List[BBox] = []
    baseline = y + shift
    for index, (line, dy) in enumerate(units):
        if dy is not None:
            baseline += dy
        elif index > 0:
            baseline += size * LINE_HEIGHT
        width = measurer.text_width(line, size, weight)
        if anchor == "middle":
            x0 = x - width / 2
        elif anchor == "end":
            x0 = x - width
        else:
            x0 = x
        boxes.append(
            BBox(
                x0,
                baseline - measurer.ascent(size),
                x0 + width,
                baseline + measurer.descent(size),
            )
        )
    union = bbox_union(boxes)
    return (union, size, plain) if union else None


def _shape_box(element: etree._Element, name: str) -> Optional[BBox]:
    get = lambda attr, default=0.0: parse_length(
        element.get(attr), default
    )  # noqa: E731
    if name == "rect":
        w, h = get("width"), get("height")
        if w <= 0 or h <= 0:
            return None
        return BBox(get("x"), get("y"), get("x") + w, get("y") + h)
    if name == "circle":
        r = get("r")
        if r <= 0:
            return None
        return BBox(get("cx") - r, get("cy") - r, get("cx") + r, get("cy") + r)
    if name == "ellipse":
        rx, ry = get("rx"), get("ry")
        if rx <= 0 or ry <= 0:
            return None
        return BBox(get("cx") - rx, get("cy") - ry, get("cx") + rx, get("cy") + ry)
    if name == "line":
        return BBox(
            min(get("x1"), get("x2")),
            min(get("y1"), get("y2")),
            max(get("x1"), get("x2")),
            max(get("y1"), get("y2")),
        )
    if name in ("polyline", "polygon"):
        return points_bbox(parse_points(element.get("points")))
    if name == "path":
        return path_bbox(element.get("d"))
    if name in ("image", "use"):
        w = get("width", 24.0 if name == "use" else 0.0)
        h = get("height", 24.0 if name == "use" else 0.0)
        if w <= 0 or h <= 0:
            return None
        return BBox(get("x"), get("y"), get("x") + w, get("y") + h)
    return None


def collect_boxes(root: etree._Element, measurer: TextMeasurer) -> List[ElementBox]:
    boxes: List[ElementBox] = []

    def walk(element: etree._Element, ctm: Matrix) -> None:
        for child in element:
            if not isinstance(child.tag, str):
                continue
            name = local_name(child)
            if name in NON_RENDERING_CONTAINERS or name in ("title", "desc"):
                continue
            local = multiply(ctm, parse_transform(child.get("transform")))
            if name == "g":
                walk(child, local)
                continue
            raw_box: Optional[BBox] = None
            font_size = 0.0
            text_value = ""
            if name == "text":
                measured = _text_box(child, measurer)
                if measured is None:
                    continue
                raw_box, font_size, text_value = measured
            else:
                raw_box = _shape_box(child, name)
                if raw_box is None:
                    continue
                padding = _stroke_padding(child)
                if padding:
                    raw_box = raw_box.expand(padding)
            bbox = apply_bbox(local, raw_box)
            role = _role_of(child)
            opacity = _opacity_of(child)
            is_background = role == ROLE_BACKGROUND or (
                name in ("rect", "image")
                and bbox.area >= BACKGROUND_AREA_RATIO * CANVAS_BOX.area
            )
            boxes.append(
                ElementBox(
                    element_id=child.get("id") or "",
                    tag=name,
                    bbox=bbox,
                    role=role,
                    is_text=name == "text",
                    is_media=name in ("image", "use"),
                    is_background=is_background,
                    opacity=opacity,
                    font_size=font_size * matrix_scale(local),
                    text=text_value,
                    element=child,
                )
            )

    walk(root, IDENTITY)
    return boxes


# ----------------------------------------------------------------------
# 信号
# ----------------------------------------------------------------------
def inspect_svg(
    root: etree._Element,
    measurer: TextMeasurer,
    layout_results: Optional[Sequence[TextLayoutResult]] = None,
    hand_path_count: Optional[int] = None,
) -> SvgInspection:
    boxes = collect_boxes(root, measurer)
    inspection = SvgInspection(boxes=boxes)
    defects = inspection.defects

    content = [b for b in boxes if b.counts_as_content]
    text_boxes = [b for b in content if b.is_text]
    if not content:
        defects.append({"type": "empty_page"})

    # 1. 越界
    for box in content:
        if not CANVAS_BOX.contains(box.bbox, CANVAS_TOLERANCE):
            defects.append(
                {
                    "type": "out_of_canvas",
                    "id": box.element_id,
                    "tag": box.tag,
                    "bbox": box.bbox.rounded(),
                    "overflow": _overflow_amounts(box.bbox),
                }
            )

    # 2. 文本超框、缺文本框、字号过小
    for result in layout_results or ():
        if result.overflow:
            defects.append(
                {
                    "type": "text_overflow",
                    "id": result.element_id,
                    "text": result.text[:60],
                    "box_w": result.box_width,
                    "box_h": result.box_height,
                    "needed_w": round(result.needed_width, 1),
                    "lines": result.line_count,
                    "font_size": result.font_size,
                }
            )
        elif result.missing_box:
            defects.append(
                {
                    "type": "missing_text_box",
                    "id": result.element_id,
                    "text": result.text[:60],
                    "needed_w": round(result.needed_width, 1),
                }
            )
    for box in text_boxes:
        if 0 < box.font_size < FONT_FLOOR:
            defects.append(
                {
                    "type": "min_font_size",
                    "id": box.element_id,
                    "font_size": box.font_size,
                }
            )
        if (
            box.role != ROLE_FOOTER
            and not SAFE_BOX.contains(box.bbox, CANVAS_TOLERANCE)
            and CANVAS_BOX.contains(box.bbox, CANVAS_TOLERANCE)
        ):
            defects.append(
                {
                    "type": "outside_safe_area",
                    "id": box.element_id,
                    "bbox": box.bbox.rounded(),
                }
            )

    # 3. 压叠：文字对文字、文字对图片/图标
    media_boxes = [b for b in content if b.is_media]
    for i, a in enumerate(text_boxes):
        for b in text_boxes[i + 1 :] + media_boxes:
            inter = a.bbox.intersection(b.bbox)
            if inter is None:
                continue
            smaller = min(a.bbox.area, b.bbox.area) or 1.0
            if inter.area / smaller >= OVERLAP_RATIO:
                defects.append(
                    {
                        "type": "overlap",
                        "a": a.element_id,
                        "b": b.element_id,
                        "a_text": a.text[:40],
                        "b_kind": b.tag,
                        "area": int(inter.area),
                        "bbox": inter.rounded(),
                    }
                )

    # 4. 空白带（stage 区域内，非背景内容的投影）
    region = _stage_region(boxes)
    stage_content = [
        b
        for b in content
        if b.role != ROLE_TITLE
        and b.role != ROLE_FOOTER
        and b.bbox.intersection(region)
    ]
    band = _largest_gap(
        [(b.bbox.y0, b.bbox.y1) for b in stage_content], region.y0, region.y1
    )
    if band and band[1] - band[0] >= EMPTY_BAND_RATIO * region.height:
        defects.append(
            {
                "type": "empty_band",
                "axis": "y",
                "range": [int(band[0]), int(band[1])],
                "height": int(band[1] - band[0]),
            }
        )
    column = _largest_gap(
        [(b.bbox.x0, b.bbox.x1) for b in stage_content], region.x0, region.x1
    )
    if column and column[1] - column[0] >= EMPTY_COLUMN_RATIO * region.width:
        defects.append(
            {
                "type": "empty_band",
                "axis": "x",
                "range": [int(column[0]), int(column[1])],
                "width": int(column[1] - column[0]),
            }
        )

    # 5. 等大等距矩形组
    groups = _equal_rect_groups([b for b in content if b.tag == "rect"])
    for group in groups:
        defects.append(
            {
                "type": "equal_rect_group",
                "ids": [b.element_id for b in group],
                "w": int(group[0].bbox.width),
                "h": int(group[0].bbox.height),
            }
        )

    # 6. 手写路径过多
    if hand_path_count is not None and hand_path_count > MAX_HAND_PATHS:
        defects.append({"type": "too_many_paths", "count": hand_path_count})

    inspection.metrics = _metrics(
        boxes,
        content,
        stage_content,
        region,
        text_boxes,
        defects,
        hand_path_count,
        layout_results,
    )
    return inspection


def _overflow_amounts(box: BBox) -> Dict[str, int]:
    return {
        "left": int(max(0.0, -box.x0)),
        "top": int(max(0.0, -box.y0)),
        "right": int(max(0.0, box.x1 - CANVAS_WIDTH)),
        "bottom": int(max(0.0, box.y1 - CANVAS_HEIGHT)),
    }


def _stage_region(boxes: Sequence[ElementBox]) -> BBox:
    top, bottom = SAFE_BOX.y0, SAFE_BOX.y1
    title = bbox_union(
        b.bbox for b in boxes if b.role == ROLE_TITLE and b.counts_as_content
    )
    footer = bbox_union(
        b.bbox for b in boxes if b.role == ROLE_FOOTER and b.counts_as_content
    )
    if title and title.y1 < bottom:
        top = max(top, title.y1 + 8)
    if footer and footer.y0 > top:
        bottom = min(bottom, footer.y0 - 8)
    if bottom - top < 120:
        top, bottom = SAFE_BOX.y0, SAFE_BOX.y1
    return BBox(SAFE_BOX.x0, top, SAFE_BOX.x1, bottom)


def _largest_gap(
    intervals: List[Tuple[float, float]], start: float, end: float
) -> Optional[Tuple[float, float]]:
    if end <= start:
        return None
    clipped = sorted(
        (max(start, a), min(end, b)) for a, b in intervals if b > start and a < end
    )
    if not clipped:
        return (start, end)
    best: Optional[Tuple[float, float]] = None
    cursor = start
    for a, b in clipped:
        if a > cursor:
            gap = (cursor, a)
            if best is None or gap[1] - gap[0] > best[1] - best[0]:
                best = gap
        cursor = max(cursor, b)
    if end > cursor:
        gap = (cursor, end)
        if best is None or gap[1] - gap[0] > best[1] - best[0]:
            best = gap
    return best


def _equal_rect_groups(
    rects: Sequence[ElementBox], tolerance: float = 4.0
) -> List[List[ElementBox]]:
    buckets: Dict[Tuple[int, int], List[ElementBox]] = {}
    for rect in rects:
        if rect.bbox.width < 40 or rect.bbox.height < 24:
            continue
        key = (
            int(round(rect.bbox.width / tolerance)),
            int(round(rect.bbox.height / tolerance)),
        )
        buckets.setdefault(key, []).append(rect)
    return [group for group in buckets.values() if len(group) >= 3]


def _coverage(boxes: Sequence[ElementBox], region: BBox, cell: float = 16.0) -> float:
    if region.area <= 0:
        return 0.0
    columns = max(1, int(region.width // cell))
    rows = max(1, int(region.height // cell))
    covered = 0
    for row in range(rows):
        y0 = region.y0 + row * cell
        y1 = y0 + cell
        for col in range(columns):
            x0 = region.x0 + col * cell
            x1 = x0 + cell
            cell_box = BBox(x0, y0, x1, y1)
            if any(b.bbox.intersection(cell_box) for b in boxes):
                covered += 1
    return covered / (rows * columns)


def _metrics(
    boxes,
    content,
    stage_content,
    region,
    text_boxes,
    defects,
    hand_path_count,
    layout_results,
) -> Dict:
    content_bbox = bbox_union(b.bbox for b in stage_content)
    font_sizes = sorted({round(b.font_size, 1) for b in text_boxes if b.font_size})
    counts: Dict[str, int] = {}
    for defect in defects:
        counts[defect["type"]] = counts.get(defect["type"], 0) + 1
    return {
        "element_count": len(boxes),
        "content_count": len(content),
        "text_count": len(text_boxes),
        "font_sizes": font_sizes,
        "min_font_size": font_sizes[0] if font_sizes else None,
        "stage_region": region.rounded(),
        "stage_content_bbox": content_bbox.rounded() if content_bbox else None,
        "stage_coverage": round(_coverage(stage_content, region), 3),
        "stage_extent_ratio": (
            round(content_bbox.area / region.area, 3)
            if content_bbox and region.area
            else 0.0
        ),
        "hand_path_count": hand_path_count,
        "equal_rect_groups": counts.get("equal_rect_group", 0),
        "shrunk_text_count": sum(1 for r in (layout_results or ()) if r.shrunk),
        "wrapped_text_count": sum(
            1 for r in (layout_results or ()) if r.rewritten and r.line_count > 1
        ),
        "defect_counts": counts,
        "blocking_count": sum(
            1 for d in defects if d.get("type") in BLOCKING_DEFECT_TYPES
        ),
        "has_roles": sorted({b.role for b in boxes if b.role}),
    }


def describe_defect(defect: Dict) -> str:
    """把缺陷写成给模型看的一句话。"""
    kind = defect.get("type")
    if kind == "out_of_canvas":
        over = defect.get("overflow", {})
        parts = [f"{side} {amount}px" for side, amount in over.items() if amount]
        return f"[out_of_canvas] 元素 {defect.get('id')} 的包围盒 {defect.get('bbox')} 超出画布（{', '.join(parts) or '越界'}），请移入安全区或缩小。"
    if kind == "text_overflow":
        return (
            f"[text_overflow] 文本 {defect.get('id')}“{defect.get('text')}”在 data-box-w={defect.get('box_w')} 内需要 "
            f"{defect.get('lines')} 行、字号已降到 {defect.get('font_size')} 仍装不下，请加宽文本框、缩短文字或调整周围布局。"
        )
    if kind == "overlap":
        return f"[overlap] 文本 {defect.get('a')}“{defect.get('a_text')}”与 {defect.get('b_kind')} {defect.get('b')} 在 {defect.get('bbox')} 处压叠，请错开位置或改变尺寸。"
    if kind == "missing_text_box":
        return f"[missing_text_box] 长文本 {defect.get('id')}“{defect.get('text')}”没有 data-box-w，无法自动换行，请补上可用宽度。"
    if kind == "empty_band":
        if defect.get("axis") == "y":
            return f"[empty_band] stage 在 y {defect.get('range')} 有 {defect.get('height')}px 连续空白，请放大主体或重新分配空间。"
        return f"[empty_band] stage 在 x {defect.get('range')} 有 {defect.get('width')}px 连续空白列。"
    if kind == "equal_rect_group":
        return f"[equal_rect_group] {len(defect.get('ids', []))} 个 {defect.get('w')}×{defect.get('h')} 的等大矩形（{', '.join(defect.get('ids', []))}），请按内容关系区分主次。"
    if kind == "min_font_size":
        return f"[min_font_size] 文本 {defect.get('id')} 字号 {defect.get('font_size')} 低于 {FONT_FLOOR:g}。"
    if kind == "outside_safe_area":
        return f"[outside_safe_area] 文本 {defect.get('id')} 超出安全区 {defect.get('bbox')}。"
    if kind == "too_many_paths":
        return f"[too_many_paths] 手写 path 有 {defect.get('count')} 个，超过 {MAX_HAND_PATHS}，请改用符号库或基本图形。"
    return f"[{kind}] {defect}"
