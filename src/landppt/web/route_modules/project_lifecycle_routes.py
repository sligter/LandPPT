"""
项目生命周期相关页面路由。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ...api.models import PPTGenerationRequest
from ...auth.middleware import get_current_user_required
from ...database.models import User
from ...services.slide.svg_page.render_mode import normalize_render_mode
from .outline_support import (
    _normalize_content_source_urls,
    _save_uploaded_files_for_confirmed_requirements,
)
from .support import get_ppt_service_for_user, logger, ppt_service, templates
from .unattended_support import (
    build_unattended_requirements,
    maybe_start_unattended_run,
    require_unattended_admin,
    resolve_unattended_config,
)

router = APIRouter()

SCENARIOS = [
    {"id": "general", "name": "通用", "description": "适用于各类通用场景的 PPT 模板", "icon": "📚"},
    {"id": "tourism", "name": "旅游观光", "description": "旅游线路、景点介绍等旅游相关 PPT", "icon": "🗺️"},
    {"id": "education", "name": "儿童科普", "description": "适合儿童的科普教育类 PPT", "icon": "🎓"},
    {"id": "analysis", "name": "深入分析", "description": "数据分析、研究报告等深度分析 PPT", "icon": "📊"},
    {"id": "history", "name": "历史文化", "description": "历史事件、文化介绍等人文类 PPT", "icon": "🏛️"},
    {"id": "technology", "name": "科技技术", "description": "技术介绍、产品发布等科技类 PPT", "icon": "💻"},
    {"id": "business", "name": "方案汇报", "description": "商业计划、项目汇报等商务 PPT", "icon": "💼"},
]


@router.get("/scenarios", response_class=HTMLResponse)
@router.get("/create", response_class=HTMLResponse)
async def web_scenarios(
    request: Request,
    scenario: str = "general",
    user: User = Depends(get_current_user_required),
):
    """一步式 PPT 创建页面（主题、需求与全部生成参数合并在同一个输入区）。"""
    valid_ids = {item["id"] for item in SCENARIOS}
    # Seed the unattended controls from the user's saved settings; otherwise the
    # settings page's defaults would never reach the primary creation path.
    unattended_defaults = await resolve_unattended_config(user_id=user.id)

    # Unattended runs skip the template-selection page, so the template has to be
    # picked here. A listing failure must not break project creation — the picker
    # then just offers 默认 / 自由模板.
    template_options: List[Dict[str, Any]] = []
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        template_options = [
            {
                "id": item.get("id"),
                "name": item.get("template_name") or f"模板 {item.get('id')}",
                "is_default": bool(item.get("is_default")),
            }
            for item in await user_ppt_service.global_template_service.get_all_templates()
            if item.get("id") is not None
        ]
        template_options.sort(key=lambda item: (not item["is_default"], item["name"]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load templates for the creation page: %s", exc)

    return templates.TemplateResponse(
        "pages/project/scenarios.html",
        {
            "request": request,
            "scenarios": SCENARIOS,
            "selected_scenario": scenario if scenario in valid_ids else "general",
            "unattended_defaults": unattended_defaults,
            "template_options": template_options,
        },
    )


@router.get("/research", response_class=HTMLResponse)
async def web_research_status(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Deep Research 状态页。"""
    return templates.TemplateResponse("pages/project/research_status.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def web_dashboard(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """项目仪表盘。"""
    try:
        projects_response = await ppt_service.project_manager.list_projects(
            page=1,
            page_size=100,
            user_id=user.id,
        )
        if projects_response.total > len(projects_response.projects):
            projects_response = await ppt_service.project_manager.list_projects(
                page=1,
                page_size=projects_response.total,
                user_id=user.id,
            )
        projects = projects_response.projects

        total_projects = projects_response.total
        completed_projects = len([project for project in projects if project.status == "completed"])
        in_progress_projects = len([project for project in projects if project.status == "in_progress"])
        draft_projects = len([project for project in projects if project.status == "draft"])
        recent_projects = sorted(projects, key=lambda project: project.updated_at, reverse=True)[:5]

        active_todo_boards = []
        for project in projects:
            if project.status == "in_progress" and project.todo_board:
                todo_board = await ppt_service.get_project_todo_board(project.project_id)
                if todo_board:
                    active_todo_boards.append(todo_board)

        return templates.TemplateResponse(
            "pages/project/project_dashboard.html",
            {
                "request": request,
                "total_projects": total_projects,
                "completed_projects": completed_projects,
                "in_progress_projects": in_progress_projects,
                "draft_projects": draft_projects,
                "recent_projects": recent_projects,
                "active_todo_boards": active_todo_boards[:3],
            },
        )
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.get("/projects", response_class=HTMLResponse)
async def web_projects_list(
    request: Request,
    page: int = 1,
    status: str | None = None,
    user: User = Depends(get_current_user_required),
):
    """项目列表页。"""
    try:
        projects_response = await ppt_service.project_manager.list_projects(
            page=page,
            page_size=10,
            status=status,
            user_id=user.id,
        )
        return templates.TemplateResponse(
            "pages/project/projects_list.html",
            {
                "request": request,
                "projects": projects_response.projects,
                "total": projects_response.total,
                "page": projects_response.page,
                "page_size": projects_response.page_size,
                "status_filter": status,
            },
        )
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.post("/projects/create", response_class=HTMLResponse)
async def web_create_project(
    request: Request,
    scenario: str = Form(...),
    topic: str = Form(...),
    requirements: str | None = Form(None),
    language: str = Form("zh"),
    network_mode: bool = Form(False),
    user: User = Depends(get_current_user_required),
):
    """创建项目。"""
    try:
        project_request = PPTGenerationRequest(
            scenario=scenario,
            topic=topic,
            requirements=requirements,
            network_mode=network_mode,
            language=language,
            user_id=user.id,
        )
        project = await ppt_service.project_manager.create_project(project_request)
        await ppt_service.project_manager.update_project_status(project.project_id, "in_progress")
        return RedirectResponse(url=f"/projects/{project.project_id}/todo", status_code=302)
    except Exception as exc:
        return templates.TemplateResponse("error.html", {"request": request, "error": str(exc)})


@router.post("/projects/create-and-confirm")
async def web_create_project_and_confirm(
    request: Request,
    scenario: str = Form("general"),
    topic: str = Form(...),
    requirements: str = Form(None),
    language: str = Form("zh"),
    render_mode: str = Form("html"),
    network_mode: bool = Form(False),
    audience_type: str = Form("普通大众"),
    custom_audience: str = Form(None),
    page_count_mode: str = Form("ai_decide"),
    min_pages: int = Form(8),
    max_pages: int = Form(15),
    fixed_pages: int = Form(10),
    include_transition_pages: bool = Form(False),
    include_page_numbers: bool = Form(True),
    ppt_style: str = Form("general"),
    custom_style_prompt: str = Form(None),
    description: str = Form(None),
    content_source: str = Form("manual"),
    file_upload: List[UploadFile] = File(None),
    content_urls: str = Form(None),
    file_processing_mode: str = Form("markitdown"),
    content_analysis_depth: str = Form("fast"),
    unattended_mode: bool = Form(False),
    stop_at_stage: str = Form("ppt"),
    unattended_notify_in_app: bool = Form(True),
    unattended_notify_email: bool = Form(False),
    unattended_template_mode: str = Form("auto"),
    unattended_template_id: str = Form(""),
    user: User = Depends(get_current_user_required),
):
    """一步式创建项目并确认需求，直接进入大纲生成阶段。"""
    require_unattended_admin(user, enabled=unattended_mode)
    project_id: str | None = None
    try:
        topic = (topic or "").strip()
        if not topic:
            raise ValueError("请填写 PPT 主题")

        # 先处理内容来源，避免在素材无效时留下一个无法继续的空项目
        source_urls: List[str] = []
        saved_file_metadata: Dict[str, Any] = {}
        if content_source == "file":
            saved_file_metadata = await _save_uploaded_files_for_confirmed_requirements(file_upload or [])
        elif content_source == "url":
            source_urls = _normalize_content_source_urls(content_urls)
            if not source_urls:
                raise ValueError("请至少提供一个有效 URL（http/https）")

        requirements = (requirements or "").strip() or None
        custom_audience = (custom_audience or "").strip() or None
        custom_style_prompt = (custom_style_prompt or "").strip() or None
        target_audience = custom_audience if audience_type == "自定义" and custom_audience else audience_type

        project_request = PPTGenerationRequest(
            scenario=scenario,
            topic=topic,
            requirements=requirements,
            network_mode=network_mode,
            language=language,
            target_audience=target_audience,
            custom_audience=custom_audience,
            ppt_style=ppt_style,
            custom_style_prompt=custom_style_prompt,
            include_transition_pages=include_transition_pages,
            description=description,
            use_file_content=content_source in ("file", "url"),
            file_processing_mode=file_processing_mode,
            content_analysis_depth=content_analysis_depth,
            user_id=user.id,
        )
        project = await ppt_service.project_manager.create_project(project_request)
        project_id = project.project_id
        await ppt_service.project_manager.update_project_status(project_id, "in_progress")

        page_count_settings = {
            "mode": page_count_mode,
            "min_pages": min_pages if page_count_mode == "custom_range" else None,
            "max_pages": max_pages if page_count_mode == "custom_range" else None,
            "fixed_pages": fixed_pages if page_count_mode == "fixed" else None,
        }

        confirmed_requirements: Dict[str, Any] = {
            "topic": topic,
            "requirements": requirements,
            "target_audience": target_audience,
            "audience_type": audience_type,
            "custom_audience": custom_audience if audience_type == "自定义" else None,
            "page_count_settings": page_count_settings,
            "include_transition_pages": include_transition_pages,
            "include_page_numbers": include_page_numbers,
            "ppt_style": ppt_style,
            "custom_style_prompt": custom_style_prompt if ppt_style == "custom" else None,
            "description": description,
            "content_source": content_source,
            "source_urls": source_urls if content_source == "url" else None,
            "file_processing_mode": file_processing_mode if content_source in ("file", "url") else None,
            "content_analysis_depth": content_analysis_depth if content_source in ("file", "url") else None,
            "file_generated_outline": None,
            "force_file_outline_regeneration": content_source in ("file", "url"),
            "unattended": build_unattended_requirements(
                enabled=unattended_mode,
                stop_at_stage=stop_at_stage,
                notify_in_app=unattended_notify_in_app,
                notify_email=unattended_notify_email,
                template_mode=unattended_template_mode,
                template_id=unattended_template_id,
            ),
        }
        if saved_file_metadata:
            confirmed_requirements.update(saved_file_metadata)

        user_ppt_service = get_ppt_service_for_user(user.id)
        metadata = dict(project.project_metadata or {})
        metadata["render_mode"] = normalize_render_mode(render_mode)
        saved = await user_ppt_service.project_manager.update_project_metadata(
            project_id, metadata, user_id=user.id
        )
        if not saved:
            raise RuntimeError("页面绘制方式保存失败，请重新确认需求")
        success = await user_ppt_service.confirm_requirements_and_update_workflow(
            project_id, confirmed_requirements
        )
        if not success:
            raise RuntimeError("需求确认失败")

        payload: Dict[str, Any] = {
            "status": "success",
            "project_id": project_id,
            "redirect_url": f"/projects/{project_id}/todo",
        }

        unattended = await maybe_start_unattended_run(
            project_id=project_id,
            project_topic=topic,
            user_id=user.id,
            confirmed_requirements=confirmed_requirements,
            language=language,
        )
        if unattended:
            payload["unattended"] = unattended

        return JSONResponse(payload)
    except Exception as exc:
        payload: Dict[str, Any] = {"status": "error", "message": str(exc)}
        if project_id:
            # 项目已建成但确认失败：引导用户到看板手动确认，避免工作丢失
            payload["project_id"] = project_id
            payload["redirect_url"] = f"/projects/{project_id}/todo"
        return JSONResponse(payload, status_code=500)


@router.post("/projects/{project_id}/start-workflow")
async def start_project_workflow(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """启动项目工作流。"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if not project.confirmed_requirements:
            return {"status": "waiting", "message": "Waiting for requirements confirmation"}

        network_mode = False
        if project.project_metadata and isinstance(project.project_metadata, dict):
            network_mode = project.project_metadata.get("network_mode", False)

        language = "zh"
        if project.project_metadata and isinstance(project.project_metadata, dict):
            language = project.project_metadata.get("language", "zh")

        confirmed_requirements = project.confirmed_requirements or {}
        project_request = PPTGenerationRequest(
            scenario=project.scenario,
            topic=project.topic,
            requirements=project.requirements,
            language=language,
            network_mode=network_mode,
            target_audience=confirmed_requirements.get("target_audience", "普通大众"),
            custom_audience=confirmed_requirements.get("custom_audience"),
            ppt_style=confirmed_requirements.get("ppt_style", "general"),
            custom_style_prompt=confirmed_requirements.get("custom_style_prompt"),
            description=confirmed_requirements.get("description"),
            user_id=user.id,
        )

        user_ppt_service = get_ppt_service_for_user(user.id)
        asyncio.create_task(
            user_ppt_service._execute_project_workflow(
                project_id,
                project_request,
                user_id=user.id,
            )
        )
        return {"status": "success", "message": "Workflow started"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
