"""
Speech Script Generation Prompts
Contains all prompt templates for generating speech scripts from PPT slides
"""

from typing import Dict, Any, List
from ..speech_script_service import SpeechTone, TargetAudience, LanguageComplexity
from ..video_explainer import is_video_explainer, video_cue_labels
from ..audience_content import is_production_direction, slide_text_blocks


class SpeechScriptPrompts:
    """Speech script generation prompt templates"""

    # ----------------------------------------------------------------
    # 共享辅助
    # ----------------------------------------------------------------

    @staticmethod
    def _tts_output_rules(language: str = "zh") -> str:
        """共享的 TTS 纯文本输出规范（中/英）。"""
        if language == "en":
            return (
                "Output format: plain text only for TTS. No Markdown, no headings, no lists, "
                "no code blocks, no speaker labels, no stage directions. "
                "Keep normal punctuation for natural speech rhythm. Prefer a single paragraph."
            )
        return (
            "TTS输出规范：只输出纯文本。不要 Markdown/标题/列表/编号/引用/代码块/表格。"
            "保留正常标点。不要出现讲解者标签或舞台描述。尽量一段连续文本。"
        )

    @staticmethod
    def _humanizer_zh_core(language: str = "zh") -> str:
        """Humanizer-zh 核心规则压缩版——引用技能而非完整内联。"""
        if language == "en":
            return (
                "Follow the Humanizer-zh workflow: identify AI patterns → rewrite problematic phrasing "
                "→ preserve facts & structure → inject natural rhythm → self-check. "
                "Delete filler phrases, break formulaic structures, vary sentence lengths, "
                "trust the listener, remove slogan-like polished lines. "
                "Avoid: exaggerated significance, promotional language, vague attribution, mechanical connectives, "
                "binary contrast patterns, overused dashes. "
                "Start directly with content—no filler lead-ins. Output plain text only."
            )
        return (
            "按 Humanizer-zh 工作流处理：识别AI痕迹→只改写有问题的部分→保留事实和结构→注入自然节奏→自检。"
            "五条核心：删除填充短语、打破公式结构、变化节奏、信任听众、删除金句。"
            "重点清理：过度拔高、宣传腔、模糊归因、机械连接词、二元对比模板、破折号滥用。"
            "不要以“好”“好的”“那么”“接下来”“下面我来讲”等口头起手式开场。"
            "快速检查清单：事实是否保留、表达是否像真人口播、是否删除空泛拔高。"
            "开头直接进入内容，不铺垫。只输出改写后的纯文本。"
        )

    @staticmethod
    def _get_tone_description(tone: str, *, language: str = "zh") -> str:
        if (language or "zh").lower() == "en":
            m = {
                'formal': "formal, precise, business-like",
                'casual': "light, natural, friendly",
                'persuasive': "persuasive and motivating",
                'educational': "educational and explanatory",
                'conversational': "conversational and engaging",
                'authoritative': "authoritative and expert-like",
                'storytelling': "storytelling, vivid and engaging",
            }
            return m.get(tone, "natural and fluent")
        m = {
            'formal': "正式、严谨、专业的商务语调",
            'casual': "轻松、自然、亲切的日常语调",
            'persuasive': "有说服力、激励性的语调",
            'educational': "教学式、解释性的语调",
            'conversational': "对话式、互动性的语调",
            'authoritative': "权威、自信、专家式的语调",
            'storytelling': "叙事性、生动有趣的语调",
        }
        return m.get(tone, "自然流畅的语调")

    @staticmethod
    def _get_audience_description(audience: str, *, language: str = "zh") -> str:
        if (language or "zh").lower() == "en":
            m = {
                'executives': "business executives and decision-makers (focus on outcomes)",
                'students': "students (clear explanations and guidance)",
                'general_public': "general audience (plain language)",
                'technical_experts': "technical experts (can include technical terms)",
                'colleagues': "colleagues/peers (collaborative tone)",
                'clients': "clients (value and benefits oriented)",
                'investors': "investors (business value and returns)",
            }
            return m.get(audience, "general audience")
        m = {
            'executives': "企业高管和决策者，注重效率和结果",
            'students': "学生群体，需要清晰的解释和引导",
            'general_public': "普通大众，使用通俗易懂的语言",
            'technical_experts': "技术专家，可以使用专业术语",
            'colleagues': "同事和合作伙伴，平等交流的语调",
            'clients': "客户群体，注重价值和利益",
            'investors': "投资者，关注商业价值和回报",
        }
        return m.get(audience, "一般听众")

    @staticmethod
    def _get_complexity_description(complexity: str, *, language: str = "zh") -> str:
        if (language or "zh").lower() == "en":
            m = {
                'simple': "simple and easy to understand",
                'moderate': "moderately complex, balanced",
                'advanced': "advanced and technical when appropriate",
            }
            return m.get(complexity, "moderately complex")
        m = {
            'simple': "简单易懂，避免复杂词汇和长句",
            'moderate': "适中复杂度，平衡专业性和可理解性",
            'advanced': "较高复杂度，可以使用专业术语和复杂概念",
        }
        return m.get(complexity, "适中复杂度")

    @staticmethod
    def _get_transition_guidance(include_transitions: bool, *, language: str = "zh") -> str:
        """Explain how to keep adjacent slides coherent with or without explicit transitions."""
        if (language or "zh").lower() == "en":
            if include_transitions:
                return (
                    "Use concise explicit transitions only when they help the talk flow. "
                    "Avoid mechanical page labels and filler openers."
                )
            return (
                "Explicit transition sentences are disabled. Do not add standalone bridge lines like "
                "\"on the previous slide\" or \"next we will\". Still preserve implicit continuity: "
                "echo the prior slide's key term or result in the opening idea, then move directly into "
                "this slide's point. Do not write this slide as an isolated mini-talk."
            )
        if include_transitions:
            return (
                "可以在必要时加入简洁的显性过渡，但只用于帮助听众理解叙述推进；"
                "避免机械地说“上一页”“接下来”等页码式串场。"
            )
        return (
            "过渡语句已关闭：不要添加“上一页讲了什么、接下来我们看什么”这类独立桥段。"
            "仍需做隐性承接：开头可自然呼应上一页的关键词、结论或问题，然后立刻展开当前页；"
            "不要把本页写成孤立段落。"
        )

    # ----------------------------------------------------------------
    # 单页演讲稿
    # ----------------------------------------------------------------

    @staticmethod
    def get_single_slide_script_prompt(
        slide_data: Dict[str, Any],
        slide_index: int,
        total_slides: int,
        project_info: Dict[str, Any],
        previous_slide_context: str,
        customization: Dict[str, Any],
    ) -> str:
        language = (customization.get("language") or "zh").strip().lower()
        slide_title = slide_data.get('title', f'第{slide_index + 1}页')
        slide_content = slide_data.get('html_content', '')

        visible_text = " ".join(
            text for text in slide_text_blocks(slide_content)
            if not is_production_direction(text)
        )
        text_content = project_info.get("audience_outline") or visible_text

        context_info = f"""项目信息：
- 演示主题：{project_info.get('topic', '')}
- 应用场景：{project_info.get('scenario', '')}
- 目标受众：{customization.get('target_audience', 'general_public')}
- 语言风格：{customization.get('tone', 'conversational')}
- 语言复杂度：{customization.get('language_complexity', 'moderate')}
- 输出语言：{language}

当前幻灯片信息：
- 幻灯片标题：{slide_title}
- 幻灯片位置：第{slide_index + 1}页，共{total_slides}页
- 幻灯片内容：{text_content}
"""
        slide_sequence = (project_info.get('slide_sequence') or '').strip()
        if slide_sequence:
            context_info += f"\n页序概览：{slide_sequence}"

        previous_slide_overview = (
            project_info.get('previous_slide_context')
            or previous_slide_context
            or ''
        ).strip()
        if previous_slide_overview:
            context_info += f"\n上一页内容概要：{previous_slide_overview}"

        previous_script_context = (
            project_info.get('previous_script_context')
            or project_info.get('previous_script_excerpt')
            or ''
        ).strip()
        if previous_script_context:
            context_info += f"\n上一页演讲稿参考：{previous_script_context}"

        next_slide_context = (project_info.get('next_slide_context') or '').strip()
        if next_slide_context:
            context_info += f"\n下一页内容概要：{next_slide_context}"

        if customization.get('custom_style_prompt'):
            context_info += f"\n自定义风格要求：{customization['custom_style_prompt']}"
        seconds = customization.get("target_seconds")
        strict_duration = customization.get("strict_duration")
        if seconds and language == "en":
            instruction = "within" if strict_duration else "around"
            length_guidance = f"Aim for {instruction} {seconds} seconds ({int(seconds * 2)} spoken words)."
        elif seconds:
            timing = f"{seconds} 秒以内" if strict_duration else f"约 {seconds} 秒"
            length_guidance = f"本页旁白{timing}，参考 {int(seconds * 3.5)} 个汉字。"
        else:
            length_guidance = ("Keep reasonably concise (1–3 minutes)." if language == "en"
                               else "控制篇幅，确保演讲时长适中（1-3分钟）")

        tone_desc = SpeechScriptPrompts._get_tone_description(
            customization.get('tone', 'conversational'), language=language)
        audience_desc = SpeechScriptPrompts._get_audience_description(
            customization.get('target_audience', 'general_public'), language=language)
        complexity_desc = SpeechScriptPrompts._get_complexity_description(
            customization.get('language_complexity', 'moderate'), language=language)
        tts_rules = SpeechScriptPrompts._tts_output_rules(language)
        if is_video_explainer(project_info):
            cue_labels = " → ".join(
                label for label in video_cue_labels(slide_content)
                if not is_production_direction(label)
            )
            return f"""为技术图解视频的当前镜头写可直接配音的旁白。

{context_info}

内部口播要求：{project_info.get("video_requirements") or "用同一个例子讲清机制"}
用于同步画面的术语顺序：{cue_labels or "按当前图解顺序"}

第一镜直接说出具体问题，其余镜头承接上一句的悬念或结论。
沿图中对象和连线解释为什么发生变化，把关键机制和例子讲出来。短句，自然停顿，删去致意和翻页话术。
术语与主题内容相关时按给定顺序自然说出。只讲主题本身，不念制作要求、画面调度、时间戳、思考或调研步骤。
有实质意义的来源归属、不确定性和适用边界继续保留。
根据整片时长和镜头数控制本镜头篇幅，给观众留出读图时间；以 {language} 输出。
{length_guidance if seconds else ""}
{tts_rules}
只输出本镜头实际说出口的文字。"""
        include_transitions = bool(customization.get('include_transitions', True))
        transition_guidance = SpeechScriptPrompts._get_transition_guidance(
            include_transitions,
            language=language,
        )

        if language == "en":
            return f"""You are a professional presentation speaker and scriptwriter. Write a natural narration script for the following PPT slide.

{context_info}

Requirements:
- Tone: {tone_desc}
- Audience: {audience_desc}
- Complexity: {complexity_desc}
- Include transitions: {'Yes' if include_transitions else 'No'}
- Speaking pace: {customization.get('speaking_pace', 'normal')}
- Cohesion mode: {transition_guidance}

Guidelines:
- Stay faithful to the slide content, but do not simply repeat it.
- Use natural spoken English for live narration.
- Start directly with the slide's substance—no filler lead-ins like "Okay,", "So,", "Now,", "Next," unless context truly requires a transition.
- Speak to the audience about the subject. Omit production instructions, stage directions, timestamps, and reasoning about how to write the script.
- Keep this slide on the same narrative line as adjacent slides; do not make it feel like a separate speech.
- {length_guidance}
- {tts_rules}

Return ONLY the script content."""

        return f"""你是一位专业的演讲稿撰写专家。请为以下PPT幻灯片生成一份自然流畅的演讲稿。

{context_info}

演讲稿要求：
- 语调风格：{tone_desc}
- 目标受众：{audience_desc}
- 语言复杂度：{complexity_desc}
- 包含过渡语句：{'是' if include_transitions else '否'}
- 演讲节奏：{customization.get('speaking_pace', 'normal')}
- 连贯性策略：{transition_guidance}

生成要求：
- 内容与幻灯片紧密相关，但不简单重复
- 自然口语化，适合现场演讲
- 开头直接进入当前页核心内容，不要先说“好”“好的”“那么”“接下来”“下面我来讲”等口头起手式
- 直接讲主题本身的事实、例子和结论，省去制作要求、画面调度、时间戳和写作过程
- 与前后页保持同一条叙述线，不要把本页写成孤立段落
- {length_guidance}
- 可适当添加例子、类比或互动元素
- {tts_rules}

请直接输出演讲稿内容。"""

    # ----------------------------------------------------------------
    # Humanized Script（引用技能，不再内联完整规则）
    # ----------------------------------------------------------------

    @staticmethod
    def get_humanized_script_prompt(
        original_script: str,
        customization: Dict[str, Any],
    ) -> str:
        language = (customization.get("language") or "zh").strip().lower()
        tone_desc = SpeechScriptPrompts._get_tone_description(
            customization.get('tone', 'conversational'), language=language)
        audience_desc = SpeechScriptPrompts._get_audience_description(
            customization.get('target_audience', 'general_public'), language=language)
        complexity_desc = SpeechScriptPrompts._get_complexity_description(
            customization.get('language_complexity', 'moderate'), language=language)
        custom_style = (customization.get('custom_style_prompt') or '').strip()
        humanizer_core = SpeechScriptPrompts._humanizer_zh_core(language)

        if language == "en":
            extra = f"\nAdditional style: {custom_style}" if custom_style else ""
            return f"""Strictly follow the Humanizer-zh workflow to rewrite this presentation script into natural spoken language.

Original script:
{original_script}

Context: Tone: {tone_desc} | Audience: {audience_desc} | Complexity: {complexity_desc} | Pace: {customization.get('speaking_pace', 'normal')}{extra}

{humanizer_core}

Return only the rewritten plain text."""

        extra = f"\n补充风格要求：{custom_style}" if custom_style else ""
        return f"""请严格按照 Humanizer-zh SKILL.md 的处理方法，把下面这段演讲稿改写成人会自然说出来的话。

原始演讲稿：
{original_script}

当前上下文：语调风格：{tone_desc} | 目标受众：{audience_desc} | 语言复杂度：{complexity_desc} | 演讲节奏：{customization.get('speaking_pace', 'normal')}{extra}

{humanizer_core}

请直接输出最终的人话化演讲稿。"""

    # ----------------------------------------------------------------
    # 开场白 & 结束语
    # ----------------------------------------------------------------

    @staticmethod
    def get_opening_remarks_prompt(
        project_info: Dict[str, Any],
        customization: Dict[str, Any],
    ) -> str:
        language = (customization.get("language") or "zh").strip().lower()
        tone_desc = SpeechScriptPrompts._get_tone_description(
            customization.get('tone', 'conversational'), language=language)
        audience_desc = SpeechScriptPrompts._get_audience_description(
            customization.get('target_audience', 'general_public'), language=language)
        tts_rules = SpeechScriptPrompts._tts_output_rules(language)

        return f"""请为以下演示生成一段精彩的开场白：

演示信息：
- 主题：{project_info.get('topic', '')}
- 场景：{project_info.get('scenario', '')}
- 目标受众：{customization.get('target_audience', 'general_public')}
- 语言风格：{customization.get('tone', 'conversational')}
- 输出语言：{language}

开场白要求：
- 语调风格：{tone_desc}
- 目标受众：{audience_desc}
- 时长控制在1-2分钟
- 能够吸引听众注意力，简要介绍演示主题和价值
- 可以包含问候语、引子（问题/故事/数据），为后续内容铺垫
- 自然口语化，体现演讲者的专业性和亲和力
- {tts_rules}

请直接输出开场白内容。"""

    @staticmethod
    def get_closing_remarks_prompt(
        project_info: Dict[str, Any],
        customization: Dict[str, Any],
    ) -> str:
        language = (customization.get("language") or "zh").strip().lower()
        tone_desc = SpeechScriptPrompts._get_tone_description(
            customization.get('tone', 'conversational'), language=language)
        audience_desc = SpeechScriptPrompts._get_audience_description(
            customization.get('target_audience', 'general_public'), language=language)
        tts_rules = SpeechScriptPrompts._tts_output_rules(language)

        return f"""请为以下演示生成一段有力的结束语：

演示信息：
- 主题：{project_info.get('topic', '')}
- 场景：{project_info.get('scenario', '')}
- 目标受众：{customization.get('target_audience', 'general_public')}
- 语言风格：{customization.get('tone', 'conversational')}
- 输出语言：{language}

结束语要求：
- 语调风格：{tone_desc}
- 目标受众：{audience_desc}
- 时长控制在1-2分钟
- 总结核心要点，强化主要价值和信息
- 包含行动号召或下一步建议
- 以积极正面的语调收束，给听众留下深刻印象
- 自然口语化，结尾有力量感和感召力
- {tts_rules}

请直接输出结束语内容。"""

    # ----------------------------------------------------------------
    # 过渡增强 & 优化
    # ----------------------------------------------------------------

    @staticmethod
    def get_transition_enhancement_prompt(
        current_script: str,
        previous_slide_context: str,
        next_slide_context: str,
    ) -> str:
        return f"""请为以下演讲稿添加自然的过渡语句，使其与前后内容更好地连接：

当前演讲稿：
{current_script}

上一页内容概要：
{previous_slide_context}

下一页内容概要：
{next_slide_context}

过渡要求：
1. 在演讲稿开头添加自然的过渡语句，连接上一页内容
2. 在演讲稿结尾添加引导语句，为下一页内容做铺垫
3. 过渡要自然流畅，不显突兀
4. 保持原有演讲稿的核心内容不变
5. 使用口语化的表达方式

{SpeechScriptPrompts._tts_output_rules()}
请输出增强过渡后的完整演讲稿。"""

    @staticmethod
    def get_script_refinement_prompt(
        original_script: str,
        refinement_request: str,
        customization: Dict[str, Any],
    ) -> str:
        tone_desc = SpeechScriptPrompts._get_tone_description(
            customization.get('tone', 'conversational'))
        audience_desc = SpeechScriptPrompts._get_audience_description(
            customization.get('target_audience', 'general_public'))
        complexity_desc = SpeechScriptPrompts._get_complexity_description(
            customization.get('language_complexity', 'moderate'))

        return f"""请根据用户要求优化以下演讲稿：

原始演讲稿：
{original_script}

用户优化要求：
{refinement_request}

当前设置：
- 语调风格：{tone_desc}
- 目标受众：{audience_desc}
- 语言复杂度：{complexity_desc}

优化要求：
1. 保持演讲稿的核心信息和结构
2. 根据用户要求进行针对性调整
3. 确保语言风格与设置保持一致
4. 使用自然的口语化表达
5. 保持适当的演讲时长

请输出优化后的演讲稿。"""
