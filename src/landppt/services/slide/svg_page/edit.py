"""SVG-aware editing without sending XML through an HTML parser."""

from __future__ import annotations

from bs4 import BeautifulSoup

from .sanitize import inject_symbol_library, parse_svg, sanitize_svg, serialize
from .shell import build_slide_html, is_svg_page_html, svg_from_shell


def is_svg_document(value: str) -> bool:
    return is_svg_page_html(value) or (value or '').lstrip().startswith('<svg')


def svg_markup(value: str) -> str:
    markup = svg_from_shell(value)
    if not markup:
        raise ValueError('SVG 页面必须包含完整的 <svg> 根元素')
    parse_svg(markup)  # reject malformed XML before BeautifulSoup's recovery parser
    return markup


def replace_svg(document: str, markup: str) -> str:
    original = svg_from_shell(document)
    if original and is_svg_page_html(document):
        return document.replace(original, markup, 1)
    return build_slide_html(markup)


def parse_svg_soup(document: str):
    return BeautifulSoup(svg_markup(document), 'xml')


def validate_svg_edit(document: str, baseline: str | None = None):
    from ..edit_agent.html_safety import SlideEditValidationResult

    try:
        markup = svg_markup(document)
        # Page edits can retain known image assets. They cannot invent new URLs.
        images = []
        if baseline:
            root = parse_svg(svg_markup(baseline))
            images = [e.get('href') or e.get('{http://www.w3.org/1999/xlink}href') for e in root.iter() if e.tag.endswith('}image')]
        cleaned = sanitize_svg(markup, allowed_image_urls=images)
        unsafe = [i for i in cleaned.issues if i.startswith(('removed-', 'unknown-symbol:'))]
        if unsafe:
            raise ValueError('SVG 包含不支持或不安全的内容：' + '; '.join(unsafe))
        inject_symbol_library(cleaned.root)
        # Keep the stored shell so a replacement cannot insert scripts outside SVG.
        output = (replace_svg(baseline, cleaned.markup)
                  if baseline and is_svg_document(baseline)
                  else build_slide_html(cleaned.markup))
        return SlideEditValidationResult(True, [], [], output)
    except (ValueError, TypeError) as exc:
        return SlideEditValidationResult(False, [str(exc)], [], document)


def strip_svg_agent_ids(document: str):
    root = parse_svg(svg_markup(document))
    for element in root.iter():
        for name in ('data-agent-id', 'data-quick-ai-id'):
            element.attrib.pop(name, None)
    return replace_svg(document, serialize(root))
