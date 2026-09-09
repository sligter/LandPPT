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

    # -- 核心约束块（合并原先的 fixed_canvas_strategy + html_guardrails + layout_priority）--
    @staticmethod
    def _build_canvas_system_context() -> str:
        return """
**固定画布系统**
- 1280×720 外框约束先行；仅画布根容器与安全裁切层使用 overflow:hidden，不要给每个卡片默认 overflow:hidden；三段式骨架（页眉/主体/页脚），页眉页脚不可压缩。
- 先做高度预算再设计；间距用 gap/百分比/clamp()，避免大号固定 padding/margin 硬顶。
- 锚点区稳定，主内容区 flex:1 / grid minmax(0,1fr)，所有 flex/grid item 显式 min-height:0; min-width:0。
- 溢出时优先删减/分组/限高，不挤压锚点区；正文容器禁止用 ellipsis / line-clamp 截断关键信息，装不下就减字或改布局。
- 版面取舍：优先守住完整容纳和锚点稳定，再决定装饰强度与版式复杂度。

**高度分配与内容偏少处理**
- 主舞台可用 flex:1 占据剩余高度；但舞台内的内容卡片/步骤块/模块默认按内容定高，禁止被 stretch 成等高空壳。
- 禁止用 margin-top:auto 或 justify-content:space-between 把短文案与底部标签拉开制造中空。
- 多列卡片仅在每卡内容量接近且阅读关系适合时等高；不要因内容少就把所有模块缩在舞台顶部。
- 内容偏少时，先判断是否适合焦点式构图，再调整主体字号、尺度与位置，最后考虑将已有关系转成流程或示意图。
- 先安排主体与辅助信息的空间关系，再分配间距；不要靠扩大卡片、拉大间距或添加装饰填空。
- 留白应围绕焦点、分组或阅读动线；结论页和引言页可以简洁，不设统一填充率或字数门槛。
- 只有现有资料提供依据时才补充说明或绘制数据图表；禁止为凑满页面编造事实、数字或例证。
""".strip()

    # -- 内容与设计质量（合并原先 content_quality + slide_generation_principles）--
    @staticmethod
    def _build_design_quality_context() -> str:
        return """
**内容与设计质量**
- 信息密度与主题复杂度相称：先建立事实和层次，再加入装饰。
- 留白服务于分组和节奏，不替代内容；背景、数据、结论形成有区分度的前后层次。
- 先为页面建立清晰的第一视觉落点，再展开阅读动线。
- 通过分组、对比、层叠、方向变化或留白张力建立主次关系——即使内容项数量对等，也通过尺寸、位置、色彩重量的差异制造视觉层次。
- 当内容偏多时，优先换一种更合适的组织方式，再考虑压缩细节。

**组件一致性**
- 同级步骤/节点的标记形态统一：全数字，或「数字+同构小图标」；禁止同一序列内有的纯图标、有的纯数字。
- 全页只保留 1 个主强调（强调色或焦点卡）；次强调最多 1 处且视觉权重明显更弱。
- 一页只用一套编号体系；若必须并列两条序列，第二条改用不同标记形态（如 ①②③ 或 P1–P5）。
- 流程/流水线必须有方向信息（箭头、连接线或明确递进），禁止仅并列卡片。
- 指标数字带对比对象或口径（如「较 X 方案 ≈10×」），避免孤立的「更快更省」。
- 字体只写实际会生效的字体栈（系统字体或模板已提供的 @font-face），不写未加载的 web font 名。
""".strip()

    # -- 模板理解方向 --
    @staticmethod
    def _build_template_guidance_context() -> str:
        return """
**模板理解方向**
把模板 HTML 原文当作视觉母语和边界参考，优先继承其中稳定的配色、字体、材质、组件气质与锚点关系。
普通内容页更适合把变化放在主内容区，让标题区、页码区继续沿着模板里的结构与位置关系展开。
如果需要新的间距、体量或强调方式，尽量从模板原文和内容逻辑中推导，让结果既有变化也仍然像同一套设计系统。
""".strip()

    # -- 创意思考方向（正面引导替代禁令）--
    @staticmethod
    def _build_creative_direction_context() -> str:
        return """
**创意方向**
先明确这一页的核心任务（聚焦/展开/对比/总结/转场），再确定视觉重心和阅读路径，最后决定空间组织和装饰策略。
装饰和点缀放大构图，但不能替代构图。
""".strip()

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

    # -- 生成自检（精简为两个关键问题）--
    @staticmethod
    def _build_generation_self_check_context() -> str:
        return """
**输出前自检**
- 若提供 composition_brief，是否表达了其中的信息关系与视觉焦点？推荐版式可按内容调整，但不要退回无差别卡片排列。
- 主体是否过小或偏在局部？留白是否服务于当前页面意图，是否靠空心容器或装饰假装充实？
- 主内容区是否围绕当前页任务重新组织，而不是直接沿用模板骨架？
- 标题区、页码区等锚点是否来自模板原文，调整时能否在模板或内容逻辑中说清依据？
- 本页是否只有一条主叙事？是否出现两套相同编号体系（如两组 01–05）？
- 是否存在被 stretch 的空心卡片（短文案 + 底部标签 + 中间大片空白）？有则改为按内容定高。
- 同级步骤标记形态是否统一？流程是否有方向？主强调是否只有一个？
- CSS 中的字体是否都是系统字体或已实际加载的字体？
""".strip()

    # -- 版式工具箱（仅在 Layer 1/2 级别使用，单页生成不再注入）--
    @staticmethod
    def _build_layout_mastery_context() -> str:
        return """
**版式参考工具箱（帮助推理，不做硬性要求）**
- 栅格与空间：版心、天头/地脚、水槽、模块化栅格、分栏网格、基线网格、安全边界
- 视觉动线：古腾堡图表、F型、Z型、第一落幅/视觉锚点、引导线、格式塔分组
- 版式结构：三分法、非对称平衡、砌体/瀑布流、满版全画幅、对角线构图、黄金比例、时间线
- 对齐与微排版：悬挂缩进、孤寡行控制、视觉边界补偿、层级跃升
- 破局手法：破格、叠层、截断感、跨栏延展、留白张力、色彩重量倾斜
""".strip()

    # -- 资源可达性与性能约束（系统级，注入到关键 prompt 中）--
    @staticmethod
    def _build_resource_context() -> str:
        return SystemPrompts.get_resource_performance_prompt()

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

        prompt = f"""请为一套 {total_pages} 页的 PPT 输出"全局视觉宪法"——只定规则，不涉及任何具体页面的布局。

**项目简报**
{project_brief}

**参考模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}

{DesignPrompts._build_canvas_system_context()}

{DesignPrompts._build_layout_mastery_context()}

请按以下结构输出：

1. **整册视觉气质**
   - 核心风格方向、色彩策略、装饰语言
   - 首页与普通内容页的气质差异

2. **固定画布规则**
   - 1280×720 画布下的锚点预算策略
   - 首页和尾页不显示页码；其他页面的页码锚点规则

3. **给单页生成器的执行原则**
   - 涵盖：布局选择、层级建立、配色使用、内容版式组织、模板边界

要求：
- 只输出全局规则，不涉及具体某一页
- 规则要可执行，不要空泛形容
- 给出方向和关系，让单页生成器根据内容自行推导具体值

{DesignPrompts._build_resource_context()}"""
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

{DesignPrompts._build_layout_mastery_context()}

**你的任务**
按页面类型归纳指导，同类型只输出一次，共享方向、节奏和边界。
变化空间写进"节奏与变化"或"弹性调节"；用弹性表达给单页生成器留空间。
给出方向和关系而非具体数值。

请严格按以下结构输出，每种类型只输出一次，沿用上方概览里的 TYPE 键名：

## TYPE: cover
- **适用页面**：覆盖哪些页面
- **页面角色**：在整套 PPT 里的作用
- **设计概念**：适合的高级排版/信息设计方向
- **视觉焦点**：观众第一眼应该看到什么
- **构图倾向**：适合怎样的空间关系和主次节奏
- **节奏与变化**：同类型页面之间如何避免雷同
- **创意边界**：哪些克制，哪些可以大胆
- **弹性调节**：内容过多或过少时优先如何调整

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
格式示例：{{"slides":[{{"page":1,"composition_brief":{{"intent":"开场介绍主题","relation":"主题与副标题","layout_family":"焦点排版","focal":"本页标题","content_sufficiency":"focus","rhythm":"简洁开场，为后续展开建立节奏"}}}}]}}
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

        prompt = f"""请为整套 PPT 生成一份"项目级创意设计指导"。

输出全局可迁移的设计策略，而非某一页的局部答案。
先阅读模板 HTML 原文判断可继承的视觉边界，再定义整体气质，最后扩展为页面家族系统和跨页节奏。

**项目简报**
{project_brief}

**整套结构摘要**
{slides_summary}

**总页数**：{total_pages} 页

**模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}

{DesignPrompts._build_design_quality_context()}

{DesignPrompts._build_canvas_system_context()}

{DesignPrompts._build_layout_mastery_context()}

请按以下结构输出：

**A. 整体叙事与视觉主张**
**B. 模板继承边界与全局风格系统**
**C. 首页/封面首屏锚点策略**
**D. 跨页节奏与空间原则**
**E. 普通内容页与特殊页面的分工**
**F. 图像、图标与数据可视化原则**
**G. 风险与禁区**
**H. 给单页生成器的执行原则**

要求：
- 具体、专业、可操作，给出方向和关系而非固定数值
- 如果模板与项目语义冲突，说明如何受控修正
- 不要直接代写任何页面的 HTML

{DesignPrompts._build_resource_context()}"""
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

        prompt = f"""请为第 {page_number} 页生成"单页创意设计指导"。

延续整套风格，让当前页拥有明确角色和合适变化。聚焦当前页，不要写泛泛原则。

**项目简报**
{project_brief}

**整套结构摘要**
{slides_summary}

**当前页数据**
{slide_data}

**页面位置**：第 {page_number} 页 / 共 {total_pages} 页

**模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}

{DesignPrompts._build_design_quality_context()}

{DesignPrompts._build_canvas_system_context()}

{DesignPrompts._build_layout_mastery_context()}
{images_context}

**额外要求**
- 若当前页数据包含 composition_brief，先落实其中的页面意图、信息关系、焦点和跨页节奏；版式建议可按内容调整。
- 根据标题长度、要点数量、是否含图表/表格/时间线等，判断适合放大焦点、保持均衡还是压缩收敛
- 从版式工具箱中选择最合适的方法，转化为可执行建议
- 即使内容项数量对等，也主动建立视觉层次
- 给出方向和关系，让生成器根据内容自行推导

请按以下结构输出：

**A. 当前页角色判断**
**B. 视觉焦点与布局方向**（标题区、主体区、页码区的空间预算）
**C. 内容呈现策略**（内容偏少/适中/偏多时如何调节）
**D. 色彩、组件与图像处理**
**E. 与前后页面的呼应和差异化**
**F. 风险与避坑**

{DesignPrompts._build_resource_context()}"""
        return DesignPrompts._finalize_prompt(prompt, confirmed_requirements)

    # ================================================================
    # 六、HTML 生成提示词（单页）
    # ================================================================

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
    ) -> str:
        template_context = DesignPrompts._build_template_html_context(template_html)
        locked_zones = DesignPrompts._build_locked_zones_context(
            template_html, page_number, total_pages, slide_type, slide_title)
        images_info = ""
        if _is_image_service_enabled() and 'images_summary' in slide_data:
            images_info = "\n\n" + DesignPrompts._build_image_usage_context()

        constitution_block = f"**全局设计规则**\n{global_constitution}" if global_constitution else ""
        brief_block = f"**当前页面指导**\n{current_page_brief}" if current_page_brief else ""

        prompt = f"""为第{page_number}页生成完整 PPT HTML。

**核心目标**
把模板当作视觉语言系统来创作，而不是换字。主内容区围绕当前页使命重新建立空间秩序。

**页面信息**
- 标题：{slide_title}
- 类型：{slide_type}
- 第 {page_number} 页 / 共 {total_pages} 页

**页面数据**
{slide_data}{images_info}

**模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}
{locked_zones}

{DesignPrompts._build_design_quality_context()}

{DesignPrompts._build_creative_direction_context()}

**项目背景**
- 主题：{project_topic}
- 类型：{project_type}
- 受众：{project_audience}
- 风格：{project_style}

**设计基因**
{style_genes}

{constitution_block}
{brief_block}

{DesignPrompts._build_canvas_system_context()}

{context_info}

{DesignPrompts._build_generation_self_check_context()}

**富文本**
可按需使用 MathJax、Prism.js、Chart.js、ECharts.js、D3.js。

{DesignPrompts._build_resource_context()}

{DesignPrompts._build_html_output_context()}
"""
        return DesignPrompts._finalize_prompt(
            prompt,
            {"include_page_numbers": include_page_numbers},
        )

    @staticmethod
    def get_single_slide_html_prompt(
        slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
        page_number: int, total_pages: int, context_info: str,
        style_genes: str,
        template_html: str = "",
        global_constitution: str = "",
        current_page_brief: str = "",
    ) -> str:
        slide_type = slide_data.get("slide_type", "content") if isinstance(slide_data, dict) else "content"
        slide_title = slide_data.get("title", "") if isinstance(slide_data, dict) else ""
        template_context = DesignPrompts._build_template_html_context(template_html)
        locked_zones = DesignPrompts._build_locked_zones_context(
            template_html, page_number, total_pages, slide_type, slide_title)
        images_info = ""
        if _is_image_service_enabled() and 'images_summary' in slide_data:
            images_info = "\n\n" + DesignPrompts._build_image_usage_context()

        constitution_block = f"**全局设计规则**\n{global_constitution}" if global_constitution else ""
        brief_block = f"**当前页面指导**\n{current_page_brief}" if current_page_brief else ""

        prompt = f"""为第{page_number}页生成完整 HTML。

**核心目标**
把内容、模板语言和创意蓝图转译成一个成立的空间体验。

**项目信息**
- 主题：{confirmed_requirements.get('topic', '')}
- 受众：{confirmed_requirements.get('target_audience', '')}
- 补充：{confirmed_requirements.get('description', '无')}

**当前页面**
{slide_data}{images_info}

**模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}
{locked_zones}

{DesignPrompts._build_design_quality_context()}

{DesignPrompts._build_creative_direction_context()}

**设计基因**
{style_genes}

{constitution_block}
{brief_block}

{DesignPrompts._build_canvas_system_context()}

{context_info}

{DesignPrompts._build_generation_self_check_context()}

**富文本**
可按需使用 MathJax、Prism.js、Chart.js、ECharts.js、D3.js。

{DesignPrompts._build_resource_context()}

{DesignPrompts._build_html_output_context()}
"""
        return DesignPrompts._finalize_prompt(prompt, confirmed_requirements)

    # ================================================================
    # 七、辅助提示词
    # ================================================================

    @staticmethod
    def get_style_gene_extraction_prompt(template_code: str) -> str:
        template_context = DesignPrompts._build_template_html_context(template_code)

        return f"""请直接阅读以下模板 HTML 原文，提炼"可复用设计基因"。

{template_context}

请输出：
1. 色彩系统
2. 字体系统
3. 布局与间距特征
4. 组件与材质语言
5. 可复用倾向与边界

要求：尽量具体（可写 CSS 值、比例或关键词），聚焦稳定特征，不必复述源码。

{DesignPrompts._build_resource_context()}"""

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

{DesignPrompts._build_template_guidance_context()}

{DesignPrompts._build_design_quality_context()}

{DesignPrompts._build_canvas_system_context()}

{DesignPrompts._build_layout_mastery_context()}

**任务一：提炼设计基因**
只总结可跨页复用的稳定规则：色彩、字体、布局、组件/材质、约束。

**任务二：生成通用设计指导**
基于设计基因和首页信息，写出整套 PPT 的方向：
气质、页面家族、内容密度、图片/图表语气、固定画布限制。

**输出格式**

===STYLE_GENES===
任务一结果
===END_STYLE_GENES===

===DESIGN_GUIDE===
任务二结果
===END_DESIGN_GUIDE===

不要输出其他说明。

{DesignPrompts._build_resource_context()}"""
        return DesignPrompts._finalize_prompt(prompt, {"include_page_numbers": include_page_numbers})
