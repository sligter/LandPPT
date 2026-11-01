"""
PPT系统提示词和默认配置
包含所有系统级别的提示词和默认配置
"""

import os
from pathlib import Path


class SystemPrompts:
    """PPT系统提示词和默认配置集合"""

    # 稳定前缀 —— 资源/画布/格式等系统级约束放在这里，一次声明全局生效
    CACHE_STABLE_PREFIX = """
角色：演示文稿规划、内容与 HTML 幻灯片生成助手。

全局约束：
- 模板与页面设计铁律：避免不必要的次要标签和描述，让布局本身来传达信息。
- 1280×720 固定画布，overflow:hidden 仅用于画布根容器与安全裁切层。整个页面不允许出现任何滚动条。
- 不引入海外公共 CDN 资源（fonts.googleapis.com、cdn.jsdelivr.net、unpkg.com、cdnjs.cloudflare.com、use.fontawesome.com 等）。
- 不通过海外外链加载字体（如 Google Fonts、Adobe Fonts）。默认使用系统字体栈：正文 system-ui, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif；等宽 ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace。除非已提供可访问的 @font-face，否则不要在 CSS 中写未加载的 web font 名（如 DM Sans、Inter、JetBrains Mono）。
- 图标少量场景优先内联 SVG/CSS/Unicode，不为少量图标引入整套远程图标库。
- 图表可用 Chart.js/ECharts.js/D3.js，公式可用 MathJax，代码高亮可用 Prism.js；仅在确有需要时按需加载。
- 背景纹理、分隔线、装饰光效优先 CSS 或内联 SVG 实现。
- 事实准确、结构清晰、输出格式可解析。
- 若任务要求 JSON 或 HTML，只输出指定格式，不附加解释。"""

    @staticmethod
    def with_cache_prefix(task_prompt: str) -> str:
        """给系统提示词添加稳定前缀，提高多次调用的KV cache命中率。"""
        task_prompt = (task_prompt or "").strip()
        prefix = SystemPrompts.CACHE_STABLE_PREFIX.strip()
        if not task_prompt:
            return prefix
        if task_prompt.startswith(prefix):
            return task_prompt
        return f"{prefix}\n\n{task_prompt}"

    @staticmethod
    def with_text_cache_prefix(prompt: str) -> str:
        """给纯文本补全 prompt 添加稳定前缀。"""
        return SystemPrompts.with_cache_prefix(prompt)

    @staticmethod
    def normalize_messages_for_cache(messages):
        """确保聊天补全的首条 system 消息具备稳定前缀。"""
        from ...ai import AIMessage, MessageRole

        normalized = list(messages or [])
        if not normalized:
            return [AIMessage(role=MessageRole.SYSTEM,
                              content=SystemPrompts.CACHE_STABLE_PREFIX.strip())]

        first = normalized[0]
        if first.role == MessageRole.SYSTEM and isinstance(first.content, str):
            normalized[0] = AIMessage(
                role=first.role,
                content=SystemPrompts.with_cache_prefix(first.content),
                name=first.name,
            )
            return normalized

        normalized.insert(0, AIMessage(
            role=MessageRole.SYSTEM,
            content=SystemPrompts.CACHE_STABLE_PREFIX.strip(),
        ))
        return normalized

    # ----------------------------------------------------------------
    # 资源可达性与性能约束（保留供设计模块引用）
    # ----------------------------------------------------------------
    @staticmethod
    def get_resource_performance_prompt() -> str:
        """获取资源可达性与性能优化约束提示词"""
        return """**资源可达性与性能约束**：
- 不引入海外公共 CDN 资源（fonts.googleapis.com、cdn.jsdelivr.net、unpkg.com、cdnjs.cloudflare.com 等）。
- 默认使用系统字体栈；未通过 @font-face 实际加载的 web font 名不要写进 CSS。
- 图标少量场景优先内联 SVG/CSS/Unicode。
- 图表/公式/代码高亮仅在确有需要时按需加载，关闭非必要动画和重复初始化。
- 背景装饰优先 CSS 或内联 SVG 实现。"""

    # ----------------------------------------------------------------
    # 默认系统提示词
    # ----------------------------------------------------------------
    @staticmethod
    def get_default_ppt_system_prompt() -> str:
        return SystemPrompts.with_cache_prefix(
            "根据幻灯片内容生成高质量 HTML 页面。设计服务于内容表达，保持视觉层级清晰和整体风格统一。\n\n"
            + SystemPrompts.get_resource_performance_prompt())

    @staticmethod
    def get_keynote_style_prompt() -> str:
        return SystemPrompts.with_cache_prefix("""请生成Apple风格的发布会PPT页面：
1. 黑色背景，简洁现代的设计
2. 卡片式布局，突出重点信息
3. 使用科技蓝或品牌色作为高亮色
4. 大字号标题，清晰的视觉层级
5. 图标优先使用内联SVG或简洁几何图形，图表优先使用纯HTML/CSS/SVG实现
6. 结尾页（thankyou/conclusion类型）需设计得令人印象深刻：使用特殊背景效果、发光文字、动态装饰等

""" + SystemPrompts.get_resource_performance_prompt())

    @staticmethod
    def load_prompts_md_system_prompt() -> str:
        try:
            current_dir = Path(__file__).parent
            prompts_file = current_dir / "prompts.md"
            if prompts_file.exists():
                with open(prompts_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                return SystemPrompts.with_cache_prefix(content)
            else:
                return SystemPrompts.get_default_ppt_system_prompt()
        except Exception:
            return SystemPrompts.get_default_ppt_system_prompt()

    @staticmethod
    def get_ai_assistant_system_prompt() -> str:
        return SystemPrompts.with_cache_prefix(
            "PPT 制作助手。理解用户需求与受众，设计清晰信息架构，"
            "保持视觉风格统一，生成高质量 HTML/CSS 代码。")

    @staticmethod
    def get_html_generation_system_prompt() -> str:
        return SystemPrompts.with_cache_prefix(
            "生成 PPT 页面的 HTML 代码。使用语义化 HTML 和现代 CSS（Flexbox/Grid），"
            "保证代码质量和加载性能。\n\n"
            + SystemPrompts.get_resource_performance_prompt())

    @staticmethod
    def get_content_analysis_system_prompt() -> str:
        return SystemPrompts.with_cache_prefix(
            "分析和优化 PPT 内容。关注信息结构完整性、语言准确性、"
            "每页信息密度、受众适配和可视化机会。")

    @staticmethod
    def get_custom_style_prompt(custom_prompt: str) -> str:
        return SystemPrompts.with_cache_prefix(f"""
请根据以下自定义风格要求生成PPT页面：

{custom_prompt}

请确保生成的HTML页面符合上述风格要求，同时保持良好的可读性和用户体验。
""")
