"""
Template-selection routes extracted from the legacy web router.
"""

from __future__ import annotations

import time
from datetime import datetime
import json
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...auth.middleware import get_current_user_required
from ...database.models import User
from .support import (
    check_credits_for_operation,
    consume_credits_for_operation,
    get_ppt_service_for_user,
    logger,
    ppt_service,
)

router = APIRouter()


@router.get("/api/projects/{project_id}/selected-global-template")
async def get_selected_global_template(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """Return the selected project template or the current default template."""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        selected_template = await user_ppt_service.get_selected_global_template(project_id, user_id=user.id)
        if selected_template:
            logger.info(
                "Project %s has selected template: %s",
                project_id,
                selected_template.get("template_name", "Unknown"),
            )
            return {"status": "success", "template": selected_template, "is_user_selected": True}

        default_template = await user_ppt_service.global_template_service.get_default_template()
        if default_template:
            logger.info(
                "Project %s using default template: %s",
                project_id,
                default_template.get("template_name", "Unknown"),
            )
            return {"status": "success", "template": default_template, "is_user_selected": False}

        logger.warning("No template available for project %s", project_id)
        return {"status": "success", "template": None, "is_user_selected": False}
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting selected global template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/projects/{project_id}/free-template")
async def get_project_free_template(
    project_id: str,
    user: User = Depends(get_current_user_required),
):
    """Return the free-template status and current generated template."""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = project.project_metadata or {}
        is_free_mode = metadata.get("template_mode") == "free"
        html = metadata.get("free_template_html")
        template = None
        if isinstance(html, str) and html.strip():
            template = {
                "template_name": metadata.get("free_template_name") or "自由模板",
                "description": "AI 生成的项目专属自由模板",
                "html_template": html,
                "tags": ["自由模板", "AI生成"],
                "created_by": "ai_free",
                "template_mode": "free",
                "is_project_free_template": True,
            }

        return {
            "success": True,
            "enabled": is_free_mode,
            "active_mode": is_free_mode,
            "available": template is not None,
            "message": (
                "项目当前正在使用自由模板"
                if is_free_mode
                else ("项目存在可复用的历史自由模板" if template is not None else "项目当前未使用自由模板")
            ),
            "status": metadata.get("free_template_status"),
            "confirmed": bool(metadata.get("free_template_confirmed")),
            "saved_template_id": metadata.get("saved_global_template_id"),
            "template": template,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting free template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/free-template/generate")
async def generate_project_free_template(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Generate or regenerate a project's free template."""
    try:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        force = bool(payload.get("force", False))
        accept = (request.headers.get("accept") or "").lower()
        stream_flag = payload.get("stream")
        want_stream = True if stream_flag is None else bool(stream_flag)
        if "application/json" in accept and "text/event-stream" not in accept and stream_flag is None:
            want_stream = False

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = project.project_metadata or {}
        if metadata.get("template_mode") != "free":
            raise HTTPException(status_code=400, detail="Project is not using free template mode")

        existing_free_html = metadata.get("free_template_html")
        will_generate = force or not (isinstance(existing_free_html, str) and existing_free_html.strip())

        template_provider_name = None
        if will_generate:
            _, template_settings = await user_ppt_service.global_template_service._get_template_role_provider_async()
            template_provider_name = template_settings.get("provider")
            has_credits, required, balance = await check_credits_for_operation(
                user.id,
                "template_generation",
                1,
                provider_name=template_provider_name,
            )
            if not has_credits:
                message = f"Insufficient credits, need {required}, current {balance}"
                if want_stream:
                    async def _credit_error_stream():
                        yield f"data: {json.dumps({'type': 'error', 'message': message, 'required': required, 'balance': balance}, ensure_ascii=False)}\n\n"

                    return StreamingResponse(
                        _credit_error_stream(),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                    )
                return {"success": False, "error": message}

        if want_stream:
            async def event_stream():
                credits_consumed = False
                try:
                    async for event in user_ppt_service.stream_free_template_generation(
                        project_id,
                        user_id=user.id,
                        force=force,
                    ):
                        if (
                            will_generate
                            and not credits_consumed
                            and (event or {}).get("type") == "complete"
                        ):
                            await consume_credits_for_operation(
                                user.id,
                                "template_generation",
                                1,
                                description="Free template generation",
                                reference_id=project_id,
                                provider_name=template_provider_name,
                            )
                            credits_consumed = True

                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except HTTPException as exc:
                    yield f"data: {json.dumps({'type': 'error', 'message': exc.detail}, ensure_ascii=False)}\n\n"
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error generating free template for project %s: %s", project_id, exc)
                    yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        template = None
        async for event in user_ppt_service.stream_free_template_generation(
            project_id,
            user_id=user.id,
            force=force,
        ):
            if (event or {}).get("type") == "complete":
                template = (event or {}).get("template")
                break
            if (event or {}).get("type") == "error":
                raise HTTPException(status_code=500, detail=(event or {}).get("message") or "Failed to generate free template")

        if not template:
            raise HTTPException(status_code=500, detail="Failed to generate free template")

        if will_generate:
            await consume_credits_for_operation(
                user.id,
                "template_generation",
                1,
                description="Free template generation",
                reference_id=project_id,
                provider_name=template_provider_name,
            )

        return {"success": True, "template": template}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error generating free template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/free-template/confirm")
async def confirm_project_free_template(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Confirm the current free template and optionally save it to the library."""
    try:
        data = await request.json()
        save_to_library = bool(data.get("save_to_library", False))
        requested_name = (data.get("template_name") or "").strip()
        requested_description = (data.get("description") or "").strip()
        requested_tags = data.get("tags") or []
        submitted_html = data.get("html_template")

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = project.project_metadata or {}
        if metadata.get("template_mode") != "free":
            raise HTTPException(status_code=400, detail="Project is not using free template mode")

        html = metadata.get("free_template_html")
        if isinstance(submitted_html, str) and submitted_html.strip():
            html = submitted_html
            metadata["free_template_html"] = submitted_html
        if requested_name:
            metadata["free_template_name"] = requested_name
        if not (isinstance(html, str) and html.strip()):
            raise HTTPException(status_code=400, detail="Free template is not generated yet")

        metadata["free_template_confirmed"] = True
        metadata["free_template_confirmed_at"] = time.time()
        metadata["free_template_status"] = "ready"

        saved_template = None
        if save_to_library:
            base_name = requested_name or f"Free-template-{(project.topic or 'PPT')[:20]}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            description = requested_description or "Template confirmed from free-template mode"
            tags: List[str] = []
            if isinstance(requested_tags, list):
                tags = [str(tag).strip() for tag in requested_tags if str(tag).strip()]
            tags = tags or ["free-template", "ai-generated"]

            final_name = base_name
            for attempt in range(1, 6):
                try:
                    saved_template = await user_ppt_service.global_template_service.create_template(
                        {
                            "template_name": final_name,
                            "description": description,
                            "html_template": html,
                            "tags": tags,
                            "is_default": False,
                            "is_active": True,
                            "created_by": f"free_template:{project_id}",
                        }
                    )
                    break
                except ValueError:
                    final_name = f"{base_name}-{attempt}"

            if not saved_template:
                raise HTTPException(status_code=409, detail="Failed to save template to library")

            metadata["saved_global_template_id"] = saved_template.get("id")
            metadata["saved_global_template_name"] = saved_template.get("template_name")

        await user_ppt_service.project_manager.update_project_metadata(project_id, metadata)
        user_ppt_service.clear_cached_style_genes(project_id)
        return {"success": True, "saved_template": saved_template}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error confirming free template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/projects/{project_id}/free-template/adjust")
async def adjust_project_free_template(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Adjust the generated free template based on user feedback."""
    try:
        data = await request.json()
        adjustment_request = (data.get("adjustment_request") or "").strip()
        if not adjustment_request:
            raise HTTPException(status_code=400, detail="Adjustment request is required")

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = project.project_metadata or {}
        if metadata.get("template_mode") != "free":
            raise HTTPException(status_code=400, detail="Project is not using free template mode")

        current_html = metadata.get("free_template_html")
        if not (isinstance(current_html, str) and current_html.strip()):
            raise HTTPException(status_code=400, detail="Free template is not generated yet")

        template_name = metadata.get("free_template_name") or "Free template"
        _, template_settings = await user_ppt_service.global_template_service._get_template_role_provider_async()
        template_provider_name = template_settings.get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user.id,
            "template_generation",
            1,
            provider_name=template_provider_name,
        )
        if not has_credits:
            return {"success": False, "error": f"Insufficient credits, need {required}, current {balance}"}

        adjusted_html = None
        async for chunk in user_ppt_service.global_template_service.adjust_template_with_ai_stream(
            current_html=current_html,
            adjustment_request=adjustment_request,
            template_name=template_name,
        ):
            if chunk.get("type") == "complete":
                adjusted_html = chunk.get("html_template")
                break
            if chunk.get("type") == "error":
                raise HTTPException(status_code=500, detail=chunk.get("message", "Template adjustment failed"))

        if not adjusted_html:
            raise HTTPException(status_code=500, detail="Failed to adjust template")

        metadata["free_template_html"] = adjusted_html
        metadata["free_template_adjusted_at"] = time.time()
        metadata["free_template_adjustment_request"] = adjustment_request
        metadata["free_template_confirmed"] = False
        await user_ppt_service.project_manager.update_project_metadata(project_id, metadata)
        user_ppt_service.clear_cached_style_genes(project_id)

        await consume_credits_for_operation(
            user.id,
            "template_generation",
            1,
            description="Free template adjustment",
            reference_id=project_id,
            provider_name=template_provider_name,
        )

        return {
            "success": True,
            "template": {
                "template_name": template_name,
                "html_template": adjusted_html,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error adjusting free template for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
