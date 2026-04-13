"""
Requirement confirmation routes for outline workflows.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from ...auth.middleware import get_current_user_required
from ...database.models import User
from .outline_support import (
    _is_billable_provider,
    _normalize_content_source_urls,
    _process_uploaded_files_for_outline,
    _process_url_sources_for_outline,
    _save_uploaded_files_for_confirmed_requirements,
)
from .support import (
    check_credits_for_operation,
    consume_credits_for_operation,
    get_ppt_service_for_user,
    logger,
    ppt_service,
    templates,
)

router = APIRouter()


@router.get("/projects/{project_id}/todo-editor")
async def web_project_todo_editor(
    request: Request,
    project_id: str,
    auto_start: bool = False,
    user: User = Depends(get_current_user_required)
):
    """Project TODO board with editor"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Project not found"
            })

        has_outline = bool(project and isinstance(project.outline, dict) and project.outline.get("slides"))
        template_name = "pages/project/todo_board_with_editor.html" if has_outline else "pages/project/todo_board.html"

        return templates.TemplateResponse(template_name, {
            "request": request,
            "todo_board": project.todo_board,
            "project": project,
            "auto_start": auto_start
        })

    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": str(e)
        })


@router.post("/projects/{project_id}/confirm-requirements")
async def confirm_project_requirements(
    request: Request,
    project_id: str,
    topic: str = Form(...),
    audience_type: str = Form(...),
    custom_audience: str = Form(None),
    page_count_mode: str = Form("ai_decide"),
    min_pages: int = Form(8),
    max_pages: int = Form(15),
    fixed_pages: int = Form(10),
    ppt_style: str = Form("general"),
    custom_style_prompt: str = Form(None),
    description: str = Form(None),
    content_source: str = Form("manual"),
    file_upload: List[UploadFile] = File(None),
    content_urls: str = Form(None),
    file_processing_mode: str = Form("markitdown"),
    content_analysis_depth: str = Form("standard"),
    user: User = Depends(get_current_user_required)
):
    """Confirm project requirements and generate TODO list - 支持多文件上传和联网搜索集成"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)

        # Get project to access original requirements
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Extract network_mode from project metadata (set during project creation)
        network_mode = False
        if project.project_metadata and isinstance(project.project_metadata, dict):
            network_mode = project.project_metadata.get("network_mode", False)

        # Process audience information
        target_audience = audience_type
        if audience_type == "自定义" and custom_audience:
            target_audience = custom_audience

        # Extract language from project metadata (set during project creation)
        language = "zh"  # Default language
        if project.project_metadata and isinstance(project.project_metadata, dict):
            language = project.project_metadata.get("language", "zh")

        # Handle content sources
        file_outline = None
        source_urls: List[str] = []
        saved_file_metadata: Dict[str, Any] = {}
        if content_source == "file":
            saved_file_metadata = await _save_uploaded_files_for_confirmed_requirements(file_upload or [])
        elif content_source == "url":
            source_urls = _normalize_content_source_urls(content_urls)
            if not source_urls:
                raise Exception("Please provide at least one valid URL (http/https).")
        # Legacy synchronous file/url generation remains disabled below to avoid long-lived confirm requests.
        if False and content_source == "file":
            # Process uploaded files (support multiple files) and generate outline
            # 使用项目创建时的 network_mode 和 language 参数
            file_outline = await _process_uploaded_files_for_outline(
                file_upload, topic, target_audience, page_count_mode, min_pages, max_pages,
                fixed_pages, ppt_style, custom_style_prompt,
                file_processing_mode, content_analysis_depth, project.requirements,
                enable_web_search=network_mode,  # 使用项目的 network_mode
                scenario=project.scenario,  # 传递场景参数
                language=language,  # 传递用户选择的语言参数
                user_id=user.id  # 传递用户ID以获取用户特定的AI配置
            )

            # Update topic if it was extracted from file
            if file_outline and file_outline.get('title') and not topic.strip():
                topic = file_outline['title']
        elif False and content_source == "url":
            source_urls = _normalize_content_source_urls(content_urls)
            if not source_urls:
                raise Exception("Please provide at least one valid URL (http/https).")

            file_outline = await _process_url_sources_for_outline(
                source_urls=source_urls,
                topic=topic,
                target_audience=target_audience,
                page_count_mode=page_count_mode,
                min_pages=min_pages,
                max_pages=max_pages,
                fixed_pages=fixed_pages,
                ppt_style=ppt_style,
                custom_style_prompt=custom_style_prompt,
                file_processing_mode=file_processing_mode,
                content_analysis_depth=content_analysis_depth,
                requirements=project.requirements,
                scenario=project.scenario,
                language=language,
                user_id=user.id,
            )
            if not file_outline:
                raise Exception("Failed to extract usable content from the provided URLs.")

            if file_outline.get('title') and not topic.strip():
                topic = file_outline['title']

        # Bill file/url outline generation by actual LLM call count.
        if content_source in ("file", "url") and file_outline:
            _, outline_settings = await user_ppt_service.get_role_provider_async("outline")
            outline_provider_name = outline_settings.get("provider")
            llm_call_count = 0
            try:
                metadata = file_outline.get("metadata", {}) if isinstance(file_outline, dict) else {}
                llm_call_count = int(metadata.get("llm_call_count", 0) or 0)
                if llm_call_count < 0:
                    llm_call_count = 0
            except Exception:
                llm_call_count = 0

            if llm_call_count > 0 and _is_billable_provider(outline_provider_name):
                has_credits, required, balance = await check_credits_for_operation(
                    user.id,
                    "outline_generation",
                    llm_call_count,
                    provider_name=outline_provider_name,
                )
                if not has_credits:
                    raise Exception(f"积分不足，大纲生成需要 {required} 积分，当前余额 {balance} 积分")

                billed, bill_message = await consume_credits_for_operation(
                    user.id,
                    "outline_generation",
                    llm_call_count,
                    description=f"文件大纲生成(需求确认): {topic or project.topic}",
                    reference_id=project_id,
                    provider_name=outline_provider_name,
                )
                if not billed:
                    raise Exception(bill_message or "积分扣费失败")

        # Process page count settings
        page_count_settings = {
            "mode": page_count_mode,
            "min_pages": min_pages if page_count_mode == "custom_range" else None,
            "max_pages": max_pages if page_count_mode == "custom_range" else None,
            "fixed_pages": fixed_pages if page_count_mode == "fixed" else None
        }

        # Update project with confirmed requirements
        confirmed_requirements = {
            "topic": topic,
            "requirements": project.requirements,  # 使用项目创建时的具体要求
            "target_audience": target_audience,
            "audience_type": audience_type,
            "custom_audience": custom_audience if audience_type == "自定义" else None,
            "page_count_settings": page_count_settings,
            "ppt_style": ppt_style,
            "custom_style_prompt": custom_style_prompt if ppt_style == "custom" else None,
            "description": description,
            "content_source": content_source,
            "source_urls": source_urls if content_source == "url" else None,
            "file_processing_mode": file_processing_mode if content_source in ("file", "url") else None,
            "content_analysis_depth": content_analysis_depth if content_source in ("file", "url") else None,
            "file_generated_outline": file_outline if content_source not in ("file", "url") else None,
            "force_file_outline_regeneration": content_source in ("file", "url"),
        }

        # 如果是文件项目，保存文件信息
        if content_source in ("file", "url") and file_outline and 'file_info' in file_outline:
            file_info = file_outline['file_info']
            file_path = file_info.get('file_path') or file_info.get('merged_file_path')
            filename = file_info.get('filename') or file_info.get('merged_filename')
            uploaded_files = file_info.get('uploaded_files')

            file_metadata = {}
            if file_path:
                file_metadata["file_path"] = file_path
            if filename:
                file_metadata["filename"] = filename
            if uploaded_files:
                file_metadata["uploaded_files"] = uploaded_files

            if file_metadata:
                confirmed_requirements.update(file_metadata)

        if saved_file_metadata:
            confirmed_requirements.update(saved_file_metadata)

        # Store confirmed requirements in project
        # 直接确认需求并更新TODO板，无需AI生成待办清单
        success = await user_ppt_service.confirm_requirements_and_update_workflow(project_id, confirmed_requirements)

        if not success:
            raise Exception("需求确认失败")

        # Return JSON success response for AJAX request
        from fastapi.responses import JSONResponse
        return JSONResponse({
            "status": "success",
            "message": "需求确认完成",
            "redirect_url": f"/projects/{project_id}/todo"
        })

    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)
