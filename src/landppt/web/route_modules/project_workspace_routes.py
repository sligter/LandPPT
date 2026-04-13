"""
项目工作区相关页面路由。
"""

from __future__ import annotations

import mimetypes
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from ...auth.middleware import get_current_user_required
from ...core.config import ai_config, app_config
from ...database.models import User
from .support import _apply_no_store_headers, logger, ppt_service, templates

router = APIRouter()


async def _get_owned_project_or_404(project_id: str, user: User):
    """Resolve a project only within the authenticated user's ownership scope."""
    from ...services.db_project_manager import DatabaseProjectManager

    project = await DatabaseProjectManager().get_project(project_id, user_id=user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _resolve_project_narration_state(project_id: str, user_id: int) -> tuple[bool, list[str]]:
    """解析项目是否存在讲稿，以及可用语言列表。"""
    has_speech_scripts = False
    narration_languages: list[str] = []
    try:
        from ...database.database import SessionLocal
        from ...database.models import Project, SpeechScript

        db = SessionLocal()
        try:
            for language in ("zh", "en"):
                exists = (
                    db.query(SpeechScript.id)
                    .join(Project, Project.project_id == SpeechScript.project_id)
                    .filter(
                        SpeechScript.project_id == project_id,
                        SpeechScript.language == language,
                        Project.user_id == user_id,
                    )
                    .first()
                )
                if exists:
                    narration_languages.append(language)
            has_speech_scripts = len(narration_languages) > 0
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to resolve speech scripts existence for project %s: %s", project_id, exc)

    return has_speech_scripts, narration_languages


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def web_project_detail(
    request: Request,
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """项目详情页。"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return templates.TemplateResponse("error.html", {"request": request, "error": "Project not found"})

        todo_board = await ppt_service.get_project_todo_board(project_id, user_id=user.id)
        versions = await ppt_service.project_manager.get_project_versions(project_id, user_id=user.id)

        return templates.TemplateResponse(
            "pages/project/project_detail.html",
            {
                "request": request,
                "project": project,
                "todo_board": todo_board,
                "versions": versions,
            },
        )
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.get("/projects/{project_id}/todo", response_class=HTMLResponse)
async def web_project_todo_board(
    request: Request,
    project_id: str,
    auto_start: bool = False,
    user: User = Depends(get_current_user_required),
):
    """项目 TODO 看板页。"""
    try:
        if project_id in ["template-selection", "todo", "edit", "preview", "fullscreen"]:
            error_msg = f"无效的项目ID: {project_id}。\n\n"
            error_msg += "可能的原因：\n"
            error_msg += "1. URL格式错误，正确格式应为: /projects/[项目ID]/todo\n"
            error_msg += "2. 您可能访问了错误的链接\n\n"
            error_msg += "建议解决方案：\n"
            error_msg += "• 返回项目列表页面选择正确的项目\n"
            error_msg += "• 检查浏览器地址栏中的URL是否完整"
            return templates.TemplateResponse("error.html", {"request": request, "error": error_msg})

        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": f"项目不存在 (ID: {project_id})。请检查项目ID是否正确。"},
            )

        todo_board = await ppt_service.get_project_todo_board(project_id)
        if not todo_board:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": f"项目 '{project.topic}' 的TODO看板不存在。请联系技术支持。"},
            )

        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        project_metadata = project.project_metadata if project and isinstance(project.project_metadata, dict) else {}
        has_outline = bool(project and isinstance(project.outline, dict) and project.outline.get("slides"))
        has_slides = bool(project and isinstance(project.slides_data, list) and len(project.slides_data) > 0)
        ppt_creation_running = any(
            stage.id == "ppt_creation" and stage.status == "running"
            for stage in todo_board.stages
        )
        has_selected_template = bool(
            project_metadata.get("selected_global_template_id")
            or project_metadata.get("template_mode") in {"global", "free"}
        )
        use_integrated_editor = bool(
            project
            and project.confirmed_requirements
            and has_outline
            and (ppt_creation_running or has_slides or has_selected_template or auto_start)
        )

        template_name = (
            "pages/project/todo_board_with_editor.html"
            if use_integrated_editor
            else "pages/project/todo_board.html"
        )
        template_context = {"request": request, "todo_board": todo_board}
        if project:
            template_context["project"] = project

        return templates.TemplateResponse(template_name, template_context)
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.get("/projects/{project_id}/edit", response_class=HTMLResponse)
async def edit_project_ppt(
    request: Request,
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """高级编辑器页面。"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if not project.slides_data:
            project.slides_data = []

        has_speech_scripts, narration_languages = await _resolve_project_narration_state(project_id, user.id)
        response = templates.TemplateResponse(
            "pages/project/project_slides_editor.html",
            {
                "request": request,
                "project": project,
                "enable_auto_layout_repair": ai_config.enable_auto_layout_repair,
                "narration_video_tools_enabled": getattr(app_config, "narration_video_tools_enabled", True),
                "has_speech_scripts": has_speech_scripts,
                "narration_languages": narration_languages,
            },
        )
        return _apply_no_store_headers(response)
    except Exception as exc:
        logger.error("Error loading project editor for %s: %s", project_id, exc)
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.get("/projects/{project_id}/fullscreen", response_class=HTMLResponse)
async def web_project_fullscreen(
    request: Request,
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """全屏演示页。"""
    try:
        try:
            project = await _get_owned_project_or_404(project_id, user)
        except HTTPException:
            return templates.TemplateResponse("error.html", {"request": request, "error": "项目未找到"})

        if not project.slides_data or len(project.slides_data) == 0:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "PPT尚未生成或无幻灯片内容"},
            )

        has_speech_scripts, narration_languages = await _resolve_project_narration_state(project_id, user.id)
        response = templates.TemplateResponse(
            "pages/project/project_fullscreen_presentation.html",
            {
                "request": request,
                "project": project,
                "slides_count": len(project.slides_data),
                "has_speech_scripts": has_speech_scripts,
                "narration_languages": narration_languages,
            },
        )
        return _apply_no_store_headers(response)
    except Exception as exc:
        logger.error("Error in fullscreen presentation: %s", exc)
        return templates.TemplateResponse("error.html", {"request": request, "error": f"加载演示时出错: {str(exc)}"})


@router.get("/api/projects/{project_id}/slides-data")
async def get_project_slides_data(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """获取项目最新的幻灯片数据。"""
    try:
        project = await _get_owned_project_or_404(project_id, user)

        if not project.slides_data or len(project.slides_data) == 0:
            return {
                "status": "no_slides",
                "message": "PPT尚未生成",
                "slides_data": [],
                "total_slides": 0,
            }

        return {
            "status": "success",
            "slides_data": project.slides_data,
            "total_slides": len(project.slides_data),
            "project_title": project.title,
            "updated_at": project.updated_at,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error getting slides data: %s", exc)
        raise HTTPException(status_code=500, detail=f"获取幻灯片数据失败: {str(exc)}")


@router.get("/test/slides-navigation", response_class=HTMLResponse)
async def test_slides_navigation(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """测试幻灯片导航功能。"""
    with open("test_slides_navigation.html", "r", encoding="utf-8") as file_handle:
        content = file_handle.read()
    return HTMLResponse(content=content)


@router.get("/temp/{file_path:path}")
async def serve_temp_file(file_path: str):
    """提供临时幻灯片文件。"""
    try:
        temp_dir = Path(tempfile.gettempdir()) / "landppt"
        full_path = temp_dir / file_path

        if not str(full_path.resolve()).startswith(str(temp_dir.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        media_type, _ = mimetypes.guess_type(str(full_path))
        return FileResponse(
            path=str(full_path),
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "no-cache"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
