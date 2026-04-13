"""
Share and public presentation routes extracted from the legacy web router.
"""

from __future__ import annotations

import os
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ...api.models import PPTProject
from ...auth.middleware import get_current_user_required
from ...database.database import get_db
from ...database.models import User
from ...services.db_project_manager import DatabaseProjectManager
from ...services.narration_audio_repository import NarrationAudioRepository
from ...services.service_instances import ppt_service
from ...services.share_service import ShareService
from .support import _apply_no_store_headers, logger, templates

router = APIRouter()


async def _get_owned_project_or_404(project_id: str, user: User):
    """Resolve a project only within the authenticated user's ownership scope."""
    project = await DatabaseProjectManager().get_project(project_id, user_id=user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/share/{share_token}", response_class=HTMLResponse)
async def web_shared_presentation(
    request: Request,
    share_token: str,
    db: Session = Depends(get_db),
):
    """Public presentation view with the latest persisted slide content."""
    try:
        from ...database.models import SlideData as DBSlideData
        from ...database.models import SpeechScript

        share_service = ShareService(db)
        project_model = share_service.validate_share_token(share_token)
        if not project_model:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "Invalid or expired share link"},
            )

        slides_db = (
            db.query(DBSlideData)
            .filter(DBSlideData.project_id == project_model.project_id)
            .order_by(DBSlideData.slide_index)
            .all()
        )
        slides_data = [
            {
                "slide_id": slide.slide_id,
                "slide_index": slide.slide_index,
                "title": slide.title,
                "content_type": slide.content_type,
                "html_content": slide.html_content,
                "metadata": slide.slide_metadata or {},
                "is_user_edited": slide.is_user_edited,
            }
            for slide in slides_db
        ]

        if not slides_data:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "Presentation has not been generated yet"},
            )

        project = PPTProject(
            project_id=project_model.project_id,
            title=project_model.title,
            scenario=project_model.scenario,
            topic=project_model.topic,
            requirements=project_model.requirements,
            status=project_model.status,
            outline=project_model.outline,
            slides_html=project_model.slides_html,
            slides_data=slides_data,
            confirmed_requirements=project_model.confirmed_requirements,
            version=project_model.version,
            created_at=project_model.created_at,
            updated_at=project_model.updated_at,
        )

        narration_languages: list[str] = []
        try:
            for language in ("zh", "en"):
                exists = (
                    db.query(SpeechScript.id)
                    .filter(
                        SpeechScript.project_id == project_model.project_id,
                        SpeechScript.language == language,
                    )
                    .first()
                )
                if exists:
                    narration_languages.append(language)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to resolve speech scripts existence for shared project %s: %s",
                project_model.project_id,
                exc,
            )

        response = templates.TemplateResponse(
            "pages/project/project_fullscreen_presentation.html",
            {
                "request": request,
                "project": project,
                "slides_count": len(project.slides_data),
                "is_shared": True,
                "share_token": share_token,
                "has_speech_scripts": bool(narration_languages),
                "narration_languages": narration_languages,
            },
        )
        return _apply_no_store_headers(response)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error displaying shared presentation: %s", exc)
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": f"Failed to load shared presentation: {exc}"},
        )


@router.get("/api/share/{share_token}/slides-data")
async def get_shared_slides_data(
    share_token: str,
    db: Session = Depends(get_db),
):
    """Return the latest stored slide data for a shared presentation."""
    try:
        from ...database.models import SlideData as DBSlideData

        share_service = ShareService(db)
        project = share_service.validate_share_token(share_token)
        if not project:
            raise HTTPException(status_code=404, detail="Invalid or expired share link")

        slides_db = (
            db.query(DBSlideData)
            .filter(DBSlideData.project_id == project.project_id)
            .order_by(DBSlideData.slide_index)
            .all()
        )

        slides_data = []
        max_updated_at = project.updated_at
        for slide in slides_db:
            slides_data.append(
                {
                    "slide_id": slide.slide_id,
                    "slide_index": slide.slide_index,
                    "title": slide.title,
                    "content_type": slide.content_type,
                    "html_content": slide.html_content,
                    "metadata": slide.slide_metadata or {},
                    "is_user_edited": slide.is_user_edited,
                }
            )
            if getattr(slide, "updated_at", None) and slide.updated_at > max_updated_at:
                max_updated_at = slide.updated_at

        if not slides_data:
            return {
                "status": "no_slides",
                "message": "Presentation has not been generated yet",
                "slides_data": [],
                "total_slides": 0,
            }

        return {
            "status": "success",
            "slides_data": slides_data,
            "total_slides": len(slides_data),
            "project_title": project.title,
            "updated_at": max_updated_at,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting shared slides data: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to get shared slides data: {exc}")


@router.get("/api/share/{share_token}/narration/audio/{slide_index}")
async def get_shared_narration_audio(
    share_token: str,
    slide_index: int,
    language: str = "zh",
    db: Session = Depends(get_db),
):
    """Stream cached narration audio for a shared presentation."""
    try:
        share_service = ShareService(db)
        project_model = share_service.validate_share_token(share_token)
        if not project_model:
            raise HTTPException(status_code=404, detail="Invalid or expired share link")

        repo = NarrationAudioRepository()
        try:
            row = await repo.get_latest_for_slide(
                project_id=project_model.project_id,
                slide_index=slide_index,
                language=language,
            )
            if not row or not row.file_path or not os.path.exists(row.file_path):
                raise HTTPException(status_code=404, detail="Narration audio not found")
        finally:
            repo.close()

        ext = os.path.splitext(row.file_path)[1].lower() or ".mp3"
        media_type = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
        }.get(ext, "application/octet-stream")
        safe_filename = urllib.parse.quote(
            f"{(project_model.topic or project_model.title or 'project')}_{language}_slide_{slide_index + 1}{ext}",
            safe="",
        )
        return FileResponse(
            row.file_path,
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{safe_filename}"},
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Get shared narration audio failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/share/{share_token}/narration/cues/{slide_index}")
async def get_shared_narration_cues(
    share_token: str,
    slide_index: int,
    language: str = "zh",
    db: Session = Depends(get_db),
):
    """Return cached narration cues for a shared presentation."""
    try:
        import json as json_lib

        share_service = ShareService(db)
        project_model = share_service.validate_share_token(share_token)
        if not project_model:
            raise HTTPException(status_code=404, detail="Invalid or expired share link")

        repo = NarrationAudioRepository()
        try:
            row = await repo.get_latest_for_slide(
                project_id=project_model.project_id,
                slide_index=slide_index,
                language=language,
            )
            if not row or not getattr(row, "file_path", None) or not os.path.exists(row.file_path):
                raise HTTPException(status_code=404, detail="Narration audio not found")

            cues: list[dict[str, object]] = []
            cue_version = 0
            if getattr(row, "cues_json", None):
                try:
                    cues = json_lib.loads(row.cues_json) or []
                except Exception:
                    cues = []
                try:
                    from ...services.narration_service import _extract_cue_payload_version

                    cue_version = _extract_cue_payload_version(row.cues_json)
                except Exception:
                    cue_version = 0

            if ((not cues) or cue_version < 2) and row.duration_ms:
                try:
                    from ...services.narration_service import build_cues_json_for_audio
                    from ...services.speech_script_repository import SpeechScriptRepository

                    speech_repo = SpeechScriptRepository(db)
                    try:
                        scripts = await speech_repo.get_current_speech_scripts_by_project(
                            project_model.project_id,
                            language=language,
                        )
                        script_by_index = {int(script.slide_index): script for script in scripts}
                        text = (script_by_index.get(int(slide_index)).script_content if script_by_index.get(int(slide_index)) else "") or ""
                    finally:
                        speech_repo.close()

                    if text.strip():
                        cues_json = await build_cues_json_for_audio(
                            text=text,
                            audio_path=row.file_path,
                            duration_ms=int(row.duration_ms),
                        )
                        if cues_json:
                            await repo.upsert_audio(
                                project_id=project_model.project_id,
                                slide_index=int(slide_index),
                                language=language,
                                provider=getattr(row, "provider", "edge_tts"),
                                voice=getattr(row, "voice", ""),
                                rate=getattr(row, "rate", "+0%"),
                                audio_format=getattr(row, "audio_format", "mp3"),
                                content_hash=getattr(row, "content_hash", ""),
                                file_path=row.file_path,
                                duration_ms=row.duration_ms,
                                cues_json=cues_json,
                            )
                            cues = json_lib.loads(cues_json) or []
                except Exception:
                    pass

            return JSONResponse(
                {
                    "success": True,
                    "project_id": project_model.project_id,
                    "slide_index": slide_index,
                    "language": language,
                    "duration_ms": getattr(row, "duration_ms", None),
                    "cues": cues,
                }
            )
        finally:
            repo.close()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Get shared narration cues failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/share/generate")
async def generate_share_link(
    project_id: str,
    user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """Generate a public share link for a project."""
    try:
        share_service = ShareService(db)
        await _get_owned_project_or_404(project_id, user)

        share_token = share_service.generate_share_token(project_id, user_id=user.id)
        if not share_token:
            raise HTTPException(status_code=500, detail="Failed to generate share link")

        return {
            "success": True,
            "share_token": share_token,
            "share_url": f"/share/{share_token}",
            "message": "Share link generated",
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error generating share link: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to generate share link: {exc}")


@router.post("/api/projects/{project_id}/share/disable")
async def disable_share_link(
    project_id: str,
    user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """Disable sharing for a project."""
    try:
        share_service = ShareService(db)
        await _get_owned_project_or_404(project_id, user)

        if not share_service.disable_sharing(project_id, user_id=user.id):
            raise HTTPException(status_code=500, detail="Failed to disable sharing")

        return {"success": True, "message": "Sharing disabled"}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error disabling share: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to disable sharing: {exc}")


@router.get("/api/projects/{project_id}/share/info")
async def get_share_info(
    project_id: str,
    user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """Get share metadata for a project."""
    try:
        share_service = ShareService(db)
        await _get_owned_project_or_404(project_id, user)

        return {"success": True, **share_service.get_share_info(project_id, user_id=user.id)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting share info: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to get share info: {exc}")
