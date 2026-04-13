"""
PPT大纲生成相关提示词
包含所有用于生成PPT大纲的提示词模板
"""

from datetime import datetime
from typing import Dict, Any, List


class OutlinePrompts:
    """PPT大纲生成相关的提示词集合"""

    @staticmethod
    def _build_current_time_context_zh() -> str:
        """构建中文当前时间上下文。"""
        now = datetime.now().astimezone()
        quarter = (now.month - 1) // 3 + 1
        timezone_name = now.tzname() or "Local"
        return "\n".join([
            f"- 当前本地时间：{now:%Y-%m-%d %H:%M:%S} ({timezone_name})",
        ])

    @staticmethod
    def _build_current_time_context_en() -> str:
        """Build English current-time context."""
        now = datetime.now().astimezone()
        quarter = (now.month - 1) // 3 + 1
        timezone_name = now.tzname() or "Local"
        return "\n".join([
            f"- Current local time: {now:%Y-%m-%d %H:%M:%S} ({timezone_name})",
            f"- Current year: {now:%Y}",
            f"- Current month: {now.month}",
            f"- Current quarter: Q{quarter}",
            "- If the outline needs phrases such as \"current\", \"this year\", \"this month\", \"this quarter\", or \"recent\", use the time above. If the project brief, research content, or source material already gives an explicit date or period, prefer the source value instead of overriding it."
        ])
    
    @staticmethod
    def get_outline_prompt_zh(topic: str, scenario_desc: str, target_audience: str, 
                             style_desc: str, requirements: str, description: str,
                             research_section: str, page_count_instruction: str,
                             expected_page_count: int, language: str) -> str:
        """获取中文大纲生成提示词"""
        current_time_context = OutlinePrompts._build_current_time_context_zh()
        return f"""你是一位专业的PPT大纲策划专家，请基于以下项目信息，生成一个**结构清晰、内容创意、专业严谨、格式规范的JSON格式PPT大纲**。

### 📌【项目信息】：
- **主题**：{topic}
- **应用场景**：{scenario_desc}
- **目标受众**：{target_audience}
- **PPT风格**：{style_desc}
- **特殊要求**：{requirements or '无'}
- **补充说明**：{description or '无'}
{research_section}

### 📄【页数要求】：
{page_count_instruction}

### 🕒【当前时间参考】：
{current_time_context}

---

### 📋【大纲生成规则】：

1. **内容契合度要求**：
   - 所有幻灯片内容必须与上述项目信息严格匹配，确保主题明确、风格统一、内容相关。
   - 信息表达要专业可信，同时具有吸引力与传播力。

2. **页面结构规范**：
   - 必须包含以下固定结构（按顺序）：
     · **第1页 — 封面页**（slide_type="title"）：展示主题标题、副标题或作者信息，是整套 PPT 的视觉开篇，应设计得令人印象深刻。
     · **第2页 — 目录页**（slide_type="agenda"）：展示整套 PPT 的章节结构和导航索引，帮助观众一眼看懂全局脉络。目录页的 content_points 应列出后续各章节的标题。
     · **第3页起 — 内容页**（slide_type="content"，若干）：合理分层，逻辑清晰，每页围绕一个主题展开。
     · **最后一页 — 结论/感谢页**（slide_type="conclusion" 或 "thankyou"）：总结核心观点或致谢收尾，与首页在气质上形成呼应。
   - 封面页、目录页和结论页属于特殊页面，后续会进行独立的创意设计，不会套用普通内容页的模板。

3. **内容点控制**：
   - 封面页：content_points 只放核心标题信息（主标题、副标题、作者/日期等），保持克制。
   - 目录页：content_points 列出后续各章节/部分的标题，作为导航索引。
   - 结论/感谢页：content_points 提炼核心结论或致谢信息，保持简洁有力。
   - 普通内容页可适当展开，但仍要避免信息堆积与重复。
   - 每个要点内容简洁清晰，可做适当解释，但**不超过50字符**。
   - 内容分布需均衡，避免信息堆积或重复。

4. **图表展示优化**：
   - 对适合可视化的信息，**建议并提供图表配置**，写入 `chart_config` 字段中。
   - 图表需明确类型（如柱状图、折线图、饼图、甘特图、森林图、韦恩图、upset图、生存曲线图、漏斗图、环形图、和弦图、词云图、关联图、瀑布图、条形图、面积图等）、说明含义、配置样式及数据结构。

5. **语言风格与语境一致性**：
   - 使用统一语言（{language}），保持语境一致，适合目标受众理解与接受。
   - 如果需要提及“当前、今年、本月、本季度、最近”等时间语义，必须以上述当前时间为准；若需求或材料已给出明确时间，以原始时间为准。

---

### 🧾【输出格式要求】：

请严格使用如下JSON格式进行输出，**使用代码块包裹，内容必须有效且结构完整**：

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
      "slide_type": "title|agenda|content|conclusion|thankyou",
      "type": "title|agenda|content|conclusion|thankyou",
      "description": "此页的简要说明与目的",
      "chart_config": {{
        "type": "bar",
        "data": {{
          "labels": ["示例A", "示例B", "示例C"],
          "datasets": [{{
            "label": "数据说明",
            "data": [80, 95, 70],
            "backgroundColor": ["#FF6B6B", "#4ECDC4", "#FFD93D"],
            "borderColor": ["#FF5252", "#26A69A", "#F4A261"],
            "borderWidth": 2
          }}]
        }},
        "options": {{
          "responsive": true,
          "plugins": {{
            "legend": {{"position": "top"}},
            "title": {{"display": true, "text": "图表标题"}}
          }},
          "scales": {{"y": {{"beginAtZero": true}}}}
        }}
      }}
    }}
  ],
  "metadata": {{
    "scenario": "{scenario_desc}",
    "language": "{language}",
    "total_slides": {expected_page_count},
    "generated_with_ai": true,
    "enhanced_with_charts": true,
    "content_depth": "professional"
  }}
}}
```"""

    @staticmethod
    def get_outline_prompt_en(topic: str, scenario_desc: str, target_audience: str,
                             style_desc: str, requirements: str, description: str,
                             research_section: str, page_count_instruction: str,
                             expected_page_count: int, language: str) -> str:
        """获取英文大纲生成提示词"""
        current_time_context = OutlinePrompts._build_current_time_context_en()
        return f"""You are a **professional presentation outline designer**. Based on the following project details, please generate a **well-structured, creative, and professional JSON-format PowerPoint outline**.

### 📌【Project Details】:
- **Topic**: {topic}
- **Scenario**: {scenario_desc}
- **Target Audience**: {target_audience}
- **PPT Style**: {style_desc}
- **Special Requirements**: {requirements or 'None'}
- **Additional Notes**: {description or 'None'}
{research_section}

**Page Count Requirements:**
{page_count_instruction}

### 🕒【Current Time Reference】:
{current_time_context}

---

### 📋【Outline Generation Rules】:

1. **Content Relevance**:
   - All slide content must strictly align with the project details above.
   - Ensure the theme is clear, the tone is consistent, and the message is well-targeted.

2. **Slide Structure**:
   - The deck must include the following fixed structure (in order):
     · **Page 1 — Cover Slide** (slide_type="title"): Display the main title, subtitle, or author info. This is the visual opening of the entire PPT.
     · **Page 2 — Agenda/TOC Slide** (slide_type="agenda"): Show the chapter structure and navigation index. The content_points should list the titles of subsequent sections.
     · **Page 3+ — Content Slides** (slide_type="content"): Logically structured, each page focused on one topic.
     · **Last Page — Conclusion/Thank You Slide** (slide_type="conclusion" or "thankyou"): Summarize key points or express gratitude.
   - Cover, Agenda, and Conclusion slides are special pages that will receive unique creative designs, not standard content page templates.

3. **Content Density Control**:
   - Cover slide: content_points should only contain core title info (main title, subtitle, author/date), keep it restrained.
   - Agenda slide: content_points should list the titles of subsequent chapters/sections as navigation.
   - Conclusion slide: content_points should distill core conclusions or thanks, keep it concise.
   - Regular content slides may be more detailed, but should still avoid overload and repetition.
   - Each point should be **no more than 50 characters**.
   - Distribute content evenly across slides to avoid overload or redundancy.

4. **Chart Suggestions**:
   - For any data, comparisons, or visual-friendly content, suggest a chart and include its configuration under `chart_config`.
   - Specify chart type (e.g., bar, pie, line), provide sample data, and chart options.

5. **Language & Tone**:
   - The entire outline should be in **{language}** and aligned with the communication preferences of the target audience.
   - If the outline needs time-sensitive phrasing such as "current", "this year", "this month", "this quarter", or "recent", use the current time above. If the brief or source material already includes an explicit date or period, use the source value.

---

### 🧾【Required Output Format】:

Please follow the exact JSON format below, and **wrap the result in a code block**. The JSON must be valid and complete.

```json
{{
  "title": "A compelling and professional PPT title",
  "total_pages": {expected_page_count},
  "page_count_mode": "final",
  "slides": [
    {{
      "page_number": 1,
      "title": "Slide Title",
      "content_points": ["Point 1", "Point 2", "Point 3"],
      "slide_type": "title|agenda|content|conclusion|thankyou",
      "type": "title|agenda|content|conclusion|thankyou",
      "description": "Brief description of this slide",
      "chart_config": {{
        "type": "bar",
        "data": {{
          "labels": ["Metric A", "Metric B", "Metric C"],
          "datasets": [{{
            "label": "Performance Data",
            "data": [80, 95, 70],
            "backgroundColor": ["#FF6B6B", "#4ECDC4", "#FFD93D"],
            "borderColor": ["#FF5252", "#26A69A", "#F4A261"],
            "borderWidth": 2
          }}]
        }},
        "options": {{
          "responsive": true,
          "plugins": {{
            "legend": {{"position": "top"}},
            "title": {{"display": true, "text": "Chart Title"}}
          }},
          "scales": {{"y": {{"beginAtZero": true}}}}
        }}
      }}
    }}
  ],
  "metadata": {{
    "scenario": "{scenario_desc}",
    "language": "{language}",
    "total_slides": {expected_page_count},
    "generated_with_ai": true,
    "enhanced_with_charts": true,
    "content_depth": "professional"
  }}
}}
```"""

    @staticmethod
    def get_streaming_outline_prompt(topic: str, target_audience: str, ppt_style: str,
                                   page_count_instruction: str, research_section: str) -> str:
        """获取流式大纲生成提示词"""
        current_time_context = OutlinePrompts._build_current_time_context_zh()
        return f"""作为专业的PPT大纲生成助手，请为以下项目生成详细的PPT大纲。

项目信息：
- 主题：{topic}
- 目标受众：{target_audience}
- PPT风格：{ppt_style}
{page_count_instruction}{research_section}

当前时间参考：
{current_time_context}

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

 slide_type可选值：
 - "title": 标题页/封面页
 - "content": 内容页
 - "agenda": 目录页
 - "conclusion": 总结/结论页
 - "thankyou": 结束页/感谢页

要求：
1. 必须返回有效的JSON格式
2. 严格遵守页数要求
 3. 第一页通常是标题页，最后一页通常是总结(conclusion)或感谢(thankyou)
4. 第一页和最后一页要保持克制与聚焦，不要像普通内容页一样堆满要点
5. 页面标题要简洁明确
6. 内容要点要具体实用
7. 根据重点内容和技术亮点安排页面内容
8. 如果需要使用“当前 / 今年 / 本月 / 本季度 / 最近”等时间语义，请以上述当前时间为准；若输入信息已给出明确时间，以输入信息为准

请只返回JSON，使用```json```代码块包裹，不要包含其他文字说明。

示例格式：
```json
{{
  "title": "PPT标题",
  "slides": [
    {{
      "page_number": 1,
      "title": "页面标题",
      "content_points": ["要点1", "要点2"],
      "slide_type": "title"
    }}
  ]
}}
```"""

    @staticmethod
    def get_outline_generation_context(topic: str, target_audience: str, ppt_style: str,
                                     page_count_instruction: str, focus_content: List[str],
                                     tech_highlights: List[str], description: str) -> str:
        """获取大纲生成上下文提示词"""
        focus_content_str = ', '.join(focus_content) if focus_content else '无'
        tech_highlights_str = ', '.join(tech_highlights) if tech_highlights else '无'
        current_time_context = OutlinePrompts._build_current_time_context_zh()
        
        return f"""请为以下项目生成详细的PPT大纲：

项目信息：
- 主题：{topic}
- 目标受众：{target_audience}
- PPT风格：{ppt_style}
- 重点展示内容：{focus_content_str}
- 技术亮点：{tech_highlights_str}
- 其他说明：{description or '无'}
{page_count_instruction}

当前时间参考：
{current_time_context}

请生成结构化的PPT大纲，包含每页的标题、内容要点和页面类型。确保内容逻辑清晰，符合目标受众需求。"""

    @staticmethod
    def get_streaming_outline_prompt(topic: str, target_audience: str, ppt_style: str,
                                   page_count_instruction: str, research_section: str) -> str:
        """获取流式大纲生成提示词"""
        current_time_context = OutlinePrompts._build_current_time_context_zh()
        prompt = f"""
作为专业的PPT大纲生成助手，请为以下项目生成详细的PPT大纲。

项目信息：
- 主题：{topic}
- 目标受众：{target_audience}
- PPT风格：{ppt_style}
{page_count_instruction}{research_section}

当前时间参考：
{current_time_context}

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

 slide_type可选值：
 - "title": 标题页/封面页
 - "content": 内容页
 - "agenda": 目录页
 - "conclusion": 总结/结论页
 - "thankyou": 结束页/感谢页

要求：
1. 必须返回有效的JSON格式
2. 严格遵守页数要求
 3. 第一页通常是标题页，最后一页通常是总结(conclusion)或感谢(thankyou)
4. 第一页和最后一页要保持克制与聚焦，不要像普通内容页一样堆满要点
5. 页面标题要简洁明确
6. 内容要点要具体实用
7. 根据重点内容和技术亮点安排页面内容
8. 如果需要使用“当前 / 今年 / 本月 / 本季度 / 最近”等时间语义，请以上述当前时间为准；若输入信息已给出明确时间，以输入信息为准

请只返回JSON，使用```json```代码块包裹，不要包含其他文字说明。

示例格式：
```json
{{
  "title": "PPT标题",
  "slides": [
    {{
      "page_number": 1,
      "title": "页面标题",
      "content_points": ["要点1", "要点2"],
      "slide_type": "title"
    }}
  ]
}}
```
"""
        return prompt

    @staticmethod
    def get_outline_generation_context(topic: str, target_audience: str, page_count_instruction: str,
                                     ppt_style: str, custom_style: str, description: str,
                                     page_count_mode: str) -> str:
        """获取大纲生成上下文提示词"""
        current_time_context = OutlinePrompts._build_current_time_context_zh()
        context = f"""
项目信息：
- 主题：{topic}
- 目标受众：{target_audience}
{page_count_instruction}
- PPT风格：{ppt_style}
- 自定义风格说明：{custom_style}
- 其他说明：{description}

当前时间参考：
{current_time_context}

任务：生成完整的PPT大纲

请生成一个详细的PPT大纲，包括：
1. PPT标题
2. 各页面标题和主要内容要点
3. 逻辑结构和流程
4. 每页的内容重点
5. 根据页数要求合理安排内容分布
6. 首尾页保持精简和聚焦，避免像正文页一样堆叠过多要点

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
            "slide_type": "title|agenda|content|conclusion|thankyou",
            "description": "页面内容描述"
        }}
    ]
}}
```
"""
        return context
