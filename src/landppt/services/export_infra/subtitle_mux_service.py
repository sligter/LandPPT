"""
Subtitle styling and cache helpers shared by export services.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SubtitleStyle:
    font_name: str = "Noto Sans CJK SC"
    font_size: int = 16
    bold: int = 1
    primary_colour: str = "&H00D4FF&"
    outline_colour: str = "&H000000&"
    outline: int = 3
    shadow: int = 0
    margin_v: int = 30
    alignment: int = 2

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SubtitleStyle":
        if not isinstance(data, dict):
            return cls()
        return cls(
            font_name=str(data.get("font_name") or cls.font_name),
            font_size=int(data.get("font_size") or cls.font_size),
            bold=int(data.get("bold") if data.get("bold") is not None else cls.bold),
            primary_colour=str(data.get("primary_colour") or data.get("primaryColor") or cls.primary_colour),
            outline_colour=str(data.get("outline_colour") or data.get("outlineColor") or cls.outline_colour),
            outline=int(data.get("outline") or cls.outline),
            shadow=int(data.get("shadow") or cls.shadow),
            margin_v=int(data.get("margin_v") or cls.margin_v),
            alignment=int(data.get("alignment") or cls.alignment),
        )

    def to_ffmpeg_force_style(self) -> str:
        safe_font = self.font_name.replace("'", "")
        return (
            f"FontName={safe_font},FontSize={self.font_size},Bold={self.bold},"
            f"PrimaryColour={self.primary_colour},OutlineColour={self.outline_colour},"
            f"BorderStyle=1,Outline={self.outline},Shadow={self.shadow},"
            f"MarginV={self.margin_v},Alignment={self.alignment}"
        )


def resolve_subtitle_style(
    subtitle_style: Optional[Dict[str, Any]],
    *,
    height: int,
    render_mode: str,
) -> SubtitleStyle:
    style = SubtitleStyle.from_dict(subtitle_style)
    style_dict = subtitle_style if isinstance(subtitle_style, dict) else {}
    has_explicit_font_size = style_dict.get("font_size") is not None or style_dict.get("fontSize") is not None
    has_explicit_margin_v = style_dict.get("margin_v") is not None or style_dict.get("marginV") is not None

    if render_mode != "live" or (has_explicit_font_size and has_explicit_margin_v):
        return style

    font_size = style.font_size
    margin_v = style.margin_v
    if not has_explicit_font_size:
        font_size = max(12, min(style.font_size, int(round(height * 0.013))))
    if not has_explicit_margin_v:
        margin_v = max(20, min(style.margin_v, int(round(height * 0.024))))

    if font_size == style.font_size and margin_v == style.margin_v:
        return style

    return SubtitleStyle(
        font_name=style.font_name,
        font_size=font_size,
        bold=style.bold,
        primary_colour=style.primary_colour,
        outline_colour=style.outline_colour,
        outline=style.outline,
        shadow=style.shadow,
        margin_v=margin_v,
        alignment=style.alignment,
    )


def build_subtitle_filter(*, subtitle_path: str, width: int, height: int, style: SubtitleStyle) -> str:
    subtitle_ref = Path(subtitle_path).name.replace("\\", "/").replace(":", r"\:")
    return (
        f"subtitles={subtitle_ref}:original_size={int(width)}x{int(height)}:"
        f"force_style='{style.to_ffmpeg_force_style()}'"
    )


def normalize_audio_cache_path(path: Optional[str]) -> str:
    if not path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except Exception:
        return str(path)


def build_cues_by_audio_path(rows: list[Any]) -> dict[str, Optional[str]]:
    mapped: dict[str, Optional[str]] = {}
    for row in rows or []:
        key = normalize_audio_cache_path(getattr(row, "file_path", None))
        if key:
            mapped[key] = getattr(row, "cues_json", None)
    return mapped

