"""
项目相关 Web 路由聚合入口。
"""

from fastapi import APIRouter

from .project_library_routes import router as project_library_router
from .project_lifecycle_routes import router as project_lifecycle_router
from .project_workspace_routes import router as project_workspace_router

router = APIRouter()
router.include_router(project_lifecycle_router)
router.include_router(project_workspace_router)
router.include_router(project_library_router)
