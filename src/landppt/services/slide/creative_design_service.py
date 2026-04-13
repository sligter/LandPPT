import asyncio
import hashlib
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..prompts import prompts_manager


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ..enhanced_ppt_service import EnhancedPPTService


class CreativeDesignService:
    """Own creative design prompting, style gene extraction, and related caches."""

    _OWNER_CACHE_ATTRS = {
        "_cached_style_genes",
        "_cached_style_genes_and_guide",
        "_cached_global_constitutions",
        "_cached_page_creative_briefs",
        "_cached_slide_creative_guides",
        "_style_genes_ready_events",
        "_global_constitution_ready_events",
        "_page_creative_brief_ready_events",
        "_slide_creative_guide_ready_events",
        "_slide_guide_prewarm_tasks",
    }

    def __init__(self, service: "EnhancedPPTService"):
        object.__setattr__(self, "_service", service)

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def __setattr__(self, name: str, value):
        if name == "_service":
            object.__setattr__(self, name, value)
            return
        if name in self._OWNER_CACHE_ATTRS:
            setattr(self._service, name, value)
            return
        object.__setattr__(self, name, value)

    def _build_creative_slides_summary(self, all_slides: Optional[List[Dict[str, Any]]]) -> str:
        """Build a compact deck summary for project-level and slide-level prompts."""
        if not all_slides:
            return "(未提供完整大纲摘要)"

        lines: List[str] = []
        max_chars = 3000
        current_chars = 0

        for idx, slide in enumerate(all_slides, start=1):
            if not isinstance(slide, dict):
                continue

            title = str(slide.get("title") or f"第{idx}页").strip()
            slide_type = str(slide.get("slide_type") or slide.get("type") or "").strip()
            content_points = slide.get("content_points") or slide.get("content") or []

            if isinstance(content_points, list):
                point_texts: List[str] = []
                for item in content_points:
                    text = str(item).strip()
                    if text:
                        point_texts.append(text[:32])
                    if len(point_texts) >= 2:
                        break
                points_summary = "；".join(point_texts)
            else:
                points_summary = str(content_points).strip()[:80] if content_points else ""

            line_parts: List[str] = []
            if slide_type:
                line_parts.append(f"类型：{slide_type}")
            if points_summary:
                line_parts.append(f"要点：{points_summary}")

            line = f"{idx}. {title}"
            if line_parts:
                line += f"（{'；'.join(line_parts)}）"

            projected_chars = current_chars + len(line) + 1
            if projected_chars > max_chars:
                remaining = len(all_slides) - idx + 1
                lines.append(f"... 其余 {remaining} 页略写，请结合前文摘要延续整体节奏。")
                break

            lines.append(line)
            current_chars = projected_chars

        return "\n".join(lines) if lines else "(未提供完整大纲摘要)"

    async def _generate_slide_with_template(
        self,
        slide_data: Dict[str, Any],
        template: Dict[str, Any],
        page_number: int,
        total_pages: int,
        confirmed_requirements: Dict[str, Any],
        all_slides: List[Dict[str, Any]] = None,
        project_id: str = None,
    ) -> str:
        """Generate slide HTML from the selected template style."""
        try:
            template_html = template["html_template"]
            template_name = template.get("template_name", "未知模板")
            logger.info("使用模板 %s 作为风格参考生成第%s页", template_name, page_number)

            context = await self._build_creative_template_context(
                slide_data,
                template_html,
                template_name,
                page_number,
                total_pages,
                confirmed_requirements,
                all_slides=all_slides,
                project_id=project_id,
            )

            system_prompt = self._load_prompts_md_system_prompt()
            html_content = await self._generate_html_with_retry(
                context,
                system_prompt,
                slide_data,
                page_number,
                total_pages,
                max_retries=5,
            )

            if html_content:
                logger.info("成功使用模板 %s 风格生成第%s页", template_name, page_number)
                return html_content

            logger.warning("模板风格生成失败，回退到默认生成方式")
            fallback_html = await self._generate_fallback_slide_html(slide_data, page_number, total_pages)
            return fallback_html
        except Exception as exc:
            logger.error("使用模板风格生成幻灯片失败: %s", exc)
            fallback_html = await self._generate_fallback_slide_html(slide_data, page_number, total_pages)
            return fallback_html

    async def _build_creative_template_context(
        self,
        slide_data: Dict[str, Any],
        template_html: str,
        template_name: str,
        page_number: int,
        total_pages: int,
        confirmed_requirements: Dict[str, Any],
        all_slides: List[Dict[str, Any]] = None,
        project_id: str = None,
    ) -> str:
        """Build slide-generation prompt context with consistent style guidance."""
        del template_name

        if not project_id:
            project_id = confirmed_requirements.get("project_id")

        await self._ensure_slide_images_context(
            slide_data,
            confirmed_requirements,
            page_number,
            total_pages,
            template_html,
        )
        (
            style_genes,
            global_constitution,
            current_page_brief,
        ) = await self._get_creative_design_inputs(
            project_id,
            template_html,
            slide_data,
            page_number,
            total_pages,
            confirmed_requirements=confirmed_requirements,
            all_slides=all_slides,
        )

        images_collection = await self._process_slide_image(
            slide_data,
            confirmed_requirements,
            page_number,
            total_pages,
            template_html,
        )
        if images_collection and images_collection.total_count > 0:
            slide_data["images_collection"] = images_collection
            slide_data["images_info"] = images_collection.to_dict()
            slide_data["images_summary"] = images_collection.get_summary_for_ai()
            logger.info("为模板生成的第%s页添加%s张图片", page_number, images_collection.total_count)

        slide_title = slide_data.get("title", f"第{page_number}页")
        slide_type = slide_data.get("slide_type", "content")

        context_info = self._build_slide_context(slide_data, page_number, total_pages)

        return prompts_manager.get_creative_template_context_prompt(
            slide_data=slide_data,
            template_html=template_html,
            slide_title=slide_title,
            slide_type=slide_type,
            page_number=page_number,
            total_pages=total_pages,
            context_info=context_info,
            style_genes=style_genes,
            project_topic=confirmed_requirements.get("topic", ""),
            project_type=confirmed_requirements.get("type", ""),
            project_audience=confirmed_requirements.get("target_audience", ""),
            project_style=confirmed_requirements.get("ppt_style", "general"),
            global_constitution=global_constitution,
            current_page_brief=current_page_brief,
        )

    async def _extract_style_genes(self, template_html: str) -> str:
        """Extract core design genes from a template with AI fallback."""
        try:
            prompt = prompts_manager.get_style_genes_extraction_prompt(template_html)
            response = await self._text_completion_for_role(
                "creative",
                prompt=prompt,
                temperature=0.3,
            )
            ai_genes = self._strip_think_tags(response.content.strip())
            if not ai_genes or len(ai_genes) < 50:
                return self._extract_fallback_style_genes(template_html)
            return ai_genes
        except Exception as exc:
            logger.warning("AI提取设计基因失败: %s", exc)
            return self._extract_fallback_style_genes(template_html)

    def _extract_fallback_style_genes(self, template_html: str) -> str:
        """Fallback style-gene extraction based on template CSS."""
        genes: List[str] = []
        try:
            colors = re.findall(r"(?:background|color)[^:]*:\s*([^;]+)", template_html, re.IGNORECASE)
            if colors:
                genes.append(f"- 核心色彩：{', '.join(list(set(colors))[:3])}")

            fonts = re.findall(r"font-family[^:]*:\s*([^;]+)", template_html, re.IGNORECASE)
            if fonts:
                genes.append(f"- 字体系统：{fonts[0]}")

            if "display: flex" in template_html:
                genes.append("- 布局方式：Flexbox弹性布局")
            elif "display: grid" in template_html:
                genes.append("- 布局方式：Grid网格布局")

            design_elements: List[str] = []
            if "border-radius" in template_html:
                design_elements.append("圆角设计")
            if "box-shadow" in template_html:
                design_elements.append("阴影效果")
            if "gradient" in template_html:
                design_elements.append("渐变背景")
            if design_elements:
                genes.append(f"- 设计元素：{', '.join(design_elements)}")

            paddings = re.findall(r"padding[^:]*:\s*([^;]+)", template_html, re.IGNORECASE)
            if paddings:
                genes.append(f"- 间距模式：{paddings[0]}")
        except Exception as exc:
            logger.warning("基础提取设计基因时出错: %s", exc)
            genes.append("- 使用现代简洁的设计风格")

        return "\n".join(genes) if genes else "- 使用现代简洁的设计风格"

    async def _get_or_extract_style_genes(self, project_id: str, template_html: str, page_number: int) -> str:
        """Read or compute style genes, with shared cache for parallel slide generation."""
        default_genes = "- 使用现代简洁的设计风格\n- 保持页面整体一致性\n- 采用清晰的视觉层次"
        cache_attr = "_cached_style_genes"
        event_attr = "_style_genes_ready_events"

        if not template_html or not template_html.strip():
            return default_genes

        if not project_id:
            try:
                return await self._extract_style_genes(template_html)
            except Exception:
                return default_genes

        if hasattr(self, cache_attr) and project_id in getattr(self, cache_attr, {}):
            logger.info("从内存缓存获取项目 %s 的设计基因", project_id)
            return getattr(self, cache_attr)[project_id]

        style_genes = None
        if hasattr(self, "cache_dirs") and self.cache_dirs:
            cache_file = self.cache_dirs["style_genes"] / f"{project_id}_style_genes.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as handle:
                        cache_data = json.load(handle)
                        style_genes = cache_data.get("style_genes")
                        logger.info("从文件缓存获取项目 %s 的设计基因", project_id)
                except Exception as exc:
                    logger.warning("读取设计基因缓存文件失败: %s", exc)

        if style_genes:
            if not hasattr(self, cache_attr):
                setattr(self, cache_attr, {})
            getattr(self, cache_attr)[project_id] = style_genes
            return style_genes

        if not hasattr(self, event_attr):
            setattr(self, event_attr, {})
        events_dict = getattr(self, event_attr)

        if project_id not in events_dict:
            event = asyncio.Event()
            events_dict[project_id] = event
            try:
                style_genes = await self._extract_style_genes(template_html)

                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = style_genes

                if hasattr(self, "cache_dirs") and self.cache_dirs:
                    try:
                        cache_file = self.cache_dirs["style_genes"] / f"{project_id}_style_genes.json"
                        cache_data = {
                            "project_id": project_id,
                            "style_genes": style_genes,
                            "created_at": time.time(),
                            "template_hash": hashlib.md5(template_html.encode()).hexdigest()[:8],
                        }
                        with open(cache_file, "w", encoding="utf-8") as handle:
                            json.dump(cache_data, handle, ensure_ascii=False, indent=2)
                        logger.info("提取并缓存项目 %s 的设计基因到文件", project_id)
                    except Exception as exc:
                        logger.warning("保存设计基因缓存文件失败: %s", exc)

                logger.info("提取并缓存项目 %s 的设计基因", project_id)
                return style_genes
            except Exception as exc:
                logger.warning("提取项目 %s 的设计基因失败，使用默认值: %s", project_id, exc)
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = default_genes
                return default_genes
            finally:
                event.set()

        event = events_dict[project_id]
        if not event.is_set():
            try:
                await asyncio.wait_for(event.wait(), timeout=600.0)
            except asyncio.TimeoutError:
                logger.warning("第%s页等待设计基因缓存超时，使用默认设计基因", page_number)
                return default_genes

        return getattr(self, cache_attr, {}).get(project_id, default_genes)

    async def _prepare_project_creative_guidance(
        self,
        project_id: str,
        slide_data: Dict[str, Any],
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        total_pages: int = 1,
        template_html: str = "",
        prewarm_slide_guides: int = 0,
        async_prewarm_remaining_slide_guides: bool = False,
    ) -> str:
        """在生成前预热共享创意缓存，并可把剩余单页指导转为后台异步预热。"""
        if not template_html and project_id:
            try:
                selected_template = await self.get_selected_global_template(project_id)
                if selected_template:
                    template_html = selected_template.get("html_template", "") or ""
            except Exception as exc:
                logger.warning("预生成项目级创意指导时获取模板HTML失败: %s", exc)

        generation_config = await self._get_user_generation_config()
        enable_per_slide_guidance = bool(
            generation_config.get("enable_per_slide_creative_guidance", True)
        )

        first_slide = (all_slides[0] if all_slides else slide_data) or {}
        if template_html:
            await self._get_or_extract_style_genes(project_id, template_html, 1)

        global_constitution = await self._get_or_generate_global_constitution(
            project_id,
            confirmed_requirements=confirmed_requirements,
            template_html=template_html,
            total_pages=total_pages,
            first_slide_data=first_slide,
        )
        if enable_per_slide_guidance:
            slides_list = all_slides or ([slide_data] if slide_data else [])
            warmup_count = min(max(prewarm_slide_guides, 0), len(slides_list))
            if warmup_count > 0:
                for idx, current_slide in enumerate(slides_list[:warmup_count], start=1):
                    await self._get_or_generate_slide_creative_guide(
                        project_id,
                        slide_data=current_slide or {},
                        page_number=idx,
                        total_pages=total_pages,
                        confirmed_requirements=confirmed_requirements,
                        all_slides=slides_list,
                        template_html=template_html,
                    )

            remaining_start = warmup_count + 1
            if async_prewarm_remaining_slide_guides and remaining_start <= len(slides_list):
                self._schedule_remaining_slide_guides_prewarm(
                    project_id=project_id,
                    slides_list=slides_list,
                    start_page_number=remaining_start,
                    total_pages=total_pages,
                    confirmed_requirements=confirmed_requirements,
                    template_html=template_html,
                )
            elif len(slides_list) > warmup_count:
                logger.info(
                    "项目 %s 未预热的单页创意指导将按需生成，剩余页数：%s",
                    project_id,
                    len(slides_list) - warmup_count,
                )
            elif warmup_count == 0:
                logger.info(
                    "项目 %s 跳过单页创意指导同步预热，仅预热共享缓存以尽快开始流式生成",
                    project_id,
                )
        else:
            await self._get_or_generate_page_creative_briefs(
                project_id,
                confirmed_requirements=confirmed_requirements,
                all_slides=all_slides,
                total_pages=total_pages,
                global_constitution=global_constitution,
            )
        return global_constitution

    def _schedule_remaining_slide_guides_prewarm(
        self,
        project_id: str,
        slides_list: List[Dict[str, Any]],
        start_page_number: int,
        total_pages: int,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        template_html: str = "",
    ) -> None:
        """后台异步预热剩余页面的单页创意指导，避免阻塞首批流式输出。"""
        if not project_id or start_page_number > len(slides_list):
            return

        task_attr = "_slide_guide_prewarm_tasks"
        if not hasattr(self, task_attr):
            setattr(self, task_attr, {})
        tasks = getattr(self, task_attr)
        existing_task = tasks.get(project_id)
        if existing_task and not existing_task.done():
            logger.info("项目 %s 已有单页创意指导后台预热任务在运行，跳过重复启动", project_id)
            return

        async def run_prewarm() -> None:
            try:
                logger.info(
                    "项目 %s 启动剩余单页创意指导后台预热，起始页：%s，共 %s 页",
                    project_id,
                    start_page_number,
                    len(slides_list),
                )
                for page_number in range(start_page_number, len(slides_list) + 1):
                    current_slide = slides_list[page_number - 1] if page_number - 1 < len(slides_list) else {}
                    await self._get_or_generate_slide_creative_guide(
                        project_id,
                        slide_data=current_slide or {},
                        page_number=page_number,
                        total_pages=total_pages,
                        confirmed_requirements=confirmed_requirements,
                        all_slides=slides_list,
                        template_html=template_html,
                    )
                logger.info("项目 %s 剩余单页创意指导后台预热完成", project_id)
            except asyncio.CancelledError:
                logger.info("项目 %s 剩余单页创意指导后台预热已取消", project_id)
                raise
            except Exception as exc:
                logger.warning("项目 %s 剩余单页创意指导后台预热失败: %s", project_id, exc)
            finally:
                current_tasks = getattr(self, task_attr, None)
                if isinstance(current_tasks, dict):
                    current_tasks.pop(project_id, None)

        tasks[project_id] = asyncio.create_task(
            run_prewarm(),
            name=f"slide-guide-prewarm:{project_id}",
        )

    # ================================================================
    # 三层架构：全局宪法 + 页面类型指导 + 单页自由喂料
    # ================================================================

    async def _get_or_generate_global_constitution(
        self,
        project_id: str,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        template_html: str = "",
        total_pages: int = 1,
        first_slide_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Layer 1: Get or generate global visual constitution, with cache."""
        cache_attr = "_cached_global_constitutions"
        event_attr = "_global_constitution_ready_events"
        default = "- 使用模板配色和字体体系\n- 普通内容页保持模板标题锚点与页码锚点\n- 首尾页可自由设计"

        if not project_id:
            return await self._generate_global_constitution(
                confirmed_requirements, template_html, total_pages, first_slide_data)

        # Check in-memory cache
        if hasattr(self, cache_attr) and project_id in getattr(self, cache_attr, {}):
            return getattr(self, cache_attr)[project_id]

        # Check file cache
        if hasattr(self, "cache_dirs") and self.cache_dirs:
            cache_file = self.cache_dirs["style_genes"] / f"{project_id}_global_constitution.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        result = data.get("constitution", "")
                        if result:
                            if not hasattr(self, cache_attr):
                                setattr(self, cache_attr, {})
                            getattr(self, cache_attr)[project_id] = result
                            return result
                except Exception as exc:
                    logger.warning("读取全局宪法缓存失败: %s", exc)

        # Generate with event coordination
        if not hasattr(self, event_attr):
            setattr(self, event_attr, {})
        events = getattr(self, event_attr)

        if project_id not in events:
            event = asyncio.Event()
            events[project_id] = event
            try:
                result = await self._generate_global_constitution(
                    confirmed_requirements, template_html, total_pages, first_slide_data)
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = result
                # Save to file
                if hasattr(self, "cache_dirs") and self.cache_dirs:
                    try:
                        cache_file = self.cache_dirs["style_genes"] / f"{project_id}_global_constitution.json"
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump({"project_id": project_id, "constitution": result,
                                       "created_at": time.time()}, f, ensure_ascii=False, indent=2)
                    except Exception as exc:
                        logger.warning("保存全局宪法缓存失败: %s", exc)
                return result
            except Exception as exc:
                logger.warning("生成全局宪法失败: %s", exc)
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = default
                return default
            finally:
                event.set()

        # Wait for another coroutine to finish
        event = events[project_id]
        if not event.is_set():
            try:
                await asyncio.wait_for(event.wait(), timeout=600.0)
            except asyncio.TimeoutError:
                return default
        return getattr(self, cache_attr, {}).get(project_id, default)

    async def _generate_global_constitution(
        self,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        template_html: str = "",
        total_pages: int = 1,
        first_slide_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Call LLM to generate global visual constitution."""
        default = "- 使用模板配色和字体体系\n- 普通内容页保持模板标题锚点与页码锚点\n- 首尾页可自由设计"
        try:
            prompt = prompts_manager.get_global_visual_constitution_prompt(
                confirmed_requirements=confirmed_requirements or {},
                template_html=template_html,
                total_pages=total_pages,
                first_slide_data=first_slide_data,
            )
            response = await self._text_completion_for_role("creative", prompt=prompt, temperature=0.5)
            result = self._strip_think_tags(response.content.strip())
            return result if result and len(result) >= 50 else default
        except Exception as exc:
            logger.warning("AI 生成全局宪法失败: %s", exc)
            return default

    def _normalize_page_guidance_type(
        self,
        slide_data: Optional[Dict[str, Any]],
        page_number: int,
        total_pages: int,
    ) -> str:
        """统一页面类型，便于按类型生成和复用指导。"""
        return prompts_manager.design._normalize_page_guidance_type(
            slide_data or {}, page_number, total_pages
        )

    def _normalize_guidance_type_key(self, guidance_type: str) -> str:
        """规范化模型返回的页面类型键。"""
        return str(guidance_type or "content").strip().lower()

    async def _get_or_generate_page_creative_briefs(
        self,
        project_id: str,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        total_pages: int = 1,
        global_constitution: str = "",
    ) -> List[Dict[str, Any]]:
        """Layer 2：获取或生成按页面类型归纳的页面指导。"""
        cache_attr = "_cached_page_creative_briefs"
        event_attr = "_page_creative_brief_ready_events"

        if not project_id:
            return await self._generate_page_creative_briefs(
                confirmed_requirements, all_slides, total_pages, global_constitution)

        if hasattr(self, cache_attr) and project_id in getattr(self, cache_attr, {}):
            return getattr(self, cache_attr)[project_id]

        if hasattr(self, "cache_dirs") and self.cache_dirs:
            cache_file = self.cache_dirs["style_genes"] / f"{project_id}_page_type_guidance.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        briefs = data.get("page_type_guidance", []) or data.get("page_creative_briefs", [])
                        if briefs:
                            if not hasattr(self, cache_attr):
                                setattr(self, cache_attr, {})
                            getattr(self, cache_attr)[project_id] = briefs
                            return briefs
                except Exception as exc:
                    logger.warning("读取页面类型指导缓存失败: %s", exc)

        if not hasattr(self, event_attr):
            setattr(self, event_attr, {})
        events = getattr(self, event_attr)

        if project_id not in events:
            event = asyncio.Event()
            events[project_id] = event
            try:
                briefs = await self._generate_page_creative_briefs(
                    confirmed_requirements, all_slides, total_pages, global_constitution)
                if not briefs:
                    return []
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = briefs
                if hasattr(self, "cache_dirs") and self.cache_dirs:
                    try:
                        cache_file = self.cache_dirs["style_genes"] / f"{project_id}_page_type_guidance.json"
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump({"project_id": project_id, "page_type_guidance": briefs,
                                       "created_at": time.time()}, f, ensure_ascii=False, indent=2)
                    except Exception as exc:
                        logger.warning("保存页面类型指导缓存失败: %s", exc)
                return briefs
            except Exception as exc:
                logger.warning("生成页面类型指导失败: %s", exc)
                return []
            finally:
                event.set()

        event = events[project_id]
        if not event.is_set():
            try:
                await asyncio.wait_for(event.wait(), timeout=600.0)
            except asyncio.TimeoutError:
                return []
        return getattr(self, cache_attr, {}).get(project_id, [])

    async def _generate_page_creative_briefs(
        self,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        total_pages: int = 1,
        global_constitution: str = "",
    ) -> List[Dict[str, Any]]:
        """调用 LLM 生成按页面类型归纳的页面指导。"""
        try:
            prompt = prompts_manager.get_page_creative_briefs_prompt(
                confirmed_requirements=confirmed_requirements or {},
                all_slides=all_slides or [],
                total_pages=total_pages,
                global_constitution=global_constitution,
            )
            response = await self._text_completion_for_role("creative", prompt=prompt, temperature=0.85)
            raw = self._strip_think_tags(response.content.strip())
            guidance_entries = self._parse_page_creative_briefs(raw, all_slides, total_pages)
            if guidance_entries:
                logger.info("成功生成 %d 页可复用的页面类型指导", len(guidance_entries))
                return guidance_entries
            logger.warning("页面类型指导解析为空")
            return []
        except Exception as exc:
            logger.warning("生成页面类型指导失败: %s", exc)
            return []

    async def _generate_slide_creative_guide(
        self,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        template_html: str = "",
    ) -> str:
        """调用 LLM 生成当前页的详细创意指导。"""
        slides_summary = self._build_creative_slides_summary(all_slides)
        prompt = prompts_manager.get_slide_design_guide_prompt(
            slide_data=slide_data or {},
            confirmed_requirements=confirmed_requirements or {},
            slides_summary=slides_summary,
            page_number=page_number,
            total_pages=total_pages,
            template_html=template_html,
        )
        response = await self._text_completion_for_role("creative", prompt=prompt, temperature=0.85)
        return self._strip_think_tags(response.content.strip())

    async def _get_or_generate_slide_creative_guide(
        self,
        project_id: str,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        template_html: str = "",
    ) -> str:
        """Layer 2.5：获取或生成当前页的详细创意指导。"""
        cache_attr = "_cached_slide_creative_guides"
        event_attr = "_slide_creative_guide_ready_events"
        cache_key = f"{project_id}:{page_number}" if project_id else None
        fallback = self._generate_fallback_unified_guide(slide_data, page_number, total_pages)

        if not project_id:
            try:
                result = await self._generate_slide_creative_guide(
                    slide_data=slide_data,
                    page_number=page_number,
                    total_pages=total_pages,
                    confirmed_requirements=confirmed_requirements,
                    all_slides=all_slides,
                    template_html=template_html,
                )
                return result or fallback
            except Exception as exc:
                logger.warning("生成第%s页单页创意指导失败: %s", page_number, exc)
                return fallback

        if hasattr(self, cache_attr) and cache_key in getattr(self, cache_attr, {}):
            return getattr(self, cache_attr)[cache_key]

        if hasattr(self, "cache_dirs") and self.cache_dirs:
            cache_file = self.cache_dirs["style_genes"] / f"{project_id}_slide_{page_number}_creative_guide.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        guide = data.get("creative_guide", "")
                        if guide:
                            if not hasattr(self, cache_attr):
                                setattr(self, cache_attr, {})
                            getattr(self, cache_attr)[cache_key] = guide
                            return guide
                except Exception as exc:
                    logger.warning("读取单页创意指导缓存失败: %s", exc)

        if not hasattr(self, event_attr):
            setattr(self, event_attr, {})
        events = getattr(self, event_attr)

        if cache_key not in events:
            event = asyncio.Event()
            events[cache_key] = event
            try:
                guide = await self._generate_slide_creative_guide(
                    slide_data=slide_data,
                    page_number=page_number,
                    total_pages=total_pages,
                    confirmed_requirements=confirmed_requirements,
                    all_slides=all_slides,
                    template_html=template_html,
                )
                if not guide:
                    guide = fallback
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[cache_key] = guide
                if hasattr(self, "cache_dirs") and self.cache_dirs:
                    try:
                        cache_file = self.cache_dirs["style_genes"] / f"{project_id}_slide_{page_number}_creative_guide.json"
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(
                                {
                                    "project_id": project_id,
                                    "page_number": page_number,
                                    "creative_guide": guide,
                                    "created_at": time.time(),
                                },
                                f,
                                ensure_ascii=False,
                                indent=2,
                            )
                    except Exception as exc:
                        logger.warning("保存单页创意指导缓存失败: %s", exc)
                return guide
            except Exception as exc:
                logger.warning("生成第%s页单页创意指导失败: %s", page_number, exc)
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[cache_key] = fallback
                return fallback
            finally:
                event.set()

        event = events[cache_key]
        if not event.is_set():
            try:
                await asyncio.wait_for(event.wait(), timeout=600.0)
            except asyncio.TimeoutError:
                logger.warning("第%s页等待单页创意指导超时，使用 fallback", page_number)
                return fallback
        return getattr(self, cache_attr, {}).get(cache_key, fallback)

    def _parse_page_creative_briefs(
        self,
        raw_text: str,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        total_pages: int = 1,
    ) -> List[Dict[str, Any]]:
        """把模型返回的页面类型指导映射为逐页可用文本。"""
        if not raw_text:
            return []

        code_match = re.search(r"```(?:markdown|md|text)?\s*\n?(.*?)```", raw_text, re.DOTALL | re.IGNORECASE)
        text = code_match.group(1).strip() if code_match else raw_text.strip()
        heading_pattern = re.compile(
            r"(?mi)^##+\s*(?:TYPE|类型)\s*[:：]\s*([A-Za-z0-9_\-\u4e00-\u9fa5]+)\b.*$"
        )
        matches = list(heading_pattern.finditer(text))

        if not matches:
            if not text:
                return []

            result: List[Dict[str, Any]] = []
            for page_number in range(1, total_pages + 1):
                slide = (all_slides[page_number - 1] if all_slides and page_number - 1 < len(all_slides) else {}) or {}
                guidance_type = self._normalize_page_guidance_type(slide, page_number, total_pages)
                result.append({
                    "page": page_number,
                    "creative_brief": text,
                    "guidance_type": guidance_type,
                })
            return result

        parsed: Dict[str, str] = {}
        for idx, match in enumerate(matches):
            guidance_type = self._normalize_guidance_type_key(match.group(1))
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            section = text[start:end].strip()
            if section:
                parsed[guidance_type] = section

        result: List[Dict[str, Any]] = []
        for page_number in range(1, total_pages + 1):
            slide = (all_slides[page_number - 1] if all_slides and page_number - 1 < len(all_slides) else {}) or {}
            guidance_type = self._normalize_page_guidance_type(slide, page_number, total_pages)
            creative_brief = (
                parsed.get(guidance_type)
                or parsed.get("content")
                or ""
            )
            result.append({
                "page": page_number,
                "creative_brief": creative_brief,
                "guidance_type": guidance_type,
            })
        return result

    # ================================================================
    # _get_creative_design_inputs: 三层架构的组装点
    # ================================================================

    async def _get_creative_design_inputs(
        self,
        project_id: str,
        template_html: str,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
        confirmed_requirements: Optional[Dict[str, Any]] = None,
        all_slides: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[str, str, str]:
        """组装设计基因、全局宪法和当前页指导。"""
        style_genes = await self._get_or_extract_style_genes(project_id, template_html, page_number)

        first_slide = (all_slides[0] if all_slides else slide_data) or {}
        global_constitution = await self._get_or_generate_global_constitution(
            project_id,
            confirmed_requirements=confirmed_requirements,
            template_html=template_html,
            total_pages=total_pages,
            first_slide_data=first_slide,
        )

        generation_config = await self._get_user_generation_config()
        enable_per_slide_guidance = bool(
            generation_config.get("enable_per_slide_creative_guidance", True)
        )

        current_page_brief = ""
        if enable_per_slide_guidance:
            current_page_brief = await self._get_or_generate_slide_creative_guide(
                project_id,
                slide_data=slide_data,
                page_number=page_number,
                total_pages=total_pages,
                confirmed_requirements=confirmed_requirements,
                all_slides=all_slides,
                template_html=template_html,
            )
        else:
            page_creative_briefs = await self._get_or_generate_page_creative_briefs(
                project_id,
                confirmed_requirements=confirmed_requirements,
                all_slides=all_slides,
                total_pages=total_pages,
                global_constitution=global_constitution,
            )
            current_entry = next((p for p in page_creative_briefs if p.get("page") == page_number), None)
            current_page_brief = str((current_entry or {}).get("creative_brief") or "").strip()

        return style_genes, global_constitution, current_page_brief

    async def _extract_style_genes_and_guide(
        self,
        template_html: str,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
    ) -> tuple[str, str]:
        """Single-call extraction of style genes plus design guidance."""
        try:
            prompt = prompts_manager.get_combined_style_genes_and_guide_prompt(
                template_html,
                slide_data,
                page_number,
                total_pages,
            )
            response = await self._text_completion_for_role(
                "creative",
                prompt=prompt,
                temperature=1.0,
            )
            raw = self._strip_think_tags(response.content.strip())

            genes_match = re.search(r"===STYLE_GENES===(.*?)===END_STYLE_GENES===", raw, re.DOTALL)
            guide_match = re.search(r"===DESIGN_GUIDE===(.*?)===END_DESIGN_GUIDE===", raw, re.DOTALL)

            style_genes = genes_match.group(1).strip() if genes_match else ""
            design_guide = guide_match.group(1).strip() if guide_match else ""

            if not style_genes and not design_guide:
                logger.warning("合并提取解析失败，整个响应作为设计基因处理")
                style_genes = raw if len(raw) >= 50 else self._extract_fallback_style_genes(template_html)
                design_guide = self._generate_fallback_unified_guide(slide_data, page_number, total_pages)
            elif not style_genes:
                logger.warning("设计基因标记未找到，使用 fallback")
                style_genes = self._extract_fallback_style_genes(template_html)
            elif not design_guide:
                logger.warning("设计指导标记未找到，使用 fallback")
                design_guide = self._generate_fallback_unified_guide(slide_data, page_number, total_pages)

            logger.info("合并提取完成: style_genes=%s字符, design_guide=%s字符", len(style_genes), len(design_guide))
            return style_genes, design_guide
        except Exception as exc:
            logger.warning("合并提取设计基因和设计指导失败: %s", exc)
            return (
                self._extract_fallback_style_genes(template_html),
                self._generate_fallback_unified_guide(slide_data, page_number, total_pages),
            )

    async def _get_or_extract_style_genes_and_guide(
        self,
        project_id: str,
        template_html: str,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
    ) -> tuple[str, str]:
        """Cache-aware combined extraction for style genes and design guidance."""
        default_genes = "- 使用现代简洁的设计风格\n- 保持页面整体一致性\n- 采用清晰的视觉层次"
        cache_attr = "_cached_style_genes_and_guide"
        event_attr = "_style_genes_ready_events"

        if not project_id:
            logger.info("第%s页无 project_id，直接调用合并提取（无缓存）", page_number)
            return await self._extract_style_genes_and_guide(template_html, slide_data, page_number, total_pages)

        if hasattr(self, cache_attr) and project_id in getattr(self, cache_attr, {}):
            cached = getattr(self, cache_attr)[project_id]
            style_genes = cached["style_genes"]
            base_guide = cached["design_guide"]
            if page_number > 1:
                page_tips = self._generate_fallback_unified_guide(slide_data, page_number, total_pages)
                base_guide = base_guide + "\n\n**当前页面补充指导：**\n" + page_tips
            logger.info("从内存缓存获取项目 %s 的合并设计基因和指导", project_id)
            return style_genes, base_guide

        style_genes = None
        design_guide = None
        if project_id and hasattr(self, "cache_dirs") and self.cache_dirs:
            cache_file = self.cache_dirs["style_genes"] / f"{project_id}_combined_genes_guide.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as handle:
                        cache_data = json.load(handle)
                        style_genes = cache_data.get("style_genes")
                        design_guide = cache_data.get("design_guide")
                        logger.info("从文件缓存获取项目 %s 的合并设计基因和指导", project_id)
                except Exception as exc:
                    logger.warning("读取合并缓存文件失败: %s", exc)

        if style_genes and design_guide:
            if project_id:
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = {
                    "style_genes": style_genes,
                    "design_guide": design_guide,
                }
            if page_number > 1:
                page_tips = self._generate_fallback_unified_guide(slide_data, page_number, total_pages)
                design_guide = design_guide + "\n\n**当前页面补充指导：**\n" + page_tips
            return style_genes, design_guide

        if not hasattr(self, event_attr):
            setattr(self, event_attr, {})
        events_dict = getattr(self, event_attr)

        if project_id and project_id not in events_dict:
            event = asyncio.Event()
            events_dict[project_id] = event
            logger.info("第%s页首先到达，开始合并提取设计基因和指导（项目 %s）", page_number, project_id)
            try:
                style_genes, design_guide = await self._extract_style_genes_and_guide(
                    template_html,
                    slide_data,
                    page_number,
                    total_pages,
                )
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = {
                    "style_genes": style_genes,
                    "design_guide": design_guide,
                }

                if not hasattr(self, "_cached_style_genes"):
                    self._cached_style_genes = {}
                self._cached_style_genes[project_id] = style_genes

                if hasattr(self, "cache_dirs") and self.cache_dirs:
                    try:
                        cache_file = self.cache_dirs["style_genes"] / f"{project_id}_combined_genes_guide.json"
                        cache_data = {
                            "project_id": project_id,
                            "style_genes": style_genes,
                            "design_guide": design_guide,
                            "created_at": time.time(),
                            "template_hash": hashlib.md5(template_html.encode()).hexdigest()[:8],
                        }
                        with open(cache_file, "w", encoding="utf-8") as handle:
                            json.dump(cache_data, handle, ensure_ascii=False, indent=2)
                        logger.info("合并提取并缓存项目 %s 的设计基因和指导到文件", project_id)
                    except Exception as exc:
                        logger.warning("保存合并缓存文件失败: %s", exc)

                logger.info("合并提取完成并通知等待者（项目 %s，单次 LLM 调用）", project_id)
            except Exception as exc:
                logger.error("合并提取失败: %s，使用 fallback 并通知等待者", exc)
                style_genes = self._extract_fallback_style_genes(template_html)
                design_guide = self._generate_fallback_unified_guide(slide_data, page_number, total_pages)
                if not hasattr(self, cache_attr):
                    setattr(self, cache_attr, {})
                getattr(self, cache_attr)[project_id] = {
                    "style_genes": style_genes,
                    "design_guide": design_guide,
                }
            finally:
                event.set()

            if page_number > 1:
                page_tips = self._generate_fallback_unified_guide(slide_data, page_number, total_pages)
                design_guide = design_guide + "\n\n**当前页面补充指导：**\n" + page_tips
            return style_genes, design_guide

        if project_id and project_id in events_dict:
            event = events_dict[project_id]
            if not event.is_set():
                logger.info("第%s页等待合并设计数据就绪（项目 %s）...", page_number, project_id)
                try:
                    await asyncio.wait_for(event.wait(), timeout=600.0)
                except asyncio.TimeoutError:
                    logger.warning("第%s页等待合并设计数据超时，使用 fallback", page_number)
                    return (
                        default_genes,
                        self._generate_fallback_unified_guide(slide_data, page_number, total_pages),
                    )

            if hasattr(self, cache_attr) and project_id in getattr(self, cache_attr, {}):
                cached = getattr(self, cache_attr)[project_id]
                style_genes = cached["style_genes"]
                base_guide = cached["design_guide"]
                if page_number > 1:
                    page_tips = self._generate_fallback_unified_guide(slide_data, page_number, total_pages)
                    base_guide = base_guide + "\n\n**当前页面补充指导：**\n" + page_tips
                logger.info("第%s页从缓存获取合并设计数据（等待后）", page_number)
                return style_genes, base_guide

        logger.warning("第%s页未找到缓存的合并设计数据，使用 fallback", page_number)
        return (
            default_genes,
            self._generate_fallback_unified_guide(slide_data, page_number, total_pages),
        )

    def _generate_fallback_unified_guide(
        self,
        slide_data: Dict[str, Any],
        page_number: int,
        total_pages: int,
    ) -> str:
        """Generate a deterministic fallback guide when AI guidance is unavailable."""
        slide_type = slide_data.get("slide_type", "content")
        content_points = slide_data.get("content_points", [])
        title = slide_data.get("title", "")

        guides = ["**A. 页面定位与创意策略**"]
        if page_number == 1:
            guides.extend(
                [
                    "- 开场页面：可以使用大胆的视觉冲击力，设置演示基调",
                    "- 标题排版：尝试非对称布局、创意字体层次、动态视觉元素",
                    "- 背景色保持统一：可以微小调整背景图案或渐变方向",
                ]
            )
        elif page_number == total_pages:
            guides.extend(
                [
                    "- 结尾页面：设计总结性视觉框架，呼应开头元素",
                    "- 行动号召：使用突出的视觉引导，如按钮、箭头等",
                    "- 联系信息：创新的信息展示方式",
                ]
            )
        else:
            guides.extend(
                [
                    "- 内容页面：根据信息重心和内容量选择更合适的空间组织方式，不要默认沿用同一种骨架。",
                    "- 信息密度：每个要点应展开为标题+说明的双层结构，避免只放单行短句",
                    "- 视觉丰富度：至少组合 2 种视觉手法（卡片、图标、色块、数据高亮、进度条等）",
                    "- 背景层次：叠加细微纹理或装饰元素，建立空间纵深",
                    "- 渐进变化：在保持模板基因一致性的基础上，按页面角色切换空间重心和节奏",
                ]
            )

        guides.append("\n**B. 内容驱动的设计建议**")
        if slide_type == "title":
            guides.extend(
                [
                    "- 视觉组件：使用大型标题卡片、品牌标识、装饰性图形元素",
                    "- 布局建议：采用居中对称布局，突出主标题的重要性",
                ]
            )
        elif slide_type == "content":
            if len(content_points) > 5:
                guides.extend(
                    [
                        "- 视觉组件：考虑分栏布局、卡片式设计或折叠展示",
                        "- 布局建议：使用网格布局或多列布局优化空间利用",
                    ]
                )
            elif len(content_points) <= 3:
                guides.extend(
                    [
                        "- 视觉组件：可以使用大型图标、插图或图表增强视觉效果",
                        "- 布局建议：采用宽松布局，增加字体大小和留白空间",
                    ]
                )
            guides.append("- 内容组织：尝试时间线、流程图、对比表格等创新方式")

        guides.append("\n**C. 视觉元素与交互体验**")
        guides.extend(
            [
                "- 视觉元素：根据内容主题选择合适的图标和色彩搭配",
                "- 色彩建议：保持与整体设计基因一致的色彩方案",
                "- 交互体验：确保信息层次清晰，便于快速阅读和理解",
            ]
        )

        if any(keyword in title.lower() for keyword in ["数据", "统计", "分析", "data", "analysis"]):
            guides.append("- 数据可视化：推荐使用柱状图、饼图或折线图展示数据")

        return "\n".join(guides)

    def _build_slide_context(self, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        return prompts_manager.get_slide_context_prompt(slide_data, page_number, total_pages)

    def _extract_style_template(self, existing_slides: List[Dict[str, Any]]) -> List[str]:
        """Extract a reusable style template from existing slides."""
        if not existing_slides:
            return []

        template_parts: List[str] = []
        color_schemes: List[str] = []
        font_families: List[str] = []
        layout_patterns: List[str] = []
        design_elements: List[str] = []

        for slide in existing_slides:
            html_content = slide.get("html_content", "")
            if not html_content:
                continue

            style_info = self._extract_detailed_style_info(html_content)
            if style_info.get("colors"):
                color_schemes.extend(style_info["colors"])
            if style_info.get("fonts"):
                font_families.extend(style_info["fonts"])
            if style_info.get("layout"):
                layout_patterns.append(style_info["layout"])
            if style_info.get("design_elements"):
                design_elements.extend(style_info["design_elements"])

        template_parts.append("**核心设计约束（必须保持一致）：**")
        if color_schemes:
            template_parts.append(f"- 主色调：{', '.join(list(set(color_schemes))[:5])}")
        if font_families:
            template_parts.append(f"- 字体系统：{', '.join(list(set(font_families))[:3])}")
        if layout_patterns:
            template_parts.append(f"- 布局模式：{self._analyze_common_layout(layout_patterns)}")
        if design_elements:
            template_parts.append(f"- 设计元素：{', '.join(list(set(design_elements))[:4])}")

        template_parts.append("")
        template_parts.append("**可创新的设计空间：**")
        template_parts.append("- 内容布局结构（在保持整体风格下可调整）")
        template_parts.append("- 图标和装饰元素的选择和位置")
        template_parts.append("- 动画和交互效果的创新")
        template_parts.append("- 内容展示方式的优化（图表、列表、卡片等）")
        template_parts.append("- 视觉层次的重新组织")
        return template_parts

    def _extract_detailed_style_info(self, html_content: str) -> Dict[str, List[str]]:
        """Extract CSS-oriented style markers from a rendered slide."""
        style_info = {
            "colors": [],
            "fonts": [],
            "layout": "",
            "design_elements": [],
        }

        try:
            color_patterns = [
                r"color[^:]*:\s*([^;]+)",
                r"background[^:]*:\s*([^;]+)",
                r"border[^:]*:\s*([^;]+)",
                r"#[0-9a-fA-F]{3,6}",
                r"rgb\([^)]+\)",
                r"rgba\([^)]+\)",
            ]
            for pattern in color_patterns:
                matches = re.findall(pattern, html_content, re.IGNORECASE)
                style_info["colors"].extend([match.strip() for match in matches if match.strip()])

            font_matches = re.findall(r"font-family[^:]*:\s*([^;]+)", html_content, re.IGNORECASE)
            style_info["fonts"] = [font.strip().replace('"', "").replace("'", "") for font in font_matches]

            if "display: flex" in html_content:
                style_info["layout"] = "Flexbox布局"
            elif "display: grid" in html_content:
                style_info["layout"] = "Grid布局"
            elif "position: absolute" in html_content:
                style_info["layout"] = "绝对定位布局"
            else:
                style_info["layout"] = "流式布局"

            if "border-radius" in html_content:
                style_info["design_elements"].append("圆角设计")
            if "box-shadow" in html_content:
                style_info["design_elements"].append("阴影效果")
            if "gradient" in html_content:
                style_info["design_elements"].append("渐变背景")
            if "transform" in html_content:
                style_info["design_elements"].append("变换效果")
            if "opacity" in html_content or "rgba" in html_content:
                style_info["design_elements"].append("透明效果")
        except Exception as exc:
            logger.warning("Error extracting detailed style info: %s", exc)

        return style_info

    def _analyze_common_layout(self, layout_patterns: List[str]) -> str:
        """Return the most common layout label across rendered slides."""
        if not layout_patterns:
            return "标准流式布局"

        layout_counts: Dict[str, int] = {}
        for layout in layout_patterns:
            layout_counts[layout] = layout_counts.get(layout, 0) + 1
        return max(layout_counts.items(), key=lambda item: item[1])[0]

    def clear_cached_style_genes(self, project_id: Optional[str] = None):
        """Clear in-memory and file caches for style genes and design guidance."""
        cache_attrs = (
            "_cached_style_genes",
            "_cached_style_genes_and_guide",
            "_cached_project_creative_guides",
            "_cached_global_constitutions",
            "_cached_page_creative_briefs",
            "_cached_slide_creative_guides",
        )
        event_attrs = (
            "_style_genes_ready_events",
            "_project_creative_guidance_ready_events",
            "_global_constitution_ready_events",
            "_page_creative_brief_ready_events",
            "_slide_creative_guide_ready_events",
            "_slide_guide_prewarm_tasks",
        )

        def _get_project_scoped_keys(mapping: Any) -> List[Any]:
            if not isinstance(mapping, dict) or not project_id:
                return []
            scoped_keys: List[Any] = []
            scoped_prefix = f"{project_id}:"
            # 单页创意指导缓存会使用“project_id:page_number”作为键。
            # 如果这里只删除项目级键，切换自由模板后仍会复用旧模板生成出的单页指导。
            for key in list(mapping.keys()):
                if key == project_id:
                    scoped_keys.append(key)
                elif isinstance(key, str) and key.startswith(scoped_prefix):
                    scoped_keys.append(key)
            return scoped_keys

        if project_id:
            for attr in cache_attrs:
                cache = getattr(self, attr, None)
                for key in _get_project_scoped_keys(cache):
                    del cache[key]

            for attr in event_attrs:
                events = getattr(self, attr, None)
                for key in _get_project_scoped_keys(events):
                    task = events.get(key)
                    if isinstance(task, asyncio.Task) and not task.done():
                        task.cancel()
                    del events[key]

            if hasattr(self, "cache_dirs") and self.cache_dirs:
                for filename in (
                    f"{project_id}_style_genes.json",
                    f"{project_id}_combined_genes_guide.json",
                    f"{project_id}_creative_guide.json",
                    f"{project_id}_global_constitution.json",
                    f"{project_id}_page_type_guidance.json",
                    f"{project_id}_page_creative_briefs.json",
                    f"{project_id}_page_plan.json",
                ):
                    try:
                        cache_file = self.cache_dirs["style_genes"] / filename
                        if cache_file.exists():
                            cache_file.unlink()
                    except Exception as exc:
                        logger.warning("删除缓存文件失败: %s, error=%s", filename, exc)
                try:
                    for cache_file in self.cache_dirs["style_genes"].glob(f"{project_id}_slide_*_creative_guide.json"):
                        cache_file.unlink()
                except Exception as exc:
                    logger.warning("删除单页创意指导缓存失败: project=%s, error=%s", project_id, exc)

            logger.info("清理项目 %s 的设计相关缓存", project_id)
            return

        for attr in cache_attrs:
            cache = getattr(self, attr, None)
            if isinstance(cache, dict):
                cache.clear()

        for attr in event_attrs:
            events = getattr(self, attr, None)
            if isinstance(events, dict):
                events.clear()

        if hasattr(self, "cache_dirs") and self.cache_dirs:
            for pattern in (
                "*_style_genes.json",
                "*_combined_genes_guide.json",
                "*_creative_guide.json",
                "*_slide_*_creative_guide.json",
            ):
                try:
                    for cache_file in self.cache_dirs["style_genes"].glob(pattern):
                        cache_file.unlink()
                except Exception as exc:
                    logger.warning("删除缓存文件失败: pattern=%s, error=%s", pattern, exc)

        logger.info("清理所有设计相关缓存")

    def get_cached_style_genes_info(self) -> Dict[str, Any]:
        """Return cache metadata for observability and debugging."""
        if not hasattr(self, "_cached_style_genes"):
            return {"cached_projects": [], "total_count": 0}

        return {
            "cached_projects": list(self._cached_style_genes.keys()),
            "total_count": len(self._cached_style_genes),
        }
