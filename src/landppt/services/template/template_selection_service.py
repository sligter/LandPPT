import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..prompts.template_prompts import TemplatePrompts

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ..enhanced_ppt_service import EnhancedPPTService


class TemplateSelectionService:
    """Own template selection and free-template generation for projects."""

    def __init__(self, service: "EnhancedPPTService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    @staticmethod
    def _build_free_template_payload(template_name: str, html_template: str) -> Dict[str, Any]:
        return {
            "template_name": template_name,
            "description": "AI 根据大纲自动生成的项目专属模板",
            "html_template": html_template,
            "tags": ["自由模板", "AI生成", "项目专属"],
            "created_by": "ai_free",
            "template_mode": "free",
            "is_project_free_template": True,
        }

    @staticmethod
    def _build_outline_slide_lines(slides: List[Dict[str, Any]]) -> List[str]:
        return TemplatePrompts.build_outline_slide_lines(slides)

    def _build_free_template_prompt(
        self,
        project: Any,
        outline: Dict[str, Any],
        confirmed: Dict[str, Any],
    ) -> str:
        """构建自由模板生成提示词，统一复用模板提示词模块，避免重复拼装。"""
        # 补充 project 级字段到 confirmed，使提示词能获取更完整的上下文
        enriched = dict(confirmed)
        if not enriched.get("requirements") and hasattr(project, "requirements"):
            enriched["requirements"] = project.requirements or ""
        if not enriched.get("description") and hasattr(project, "description"):
            enriched["description"] = getattr(project, "description", "") or ""
        user_prompt = TemplatePrompts.build_free_template_user_prompt(project, outline, enriched)
        return TemplatePrompts.build_template_generation_prompt(user_prompt)

    @staticmethod
    def _extract_free_template_preview_html(response_content: str) -> Optional[str]:
        """尽量从流式增量文本里提取当前可预览的 HTML 快照。"""
        if not isinstance(response_content, str) or not response_content.strip():
            return None

        content = response_content.strip()
        content_lower = content.lower()

        if "```html" in content_lower:
            start = content_lower.find("```html") + len("```html")
            candidate = content[start:].lstrip()
            end = candidate.rfind("```")
            if end >= 0:
                candidate = candidate[:end]
            candidate = candidate.strip()
            if "<" in candidate and len(candidate) >= 40:
                return candidate

        for marker in ("<!doctype html", "<html", "<body", "<div"):
            idx = content_lower.find(marker)
            if idx < 0:
                continue
            candidate = content[idx:]
            end = candidate.rfind("```")
            if end >= 0:
                candidate = candidate[:end]
            candidate = candidate.strip()
            if "<" in candidate and len(candidate) >= 40:
                return candidate

        return None

    async def stream_free_template_generation(
        self,
        project_id: str,
        user_id: Optional[int] = None,
        force: bool = False,
    ):
        """Stream free-template generation events and persist the final template on success."""
        lock = self._free_template_generation_locks.setdefault(project_id, asyncio.Lock())
        if lock.locked():
            yield {"type": "status", "message": "已有自由模板生成任务正在进行，等待上一个任务完成..."}

        async with lock:
            project = await self.project_manager.get_project(project_id, user_id=user_id)
            if not project:
                raise ValueError("Project not found")

            project_metadata = dict(project.project_metadata or {})
            if project_metadata.get("template_mode") != "free":
                raise ValueError("Project is not using free template mode")

            if force:
                project_metadata.pop("free_template_html", None)
                project_metadata.pop("free_template_name", None)
                project_metadata.pop("free_template_generated_at", None)
                project_metadata.pop("free_template_prompt", None)
                project_metadata.pop("free_template_error", None)
                project_metadata["free_template_status"] = "pending"
                project_metadata["free_template_confirmed"] = False
                project_metadata.pop("free_template_confirmed_at", None)
                await self.project_manager.update_project_metadata(project_id, project_metadata)
                self.clear_cached_style_genes(project_id)
                yield {"type": "status", "message": "已清理旧模板，准备重新生成..."}

            free_html = project_metadata.get("free_template_html")
            free_name = project_metadata.get("free_template_name") or "自由模板（AI决定）"
            if isinstance(free_html, str) and free_html.strip():
                yield {"type": "status", "message": "已加载已有自由模板"}
                yield {
                    "type": "complete",
                    "message": "自由模板已就绪",
                    "template": self._build_free_template_payload(free_name, free_html),
                    "template_name": free_name,
                    "html_template": free_html,
                }
                return

            yield {"type": "status", "message": "正在整理项目大纲和需求..."}
            outline = project.outline or {}
            confirmed = project.confirmed_requirements or {}
            free_prompt = self._build_free_template_prompt(project, outline, confirmed)
            template_name = f"自由模板-{project_id[:8]}"

            project_metadata["template_mode"] = "free"
            project_metadata["free_template_status"] = "generating"
            project_metadata["free_template_confirmed"] = False
            project_metadata.pop("free_template_confirmed_at", None)
            project_metadata.pop("free_template_error", None)
            await self.project_manager.update_project_metadata(project_id, project_metadata)

            yield {"type": "status", "message": "正在调用 AI 流式生成模板..."}

            streamed_response = ""
            last_preview_html = None
            try:
                async for chunk in self.global_template_service.generate_template_with_ai_stream(
                    prompt=free_prompt,
                    template_name=template_name,
                    description="AI 根据大纲自动生成的项目专属模板",
                    tags=["自由模板", "AI生成", "项目专属"],
                    generation_mode="text_only",
                    prompt_is_ready=True,
                ):
                    chunk_type = (chunk or {}).get("type")

                    if chunk_type == "thinking":
                        content = (chunk or {}).get("content") or ""
                        if content:
                            streamed_response += content
                            yield {"type": "thinking", "content": content}
                            preview_html = self._extract_free_template_preview_html(streamed_response)
                            if preview_html and preview_html != last_preview_html:
                                last_preview_html = preview_html
                                yield {
                                    "type": "preview",
                                    "message": "正在生成 HTML 预览...",
                                    "html_template": preview_html,
                                    "template_name": template_name,
                                }
                        continue

                    if chunk_type == "complete":
                        final_html = (chunk or {}).get("html_template") or last_preview_html or ""
                        final_name = (chunk or {}).get("template_name") or template_name
                        if not isinstance(final_html, str) or not final_html.strip():
                            raise ValueError("Failed to generate free template")

                        project_metadata["template_mode"] = "free"
                        project_metadata["free_template_html"] = final_html
                        project_metadata["free_template_name"] = final_name
                        project_metadata["free_template_prompt"] = free_prompt
                        project_metadata["free_template_generated_at"] = time.time()
                        project_metadata["free_template_status"] = "ready"
                        project_metadata.pop("free_template_error", None)
                        await self.project_manager.update_project_metadata(project_id, project_metadata)
                        self.clear_cached_style_genes(project_id)

                        yield {
                            "type": "complete",
                            "message": (chunk or {}).get("message") or "模板生成完成！",
                            "template": self._build_free_template_payload(final_name, final_html),
                            "template_name": final_name,
                            "html_template": final_html,
                        }
                        return

                    if chunk_type == "error":
                        raise ValueError((chunk or {}).get("message") or "Failed to generate free template")

                raise ValueError("Failed to generate free template")
            except Exception as exc:
                project_metadata["free_template_status"] = "error"
                project_metadata["free_template_error"] = str(exc)
                await self.project_manager.update_project_metadata(project_id, project_metadata)
                raise

    async def _ensure_global_master_template_selected(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Ensure the project has a selected template, defaulting when necessary."""
        try:
            project = await self.project_manager.get_project(project_id)
            if not project:
                logger.error(f"Project {project_id} not found")
                return None

            project_metadata = project.project_metadata or {}
            if project_metadata.get("template_mode") == "free":
                free_template = await self.get_selected_global_template(project_id)
                if free_template:
                    logger.info(
                        "Project %s using free template: %s",
                        project_id,
                        free_template.get("template_name", "AI自由模板"),
                    )
                    return free_template
                logger.warning(
                    "Project %s is in free template mode but no template is available; falling back to default",
                    project_id,
                )

            selected_template_id = project_metadata.get("selected_global_template_id")
            if selected_template_id:
                template = await self.global_template_service.get_template_by_id(selected_template_id)
                if template and template.get("is_active", True):
                    logger.info("Project %s using selected template: %s", project_id, template["template_name"])
                    return template

            default_template = await self.global_template_service.get_default_template()
            if default_template:
                await self._save_selected_template_to_project(project_id, default_template["id"])
                logger.info("Project %s using default template: %s", project_id, default_template["template_name"])
                return default_template

            logger.warning("No global master template available for project %s", project_id)
            return None
        except Exception as exc:
            logger.error("Error ensuring global master template for project %s: %s", project_id, exc)
            return None

    async def _save_selected_template_to_project(self, project_id: str, template_id: int):
        """Persist template selection into project metadata."""
        try:
            project = await self.project_manager.get_project(project_id)
            if not project:
                return

            project_metadata = project.project_metadata or {}
            project_metadata["selected_global_template_id"] = template_id
            project_metadata["template_mode"] = "global"

            await self.project_manager.update_project_metadata(project_id, project_metadata)
            self.clear_cached_style_genes(project_id)
            logger.info("Saved selected template %s to project %s", template_id, project_id)
        except Exception as exc:
            logger.error("Error saving selected template to project %s: %s", project_id, exc)

    async def select_global_template_for_project(
        self,
        project_id: str,
        template_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Select a global template for a project."""
        try:
            project = await self.project_manager.get_project(project_id, user_id=user_id)
            if not project:
                raise ValueError(f"Project {project_id} not found or access denied")

            if template_id:
                template = await self.global_template_service.get_template_by_id(template_id)
                if not template:
                    raise ValueError(f"Template {template_id} not found")
                if not template.get("is_active", True):
                    raise ValueError(f"Template {template_id} is not active")
            else:
                template = await self.global_template_service.get_default_template()
                if not template:
                    raise ValueError("No default template available")
                template_id = template["id"]

            await self._save_selected_template_to_project(project_id, template_id)
            await self.global_template_service.increment_template_usage(template_id)
            return {
                "success": True,
                "message": "模板选择成功",
                "selected_template": template,
            }
        except Exception as exc:
            logger.error("Error selecting global template for project %s: %s", project_id, exc)
            return {
                "success": False,
                "message": str(exc),
                "selected_template": None,
            }

    async def select_free_template_for_project(
        self,
        project_id: str,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Switch a project into free-template mode."""
        try:
            project = await self.project_manager.get_project(project_id, user_id=user_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            project_metadata = project.project_metadata or {}
            has_existing_free_template = bool(
                isinstance(project_metadata.get("free_template_html"), str)
                and project_metadata.get("free_template_html", "").strip()
            )
            project_metadata["template_mode"] = "free"
            project_metadata.pop("selected_global_template_id", None)
            project_metadata["free_template_status"] = "ready" if has_existing_free_template else "pending"

            await self.project_manager.update_project_metadata(project_id, project_metadata)
            self.clear_cached_style_genes(project_id)
            return {
                "success": True,
                "message": "已切换为自由模板",
                "selected_template": None,
            }
        except Exception as exc:
            logger.error("Error selecting free template for project %s: %s", project_id, exc)
            return {
                "success": False,
                "message": str(exc),
                "selected_template": None,
            }

    async def get_selected_global_template(
        self,
        project_id: str,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return the selected global or AI-generated free template for a project."""
        try:
            project = await self.project_manager.get_project(project_id, user_id=user_id)
            if not project:
                return None

            project_metadata = project.project_metadata or {}
            template_mode = project_metadata.get("template_mode")

            if template_mode == "free":
                free_html = project_metadata.get("free_template_html")
                free_name = project_metadata.get("free_template_name") or "自由模板（AI决定）"

                if free_html and isinstance(free_html, str) and free_html.strip():
                    return self._build_free_template_payload(free_name, free_html)

                return None

            selected_template_id = project_metadata.get("selected_global_template_id")
            if selected_template_id:
                return await self.global_template_service.get_template_by_id(selected_template_id)

            return None
        except Exception as exc:
            logger.error("Error getting selected global template for project %s: %s", project_id, exc)
            return None
