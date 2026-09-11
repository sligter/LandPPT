"""最小 HTML 壳：SVG 页仍以 html_content 存储，预览、放映、导出零改动复用。"""

from __future__ import annotations

import html
import re
from typing import Optional

from .constants import CANVAS_HEIGHT, CANVAS_WIDTH, DEFAULT_FONT_STACK

RENDER_MODE_ATTR = "data-render-mode"
_SVG_RE = re.compile(r"<svg\b.*?</svg\s*>", re.DOTALL | re.IGNORECASE)
_MODE_RE = re.compile(r'data-render-mode\s*=\s*["\']svg["\']', re.IGNORECASE)


def build_slide_html(
    svg_markup: str,
    *,
    font_stack: str = DEFAULT_FONT_STACK,
    lang: str = "zh-CN",
    title: str = "",
) -> str:
    safe_title = html.escape(title or "Slide", quote=True)
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{html.escape(lang, quote=True)}" {RENDER_MODE_ATTR}="svg">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{safe_title}</title>\n"
        "<style>\n"
        f"html,body{{margin:0;padding:0;width:{CANVAS_WIDTH}px;height:{CANVAS_HEIGHT}px;overflow:hidden;background:#000}}\n"
        f"svg.landppt-svg-page{{display:block;width:{CANVAS_WIDTH}px;height:{CANVAS_HEIGHT}px;font-family:{font_stack}}}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"{_with_root_class(svg_markup)}\n"
        "</body>\n"
        "</html>"
    )


def _with_root_class(svg_markup: str) -> str:
    match = re.match(r"\s*<svg\b([^>]*)>", svg_markup, re.IGNORECASE | re.DOTALL)
    if not match:
        return svg_markup
    attrs = match.group(1)
    if re.search(r"\sclass\s*=", attrs):
        attrs = re.sub(r'(\sclass\s*=\s*["\'])', r"\1landppt-svg-page ", attrs, count=1)
    else:
        attrs = attrs + ' class="landppt-svg-page"'
    return "<svg" + attrs + ">" + svg_markup[match.end() :]


def svg_from_shell(html_content: str) -> Optional[str]:
    match = _SVG_RE.search(html_content or "")
    return match.group(0) if match else None


def is_svg_page_html(html_content: str) -> bool:
    head = (html_content or "")[:600]
    return bool(_MODE_RE.search(head))
