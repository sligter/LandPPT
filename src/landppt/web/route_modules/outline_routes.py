"""
Outline route aggregator.
"""

from fastapi import APIRouter

from .outline_generation_routes import router as outline_generation_router
from .outline_requirements_routes import router as outline_requirements_router

router = APIRouter()
router.include_router(outline_requirements_router)
router.include_router(outline_generation_router)
