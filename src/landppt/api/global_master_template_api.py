"""
Global Master Template API endpoints
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import JSONResponse

from .models import (
    GlobalMasterTemplateCreate, GlobalMasterTemplateUpdate, GlobalMasterTemplateResponse,
    GlobalMasterTemplateDetailResponse, GlobalMasterTemplateGenerateRequest,
    TemplateSelectionRequest, TemplateSelectionResponse
)
from ..services.template.global_master_template_service import GlobalMasterTemplateService
from ..auth.middleware import get_current_user_required
from ..core.config import app_config
from ..database.database import AsyncSessionLocal
from ..services.credits_service import CreditsService

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/global-master-templates", tags=["Global Master Templates"])


def _template_service_for_user(
    user,
    *,
    allow_system_template_write: bool = False,
) -> GlobalMasterTemplateService:
    """Create a user-scoped template service instance."""
    return GlobalMasterTemplateService(
        user_id=user.id,
        allow_system_template_write=bool(
            allow_system_template_write and getattr(user, "is_admin", False)
        ),
    )


@router.post("/", response_model=GlobalMasterTemplateResponse)
async def create_template(
    template_data: GlobalMasterTemplateCreate,
    user=Depends(get_current_user_required),
):
    """Create a new global master template"""
    try:
        template_service = _template_service_for_user(user)
        payload = template_data.model_dump()
        if (payload.get("created_by") or "").strip().lower() == "user":
            payload["created_by"] = f"user:{user.id}"
        result = await template_service.create_template(payload)
        return GlobalMasterTemplateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create template: {e}")
        raise HTTPException(status_code=500, detail="Failed to create template")


@router.get("/", response_model=dict)
async def get_all_templates(
    active_only: bool = Query(True, description="Only return active templates"),
    tags: Optional[str] = Query(None, description="Filter by tags (comma-separated)"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(6, ge=1, le=100, description="Number of items per page"),
    search: Optional[str] = Query(None, description="Search in template name and description"),
    user=Depends(get_current_user_required),
):
    """Get all global master templates with pagination"""
    try:
        template_service = _template_service_for_user(user)
        if tags:
            tag_list = [tag.strip() for tag in tags.split(",")]
            result = await template_service.get_templates_by_tags_paginated(
                tag_list, active_only, page, page_size, search
            )
        else:
            result = await template_service.get_all_templates_paginated(
                active_only, page, page_size, search
            )

        return {
            "templates": [GlobalMasterTemplateResponse(**template) for template in result["templates"]],
            "pagination": result["pagination"]
        }
    except Exception as e:
        logger.error(f"Failed to get templates: {e}")
        raise HTTPException(status_code=500, detail="Failed to get templates")


@router.put("/{template_id}", response_model=dict)
async def update_template(
    template_id: int,
    update_data: GlobalMasterTemplateUpdate,
    user=Depends(get_current_user_required),
):
    """Update a global master template"""
    try:
        template_service = _template_service_for_user(
            user,
            allow_system_template_write=True,
        )
        # Filter out None values
        update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
        
        if not update_dict:
            raise HTTPException(status_code=400, detail="No update data provided")
        
        success = await template_service.update_template(template_id, update_dict)
        if not success:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return {"success": True, "message": "Template updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update template {template_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update template")


@router.delete("/{template_id}", response_model=dict)
async def delete_template(template_id: int, user=Depends(get_current_user_required)):
    """Delete a global master template"""
    try:
        template_service = _template_service_for_user(
            user,
            allow_system_template_write=True,
        )
        success = await template_service.delete_template(template_id)
        if not success:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return {"success": True, "message": "Template deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete template {template_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete template")


@router.post("/{template_id}/set-default", response_model=dict)
async def set_default_template(template_id: int, user=Depends(get_current_user_required)):
    """Set a template as the default template"""
    try:
        template_service = _template_service_for_user(
            user,
            allow_system_template_write=True,
        )
        success = await template_service.set_default_template(template_id)
        if not success:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return {"success": True, "message": "Default template set successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set default template {template_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to set default template")


@router.get("/default/template", response_model=GlobalMasterTemplateDetailResponse)
async def get_default_template(user=Depends(get_current_user_required)):
    """Get the default global master template"""
    try:
        template_service = _template_service_for_user(user)
        template = await template_service.get_default_template()
        if not template:
            raise HTTPException(status_code=404, detail="No default template found")
        
        return GlobalMasterTemplateDetailResponse(**template)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get default template: {e}")
        raise HTTPException(status_code=500, detail="Failed to get default template")


@router.get("/{template_id}", response_model=GlobalMasterTemplateDetailResponse)
async def get_template_by_id(template_id: int, user=Depends(get_current_user_required)):
    """Get a global master template by ID"""
    try:
        template_service = _template_service_for_user(user)
        template = await template_service.get_template_by_id(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return GlobalMasterTemplateDetailResponse(**template)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get template {template_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get template")


@router.post("/generate")
async def generate_template_with_ai(
    request: GlobalMasterTemplateGenerateRequest,
    user = Depends(get_current_user_required)
):
    """Generate a new template using AI (does not save to database)"""
    try:
        # Create service with user_id for proper landppt config handling
        user_template_service = GlobalMasterTemplateService(user_id=user.id)

        # Credits: only bill LandPPT official provider.
        provider_name = None
        if app_config.enable_credits_system:
            try:
                _, template_settings = await user_template_service._get_template_role_provider_async()
                provider_name = template_settings.get("provider")
            except Exception as e:
                logger.warning(f"Failed to resolve template provider for credits check: {e}")

            if (provider_name or "").strip().lower() == "landppt":
                async with AsyncSessionLocal() as session:
                    credits_service = CreditsService(session)
                    required = credits_service.get_operation_cost("template_generation", 1)
                    balance = await credits_service.get_balance(user.id)
                    if balance < required:
                        return {
                            "success": False,
                            "message": f"积分不足，模板生成需要{required}积分，当前余额{balance}积分",
                            "required": required,
                            "balance": balance,
                        }
        
        # 准备参考图片数据
        reference_image_data = None
        if request.reference_image:
            reference_image_data = {
                "filename": request.reference_image.filename,
                "data": request.reference_image.data,
                "size": request.reference_image.size,
                "type": request.reference_image.type
            }
        reference_pptx_data = None
        if getattr(request, "reference_pptx", None):
            reference_pptx_data = {
                "filename": request.reference_pptx.filename,
                "data": request.reference_pptx.data,
                "size": request.reference_pptx.size,
                "type": request.reference_pptx.type,
            }

        # 使用AI生成服务（不保存到数据库）
        result = await user_template_service.generate_template_with_ai(
            prompt=request.prompt,
            template_name=request.template_name,
            description=request.description,
            tags=request.tags,
            generation_mode=request.generation_mode,
            reference_image=reference_image_data,
            reference_pptx=reference_pptx_data,
        )

        # Deduct credits after successful generation.
        if app_config.enable_credits_system and (provider_name or "").strip().lower() == "landppt":
            try:
                async with AsyncSessionLocal() as session:
                    credits_service = CreditsService(session)
                    await credits_service.consume_credits(
                        user_id=user.id,
                        operation_type="template_generation",
                        quantity=1,
                        description="AI模板生成",
                        reference_id=f"global_master_template:{request.template_name or ''}".rstrip(":"),
                    )
            except Exception as e:
                logger.error(f"Failed to consume credits for template generation: {e}")

        return {
            "success": True,
            "message": "模板生成完成！",
            "data": result
        }

    except Exception as e:
        logger.error(f"Failed to generate template with AI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save-generated", response_model=GlobalMasterTemplateResponse)
async def save_generated_template(
    request: dict,
    user=Depends(get_current_user_required),
):
    """Save a generated template after user confirmation"""
    try:
        template_service = _template_service_for_user(user)
        # Extract template data from request
        template_data = {
            'template_name': request.get('template_name'),
            'description': request.get('description', ''),
            'html_template': request.get('html_template'),
            'tags': request.get('tags', []),
            'created_by': 'AI'
        }

        # Add timestamp to avoid name conflicts
        import time
        timestamp = int(time.time())
        template_data['template_name'] = f"{template_data['template_name']}_{timestamp}"

        result = await template_service.create_template(template_data)
        return GlobalMasterTemplateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to save generated template: {e}")
        raise HTTPException(status_code=500, detail="Failed to save template")


@router.post("/adjust-template")
async def adjust_template(
    payload: dict,
    user=Depends(get_current_user_required),
    http_request: Request = None,
):
    """Adjust a generated template based on user feedback"""
    from fastapi.responses import StreamingResponse
    import json

    user_template_service = GlobalMasterTemplateService(user_id=user.id)

    template_data = payload.get("template_data") or {}
    current_html = (
        payload.get("html_template")
        or template_data.get("html_template")
        or template_data.get("html")
    )
    adjustment_request = (
        payload.get("adjustment_request")
        or payload.get("adjustment")
        or template_data.get("adjustment_request")
    )
    template_name = (
        payload.get("template_name")
        or template_data.get("template_name")
        or "模板"
    )

    # Decide response mode:
    # - SSE when the client explicitly asks (`Accept: text/event-stream`) or `stream=true`.
    accept = ((http_request.headers.get("accept") if http_request else "") or "").lower()
    stream_flag = payload.get("stream")
    want_stream = ("text/event-stream" in accept) or bool(stream_flag)

    if not (isinstance(current_html, str) and current_html.strip()):
        if want_stream:
            async def _err():
                yield f"data: {json.dumps({'type': 'error', 'message': 'html_template is required'})}\n\n"
            return StreamingResponse(_err(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
        raise HTTPException(status_code=400, detail="html_template is required")

    if not (isinstance(adjustment_request, str) and adjustment_request.strip()):
        if want_stream:
            async def _err():
                yield f"data: {json.dumps({'type': 'error', 'message': 'adjustment_request is required'})}\n\n"
            return StreamingResponse(_err(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
        raise HTTPException(status_code=400, detail="adjustment_request is required")

    provider_name = None
    required = 0
    balance = 0
    if app_config.enable_credits_system:
        try:
            _, template_settings = await user_template_service._get_template_role_provider_async()
            provider_name = template_settings.get("provider")
        except Exception as e:
            logger.warning(f"Failed to resolve template provider for credits check: {e}")

        if (provider_name or "").strip().lower() == "landppt":
            async with AsyncSessionLocal() as session:
                credits_service = CreditsService(session)
                required = credits_service.get_operation_cost("template_generation", 1)
                balance = await credits_service.get_balance(user.id)
                if balance < required:
                    message = f"积分不足，模板调整需要{required}积分，当前余额{balance}积分"
                    if want_stream:
                        async def _err():
                            yield f"data: {json.dumps({'type': 'error', 'message': message, 'required': required, 'balance': balance})}\n\n"
                        return StreamingResponse(_err(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
                    return {"success": False, "message": message, "required": required, "balance": balance}

    if want_stream:
        async def adjust_stream():
            try:
                # Send initial status
                yield f"data: {json.dumps({'type': 'status', 'message': '正在分析调整需求...'})}\n\n"

                credits_consumed = False
                async for chunk in user_template_service.adjust_template_with_ai_stream(
                    current_html=current_html,
                    adjustment_request=adjustment_request,
                    template_name=template_name,
                ):
                    if (
                        app_config.enable_credits_system
                        and (provider_name or "").strip().lower() == "landppt"
                        and (chunk or {}).get("type") == "complete"
                        and not credits_consumed
                    ):
                        try:
                            async with AsyncSessionLocal() as session:
                                credits_service = CreditsService(session)
                                await credits_service.consume_credits(
                                    user_id=user.id,
                                    operation_type="template_generation",
                                    quantity=1,
                                    description="AI模板调整",
                                    reference_id=f"global_master_template_adjust:{template_name}".rstrip(":"),
                                )
                            credits_consumed = True
                        except Exception as e:
                            logger.error(f"Failed to consume credits for template adjustment: {e}")

                    yield f"data: {json.dumps(chunk)}\n\n"

            except Exception as e:
                logger.error(f"Failed to adjust template: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return StreamingResponse(
            adjust_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # Default: return JSON (more compatible with `apiClient` callers).
    complete_event = None
    async for chunk in user_template_service.adjust_template_with_ai_stream(
        current_html=current_html,
        adjustment_request=adjustment_request,
        template_name=template_name,
    ):
        if (chunk or {}).get("type") == "error":
            raise HTTPException(status_code=500, detail=(chunk or {}).get("message") or "Template adjustment failed")
        if (chunk or {}).get("type") == "complete" and (chunk or {}).get("html_template"):
            complete_event = chunk
            break

    if not complete_event:
        raise HTTPException(status_code=500, detail="Template adjustment failed")

    if app_config.enable_credits_system and (provider_name or "").strip().lower() == "landppt":
        try:
            async with AsyncSessionLocal() as session:
                credits_service = CreditsService(session)
                await credits_service.consume_credits(
                    user_id=user.id,
                    operation_type="template_generation",
                    quantity=1,
                    description="AI模板调整",
                    reference_id=f"global_master_template_adjust:{template_name}".rstrip(":"),
                )
        except Exception as e:
            logger.error(f"Failed to consume credits for template adjustment: {e}")

    return {"success": True, "data": complete_event}


@router.post("/select", response_model=TemplateSelectionResponse)
async def select_template_for_project(
    request: TemplateSelectionRequest,
    user=Depends(get_current_user_required),
):
    """Select a template for PPT generation"""
    try:
        template_service = _template_service_for_user(user)
        if request.selected_template_id:
            # Get the selected template
            template = await template_service.get_template_by_id(request.selected_template_id)
            if not template:
                raise HTTPException(status_code=404, detail="Selected template not found")
            
            # Increment usage count
            await template_service.increment_template_usage(request.selected_template_id)
            
            return TemplateSelectionResponse(
                success=True,
                message="Template selected successfully",
                selected_template=GlobalMasterTemplateResponse(**template)
            )
        else:
            # Use default template
            template = await template_service.get_default_template()
            if not template:
                raise HTTPException(status_code=404, detail="No default template found")
            
            # Increment usage count
            await template_service.increment_template_usage(template['id'])
            
            return TemplateSelectionResponse(
                success=True,
                message="Default template selected",
                selected_template=GlobalMasterTemplateResponse(**template)
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to select template: {e}")
        raise HTTPException(status_code=500, detail="Failed to select template")


@router.post("/{template_id}/duplicate", response_model=GlobalMasterTemplateResponse)
async def duplicate_template(
    template_id: int,
    new_name: str = Query(..., description="New template name"),
    user=Depends(get_current_user_required),
):
    """Duplicate an existing template"""
    try:
        template_service = _template_service_for_user(user)
        # Get the original template
        original = await template_service.get_template_by_id(template_id)
        if not original:
            raise HTTPException(status_code=404, detail="Template not found")
        
        # Create duplicate data
        duplicate_data = {
            'template_name': new_name,
            'description': f"复制自: {original['template_name']}",
            'html_template': original['html_template'],
            'tags': original['tags'] + ['复制'],
            'created_by': 'duplicate'
        }
        
        result = await template_service.create_template(duplicate_data)
        return GlobalMasterTemplateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to duplicate template {template_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to duplicate template")


@router.get("/{template_id}/preview", response_model=dict)
async def get_template_preview(template_id: int, user=Depends(get_current_user_required)):
    """Get template preview data"""
    try:
        template_service = _template_service_for_user(user)
        template = await template_service.get_template_by_id(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return {
            "id": template['id'],
            "template_name": template['template_name'],
            "preview_image": template['preview_image'],
            "html_template": template['html_template']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get template preview {template_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get template preview")


# Add increment usage endpoint for internal use
@router.post("/{template_id}/increment-usage", response_model=dict)
async def increment_template_usage(template_id: int, user=Depends(get_current_user_required)):
    """Increment template usage count (internal use)"""
    try:
        template_service = _template_service_for_user(user)
        success = await template_service.increment_template_usage(template_id)
        if not success:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return {"success": True, "message": "Usage count incremented"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to increment usage for template {template_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to increment usage count")
