"""
Web route aggregator for LandPPT.
"""

from fastapi import APIRouter

from .route_modules.ai_edit_routes import router as ai_edit_router
from .route_modules.config_routes import router as config_router
from .route_modules.export_routes import router as export_router
from .route_modules.narration_routes import router as narration_router
from .route_modules.outline_routes import router as outline_router
from .route_modules.project_routes import router as project_router
from .route_modules.share_routes import router as share_router
from .route_modules.slide_routes import router as slide_router
from .route_modules.speech_script_routes import router as speech_script_router
from .route_modules.template_routes import router as template_router

router = APIRouter()
router.include_router(config_router)
router.include_router(project_router)
router.include_router(outline_router)
router.include_router(share_router)
router.include_router(narration_router)
router.include_router(template_router)
router.include_router(export_router)
router.include_router(slide_router)
router.include_router(ai_edit_router)
router.include_router(speech_script_router)
