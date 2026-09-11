"""把清洗、分行、检查、修复串成一次候选处理。生成循环与实验脚本共用。"""

from __future__ import annotations

import html as html_lib
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from lxml import etree

from .constants import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    ROLE_ATTR,
    ROLE_STAGE,
    ROLE_TITLE,
    SVG_NS,
)
from .inspect import SvgInspection, describe_defect, inspect_svg
from .layout import TextLayoutResult, layout_text_elements
from .metrics import TextMeasurer, get_text_measurer
from .repair import repair_out_of_canvas
from .sanitize import SanitizedSvg, inject_symbol_library, sanitize_svg, serialize


@dataclass
class CandidateResult:
    root: etree._Element
    sanitize_issues: List[str]
    layout_results: List[TextLayoutResult]
    inspection: SvgInspection
    repair_actions: List[Dict] = field(default_factory=list)
    injected_symbols: List[str] = field(default_factory=list)
    before_repair: Dict = field(default_factory=dict)

    @property
    def markup(self) -> str:
        return serialize(self.root)

    @property
    def blocking(self) -> List[Dict]:
        return self.inspection.blocking

    @property
    def advisory(self) -> List[Dict]:
        return self.inspection.advisory

    @property
    def metrics(self) -> Dict:
        return self.inspection.metrics

    def summary(self) -> Dict:
        return {
            "blocking": len(self.blocking),
            "advisory": len(self.advisory),
            "sanitize_issues": len(self.sanitize_issues),
            "repair_actions": len(self.repair_actions),
            "metrics": self.metrics,
            "defects": self.inspection.defects,
        }


def process_svg_candidate(
    markup: str,
    *,
    measurer: Optional[TextMeasurer] = None,
    allowed_image_urls: Optional[Iterable[str]] = None,
    apply_repair: bool = True,
) -> CandidateResult:
    """清洗 → 注入符号 → 分行缩字 → 检查 → 确定性修复 → 复检。"""
    measurer = measurer or get_text_measurer()
    sanitized: SanitizedSvg = sanitize_svg(
        markup, allowed_image_urls=allowed_image_urls
    )
    root = sanitized.root
    injected = inject_symbol_library(root)
    initial_layout = layout_text_elements(root, measurer, apply_layout=False)
    initial = inspect_svg(root, measurer, initial_layout, sanitized.hand_path_count)
    layout_results = (
        layout_text_elements(root, measurer) if apply_repair else initial_layout
    )
    inspection = inspect_svg(root, measurer, layout_results, sanitized.hand_path_count)
    actions: List[Dict] = []
    if apply_repair and any(
        d.get("type") == "out_of_canvas" for d in inspection.blocking
    ):
        actions = repair_out_of_canvas(root, inspection)
        if actions:
            inspection = inspect_svg(
                root, measurer, layout_results, sanitized.hand_path_count
            )
    return CandidateResult(
        root=root,
        sanitize_issues=list(sanitized.issues),
        layout_results=layout_results,
        inspection=inspection,
        repair_actions=actions,
        injected_symbols=injected,
        before_repair={
            "metrics": initial.metrics,
            "defects": initial.defects,
            "blocking": len(initial.blocking),
        },
    )


def defects_to_prompt_lines(defects: Iterable[Dict]) -> List[str]:
    return [describe_defect(defect) for defect in defects]


def build_placeholder_svg(
    title: str,
    points: Iterable[str],
    page_number: int,
    total_pages: int,
    note: str = "",
) -> str:
    """生成彻底失败时的占位页：只承载标题与要点，并明确标注需要重新生成。"""
    safe_title = html_lib.escape(title or f"第{page_number}页", quote=True)
    lines = [html_lib.escape(str(p), quote=True) for p in list(points)[:6]]
    body = "".join(
        f'<text x="96" y="{240 + i * 44}" font-size="24" fill="#cbd5e1" data-box-w="1088">• {line}</text>'
        for i, line in enumerate(lines)
    )
    note_text = html_lib.escape(
        note or "此页 SVG 生成未通过校验，请重新生成", quote=True
    )
    return (
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}">'
        f'<g {ROLE_ATTR}="background"><rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="#0f172a"/></g>'
        f'<g {ROLE_ATTR}="{ROLE_TITLE}"><text x="96" y="140" font-size="44" font-weight="bold" fill="#f8fafc" data-box-w="1088">{safe_title}</text></g>'
        f'<g {ROLE_ATTR}="{ROLE_STAGE}">{body}</g>'
        f'<g {ROLE_ATTR}="footer"><text x="96" y="690" font-size="16" fill="#f59e0b">{note_text}</text>'
        f'<text x="1200" y="690" font-size="16" fill="#94a3b8" text-anchor="end">{page_number} / {total_pages}</text></g>'
        "</svg>"
    )
