"""
PPT大纲生成相关提示词
包含所有用于生成PPT大纲的提示词模板
"""

from datetime import datetime
from typing import Dict, Any, List
from ..audience_content import OUTLINE_COPY_RULE, OUTLINE_COPY_RULE_EN


class OutlinePrompts:
    """PPT大纲生成相关的提示词集合"""

    @staticmethod
    def get_video_storyboard_prompt(
        topic: str,
        target_audience: str,
        requirements: str,
        visual_style: str,
        page_count_instruction: str,
        research_context: str,
        language: str = "zh",
    ) -> str:
        return f"""为 16:9 技术图解视频写逐镜大纲，每一页对应一个可播放的镜头。

主题：{topic}
受众：{target_audience}
制作要求：{requirements}
画面风格：{visual_style}
{page_count_instruction}
参考资料：{research_context or "暂无额外调研资料"}
当前时间：{OutlinePrompts._build_current_time_context_zh()}

第一镜直接展示可辨识的场景和一个具体问题，使用 content 类型。沿同一个例子解释问题、机制、应用结果，
最后讲清边界。只使用 content 或 conclusion。跳过独立封面、目录、转场页和致谢页。
{OUTLINE_COPY_RULE}
每镜围绕一个可理解的关系或变化。production_notes 仅在需要时写底图对象或依次出现的连线，
相邻镜头可沿用同一个图。主题例子若只是示意，说明其性质；引用调研事实时保留来源。
{OutlinePrompts._build_streaming_language_instruction(language)}

只返回 JSON 代码块，字段如下：
{{
  "title": "视频标题",
  "slides": [
    {{
      "page_number": 1,
      "title": "具体问题或判断",
      "slide_type": "content",
      "content_points": ["对象或事实"],
      "description": "有必要时补充一条观众需要知道的事实或边界",
      "production_notes": "可选的绘图备注，留在制作流程内"
    }}
  ]
}}"""

    # ----------------------------------------------------------------
    # 时间上下文
    # ----------------------------------------------------------------

    @staticmethod
    def _build_current_time_context_zh() -> str:
        now = datetime.now().astimezone()
        quarter = (now.month - 1) // 3 + 1
        tz_name = now.tzname() or "Local"
        return "\n".join([
            f"- 当前本地时间：{now:%Y-%m-%d %H:%M:%S} ({tz_name})",
            f"- 当前年份：{now:%Y}，月份：{now.month}，季度：Q{quarter}",
            '- 若大纲需使用\u201c当前/今年/本月/本季度/最近\u201d等时间语义，请以上述时间为准；若项目需求或来源材料已给出明确日期，优先使用来源值。',
        ])

    @staticmethod
    def _build_current_time_context_en() -> str:
        now = datetime.now().astimezone()
        quarter = (now.month - 1) // 3 + 1
        tz_name = now.tzname() or "Local"
        return "\n".join([
            f"- Current local time: {now:%Y-%m-%d %H:%M:%S} ({tz_name})",
            f"- Current year: {now:%Y}, month: {now.month}, quarter: Q{quarter}",
            "- If the outline uses time-sensitive phrasing (\"current\", \"this year\", etc.), use the time above. If the brief or source material gives an explicit date, prefer the source value.",
        ])

    # ----------------------------------------------------------------
    # 过渡页指令
    # ----------------------------------------------------------------

    @staticmethod
    def _build_transition_page_instruction_zh(include: bool) -> str:
        if not include:
            return "过渡页：未开启；不要生成 transition 类型页面。"
        return (
            "过渡页：已开启；请在主要章节之间插入 slide_type=\"transition\" 的页面，"
            "用于章节分隔和节奏控制。content_points 只保留章节名、转场语或下一章提示。"
            "过渡页计入总页数。"
        )

    @staticmethod
    def _build_transition_page_instruction_en(include: bool) -> str:
        if not include:
            return "Transition slides: disabled; do not generate `transition` slides."
        return (
            "Transition slides: enabled; insert slide_type=\"transition\" pages between major sections. "
            "Use them for section separation and pacing. Keep content_points limited to section title / bridge phrase. "
            "Transition slides count toward the requested page count."
        )

    # ----------------------------------------------------------------
    # 核心大纲生成（中文）
    # ----------------------------------------------------------------

    @staticmethod
    def get_outline_prompt_zh(
        topic: str, scenario_desc: str, target_audience: str,
        style_desc: str, requirements: str, description: str,
        research_section: str, page_count_instruction: str,
        expected_page_count: int, language: str,
        include_transition_pages: bool = False,
    ) -> str:
        time_ctx = OutlinePrompts._build_current_time_context_zh()
        transition_inst = OutlinePrompts._build_transition_page_instruction_zh(include_transition_pages)

        return f"""你是专业的PPT大纲策划专家。请基于以下项目信息，生成结构清晰、内容创意、专业严谨的 JSON 格式 PPT 大纲。

### 项目信息
- 主题：{topic}
- 应用场景：{scenario_desc}
- 目标受众：{target_audience}
- PPT风格：{style_desc}
- 特殊要求：{requirements or '无'}
- 补充说明：{description or '无'}
{research_section}

### 页数要求
{page_count_instruction}

### 当前时间参考
{time_ctx}

---

### 大纲生成规则

1. **内容契合**：所有幻灯片内容必须与项目信息严格匹配，风格统一、信息专业可信。

2. **页面结构**（按顺序）：
   - 第1页 — 封面页（slide_type="title"）：展示主题标题、副标题或作者信息。
   - 第2页 — 目录页（slide_type="agenda"）：展示章节结构和导航索引，content_points 列出后续各章节标题。
   - 第3页起 — 内容页（slide_type="content"）：合理分层，每页围绕一个主题。
   - 可选过渡页（slide_type="transition"）：仅在开启时插入在主要章节之间。
   - 最后一页 — 结论/感谢页（slide_type="conclusion" 或 "thankyou"）：总结或致谢收尾。
   - {transition_inst}

3. **内容点控制**：
   - {OUTLINE_COPY_RULE}
   - 封面页 content_points 只放核心标题信息（主标题、副标题、作者/日期）。
   - 目录页 content_points 列出后续章节标题作为导航索引。
   - 过渡页 content_points 只保留章节名和转场提示。
   - 结论/感谢页 content_points 提炼核心结论，保持简洁有力。
   - 普通内容页可适当展开，每个要点不超过50字符，避免信息堆积。

4. **单页信息架构**：
   - 每页只承担 1 个核心任务（解释/上手/对比/架构/总结等）；标题用顿号或「与/及」串联 2 个以上独立主题时，优先拆成多页。
   - 普通内容页建议 1 个主模块 + 至多 1 个辅助模块；禁止同页并列两套完整流程且共用同一编号体系。
   - content_points 应能映射为单一版式（流程/卡片/指标/对比/层级），不要把多类完全不同的信息塞进同一页。
   - 页数紧张时宁可一页一任务、减少装饰性要点，也不要一页多主题。

5. **图表建议**：对适合可视化的信息，在 chart_config 字段中给出图表类型（bar/pie/line/scatter/radar 等）和简要说明。

6. **语言一致性**：统一使用 {language}。若需提及时间语义，以上述当前时间为准；若需求已给出明确时间，以原始时间为准。

---

### 输出格式

严格使用以下 JSON 格式，用 ```json``` 代码块包裹：

```json
{{
  "title": "专业且吸引人的PPT标题",
  "total_pages": {expected_page_count},
  "page_count_mode": "final",
  "slides": [
    {{
      "page_number": 1,
      "title": "页面标题",
      "content_points": ["要点1", "要点2", "要点3"],
      "slide_type": "title",
      "type": "title",
      "description": "观众需要知道的补充事实，可留空",
      "production_notes": "可选的绘图备注",
      "chart_config": null
    }}
  ],
  "metadata": {{
    "scenario": "{scenario_desc}",
    "language": "{language}",
    "total_slides": {expected_page_count},
    "generated_with_ai": true,
    "content_depth": "professional"
  }}
}}
```

slide_type 可选值：title / agenda / transition / content / conclusion / thankyou
chart_config 仅在需要图表时填写，含 type、data、options；不需要时设为 null。"""

    # ----------------------------------------------------------------
    # 核心大纲生成（英文）
    # ----------------------------------------------------------------

    @staticmethod
    def get_outline_prompt_en(
        topic: str, scenario_desc: str, target_audience: str,
        style_desc: str, requirements: str, description: str,
        research_section: str, page_count_instruction: str,
        expected_page_count: int, language: str,
        include_transition_pages: bool = False,
    ) -> str:
        time_ctx = OutlinePrompts._build_current_time_context_en()
        transition_inst = OutlinePrompts._build_transition_page_instruction_en(include_transition_pages)

        return f"""You are a professional presentation outline designer. Based on the following project details, generate a **well-structured, creative, and professional JSON-format PowerPoint outline**.

### Project Details
- Topic: {topic}
- Scenario: {scenario_desc}
- Target Audience: {target_audience}
- PPT Style: {style_desc}
- Special Requirements: {requirements or 'None'}
- Additional Notes: {description or 'None'}
{research_section}

### Page Count Requirements
{page_count_instruction}

### Current Time Reference
{time_ctx}

---

### Outline Generation Rules

1. **Content Relevance**: All slide content must strictly align with the project details above.

2. **Slide Structure** (in order):
   - Page 1 — Cover (slide_type="title"): Main title, subtitle, or author info.
   - Page 2 — Agenda/TOC (slide_type="agenda"): Chapter structure and navigation index.
   - Page 3+ — Content (slide_type="content"): Logically structured, one topic per page.
   - Optional Transition (slide_type="transition"): Between major sections when enabled.
   - Last Page — Conclusion/Thank You (slide_type="conclusion" or "thankyou").
   - {transition_inst}

3. **Content Density**:
   - {OUTLINE_COPY_RULE_EN}
   - Cover: content_points only for core title info.
   - Agenda: content_points list subsequent chapter titles.
   - Transition: content_points limited to section title and bridge cues.
   - Conclusion: concise summary or thanks.
   - Content pages: each point under 50 characters; avoid overload.

4. **Per-Slide Information Architecture**:
   - Each slide carries ONE core task (explain / get-started / compare / architecture / summary). If a title chains 2+ independent topics, split into multiple slides.
   - Content pages: 1 primary module + at most 1 auxiliary module; never place two complete numbered flows sharing the same numbering scheme on one slide.
   - content_points should map to a single layout family (process / cards / metrics / compare / stack); do not mix unrelated information types on one slide.
   - When page count is tight, prefer one-task-per-slide with fewer decorative points over multi-topic slides.

5. **Chart Suggestions**: For data-rich content, include a chart_config with type (bar/pie/line/scatter/radar etc.) and brief description.

6. **Language**: Entire outline in **{language}**. Use current time reference where applicable; prefer source values when given.

---

### Output Format

Exact JSON format, wrapped in ```json``` code block:

```json
{{
  "title": "A compelling PPT title",
  "total_pages": {expected_page_count},
  "page_count_mode": "final",
  "slides": [
    {{
      "page_number": 1,
      "title": "Slide Title",
      "content_points": ["Point 1", "Point 2", "Point 3"],
      "slide_type": "title",
      "type": "title",
      "description": "Optional extra fact for the audience",
      "production_notes": "Optional private drawing notes",
      "chart_config": null
    }}
  ],
  "metadata": {{
    "scenario": "{scenario_desc}",
    "language": "{language}",
    "total_slides": {expected_page_count},
    "generated_with_ai": true,
    "content_depth": "professional"
  }}
}}
```

slide_type values: title / agenda / transition / content / conclusion / thankyou
Use chart_config only when a chart is needed (include type, data, options); set to null otherwise."""

    # ----------------------------------------------------------------
    # 流式大纲生成
    # ----------------------------------------------------------------

    @staticmethod
    def get_streaming_outline_prompt(
        topic: str, target_audience: str, ppt_style: str,
        page_count_instruction: str, research_section: str,
        include_transition_pages: bool = False,
        language: str = "zh",
    ) -> str:
        time_ctx = OutlinePrompts._build_current_time_context_zh()
        transition_inst = OutlinePrompts._build_transition_page_instruction_zh(include_transition_pages)
        # The prompt scaffolding stays Chinese, but the OUTPUT language must follow
        # the project: an English project used to get a Chinese outline because this
        # function had no language parameter at all.
        language_instruction = OutlinePrompts._build_streaming_language_instruction(language)

        return f"""作为专业的PPT大纲生成助手，请为以下项目生成详细的PPT大纲。

项目信息：
- 主题：{topic}
- 目标受众：{target_audience}
- PPT风格：{ppt_style}
{page_count_instruction}{research_section}

当前时间参考：
{time_ctx}

请严格按照以下JSON格式生成PPT大纲：

{{
    "title": "PPT标题",
    "slides": [
        {{
            "page_number": 1,
            "title": "页面标题",
            "content_points": ["要点1", "要点2", "要点3"],
            "slide_type": "title"
        }},
        {{
            "page_number": 2,
            "title": "页面标题",
            "content_points": ["要点1", "要点2", "要点3"],
            "slide_type": "content"
        }}
    ]
}}

slide_type 可选值：title / content / agenda / transition / conclusion / thankyou

要求：
1. 必须返回有效的JSON格式，用```json```代码块包裹，不要包含其他文字说明
2. 严格遵守页数要求
3. 第一页为标题页，最后一页为 conclusion 或 thankyou
4. 首尾页保持克制与聚焦，不要像普通内容页一样堆满要点
5. {transition_inst}
6. 页面标题简洁明确，内容要点具体实用
7. 每页只承担一个核心任务；标题串联多个独立主题时优先拆页，不要一页多主题
8. 时间语义以上述当前时间为准；若输入信息已给出明确时间，以输入信息为准
9. {language_instruction}
10. {OUTLINE_COPY_RULE}"""

    _LANGUAGE_DISPLAY_NAMES = {
        "zh": "中文（简体）",
        "zh-cn": "中文（简体）",
        "zh-tw": "中文（繁體）",
        "en": "English",
        "ja": "日本語",
        "ko": "한국어",
        "fr": "Français",
        "de": "Deutsch",
        "es": "Español",
        "ru": "Русский",
        "pt": "Português",
    }

    @classmethod
    def _build_streaming_language_instruction(cls, language: str) -> str:
        code = (language or "zh").strip().lower()
        display = cls._LANGUAGE_DISPLAY_NAMES.get(code)
        if display is None:
            display = language.strip() if language and language.strip() else "中文（简体）"
        return (
            f"所有输出内容（title、页面标题、content_points）必须使用 {display} 撰写，"
            f"JSON 的字段名保持英文不变"
        )

    # ----------------------------------------------------------------
    # 大纲生成上下文（供其他模块使用）
    # ----------------------------------------------------------------

    @staticmethod
    def get_outline_generation_context(
        topic: str, target_audience: str, page_count_instruction: str,
        ppt_style: str, custom_style: str, description: str,
        page_count_mode: str,
    ) -> str:
        time_ctx = OutlinePrompts._build_current_time_context_zh()

        return f"""
项目信息：
- 主题：{topic}
- 目标受众：{target_audience}
{page_count_instruction}
- PPT风格：{ppt_style}
- 自定义风格说明：{custom_style}
- 其他说明：{description}

当前时间参考：
{time_ctx}

任务：生成完整的PPT大纲

请生成一个详细的PPT大纲，包括：
1. PPT标题
2. 各页面标题和主要内容要点
3. 逻辑结构和流程
4. 每页的内容重点
5. 根据页数要求合理安排内容分布
6. 首尾页保持精简和聚焦，避免像正文页一样堆叠过多要点
7. {OUTLINE_COPY_RULE}

请以JSON格式返回大纲，使用```json```代码块包裹，格式如下：

```json
{{
    "title": "PPT标题",
    "total_pages": 实际页数,
    "page_count_mode": "{page_count_mode}",
    "slides": [
        {{
            "page_number": 1,
            "title": "页面标题",
            "content_points": ["要点1", "要点2", "要点3"],
            "slide_type": "title|agenda|transition|content|conclusion|thankyou",
            "description": "观众需要知道的补充事实，可留空",
            "production_notes": "可选的绘图备注"
        }}
    ]
}}
```
"""
