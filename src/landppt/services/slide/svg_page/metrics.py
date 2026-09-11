"""用真实字体测量文字宽度。

全角字符按 1em 估算，适合默认中文字体；字体替换和特殊字形仍需浏览器复核。
拉丁字母与数字宽度差异大（小写约 0.54em、大写约 0.67em、数字约 0.59em），
用 Pillow 测量并加安全余量，不能保证覆盖所有机器上的字体差异。
"""

from __future__ import annotations

import functools
import logging
import os
import sys
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 展示字体栈里最宽的是雅黑；Noto Sans CJK 的拉丁字形窄约 7%。
LATIN_SAFETY = 1.05
BOLD_FACTOR = 1.04
_BASE_SIZE = 100

_FONT_ENV = "LANDPPT_SVG_MEASURE_FONT"

_CANDIDATE_FONTS: Tuple[Tuple[str, str], ...] = (
    # (regular, bold)
    ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"),
    (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ),
    (
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ),
    (
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
    ),
    (
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    ),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", ""),
    ("/System/Library/Fonts/PingFang.ttc", ""),
    ("C:/Windows/Fonts/simhei.ttf", ""),
)

#: 没有字体文件时的估算（em/字符），来自雅黑实测。
_FALLBACK_WIDTHS = {
    "digit": 0.60,
    "upper": 0.68,
    "lower": 0.54,
    "space": 0.28,
    "punct": 0.35,
    "other": 0.62,
}


def is_cjk_char(ch: str) -> bool:
    """汉字、假名、谚文以及全角标点：都按 1em 处理。"""
    code = ord(ch)
    if (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2FA1F
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFF60
        or 0xFFE0 <= code <= 0xFFE6
    ):
        return True
    try:
        return unicodedata.east_asian_width(ch) in ("W", "F")
    except (TypeError, ValueError):
        return False


def _fallback_width(run: str, size: float) -> float:
    total = 0.0
    for ch in run:
        if ch.isdigit():
            total += _FALLBACK_WIDTHS["digit"]
        elif ch.isspace():
            total += _FALLBACK_WIDTHS["space"]
        elif ch.isupper():
            total += _FALLBACK_WIDTHS["upper"]
        elif ch.islower():
            total += _FALLBACK_WIDTHS["lower"]
        elif unicodedata.category(ch).startswith("P"):
            total += _FALLBACK_WIDTHS["punct"]
        else:
            total += _FALLBACK_WIDTHS["other"]
    return total * size


class TextMeasurer:
    """按字号测量文字宽度；字体对象只在 100px 建一次，按比例缩放。"""

    def __init__(
        self, font_path: Optional[str] = None, bold_font_path: Optional[str] = None
    ):
        self.font_path, self.bold_font_path = self._resolve_fonts(
            font_path, bold_font_path
        )
        self._fonts: Dict[bool, object] = {}
        self._cache: Dict[Tuple[str, bool], float] = {}
        self._ascent_ratio = 0.88
        self._descent_ratio = 0.24
        self._load_metrics()

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_fonts(
        font_path: Optional[str], bold_font_path: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        env_font = os.environ.get(_FONT_ENV)
        if font_path:
            return (
                font_path if os.path.exists(font_path) else None,
                (
                    bold_font_path
                    if bold_font_path and os.path.exists(bold_font_path)
                    else None
                ),
            )
        if env_font and os.path.exists(env_font):
            return env_font, None
        for regular, bold in _CANDIDATE_FONTS:
            if os.path.exists(regular):
                return regular, (bold if bold and os.path.exists(bold) else None)
        return None, None

    def _font(self, bold: bool):
        if bold in self._fonts:
            return self._fonts[bold]
        font = None
        path = (self.bold_font_path if bold else None) or self.font_path
        if path:
            try:
                from PIL import ImageFont

                font = ImageFont.truetype(path, _BASE_SIZE)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "SVG text measurer could not load font %s: %s", path, exc
                )
                font = None
        self._fonts[bold] = font
        return font

    def _load_metrics(self) -> None:
        font = self._font(False)
        if font is None:
            return
        try:
            ascent, descent = font.getmetrics()
            if ascent > 0:
                self._ascent_ratio = min(1.2, max(0.7, ascent / _BASE_SIZE))
                self._descent_ratio = min(0.5, max(0.1, descent / _BASE_SIZE))
        except Exception:  # noqa: BLE001
            pass

    @property
    def has_font(self) -> bool:
        return self._font(False) is not None

    # ------------------------------------------------------------------
    def ascent(self, size: float) -> float:
        return self._ascent_ratio * size

    def descent(self, size: float) -> float:
        return self._descent_ratio * size

    def text_width(
        self, text: str, size: float, weight: str | float | None = "normal"
    ) -> float:
        """文字在指定字号下的排版宽度（px）。"""
        if not text:
            return 0.0
        bold = _is_bold(weight)
        key = (text, bold)
        cached = self._cache.get(key)
        if cached is None:
            cached = self._width_at_base(text, bold)
            if len(self._cache) > 8192:
                self._cache.clear()
            self._cache[key] = cached
        return cached * (size / _BASE_SIZE)

    def _width_at_base(self, text: str, bold: bool) -> float:
        total = 0.0
        run: List[str] = []
        for ch in text:
            if is_cjk_char(ch):
                if run:
                    total += self._latin_run_width("".join(run), bold)
                    run = []
                total += _BASE_SIZE
            else:
                run.append(ch)
        if run:
            total += self._latin_run_width("".join(run), bold)
        return total

    def _latin_run_width(self, run: str, bold: bool) -> float:
        font = self._font(bold)
        if font is None:
            width = _fallback_width(run, _BASE_SIZE)
        else:
            try:
                width = float(font.getlength(run))
            except Exception:  # noqa: BLE001
                width = _fallback_width(run, _BASE_SIZE)
            if bold and self.bold_font_path is None:
                width *= BOLD_FACTOR
        return width * LATIN_SAFETY

    def char_widths(self, text: str, size: float, weight="normal") -> List[float]:
        return [self.text_width(ch, size, weight) for ch in text]


def _is_bold(weight) -> bool:
    if weight is None:
        return False
    if isinstance(weight, (int, float)):
        return weight >= 600
    text = str(weight).strip().lower()
    if text in ("bold", "bolder"):
        return True
    try:
        return float(text) >= 600
    except ValueError:
        return False


@functools.lru_cache(maxsize=1)
def get_text_measurer() -> TextMeasurer:
    measurer = TextMeasurer()
    if measurer.has_font:
        logger.info("SVG text measurer using font %s", measurer.font_path)
    else:
        logger.warning(
            "SVG text measurer found no CJK font; falling back to width estimates (platform=%s)",
            sys.platform,
        )
    return measurer


def count_text_kinds(text: str) -> Tuple[int, int]:
    """返回 (中文字符数, 其他字符数)，用于判断长文本。"""
    cjk = sum(1 for ch in text if is_cjk_char(ch))
    return cjk, len(text) - cjk


def iter_break_units(text: str) -> Iterable[str]:
    """把文本切成最小换行单元：中文逐字、拉丁按词、标点粘住相邻单元。"""
    units: List[str] = []
    buffer: List[str] = []

    def flush() -> None:
        if buffer:
            units.append("".join(buffer))
            buffer.clear()

    for ch in text:
        if is_cjk_char(ch):
            flush()
            if ch in "，。、；：！？）】」』》〉" and units:
                units[-1] += ch
            else:
                units.append(ch)
        elif ch.isspace():
            flush()
            units.append(" ")
        else:
            buffer.append(ch)
    flush()

    # 开括号粘到后一个单元
    merged: List[str] = []
    pending_open = ""
    for unit in units:
        if unit in ("（", "【", "「", "『", "《", "〈"):
            pending_open += unit
            continue
        if pending_open:
            unit = pending_open + unit
            pending_open = ""
        merged.append(unit)
    if pending_open:
        merged.append(pending_open)
    return merged
