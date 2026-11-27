"""
PPT设计基因和视觉指导相关提示词
包含所有用于设计分析和视觉指导的提示词模板
"""

from typing import Dict, Any
import json
import logging

from .system_prompts import SystemPrompts
from .prompt_utils import apply_page_number_prompt_filter
from ..prompt_asset_service import strip_base64_image_payloads_for_prompt
from ..video_explainer import is_video_explainer
from ..audience_content import audience_slide_copy, is_production_direction

logger = logging.getLogger(__name__)


def _is_image_service_enabled() -> bool:
    """检查图片服务是否启用和可用"""
    try:
        from ..service_instances import get_ppt_service
        ppt_service = get_ppt_service()

        if not ppt_service.image_service or not ppt_service.image_service.initialized:
            return False

        from ..image.providers.base import provider_registry
        generation_providers = provider_registry.get_generation_providers(enabled_only=True)
        search_providers = provider_registry.get_search_providers(enabled_only=True)
        storage_providers = provider_registry.get_storage_providers(enabled_only=True)

        return bool(generation_providers or search_providers or storage_providers)
    except Exception:
        return False


class DesignPrompts:
    """PPT 设计提示词构建器。

    所有 _build_* 方法返回可嵌入的上下文片段；
    所有 get_* 方法返回完整的、可直接发送给 LLM 的提示词。
    """

    # ================================================================
    # 一、统一的上下文构建块（已合并精简）
    # ================================================================

    @staticmethod
    def _finalize_prompt(prompt: str, confirmed_requirements: Dict[str, Any] = None) -> str:
        return apply_page_number_prompt_filter(prompt, confirmed_requirements)

    # -- 单页生成器负责尺寸与布局，上游只提供视觉规范和表达意图 --
    @staticmethod
    def _build_canvas_system_context() -> str:
        return """
**固定画布系统**
- 1280×720 固定画布，无滚动条；使用 border-box，仅根容器与安全裁切层使用 overflow:hidden，不能靠裁切隐藏正文。
- 先确定主体的列宽，再估算文字换行、行高和高度；可用高度扣除实际锚点区、安全边距和间距。纵向堆叠计算高度总和，并列区域取各列高度的最大值，计入 padding、gap，为换行误差留余量。
- Flex/Grid 子项设置 min-width:0、min-height:0；由内容关系决定行列和对齐，不强制等高卡片或三段式骨架。
- 未指定字号时，正文优先 22–28px，辅助文字不低于 14px；正文不靠缩成小字来容纳内容。
- 内容少：放大核心文字或视觉主体，让内容组在可用区域内居中或围绕焦点布局；内容适中：用一个主视觉组织辅助信息。
- 内容多：先调整分组、列宽和版式，再压缩冗余表述，保留关键事实、数字及限定条件；不用 ellipsis / line-clamp 截断关键信息。
- 扩大外层容器不等于扩大主体。留白服务于焦点和阅读顺序，不设统一填充率或字数门槛；禁止为凑满页面编造事实、数字或例证。
""".strip()

    # -- 内容与设计质量（合并原先 content_quality + slide_generation_principles）--
    @staticmethod
    def _build_design_quality_context() -> str:
        return """
**内容与设计质量**
- 明确本页最值得记住的信息，围绕它安排视觉焦点和阅读顺序；按已有的流程、对比、主从等关系组织内容，不按要点数量机械套卡片。
- 保留原始事实和必要说明；图表、因果和对比关系必须有材料依据，不能把缺失信息补成事实。
- 同级元素保持标记一致，流程表达方向，指标保留单位和口径；装饰服务于信息层级。
""".strip()

    # -- 模板理解方向 --
    @staticmethod
    def _build_template_guidance_context() -> str:
        return """
**模板理解方向**
模板提供配色、字体、组件风格和稳定锚点；主体布局由本页内容决定，不照搬示例的内容密度、分栏或卡片数量。
""".strip()

    @staticmethod
    def _build_creative_direction_context() -> str:
        """Shared with the SVG prompt, whose generation contract stays separate."""
        return "先确定本页的核心信息和阅读顺序，再按已有信息关系选择构图。"

    # -- HTML输出格式 --
    @staticmethod
    def _build_html_output_context() -> str:
        return """
**输出格式**
只返回 ```html ... ``` 代码块，以 `<!DOCTYPE html>` 开始、`</html>` 结束，不附加解释。
""".strip()

    # -- 图片使用 --
    @staticmethod
    def _build_image_usage_context() -> str:
        return """
**图片使用**
图片服务于内容重点，不喧宾夺主。根据实际用途决定位置、裁切与样式，按需使用蒙版或边框。
""".strip()

    # -- 生成自检 --
    @staticmethod
    def _build_generation_self_check_context() -> str:
        return """
**输出前自检**
检查关键信息完整、文字可读且无越界遮挡；实际文字/图表/图片是否形成舒展的主体，而非内容挤在局部、外层空壳撑满。直接修正 HTML，无需输出检查报告或布局注释。
""".strip()

    # -- 资源可达性与性能约束（系统级，注入到关键 prompt 中）--
    @staticmethod
    def _build_resource_context() -> str:
        return SystemPrompts.get_resource_performance_prompt()

    @staticmethod
    def _build_design_system_spec(video_mode: bool = False) -> str:
        anchors = (
            "所有镜头共享标题、主图和字幕安全区锚点。"
            if video_mode else "普通内容页标题区的位置和预留空间；首尾页、目录页的例外。"
        )
        return f"""只输出以下五项，每项 1–2 行，总计不超过 500 字：
- palette：背景、正文、弱化文字、强调色，写出 CSS 色值及用途。
- typography：实际可用的字体栈；标题、正文、辅助文字的字号和行高，用 px/倍数表达。
  面向投影阅读选择字号，不机械照搬模板小字；默认正文 22–28px、辅助文字至少 14px。
- spacing：画布安全边距、常用间距，给出 px 值。
- anchors：{anchors}
- components：边框、圆角、材质等可复用特征，简短列出。
页码启用时，在 anchors 中补充页码位置；首页和尾页不显示页码。
从模板提取稳定值；未提供模板或未定义的值由你选择，并标记为默认值。未加载的字体使用系统字体栈。
只负责整套视觉规范，不指定单页分栏、卡片数量、模块高度或填充率，不复述布局原则。"""

    # ================================================================
    # 二、项目简报构建
    # ================================================================

    @staticmethod
    def _build_project_brief(confirmed_requirements: Dict[str, Any]) -> str:
        confirmed_requirements = confirmed_requirements or {}
        field_map = {
            '主题': confirmed_requirements.get('topic') or confirmed_requirements.get('title'),
            '项目类型': confirmed_requirements.get('type') or confirmed_requirements.get('scenario'),
            '使用场景': confirmed_requirements.get('scenario'),
            '目标受众': (confirmed_requirements.get('target_audience')
                         or confirmed_requirements.get('custom_audience')),
            '风格偏好': confirmed_requirements.get('ppt_style'),
            '自定义风格补充': confirmed_requirements.get('custom_style_prompt'),
        }
        lines = [f"- {k}：{v}" for k, v in field_map.items() if v]
        if is_video_explainer(confirmed_requirements):
            lines.append(
                "- 将每页设计成技术图解视频的一个镜头。底图和固定标题始终可见，画面留出字幕区。"
                "需要逐步揭示时，把新增的图元或连线标为 data-video-step=\"1\" 到 \"4\"，同组共用序号。"
                "每组可在首个元素标注 data-video-cue=\"对应的简短口播词\"，由视频录制器安排露出。"
                "HTML 本身保持所有图元可见以供静态阅读，避免另写自动播放脚本。"
            )
        return "\n".join(lines) if lines else "- 未提供项目背景，请根据内容自行建立设计主张。"

    @staticmethod
    def _build_slide_images_context(slide_data: Dict[str, Any]) -> str:
        if not (_is_image_service_enabled() and 'images_summary' in slide_data):
            return ""
        return f"\n\n{DesignPrompts._build_image_usage_context()}"

    @staticmethod
    def _build_template_html_context(template_html: str) -> str:
        return strip_base64_image_payloads_for_prompt(template_html or "")

    @staticmethod
    def _build_locked_zones_context(template_html: str, page_number: int,
                                     total_pages: int, slide_type: str,
                                     slide_title: str = "") -> str:
        is_first = page_number == 1
        is_last = page_number == total_pages
        is_catalog = slide_type in ("outline", "catalog", "directory", "agenda")
        if not is_catalog and slide_title:
            is_catalog = any(kw in slide_title for kw in ["目录", "大纲"])

        if is_first or is_last or is_catalog or not template_html:
            return ""

        return """
**稳定区域理解方向**
结合上方模板 HTML 原文，自行识别标题区、页码区和其他稳定锚点。
普通内容页更适合沿用这些区域的层级、位置关系和语气，只在主内容区重新组织信息。
""".strip()

    @staticmethod
    def _normalize_page_guidance_type(slide_data: Dict[str, Any], page_number: int,
                                       total_pages: int) -> str:
        slide_data = slide_data or {}
        title = str(slide_data.get("title") or "").strip()
        slide_type = str(slide_data.get("slide_type") or slide_data.get("type") or "").strip().lower()

        if page_number == 1:
            return "cover"
        if page_number == total_pages:
            return "ending"
        if slide_type in ("outline", "catalog", "directory", "agenda") or any(
            kw in title for kw in ["目录", "大纲"]
        ):
            return "catalog"
        if not slide_type or slide_type == "unknown":
            return "content"
        return slide_type

    @staticmethod
    def _get_page_guidance_type_label(guidance_type: str) -> str:
        label_map = {
            "cover": "首页/封面",
            "catalog": "目录/大纲",
            "transition": "章节过渡页",
            "ending": "结尾/感谢",
            "content": "普通内容页",
        }
        return label_map.get(guidance_type, f"{guidance_type} 类型页")

    @staticmethod
    def _build_page_type_guidance_overview(all_slides: list, total_pages: int) -> str:
        groups: Dict[str, Dict[str, Any]] = {}
        for idx in range(total_pages):
            page_number = idx + 1
            slide = (all_slides[idx] if all_slides and idx < len(all_slides) else {}) or {}
            guidance_type = DesignPrompts._normalize_page_guidance_type(slide, page_number, total_pages)
            title = str(slide.get("title") or f"第{page_number}页").strip()
            entry = groups.setdefault(guidance_type, {
                "label": DesignPrompts._get_page_guidance_type_label(guidance_type),
                "pages": [],
            })
            entry["pages"].append(f"第{page_number}页《{title}》")

        lines = []
        for guidance_type, entry in groups.items():
            pages = entry["pages"]
            pages_text = "、".join(pages[:6])
            if len(pages) > 6:
                pages_text += f" 等 {len(pages)} 页"
            lines.append(f"- TYPE: {guidance_type}（{entry['label']}）：{pages_text}")

        return "\n".join(lines) if lines else "- TYPE: content（普通内容页）：请结合完整大纲自行归纳。"

    # ================================================================
    # 三、三层架构提示词（Layer 1：全局视觉宪法）
    # ================================================================

    @staticmethod
    def get_global_visual_constitution_prompt(
        confirmed_requirements: Dict[str, Any],
        template_html: str, total_pages: int,
        first_slide_data: Dict[str, Any] = None,
    ) -> str:
        project_brief = DesignPrompts._build_project_brief(confirmed_requirements)
        template_context = DesignPrompts._build_template_html_context(template_html)

        prompt = f"""为一套 {total_pages} 页的 PPT 提炼一份紧凑的整套设计系统，供所有页面共享。

**项目简报**
{project_brief}

**参考模板 HTML 原文**
{template_context}

画布：1280×720。用户明确要求优先于模板示例。
{DesignPrompts._build_design_system_spec(is_video_explainer(confirmed_requirements))}"""
        return DesignPrompts._finalize_prompt(prompt, confirmed_requirements)

    # ================================================================
    # 四、Layer 2：页面类型指导
    # ================================================================

    @staticmethod
    def get_page_creative_briefs_prompt(
        confirmed_requirements: Dict[str, Any],
        all_slides: list, total_pages: int,
        global_constitution: str,
    ) -> str:
        project_brief = DesignPrompts._build_project_brief(confirmed_requirements)
        page_type_overview = DesignPrompts._build_page_type_guidance_overview(all_slides, total_pages)

        slides_lines = []
        for idx, slide in enumerate(all_slides or [], start=1):
            if not isinstance(slide, dict):
                continue
            title = str(slide.get("title") or f"第{idx}页").strip()
            slide_type = str(slide.get("slide_type") or slide.get("type") or "content").strip()
            points = slide.get("content_points") or slide.get("content") or []
            if isinstance(points, list):
                pts = "；".join(str(p).strip()[:50] for p in points[:5] if str(p).strip())
            else:
                pts = str(points).strip()[:100]
            line = f"{idx}. {title}（{slide_type}"
            if pts:
                line += f"；{pts}"
            line += "）"
            slides_lines.append(line)
        slides_detail = "\n".join(slides_lines) if slides_lines else "(无大纲数据)"

        prompt = f"""请为这套 {total_pages} 页 PPT 生成"页面类型指导"。

**项目简报**
{project_brief}

**全局视觉方向（已确定，优先对齐）**
{global_constitution}

**完整大纲**
{slides_detail}

**页面类型概览**
{page_type_overview}

**你的任务**
按页面类型归纳表达任务，同类型只输出一次，每种类型最多三行。
不重复视觉规范，不规定模块尺寸或默认卡片数量；具体布局由单页生成器决定。

请严格按以下结构输出，每种类型只输出一次，沿用上方概览里的 TYPE 键名：

## TYPE: cover
- 任务：这类页面应帮助观众理解什么。
- 焦点：应突出哪类已有信息，以及适用的信息关系。
- 节奏：与前后页如何呼应，哪些连续比较应保持一致。

首页、目录页、尾页属于特殊页面，可相对自由地处理锚点关系。
只输出页面类型指导，不附加解释。"""
        return DesignPrompts._finalize_prompt(prompt, confirmed_requirements)

    @staticmethod
    def get_composition_briefs_prompt(
        confirmed_requirements: Dict[str, Any], all_slides: list,
        total_pages: int, template_html: str = "",
    ) -> str:
        outline = json.dumps(all_slides, ensure_ascii=False, default=str)
        template = DesignPrompts._build_template_html_context(template_html)
        intent, relation, layout = (
            ("展示读到旧库存的矛盾", "库存接口与缓存之间的读取关系", "逐步展开同一张图")
            if is_video_explainer(confirmed_requirements)
            else ("开场介绍主题", "主题与副标题", "焦点排版")
        )
        return f"""为整套 {total_pages} 页 PPT 制定逐页构图计划，供后续并行生成使用。

项目简报：{DesignPrompts._build_project_brief(confirmed_requirements)}
完整大纲（按数组顺序对应从 1 开始的物理页码）：
{outline}
模板风格与边界参考：
{template}

先判断每页的表达意图与信息关系，再推荐构图；不要按要点数量机械套卡片。
流程、对比、主从、因果或数量关系必须来自大纲，不得推断不存在的关系或编造数据。
保持配色、字体和模板锚点一致；主内容区的变化服务于表达和整套阅读节奏。
相邻页面避免无理由地重复，但连续比较页可保持相同结构以方便比较。
layout_family 是建议，允许后续生成器根据实际内容调整，不是固定模板轮换表。
每个字段尽量只写一句具体建议，不重复配色、字体等整套视觉规范，不指定模块尺寸。
内容少可采用焦点构图和有意图的留白，不要求补字数、填充率或强制图表。
证据不足标记 missing_evidence，并在 intent 中指出缺口；保留已有内容，不补事实、不合并或增删页面。

只输出 JSON，slides 数组覆盖所有页面且页码唯一；每项包含 page 和 composition_brief。
composition_brief 的六个字段均为非空字符串：
- intent：页面意图，以及必要的证据缺口
- relation：内容之间已有的关系
- layout_family：推荐版式及如何呈现已有信息（流程、对比、焦点加证据、时间线、纯排版等）
- focal：第一视觉落点，引用当前页已有内容
- content_sufficiency：只选 sufficient（信息足够）、focus（适合简洁焦点页）、missing_evidence（缺证据）
- rhythm：与前后页的呼应、差异或保持一致的理由
格式示例：{{"slides":[{{"page":1,"composition_brief":{{"intent":"{intent}","relation":"{relation}","layout_family":"{layout}","focal":"本页标题","content_sufficiency":"focus","rhythm":"简洁开场，为后续展开建立节奏"}}}}]}}
"""

    # 向后兼容别名
    @staticmethod
    def get_page_plan_prompt(*args, **kwargs) -> str:
        return DesignPrompts.get_page_creative_briefs_prompt(*args, **kwargs)

    # ================================================================
    # 五、项目级与页面级设计指导
    # ================================================================

    @staticmethod
    def get_project_design_guide_prompt(
        confirmed_requirements: Dict[str, Any],
        slides_summary: str, total_pages: int,
        first_slide_data: Dict[str, Any] = None,
        template_html: str = "",
    ) -> str:
        project_brief = DesignPrompts._build_project_brief(confirmed_requirements)
        slides_summary = slides_summary or "(未提供大纲摘要)"
        template_context = DesignPrompts._build_template_html_context(template_html)

        prompt = f"""为整套 PPT 提炼共享设计系统；单页生成器负责具体构图。

**项目简报**
{project_brief}

**整套结构摘要**
{slides_summary}

**总页数**：{total_pages} 页

**模板 HTML 原文**
{template_context}

画布：1280×720。用户明确要求优先于模板示例。
{DesignPrompts._build_design_system_spec(is_video_explainer(confirmed_requirements))}"""
        return DesignPrompts._finalize_prompt(prompt, confirmed_requirements)

    @staticmethod
    def get_slide_design_guide_prompt(
        slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
        slides_summary: str, page_number: int, total_pages: int,
        template_html: str = "",
    ) -> str:
        project_brief = DesignPrompts._build_project_brief(confirmed_requirements)
        slides_summary = slides_summary or "(未提供大纲摘要)"
        images_context = DesignPrompts._build_slide_images_context(slide_data)
        template_context = DesignPrompts._build_template_html_context(template_html)

        prompt = f"""为第 {page_number} 页提供简短的表达意图，供单页生成器决定具体布局。

**项目简报**
{project_brief}

**整套结构摘要**
{slides_summary}

**当前页数据**
{slide_data}

**页面位置**：第 {page_number} 页 / 共 {total_pages} 页

**模板 HTML 原文**
{template_context}

{images_context}

最多输出四行，总计不超过 200 字：任务、关系、焦点、节奏，每行给出当前页特有的信息。
若已有 composition_brief，仅补充它未覆盖的必要说明，不重复计划；无必要补充时只写“无额外补充”。
关系和焦点必须来自本页材料；不能因为要点数量相同就套用等分卡片，也不能编造主次或数据。
不复述整套视觉规范，不规定字号、分栏、模块高度或填充率；这些由生成器结合实际换行决定。"""
        return DesignPrompts._finalize_prompt(prompt, confirmed_requirements)

    # ================================================================
    # 六、HTML 生成提示词（单页）
    # ================================================================

    @staticmethod
    def _build_slide_html_prompt(
        slide_data: Dict[str, Any], template_html: str, slide_title: str,
        slide_type: str, page_number: int, total_pages: int,
        project_brief: str, context_info: str, style_genes: str,
        global_constitution: str, current_page_brief: str,
    ) -> str:
        """Both HTML entry points share one contract; legacy genes are a fallback."""
        template_context = DesignPrompts._build_template_html_context(template_html)
        locked_zones = DesignPrompts._build_locked_zones_context(
            template_html, page_number, total_pages, slide_type, slide_title)
        design_system = (global_constitution or "").strip() or (style_genes or "").strip()
        if not design_system:
            design_system = "从模板提取配色、字体和稳定锚点；无模板时建立简洁一致的视觉规范。"
        brief_block = f"**页面表达补充**\n{current_page_brief}" if current_page_brief else ""
        images_info = ""
        if _is_image_service_enabled() and 'images_summary' in slide_data:
            images_info = DesignPrompts._build_image_usage_context()
        public_copy = json.dumps(audience_slide_copy(slide_data), ensure_ascii=False)
        internal_context = {
            key: value for key, value in slide_data.items()
            if key in {
                "production_notes", "composition_brief", "chart_config", "chart_data",
                "image_suggestions", "images_info", "images_summary", "layout",
            } and value
        }
        description = slide_data.get("description")
        if isinstance(description, str) and is_production_direction(description):
            internal_context["旧版绘图备注"] = description
        layout_data = json.dumps(internal_context, ensure_ascii=False, default=str)

        return f"""为第 {page_number} / {total_pages} 页生成完整 PPT HTML：{slide_title}（{slide_type}）。

**项目要求**
{project_brief}

**整套设计系统**
{design_system}

**模板 HTML 原文**
{template_context}
{DesignPrompts._build_template_guidance_context()}
{locked_zones}

**观众看到的内容**
{public_copy}

**仅供生成画面的制作备注**
{layout_data}
{images_info}
{brief_block}
{context_info}

**职责与取舍**
用户明确要求优先；整套设计系统负责视觉规范，composition_brief 负责本页意图、已有信息关系和跨页节奏，具体布局由你决定。版式建议可调整，关键事实不可丢失。
可见标题、图例、短标签和正文都来自观众内容及有材料依据的图表数据。把机制画出来，禁止把制作备注、提示词、
布局参数、绘制动作或推理过程转成任何观众可见的文字。图解节拍只用 HTML 属性表达。

{DesignPrompts._build_design_quality_context()}
{DesignPrompts._build_canvas_system_context()}
{DesignPrompts._build_resource_context()}
{DesignPrompts._build_generation_self_check_context()}
{DesignPrompts._build_html_output_context()}
"""

    @staticmethod
    def get_creative_template_context_prompt(
        slide_data: Dict[str, Any], template_html: str,
        slide_title: str, slide_type: str, page_number: int,
        total_pages: int, context_info: str, style_genes: str,
        project_topic: str = "",
        project_type: str = "", project_audience: str = "",
        project_style: str = "",
        global_constitution: str = "",
        current_page_brief: str = "",
        include_page_numbers: bool = True,
        content_mode: str = "presentation",
        custom_style_prompt: str = "",
    ) -> str:
        requirements = {
            "topic": project_topic,
            "type": project_type,
            "target_audience": project_audience,
            "ppt_style": project_style,
            "content_mode": content_mode,
            "custom_style_prompt": custom_style_prompt,
            "include_page_numbers": include_page_numbers,
        }
        prompt = DesignPrompts._build_slide_html_prompt(
            slide_data, template_html, slide_title, slide_type, page_number, total_pages,
            DesignPrompts._build_project_brief(requirements), context_info, style_genes,
            global_constitution, current_page_brief,
        )
        return DesignPrompts._finalize_prompt(prompt, requirements)

    @staticmethod
    def get_single_slide_html_prompt(
        slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
        page_number: int, total_pages: int, context_info: str,
        style_genes: str,
        template_html: str = "",
        global_constitution: str = "",
        current_page_brief: str = "",
    ) -> str:
        slide_type = slide_data.get("slide_type", "content")
        slide_title = slide_data.get("title", "")
        project_brief = DesignPrompts._build_project_brief(confirmed_requirements)
        if confirmed_requirements.get("description"):
            project_brief += f"\n- 补充：{confirmed_requirements['description']}"
        prompt = DesignPrompts._build_slide_html_prompt(
            slide_data, template_html, slide_title, slide_type, page_number, total_pages,
            project_brief, context_info, style_genes, global_constitution, current_page_brief,
        )
        return DesignPrompts._finalize_prompt(prompt, confirmed_requirements)

    # ================================================================
    # 七、辅助提示词
    # ================================================================

    @staticmethod
    def get_style_gene_extraction_prompt(template_code: str) -> str:
        template_context = DesignPrompts._build_template_html_context(template_code)

        return f"""请阅读模板 HTML，提炼可复用的视觉规范，作为缺少整套设计系统时的备用。

{template_context}

{DesignPrompts._build_design_system_spec()}"""

    @staticmethod
    def get_style_genes_extraction_prompt(template_code: str) -> str:
        """向后兼容别名"""
        return DesignPrompts.get_style_gene_extraction_prompt(template_code)

    @staticmethod
    def get_creative_variation_prompt(slide_data: Dict[str, Any], page_number: int,
                                       total_pages: int) -> str:
        return f"""请为当前页提供创意变化建议。

**页面数据**
{slide_data}

**页面位置**：第{page_number}页 / 共{total_pages}页

请输出：
1. 适合的变化方向
2. 可变化的元素（布局、焦点、背景等）
3. 需要保持不变的全局特征
4. 需要避免的雷同和过度设计

要求：变化服务内容，不要为变化而变化。"""

    @staticmethod
    def get_content_driven_design_prompt(slide_data: Dict[str, Any], page_number: int,
                                          total_pages: int) -> str:
        return f"""请根据当前页内容给出版式建议。

**页面数据**
{slide_data}

**页面位置**：第{page_number}页 / 共{total_pages}页

请输出：
1. 信息层级
2. 最合适的表达方式
3. 布局建议
4. 风险与取舍

要求：优先服务信息清晰度和阅读效率。"""

    @staticmethod
    def get_slide_context_prompt(
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        include_page_numbers: bool = True,
    ) -> str:
        slide_type = slide_data.get("slide_type", "")
        title = slide_data.get("title", "")
        is_catalog = (
            slide_type in ("outline", "catalog", "directory", "agenda")
            or any(kw in title for kw in ["目录", "大纲"])
        )

        if page_number == 1:
            prompt = """**特殊页面：首页/封面**
- 做出区别于普通内容页的开篇设计，建立强主焦点和开篇气场。
- 通常不显示页码，标题区和编号区可以更自由地处理。
- 应与后续内容页有明显视觉区别，作为整套 PPT 的开篇定调。
"""
        elif is_catalog:
            prompt = """**特殊页面：目录/大纲**
- 与普通内容页明显不同，核心是结构导航。
- 不显示页码，锚点可以自由设计。
- 章节关系、主次层级一眼可辨，与首页风格衔接。
"""
        elif str(slide_type).lower() == "transition":
            prompt = """**特殊页面：章节过渡页**
- 用于章节分隔和演示节奏控制，与普通内容页明显不同。
- 优先突出章节标题、短转场语和下一部分方向，不展开正文。
- 可以弱化页码和细节元素。
"""
        elif page_number == total_pages:
            prompt = """**特殊页面：结尾/感谢**
- 做出有收束感和仪式感的设计，与首页形成呼应。
- 通常不显示页码，锚点可以更自由地处理。
- 优先单一焦点和情绪收尾。
"""
        else:
            prompt = """**普通内容页**
- 标题区和页码区作为母板锚定区，创意主要发生在主内容区。
- 页码锚点优先跟随模板原有位置。
- 吸收页面指导的方向建议，但可根据内容自由选择实现方式。
- 在单一主任务前提下展开要点；信息已足够时优先精简或聚焦，而不是再叠加视觉模块。
"""
        return DesignPrompts._finalize_prompt(prompt, {"include_page_numbers": include_page_numbers})

    @staticmethod
    def get_combined_style_genes_and_guide_prompt(
        template_code: str, slide_data: Dict[str, Any],
        page_number: int, total_pages: int,
        include_page_numbers: bool = True,
    ) -> str:
        images_context = ""
        if _is_image_service_enabled() and 'images_summary' in slide_data:
            images_context = f"\n\n{DesignPrompts._build_image_usage_context()}"
        template_context = DesignPrompts._build_template_html_context(template_code)

        prompt = f"""请一次完成两件事，严格按标记输出。

**输入**
- 首页数据：{slide_data}
- 总页数：{total_pages}页{images_context}

**模板 HTML 原文**
{template_context}

**任务一：提炼设计基因**
画布：1280×720。
{DesignPrompts._build_design_system_spec()}

**任务二：生成通用设计指导**
最多三行说明开场、内容展开和收束的叙事节奏。不要重复任务一的视觉规范，具体构图交给单页生成器。

**输出格式**

===STYLE_GENES===
任务一结果
===END_STYLE_GENES===

===DESIGN_GUIDE===
任务二结果
===END_DESIGN_GUIDE===

不要输出其他说明。"""
        return DesignPrompts._finalize_prompt(prompt, {"include_page_numbers": include_page_numbers})
