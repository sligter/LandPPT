"""
Outline generation routes extracted from the outline router.
"""

from __future__ import annotations

import json
import time
from contextlib import aclosing

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ...api.models import FileOutlineGenerationRequest, PPTGenerationRequest
from ...services.template_package.outline_reference import with_package_reference
from ...auth.middleware import get_current_user_required
from ...database.models import User
from ..responses import ClosingStreamingResponse
from .outline_support import (
    _extract_saved_file_outline,
    _is_billable_provider,
    _resolve_outline_llm_call_count,
    _stream_outline_from_confirmed_sources_v2,
)
from .support import (
    check_credits_for_operation,
    consume_credits_for_operation,
    get_ppt_service_for_user,
    logger,
    ppt_service,
)

router = APIRouter()


class OutlineGenerationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network_mode: StrictBool | None = None
    custom_requirements: str = Field(default="", max_length=4000)


async def _collect_source_outline(project, requirements, user_id, custom_requirements):
    outline = None
    async with aclosing(_stream_outline_from_confirmed_sources_v2(
        project.project_id, project, requirements, user_id=user_id,
        requirements_override=custom_requirements,
    )) as chunks:
        async for chunk in chunks:
            event = json.loads(chunk.removeprefix("data: ").strip())
            if event.get("error"):
                raise ValueError(event["error"])
            if event.get("outline"):
                outline = event["outline"]
    if not outline or not outline.get("slides"):
        raise ValueError("资料大纲生成未产生任何页面")
    return outline


@router.get("/projects/{project_id}/outline-stream")
async def stream_outline_generation(
    project_id: str,
    force_regenerate: bool = False,
    user: User = Depends(get_current_user_required)
):
    """Stream outline generation for a project"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        user_ppt_service = get_ppt_service_for_user(user.id)
        confirmed_requirements = project.confirmed_requirements or {}
        force_file_outline_regeneration = bool(
            confirmed_requirements.get("force_file_outline_regeneration")
        )
        existing_outline = project.outline if isinstance(project.outline, dict) else None
        existing_slides = existing_outline.get("slides", []) if existing_outline else []

        if existing_slides and not force_regenerate and not force_file_outline_regeneration:
            async def generate_saved_outline():
                import json
                try:
                    await user_ppt_service._update_outline_generation_stage(project_id, existing_outline)
                except Exception as stage_error:
                    logger.warning(
                        "Failed to mark saved outline stage completed for project %s: %s",
                        project_id,
                        stage_error,
                    )
                yield f"data: {json.dumps({'status': {'step': 'cached', 'message': '已加载已有大纲', 'progress': 1.0}}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'outline': existing_outline}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'llm_call_count': 0})}\n\n"

            return ClosingStreamingResponse(
                generate_saved_outline(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                },
            )

        _, outline_settings = await user_ppt_service.get_role_provider_async("outline")
        outline_provider_name = outline_settings.get("provider")

        has_credits, required, balance = await check_credits_for_operation(
            user.id,
            "outline_generation",
            1,
            provider_name=outline_provider_name,
        )
        if not has_credits:
            async def generate():
                import json
                yield f"data: {json.dumps({'error': f'积分不足，大纲生成需要 {required} 积分，当前余额 {balance} 积分'})}\n\n"
            return ClosingStreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                },
            )

        async def generate():
            billed = False
            content_source = confirmed_requirements.get("content_source")
            force_fresh_generation = bool(force_regenerate or force_file_outline_regeneration)
            if force_fresh_generation:
                logger.info(
                    "Project %s outline stream requested fresh regeneration; skipping reusable outline branches",
                    project_id,
                )
            has_saved_file_outline = (
                False if force_fresh_generation
                else (_extract_saved_file_outline(project, confirmed_requirements) is not None)
            )

            try:
                chunk_source = user_ppt_service.generate_outline_streaming(
                    project_id,
                    force_regenerate=force_fresh_generation,
                )
                if content_source in ("file", "url", "mixed") and (
                    force_fresh_generation or not has_saved_file_outline
                ):
                    await user_ppt_service.project_manager.update_project_status(
                        project_id, "in_progress", user_id=user.id
                    )
                    await user_ppt_service.project_manager.update_stage_status(
                        project_id, "outline_generation", "running", 0.0, user_id=user.id
                    )
                    chunk_source = _stream_outline_from_confirmed_sources_v2(
                        project_id,
                        project,
                        confirmed_requirements,
                        user_id=user.id,
                    )

                # Own the stream: on client disconnect this generator would
                # otherwise be left to the loop's finalizer, which unwinds the
                # conversation scope in a copied Context.
                async with aclosing(chunk_source):
                    async for chunk in chunk_source:
                        # Bill BEFORE yielding the completion event. Billing afterwards
                        # meant a client that disconnected right after receiving `done`
                        # closed the generator before the charge was applied.
                        if not billed and _is_billable_provider(outline_provider_name):
                            for line in str(chunk).splitlines():
                                if not line.startswith("data: "):
                                    continue
                                try:
                                    import json
                                    payload = json.loads(line[6:])
                                except Exception:
                                    continue
                                if payload.get("done") is True:
                                    billed = True
                                    llm_call_count = payload.get("llm_call_count", 1)
                                    try:
                                        llm_call_count = max(0, int(llm_call_count))
                                    except Exception:
                                        llm_call_count = 1

                                    if llm_call_count > 0:
                                        await consume_credits_for_operation(
                                            user.id,
                                            "outline_generation",
                                            llm_call_count,
                                            description=f"大纲生成(流式): {project.topic}",
                                            reference_id=project_id,
                                            provider_name=outline_provider_name,
                                        )
                        yield chunk
            except Exception as e:
                import json
                # Record the failure: leaving the stage "running" made the todo board
                # spin forever with no error and no retry affordance.
                try:
                    await user_ppt_service.project_manager.update_stage_status(
                        project_id, "outline_generation", "failed", None, user_id=user.id
                    )
                except Exception as stage_error:
                    logger.warning(
                        "Could not mark outline_generation failed for %s: %s",
                        project_id, stage_error
                    )
                error_response = {'error': str(e)}
                yield f"data: {json.dumps(error_response)}\n\n"

        return ClosingStreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                # For nginx/traefik buffering; safe to include even if unused.
                "X-Accel-Buffering": "no",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/generate-outline")
@router.post("/projects/{project_id}/generate-outline-with-options")
async def generate_outline(
    project_id: str,
    user: User = Depends(get_current_user_required),
    options: OutlineGenerationOptions | None = None,
):
    """Generate outline for a project (non-streaming)"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check if project has confirmed requirements
        if not project.confirmed_requirements:
            return {
                "status": "error",
                "error": "项目需求尚未确认，请先完成需求确认步骤"
            }

        source_type = project.confirmed_requirements.get("content_source")
        if source_type == "mixed" and options is None:
            return {"status": "success", "defer_generation": True, "message": "请通过大纲生成工作区合并文件与网页资料。"}

        # Check credits before generating outline
        user_ppt_service = get_ppt_service_for_user(user.id)
        _, outline_settings = await user_ppt_service.get_role_provider_async("outline")
        outline_provider_name = outline_settings.get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user.id, "outline_generation", 1, provider_name=outline_provider_name
        )
        if not has_credits:
            return {
                "status": "error",
                "error": f"积分不足，大纲生成需要 {required} 积分，当前余额 {balance} 积分"
            }


        # Create PPTGenerationRequest from project data
        confirmed_requirements = project.confirmed_requirements

        # Extract network_mode and language from project metadata
        metadata = project.project_metadata or {}
        network_mode = metadata.get("network_mode", False)
        if options is not None and options.network_mode is not None:
            network_mode = options.network_mode
        language = metadata.get("language", "zh")
        custom_requirements = options.custom_requirements.strip() if options else ""
        requirements = confirmed_requirements.get("requirements") or project.requirements
        if custom_requirements:
            requirements = "\n\n".join(filter(None, (requirements, custom_requirements)))

        project_request = PPTGenerationRequest(
            scenario=project.scenario,
            topic=confirmed_requirements.get('topic', project.topic),
            requirements=with_package_reference(requirements, confirmed_requirements),
            language=language,
            network_mode=network_mode,
            target_audience=confirmed_requirements.get('target_audience', '普通大众'),
            custom_audience=confirmed_requirements.get('custom_audience'),
            ppt_style=confirmed_requirements.get('ppt_style', 'general'),
            custom_style_prompt=confirmed_requirements.get('custom_style_prompt'),
            include_transition_pages=bool(confirmed_requirements.get('include_transition_pages', False)),
            description=confirmed_requirements.get('description')
        )

        # Extract page count settings from confirmed requirements
        page_count_settings = confirmed_requirements.get('page_count_settings', {})

        # Generate outline using AI with page count settings
        if options is not None and source_type in {"file", "url", "mixed"}:
            generation_project = project.model_copy(
                update={"project_metadata": {**metadata, "network_mode": network_mode}}
            )
            outline_dict = await _collect_source_outline(
                generation_project, confirmed_requirements, user.id, requirements
            )
            outline_llm_call_count = max(0, int(outline_dict["metadata"]["llm_call_count"]))
        else:
            outline = await user_ppt_service.generate_outline(project_request, page_count_settings)
            outline_dict = {"title": outline.title, "slides": outline.slides, "metadata": outline.metadata}
            await user_ppt_service._update_outline_generation_stage(project_id, outline_dict)
            outline_llm_call_count = _resolve_outline_llm_call_count(outline, default=1)

        # Format as JSON
        formatted_json = json.dumps(outline_dict, ensure_ascii=False, indent=2)

        # Bill by actual LLM call count, matching the streaming route. A flat 1 here
        # meant the same file-based outline cost 4 credits via SSE but 1 via this
        # endpoint.
        if outline_llm_call_count > 0:
            await consume_credits_for_operation(
                user.id, "outline_generation", outline_llm_call_count,
                description=f"大纲生成: {project.topic}",
                reference_id=project_id,
                provider_name=outline_provider_name,
            )

        return {
            "status": "success",
            "network_mode": network_mode,
            "outline_content": formatted_json,
            "message": "Outline generated successfully"
        }


    except Exception as e:
        logger.error(f"Error generating outline: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.post("/projects/{project_id}/regenerate-outline")
async def regenerate_outline(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Regenerate outline for a project (overwrites existing outline) with optional custom requirements"""
    try:
        # Get request body to extract custom requirements if provided
        request_data = {}
        try:
            request_data = await request.json()
        except:
            pass  # If no body or invalid JSON, use empty dict
        
        custom_requirements = request_data.get('custom_requirements', '')
        
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check if project has confirmed requirements
        if not project.confirmed_requirements:
            return {
                "status": "error",
                "error": "项目需求尚未确认，请先完成需求确认步骤"
            }

        # Create project request from confirmed requirements
        confirmed_requirements = project.confirmed_requirements
        
        # Extract language from project metadata (set during project creation)
        language = "zh"  # Default language
        if project.project_metadata and isinstance(project.project_metadata, dict):
            language = project.project_metadata.get("language", "zh")
        
        # 如果提供了自定义需求，将其追加或覆盖原有需求
        final_requirements = confirmed_requirements.get('requirements', project.requirements)
        if custom_requirements:
            # 将自定义需求追加到原有需求
            if final_requirements:
                final_requirements = f"{final_requirements}\n\n【本次重新生成的额外要求】\n{custom_requirements}"
            else:
                final_requirements = custom_requirements
        
        # Extract network_mode from project metadata (set during project creation)
        network_mode = False
        if project.project_metadata and isinstance(project.project_metadata, dict):
            network_mode = project.project_metadata.get("network_mode", False)
        
        project_request = PPTGenerationRequest(
            scenario=confirmed_requirements.get('scenario', project.scenario),
            topic=confirmed_requirements.get('topic', project.topic),
            requirements=with_package_reference(final_requirements, confirmed_requirements),
            language=language,
            network_mode=network_mode,
            target_audience=confirmed_requirements.get('target_audience', '普通大众'),
            custom_audience=confirmed_requirements.get('custom_audience'),
            ppt_style=confirmed_requirements.get('ppt_style', 'general'),
            custom_style_prompt=confirmed_requirements.get('custom_style_prompt'),
            include_transition_pages=bool(confirmed_requirements.get('include_transition_pages', False)),
            description=confirmed_requirements.get('description')
        )


        # Extract page count settings from confirmed requirements
        page_count_settings = confirmed_requirements.get('page_count_settings', {})

        # Check if this is a file-like project (uploaded files or URL-extracted content)
        is_file_project = confirmed_requirements.get('content_source') in ('file', 'url', 'mixed')

        user_ppt_service_for_credits = get_ppt_service_for_user(user.id)
        _, outline_settings = await user_ppt_service_for_credits.get_role_provider_async("outline")
        outline_provider_name = outline_settings.get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user.id, "outline_generation", 1, provider_name=outline_provider_name
        )
        if not has_credits:
            return {
                "status": "error",
                "error": f"积分不足，大纲生成需要 {required} 积分，当前余额 {balance} 积分"
            }

        if is_file_project:
            from ...services.db_project_manager import DatabaseProjectManager

            updated_requirements = dict(confirmed_requirements or {})
            updated_requirements["requirements"] = final_requirements
            updated_requirements["file_generated_outline"] = None
            updated_requirements["force_file_outline_regeneration"] = True

            db_manager = DatabaseProjectManager()
            await db_manager.save_confirmed_requirements(project_id, updated_requirements, user_id=user.id)

            return {
                "status": "success",
                "defer_generation": True,
                "message": "Outline regeneration scheduled"
            }

        else:
            from ...services.db_project_manager import DatabaseProjectManager

            updated_requirements = dict(confirmed_requirements or {})
            updated_requirements["requirements"] = final_requirements

            db_manager = DatabaseProjectManager()
            await db_manager.save_confirmed_requirements(project_id, updated_requirements, user_id=user.id)
            await db_manager.update_project(
                project_id,
                {
                    "requirements": final_requirements,
                    "updated_at": time.time(),
                },
                user_id=user.id,
            )

            return {
                "status": "success",
                "defer_generation": True,
                "message": "Outline regeneration scheduled"
            }

    except Exception as e:
        logger.error(f"Error regenerating outline: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.post("/projects/{project_id}/generate-file-outline")
async def generate_file_outline(
    project_id: str,
    user: User = Depends(get_current_user_required)
):
    """Generate outline from uploaded file (non-streaming)"""
    try:
        project = await ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        confirmed_requirements = project.confirmed_requirements or {}
        user_ppt_service = get_ppt_service_for_user(user.id)
        _, outline_settings = await user_ppt_service.get_role_provider_async("outline")
        outline_provider_name = outline_settings.get("provider")

        # Check if project has file-generated outline
        from ...services.file_outline_utils import (
            extract_saved_file_outline,
            should_force_file_outline_regeneration,
        )

        force_file_outline_regeneration = should_force_file_outline_regeneration(
            confirmed_requirements
        )
        if force_file_outline_regeneration:
            logger.info(
                "Project %s requested file outline regeneration, skipping saved outline cache",
                project_id,
            )

        file_generated_outline = extract_saved_file_outline(
            project.outline,
            confirmed_requirements,
            ignore_saved_outline=force_file_outline_regeneration,
        )

        # 首先检查项目的outline字段
        if project.outline and project.outline.get('slides'):
            # 检查是否是从文件生成的大纲
            metadata = project.outline.get('metadata', {})
            if metadata.get('generated_with_summeryfile') or metadata.get('generated_with_file'):
                file_generated_outline = project.outline

        # 如果项目outline中没有，再检查confirmed_requirements
        if not file_generated_outline and confirmed_requirements and confirmed_requirements.get('file_generated_outline'):
            file_generated_outline = confirmed_requirements['file_generated_outline']

        file_generated_outline = extract_saved_file_outline(
            project.outline,
            confirmed_requirements,
            ignore_saved_outline=force_file_outline_regeneration,
        )
        if file_generated_outline:
            logger.info(
                "Project %s has reusable file-generated outline, using existing outline",
                project_id,
            )

        if file_generated_outline:
            # Return the existing file-generated outline
            import json
            existing_outline = {
                "title": file_generated_outline.get('title', project.topic),
                "slides": file_generated_outline.get('slides', []),
                "metadata": file_generated_outline.get('metadata', {})
            }

            # Ensure metadata includes correct identification
            if 'metadata' not in existing_outline:
                existing_outline['metadata'] = {}
            existing_outline['metadata']['generated_with_summeryfile'] = True
            existing_outline['metadata']['generated_at'] = time.time()

            formatted_json = json.dumps(existing_outline, ensure_ascii=False, indent=2)

            # Update outline generation stage
            await ppt_service._update_outline_generation_stage(project_id, existing_outline)

            return {
                "status": "success",
                "outline_content": formatted_json,
                "message": "File outline generated successfully"
            }
        elif confirmed_requirements.get("content_source") == "mixed":
            # All sources must use the common stream; the legacy single-file
            # fallback below would otherwise silently omit the web content.
            return {"status": "success", "defer_generation": True, "message": "请通过大纲生成工作区合并文件与网页资料。"}
        else:
            # Check if there's an uploaded file that needs processing
            if (confirmed_requirements and
                (confirmed_requirements.get('uploaded_files') or
                 confirmed_requirements.get('content_source') in ('file', 'url'))):
                logger.info(f"Project {project_id} starting file outline generation")

                # Start file outline generation using summeryfile
                try:
                    # Create a request object for file outline generation
                    from ...api.models import FileOutlineGenerationRequest
                    from pathlib import Path

                    # Get file information from confirmed requirements
                    uploaded_files = confirmed_requirements.get('uploaded_files', [])
                    file_processing_mode = confirmed_requirements.get('file_processing_mode', 'markitdown')
                    content_analysis_depth = confirmed_requirements.get('content_analysis_depth', 'standard')

                    logger.info(
                        f"File outline generation params: mode={file_processing_mode}, depth={content_analysis_depth}, uploaded_files={len(uploaded_files)}"
                    )

                    if not uploaded_files:
                        logger.warning(
                            f"Project {project_id} content_source is file/url but no uploaded_files metadata found in confirmed_requirements"
                        )
                        return {
                            "status": "error",
                            "error": "未找到已上传文件信息（uploaded_files）。该项目可能是在文件解析失败时保存的，请重新上传并确认需求后再试。"
                        }
                    if uploaded_files:
                        file_info = uploaded_files[0]  # Use first file
                        file_path = file_info.get('file_path', '')
                        if not file_path:
                            logger.warning(f"Project {project_id} uploaded_files entry missing file_path: {file_info}")
                            return {
                                "status": "error",
                                "error": "已上传文件信息缺少 file_path，无法生成大纲。请重新上传文件后再试。"
                            }

                        try:
                            if not Path(file_path).exists():
                                logger.error(f"Uploaded file path does not exist: {file_path}")
                                return {
                                    "status": "error",
                                    "error": f"文件不存在或已被清理：{file_path}。请重新上传文件后再试。"
                                }
                        except Exception:
                            pass
                        # 使用确认的要求或项目创建时的要求作为fallback
                        confirmed_reqs = confirmed_requirements.get('requirements', '')
                        project_reqs = project.requirements or ''
                        final_reqs = confirmed_reqs or project_reqs

                        # Extract language from project metadata (set during project creation)
                        language = "zh"
                        if project.project_metadata and isinstance(project.project_metadata, dict):
                            language = project.project_metadata.get("language", "zh")

                        file_request = FileOutlineGenerationRequest(
                            filename=file_info.get('filename', 'uploaded_file'),
                            file_path=file_path,
                            topic=project.topic,
                            scenario='general',
                            requirements=with_package_reference(final_reqs, confirmed_requirements),
                            target_audience=confirmed_requirements.get('target_audience', '普通大众'),
                            custom_audience=confirmed_requirements.get('custom_audience'),
                            description=confirmed_requirements.get('description'),
                            language=language,
                            page_count_mode=confirmed_requirements.get('page_count_settings', {}).get('mode', 'ai_decide'),
                            min_pages=confirmed_requirements.get('page_count_settings', {}).get('min_pages', 8),
                            max_pages=confirmed_requirements.get('page_count_settings', {}).get('max_pages', 15),
                            fixed_pages=confirmed_requirements.get('page_count_settings', {}).get('fixed_pages', 10),
                            ppt_style=confirmed_requirements.get('ppt_style', 'general'),
                            custom_style_prompt=confirmed_requirements.get('custom_style_prompt'),
                            include_transition_pages=bool(confirmed_requirements.get('include_transition_pages', False)),
                            file_processing_mode=file_processing_mode,
                            content_analysis_depth=content_analysis_depth
                        )

                        has_credits, required, balance = await check_credits_for_operation(
                            user.id, "outline_generation", 1, provider_name=outline_provider_name
                        )
                        if not has_credits:
                            return {
                                "status": "error",
                                "error": f"积分不足，大纲生成需要 {required} 积分，当前余额 {balance} 积分"
                            }

                        # Generate outline from file using summeryfile
                        logger.info(
                            f"Calling generate_outline_from_file: filename={file_request.filename}, path={file_request.file_path}, mode={file_request.file_processing_mode}"
                        )
                        outline_response = await user_ppt_service.generate_outline_from_file(file_request)

                        if outline_response.success and outline_response.outline:
                            # Format the generated outline
                            import json
                            formatted_outline = outline_response.outline

                            # Ensure metadata includes correct identification
                            if 'metadata' not in formatted_outline:
                                formatted_outline['metadata'] = {}
                            formatted_outline['metadata']['generated_with_summeryfile'] = True
                            formatted_outline['metadata']['generated_at'] = time.time()

                            formatted_json = json.dumps(formatted_outline, ensure_ascii=False, indent=2)

                            llm_call_count = _resolve_outline_llm_call_count(outline_response, default=1)
                            if llm_call_count > 0:
                                has_credits_exact, required_exact, balance_exact = await check_credits_for_operation(
                                    user.id, "outline_generation", llm_call_count, provider_name=outline_provider_name
                                )
                                if not has_credits_exact:
                                    return {
                                        "status": "error",
                                        "error": f"积分不足，大纲生成需要 {required_exact} 积分，当前余额 {balance_exact} 积分"
                                    }

                                billed, bill_message = await consume_credits_for_operation(
                                    user.id,
                                    "outline_generation",
                                    llm_call_count,
                                    description=f"文件大纲生成: {project.topic}",
                                    reference_id=project_id,
                                    provider_name=outline_provider_name,
                                )
                                if not billed:
                                    return {
                                        "status": "error",
                                        "error": bill_message or "积分扣费失败"
                                    }

                            # Update outline generation stage
                            await user_ppt_service._update_outline_generation_stage(project_id, formatted_outline)

                            return {
                                "status": "success",
                                "outline_content": formatted_json,
                                "message": "File outline generated successfully"
                            }
                        else:
                            error_msg = outline_response.error if hasattr(outline_response, 'error') else "Unknown error"
                            return {
                                "status": "error",
                                "error": f"Failed to generate outline from uploaded file: {error_msg}"
                            }
                    else:
                        return {
                            "status": "error",
                            "error": "No uploaded file information found in project requirements."
                        }

                except Exception as gen_error:
                    logger.error(f"Error generating outline from file: {gen_error}")
                    return {
                        "status": "error",
                        "error": f"Failed to generate outline from file: {str(gen_error)}"
                    }
            else:
                # No file outline found and no uploaded files
                return {
                    "status": "error",
                    "error": "No file outline found. Please ensure you uploaded a file during requirements confirmation."
                }

    except Exception as e:
        logger.error(f"Error generating file outline: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.post("/projects/{project_id}/update-outline")
async def update_project_outline(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Update project outline content"""
    try:
        data = await request.json()
        outline_content = data.get('outline_content', '')
        operation = data.get('operation')
        try:
            json.loads(outline_content)
        except (TypeError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid outline JSON")

        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if operation:
            operation_success = await user_ppt_service.project_manager.apply_slide_structure_operation(
                project_id,
                operation,
                user_id=user.id,
            )
            if not operation_success:
                raise HTTPException(status_code=400, detail="Failed to apply slide structure operation")

        success = await user_ppt_service.update_project_outline(project_id, outline_content)
        if success:
            return {"status": "success", "message": "Outline updated"}
        else:
            raise HTTPException(status_code=500, detail="Failed to update outline")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/confirm-outline")
async def confirm_project_outline(
    project_id: str,
    user: User = Depends(get_current_user_required)
):
    """Confirm project outline and enable PPT generation"""
    try:
        success = await ppt_service.confirm_project_outline(project_id)
        if success:
            return {"status": "success", "message": "Outline confirmed"}
        else:
            raise HTTPException(status_code=500, detail="Failed to confirm outline")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
