"""
PPT设计基因和视觉指导相关提示词
包含所有用于设计分析和视觉指导的提示词模板

"""

from typing import Dict, Any
import logging

from .system_prompts import SystemPrompts

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

        has_providers = (
            len(generation_providers) > 0
            or len(search_providers) > 0
            or len(storage_providers) > 0
        )

        logger.debug(
            f"Image service status: initialized={ppt_service.image_service.initialized}, "
            f"generation={len(generation_providers)}, search={len(search_providers)}, "
            f"storage={len(storage_providers)}"
        )
        return has_providers

    except Exception as e:
        logger.debug(f"Failed to check image service status: {e}")
        return False


class DesignPrompts:
    """PPT 设计提示词构建器。

    所有 _build_* 方法返回可嵌入的上下文片段；
    所有 get_* 方法返回完整的、可直接发送给 LLM 的提示词。
    """

    # ================================================================
    # 一、基础上下文构建块（Context Building Blocks）
    # ================================================================

    @staticmethod
    def _build_resource_performance_context() -> str:
        """资源与性能约束。"""
        return SystemPrompts.get_resource_performance_prompt()

    @staticmethod
    def _build_template_guidance_context() -> str:
        """模板使用方向：合并模板继承、变化、锚点和推导提示。"""
        return """
**模板理解与使用方向**
把模板 HTML 原文当作视觉母语和边界参考，优先继承其中更稳定的配色、字体、材质、组件气质与锚点关系。
普通内容页更适合把变化放在主内容区，让标题区、页码区和其他稳定区域继续沿着模板里的结构与位置关系展开。
分析模板时，先看它如何组织阅读顺序、重心和层级，再决定这一页怎样做同源变化，而不是先套版式名称。
如果需要新的间距、体量、图文比例或强调方式，尽量从模板原文和内容逻辑中推导，让结果既有变化，也仍然像同一套设计系统。
""".strip()

    @staticmethod
    def _build_creative_intent_context() -> str:
        """创意决策：引导思考顺序而非指定步骤。"""
        return """
**创意思考顺序**
先问这页要做什么（聚焦？展开？对比？总结？转场？），再问观众第一眼该看哪里、阅读路径怎么走。
然后才决定空间怎么切、元素怎么放。装饰和点缀最后考虑——它们放大构图，但不能替代构图。
""".strip()

    @staticmethod
    def _build_html_output_context() -> str:
        """HTML 输出格式要求。"""
        return """
**输出格式**
只返回 ```html ... ``` 代码块，以 `<!DOCTYPE html>` 开始、`</html>` 结束，不附加解释。
""".strip()

    @staticmethod
    def _build_image_usage_context() -> str:
        """图片使用原则。"""
        return """
**图片使用**
图片服务于内容重点，不喧宾夺主。根据实际用途决定位置、裁切与样式，按需使用蒙版或边框。
""".strip()

    @staticmethod
    def _build_content_quality_context() -> str:
        """内容充实度与设计丰富度（合并原来两个方法）。"""
        return """
**内容与设计质量**
- 让信息密度与主题复杂度相称，避免只剩标题和无效留白。
- 先补足事实、层次和结论，再决定是否增加装饰。
- 让留白服务于分组、节奏和呼吸感，而不是替代内容本身。
- 通过清晰的模块分隔和层级关系，帮助观众更顺畅地阅读。
- 让背景、数据和关键结论形成有区分度的前后层次。
- 避免把信息平均切成四宫格这类均质化结构；即使内容天然四等分，也应通过主次、轻重、大小、节奏或焦点转移建立层次差异。
""".strip()

    @staticmethod
    def _build_slide_generation_principles_context() -> str:
        """单页生成核心原则（用原则替代禁令清单）。"""
        return """
**生成方向**
- 先为页面建立清晰的第一视觉落点，再展开阅读动线。
- 通过分组、对比、层叠、方向变化或留白张力，让主次关系自然显现。
- 当内容容易变得平均时，优先调整空间关系，而不是把元素铺平摆齐。
- 避免默认落回四宫格、等宽等高卡片阵列这类均质化布局；即使四项内容完全对等，也不要做成均质排布，仍要主动制造视觉层次。
- 当内容偏多时，优先换一种更合适的组织方式，再考虑压缩细节。
- 让创意始终服务可读性、信息表达和实现稳定性。
""".strip()

    @staticmethod
    def _build_generation_self_check_context() -> str:
        """生成前自检（用问题替代规则）。"""
        return """
**输出前问自己**
- 主内容区是否真的围绕当前页任务重新组织，而不是直接沿用模板中段骨架？
- 标题区、页码区和稳定锚点是否仍然来自模板原文，而不是我临时发明的新规则？
- 当我调整间距、比例或强调方式时，能否在模板原文或内容逻辑里说清依据？
""".strip()

    # ================================================================
    # 二、固定画布相关（Canvas Constraints）
    # ================================================================

    @staticmethod
    def _build_fixed_canvas_strategy_context() -> str:
        """固定画布高层策略。"""
        return """
**固定画布策略**
- 放弃“由内容自然撑高页面”的网页思维，改为“由 1280x720 外框先约束、内容再适配”的组件思维。
- 优先采用三段式结构：页眉、主体、页脚明确分层；页眉页脚不能被压缩，主体区负责吸收剩余空间。
- 先做高度预算，再做视觉设计：Header + Main + Footer + Gap 必须控制在 720px 内，避免页脚被挤出或底部信息丢失。
- 间距优先使用 `gap`、百分比和 `clamp()`，不要依赖大号固定 `padding` 或 `margin` 去硬顶版面。
- 对图表、卡片组、日志窗、长列表、代码块等容易增高的模块，优先限制容器高度、减少列数、收紧装饰，再考虑缩小字号。
- 建立页脚安全区：页码、标识、品牌元素不要贴死边缘；必要时页脚可固定在底部，而主体区必须预留对应底部空间。
""".strip()

    @staticmethod
    def _build_fixed_canvas_html_guardrails() -> str:
        """固定画布 HTML 实现提醒。"""
        return """
**固定画布实现提醒**
- 让根容器保持 `1280×720` 并配合 `overflow:hidden`，更容易守住固定画布边界。
- 更适合把主内容区当作主要重构区，锚点区尽量沿用模板的容器层级和位置逻辑。
- 页码锚点优先跟随模板原有位置关系。
- 首页和尾页通常更适合弱化页码。

**骨架稳定性**
- 使用 flex 骨架时，让锚点区保持稳定，给主内容区留出可收缩空间。
- 使用 grid 骨架时，为主内容轨道预留真正可压缩的范围，避免轨道把内容顶出画布。
- 让 flex/grid item 具备可收缩的最小尺寸设置，便于处理复杂内容。

**溢出处理倾向**
- 长内容更适合优先删减、分组或限高，而不是挤压锚点区。
- 当锚点区开始越出画布边界，通常意味着需要回到骨架层重排。
- 尽量避免滚动条、锚点错位或内容被硬裁切。
""".strip()

    @staticmethod
    def _build_layout_priority_context() -> str:
        """版面优先级。"""
        return """
**版面取舍顺序**
优先守住 1280×720 内的完整容纳和锚点稳定，再决定装饰强度与版式复杂度。
内容偏多时，可以先从装饰、特效、间距和次要说明中回收空间，再考虑字号微调。
当布局被推到极限时，选择更简单的组织方式，通常比硬撑当前构图更稳。
""".strip()

    # ================================================================
    # 三、版式知识库（Layout Knowledge）
    # ================================================================

    @staticmethod
    def _build_layout_mastery_context() -> str:
        """高级版式方法库：显式提供布局推理工具箱。"""
        return """
**高级版式方法库（必须内化后使用，不要机械罗列术语）**
- 请把下面的方法当作“布局推理工具箱”，结合模板边界、页面目标、信息密度、受众气质和内容类型，主动选择最适合的版式策略。
- 输出时要把术语转化为可执行的排版判断，例如“采用 12 栏分栏网格，标题跨 8 栏，数据区占 4 栏”，而不是只写“使用分栏网格”。
- 可以混合使用多个方法，但必须明确主导策略、辅助策略，以及内容偏少、适中、偏多时各自如何调节。
- 任何出血、破格、叠层、截断、跨栏等高张力做法，都必须建立在版心、安全区、可读性和信息优先级稳定的前提下。

**一、栅格与空间体系（Grid & Spatial Systems）**
- 版心（Type Area / Live Area）：核心安全渲染区，主要文本和重要图表必须限制在版心内，绝不越界。
- 天头 / 地脚（Top Margin / Bottom Margin）：页面顶部与底部的边缘留白，在 PPT 中通常对应页眉与页脚的固定高度防线。
- 水槽 / 栏间距（Gutter）：相邻列或相邻卡片之间的水平或垂直间隙，决定页面的呼吸感。
- 模块化栅格（Modular Grid）：用纵横参考线切出等比矩形网格，适合展示同层级的大量卡片、图标矩阵、指标宫格，如 3x3、4x2。
- 分栏网格（Column Grid）：只在垂直方向划分栏数，如 12 栏、24 栏系统，适合文本主导页面做不对称切分，如左 4 栏、右 8 栏。
- 基线网格（Baseline Grid）：控制多行文本的底部对齐线，保证跨分栏文本仍具备稳定的纵向节律。
- 出血位（Bleed）：图片或色块故意突破版心直达屏幕边缘，用来制造空间延展感，例如全画幅背景图。
- 微观 / 宏观留白（Micro / Macro Whitespace）：微观留白管字距、行距、组件内间距；宏观留白管版块之间和版心四周的大面积空白。
- 安全边界缩进（Safe Zone Padding）：版心四周额外保留的绝对不可侵犯内边距，用于防止裁切和跨设备变形。

**二、视觉动线与阅读重心（Visual Flow & Reading Gravity）**
- 古腾堡图表 / 阅读重力（Gutenberg Diagram）：第一视觉落点通常在左上，最终停留在右下，重要内容应优先落在对角线关键区。
- F 型动线（F-Pattern）：适合文字密集页，要求左侧有稳定锚点，如项目符号、加粗小标题、编号体系。
- Z 型动线（Z-Pattern）：适合图文交替页，视线从左上到右上，再斜向左下，最后到右下，适合安排图文交错与 CTA 落点。
- 第一落幅 / 视觉锚点（Anchor Point / Primary Focal Point）：用户翻到页面第一眼锁定的元素，通常通过最大字号、最高对比度、最亮色块建立。
- 视觉流向引导（Leading Lines）：利用人物视线、手势、背景几何线条或容器延长线，把注意力指向核心文本区。
- 中心辐射动线（Radial Flow）：把核心信息放在中央，辅助信息环绕或发散，适合核心架构、总分模型、中心结论页。
- 格式塔分组（Gestalt Grouping）：利用亲密性原则，通过元素间距暗示内容关联度，减少多余分割线。

**三、版式结构与构图（Layout Structures & Composition）**
- 三分法则 / 九宫格构图（Rule of Thirds）：把焦点放在四个交叉点或其附近，让图表核心、人物视线、关键数据更自然稳定。
- 非对称平衡 / 动态平衡（Asymmetrical Balance）：左右元素体积不等，但通过色彩重量、信息密度、留白面积实现视觉平衡。
- 瀑布流 / 砌体布局（Masonry Layout）：卡片高度不一时采用交错排布，适合灵感板、案例集合、多维展示。
- 满版排版 / 全画幅（Full-Bleed Layout）：一张大图或大色块铺满页面，文字叠加在模糊蒙版或半透明遮罩上，营造沉浸感。
- 悬浮式排版 / 顶对齐结构（Canopy / Top-heavy Layout）：内容集中在页面中上部，下方留出大面积连续留白，形成轻盈、高级的呼吸感。
- 对角线构图（Diagonal Composition）：重要元素沿页面对角线分布，强化动态张力和速度感。
- 黄金比例分割（Golden Ratio Division, 1:1.618）：版面按约 3.8 : 6.2 切分主副区域，适合建立舒适而高级的主次关系。
- 仪表盘布局（Dashboard Layout）：把指标、结论、状态和摘要压缩进统一信息面板，适合总结页、结论页、经营分析页。
- 里程碑时间线（Milestone Timeline）：按时间或逻辑进程串联关键节点，适合路线图、发展脉络、阶段复盘。
- 沉浸式场景（Immersive Scene Layout）：以单一场景、大图或大色块建立空间包裹感，适合封面、展望页、情绪型结尾页。

**四、对齐、层级与微排版（Alignment, Hierarchy & Micro-typography）**
- 悬挂式缩进 / 凸排（Hanging Indent）：序号或项目符号悬挂在正文左侧之外，让正文形成绝对垂直对齐线。
- 孤行 / 寡行控制（Orphan / Widow Control）：禁止段落尾行只剩一个字，或上一组内容的最后一行孤立到下一组开头，可通过微调字距、文本框宽度强制换行。
- 视觉边界补偿（Optical Alignment / Margin Outset）：对引号、圆形图标、弱边缘元素做轻微外扩，让视觉上的左对齐更精准。
- 纵向节律 / 行高控制（Vertical Rhythm & Leading）：正文行高要与字号保持严格比例，如正文 1.5 倍、标题 1.2 倍，段间距通常为行高的 1.5 到 2 倍。
- 字偶间距调整（Kerning & Tracking）：大标题适当收紧字距增强整体性，小字号注释适当放宽字距提升可读性。
- 视觉层级跃升（Typographic Hierarchy Leap）：主标题与正文之间采用跨越式比例，如 48pt 直接跳到 16pt，制造强烈体积差。

**五、破局与张力制造（Breaking the Grid & Visual Tension）**
- 破格 / 破界排版（Breaking the Grid / Pop-out）：主图或核心数字故意突破卡片边界或栅格边界，制造视觉冲击。
- 叠层排版（Layering / Overlapping）：卡片与卡片、文字与图片发生交叠，并通过投影或层次关系拉开 Z 轴深度。
- 截断感排版（Cropping / Edge Bleeding）：把图片或超大字母故意切到屏幕边缘，暗示画面外仍有延展空间。
- 跨栏延展（Spanning）：在多栏系统中让关键元素横跨所有栏宽，强行打断阅读节奏，形成重音。
- 留白张力（Whitespace Tension）：把元素挤压到某个角落或边缘，留下巨大且不均等的负空间，形成现代感与压迫感。
- 色彩重量倾斜（Color Weight Shift）：用大面积深色或高饱和色块压住一侧，另一侧保持浅色或轻量内容，制造视觉失衡与吸引力。
- 底线对齐 / 沉底排版（Bottom-heavy Layout）：所有内容贴近页面下缘对齐，顶部大面积留空，适合表达基石、沉稳、落地感。
""".strip()

    # ================================================================
    # 四、模板解析工具（Template Analysis）
    # ================================================================

    @staticmethod
    def _build_project_brief(confirmed_requirements: Dict[str, Any]) -> str:
        """从需求中构建紧凑的项目简报。"""
        confirmed_requirements = confirmed_requirements or {}

        field_map = {
            '主题': confirmed_requirements.get('topic') or confirmed_requirements.get('title'),
            '项目类型': confirmed_requirements.get('type') or confirmed_requirements.get('scenario'),
            '使用场景': confirmed_requirements.get('scenario'),
            '目标受众': (
                confirmed_requirements.get('target_audience')
                or confirmed_requirements.get('custom_audience')
            ),
            '风格偏好': confirmed_requirements.get('ppt_style'),
            '自定义风格补充': confirmed_requirements.get('custom_style_prompt'),
        }

        lines = [f"- {k}：{v}" for k, v in field_map.items() if v]
        return "\n".join(lines) if lines else "- 未提供项目背景，请根据内容自行建立设计主张。"

    @staticmethod
    def _build_slide_images_context(slide_data: Dict[str, Any]) -> str:
        """仅当有图片输入时构建图片上下文。"""
        if not (_is_image_service_enabled() and 'images_summary' in slide_data):
            return ""
        return f"\n\n{DesignPrompts._build_image_usage_context()}"

    def _build_template_html_context(template_html: str) -> str:
        """模板 HTML 原样透传，不做截断、提取或兜底。"""
        return template_html or ""

    @staticmethod
    def _build_locked_zones_context(template_html: str, page_number: int,
                                     total_pages: int, slide_type: str,
                                      slide_title: str = "") -> str:
        """普通内容页给出稳定区域的理解方向，不解析模板 HTML。"""
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
    def _normalize_page_guidance_type(slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """将页面归一到可复用的页面类型，用于类型级指导。"""
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
        """将页面类型键映射为可读标签。"""
        label_map = {
            "cover": "首页/封面",
            "catalog": "目录/大纲",
            "ending": "结尾/感谢",
            "content": "普通内容页",
        }
        return label_map.get(guidance_type, f"{guidance_type} 类型页")

    @staticmethod
    def _build_page_type_guidance_overview(all_slides: list, total_pages: int) -> str:
        """构建页面类型概览，提示模型按类型输出指导。"""
        groups: Dict[str, Dict[str, Any]] = {}

        for idx in range(total_pages):
            page_number = idx + 1
            slide = (all_slides[idx] if all_slides and idx < len(all_slides) else {}) or {}
            guidance_type = DesignPrompts._normalize_page_guidance_type(slide, page_number, total_pages)
            title = str(slide.get("title") or f"第{page_number}页").strip()

            entry = groups.setdefault(
                guidance_type,
                {
                    "label": DesignPrompts._get_page_guidance_type_label(guidance_type),
                    "pages": [],
                },
            )
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
    # 五、三层架构提示词（Layer 1/2/3）
    # ================================================================

    @staticmethod
    def get_global_visual_constitution_prompt(confirmed_requirements: Dict[str, Any],
                                              template_html: str, total_pages: int,
                                              first_slide_data: Dict[str, Any] = None) -> str:
        """Layer 1: 全局视觉宪法——只定规则，不涉及具体页面。"""
        project_brief = DesignPrompts._build_project_brief(confirmed_requirements)
        template_context = DesignPrompts._build_template_html_context(template_html)
        resource_perf = DesignPrompts._build_resource_performance_context()

        return f"""请为一套 {total_pages} 页的 PPT 输出"全局视觉宪法"——只定规则，不涉及任何具体页面的布局。

**项目简报**
{project_brief}

**参考模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}

{DesignPrompts._build_fixed_canvas_strategy_context()}

请按以下结构输出：

1. **整册视觉气质**
   - 核心风格方向、色彩策略、装饰语言
   - 首页与普通内容页的气质差异

2. **固定画布规则**
   - 1280×720 画布下的锚点预算策略
   - 首页和尾页不显示页码
   - 其他页面的页码锚点规则

3. **给单页生成器的执行原则**
   - 涵盖：布局选择、层级建立、配色使用、内容版式组织、模板边界

{resource_perf}

要求：
- 只输出全局规则，不要涉及具体某一页
- 规则要可执行，不要空泛形容
- 不要给出具体像素值或固定比例数字，让单页生成器根据内容自行推导"""

    @staticmethod
    def get_page_creative_briefs_prompt(confirmed_requirements: Dict[str, Any],
                                        all_slides: list, total_pages: int,
                                        global_constitution: str) -> str:
        """Layer 2: 按页面类型输出页面指导——给方向感但不锁死版式。"""
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

        return f"""请为这套 {total_pages} 页 PPT 生成整套"页面类型指导"。

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
不要按页面逐页输出，而是按页面类型归纳指导。
同一种页面类型只输出一次，让同类页面共享方向、节奏、焦点和边界。
如果同类型页面之间仍需要变化，请把变化空间写进“节奏与变化”或“弹性调节”。
先从你自己的设计知识库里提炼一个更适合该类型页面的设计概念，再围绕它生成空间解法。
用“偏向、优先、可以考虑、适合”这类弹性表达，给单页生成器留自由空间。
不要输出 JSON、固定尺寸参数或查表式枚举。

请严格按以下结构输出，每种类型只输出一次，并沿用上方概览里的 `TYPE` 键名：

## TYPE: cover
- **适用页面**：这一类型覆盖哪些页面
- **页面角色**：这一类型页面在整套 PPT 里的作用
- **设计概念**：适合这一类型页面的高级排版/信息设计概念
- **视觉焦点**：观众第一眼应该看到什么
- **构图倾向**：适合怎样的空间关系和主次节奏
- **节奏与变化**：同类型页面之间可以如何避免雷同
- **创意边界**：哪些克制，哪些可以大胆
- **弹性调节**：内容过多或过少时优先如何调整

补充：
- 首页、目录页、尾页属于特殊页面，可相对自由地处理锚点关系。
- 更适合给出相对关系，而不是具体像素值或比例范围。
- 只输出页面类型指导，不附加解释。"""

    @staticmethod
    def get_page_plan_prompt(confirmed_requirements: Dict[str, Any],
                             all_slides: list, total_pages: int,
                             global_constitution: str) -> str:
        """向后兼容：旧接口转发到按页面类型输出的指导提示词。"""
        return DesignPrompts.get_page_creative_briefs_prompt(
            confirmed_requirements=confirmed_requirements,
            all_slides=all_slides,
            total_pages=total_pages,
            global_constitution=global_constitution,
        )

    # ================================================================
    # 六、项目级与页面级设计指导（Design Guides）
    # ================================================================

    @staticmethod
    def get_project_design_guide_prompt(confirmed_requirements: Dict[str, Any],
                                        slides_summary: str, total_pages: int,
                                        first_slide_data: Dict[str, Any] = None,
                                        template_html: str = "") -> str:
        """项目级创意设计指导。"""
        project_brief = DesignPrompts._build_project_brief(confirmed_requirements)
        slides_summary = slides_summary or "(未提供大纲摘要)"
        template_context = DesignPrompts._build_template_html_context(template_html)
        resource_perf = DesignPrompts._build_resource_performance_context()

        return f"""作为资深 PPT 创意总监，请为整套 PPT 生成一份"项目级创意设计指导"。

这份指导会被反复复用，因此输出全局可迁移的设计策略，而非某一页的局部答案。

**思考顺序**
1. 先直接阅读模板 HTML 原文，判断可继承的视觉边界和材质语言
2. 再为封面定义整体气质和布局锚点
3. 最后扩展为整套 PPT 的页面家族系统和跨页节奏

**项目简报**
{project_brief}

**整套结构摘要**
{slides_summary}

**总页数**：{total_pages} 页

**模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}

{DesignPrompts._build_content_quality_context()}

{DesignPrompts._build_fixed_canvas_strategy_context()}

{DesignPrompts._build_layout_priority_context()}

{DesignPrompts._build_layout_mastery_context()}

请按以下结构输出：

**A. 整体叙事与视觉主张**
**B. 模板继承边界与全局风格系统**
**C. 首页/封面首屏锚点策略**（明确哪些只属于首页）
**D. 跨页节奏与空间原则**（如何避免连续雷同）
**E. 普通内容页与特殊页面的分工**
**F. 图像、图标与数据可视化原则**
**G. 风险与禁区**
**H. 给单页生成器的执行原则**

要求：
- 具体、专业、可操作，避免空泛形容词
- 更适合给出相对关系，而不是具体像素值或固定版式方案
- 如果模板与项目语义冲突，说明如何受控修正
- 不要直接代写任何页面的 HTML

{resource_perf}"""

    @staticmethod
    def get_slide_design_guide_prompt(slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
                                      slides_summary: str, page_number: int, total_pages: int,
                                      template_html: str = "") -> str:
        """单页级创意设计指导。"""
        project_brief = DesignPrompts._build_project_brief(confirmed_requirements)
        slides_summary = slides_summary or "(未提供大纲摘要)"
        images_context = DesignPrompts._build_slide_images_context(slide_data)
        template_context = DesignPrompts._build_template_html_context(template_html)
        resource_perf = DesignPrompts._build_resource_performance_context()

        return f"""作为资深 PPT 页面设计师，请为第 {page_number} 页生成"单页创意设计指导"。

在延续整套风格的前提下，让当前页拥有明确角色和合适变化。聚焦当前页，不要写泛泛原则。

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

{DesignPrompts._build_content_quality_context()}

{DesignPrompts._build_fixed_canvas_strategy_context()}

{DesignPrompts._build_layout_priority_context()}

{DesignPrompts._build_layout_mastery_context()}

{images_context}

**额外要求**
- 根据标题长度、要点数量、是否含图表/表格/时间线等，判断适合放大焦点、保持均衡还是压缩收敛
- 从版式工具箱中选择最合适的方法，转化为可执行建议
- 明确避免推荐四宫格等均质化布局；即使当前页内容天然四等分且主次关系一致，也必须主动建立视觉层次，不能做成均质排布
- 更适合给出相对关系，让生成器根据内容自行推导

请按以下结构输出：

**A. 当前页角色判断**
**B. 视觉焦点与布局方向**（标题区、主体区、页码区的空间预算）
**C. 内容呈现策略**（内容偏少/适中/偏多时如何调节）
**D. 色彩、组件与图像处理**
**E. 与前后页面的呼应和差异化**
**F. 风险与避坑**

{resource_perf}"""

    # ================================================================
    # 七、HTML 生成提示词（Slide Generation）
    # ================================================================

    @staticmethod
    def get_creative_template_context_prompt(slide_data: Dict[str, Any], template_html: str,
                                           slide_title: str, slide_type: str, page_number: int,
                                           total_pages: int, context_info: str, style_genes: str,
                                           project_topic: str = "",
                                           project_type: str = "", project_audience: str = "",
                                           project_style: str = "",
                                           global_constitution: str = "",
                                           current_page_brief: str = "") -> str:
        """创意模板上下文 HTML 生成提示词。"""
        template_context = DesignPrompts._build_template_html_context(template_html)
        locked_zones = DesignPrompts._build_locked_zones_context(
            template_html, page_number, total_pages, slide_type, slide_title)
        images_info = ""
        if _is_image_service_enabled() and 'images_summary' in slide_data:
            images_info = "\n\n" + DesignPrompts._build_image_usage_context()
        resource_perf = DesignPrompts._build_resource_performance_context()

        # 条件性地加入指导上下文
        constitution_block = f"**全局设计规则**\n{global_constitution}" if global_constitution else ""
        brief_block = f"**当前页面指导**\n{current_page_brief}" if current_page_brief else ""

        return f"""为第{page_number}页生成完整 PPT HTML。

**核心目标**
把模板当作视觉语言系统来创作，而不是换字。主内容区更适合围绕当前页使命重新建立空间秩序。
如果结果看起来接近"模板换字"，回到主内容区重新组织。

**页面信息**
- 标题：{slide_title}
- 类型：{slide_type}
- 第 {page_number} 页 / 共 {total_pages} 页

**页面数据**
{slide_data}
{images_info}

**模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}

{locked_zones}

{DesignPrompts._build_content_quality_context()}

{DesignPrompts._build_creative_intent_context()}

**项目背景**
- 主题：{project_topic}
- 类型：{project_type}
- 受众：{project_audience}
- 风格：{project_style}

**设计基因**
{style_genes}

{constitution_block}

{brief_block}

{DesignPrompts._build_fixed_canvas_html_guardrails()}

{DesignPrompts._build_layout_priority_context()}

{context_info}

{DesignPrompts._build_slide_generation_principles_context()}

{DesignPrompts._build_generation_self_check_context()}

**富文本**
可按需使用 MathJax、Prism.js、Chart.js、ECharts.js、D3.js。

{resource_perf}

{DesignPrompts._build_html_output_context()}
"""

    @staticmethod
    def get_single_slide_html_prompt(slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
                                   page_number: int, total_pages: int, context_info: str,
                                   style_genes: str,
                                   template_html: str = "",
                                   global_constitution: str = "",
                                   current_page_brief: str = "") -> str:
        """单页 HTML 生成提示词。"""
        slide_type = slide_data.get("slide_type", "content") if isinstance(slide_data, dict) else "content"
        slide_title = slide_data.get("title", "") if isinstance(slide_data, dict) else ""
        template_context = DesignPrompts._build_template_html_context(template_html)
        locked_zones = DesignPrompts._build_locked_zones_context(
            template_html, page_number, total_pages, slide_type, slide_title)
        images_info = ""
        if _is_image_service_enabled() and 'images_summary' in slide_data:
            images_info = "\n\n" + DesignPrompts._build_image_usage_context()
        resource_perf = DesignPrompts._build_resource_performance_context()

        constitution_block = f"**全局设计规则**\n{global_constitution}" if global_constitution else ""
        brief_block = f"**当前页面指导**\n{current_page_brief}" if current_page_brief else ""

        return f"""为第{page_number}页生成完整 HTML。

**核心目标**
把内容、模板语言和创意蓝图转译成一个成立的空间体验。
如果结果看起来接近"模板换字"，回到主内容区重新组织。

**项目信息**
- 主题：{confirmed_requirements.get('topic', '')}
- 受众：{confirmed_requirements.get('target_audience', '')}
- 补充：{confirmed_requirements.get('description', '无')}

**当前页面**
{slide_data}
{images_info}

**模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}

{locked_zones}

{DesignPrompts._build_content_quality_context()}

{DesignPrompts._build_creative_intent_context()}

**设计基因**
{style_genes}

{constitution_block}

{brief_block}

{DesignPrompts._build_fixed_canvas_html_guardrails()}

{DesignPrompts._build_layout_priority_context()}

{context_info}

{DesignPrompts._build_slide_generation_principles_context()}

{DesignPrompts._build_generation_self_check_context()}

**富文本**
可按需使用 MathJax、Prism.js、Chart.js、ECharts.js、D3.js。

{resource_perf}

{DesignPrompts._build_html_output_context()}
"""

    # ================================================================
    # 八、辅助提示词（Utility Prompts）
    # ================================================================

    @staticmethod
    def get_style_gene_extraction_prompt(template_code: str) -> str:
        """设计基因提取提示词。"""
        template_context = DesignPrompts._build_template_html_context(template_code)
        resource_perf = DesignPrompts._build_resource_performance_context()

        return f"""请直接阅读以下模板 HTML 原文，提炼"可复用设计基因"。

{template_context}

请输出：
1. 色彩系统
2. 字体系统
3. 布局与间距特征
4. 组件与材质语言
5. 可复用倾向与边界

要求：尽量具体（可写 CSS 值、比例或关键词），聚焦稳定特征，不必复述源码。

{resource_perf}"""

    @staticmethod
    def get_style_genes_extraction_prompt(template_code: str) -> str:
        """向后兼容别名。"""
        return DesignPrompts.get_style_gene_extraction_prompt(template_code)

    @staticmethod
    def get_creative_variation_prompt(slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """创意变化指导提示词。"""
        return f"""请为当前页提供创意变化建议。

**页面数据**
{slide_data}

**页面位置**：第{page_number}页 / 共{total_pages}页

请输出：
1. 适合的变化方向
2. 可变化的元素（布局、焦点、背景等）
3. 需要保持不变的全局特征
4. 需要避免的雷同和过度设计

要求：变化服务内容，不要为变化而变化。不要推荐海外外链资源。"""

    @staticmethod
    def get_content_driven_design_prompt(slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """内容驱动设计建议提示词。"""
        return f"""请根据当前页内容给出版式建议。

**页面数据**
{slide_data}

**页面位置**：第{page_number}页 / 共{total_pages}页

请输出：
1. 信息层级
2. 最合适的表达方式
3. 布局建议
4. 风险与取舍

要求：优先服务信息清晰度和阅读效率。不要推荐海外外链资源。"""

    @staticmethod
    def get_slide_context_prompt(slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """幻灯片上下文提示词（特殊页面 vs 普通页面）。"""
        slide_type = slide_data.get("slide_type", "")
        title = slide_data.get("title", "")

        is_catalog = (
            slide_type in ("outline", "catalog", "directory", "agenda")
            or any(kw in title for kw in ["目录", "大纲"])
        )

        # --- 特殊页面 ---
        if page_number == 1:
            return """**特殊页面：首页/封面**
- 更适合做出区别于普通内容页的开篇设计。
- 通常不显示页码，标题区和编号区可以更自由地处理。
- 建立强主焦点和开篇气场，标题是绝对焦点。
- 应与后续内容页有明显视觉区别，作为整套 PPT 的开篇定调。
"""

        if is_catalog:
            return """**特殊页面：目录/大纲**
- 属于特殊页面，需要与普通内容页明显不同。
- 不显示页码，锚点可以自由设计。
- 核心是结构导航：章节关系、主次层级一眼可辨。
- 与首页风格衔接，作为从开篇到正文的过渡。
"""

        if page_number == total_pages:
            return """**特殊页面：结尾/感谢**
- 更适合做出有收束感和仪式感的设计，与首页形成呼应。
- 通常不显示页码，锚点可以更自由地处理。
- 优先单一焦点和情绪收尾，与首页在气质上形成闭环。
"""

        # --- 普通内容页 ---
        return """**普通内容页**
        - 标题区和页码区为母板锚定区，创意主要发生在主内容区。
        - 页码锚点优先跟随模板原有位置。
        - 吸收页面指导的方向建议，但可根据内容自由选择实现方式。
        - 每个要点展开为完整信息单元，组合多种视觉手法，避免纯文本。
"""

    @staticmethod
    def get_combined_style_genes_and_guide_prompt(template_code: str, slide_data: Dict[str, Any],
                                                  page_number: int, total_pages: int) -> str:
        """合并的设计基因 + 统一设计指导（单次 LLM 调用）。

        输出用分隔标记分开：
        - ===STYLE_GENES=== / ===END_STYLE_GENES===
        - ===DESIGN_GUIDE=== / ===END_DESIGN_GUIDE===
        """
        images_context = ""
        if _is_image_service_enabled() and 'images_summary' in slide_data:
            images_context = f"\n\n{DesignPrompts._build_image_usage_context()}"
        template_context = DesignPrompts._build_template_html_context(template_code)
        resource_perf = DesignPrompts._build_resource_performance_context()

        return f"""请一次完成两件事，严格按标记输出。

**输入**
- 首页数据：{slide_data}
- 总页数：{total_pages}页
{images_context}

**模板 HTML 原文**
{template_context}

{DesignPrompts._build_template_guidance_context()}

{DesignPrompts._build_content_quality_context()}

{DesignPrompts._build_fixed_canvas_strategy_context()}

{DesignPrompts._build_layout_priority_context()}

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

{resource_perf}"""
