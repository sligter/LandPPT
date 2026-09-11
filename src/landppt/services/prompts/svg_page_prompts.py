"""SVG 页面模式的提示词：系统提示、单页绘制、定点修复。

共享的设计质量、创意方向、自检段落直接复用 DesignPrompts，画布契约来自
svg_page.constants，符号清单来自 svg_page.defs_library，三者只维护一份。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..slide.svg_page.constants import CANVAS_CONTRACT_TEXT
from ..slide.svg_page.defs_library import symbol_catalog_text
from .design_prompts import DesignPrompts

_INTERNAL_KEYS = ("images_collection", "images_info", "html_content", "svg_report")


class SvgPagePrompts:
    """SVG 页面模式的提示词集合。"""

    @staticmethod
    def get_svg_page_system_prompt() -> str:
        return """你是幻灯片页面的 SVG 绘制器。本次任务输出 SVG 页面而不是 HTML：上文中关于 HTML/CSS、overflow:hidden、Tailwind、Chart.js/ECharts/MathJax/Prism 的说明对本任务无效，页面内不允许任何脚本、样式表、外部资源或动画。
在 1280×720 的画布上直接决定每个元素的位置、尺寸和层次：文字用原生 <text>，图标只能引用给定符号，几何用基本图形和少量路径表达。
设计服务于内容表达：先确定视觉焦点与阅读动线，再安排空间；装饰放大构图，但不能替代构图。"""

    @staticmethod
    def _prompt_slide_data(slide_data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(slide_data, dict):
            return {}
        return {
            key: value
            for key, value in slide_data.items()
            if not str(key).startswith("_") and key not in _INTERNAL_KEYS
        }

    @staticmethod
    def _build_symbol_context() -> str:
        return f"""**可用图标符号**
只能用 `<use href="#id" …/>` 引用下列 id（不含 # 之外的前缀）：
{symbol_catalog_text()}"""

    @staticmethod
    def _build_image_context(image_urls: Optional[Iterable[str]]) -> str:
        urls = [u for u in (image_urls or ()) if u]
        if not urls:
            return "**图片**\n本页没有可用图片，不要写 `<image>`。"
        listed = "\n".join(f"- {url}" for url in urls[:12])
        return f"""**图片**
`<image href>` 只能使用下列地址，按需裁切（clipPath）或加边框，不喧宾夺主：
{listed}"""

    @staticmethod
    def _build_svg_self_check_context() -> str:
        return """**输出前自检**
- 是否表达了 composition_brief 里的信息关系与视觉焦点？主体是否足够大、位置是否有意图？
- 四个 data-role 分组是否按页面类型齐全？所有坐标是否都在 0–1280 × 0–720 内、主要内容是否在安全区内？
- 长文本是否都带了 data-box-w？为换行后的高度预留了空间吗？相邻元素是否留出至少 16px 间距？
- 是否只用了列出的符号 id、只用了给定图片？是否没有 script、style、foreignObject、外链？
- 同级步骤的标记形态是否统一？流程是否有方向？主强调是否只有一个？
- 是否出现了一排等大等距的卡片却没有主次？内容偏少时是否放大了主体而不是留一大片空白？"""

    @staticmethod
    def _build_svg_output_context() -> str:
        return """**输出格式**
只返回一个 ```svg 代码块，内容以 `<svg` 开头、`</svg>` 结束；不要 XML 声明、DOCTYPE、注释或任何解释文字。"""

    @staticmethod
    def get_single_slide_svg_prompt(
        slide_data: Dict[str, Any],
        confirmed_requirements: Dict[str, Any],
        page_number: int,
        total_pages: int,
        context_info: str,
        style_genes: str,
        global_constitution: str = "",
        current_page_brief: str = "",
        image_urls: Optional[Iterable[str]] = None,
    ) -> str:
        constitution_block = (
            f"**全局设计规则**\n{global_constitution}" if global_constitution else ""
        )
        brief_block = (
            "**当前页面指导**\n"
            f"{current_page_brief}\n"
            "（指导里提到的 CSS 手段，请改用等价的几何关系与坐标实现。）"
            if current_page_brief
            else ""
        )
        requirements = (
            confirmed_requirements if isinstance(confirmed_requirements, dict) else {}
        )

        prompt = f"""为第{page_number}页绘制完整 SVG 页面。

**核心目标**
把内容、设计基因和创意蓝图转译成一个成立的空间体验：在固定画布上直接决定每个元素的位置、尺度与层次。

**项目信息**
- 主题：{requirements.get('topic', '')}
- 受众：{requirements.get('target_audience', '')}
- 补充：{requirements.get('description', '无')}

**当前页面**
{SvgPagePrompts._prompt_slide_data(slide_data)}

{DesignPrompts._build_design_quality_context()}

{DesignPrompts._build_creative_direction_context()}

**设计基因**
{style_genes}

{constitution_block}
{brief_block}

{CANVAS_CONTRACT_TEXT.strip()}

{SvgPagePrompts._build_symbol_context()}

{SvgPagePrompts._build_image_context(image_urls)}

{context_info}

{SvgPagePrompts._build_svg_self_check_context()}

{SvgPagePrompts._build_svg_output_context()}
"""
        return DesignPrompts._finalize_prompt(prompt, requirements)

    @staticmethod
    def get_svg_page_repair_prompt(
        svg_markup: str,
        blocking_lines: Iterable[str],
        advisory_lines: Iterable[str],
        page_number: int,
        total_pages: int,
    ) -> str:
        blocking = list(blocking_lines)
        advisory = list(advisory_lines)
        must = "\n".join(f"- {line}" for line in blocking) or "- （无）"
        should = "\n".join(f"- {line}" for line in advisory) or "- （无）"
        return f"""下面是第{page_number}页（共 {total_pages} 页）当前的 SVG，以及服务端校验器发现的问题。
请只修改与问题相关的元素，保留其他元素、id 与整体构图；文字的分行由服务端处理，不要自己拆行。
返回完整 SVG，同样只用一个 ```svg 代码块。

**必须修复**
{must}

**建议改善（不强制）**
{should}

{CANVAS_CONTRACT_TEXT.strip()}

**当前 SVG**
```svg
{svg_markup}
```
"""


__all__: List[str] = ["SvgPagePrompts"]
