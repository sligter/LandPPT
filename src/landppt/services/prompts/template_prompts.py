"""
模板生成相关提示词

职责：
- 集中维护 HTML PPT 母版生成的通用约束
- 组装自由模板的项目专属上下文
"""

from typing import Any, Dict, List

from .system_prompts import SystemPrompts
from .prompt_utils import apply_page_number_prompt_filter


class TemplatePrompts:
    """模板生成提示词构建器。"""

    @staticmethod
    def build_video_explainer_template_prompt(
        project: Any,
        outline: Dict[str, Any],
        requirements: Dict[str, Any],
    ) -> str:
        slides = outline.get("slides", [])
        topic = getattr(project, "topic", "") or outline.get("title", "")
        style = requirements.get("custom_style_prompt") or "浅暖底色、石墨色字、低饱和青蓝细线"
        audience = requirements.get("target_audience", "")
        return f"""为技术图解视频制作一张可复用的 1280×720 镜头母版。

主题：{topic}
受众：{audience}
设计要求：{style}
镜头顺序：
{TemplatePrompts._build_compact_outline_summary(slides)}

每个镜头共享固定标题锚点和尽可能大的连续图解区。底部留出约 15% 的字幕安全区。
让图中的对象、标签和连线承载叙事，母版只提供底色、字号、色板和间距。省去页码、横幅、徽章与装饰区块。
输出自包含的 HTML 和 CSS，根容器使用 position:relative 和 overflow:hidden。
标题和图解区分别使用 `{{{{ page_title }}}}` 和 `{{{{ page_content }}}}` 占位，只放一份，不写示例文案或模板控制语法。
只输出 HTML 代码块。"""

    @staticmethod
    def build_outline_slide_lines(slides: List[Dict[str, Any]]) -> List[str]:
        """从大纲中提取少量摘要行，用于感知内容类型。"""
        slide_lines: List[str] = []
        for idx, slide in enumerate(slides[:3], start=1):
            if not isinstance(slide, dict):
                continue

            title = slide.get("title") or f"第{idx}页"
            slide_type = slide.get("slide_type") or slide.get("type") or ""
            points = slide.get("content_points") or slide.get("content") or []

            if isinstance(points, list):
                points = [str(item) for item in points[:4]]
                points_text = "；".join([item for item in points if item])
            else:
                points_text = str(points)[:120]

            extra = f"（{slide_type}）" if slide_type else ""
            slide_lines.append(f"{idx}. {title}{extra}：{points_text}".strip("："))

        return slide_lines

    # ------------------------------------------------------------------
    # 大纲分析辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_compact_outline_summary(slides: List[Dict[str, Any]]) -> str:
        """全部幻灯片的紧凑摘要，每页一行：序号. 标题（类型）。"""
        lines: List[str] = []
        for idx, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict):
                continue
            title = slide.get("title") or f"第{idx}页"
            slide_type = slide.get("slide_type") or slide.get("type") or ""
            tag = f"（{slide_type}）" if slide_type else ""
            lines.append(f"{idx}. {title}{tag}")
        return "\n".join(lines) if lines else "(暂无大纲)"

    @staticmethod
    def _build_slide_type_distribution(slides: List[Dict[str, Any]]) -> str:
        """统计页面类型分布，如 '封面1页 / 内容8页 / 结尾1页'。"""
        type_labels = {
            "cover": "封面", "title": "封面",
            "catalog": "目录", "outline": "目录", "directory": "目录", "agenda": "目录",
            "ending": "结尾", "thankyou": "结尾", "conclusion": "结尾",
        }
        counts: Dict[str, int] = {}
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            raw = (slide.get("slide_type") or slide.get("type") or "content").strip().lower()
            label = type_labels.get(raw, "内容")
            counts[label] = counts.get(label, 0) + 1
        if not counts:
            return "暂无"
        return " / ".join(f"{label}{n}页" for label, n in counts.items())

    @staticmethod
    def _build_narrative_arc_summary(slides: List[Dict[str, Any]]) -> str:
        """从幻灯片标题序列推导一句话叙事弧线。"""
        titles = []
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            t = slide.get("title") or ""
            if t:
                titles.append(t)
        if len(titles) <= 2:
            return ""
        mid_count = len(titles) - 2
        mid_preview = "→".join(titles[1:4]) if mid_count <= 3 else f"{'→'.join(titles[1:3])}→…→{titles[-2]}"
        return f"{titles[0]} → {mid_preview} → {titles[-1]}"

    @staticmethod
    def build_free_template_user_prompt(
        project: Any,
        outline: Dict[str, Any],
        confirmed: Dict[str, Any],
    ) -> str:
        """构建自由模板的项目专属需求，提供丰富的项目上下文和创意催化。"""
        slides = outline.get("slides", []) if isinstance(outline, dict) else []

        topic = getattr(project, "topic", "") or outline.get("title") or ""
        scenario = getattr(project, "scenario", "") or confirmed.get("scenario", "")
        target_audience = confirmed.get("target_audience") or ""
        ppt_style = confirmed.get("ppt_style") or ""
        custom_style_prompt = confirmed.get("custom_style_prompt") or ""
        description = confirmed.get("description") or ""
        requirements = confirmed.get("requirements") or ""
        focus_content = confirmed.get("focus_content") or []
        if isinstance(focus_content, list):
            focus_content = "、".join(str(item) for item in focus_content if item)

        prompt_parts = [
            "===== 项目信息 =====",
            f"主题：{topic}" if topic else "",
            f"场景：{scenario}" if scenario else "",
            f"受众：{target_audience}" if target_audience else "",
            f"风格偏好：{ppt_style}" if ppt_style else "",
            f"自定义风格补充：{custom_style_prompt}" if custom_style_prompt else "",
            f"项目说明：{description}" if description else "",
            f"内容重点：{focus_content}" if focus_content else "",
            f"补充要求：{requirements}" if requirements else "",
        ]

        prompt_parts.append("")
        prompt_parts.append(
            TemplatePrompts.get_template_atmosphere_prompt_text(
                topic=topic, scenario=scenario,
                target_audience=target_audience, ppt_style=ppt_style,
            )
        )

        total_pages = len(slides)
        type_dist = TemplatePrompts._build_slide_type_distribution(slides)
        arc = TemplatePrompts._build_narrative_arc_summary(slides)
        compact_outline = TemplatePrompts._build_compact_outline_summary(slides)

        prompt_parts.append("")
        prompt_parts.append("===== 大纲全貌（用于推导内容节奏与视觉密度变化） =====")
        prompt_parts.append(f"总页数：{total_pages}")
        prompt_parts.append(f"页面类型分布：{type_dist}")
        if arc:
            prompt_parts.append(f"叙事弧线：{arc}")
        prompt_parts.append(compact_outline)

        topic_label = topic or "本项目"
        prompt_parts.append("")
        prompt_parts.append("===== 自由模板设计方向 =====")
        prompt_parts.append(
            f"- 这是为「{topic_label}」量身定制的视觉系统，不是换了标题的通用商务皮肤。"
        )
        prompt_parts.append(
            f"- 思考：什么视觉隐喻最能传达「{topic_label}」的本质？将它编码为跨页复现的设计语汇。"
        )
        prompt_parts.append(
            "- 生成一个通用单页母版，不为封面、目录、过渡、内容、标题、结尾分别输出变体。"
        )
        prompt_parts.append(
            "- 如果项目信息不足以建立强方向，从大纲的叙事弧线和内容类型中主动推导视觉主张。"
        )

        prompt = "\n".join([part for part in prompt_parts if part]).strip()
        return apply_page_number_prompt_filter(prompt, confirmed)

    # ------------------------------------------------------------------
    # 角色定义与创意催化
    # ------------------------------------------------------------------

    @staticmethod
    def _get_role_framing() -> str:
        """附带创意方法论的角色定义。"""
        return """你是一位以「场所精神」为理念的视觉系统建筑师。
你的工作不是排版，而是为一个主题建造它专属的视觉世界。

你的设计方法论：
1. 先感受——这个主题让人联想到什么材质、光线、空间气质？
2. 再提炼——从联想中提取可编码为 CSS 的设计语汇（色彩、字体气质、几何语言、空间节奏）。
3. 然后构建——将语汇编织成一套母版系统：稳定的锚点让人安心，灵活的主舞台让内容呼吸。
4. 最后检验——这套系统能否让 10+ 页内容各不相同却一眼同源？

你要交付的是一个**通用单页母版**——一个 HTML 文件中只包含一个可复用的 1280×720 页面模板，形成稳定、可持续复用的视觉系统。"""

    @staticmethod
    def get_template_atmosphere_prompt_text(
        topic: str = "", scenario: str = "",
        target_audience: str = "", ppt_style: str = "",
    ) -> str:
        """根据主题信息动态生成氛围感知问题，引导模型建立情绪基调和视觉隐喻。"""
        parts = ["===== 氛围感知（在写代码前先回答） ====="]

        questions: List[str] = []
        topic_label = topic or "这个主题"
        questions.append(f"如果「{topic_label}」是一个物理空间，它的光线、材质和温度是什么样的？")
        questions.append("这套演示的情绪基调应该是什么？（庄重 / 轻快 / 前卫 / 温暖 / 沉浸 / 其他）")
        questions.append(
            f"什么视觉隐喻最能代表「{topic_label}」的内在逻辑？"
            "（例如：数据流、年轮、星图、积木、水墨、晶格……）"
        )
        questions.append("什么色彩组合能同时传递专业感和这个主题独有的情绪？")
        if scenario:
            questions.append(
                f"在「{scenario}」场景下，演示者和观众之间的关系如何？这种关系应该反映在视觉节奏上吗？"
            )
        if target_audience:
            questions.append(
                f"面向「{target_audience}」，视觉系统应该偏向哪种气质——权威、亲和、激励、沉浸？"
            )

        for i, q in enumerate(questions, 1):
            parts.append(f"{i}. {q}")

        parts.append("")
        parts.append(
            "将你的回答内化为设计决策的依据——不需要在输出中写出答案，"
            "但每一个配色、字体、几何图形和空间关系的选择都应该能追溯到这些问题。"
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 资源与画布护栏
    # ------------------------------------------------------------------

    @staticmethod
    def get_template_resource_performance_prompt_text() -> str:
        """统一模板生成阶段的资源可达性与性能约束。"""
        return SystemPrompts.get_resource_performance_prompt()

    @staticmethod
    def get_template_annotation_prompt_text() -> str:
        """固定画布与单页母版职责分层提示。"""
        return """
**母版/设计系统骨架**
- 只生成一个 1280×720 的通用页面模板，不输出多页面类型变体。
- 画布根容器负责 `position:relative` 与 1280×720 裁切，整个页面不允许出现滚动条。
- 模板内部建立标题锚点区、主舞台区、编号锚点区三类职责层；编号锚点可以 `absolute` 脱流，也可以嵌入稳定容器。
- 页码结构必须兼容“页码 absolute 脱离文档流 + 内容层预留安全区”的固定画布骨架。
- 如果使用纵向 `flex` 骨架，标题锚点和编号锚点 `flex:none`，主舞台 `flex:1; min-height:0; min-width:0; overflow:hidden`。
- 如果使用 `grid` 骨架，主舞台轨道写成 `minmax(0,1fr)`。
- 所有承载正文的 flex/grid item 显式写 `min-height:0; min-width:0`。
- 主舞台可占满剩余高度，但舞台内的内容模块按内容定高，不被 stretch 成等高空壳。
- 内容较少时的气场靠放大焦点字号、加强主视觉、加大模块间距，而非纵向拉满；内容较多时不能崩坏。
- 类名仅用于说明结构关系，使用 inline style 做等价实现同样有效。
""".strip()

    # ------------------------------------------------------------------
    # 创意与方法
    # ------------------------------------------------------------------

    @staticmethod
    def get_template_generation_creative_prompt_text() -> str:
        """母版创意愿景，以正面驱动替代负面禁令。"""
        return """
**创意愿景——单页母版**
- 在一个 HTML 文件中只输出一个通用页面模板，形成可复用的视觉语言系统。
- 模板需要兼容封面、目录、过渡、内容、标题、结尾等不同实际页面的内容替换，但不要分别生成页面类型变体。
- 从主题内涵中提取视觉隐喻，让配色、几何语言和空间节奏都有"为什么是这样"的理由。
- 标题区是性格表达——用排版、字重、装饰元素赋予它辨识度，让它成为整套系统的签名。
- 用稳定的标题锚点、主舞台和编号锚点承载不同内容密度，让单个模板在多页复用时仍有空间弹性。
- 克制胜于堆叠：一个精准的视觉隐喻胜过三个并列的装饰效果。
""".strip()

    @staticmethod
    def get_template_generation_method_prompt_text() -> str:
        """模板创作过程，以创意思考驱动而非工程流水线。"""
        return """
**创作过程**
1. 感知 — 阅读项目信息和大纲全貌，感受这个主题的情绪重心、节奏和内在张力。
2. 提炼视觉主张 — 用一句话定义这套母版的灵魂（例如："用数据流的透明层叠感传递 AI 的理性与可能性"）。
3. 建立设计语汇 — 从视觉主张推导出：核心色彩逻辑、字体性格组合、标志性几何语言、空间节奏策略。
4. 构建系统骨架 — 定义标题锚点、主舞台、编号锚点三类职责层，让单个模板可承载不同页面内容。
5. 设计通用构图 — 平衡标题表达、正文承载和页码安全区，避免只能服务某一种页面类型。
6. 编码落地 — 将以上决策转化为一个完整 HTML/CSS 模板，共享 `:root` 变量和 `<style>` 样式。
""".strip()

    # ------------------------------------------------------------------
    # 技术要求（合并护栏层，避免与系统级约束重复）
    # ------------------------------------------------------------------

    @staticmethod
    def get_template_generation_requirements_prompt_text(
        include_page_numbers: bool = True,
    ) -> str:
        """母版生成技术要求——聚焦实现细节，系统级约束（CDN/画布/overflow）由 SystemPrompts.CACHE_STABLE_PREFIX 覆盖。"""
        placeholders = "`{{{{ page_title }}}}`、`{{{{ page_content }}}}`"
        if include_page_numbers:
            placeholders += "、`{{{{ current_page_number }}}}`、`{{{{ total_page_count }}}}`"

        prompt = f"""
**技术要求**
- 只输出一个 1280×720 的通用页面模板，画布根容器 `position:relative; overflow:hidden`。
- 输出完整 HTML，自包含 `<style>`，优先使用 `:root` 变量。
- 模板内部使用以下占位符：{placeholders}。它们会在渲染时被真实内容替换。
- 不要输出 cover/toc/transition/content/title/ending 等多页面类型变体，不要生成多个 `<section data-slide-type="xxx">`。
- 模板需要包含稳定的标题锚点区、主舞台区和编号锚点区；编号锚点可省略或极简，但不能挤占正文。
- 主舞台需要同时兼容标题页式的大留白和内容页式的信息密度，避免只能服务某一种页面类型。
- **禁止使用模板条件语法**：不要输出 `{{% if %}}` / `{{% endif %}}` / `{{% for %}}` 等 Jinja/模板控制结构。
- **禁止硬编码示例文案**：不要在模板中写入具体标题文字、口号或段落内容。所有会变化的文字必须使用占位符。如需辅助理解，放在 `<!-- 注释 -->` 中。
- 图标优先内联 SVG/CSS/Unicode；图表、公式、代码高亮按需启用。
- 如果使用纵向 `flex` 骨架，标题锚点和编号锚点 `flex:none`，主舞台 `flex:1; min-height:0; min-width:0; overflow:hidden`。
- 如果使用 `grid` 骨架，主舞台轨道写成 `minmax(0,1fr)`。
- 所有承载正文的 flex/grid item 显式写 `min-height:0; min-width:0`。
- 内容页兼容"内容较少时有气场"和"内容较多时不崩坏"；气场靠放大焦点与间距实现，舞台内模块按内容定高，不做纵向 stretch 撑空。
""".strip()
        return apply_page_number_prompt_filter(
            prompt,
            {"include_page_numbers": include_page_numbers},
        )

    @staticmethod
    def build_template_generation_prompt(
        user_prompt: str,
        mode_instruction: str = "",
        include_page_numbers: bool = True,
    ) -> str:
        """组装完整母版生成提示词——创意优先，技术护栏在后。"""
        mode_section = f"{mode_instruction.strip()}\n\n" if mode_instruction else ""
        prompt = f"""
{TemplatePrompts._get_role_framing()}

{mode_section}用户需求：
{user_prompt}

{TemplatePrompts.get_template_generation_creative_prompt_text()}

{TemplatePrompts.get_template_generation_method_prompt_text()}

{TemplatePrompts.get_template_generation_requirements_prompt_text(include_page_numbers=include_page_numbers)}

直接输出完整的单页母版 HTML（只包含一个通用 1280×720 页面模板），使用```html```代码块返回，不要附加解释。
""".strip()
        return apply_page_number_prompt_filter(
            prompt,
            {"include_page_numbers": include_page_numbers},
        )
