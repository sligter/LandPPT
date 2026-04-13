"""
Outline workflow orchestration extracted from EnhancedPPTService.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ...api.models import FileOutlineGenerationResponse
from ...utils.thread_pool import run_blocking_io
from .outline_workflow_support import (
    build_file_info,
    build_processing_stats,
    build_validation_requirements,
    create_outline_from_file_content,
    get_chunk_size_from_request,
    get_chunk_strategy_from_request,
    get_slides_range_from_request,
)

logger = logging.getLogger(__name__)


class OutlineWorkflowService:
    """Owns file-based outline generation workflows for EnhancedPPTService."""

    def __init__(self, service: Any):
        self._service = service

    async def _create_outline_generator(self, request: Any):
        from summeryanyfile.core.models import ProcessingConfig
        from summeryanyfile.generators.ppt_generator import PPTOutlineGenerator

        svc = self._service
        current_ai_config = await svc._get_current_ai_config_async("outline")
        min_slides, max_slides = get_slides_range_from_request(request)
        chunk_strategy = get_chunk_strategy_from_request(request)
        chunk_size = get_chunk_size_from_request(request)

        logger.info(
            "Preparing file-outline generator: provider=%s model=%s chunk_strategy=%s chunk_size=%s",
            current_ai_config["llm_provider"],
            current_ai_config["llm_model"],
            chunk_strategy,
            chunk_size,
        )

        execution_context = svc._build_execution_context("outline", current_ai_config)
        config = svc._build_summeryanyfile_processing_config(
            processing_config_cls=ProcessingConfig,
            execution_context=execution_context,
            target_language=request.language,
            min_slides=min_slides,
            max_slides=max_slides,
            chunk_size=chunk_size,
            chunk_strategy=chunk_strategy,
        )

        use_magic_pdf = request.file_processing_mode == "magic_pdf"
        mineru_config = await svc._get_current_mineru_config_async()
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        cache_dir = project_root / "temp" / "summeryanyfile_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        generator = PPTOutlineGenerator(
            config,
            use_magic_pdf=use_magic_pdf,
            cache_dir=str(cache_dir),
            mineru_api_key=mineru_config.get("api_key"),
            mineru_base_url=mineru_config.get("base_url"),
        )

        return generator, cache_dir

    async def generate_outline_from_file_streaming(self, request: Any):
        svc = self._service
        try:
            logger.info("Streaming file outline generation for %s", request.filename)
            try:
                generator, cache_dir = await self._create_outline_generator(request)
                try:
                    shutil.copy(request.file_path, cache_dir)
                except Exception:
                    pass

                async for event in generator.stream_generate_from_file(
                    request.file_path,
                    project_topic=request.topic or "",
                    project_scenario=request.scenario or "general",
                    project_requirements=getattr(request, "requirements", "") or "",
                    target_audience=getattr(request, "target_audience", "General audience"),
                    custom_audience="",
                    ppt_style=getattr(request, "ppt_style", "general"),
                    custom_style_prompt=getattr(request, "custom_style_prompt", ""),
                    page_count_mode=getattr(request, "page_count_mode", "ai_decide"),
                    min_pages=getattr(request, "min_pages", None),
                    max_pages=getattr(request, "max_pages", None),
                    fixed_pages=getattr(request, "fixed_pages", None),
                ):
                    outline_obj = event.get("outline_obj")
                    if not outline_obj:
                        yield event
                        continue

                    llm_call_count = int(
                        event.get("llm_call_count")
                        or svc._extract_summeryanyfile_llm_call_count(generator)
                        or 0
                    )
                    yield {
                        "status": {
                            "step": "validating",
                            "message": "Validating generated outline...",
                            "progress": 0.94,
                        }
                    }

                    outline = svc._standardize_summeryfile_outline(outline_obj.to_dict())
                    outline = await svc._validate_and_repair_outline_json(
                        outline,
                        build_validation_requirements(
                            request,
                            outline.get("title", "Document Presentation"),
                        ),
                    )
                    yield {
                        "outline": outline,
                        "llm_call_count": max(llm_call_count, 0),
                    }
                    return
            except ImportError as exc:
                logger.warning(
                    "summeryanyfile unavailable for streaming file outline generation: %s",
                    exc,
                )
            except Exception as exc:
                logger.error("summeryanyfile streaming file outline generation failed: %s", exc)

            fallback_result = await self._generate_outline_from_file_fallback(request)
            if not fallback_result.success or not fallback_result.outline:
                raise ValueError(fallback_result.error or "File outline generation failed")

            yield {"content_reset": True, "content_header": "Preparing outline..."}
            formatted_outline = json.dumps(fallback_result.outline, ensure_ascii=False, indent=2)
            for index, char in enumerate(formatted_outline):
                yield {"content": char}
                if index % 40 == 0:
                    await asyncio.sleep(0)

            llm_call_count = int(
                (fallback_result.processing_stats or {}).get("llm_call_count", 0) or 0
            )
            yield {
                "status": {
                    "step": "validating",
                    "message": "Outline generation completed.",
                    "progress": 0.94,
                }
            }
            yield {
                "outline": fallback_result.outline,
                "llm_call_count": max(llm_call_count, 0),
            }
        except Exception as exc:
            logger.error("Streaming outline generation from file failed: %s", exc)
            yield {"error": str(exc)}

    async def generate_outline_from_file(
        self, request: Any
    ) -> FileOutlineGenerationResponse:
        svc = self._service
        try:
            logger.info("Generating file outline for %s", request.filename)
            try:
                generator, cache_dir = await self._create_outline_generator(request)
                try:
                    shutil.copy(request.file_path, cache_dir)
                except Exception:
                    pass

                outline_obj = await generator.generate_from_file(
                    request.file_path,
                    project_topic=request.topic or "",
                    project_scenario=request.scenario or "general",
                    project_requirements=getattr(request, "requirements", "") or "",
                    target_audience=getattr(request, "target_audience", "General audience"),
                    custom_audience="",
                    ppt_style=getattr(request, "ppt_style", "general"),
                    custom_style_prompt=getattr(request, "custom_style_prompt", ""),
                    page_count_mode=getattr(request, "page_count_mode", "ai_decide"),
                    min_pages=getattr(request, "min_pages", None),
                    max_pages=getattr(request, "max_pages", None),
                    fixed_pages=getattr(request, "fixed_pages", None),
                )

                outline = svc._standardize_summeryfile_outline(outline_obj.to_dict())
                outline = await svc._validate_and_repair_outline_json(
                    outline,
                    build_validation_requirements(
                        request,
                        outline.get("title", "Document Presentation"),
                    ),
                )
                slides_count = len(outline.get("slides", []))
                llm_call_count = svc._extract_summeryanyfile_llm_call_count(generator)

                return FileOutlineGenerationResponse(
                    success=True,
                    outline=outline,
                    file_info=build_file_info(request, used_summeryanyfile=True),
                    processing_stats=build_processing_stats(
                        request,
                        slides_count=slides_count,
                        total_pages=getattr(outline_obj, "total_pages", slides_count),
                        generator_name="summeryanyfile",
                        llm_call_count=llm_call_count,
                    ),
                    message=f"Generated outline from {request.filename} with {slides_count} slides.",
                )
            except ImportError as exc:
                logger.warning("summeryanyfile unavailable, using fallback generator: %s", exc)
                return await self._generate_outline_from_file_fallback(request)
            except Exception as exc:
                logger.error("summeryanyfile outline generation failed, using fallback: %s", exc)
                return await self._generate_outline_from_file_fallback(request)
        except Exception as exc:
            logger.error("Outline generation from file failed: %s", exc)
            return FileOutlineGenerationResponse(
                success=False,
                error=str(exc),
                message=f"Outline generation from file failed: {exc}",
            )

    async def _generate_outline_from_file_fallback(
        self, request: Any
    ) -> FileOutlineGenerationResponse:
        svc = self._service
        logger.info("Using fallback file-outline generation for %s", request.filename)
        content = await run_blocking_io(svc._read_file_with_fallback_encoding, request.file_path)
        outline = create_outline_from_file_content(content, request)
        outline = await svc._validate_and_repair_outline_json(
            outline,
            build_validation_requirements(
                request,
                outline.get("title", "Document Presentation"),
            ),
        )
        slides_count = len(outline.get("slides", []))
        return FileOutlineGenerationResponse(
            success=True,
            outline=outline,
            file_info=build_file_info(request, used_summeryanyfile=False),
            processing_stats=build_processing_stats(
                request,
                slides_count=slides_count,
                total_pages=slides_count,
                generator_name="fallback",
                llm_call_count=0,
            ),
            message=f"Generated fallback outline from {request.filename}.",
        )
