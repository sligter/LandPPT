"""
Web route aggregator for LandPPT.
"""

from fastapi import APIRouter

from .route_modules.ai_edit_routes import router as ai_edit_router
from .route_modules.artifact_library_routes import router as artifact_library_router
from .route_modules.config_routes import router as config_router
from .route_modules.creation_assistant_routes import router as creation_assistant_router
from .route_modules.editor_document_routes import router as editor_document_router
from .route_modules.project_agent_routes import router as project_agent_router
from .route_modules.export_routes import router as export_router
from .route_modules.narration_routes import router as narration_router
from .route_modules.notification_routes import router as notification_router
from .route_modules.outline_routes import router as outline_router
from .route_modules.project_routes import router as project_router
from .route_modules.share_routes import router as share_router
from .route_modules.slide_edit_agent_routes import router as slide_edit_agent_router
from .route_modules.slide_routes import router as slide_router
from .route_modules.speech_script_routes import router as speech_script_router
from .route_modules.source_library_routes import router as source_library_router
from .route_modules.template_routes import router as template_router
from .route_modules.unattended_routes import router as unattended_router

router = APIRouter()
router.include_router(config_router)
router.include_router(artifact_library_router)
router.include_router(source_library_router)
router.include_router(project_router)
router.include_router(outline_router)
router.include_router(share_router)
router.include_router(narration_router)
router.include_router(template_router)
router.include_router(export_router)
router.include_router(slide_router)
router.include_router(ai_edit_router)
router.include_router(creation_assistant_router)
router.include_router(slide_edit_agent_router)
router.include_router(speech_script_router)
router.include_router(editor_document_router)
router.include_router(project_agent_router)
router.include_router(unattended_router)
router.include_router(notification_router)
