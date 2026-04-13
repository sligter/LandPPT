"""
项目生命周期相关页面路由。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...api.models import PPTGenerationRequest
from ...auth.middleware import get_current_user_required
from ...database.models import User
from .support import get_ppt_service_for_user, ppt_service, templates

router = APIRouter()


@router.get("/scenarios", response_class=HTMLResponse)
async def web_scenarios(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """场景选择页面。"""
    scenarios = [
        {"id": "general", "name": "通用", "description": "适用于各类通用场景的 PPT 模板", "icon": "📚"},
        {"id": "tourism", "name": "旅游观光", "description": "旅游线路、景点介绍等旅游相关 PPT", "icon": "🗺️"},
        {"id": "education", "name": "儿童科普", "description": "适合儿童的科普教育类 PPT", "icon": "🎓"},
        {"id": "analysis", "name": "深入分析", "description": "数据分析、研究报告等深度分析 PPT", "icon": "📊"},
        {"id": "history", "name": "历史文化", "description": "历史事件、文化介绍等人文类 PPT", "icon": "🏛️"},
        {"id": "technology", "name": "科技技术", "description": "技术介绍、产品发布等科技类 PPT", "icon": "💻"},
        {"id": "business", "name": "方案汇报", "description": "商业计划、项目汇报等商务 PPT", "icon": "💼"},
    ]
    return templates.TemplateResponse(
        "pages/project/scenarios.html",
        {"request": request, "scenarios": scenarios},
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
        projects = projects_response.projects

        total_projects = len(projects)
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
