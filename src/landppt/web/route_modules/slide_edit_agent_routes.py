"""
Slide edit agent web routes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ...auth.middleware import get_current_user_required
from ...database.models import User
from ...services.db_project_manager import DatabaseProjectManager
from ...services.slide.edit_agent import events as agent_events
from ...services.slide.slide_edit_agent_service import (
    SlideEditAgentApplyRequest,
    SlideEditAgentCancelRequest,
    SlideEditAgentRequest,
    SlideEditAgentService,
    agent_run_registry,
    compute_slide_html_hash,
    strip_agent_ids,
    validate_slide_html,
)
from ...services.slide.edit_agent.schema import new_run_id
from .support import (
    check_credits_for_operation,
    consume_credits_for_operation,
    get_ppt_service_for_user,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Cache-Control",
}

_STREAM_SENTINEL = "_agent_done"


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _is_billable_agent_completion(event: dict[str, Any]) -> bool:
    """run 真正跑过至少一轮模型调用才计费。

    立刻被用户停掉、还没发出任何模型请求的 run 不收费。
    """
    if event.get("type") not in agent_events.BILLABLE_EVENT_TYPES:
        return False
    if event.get("status") == "failed":
        return False
    try:
        return int(event.get("iterationsUsed") or 0) > 0
    except (TypeError, ValueError):
        return False


def _agent_provider_role(request: SlideEditAgentRequest) -> str:
    has_vision_input = bool(
        request.slideScreenshot or request.elementScreenshot or request.images
    )
    return "vision_analysis" if request.visionEnabled and has_vision_input else "editor"


async def _charge_completed_agent_run(
    *,
    user_id: int,
    request: SlideEditAgentRequest,
    provider_name: str | None,
) -> None:
    try:
        success, message = await consume_credits_for_operation(
            user_id,
            "ai_edit",
            1,
            description=f"AI Agent edit: slide {request.slideIndex} {request.slideTitle or ''}".strip(),
            reference_id=request.projectId,
            provider_name=provider_name,
        )
        if not success:
            logger.warning("Slide edit agent credit charge failed: %s", message)
    except Exception as exc:  # noqa: BLE001
        logger.error("Slide edit agent credit charge raised: %s", exc, exc_info=True)


@router.post("/api/ai/slide-edit-agent/stream")
async def stream_slide_edit_agent(
    request: SlideEditAgentRequest,
    user: User = Depends(get_current_user_required),
):
    user_ppt_service = get_ppt_service_for_user(user.id)
    role = _agent_provider_role(request)
    _, settings = await user_ppt_service.get_role_provider_async(role)
    provider_name = settings.get("provider")

    run_id = (request.runId or "").strip() or new_run_id()
    request.runId = run_id

    has_credits, required, balance = await check_credits_for_operation(
        user.id,
        "ai_edit",
        1,
        provider_name=provider_name,
    )
    if not has_credits:
        return StreamingResponse(
            iter(
                [
                    _sse(
                        {
                            "type": agent_events.ERROR,
                            "runId": run_id,
                            "phase": "credits",
                            "message": (
                                "Insufficient credits for AI edit. "
                                f"Required: {required}, balance: {balance}."
                            ),
                        }
                    )
                ]
            ),
            media_type="text/event-stream",
            headers=_STREAM_HEADERS,
        )

    async def event_stream():
        charged = False
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        handle = agent_run_registry.register(run_id, user.id)

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def run_agent_task() -> None:
            try:
                service = SlideEditAgentService()
                await service.run_agent(request, user_ppt_service, emit, handle=handle)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Slide edit agent stream failed: %s", exc, exc_info=True)
                await queue.put(
                    {
                        "type": agent_events.RUN_FINISHED,
                        "runId": run_id,
                        "status": "failed",
                        "summary": "Agent 编辑失败。",
                        "error": str(exc) or exc.__class__.__name__,
                    }
                )
            finally:
                await queue.put({"type": _STREAM_SENTINEL})

        task = asyncio.create_task(run_agent_task())
        try:
            while True:
                event = await queue.get()
                if event.get("type") == _STREAM_SENTINEL:
                    break

                if _is_billable_agent_completion(event) and not charged:
                    await _charge_completed_agent_run(
                        user_id=user.id,
                        request=request,
                        provider_name=provider_name,
                    )
                    charged = True

                yield _sse(event)

            await task
        except asyncio.CancelledError:
            # 客户端断开：先置位取消信号，让循环在下一个检查点干净退出。
            handle.cancel("client disconnected")
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise
        finally:
            agent_run_registry.release(run_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


@router.post("/api/ai/slide-edit-agent/apply")
async def apply_slide_edit_agent_proposal(
    request: SlideEditAgentApplyRequest,
    user: User = Depends(get_current_user_required),
):
    if request.slideIndex < 1:
        raise HTTPException(
            status_code=400,
            detail="slideIndex must be 1-based and greater than 0",
        )

    user_ppt_service = get_ppt_service_for_user(user.id)
    project = await user_ppt_service.project_manager.get_project(
        request.projectId,
        user_id=user.id,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    slides_data = project.slides_data or []
    zero_based_index = request.slideIndex - 1
    if zero_based_index >= len(slides_data):
        raise HTTPException(status_code=404, detail="Slide not found")

    existing_slide = slides_data[zero_based_index] or {}
    if not isinstance(existing_slide, dict):
        existing_slide = {}

    current_html = existing_slide.get("html_content") or ""
    from ...services.slide.svg_page.shell import is_svg_page_html

    if compute_slide_html_hash(current_html) != request.expectedBaseHash:
        raise HTTPException(
            status_code=409,
            detail="Slide changed after proposal was created",
        )

    validation = validate_slide_html(request.htmlContent, baseline_html=current_html)
    if not validation.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "errors": validation.errors,
                "warnings": validation.warnings,
            },
        )

    cleaned_html = strip_agent_ids(validation.sanitized_html)
    validation = validate_slide_html(cleaned_html, baseline_html=current_html)
    if not validation.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "errors": validation.errors,
                "warnings": validation.warnings,
            },
        )

    slide_data = {
        **existing_slide,
        **(request.slideData or {}),
        "page_number": request.slideIndex,
        "html_content": validation.sanitized_html,
        "is_user_edited": True,
    }
    if existing_slide.get("render_mode") == "svg" or is_svg_page_html(current_html):
        slide_data["render_mode"] = "svg"
        slide_data.pop("generation_failed", None)
        slide_data.pop("generation_error", None)
        slide_data.pop("svg_report", None)

    db_manager = DatabaseProjectManager()
    saved = await db_manager.save_single_slide(
        request.projectId,
        zero_based_index,
        slide_data,
    )
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save slide")

    return {
        "success": True,
        "proposalId": request.proposalId,
        "slideIndex": request.slideIndex,
        "slideData": slide_data,
        "htmlContent": validation.sanitized_html,
    }


@router.post("/api/ai/slide-edit-agent/cancel")
async def cancel_slide_edit_agent(
    request: SlideEditAgentCancelRequest,
    user: User = Depends(get_current_user_required),
):
    cancelled = agent_run_registry.cancel(request.runId, user.id, reason="cancelled by user")
    return {"success": True, "cancelled": cancelled, "runId": request.runId}
