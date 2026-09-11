"""确定性修复：把越界内容平移回画布，装不下就围绕中心等比缩放。

移动的单位是越界元素所属的最外层内容单元（role 分组或根的直接子元素）。
模型经常把卡片矩形和它上面的文字写成同级元素而不分组，所以被该单元包围盒
完全包住的同级元素会一起移动，避免把卡片和标签拆散。

不可机械修复的缺陷（压叠、文本超框、空白带）交给模型定点修复。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from lxml import etree

from .constants import ROLE_ATTR, SAFE_BOTTOM, SAFE_LEFT, SAFE_RIGHT, SAFE_TOP
from .geometry import BBox, IDENTITY, format_transform_prefix, multiply, parse_transform
from .inspect import CANVAS_BOX, ElementBox, SvgInspection
from .sanitize import local_name

SAFE = BBox(float(SAFE_LEFT), float(SAFE_TOP), float(SAFE_RIGHT), float(SAFE_BOTTOM))


def _movable_unit(element: etree._Element) -> etree._Element:
    """越界元素所属的最外层内容单元：role 分组或根的直接子元素。"""
    current = element
    while True:
        parent = current.getparent()
        if parent is None:
            return current
        if local_name(parent) == "svg" or parent.get(ROLE_ATTR):
            return current
        current = parent


def _is_descendant(element: etree._Element, ancestor: etree._Element) -> bool:
    parent = element.getparent()
    while parent is not None:
        if parent is ancestor:
            return True
        parent = parent.getparent()
    return False


def _unit_bbox(unit: etree._Element, boxes: List[ElementBox]) -> Optional[BBox]:
    members = [
        b.bbox
        for b in boxes
        if b.element is not None
        and (b.element is unit or _is_descendant(b.element, unit))
    ]
    if not members:
        return None
    result = members[0]
    for box in members[1:]:
        result = result.union(box)
    return result


def _companions(
    unit: etree._Element, unit_bbox: BBox, boxes: List[ElementBox]
) -> List[etree._Element]:
    """同级且被单元包围盒包住的元素（例如卡片上的文字），随单元一起移动。"""
    parent = unit.getparent()
    if parent is None:
        return []
    tolerance = unit_bbox.expand(2.0)
    companions: List[etree._Element] = []
    for sibling in parent:
        if (
            sibling is unit
            or not isinstance(sibling.tag, str)
            or sibling.get(ROLE_ATTR)
        ):
            continue
        sibling_bbox = _unit_bbox(sibling, boxes)
        if sibling_bbox is not None and tolerance.contains(sibling_bbox):
            companions.append(sibling)
    return companions


def _local_prefix(unit: etree._Element, prefix: str) -> Optional[str]:
    # Inspection reports world coordinates; transforms on a child use its parent's coordinates.
    parent_matrix = IDENTITY
    for ancestor in reversed(list(unit.iterancestors())):
        parent_matrix = multiply(
            parent_matrix, parse_transform(ancestor.get("transform"))
        )
    a, b, c, d, e, f = parent_matrix
    determinant = a * d - b * c
    if abs(determinant) < 1e-9:
        return None
    inverse = (
        d / determinant,
        -b / determinant,
        -c / determinant,
        a / determinant,
        (c * f - d * e) / determinant,
        (b * e - a * f) / determinant,
    )
    local = multiply(multiply(inverse, parse_transform(prefix)), parent_matrix)
    return "matrix(" + " ".join(f"{value:.8g}" for value in local) + ")"


def repair_out_of_canvas(root: etree._Element, inspection: SvgInspection) -> List[Dict]:
    """返回执行过的修复动作；调用方随后需要重新检查。"""
    actions: List[Dict] = []
    by_id = {b.element_id: b for b in inspection.boxes if b.element_id}
    handled: Set[int] = set()
    for defect in inspection.blocking:
        if defect.get("type") != "out_of_canvas":
            continue
        box = by_id.get(defect.get("id"))
        if box is None or box.element is None:
            continue
        unit = _movable_unit(box.element)
        if id(unit) in handled:
            continue
        handled.add(id(unit))
        bbox = _unit_bbox(unit, inspection.boxes)
        if bbox is None:
            continue
        fitted = _fit_unit(bbox)
        if fitted is None:
            continue
        action, prefix = fitted
        prefix = _local_prefix(unit, prefix)
        if prefix is None:
            continue
        companions = _companions(unit, bbox, inspection.boxes)
        for element in [unit, *companions]:
            element.set(
                "transform", format_transform_prefix(element.get("transform"), prefix)
            )
            handled.add(id(element))
        action["id"] = unit.get("id") or defect.get("id")
        action["moved_with"] = [c.get("id") or "" for c in companions]
        actions.append(action)
    return actions


def _fit_unit(bbox: BBox) -> Optional[Tuple[Dict, str]]:
    target = (
        SAFE if bbox.width <= SAFE.width and bbox.height <= SAFE.height else CANVAS_BOX
    )
    if bbox.width <= target.width and bbox.height <= target.height:
        dx = 0.0
        dy = 0.0
        if bbox.x0 < target.x0:
            dx = target.x0 - bbox.x0
        elif bbox.x1 > target.x1:
            dx = target.x1 - bbox.x1
        if bbox.y0 < target.y0:
            dy = target.y0 - bbox.y0
        elif bbox.y1 > target.y1:
            dy = target.y1 - bbox.y1
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return None
        return {
            "action": "translate",
            "dx": round(dx, 1),
            "dy": round(dy, 1),
        }, f"translate({dx:.1f} {dy:.1f})"

    scale = min(target.width / bbox.width, target.height / bbox.height) * 0.98
    cx, cy = bbox.center
    new_w, new_h = bbox.width * scale, bbox.height * scale
    new_cx = min(max(cx, target.x0 + new_w / 2), target.x1 - new_w / 2)
    new_cy = min(max(cy, target.y0 + new_h / 2), target.y1 - new_h / 2)
    prefix = (
        f"translate({new_cx - cx:.1f} {new_cy - cy:.1f}) translate({cx:.1f} {cy:.1f}) "
        f"scale({scale:.4f}) translate({-cx:.1f} {-cy:.1f})"
    )
    return {
        "action": "scale",
        "scale": round(scale, 4),
        "dx": round(new_cx - cx, 1),
        "dy": round(new_cy - cy, 1),
    }, prefix
