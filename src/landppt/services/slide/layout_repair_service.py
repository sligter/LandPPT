import asyncio
import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from ...ai import AIMessage, MessageRole, get_ai_provider
from ...ai.base import ImageContent, TextContent
from ...core.config import ai_config
from ..pyppeteer_pdf_converter import get_pdf_converter


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ..enhanced_ppt_service import EnhancedPPTService


class LayoutRepairService:
    """Own slide layout inspection, vision analysis, and repair prompts."""

    def __init__(self, service: "EnhancedPPTService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    @staticmethod
    def _should_skip_layout_repair(inspection_report: str) -> bool:
            """Determine whether layout repair can be skipped based on severity assessment."""
            if not inspection_report:
                return False

            import re

            lowered = inspection_report.lower()

            # Quick allow-list: if report mentions medium/high anywhere, perform repair
            if any(level in lowered for level in ("medium", "high")):
                return False

            # Look for structured severity section, ensure all entries are low
            inline_severity = re.findall(
                r"-\s*severity\s*:\s*([^\n\r]+)",
                inspection_report,
                flags=re.IGNORECASE,
            )

            if inline_severity:
                for entry in inline_severity:
                    levels = re.findall(r"(high|medium|low)", entry, flags=re.IGNORECASE)
                    if not levels:
                        return False
                    if any(level.lower() != "low" for level in levels):
                        return False
                return True

            severity_sections = re.findall(
                r"-\s*severity\s*:\s*((?:\n\s*-\s*[a-zA-Z]+)+)",
                inspection_report,
                flags=re.IGNORECASE,
            )

            if severity_sections:
                for section in severity_sections:
                    levels = re.findall(r"-\s*([a-zA-Z]+)", section, flags=re.IGNORECASE)
                    normalized = {level.lower() for level in levels}
                    if not normalized:
                        return False
                    if normalized - {"low"}:
                        return False
                return True

            # No recognizable severity info -> fall back to repairing
            return False

    def _inject_anti_overflow_css(self, html_content: str) -> str:
            """注入防内容溢出的 CSS 样式，确保所有文字完整显示

            在 </head> 前注入强制样式，覆盖 LLM 生成的 overflow:hidden 等截断规则。
            """
            import re

            anti_overflow_css = """
    <style id="anti-overflow-fix">
      /*
       * 目标：防止 LLM 生成的 overflow:hidden / text-overflow:ellipsis
       *       粗暴截断卡片内的正文文字。
       * 原则：只解锁"叶子级内容容器"的文字截断，
       *       绝不触碰画布根容器、flex 主轴容器和安全裁切层的 overflow。
       */

      /* 1. 行内文字元素：确保文字本身不被截断 */
      p, span, li, td, th, label,
      h1, h2, h3, h4, h5, h6, a {
        text-overflow: unset !important;
        -webkit-line-clamp: unset !important;
      }

      /* 2. 叶子级内容容器：解除 LLM 可能加的 overflow:hidden
       *    排除画布骨架（main-content / content-layer / slide-root 等） */
      [class*="card"] > *,
      [class*="item"] > p, [class*="item"] > span,
      [class*="tile"] > *, [class*="panel"] > *,
      [class*="desc"], [class*="info"] > p {
        overflow: visible !important;
        text-overflow: unset !important;
        -webkit-line-clamp: unset !important;
      }

      /* 3. 明确保留画布骨架的裁切能力 */
      .content-layer,
      [data-content-layer],
      .main-content,
      [class*="slide-root"],
      #canvas,
      body > div {
        /* 不覆盖——保持原有 overflow 行为 */
      }
    </style>
    """

            if '</head>' in html_content.lower():
                # 在 </head> 前注入
                html_content = re.sub(
                    r'(</head>)',
                    anti_overflow_css + r'\1',
                    html_content,
                    count=1,
                    flags=re.IGNORECASE
                )
            elif '<body' in html_content.lower():
                # 没有 </head>，在 <body 前注入
                html_content = re.sub(
                    r'(<body)',
                    anti_overflow_css + r'\1',
                    html_content,
                    count=1,
                    flags=re.IGNORECASE
                )

            return html_content

    async def _apply_auto_layout_repair(
            self,
            html_content: str,
            slide_data: Dict[str, Any],
            page_number: int,
            total_pages: int
        ) -> str:
            """Invoke multimodal vision model to inspect and repair layout when feature flag is enabled."""
            # 优先从用户数据库配置读取功能开关和视觉分析模型配置
            feature_flag_enabled = False
            vision_provider_name = None
            vision_model_name = None

            if self.user_id is not None:
                try:
                    from ..db_config_service import get_db_config_service
                    db_config_service = get_db_config_service()
                    user_config = await db_config_service.get_all_config(user_id=self.user_id)

                    # 从数据库读取功能开关
                    feature_flag_enabled = user_config.get("enable_auto_layout_repair", False)
                    if isinstance(feature_flag_enabled, str):
                        feature_flag_enabled = feature_flag_enabled.lower() in {"true", "1", "yes", "on"}

                    # 从数据库读取视觉分析模型配置
                    vision_provider_name = user_config.get("vision_analysis_model_provider")
                    vision_model_name = user_config.get("vision_analysis_model_name")

                    logger.info(f"Auto layout repair config from database (user_id={self.user_id}): enabled={feature_flag_enabled}, provider={vision_provider_name}, model={vision_model_name}")
                except Exception as db_error:
                    logger.warning(f"Failed to read auto layout config from database: {db_error}")

            # 如果数据库没有配置，回退到全局配置和环境变量
            if not feature_flag_enabled:
                feature_flag_enabled = getattr(ai_config, "enable_auto_layout_repair", False)
                env_override = os.getenv("ENABLE_AUTO_LAYOUT_REPAIR")
                if env_override is not None:
                    feature_flag_enabled = str(env_override).lower() in {"true", "1", "yes", "on"}

            logger.info("Auto layout repair feature flag enabled: %s", feature_flag_enabled)
            if not html_content or not feature_flag_enabled:
                return html_content

            try:
                # 优先使用异步方法获取用户配置的视觉分析提供者
                vision_provider, vision_settings = await self._get_role_provider_async("vision_analysis")
            except ValueError as role_error:
                # 如果数据库没有配置，使用回退逻辑
                if not vision_provider_name:
                    vision_provider_name = getattr(ai_config, "vision_analysis_model_provider", None)
                if not vision_model_name:
                    vision_model_name = getattr(ai_config, "vision_analysis_model_name", None)

                if not vision_provider_name:
                    vision_provider_name = os.getenv("VISION_ANALYSIS_MODEL_PROVIDER")
                if not vision_model_name:
                    vision_model_name = os.getenv("VISION_ANALYSIS_MODEL_NAME")

                if vision_provider_name:
                    try:
                        vision_provider_name = vision_provider_name.lower()
                        # 优先从用户配置获取提供者
                        if self.user_id is not None:
                            from ..db_config_service import get_user_ai_provider
                            vision_provider = await get_user_ai_provider(self.user_id, vision_provider_name)
                        else:
                            vision_provider = get_ai_provider(vision_provider_name)
                        vision_settings = {
                            "provider": vision_provider_name,
                            "model": vision_model_name,
                            "default_model": getattr(vision_provider, "model", None),
                        }
                        logger.info(
                            "Vision analysis role fallback in use: provider=%s model=%s",
                            vision_provider_name,
                            vision_model_name,
                        )
                    except Exception as provider_error:  # noqa: BLE001
                        logger.warning(
                            "Failed to initialize vision analysis provider (%s): %s",
                            vision_provider_name,
                            provider_error,
                            exc_info=True,
                        )
                        logger.info("Skipping auto layout repair due to provider initialization failure")
                        return html_content
                else:
                    logger.info(
                        "Vision analysis role not configured (missing provider). Original error: %s",
                        role_error,
                    )
                    return html_content


            try:
                pdf_converter = get_pdf_converter()
                if not pdf_converter.is_available():
                    logger.debug("PDF converter unavailable, skipping auto layout repair")
                    return html_content

                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    html_path = tmp_path / "slide.html"
                    screenshot_path = tmp_path / "slide.png"

                    html_path.write_text(html_content, encoding="utf-8")

                    screenshot_ok = await pdf_converter.screenshot_html(
                        str(html_path),
                        str(screenshot_path),
                        width=1280,
                        height=720
                    )

                    if not screenshot_ok or not screenshot_path.exists():
                        logger.warning("Auto layout repair skipped: screenshot capture failed")
                        return html_content

                    try:
                        # 调试
                        # debug_dir = self._get_auto_layout_debug_dir()
                        # timestamp_label = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        # debug_html_path = debug_dir / f"{timestamp_label}_slide{page_number}.html"
                        # debug_png_path = debug_dir / f"{timestamp_label}_slide{page_number}.png"

                        # shutil.copy2(html_path, debug_html_path)
                        # shutil.copy2(screenshot_path, debug_png_path)

                        logger.debug(
                            "Persisted auto layout debug assets for slide %s: html=%s screenshot=%s",
                            page_number,
                            # debug_html_path,
                            # debug_png_path
                        )
                    except Exception as debug_copy_error:  # noqa: BLE001
                        logger.warning(
                            "Failed to persist auto layout debug assets for slide %s: %s",
                            page_number,
                            debug_copy_error,
                            exc_info=True
                        )

                    screenshot_b64 = base64.b64encode(screenshot_path.read_bytes()).decode("utf-8")

                inspection_prompt = self._build_layout_inspection_prompt(slide_data, page_number, total_pages)

                messages = [
                    AIMessage(
                        role=MessageRole.SYSTEM,
                        content="You are an expert presentation designer. Inspect slides for layout issues and respond with actionable insights."
                    ),
                    AIMessage(
                        role=MessageRole.USER,
                        content=[
                            TextContent(text=inspection_prompt),
                            ImageContent(image_url={"url": f"data:image/png;base64,{screenshot_b64}"})
                        ]
                    )
                ]

                model_name = vision_settings.get("model") or vision_settings.get("default_model")
                inspection_response = None
                for attempt in range(3):
                    try:
                        inspection_response = await vision_provider.chat_completion(messages=messages, model=model_name)
                        if inspection_response and getattr(inspection_response, "content", None):
                            break
                        raise ValueError("Vision provider returned empty response")
                    except Exception as vision_error:
                        logger.warning(
                            "Vision inspection attempt %s failed for slide %s: %s",
                            attempt + 1,
                            page_number,
                            vision_error,
                            exc_info=True
                        )
                        inspection_response = None
                        if attempt < 2:
                            await asyncio.sleep(0.5 * (attempt + 1))

                if not inspection_response or not getattr(inspection_response, "content", None):
                    logger.error(
                        "Vision inspection could not be completed after retries for slide %s, skipping repair",
                        page_number
                    )
                    return html_content

                inspection_report = self._strip_think_tags(inspection_response.content)
                logger.info(
                    "Vision inspection response for slide %s: %s",
                    page_number,
                    inspection_report[:1000]
                )

                if not inspection_report:
                    logger.debug("Vision analysis returned empty report, keeping original HTML")
                    return html_content

                if self._should_skip_layout_repair(inspection_report):
                    logger.info(
                        "Skipping auto layout repair for slide %s due to low-severity findings",
                        page_number
                    )
                    return html_content

                repair_prompt = self._build_layout_repair_prompt(html_content, inspection_report)
                repair_response = None
                for attempt in range(3):
                    try:
                        repair_response = await self._text_completion_for_role(
                            "slide_generation",
                            prompt=repair_prompt,
                            temperature=min(0.5, max(0.1, ai_config.temperature * 0.5))
                        )
                        if repair_response and getattr(repair_response, "content", None):
                            break
                        raise ValueError("Layout repair model returned empty response")
                    except Exception as repair_error:
                        logger.warning(
                            "Layout repair attempt %s failed for slide %s: %s",
                            attempt + 1,
                            page_number,
                            repair_error,
                            exc_info=True
                        )
                        repair_response = None
                        if attempt < 2:
                            await asyncio.sleep(0.5 * (attempt + 1))

                if not repair_response or not getattr(repair_response, "content", None):
                    logger.error(
                        "Layout repair could not be completed after retries for slide %s, returning original HTML",
                        page_number
                    )
                    return html_content

                repair_content = self._strip_think_tags(repair_response.content)
                logger.debug(
                    "Layout repair response for slide %s: %s",
                    page_number,
                    repair_content[:1000]
                )

                repaired_html = self._clean_html_response(repair_content)
                if repaired_html and repaired_html.strip() and repaired_html.strip() != html_content.strip():
                    logger.info(f"Auto layout repair applied for slide {page_number}")
                    return repaired_html

                logger.debug("Auto layout repair produced no improvements, keeping original HTML")

            except Exception as e:
                logger.error(f"Auto layout repair failed for slide {page_number}: {e}", exc_info=True)

            return html_content

    def _build_layout_inspection_prompt(
            self,
            slide_data: Dict[str, Any],
            page_number: int,
            total_pages: int
        ) -> str:
            """Build prompt for multimodal layout inspection."""
            title = slide_data.get("title", "")
            subtitle = slide_data.get("subtitle", "")
            body = slide_data.get("content", "") or slide_data.get("description", "")
            bullet_points = slide_data.get("bullet_points") or slide_data.get("content_points") or []
            bullet_text = "\n".join(f"- {point}" for point in bullet_points)

            return (
                f"幻灯片编号：第{page_number}页\n"
                f"标题：{title}\n"
                f"正文摘要：{body}\n"
                f"要点：\n{bullet_text}\n\n"
                "请结合截图检查以下项目：\n"
                "1. 文本是否被遮挡、超出或断裂\n"
                "2. 元素是否重叠、错位或超出画布\n"
                "3. 布局和留白是否平衡，避免大片空白\n"
                "4. 颜色对比与字号是否影响可读性\n\n"
                "5. 卡片或图片布局是否超出画布或显示不全\n"
                "6. 内容是否完整，是否出现了滚动条(严禁出现滚动条)\n"
                "7. 页码是否完整落在其安全区内，是否存在贴边、换行、漂移或被正文侵占的问题\n"
                "8. 当前空间组织方式是否与内容量不匹配，是否需要切换为更紧凑的结构\n"
                "请输出结构化结果：\n"
                "- issues: 每个问题的描述与定位\n"
                "- recommendations: 对应的修复建议(页码仅在越界、贴边、换行、漂移或安全区被侵占时，允许建议调整其定位、安全边距、最大宽度以及与正文的关系；当现有布局不适配内容量时，应明确指出更适合的紧凑布局方向)\n"
                "- severity: high/medium/low\n"
            )

    def _build_layout_repair_prompt(self, original_html: str, inspection_report: str) -> str:
            """Prompt LLM to repair HTML based on inspection findings."""
            return (
                "你是资深前端工程师，请严格按照视觉检测报告中的每条建议对下方幻灯片 HTML 进行修改，"
                "确保 1280x720 画布内无遮挡、错位或溢出，并保持主题配色与结构一致。\n\n"
                "【视觉检测报告】\n"
                f"{inspection_report}\n\n"
                "【原始HTML】\n"
                "```html\n"
                f"{original_html}\n"
                "```\n\n"
                "输出要求（务必遵守）：\n"
                "- 直接返回一个 ```html ...``` 代码块，内容为完整、修复后的 HTML。\n"
                "- 除该代码块外禁止输出任何其他文字、说明、think 内容或总结。\n"
                "- 严禁出现滚动条，确保内容完整。\n"
                "- 仅针对检测报告指出的问题调整内容区布局/文案，避免无关元素的增删或样式重写。\n"
                "- 页眉区域：默认保持标题文案、字体族、主色、字重和对齐方式不变；如内容区高度不足，可优先调整 header 容器的 margin/padding、标题上下留白和标题区占高。只有在仍无法消除溢出时，才允许对标题字号、行高做小幅收紧，且不得改变整体风格。\n"
                "- 如果原始 HTML 中页码已通过 `position:absolute` 或等价 inline style 脱离文档流，这是有意设计；修复时必须保持这种结构，不得改回 flex/grid 正文流。\n"
                "- 页脚区域：默认保持页码的视觉风格、文本内容和层级不变；只有当页码越界、贴边、换行、漂移、被遮挡或安全区被侵占时，才允许做最小化修复。\n"
                "- 页码相关的最小化修复只允许调整其容器定位方式、安全边距、最大宽度、与正文的间隔关系，必要时可轻微收紧内边距或缩放；不要把页码改成新的样式体系。\n"
                "- 类名仅用于结构说明；若原始 HTML 用 inline style 表达了与上述相同的页码独立定位关系，应视为同一结构继续保留。\n"
                "- 处理溢出时遵循统一顺序：先减装饰层和特效，再收紧 gap/padding/空白，再压缩辅助信息与媒体占比，再减少分栏数、卡片数或切换到更紧凑的空间组织方式，最后才小幅缩字。\n"
                "- 如果当前空间组织方式与内容量明显不匹配，允许切换为更紧凑的同风格结构；不要为了保住原布局而让内容被裁切。\n"
            )
