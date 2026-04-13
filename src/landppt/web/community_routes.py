"""
Public community-facing pages.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..auth.middleware import get_current_user_optional
from ..database.models import User
from ..services.community_service import community_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["community"])
templates = Jinja2Templates(directory="src/landppt/web/templates")


@router.get("/api/community/public-settings")
async def get_public_community_settings():
    """Expose public-safe community settings for public pages."""
    try:
        settings = await community_service.get_settings()
        return community_service.build_public_settings_payload(settings)
    except Exception as exc:
        logger.warning("Failed to load public community settings: %s", exc)
        return community_service.build_public_settings_payload({})


@router.get("/sponsors", response_class=HTMLResponse)
async def sponsor_thanks_page(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    """Public sponsor thank-you page."""
    settings = await community_service.get_settings()
    sponsor_page_enabled = bool(settings.get("sponsor_page_enabled"))
    preview_mode = bool(user and user.is_admin and not sponsor_page_enabled)

    if not sponsor_page_enabled and not preview_mode:
        raise HTTPException(status_code=404, detail="Page not found")

    sponsors = await community_service.get_public_sponsors()
    return templates.TemplateResponse(
        "pages/community/sponsor_thanks.html",
        {
            "request": request,
            "user": user,
            "sponsors": sponsors,
            "sponsor_page_enabled": sponsor_page_enabled,
            "preview_mode": preview_mode,
        },
    )
