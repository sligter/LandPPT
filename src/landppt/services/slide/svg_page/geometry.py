"""包围盒、transform 与 path 的几何计算。

路径包围盒为近似值；圆弧与光滑曲线不保证覆盖真实轮廓，需截图复核。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

Matrix = Tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TRANSFORM_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_PATH_TOKEN_RE = re.compile(
    r"[MmZzLlHhVvCcSsQqTtAa]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
)


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def union(self, other: "BBox") -> "BBox":
        return BBox(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def intersection(self, other: "BBox") -> Optional["BBox"]:
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return BBox(x0, y0, x1, y1)

    def expand(self, amount: float) -> "BBox":
        return BBox(
            self.x0 - amount, self.y0 - amount, self.x1 + amount, self.y1 + amount
        )

    def contains(self, other: "BBox", tolerance: float = 0.0) -> bool:
        return (
            other.x0 >= self.x0 - tolerance
            and other.y0 >= self.y0 - tolerance
            and other.x1 <= self.x1 + tolerance
            and other.y1 <= self.y1 + tolerance
        )

    def rounded(self) -> List[int]:
        return [
            int(round(self.x0)),
            int(round(self.y0)),
            int(round(self.x1)),
            int(round(self.y1)),
        ]


def bbox_union(boxes: Iterable[BBox]) -> Optional[BBox]:
    result: Optional[BBox] = None
    for box in boxes:
        result = box if result is None else result.union(box)
    return result


def parse_length(value: Optional[str], default: float = 0.0) -> float:
    """解析 ``24``、``24px``、``50%``（按画布宽 1280 的百分比不适用，视为无效）。"""
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    match = _NUMBER_RE.match(text)
    if not match:
        return default
    number = float(match.group(0))
    if not math.isfinite(number):
        raise ValueError("SVG coordinates must be finite")
    unit = text[match.end() :].strip()
    if unit in ("", "px"):
        return number
    if unit == "pt":
        return number * 4 / 3
    if unit in ("em", "rem"):
        return number * 16
    if unit == "%":
        return default
    return number


def parse_points(value: Optional[str]) -> List[Tuple[float, float]]:
    numbers = [float(n) for n in _NUMBER_RE.findall(value or "")]
    return [(numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)]


# ----------------------------------------------------------------------
# transform
# ----------------------------------------------------------------------
def multiply(m1: Matrix, m2: Matrix) -> Matrix:
    """返回 m1 · m2（先应用 m2，再应用 m1）。"""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def parse_transform(value: Optional[str]) -> Matrix:
    matrix: Matrix = IDENTITY
    if not value:
        return matrix
    for name, args_text in _TRANSFORM_RE.findall(value):
        args = [float(n) for n in _NUMBER_RE.findall(args_text)]
        local: Matrix = IDENTITY
        if name == "matrix" and len(args) == 6:
            local = tuple(args)  # type: ignore[assignment]
        elif name == "translate" and args:
            local = (1, 0, 0, 1, args[0], args[1] if len(args) > 1 else 0.0)
        elif name == "scale" and args:
            sx = args[0]
            sy = args[1] if len(args) > 1 else sx
            local = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate" and args:
            angle = math.radians(args[0])
            cos, sin = math.cos(angle), math.sin(angle)
            rotation: Matrix = (cos, sin, -sin, cos, 0, 0)
            if len(args) >= 3:
                cx, cy = args[1], args[2]
                local = multiply(
                    multiply((1, 0, 0, 1, cx, cy), rotation), (1, 0, 0, 1, -cx, -cy)
                )
            else:
                local = rotation
        elif name == "skewX" and args:
            local = (1, 0, math.tan(math.radians(args[0])), 1, 0, 0)
        elif name == "skewY" and args:
            local = (1, math.tan(math.radians(args[0])), 0, 1, 0, 0)
        matrix = multiply(matrix, local)
    return matrix


def apply_point(m: Matrix, x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def apply_bbox(m: Matrix, box: BBox) -> BBox:
    corners = [
        apply_point(m, box.x0, box.y0),
        apply_point(m, box.x1, box.y0),
        apply_point(m, box.x0, box.y1),
        apply_point(m, box.x1, box.y1),
    ]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def matrix_scale(m: Matrix) -> float:
    a, b, c, d, _, _ = m
    return math.sqrt(abs(a * d - b * c)) or 1.0


def format_transform_prefix(existing: Optional[str], prefix: str) -> str:
    existing = (existing or "").strip()
    return f"{prefix} {existing}".strip()


# ----------------------------------------------------------------------
# path
# ----------------------------------------------------------------------
def path_bbox(d: Optional[str]) -> Optional[BBox]:
    """控制点外壳：包含所有端点与控制点，圆弧按半径外扩。"""
    tokens = _PATH_TOKEN_RE.findall(d or "")
    if not tokens:
        return None

    points: List[Tuple[float, float]] = []
    x = y = 0.0
    start_x = start_y = 0.0
    command = ""
    index = 0

    def take(count: int) -> Optional[List[float]]:
        nonlocal index
        values: List[float] = []
        while len(values) < count and index < len(tokens):
            token = tokens[index]
            if token[0].isalpha():
                return None
            values.append(float(token))
            index += 1
        return values if len(values) == count else None

    while index < len(tokens):
        token = tokens[index]
        if token[0].isalpha():
            command = token
            index += 1
            if command in ("Z", "z"):
                x, y = start_x, start_y
                continue
        if not command:
            index += 1
            continue
        relative = command.islower()
        upper = command.upper()
        if upper == "M":
            values = take(2)
            if values is None:
                break
            x, y = (
                (x + values[0], y + values[1]) if relative else (values[0], values[1])
            )
            start_x, start_y = x, y
            points.append((x, y))
            command = "l" if relative else "L"
        elif upper == "L":
            values = take(2)
            if values is None:
                break
            x, y = (
                (x + values[0], y + values[1]) if relative else (values[0], values[1])
            )
            points.append((x, y))
        elif upper == "H":
            values = take(1)
            if values is None:
                break
            x = x + values[0] if relative else values[0]
            points.append((x, y))
        elif upper == "V":
            values = take(1)
            if values is None:
                break
            y = y + values[0] if relative else values[0]
            points.append((x, y))
        elif upper == "C":
            values = take(6)
            if values is None:
                break
            base_x, base_y = (x, y) if relative else (0.0, 0.0)
            for i in range(0, 6, 2):
                points.append((base_x + values[i], base_y + values[i + 1]))
            x, y = base_x + values[4], base_y + values[5]
        elif upper in ("S", "Q"):
            values = take(4)
            if values is None:
                break
            base_x, base_y = (x, y) if relative else (0.0, 0.0)
            for i in range(0, 4, 2):
                points.append((base_x + values[i], base_y + values[i + 1]))
            x, y = base_x + values[2], base_y + values[3]
        elif upper == "T":
            values = take(2)
            if values is None:
                break
            x, y = (
                (x + values[0], y + values[1]) if relative else (values[0], values[1])
            )
            points.append((x, y))
        elif upper == "A":
            values = take(7)
            if values is None:
                break
            rx, ry = abs(values[0]), abs(values[1])
            end_x, end_y = (
                (x + values[5], y + values[6]) if relative else (values[5], values[6])
            )
            for px, py in ((x, y), (end_x, end_y)):
                points.append((px - rx, py - ry))
                points.append((px + rx, py + ry))
            x, y = end_x, end_y
        else:
            index += 1

    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def points_bbox(points: Sequence[Tuple[float, float]]) -> Optional[BBox]:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))
