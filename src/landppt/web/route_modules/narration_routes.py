"""
Narration audio and narration video routes extracted from the legacy web router.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ...auth.middleware import get_current_user_required
from ...core.config import app_config
from ...database.models import User
from ...services.narration_audio_repository import NarrationAudioRepository
from ...services.service_instances import ppt_service
from ...utils.thread_pool import run_blocking_io
from .support import logger

router = APIRouter()


class NarrationGenerateRequest(BaseModel):
    provider: str = "edge_tts"
    language: str = "zh"
    slide_indices: Optional[List[int]] = None
    voice: Optional[str] = None
    rate: str = "+0%"
    reference_audio_path: Optional[str] = None
    reference_text: str = ""
    force_regenerate: bool = False


class NarrationVideoExportRequest(BaseModel):
    language: str = "zh"
    fps: int = 30
    embed_subtitles: bool = True
    subtitle_style: Optional[Dict[str, Any]] = None
    render_mode: str = "live"


class NarrationAudioExportRequest(BaseModel):
    provider: str = "auto"
    language: str = "zh"
    voice: Optional[str] = None
    rate: str = "+0%"
    reference_audio_path: Optional[str] = None
    reference_text: str = ""
    force_regenerate: bool = False


def _resolve_reference_audio_path(project_id: str, raw_reference_audio_path: str | None) -> Optional[str]:
    reference_audio_path = None
    candidate_text = (raw_reference_audio_path or "").strip()
    if not candidate_text:
        return None

    uploads_root = Path("uploads").resolve()
    allowed_dir = (uploads_root / "narration_refs" / project_id).resolve()
    candidate = Path(candidate_text)
    candidate = (Path.cwd() / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if allowed_dir != candidate and allowed_dir not in candidate.parents:
        raise HTTPException(status_code=400, detail="Invalid reference_audio_path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=400, detail="reference_audio_path not found")
    reference_audio_path = str(candidate)
    return reference_audio_path


def _sanitize_narration_entry_name(raw_name: str, fallback_name: str) -> str:
    base_name = (raw_name or "").strip() or fallback_name
    base_name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", base_name)
    base_name = re.sub(r"\s+", " ", base_name).strip(" ._")
    return base_name or fallback_name


def _build_narration_audio_export_zip(
    *,
    project_topic: str,
    slides_data: List[Dict[str, Any]],
    language: str,
    items: List[Any],
) -> str:
    with tempfile.NamedTemporaryFile(prefix="landppt_narration_audio_", suffix=".zip", delete=False) as tmp_file:
        zip_path = tmp_file.name

    manifest: Dict[str, Any] = {
        "project_topic": project_topic,
        "language": language,
        "exported_at": int(time.time()),
        "count": len(items),
        "items": [],
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(items, key=lambda row: int(getattr(row, "slide_index", 0))):
            slide_index = int(getattr(item, "slide_index", 0))
            audio_path = str(getattr(item, "audio_path", "") or "").strip()
            if not audio_path or not os.path.exists(audio_path):
                raise FileNotFoundError(f"Missing narration audio for slide {slide_index + 1}")

            ext = Path(audio_path).suffix or ".mp3"
            slide = slides_data[slide_index] if 0 <= slide_index < len(slides_data) else {}
            slide_title = _sanitize_narration_entry_name(
                str(slide.get("title") or ""),
                f"第{slide_index + 1}页",
            )
            archive_name = f"{slide_index + 1:02d}_{slide_title}{ext}"
            archive.write(audio_path, arcname=archive_name)

            manifest["items"].append(
                {
                    "slide_index": slide_index,
                    "slide_title": slide.get("title") or f"第{slide_index + 1}页",
                    "file_name": archive_name,
                    "duration_ms": getattr(item, "duration_ms", None),
                    "cached": bool(getattr(item, "cached", False)),
                }
            )

        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return zip_path


@router.post("/api/projects/{project_id}/narration/generate")
async def generate_narration_audio(
    project_id: str,
    request: NarrationGenerateRequest,
    user: User = Depends(get_current_user_required),
):
    """Generate slide-level narration audio as a background task."""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        from ...services.background_tasks import get_task_manager

        task_manager = get_task_manager()
        language = (request.language or "zh").strip().lower()
        provider = (request.provider or "edge_tts").strip().lower()

        reference_audio_path = _resolve_reference_audio_path(project_id, request.reference_audio_path)

        existing = await task_manager.find_active_task_async(
            task_type="narration_generation",
            metadata_filter={"project_id": project_id, "language": language, "provider": provider, "user_id": user.id},
        )
        if existing:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "already_processing",
                    "task_id": existing.task_id,
                    "message": "Narration audio generation is already in progress for this project/language",
                    "polling_endpoint": f"/api/landppt/tasks/{existing.task_id}",
                },
            )

        async def narration_task():
            from ...services.narration_service import NarrationService

            service = NarrationService(user_id=user.id)
            items = await service.generate_project_slide_audios(
                project_id=project_id,
                slide_indices=request.slide_indices,
                provider=provider,
                language=language,
                voice=request.voice,
                rate=request.rate,
                reference_audio_path=reference_audio_path,
                reference_text=(request.reference_text or ""),
                force_regenerate=bool(request.force_regenerate),
                uploads_dir="uploads",
            )
            return {
                "success": True,
                "language": language,
                "count": len(items),
                "items": [
                    {
                        "slide_index": item.slide_index,
                        "language": item.language,
                        "voice": item.voice,
                        "rate": item.rate,
                        "audio_path": item.audio_path,
                        "duration_ms": item.duration_ms,
                        "cached": item.cached,
                    }
                    for item in items
                ],
            }

        task_id = task_manager.submit_task(
            task_type="narration_generation",
            func=narration_task,
            metadata={
                "project_id": project_id,
                "project_topic": project.topic,
                "language": language,
                "provider": provider,
                "user_id": user.id,
            },
        )
        return JSONResponse(
            {
                "status": "processing",
                "task_id": task_id,
                "message": "Narration audio generation started in background",
                "polling_endpoint": f"/api/landppt/tasks/{task_id}",
            }
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Narration generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/narration/reference-audio")
async def upload_narration_reference_audio(
    project_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user_required),
):
    """Upload a reference audio file for voice-clone TTS."""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        filename = (file.filename or "").strip()
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
            raise HTTPException(status_code=400, detail=f"Unsupported audio type: {ext or '(none)'}")

        max_bytes = max(int(getattr(app_config, "max_file_size", 10 * 1024 * 1024) or 0), 50 * 1024 * 1024)
        out_dir = Path("uploads") / "narration_refs" / project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{int(time.time())}_{uuid.uuid4().hex[:12]}{ext}"

        size = 0
        with open(out_path, "wb") as file_obj:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    try:
                        out_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise HTTPException(status_code=413, detail="Reference audio too large")
                file_obj.write(chunk)

        return JSONResponse({"success": True, "reference_audio_path": str(out_path)})
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Upload narration reference audio failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/projects/{project_id}/narration/audio/{slide_index}")
async def get_narration_audio(
    project_id: str,
    slide_index: int,
    language: str = "zh",
    autogen: bool = True,
    user: User = Depends(get_current_user_required),
):
    """Download or stream narration audio for a slide."""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        repo = NarrationAudioRepository()
        try:
            row = await repo.get_latest_for_slide(project_id=project_id, slide_index=slide_index, language=language)
            if (not row or not row.file_path or not os.path.exists(row.file_path)) and autogen:
                from ...services.narration_service import NarrationService

                service = NarrationService(user_id=user.id)
                await service.generate_project_slide_audios(
                    project_id=project_id,
                    slide_indices=[int(slide_index)],
                    language=language,
                    uploads_dir="uploads",
                )
                row = await repo.get_latest_for_slide(project_id=project_id, slide_index=slide_index, language=language)

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
        safe_filename = urllib.parse.quote(f"{project.topic}_{language}_slide_{slide_index + 1}{ext}", safe="")
        return FileResponse(
            row.file_path,
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{safe_filename}"},
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Get narration audio failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/projects/{project_id}/narration/cues/{slide_index}")
async def get_narration_cues(
    project_id: str,
    slide_index: int,
    language: str = "zh",
    autogen: bool = True,
    user: User = Depends(get_current_user_required),
):
    """Return timed subtitle cues for a slide narration audio track."""
    try:
        import json as json_lib

        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        repo = NarrationAudioRepository()
        try:
            row = await repo.get_latest_for_slide(project_id=project_id, slide_index=slide_index, language=language)
            if (not row or not row.file_path or not os.path.exists(row.file_path)) and autogen:
                from ...services.narration_service import NarrationService

                service = NarrationService(user_id=user.id)
                await service.generate_project_slide_audios(
                    project_id=project_id,
                    slide_indices=[int(slide_index)],
                    language=language,
                    uploads_dir="uploads",
                )
                row = await repo.get_latest_for_slide(project_id=project_id, slide_index=slide_index, language=language)

            if not row:
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

            if autogen and (((not cues) or cue_version < 2)) and row.file_path and os.path.exists(row.file_path) and row.duration_ms:
                try:
                    from ...services.narration_service import build_cues_json_for_audio
                    from ...services.speech_script_repository import SpeechScriptRepository

                    speech_repo = SpeechScriptRepository()
                    try:
                        scripts = await speech_repo.get_current_speech_scripts_by_project(project_id, language=language)
                        script_by_index = {int(script.slide_index): script for script in scripts}
                        script = script_by_index.get(int(slide_index))
                        text = (script.script_content if script else "") or ""
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
                                project_id=project_id,
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
                    "project_id": project_id,
                    "slide_index": slide_index,
                    "language": language,
                    "duration_ms": row.duration_ms,
                    "cues": cues,
                }
            )
        finally:
            repo.close()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Get narration cues failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/export/narration-audio")
async def export_narration_audio(
    project_id: str,
    request: NarrationAudioExportRequest,
    user: User = Depends(get_current_user_required),
):
    """导出项目讲解音频压缩包。"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        from ...services.background_tasks import TaskStatus, get_task_manager

        task_manager = get_task_manager()
        language = (request.language or "zh").strip().lower() or "zh"
        provider = (request.provider or "auto").strip().lower() or "auto"
        reference_audio_path = _resolve_reference_audio_path(project_id, request.reference_audio_path)

        existing = await task_manager.find_active_task_async(
            task_type="narration_audio_export",
            metadata_filter={"project_id": project_id, "language": language, "user_id": user.id},
        )
        if existing:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "already_processing",
                    "task_id": existing.task_id,
                    "message": "当前项目该语言的讲解音频正在导出中",
                    "polling_endpoint": f"/api/landppt/tasks/{existing.task_id}",
                },
            )

        task_id = ""

        async def export_task():
            from ...services.narration_service import NarrationService

            async def update_export_progress(progress: float, message: str) -> None:
                task = task_manager.tasks.get(task_id)
                if task is not None:
                    task.metadata["progress_message"] = message
                await task_manager.update_task_status_async(
                    task_id,
                    TaskStatus.RUNNING,
                    progress=max(0.0, min(99.0, float(progress))),
                )

            await update_export_progress(5, "正在准备讲解音频导出任务...")

            service = NarrationService(user_id=user.id)
            items = await service.generate_project_slide_audios(
                project_id=project_id,
                slide_indices=None,
                provider=provider,
                language=language,
                voice=request.voice,
                rate=request.rate,
                reference_audio_path=reference_audio_path,
                reference_text=(request.reference_text or ""),
                force_regenerate=bool(request.force_regenerate),
                uploads_dir="uploads",
            )
            if not items:
                raise RuntimeError("未找到可导出的讲解音频")

            await update_export_progress(78, "讲解音频已就绪，正在打包...")
            zip_path = await run_blocking_io(
                _build_narration_audio_export_zip,
                project_topic=project.topic,
                slides_data=project.slides_data or [],
                language=language,
                items=items,
            )
            await update_export_progress(96, "讲解音频打包完成，准备下载...")

            return {
                "success": True,
                "language": language,
                "provider": provider,
                "count": len(items),
                "audio_path": zip_path,
            }

        task_id = task_manager.submit_task(
            task_type="narration_audio_export",
            func=export_task,
            metadata={
                "project_id": project_id,
                "project_topic": project.topic,
                "language": language,
                "provider": provider,
                "user_id": user.id,
                "progress_message": "讲解音频导出任务已创建，等待后台执行...",
            },
        )

        return JSONResponse(
            {
                "status": "processing",
                "task_id": task_id,
                "message": "讲解音频导出已开始，请稍候",
                "polling_endpoint": f"/api/landppt/tasks/{task_id}",
            }
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Narration audio export failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/export/narration-video")
async def export_narration_video(
    project_id: str,
    request: NarrationVideoExportRequest,
    user: User = Depends(get_current_user_required),
):
    """Export narration video (MP4) with optional subtitles."""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if not bool(getattr(user, "is_admin", False)):
            if not app_config.enable_credits_system:
                raise HTTPException(status_code=403, detail="Permission denied")
            try:
                from ...services.credits_service import CreditsService
                from ...database.database import AsyncSessionLocal

                async with AsyncSessionLocal() as session:
                    credits_service = CreditsService(session)
                    balance = await credits_service.get_balance(user.id)
                if int(balance) <= 1_000_000:
                    raise HTTPException(status_code=403, detail="Permission denied")
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to check credits for narration video export (user_id=%s): %s",
                    user.id,
                    exc,
                )
                raise HTTPException(status_code=403, detail="Permission denied")

        from ...services.background_tasks import get_task_manager

        task_manager = get_task_manager()
        language = (request.language or "zh").strip().lower()
        fps = 60 if int(request.fps) == 60 else 30

        existing = await task_manager.find_active_task_async(
            task_type="narration_video_export",
            metadata_filter={"project_id": project_id, "language": language, "fps": fps, "user_id": user.id},
        )
        if existing:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "already_processing",
                    "task_id": existing.task_id,
                    "message": "Narration video export is already in progress for this project/language/fps",
                    "polling_endpoint": f"/api/landppt/tasks/{existing.task_id}",
                },
            )

        async def export_task():
            from ...services.video_export_service import NarrationVideoExportService

            return await NarrationVideoExportService().export_project_video(
                project=project,
                language=language,
                fps=fps,
                width=1920,
                height=1080,
                embed_subtitles=bool(request.embed_subtitles),
                subtitle_style=request.subtitle_style,
                render_mode=(request.render_mode or "live"),
                uploads_dir="uploads",
            )

        task_id = task_manager.submit_task(
            task_type="narration_video_export",
            func=export_task,
            metadata={
                "project_id": project_id,
                "project_topic": project.topic,
                "language": language,
                "fps": fps,
                "user_id": user.id,
            },
        )
        return JSONResponse(
            {
                "status": "processing",
                "task_id": task_id,
                "message": "Narration video export started in background",
                "polling_endpoint": f"/api/landppt/tasks/{task_id}",
            }
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Narration video export failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
