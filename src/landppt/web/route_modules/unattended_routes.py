"""
Unattended (无人值守) pipeline routes.

Start a run for a project, poll its live per-stage snapshot, and request
cancellation. The heavy lifting lives in ``services/unattended_service.py``; these
handlers only own auth, dedupe, and the inline-vs-queue dispatch decision.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...auth.middleware import get_current_user_required
from ...database.models import User
from ...services.service_instances import ppt_service
from ...services.video_explainer import is_video_explainer
from ...services.unattended_service import (
    STAGE_SPECS,
    UNATTENDED_TASK_TYPE,
    normalize_stop_after,
    request_cancel,
)
from .support import _apply_no_store_headers, logger
from .unattended_support import (
    TERMINAL_TASK_STATUSES,
    default_stage_snapshot,
    require_unattended_admin,
    resolve_unattended_config,
    submit_unattended_run,
)

router = APIRouter()


class UnattendedStartRequest(BaseModel):
    stop_after: Optional[str] = None
    language: Optional[str] = None
    template_id: Optional[int] = None
    template_mode: Literal["auto", "global", "free"] | None = None
    tts_provider: Optional[str] = None
    tts_voice: Optional[str] = None
    tts_rate: Optional[str] = None
    fps: Optional[int] = None
    render_mode: Optional[str] = None
    embed_subtitles: Optional[bool] = None
    notify_in_app: Optional[bool] = None
    notify_email: Optional[bool] = None
    speech_requirements: str = Field(default="", max_length=1600)
    target_duration_seconds: int | None = Field(default=None, ge=1, le=7200)
    max_duration_seconds: int | None = Field(default=None, ge=1, le=7200)
    start_from: Literal["speech_script", "video"] | None = None
    request_id: str | None = Field(default=None, max_length=80)


@router.get("/api/unattended/stages")
async def list_unattended_stages(user: User = Depends(get_current_user_required)):
    """The ordered stage catalogue, for rendering stop-at-stage pickers."""
    return {
        "success": True,
        "stages": [
            {"id": spec.id, "name": spec.name, "description": spec.description}
            for spec in STAGE_SPECS
        ],
    }


@router.post("/api/projects/{project_id}/unattended/start")
@router.post("/api/projects/{project_id}/unattended/start-with-speech")
async def start_unattended_run(
    project_id: str,
    request: UnattendedStartRequest,
    user: User = Depends(get_current_user_required),
):
    """Start (or resume) an unattended run for a project."""
    require_unattended_admin(user)
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if not project.confirmed_requirements:
            raise HTTPException(status_code=400, detail="项目需求尚未确认，无法启动无人值守任务")
        if request.start_from == "video" and normalize_stop_after(request.stop_after) != "video":
            raise HTTPException(status_code=422, detail="仅渲染成片时请选择视频终点")
        if request.start_from == "speech_script" and normalize_stop_after(request.stop_after) not in {
            "speech_script", "narration_audio", "video",
        }:
            raise HTTPException(status_code=422, detail="从讲稿重做时请选择讲稿或更后阶段")
        if (
            not request.start_from
            and (request.template_id or request.template_mode == "global")
            and is_video_explainer(project.confirmed_requirements)
        ):
            raise HTTPException(status_code=422, detail="视频图解项目仅支持自由模板")

        project_language = "zh"
        if isinstance(project.project_metadata, dict):
            project_language = project.project_metadata.get("language", "zh")

        config = await resolve_unattended_config(
            user_id=user.id,
            overrides=request.model_dump(exclude_none=True),
            language=request.language or project_language,
        )
        envelope = await submit_unattended_run(
            project_id=project_id,
            project_topic=project.topic,
            user_id=user.id,
            config=config,
        )
        status_code = 409 if envelope["status"] == "already_processing" else 200
        return JSONResponse({**envelope, "config": config}, status_code=status_code)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to start unattended run for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/projects/{project_id}/unattended/status")
async def get_unattended_status(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """Return the most recent unattended run for a project, running or finished.

    Unlike the generic task endpoint this also returns the live snapshot while the
    run is still in flight, which is what the workspace monitor panel renders.
    """
    try:
        from ...services.background_tasks import get_task_manager

        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        task_manager = get_task_manager()
        task = await task_manager.find_active_task_async(
            task_type=UNATTENDED_TASK_TYPE,
            metadata_filter={"project_id": project_id, "user_id": user.id},
        )

        if task is None:
            task_id = None
            if isinstance(project.project_metadata, dict):
                task_id = project.project_metadata.get("unattended_task_id")
            if task_id:
                task = await task_manager.get_task_async(str(task_id))
                if task and (task.metadata or {}).get("user_id") != user.id:
                    task = None

        if task is None:
            return _apply_no_store_headers(JSONResponse({"success": True, "active": False, "run": None}))

        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        config = metadata.get("config") if isinstance(metadata.get("config"), dict) else {}
        stop_after = normalize_stop_after(config.get("stop_after") or metadata.get("stop_after"))
        snapshot = task.result if isinstance(task.result, dict) and task.result.get("unattended") else None
        task_status = task.status.value if hasattr(task.status, "value") else str(task.status)

        # BackgroundTaskManager maps any result with success=False to FAILED, so a run
        # the user deliberately stopped would otherwise be reported as an error. The
        # snapshot flips to cancelled before the task record does, so trust it
        # unconditionally rather than only once the task has settled on "failed".
        run_status = (snapshot or {}).get("status")
        if run_status == "cancelled":
            task_status = "cancelled"

        run = {
            "task_id": task.task_id,
            "task_status": task_status,
            "status": run_status or ("running" if task_status == "running" else task_status),
            "stop_after": stop_after,
            "request_id": config.get("request_id"),
            "topic": (snapshot or {}).get("topic") or metadata.get("project_topic") or project.topic,
            "language": config.get("language") or metadata.get("language") or "zh",
            "overall_progress": (snapshot or {}).get("overall_progress", task.progress),
            "current_stage": (snapshot or {}).get("current_stage"),
            "stages": (snapshot or {}).get("stages") or default_stage_snapshot(stop_after),
            "error": (snapshot or {}).get("error") or task.error,
            "artifact_id": (snapshot or {}).get("artifact_id"),
            "started_at": (snapshot or {}).get("started_at"),
            "finished_at": (snapshot or {}).get("finished_at"),
        }
        if run["artifact_id"]:
            run["download_url"] = f"/api/landppt/tasks/{task.task_id}/download"

        return _apply_no_store_headers(
            JSONResponse(
                {
                    "success": True,
                    "active": task_status not in TERMINAL_TASK_STATUSES,
                    "run": run,
                }
            )
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load unattended status for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/unattended/cancel")
async def cancel_unattended_run(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """Ask a running pipeline to stop at the next stage boundary."""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        from ...services.background_tasks import get_task_manager

        task = await get_task_manager().find_active_task_async(
            task_type=UNATTENDED_TASK_TYPE,
            metadata_filter={"project_id": project_id, "user_id": user.id},
        )
        await request_cancel(project_id)

        # The PPT stage is the only one that can run for minutes without checking the
        # pipeline flag, so signal its own cooperative cancel too.
        try:
            from ...services.service_instances import get_ppt_service_for_user

            await get_ppt_service_for_user(user.id).request_cancel_slides_generation(project_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not signal slide cancellation for %s: %s", project_id, exc)

        return JSONResponse(
            {
                "success": True,
                "task_id": task.task_id if task else None,
                "message": "已请求取消，当前阶段结束后停止",
            }
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to cancel unattended run for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
