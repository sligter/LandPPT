"""两组共用的结果结构与几何统计。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from landppt.services.slide.svg_page.constants import (
    BACKGROUND_AREA_RATIO,
    CANVAS_HEIGHT,
    CANVAS_TOLERANCE,
    CANVAS_WIDTH,
    DECOR_OPACITY,
    EMPTY_BAND_RATIO,
    EMPTY_COLUMN_RATIO,
    OVERLAP_RATIO,
)
from landppt.services.slide.svg_page.geometry import BBox, bbox_union
from landppt.services.slide.svg_page.inspect import (
    CANVAS_BOX,
    SAFE_BOX,
    ElementBox,
    _coverage,
    _equal_rect_groups,
    _largest_gap,
)

SIGNAL_TYPES = (
    "out_of_canvas",
    "overlap",
    "text_overflow",
    "missing_text_box",
    "empty_band",
    "equal_rect_group",
    "min_font_size",
    "too_many_paths",
    "empty_page",
    "measurement_failed",
)


@dataclass
class PageMeasurement:
    source: str
    render_mode: str
    defects: List[Dict] = field(default_factory=list)
    metrics: Dict = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @property
    def signals(self) -> Dict[str, int]:
        counts = {kind: 0 for kind in SIGNAL_TYPES}
        for defect in self.defects:
            kind = defect.get("type")
            if kind in counts:
                counts[kind] += 1
        return counts

    def to_dict(self) -> Dict:
        payload = asdict(self)
        payload["signals"] = self.signals
        return payload

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


def boxes_from_rects(rects: Iterable[Dict]) -> List[ElementBox]:
    """把浏览器返回的矩形转成检查器的 ElementBox，背景与装饰判定沿用同一阈值。"""
    boxes: List[ElementBox] = []
    for rect in rects:
        bbox = BBox(
            float(rect["x0"]), float(rect["y0"]), float(rect["x1"]), float(rect["y1"])
        )
        opacity = float(rect.get("opacity", 1.0) or 1.0)
        role = rect.get("role") or ""
        is_background = role == "background" or (
            rect.get("is_box")
            and not rect.get("is_text")
            and bbox.area >= BACKGROUND_AREA_RATIO * CANVAS_BOX.area
        )
        boxes.append(
            ElementBox(
                element_id=rect.get("id") or rect.get("path") or "",
                tag=rect.get("tag") or "",
                bbox=bbox,
                role=role,
                is_text=bool(rect.get("is_text")),
                is_media=bool(rect.get("is_media")),
                is_background=bool(is_background),
                opacity=opacity,
                font_size=float(rect.get("font_size") or 0.0),
                text=str(rect.get("text") or ""),
            )
        )
    return boxes


def geometry_defects(
    boxes: Sequence[ElementBox], overlaps: Optional[Iterable[Dict]] = None
) -> List[Dict]:
    """与 svg_page.inspect 相同口径的信号；HTML 组的压叠对由浏览器端算好后传入。"""
    content = [b for b in boxes if b.counts_as_content]
    defects: List[Dict] = []
    for box in content:
        if not CANVAS_BOX.contains(box.bbox, CANVAS_TOLERANCE):
            defects.append(
                {
                    "type": "out_of_canvas",
                    "id": box.element_id,
                    "tag": box.tag,
                    "bbox": box.bbox.rounded(),
                }
            )
    for pair in overlaps or ():
        defects.append({"type": "overlap", **pair})
    title = bbox_union(
        b.bbox for b in boxes if b.role == "title" and b.counts_as_content
    )
    footer = bbox_union(
        b.bbox for b in boxes if b.role == "footer" and b.counts_as_content
    )
    top, bottom = SAFE_BOX.y0, SAFE_BOX.y1
    if title and title.y1 < bottom:
        top = max(top, title.y1 + 8)
    if footer and footer.y0 > top:
        bottom = min(bottom, footer.y0 - 8)
    if bottom - top < 120:
        top, bottom = SAFE_BOX.y0, SAFE_BOX.y1
    region = BBox(SAFE_BOX.x0, top, SAFE_BOX.x1, bottom)
    stage = [
        b
        for b in content
        if b.role not in ("title", "footer") and b.bbox.intersection(region)
    ]
    band = _largest_gap([(b.bbox.y0, b.bbox.y1) for b in stage], region.y0, region.y1)
    if band and band[1] - band[0] >= EMPTY_BAND_RATIO * region.height:
        defects.append(
            {
                "type": "empty_band",
                "axis": "y",
                "range": [int(band[0]), int(band[1])],
                "height": int(band[1] - band[0]),
            }
        )
    column = _largest_gap([(b.bbox.x0, b.bbox.x1) for b in stage], region.x0, region.x1)
    if column and column[1] - column[0] >= EMPTY_COLUMN_RATIO * region.width:
        defects.append(
            {
                "type": "empty_band",
                "axis": "x",
                "range": [int(column[0]), int(column[1])],
                "width": int(column[1] - column[0]),
            }
        )
    rects = [
        b
        for b in content
        if b.tag in ("rect", "div", "section", "article", "li", "figure")
        and not b.is_text
    ]
    for group in _equal_rect_groups(rects):
        defects.append(
            {
                "type": "equal_rect_group",
                "ids": [b.element_id for b in group],
                "w": int(group[0].bbox.width),
                "h": int(group[0].bbox.height),
            }
        )
    for box in content:
        if box.is_text and 0 < box.font_size < 14:
            defects.append(
                {
                    "type": "min_font_size",
                    "id": box.element_id,
                    "font_size": box.font_size,
                }
            )
    return defects


def geometry_metrics(boxes: Sequence[ElementBox], defects: Sequence[Dict]) -> Dict:
    content = [b for b in boxes if b.counts_as_content]
    title = bbox_union(
        b.bbox for b in boxes if b.role == "title" and b.counts_as_content
    )
    footer = bbox_union(
        b.bbox for b in boxes if b.role == "footer" and b.counts_as_content
    )
    top, bottom = SAFE_BOX.y0, SAFE_BOX.y1
    if title and title.y1 < bottom:
        top = max(top, title.y1 + 8)
    if footer and footer.y0 > top:
        bottom = min(bottom, footer.y0 - 8)
    if bottom - top < 120:
        top, bottom = SAFE_BOX.y0, SAFE_BOX.y1
    region = BBox(SAFE_BOX.x0, top, SAFE_BOX.x1, bottom)
    stage = [
        b
        for b in content
        if b.role not in ("title", "footer") and b.bbox.intersection(region)
    ]
    content_bbox = bbox_union(b.bbox for b in stage)
    text_boxes = [b for b in content if b.is_text]
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
        "stage_coverage": round(_coverage(stage, region), 3),
        "stage_extent_ratio": (
            round(content_bbox.area / region.area, 3)
            if content_bbox and region.area
            else 0.0
        ),
        "equal_rect_groups": counts.get("equal_rect_group", 0),
        "defect_counts": counts,
        "blocking_count": sum(
            counts.get(kind, 0)
            for kind in ("out_of_canvas", "overlap", "text_overflow")
        ),
    }


def iter_pages(
    paths: Iterable[str], suffixes: Sequence[str] = (".html", ".htm", ".svg")
) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(
                sorted(p for p in path.rglob("*") if p.suffix.lower() in suffixes)
            )
        elif path.exists():
            files.append(path)
    return files
