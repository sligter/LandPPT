"""
Speech Script Generation Prompts
Contains all prompt templates for generating speech scripts from PPT slides
"""

from typing import Dict, Any, List
from ..speech_script_service import SpeechTone, TargetAudience, LanguageComplexity


class SpeechScriptPrompts:
    """Speech script generation prompt templates"""
    
    @staticmethod
    def get_single_slide_script_prompt(
        slide_data: Dict[str, Any],
        slide_index: int,
        total_slides: int,
        project_info: Dict[str, Any],
        previous_slide_context: str,
        customization: Dict[str, Any]
    ) -> str:
        """Generate prompt for single slide speech script"""
        language = (customization.get("language") or "zh").strip().lower()
        
        slide_title = slide_data.get('title', f'第{slide_index + 1}页')
        slide_content = slide_data.get('html_content', '')
        
        # Extract text content from HTML
        import re
        text_content = re.sub(r'<[^>]+>', '', slide_content)
        text_content = re.sub(r'\s+', ' ', text_content).strip()
        
        # Build context information
        context_info = f"""
项目信息：
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
        
        if previous_slide_context:
            context_info += f"\n上一页内容概要：{previous_slide_context}"
        
        if customization.get('custom_style_prompt'):
            context_info += f"\n自定义风格要求：{customization['custom_style_prompt']}"
        
        # Get tone and audience descriptions
        tone_desc = SpeechScriptPrompts._get_tone_description(
            customization.get('tone', 'conversational'),
            language=language,
        )
        audience_desc = SpeechScriptPrompts._get_audience_description(
            customization.get('target_audience', 'general_public'),
            language=language,
        )
        complexity_desc = SpeechScriptPrompts._get_complexity_description(
            customization.get('language_complexity', 'moderate'),
            language=language,
        )

        if language == "en":
            prompt = f"""You are a professional presentation speaker and scriptwriter. Write a natural narration script for the following PPT slide.

{context_info}

Requirements:
1. Tone: {tone_desc}
2. Audience: {audience_desc}
3. Complexity: {complexity_desc}
4. Include transitions: {'Yes' if customization.get('include_transitions', True) else 'No'}
5. Speaking pace: {customization.get('speaking_pace', 'normal')}

Guidelines:
- Stay faithful to the slide content, but do not simply repeat it.
- Use natural spoken English for live narration.
- If transitions are enabled, connect smoothly with the previous slide context.
- Start directly with the slide's substance. Do not open with filler lead-ins like "Okay,", "So,", "Now,", or "Next," unless the context truly requires a transition.
- Keep it reasonably concise (suggested 1–3 minutes).

Output plain English text only for TTS (no Markdown / no formatting):
- Do NOT use headings, bullet lists, numbering, quotes, code blocks, or tables.
- Keep normal punctuation (e.g. commas, periods, question marks) for natural speech; do not remove punctuation.
- Do NOT use Markdown formatting (e.g. headings starting with "#", list markers like "- " / "* " / "1.", emphasis "*"/"_", backticks "`", blockquotes ">", tables "|", code fences).
- Do NOT add speaker labels (e.g. "Narrator:") or stage directions in brackets.
- Prefer a single paragraph (no extra blank lines).
Return ONLY the script content."""
            return prompt

        # Default: Chinese prompt
        prompt = f"""你是一位专业的演讲稿撰写专家。请为以下PPT幻灯片生成一份自然流畅的演讲稿。

{context_info}

演讲稿要求：
1. 语调风格：{tone_desc}
2. 目标受众：{audience_desc}
3. 语言复杂度：{complexity_desc}
4. 包含过渡语句：{'是' if customization.get('include_transitions', True) else '否'}
5. 演讲节奏：{customization.get('speaking_pace', 'normal')}

生成要求：
- 内容要与幻灯片内容紧密相关，但不要简单重复
- 使用自然的口语化表达，适合现场演讲
- 如果需要过渡，请自然地连接上一页的内容
- 开头直接进入当前页核心内容，不要先说“好”“好的”“那么”“接下来”“下面我来讲”等口头起手式，除非上下文承接确实需要
- 控制篇幅，确保演讲时长适中（建议1-3分钟）
- 语言要符合指定的风格和受众特点
- 可以适当添加例子、类比或互动元素来增强效果

TTS输出规范（请严格遵守）：
- 只输出纯文本演讲稿，不要 Markdown/不要任何排版格式
- 不要标题、不要列表、不要编号、不要引用/代码/表格
- 保留正常中文标点（如，。！？；：、“”……），不要刻意去掉标点
- 不要使用 Markdown 排版符号（如以 # 开头的标题、以“- ”/“* ”/“1.”开头的列表、反引号`、引用符 >、表格竖线 | 等）
- 不要出现“讲解者：/解说：”等标签，也不要括号里的舞台描述
- 尽量一段连续文本，不要多余空行

请直接输出演讲稿内容，不需要额外的格式说明或标题。"""
        return prompt

    @staticmethod
    def get_humanized_script_prompt(
        original_script: str,
        customization: Dict[str, Any]
    ) -> str:
        """严格按 Humanizer-zh 技能工作流改写演讲稿。"""

        language = (customization.get("language") or "zh").strip().lower()
        tone_desc = SpeechScriptPrompts._get_tone_description(
            customization.get('tone', 'conversational'),
            language=language,
        )
        audience_desc = SpeechScriptPrompts._get_audience_description(
            customization.get('target_audience', 'general_public'),
            language=language,
        )
        complexity_desc = SpeechScriptPrompts._get_complexity_description(
            customization.get('language_complexity', 'moderate'),
            language=language,
        )
        custom_style_prompt = (customization.get('custom_style_prompt') or '').strip()

        if language == "en":
            extra_style = f"\nAdditional style constraints: {custom_style_prompt}" if custom_style_prompt else ""
            return f"""Follow the Humanizer-zh workflow strictly to rewrite this presentation script into natural spoken language.

Original script:
{original_script}

Context:
- Tone: {tone_desc}
- Audience: {audience_desc}
- Complexity: {complexity_desc}
- Speaking pace: {customization.get('speaking_pace', 'normal')}
{extra_style}

Required workflow:
1. Identify AI patterns in the original text.
2. Rewrite only the problematic phrasing while preserving meaning.
3. Keep the intended tone and speaker role.
4. Add real human rhythm and texture where appropriate.
5. Run a final self-check before answering.

Core principles from Humanizer-zh:
- Delete filler phrases and empty emphasis.
- Break formulaic structures and avoid staged contrast patterns.
- Vary rhythm with mixed sentence lengths.
- Trust the listener and state things directly.
- Remove quote-like “golden lines” if they sound overly polished.

Common AI patterns to remove:
- exaggerated significance or symbolic meaning
- promotional or slogan-like language
- vague attribution such as “experts say” without substance
- excessive connective adverbs like “furthermore” used mechanically
- repeated binary contrast structures
- overuse of dashes for dramatic reveals

Human voice requirements:
- Keep all facts and conclusions accurate. Do not invent anything.
- Make it sound like something a real presenter would actually say out loud.
- Prefer concrete phrasing over abstract summary language.
- Allow light natural texture, but do not become slang-heavy, jokey, or unprofessional.
- Start directly with the content. Do not begin with filler lead-ins like "Okay,", "So,", "Now,", or "Next," unless the context genuinely requires it.
- If the original is already fairly natural, only revise what needs revision.

Final self-check:
- avoid three sentences in a row with similar length
- avoid mechanical transitions
- avoid over-explaining obvious points
- avoid polished slogan endings
- ensure the script sounds natural when read aloud

Output rules:
- Return only the rewritten plain text.
- No Markdown, no headings, no bullet lists, no numbering, no commentary.
- Keep normal punctuation for TTS rhythm.
- Do not add speaker labels or stage directions.
"""

        extra_style = f"\n补充风格要求：{custom_style_prompt}" if custom_style_prompt else ""
        return f"""请严格按照 Humanizer-zh SKILL.md 的处理方法，把下面这段演讲稿改写成人会自然说出来的话。

原始演讲稿：
{original_script}

当前上下文：
- 语调风格：{tone_desc}
- 目标受众：{audience_desc}
- 语言复杂度：{complexity_desc}
- 演讲节奏：{customization.get('speaking_pace', 'normal')}
{extra_style}

必须遵守的处理流程：
1. 先识别原文里的 AI 写作模式。
2. 只重写有问题的部分，但整体上让全文更自然。
3. 保留原意、事实、判断和核心结构，不要编造新信息。
4. 保持原本应有的语气和讲述身份。
5. 在输出前按快速检查清单做一次自检。

Humanizer-zh 的五条核心原则：
- 删除填充短语：去掉开场白、强调性拐杖词、空泛套话。
- 打破公式结构：避免“不仅……而且……”“这不只是……而是……”这类模板结构。
- 变化节奏：混合长短句，不要连续多个句子长度和结构都差不多。
- 信任听众：直接陈述，不要过度解释、软化、铺垫和手把手引导。
- 删除金句：如果一句话听起来像刻意做成可引用的口号，就重写它。

重点清理这些 Humanizer-zh 明确关注的模式：
- 过度强调意义、象征意义、历史地位、关键转折
- 宣传腔、广告腔、空泛拔高、过度正面包装
- 模糊归因，比如“专家认为”“行业观察显示”但没有实质信息
- 高频 AI 连接词和书面套话，比如“此外”“值得注意的是”“我们不难发现”
- 机械的三段式并列、二元对比、否定式排比
- 为了显得有力量而滥用破折号、总结句、收束金句

“注入灵魂”时要注意：
- 让文本像真实讲解，而不是百科词条或公关稿。
- 可以让句子更有呼吸感和口语节奏，但不要油腻，不要网络梗，不要故作夸张。
- 优先用具体表达替代抽象判断。
- 适合演讲口播和 TTS 朗读，听起来顺，落地，像真人。
- 如果原文已经比较自然，只做必要改动，不要为了“人话化”而过度改写。

输出前请按这份快速检查清单自检：
- 是否连续三个句子长度接近、结构相似？如果是，打断它。
- 是否用了机械连接词，如“此外”“然后”“同时”但删掉也不影响理解？删掉。
- 是否用了破折号做戏剧性揭示？去掉。
- 是否在解释显而易见的隐喻或比喻？删掉。
- 是否用了“三项并列”但两项或四项更自然？改掉。
- 是否有一句话像口号、像总结金句？重写。

输出要求：
- 只输出改写后的纯文本，不要解释，不要分析，不要评分，不要标题，不要列表，不要编号。
- 保留正常中文标点，方便口播停连。
- 开头直接进入内容，不要以“好”“好的”“那么”“接下来”“下面我来讲”等口头起手式开场，除非原文上下文确实需要承接。
- 不要添加“讲解者：”“下面我来讲”等额外标签，除非原文本来就需要。

请直接输出最终的人话化演讲稿。"""
    
    @staticmethod
    def get_opening_remarks_prompt(
        project_info: Dict[str, Any],
        customization: Dict[str, Any]
    ) -> str:
        """Generate prompt for opening remarks"""
        language = (customization.get("language") or "zh").strip().lower()
        
        tone_desc = SpeechScriptPrompts._get_tone_description(customization.get('tone', 'conversational'), language=language)
        audience_desc = SpeechScriptPrompts._get_audience_description(customization.get('target_audience', 'general_public'), language=language)
        
        prompt = f"""请为以下演示生成一段精彩的开场白：

演示信息：
- 主题：{project_info.get('topic', '')}
- 场景：{project_info.get('scenario', '')}
- 目标受众：{customization.get('target_audience', 'general_public')}
- 语言风格：{customization.get('tone', 'conversational')}
- 输出语言：{language}

开场白要求：
1. 语调风格：{tone_desc}
2. 目标受众：{audience_desc}
3. 时长控制在1-2分钟
4. 能够吸引听众注意力
5. 简要介绍演示主题和价值
6. 与听众建立连接
7. 为后续内容做好铺垫

生成要求：
- 使用自然的口语化表达
- 可以包含问候语、自我介绍（如需要）
- 可以使用引人入胜的开场方式（问题、故事、数据等）
- 要体现演讲者的专业性和亲和力
- 语言要符合指定的风格和受众特点

TTS输出规范：只输出纯文本，不要 Markdown/排版；不要标题/列表/编号；保留正常标点；不要使用 Markdown 排版符号（如 #、-/*/1. 列表、反引号`、引用符 >、表格竖线 | 等）。
请直接输出开场白内容，使用自然流畅的演讲语言。"""
        
        return prompt
    
    @staticmethod
    def get_closing_remarks_prompt(
        project_info: Dict[str, Any],
        customization: Dict[str, Any]
    ) -> str:
        """Generate prompt for closing remarks"""
        
        tone_desc = SpeechScriptPrompts._get_tone_description(customization.get('tone', 'conversational'))
        audience_desc = SpeechScriptPrompts._get_audience_description(customization.get('target_audience', 'general_public'))
        
        prompt = f"""请为以下演示生成一段有力的结束语：

演示信息：
- 主题：{project_info.get('topic', '')}
- 场景：{project_info.get('scenario', '')}
- 目标受众：{customization.get('target_audience', 'general_public')}
- 语言风格：{customization.get('tone', 'conversational')}

结束语要求：
1. 语调风格：{tone_desc}
2. 目标受众：{audience_desc}
3. 时长控制在1-2分钟
4. 总结演示的核心要点
5. 强化主要信息和价值
6. 给听众留下深刻印象
7. 包含行动号召或下一步建议
8. 以积极正面的语调结束

生成要求：
- 使用自然的口语化表达
- 可以回顾关键要点，但要简洁
- 可以包含感谢语和互动邀请
- 要给听众明确的下一步指引
- 语言要符合指定的风格和受众特点
- 结尾要有力量感和感召力

TTS输出规范：只输出纯文本，不要 Markdown/排版；不要标题/列表/编号；保留正常标点；不要使用 Markdown 排版符号（如 #、-/*/1. 列表、反引号`、引用符 >、表格竖线 | 等）。
请直接输出结束语内容，使用自然流畅的演讲语言。"""
        
        return prompt
    
    @staticmethod
    def get_transition_enhancement_prompt(
        current_script: str,
        previous_slide_context: str,
        next_slide_context: str
    ) -> str:
        """Generate prompt for enhancing transitions between slides"""
        
        prompt = f"""请为以下演讲稿添加自然的过渡语句，使其与前后内容更好地连接：

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

TTS输出规范：只输出纯文本，不要 Markdown/排版；不要标题/列表/编号；保留正常标点；不要使用 Markdown 排版符号（如 #、-/*/1. 列表、反引号`、引用符 >、表格竖线 | 等）。
请输出增强过渡后的完整演讲稿。"""
        
        return prompt
    
    @staticmethod
    def _get_tone_description(tone: str, *, language: str = "zh") -> str:
        """Get description for speech tone"""
        if (language or "zh").lower() == "en":
            descriptions = {
                'formal': "formal, precise, business-like",
                'casual': "light, natural, friendly",
                'persuasive': "persuasive and motivating",
                'educational': "educational and explanatory",
                'conversational': "conversational and engaging",
                'authoritative': "authoritative and expert-like",
                'storytelling': "storytelling, vivid and engaging",
            }
            return descriptions.get(tone, "natural and fluent")

        descriptions = {
            'formal': "正式、严谨、专业的商务语调",
            'casual': "轻松、自然、亲切的日常语调",
            'persuasive': "有说服力、激励性的语调",
            'educational': "教学式、解释性的语调",
            'conversational': "对话式、互动性的语调",
            'authoritative': "权威、自信、专家式的语调",
            'storytelling': "叙事性、生动有趣的语调"
        }
        return descriptions.get(tone, "自然流畅的语调")
    
    @staticmethod
    def _get_audience_description(audience: str, *, language: str = "zh") -> str:
        """Get description for target audience"""
        if (language or "zh").lower() == "en":
            descriptions = {
                'executives': "business executives and decision-makers (focus on outcomes)",
                'students': "students (clear explanations and guidance)",
                'general_public': "general audience (plain language)",
                'technical_experts': "technical experts (can include technical terms)",
                'colleagues': "colleagues/peers (collaborative tone)",
                'clients': "clients (value and benefits oriented)",
                'investors': "investors (business value and returns)",
            }
            return descriptions.get(audience, "general audience")

        descriptions = {
            'executives': "企业高管和决策者，注重效率和结果",
            'students': "学生群体，需要清晰的解释和引导",
            'general_public': "普通大众，使用通俗易懂的语言",
            'technical_experts': "技术专家，可以使用专业术语",
            'colleagues': "同事和合作伙伴，平等交流的语调",
            'clients': "客户群体，注重价值和利益",
            'investors': "投资者，关注商业价值和回报"
        }
        return descriptions.get(audience, "一般听众")
    
    @staticmethod
    def _get_complexity_description(complexity: str, *, language: str = "zh") -> str:
        """Get description for language complexity"""
        if (language or "zh").lower() == "en":
            descriptions = {
                'simple': "simple and easy to understand",
                'moderate': "moderately complex, balanced",
                'advanced': "advanced and technical when appropriate",
            }
            return descriptions.get(complexity, "moderately complex")

        descriptions = {
            'simple': "简单易懂，避免复杂词汇和长句",
            'moderate': "适中复杂度，平衡专业性和可理解性",
            'advanced': "较高复杂度，可以使用专业术语和复杂概念"
        }
        return descriptions.get(complexity, "适中复杂度")
    
    @staticmethod
    def get_script_refinement_prompt(
        original_script: str,
        refinement_request: str,
        customization: Dict[str, Any]
    ) -> str:
        """Generate prompt for refining existing speech script"""
        
        tone_desc = SpeechScriptPrompts._get_tone_description(customization.get('tone', 'conversational'))
        audience_desc = SpeechScriptPrompts._get_audience_description(customization.get('target_audience', 'general_public'))
        
        prompt = f"""请根据用户要求优化以下演讲稿：

原始演讲稿：
{original_script}

用户优化要求：
{refinement_request}

当前设置：
- 语调风格：{tone_desc}
- 目标受众：{audience_desc}
- 语言复杂度：{SpeechScriptPrompts._get_complexity_description(customization.get('language_complexity', 'moderate'))}

优化要求：
1. 保持演讲稿的核心信息和结构
2. 根据用户要求进行针对性调整
3. 确保语言风格与设置保持一致
4. 使用自然的口语化表达
5. 保持适当的演讲时长

请输出优化后的演讲稿。"""
        
        return prompt
