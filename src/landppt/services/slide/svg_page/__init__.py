"""SVG 页面模式：让模型直接在固定画布上绘制整页。

子模块分工：

- ``constants``     画布契约常量与元素/属性白名单
- ``defs_library``  服务端注入的图标符号库
- ``extract``       从模型回复里取出 ``<svg>``
- ``sanitize``      严格 XML 解析、白名单清洗、id 分配
- ``metrics``       用真实字体测量文字宽度
- ``layout``        按 data-box-w 分行与缩字
- ``geometry``      包围盒、transform、path 解析
- ``inspect``       几何信号：越界、压叠、文本超框、空白带、等大矩形组
- ``repair``        确定性修复：平移或缩放越界内容
- ``shell``         最小 HTML 壳，SVG 页仍以 html_content 存储
- ``pipeline``      把上述步骤串成"候选处理"，供生成循环与实验脚本共用
- ``render_mode``   项目级 render_mode 的解析
"""

from .constants import CANVAS_HEIGHT, CANVAS_WIDTH, SVG_NS
from .extract import extract_svg_markup, looks_truncated
from .metrics import TextMeasurer, get_text_measurer
from .pipeline import CandidateResult, build_placeholder_svg, process_svg_candidate
from .render_mode import (
    RENDER_MODE_HTML,
    RENDER_MODE_SVG,
    attach_render_mode,
    normalize_render_mode,
    render_mode_from_requirements,
    resolve_project_render_mode,
)
from .sanitize import SvgSanitizeError, sanitize_svg
from .shell import build_slide_html, is_svg_page_html, svg_from_shell

__all__ = [
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "CandidateResult",
    "RENDER_MODE_HTML",
    "RENDER_MODE_SVG",
    "SVG_NS",
    "SvgSanitizeError",
    "TextMeasurer",
    "attach_render_mode",
    "build_placeholder_svg",
    "build_slide_html",
    "extract_svg_markup",
    "get_text_measurer",
    "is_svg_page_html",
    "looks_truncated",
    "normalize_render_mode",
    "process_svg_candidate",
    "render_mode_from_requirements",
    "resolve_project_render_mode",
    "sanitize_svg",
    "svg_from_shell",
]
