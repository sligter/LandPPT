"""
Support helpers for outline and file-outline route modules.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ...api.models import FileOutlineGenerationRequest, PPTProject
from ...services.db_project_manager import DatabaseProjectManager
from ...utils.thread_pool import run_blocking_io
from .support import (
    check_credits_for_operation,
    consume_credits_for_operation,
    get_ppt_service_for_user,
    logger,
    ppt_service,
    templates,
)

def _is_billable_provider(provider_name: str | None) -> bool:
    return (provider_name or "").strip().lower() == "landppt"


def _resolve_outline_llm_call_count(result: Any, default: int = 1) -> int:
    """Extract outline LLM call count from response payloads/models."""
    # Preferred source: explicit processing stats from file-outline response.
    try:
        processing_stats = getattr(result, "processing_stats", None)
        if isinstance(processing_stats, dict) and "llm_call_count" in processing_stats:
            return max(0, int(processing_stats.get("llm_call_count") or 0))
    except Exception:
        pass

    # Secondary source: outline metadata if available.
    try:
        outline = getattr(result, "outline", None)
        if isinstance(outline, dict):
            metadata = outline.get("metadata", {})
            if isinstance(metadata, dict) and "llm_call_count" in metadata:
                return max(0, int(metadata.get("llm_call_count") or 0))
    except Exception:
        pass

    return max(0, int(default))


def _extract_saved_file_outline(project: PPTProject, confirmed_requirements: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    from ...services.file_outline_utils import extract_saved_file_outline

    return extract_saved_file_outline(
        getattr(project, "outline", None),
        confirmed_requirements or {},
    )


def _get_project_language(project: PPTProject) -> str:
    if project.project_metadata and isinstance(project.project_metadata, dict):
        return project.project_metadata.get("language", "zh")
    return "zh"


def _get_project_network_mode(project: PPTProject) -> bool:
    if project.project_metadata and isinstance(project.project_metadata, dict):
        return bool(project.project_metadata.get("network_mode", False))
    return False


async def _save_uploaded_files_for_confirmed_requirements(file_uploads: List[UploadFile]) -> Dict[str, Any]:
    from ...services.file_processor import FileProcessor

    file_processor = FileProcessor()
    files = [f for f in (file_uploads or []) if f is not None]
    if not files:
        raise Exception("Please upload at least one file.")

    saved_files: List[Dict[str, str]] = []
    try:
        for file_upload in files:
            is_valid, message = file_processor.validate_file(file_upload.filename, file_upload.size)
            if not is_valid:
                raise Exception(f"{file_upload.filename}: {message}")

            content = await file_upload.read()
            if not content:
                raise Exception(f"{file_upload.filename}: file content is empty.")

            project_file_path = await run_blocking_io(
                _save_project_file_sync, content, file_upload.filename
            )
            saved_files.append({
                "filename": file_upload.filename,
                "file_path": project_file_path,
            })

        saved_metadata: Dict[str, Any] = {"uploaded_files": saved_files}
        if len(saved_files) == 1:
            saved_metadata["file_path"] = saved_files[0]["file_path"]
            saved_metadata["filename"] = saved_files[0]["filename"]
        return saved_metadata
    except Exception:
        for item in saved_files:
            file_path = item.get("file_path")
            if not file_path:
                continue
            try:
                await run_blocking_io(_cleanup_project_file_sync, file_path)
            except Exception:
                pass
        raise


async def _persist_generated_source_outline(
    project_id: str,
    confirmed_requirements: Dict[str, Any],
    outline: Dict[str, Any],
    *,
    user_id: int,
) -> Dict[str, Any]:
    from ...services.db_project_manager import DatabaseProjectManager

    updated_requirements = dict(confirmed_requirements or {})
    updated_requirements["file_generated_outline"] = outline
    updated_requirements["force_file_outline_regeneration"] = False

    file_info = outline.get("file_info")
    if isinstance(file_info, dict):
        for key in (
            "file_path",
            "filename",
            "uploaded_files",
            "merged_file_path",
            "merged_filename",
            "file_paths",
        ):
            value = file_info.get(key)
            if value:
                updated_requirements[key] = value

    try:
        db_manager = DatabaseProjectManager()
        await db_manager.save_confirmed_requirements(project_id, updated_requirements, user_id=user_id)
    except Exception as save_error:
        logger.warning(
            f"Failed to persist generated source outline metadata for project {project_id}: {save_error}"
        )

    return updated_requirements


async def _prepare_uploaded_source_outline_request(
    project: PPTProject,
    confirmed_requirements: Dict[str, Any],
    *,
    user_id: int,
    requirements_override: Optional[str] = None,
    event_callback=None,
) -> Dict[str, Any]:
    from ...services.file_outline_utils import get_file_processing_mode, normalize_uploaded_files
    from ...services.file_processor import FileProcessor

    topic = (confirmed_requirements.get("topic") or project.topic or "").strip()
    scenario = confirmed_requirements.get("scenario", project.scenario)
    target_audience = confirmed_requirements.get("target_audience", "普通观众")
    language = _get_project_language(project)
    network_mode = _get_project_network_mode(project)
    requirements_text = requirements_override
    if requirements_text is None:
        requirements_text = confirmed_requirements.get("requirements") or project.requirements or ""

    page_count_settings = confirmed_requirements.get("page_count_settings", {})
    page_count_mode = page_count_settings.get("mode", "ai_decide")
    min_pages = page_count_settings.get("min_pages", 8)
    max_pages = page_count_settings.get("max_pages", 15)
    fixed_pages = page_count_settings.get("fixed_pages", 10)
    ppt_style = confirmed_requirements.get("ppt_style", "general")
    custom_style_prompt = confirmed_requirements.get("custom_style_prompt")
    file_processing_mode = get_file_processing_mode(confirmed_requirements)
    content_analysis_depth = confirmed_requirements.get("content_analysis_depth", "standard")
    user_ppt_service = get_ppt_service_for_user(user_id)

    uploaded_files = normalize_uploaded_files(confirmed_requirements.get("uploaded_files"))
    file_entries = uploaded_files[:]
    primary_file_path = confirmed_requirements.get("file_path")
    primary_filename = confirmed_requirements.get("filename")

    if not file_entries and primary_file_path:
        file_entries = [{
            "file_path": str(primary_file_path),
            "filename": str(primary_filename or Path(str(primary_file_path)).name),
        }]

    if not file_entries:
        raise Exception("No uploaded file information found in project requirements.")

    for entry in file_entries:
        file_path = entry.get("file_path")
        if not file_path:
            raise Exception("Uploaded file metadata is missing file_path.")
        if not Path(file_path).exists():
            raise Exception(f"Uploaded file no longer exists: {file_path}")

    merged_file_path: Optional[str] = None
    filename_for_request = primary_filename or file_entries[0].get("filename") or "uploaded_file"

    if network_mode and topic:
        context = {
            "scenario": scenario,
            "target_audience": target_audience or "普通观众",
            "requirements": requirements_text or "",
            "ppt_style": ppt_style,
            "description": f"文件数量: {len(file_entries)}",
            "file_processing_mode": file_processing_mode,
        }
        merged_file_path = await user_ppt_service.conduct_research_and_merge_with_files(
            topic=topic,
            language=language,
            file_paths=[entry["file_path"] for entry in file_entries],
            context=context,
            event_callback=event_callback,
        )
        filename_for_request = f"merged_with_search_{len(file_entries)}_files.md"
        file_path_for_request = merged_file_path
    elif len(file_entries) == 1:
        file_path_for_request = file_entries[0]["file_path"]
        filename_for_request = file_entries[0].get("filename") or filename_for_request
    else:
        file_processor = FileProcessor()
        merged_parts: List[Dict[str, str]] = []
        for entry in file_entries:
            src_path = entry["file_path"]
            src_name = entry.get("filename") or Path(src_path).name
            processed = await file_processor.process_file(
                src_path,
                src_name,
                file_processing_mode=file_processing_mode,
            )
            merged_parts.append({
                "filename": src_name,
                "content": processed.processed_content,
            })

        if not merged_parts:
            raise Exception("No uploaded files were successfully processed.")

        merged_content = file_processor.merge_multiple_files_to_markdown(merged_parts)
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md", encoding="utf-8") as merged_file:
            merged_file.write(merged_content)
            merged_file_path = merged_file.name

        filename_for_request = f"merged_content_{len(merged_parts)}_files.md"
        file_path_for_request = merged_file_path

    file_request = FileOutlineGenerationRequest(
        file_path=file_path_for_request,
        filename=filename_for_request,
        topic=topic or None,
        scenario=scenario,
        requirements=requirements_text,
        target_audience=target_audience,
        language=language,
        page_count_mode=page_count_mode,
        min_pages=min_pages,
        max_pages=max_pages,
        fixed_pages=fixed_pages,
        ppt_style=ppt_style,
        custom_style_prompt=custom_style_prompt,
        file_processing_mode=file_processing_mode,
        content_analysis_depth=content_analysis_depth,
    )

    file_info = {
        "file_paths": [entry["file_path"] for entry in file_entries],
        "merged_file_path": merged_file_path or file_request.file_path,
        "merged_filename": filename_for_request,
        "filenames": [entry.get("filename") or Path(entry["file_path"]).name for entry in file_entries],
        "files_count": len(file_entries),
        "processing_mode": file_processing_mode,
        "analysis_depth": content_analysis_depth,
        "file_path": file_request.file_path,
        "filename": file_request.filename,
        "uploaded_files": file_entries,
    }

    return {
        "file_request": file_request,
        "file_info": file_info,
    }


async def _generate_outline_from_confirmed_sources(
    project: PPTProject,
    confirmed_requirements: Dict[str, Any],
    *,
    user_id: int,
    requirements_override: Optional[str] = None,
) -> Dict[str, Any]:
    from ...services.file_outline_utils import get_file_processing_mode, normalize_uploaded_files
    from ...services.file_processor import FileProcessor

    content_source = (confirmed_requirements or {}).get("content_source") or "file"
    topic = (confirmed_requirements.get("topic") or project.topic or "").strip()
    scenario = confirmed_requirements.get("scenario", project.scenario)
    target_audience = confirmed_requirements.get("target_audience", "普通观众")
    language = _get_project_language(project)
    network_mode = _get_project_network_mode(project)
    requirements_text = requirements_override
    if requirements_text is None:
        requirements_text = confirmed_requirements.get("requirements") or project.requirements or ""

    page_count_settings = confirmed_requirements.get("page_count_settings", {})
    page_count_mode = page_count_settings.get("mode", "ai_decide")
    min_pages = page_count_settings.get("min_pages", 8)
    max_pages = page_count_settings.get("max_pages", 15)
    fixed_pages = page_count_settings.get("fixed_pages", 10)
    ppt_style = confirmed_requirements.get("ppt_style", "general")
    custom_style_prompt = confirmed_requirements.get("custom_style_prompt")
    file_processing_mode = get_file_processing_mode(confirmed_requirements)
    content_analysis_depth = confirmed_requirements.get("content_analysis_depth", "standard")
    user_ppt_service = get_ppt_service_for_user(user_id)

    if content_source == "url":
        source_urls = confirmed_requirements.get("source_urls") or []
        if isinstance(source_urls, str):
            source_urls = _normalize_content_source_urls(source_urls)
        if not source_urls:
            raise Exception("Please provide at least one valid URL (http/https).")

        outline = await _process_url_sources_for_outline(
            source_urls=source_urls,
            topic=topic,
            target_audience=target_audience,
            page_count_mode=page_count_mode,
            min_pages=min_pages,
            max_pages=max_pages,
            fixed_pages=fixed_pages,
            ppt_style=ppt_style,
            custom_style_prompt=custom_style_prompt,
            file_processing_mode=file_processing_mode,
            content_analysis_depth=content_analysis_depth,
            requirements=requirements_text,
            scenario=scenario,
            language=language,
            user_id=user_id,
        )
        if not outline:
            raise Exception("Failed to extract usable content from the provided URLs.")
        return outline

    uploaded_files = normalize_uploaded_files(confirmed_requirements.get("uploaded_files"))
    file_entries = uploaded_files[:]
    primary_file_path = confirmed_requirements.get("file_path")
    primary_filename = confirmed_requirements.get("filename")

    if not file_entries and primary_file_path:
        file_entries = [{
            "file_path": str(primary_file_path),
            "filename": str(primary_filename or Path(str(primary_file_path)).name),
        }]

    if not file_entries:
        raise Exception("No uploaded file information found in project requirements.")

    for entry in file_entries:
        file_path = entry.get("file_path")
        if not file_path:
            raise Exception("Uploaded file metadata is missing file_path.")
        if not Path(file_path).exists():
            raise Exception(f"Uploaded file no longer exists: {file_path}")

    merged_file_path: Optional[str] = None
    filename_for_request = primary_filename or file_entries[0].get("filename") or "uploaded_file"

    if network_mode and topic:
        context = {
            "scenario": scenario,
            "target_audience": target_audience or "普通观众",
            "requirements": requirements_text or "",
            "ppt_style": ppt_style,
            "description": f"文件数量: {len(file_entries)}",
            "file_processing_mode": file_processing_mode,
        }
        merged_file_path = await user_ppt_service.conduct_research_and_merge_with_files(
            topic=topic,
            language=language,
            file_paths=[entry["file_path"] for entry in file_entries],
            context=context,
        )
        filename_for_request = f"merged_with_search_{len(file_entries)}_files.md"
        file_path_for_request = merged_file_path
    elif len(file_entries) == 1:
        file_path_for_request = file_entries[0]["file_path"]
        filename_for_request = file_entries[0].get("filename") or filename_for_request
    else:
        file_processor = FileProcessor()
        merged_parts: List[Dict[str, str]] = []
        for entry in file_entries:
            src_path = entry["file_path"]
            src_name = entry.get("filename") or Path(src_path).name
            processed = await file_processor.process_file(
                src_path,
                src_name,
                file_processing_mode=file_processing_mode,
            )
            merged_parts.append({
                "filename": src_name,
                "content": processed.processed_content,
            })

        if not merged_parts:
            raise Exception("No uploaded files were successfully processed.")

        merged_content = file_processor.merge_multiple_files_to_markdown(merged_parts)
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md", encoding="utf-8") as merged_file:
            merged_file.write(merged_content)
            merged_file_path = merged_file.name

        filename_for_request = f"merged_content_{len(merged_parts)}_files.md"
        file_path_for_request = merged_file_path

    file_request = FileOutlineGenerationRequest(
        file_path=file_path_for_request,
        filename=filename_for_request,
        topic=topic or None,
        scenario=scenario,
        requirements=requirements_text,
        target_audience=target_audience,
        language=language,
        page_count_mode=page_count_mode,
        min_pages=min_pages,
        max_pages=max_pages,
        fixed_pages=fixed_pages,
        ppt_style=ppt_style,
        custom_style_prompt=custom_style_prompt,
        file_processing_mode=file_processing_mode,
        content_analysis_depth=content_analysis_depth,
    )

    result = await user_ppt_service.generate_outline_from_file(file_request)
    if not result.success or not result.outline:
        raise Exception(result.error or "Failed to generate outline from uploaded files.")

    outline = result.outline.copy()
    metadata = outline.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        outline["metadata"] = metadata
    metadata["llm_call_count"] = _resolve_outline_llm_call_count(result, default=1)

    outline["file_info"] = {
        "file_paths": [entry["file_path"] for entry in file_entries],
        "merged_file_path": merged_file_path or file_request.file_path,
        "merged_filename": filename_for_request,
        "filenames": [entry.get("filename") or Path(entry["file_path"]).name for entry in file_entries],
        "files_count": len(file_entries),
        "processing_mode": file_processing_mode,
        "analysis_depth": content_analysis_depth,
        "file_path": file_request.file_path,
        "filename": file_request.filename,
        "uploaded_files": file_entries,
    }
    return outline


async def _stream_outline_from_confirmed_sources(
    project_id: str,
    project: PPTProject,
    confirmed_requirements: Dict[str, Any],
    *,
    user_id: int,
) -> Any:
    content_source = (confirmed_requirements or {}).get("content_source") or "file"
    status_message = (
        "正在抓取并分析 URL 内容..."
        if content_source == "url"
        else "正在处理上传文件并生成大纲..."
    )

    try:
        yield f"data: {json.dumps({'ping': True})}\n\n"
        yield (
            f"data: {json.dumps({'status': {'step': 'file_process', 'message': status_message, 'progress': 0.0}})}\n\n"
        )

        generation_task = asyncio.create_task(
            _generate_outline_from_confirmed_sources(
                project,
                confirmed_requirements,
                user_id=user_id,
            )
        )
        while not generation_task.done():
            done, _ = await asyncio.wait({generation_task}, timeout=5.0)
            if done:
                break
            yield f"data: {json.dumps({'ping': True})}\n\n"

        outline = await generation_task
        metadata = outline.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            outline["metadata"] = metadata
        metadata["generated_with_summeryfile"] = True
        metadata["generated_at"] = time.time()

        await _persist_generated_source_outline(
            project_id,
            confirmed_requirements,
            outline,
            user_id=user_id,
        )

        user_ppt_service = get_ppt_service_for_user(user_id)
        await user_ppt_service._update_outline_generation_stage(project_id, outline)

        llm_call_count = max(0, int((outline.get("metadata") or {}).get("llm_call_count") or 0))
        yield (
            f"data: {json.dumps({'status': {'step': 'validating', 'message': '大纲生成完成，正在保存结果...', 'progress': 1.0}})}\n\n"
        )
        yield f"data: {json.dumps({'outline': outline}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True, 'llm_call_count': llm_call_count})}\n\n"
    except Exception as e:
        logger.error(f"Error streaming source outline for project {project_id}: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

# AI编辑请求数据模型
async def _stream_outline_from_confirmed_sources_v2(
    project_id: str,
    project: PPTProject,
    confirmed_requirements: Dict[str, Any],
    *,
    user_id: int,
) -> Any:
    content_source = (confirmed_requirements or {}).get("content_source") or "file"
    status_message = (
        "正在抓取并分析 URL 内容..."
        if content_source == "url"
        else "正在处理上传文件并生成大纲..."
    )

    try:
        yield f"data: {json.dumps({'ping': True})}\n\n"
        yield (
            f"data: {json.dumps({'status': {'step': 'file_process', 'message': status_message, 'progress': 0.0}}, ensure_ascii=False)}\n\n"
        )

        user_ppt_service = get_ppt_service_for_user(user_id)
        outline: Optional[Dict[str, Any]] = None
        llm_call_count = 0

        if content_source == "file":
            research_event_queue: asyncio.Queue = asyncio.Queue()

            async def _research_event_cb(event: Dict[str, Any]) -> None:
                await research_event_queue.put(event)

            prepare_task = asyncio.create_task(
                _prepare_uploaded_source_outline_request(
                    project,
                    confirmed_requirements,
                    user_id=user_id,
                    event_callback=_research_event_cb,
                )
            )
            last_ping_at = time.time()

            while not prepare_task.done():
                done, _ = await asyncio.wait({prepare_task}, timeout=1.0)
                while not research_event_queue.empty():
                    research_event = research_event_queue.get_nowait()
                    for payload in user_ppt_service.iter_research_stream_payloads(research_event):
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if done:
                    break
                now = time.time()
                if now - last_ping_at >= 5:
                    yield f"data: {json.dumps({'ping': True})}\n\n"
                    last_ping_at = now

            prepared_request = await prepare_task
            while not research_event_queue.empty():
                research_event = research_event_queue.get_nowait()
                for payload in user_ppt_service.iter_research_stream_payloads(research_event):
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            file_request = prepared_request["file_request"]
            last_ping_at = time.time()

            async for event in user_ppt_service.generate_outline_from_file_streaming(file_request):
                if event.get("error"):
                    raise Exception(event["error"])

                if event.get("outline"):
                    outline = event["outline"]
                    try:
                        llm_call_count = max(0, int(event.get("llm_call_count") or 0))
                    except Exception:
                        llm_call_count = 0
                    break

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                now = time.time()
                if now - last_ping_at >= 5:
                    yield f"data: {json.dumps({'ping': True})}\n\n"
                    last_ping_at = now

            if not outline:
                raise Exception("Failed to generate outline from uploaded files.")

            outline = outline.copy()
            outline["file_info"] = prepared_request["file_info"]
        else:
            generation_task = asyncio.create_task(
                _generate_outline_from_confirmed_sources(
                    project,
                    confirmed_requirements,
                    user_id=user_id,
                )
            )
            while not generation_task.done():
                done, _ = await asyncio.wait({generation_task}, timeout=5.0)
                if done:
                    break
                yield f"data: {json.dumps({'ping': True})}\n\n"

            outline = await generation_task
            llm_call_count = max(0, int((outline.get("metadata") or {}).get("llm_call_count") or 0))

        metadata = outline.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            outline["metadata"] = metadata
        metadata["generated_with_summeryfile"] = True
        metadata["generated_at"] = time.time()
        metadata["llm_call_count"] = llm_call_count

        await _persist_generated_source_outline(
            project_id,
            confirmed_requirements,
            outline,
            user_id=user_id,
        )
        await user_ppt_service._update_outline_generation_stage(project_id, outline)

        yield (
            f"data: {json.dumps({'status': {'step': 'validating', 'message': '大纲生成完成，正在保存结果...', 'progress': 1.0}}, ensure_ascii=False)}\n\n"
        )
        yield f"data: {json.dumps({'outline': outline}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True, 'llm_call_count': llm_call_count})}\n\n"
    except Exception as e:
        logger.error(f"Error streaming source outline for project {project_id}: {e}")
        yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

def _normalize_content_source_urls(content_urls: Optional[str], max_urls: int = 50) -> List[str]:
    """Parse and normalize URL input from textarea/comma-separated content."""
    if not content_urls:
        return []

    candidates = re.split(r"[\n,;\t ]+", content_urls.strip())
    normalized: List[str] = []
    seen = set()

    for raw in candidates:
        value = (raw or "").strip()
        if not value:
            continue

        if not value.startswith(("http://", "https://")):
            value = f"https://{value}"

        try:
            parsed = urllib.parse.urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                continue
            clean_url = parsed.geturl()
        except Exception:
            continue

        if clean_url in seen:
            continue

        normalized.append(clean_url)
        seen.add(clean_url)
        if len(normalized) >= max_urls:
            break

    return normalized


_URL_SOURCE_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".jpg", ".jpeg", ".png"}
_URL_SOURCE_CONTENT_TYPE_TO_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
}


def _infer_extension_from_content_type(content_type: Optional[str]) -> Optional[str]:
    if not content_type:
        return None
    normalized = str(content_type).split(";", 1)[0].strip().lower()
    return _URL_SOURCE_CONTENT_TYPE_TO_EXT.get(normalized)


def _extract_filename_from_content_disposition(content_disposition: Optional[str]) -> Optional[str]:
    if not content_disposition:
        return None

    # RFC 5987: filename*=UTF-8''...
    filename_star_match = re.search(r"filename\*\s*=\s*([^;]+)", content_disposition, flags=re.IGNORECASE)
    if filename_star_match:
        raw_value = filename_star_match.group(1).strip().strip('"')
        if "''" in raw_value:
            raw_value = raw_value.split("''", 1)[1]
        decoded = urllib.parse.unquote(raw_value).strip()
        if decoded:
            return Path(decoded).name

    filename_match = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition, flags=re.IGNORECASE)
    if not filename_match:
        filename_match = re.search(r"filename\s*=\s*([^;]+)", content_disposition, flags=re.IGNORECASE)
    if filename_match:
        decoded = urllib.parse.unquote(filename_match.group(1).strip().strip('"')).strip()
        if decoded:
            return Path(decoded).name

    return None


def _is_supported_file_source_url(
    source_url: str,
    content_type: Optional[str] = None,
    content_disposition: Optional[str] = None,
) -> bool:
    parsed = urllib.parse.urlparse(source_url)
    path_lower = (parsed.path or "").lower()
    ext = Path(path_lower).suffix.lower()
    if ext in _URL_SOURCE_SUPPORTED_EXTENSIONS:
        return True

    # Common direct-PDF link pattern, e.g. https://arxiv.org/pdf/2602.23323
    if "/pdf/" in path_lower:
        return True

    disposition_name = _extract_filename_from_content_disposition(content_disposition)
    if disposition_name and Path(disposition_name).suffix.lower() in _URL_SOURCE_SUPPORTED_EXTENSIONS:
        return True

    return _infer_extension_from_content_type(content_type) in _URL_SOURCE_SUPPORTED_EXTENSIONS


def _build_download_filename_for_url(
    source_url: str,
    resolved_url: str,
    content_type: Optional[str],
    content_disposition: Optional[str],
    index: int,
) -> Optional[str]:
    disposition_name = _extract_filename_from_content_disposition(content_disposition)
    parsed_resolved = urllib.parse.urlparse(resolved_url or source_url)
    url_name = urllib.parse.unquote(Path(parsed_resolved.path or "").name)
    base_name = (disposition_name or url_name or f"url_source_{index}").strip()

    current_ext = Path(base_name).suffix.lower()
    target_ext = current_ext if current_ext in _URL_SOURCE_SUPPORTED_EXTENSIONS else None
    if not target_ext:
        target_ext = _infer_extension_from_content_type(content_type)

    # Fallback for /pdf/ style links with numeric suffixes.
    if not target_ext and "/pdf/" in (parsed_resolved.path or "").lower():
        target_ext = ".pdf"

    if not target_ext or target_ext not in _URL_SOURCE_SUPPORTED_EXTENSIONS:
        return None

    if current_ext not in _URL_SOURCE_SUPPORTED_EXTENSIONS:
        if not base_name.lower().endswith(target_ext):
            base_name = f"{base_name}{target_ext}"

    sanitized = re.sub(r'[\\/:*?"<>|]+', "_", base_name).strip(" .")
    return sanitized or f"url_source_{index}{target_ext}"


async def _url_likely_points_to_file(session: aiohttp.ClientSession, source_url: str) -> bool:
    if _is_supported_file_source_url(source_url):
        return True

    try:
        async with session.head(source_url, allow_redirects=True) as response:
            if response.status >= 400:
                return False
            return _is_supported_file_source_url(
                str(response.url),
                content_type=response.headers.get("content-type"),
                content_disposition=response.headers.get("content-disposition"),
            )
    except Exception:
        return False


async def _download_supported_file_from_url(
    session: aiohttp.ClientSession,
    source_url: str,
    index: int,
    max_size_bytes: int = 100 * 1024 * 1024,
) -> Optional[Dict[str, Any]]:
    try:
        async with session.get(source_url, allow_redirects=True) as response:
            if response.status != 200:
                logger.warning(f"Skip URL file download (HTTP {response.status}): {source_url}")
                return None

            resolved_url = str(response.url)
            content_type = response.headers.get("content-type", "")
            content_disposition = response.headers.get("content-disposition", "")

            if not _is_supported_file_source_url(
                resolved_url,
                content_type=content_type,
                content_disposition=content_disposition,
            ):
                return None

            filename = _build_download_filename_for_url(
                source_url=source_url,
                resolved_url=resolved_url,
                content_type=content_type,
                content_disposition=content_disposition,
                index=index,
            )
            if not filename:
                logger.warning(f"Cannot infer supported filename for URL: {source_url}")
                return None

            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > max_size_bytes:
                        logger.warning(f"Skip oversized URL file (>100MB): {source_url}")
                        return None
                except ValueError:
                    pass

            chunks = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                chunks.extend(chunk)
                if len(chunks) > max_size_bytes:
                    logger.warning(f"Skip oversized URL file while streaming (>100MB): {source_url}")
                    return None

            if not chunks:
                logger.warning(f"Skip empty URL file response: {source_url}")
                return None

            saved_path = await run_blocking_io(
                _save_project_file_sync,
                bytes(chunks),
                filename,
            )
            return {
                "source_url": source_url,
                "resolved_url": resolved_url,
                "filename": filename,
                "file_path": saved_path,
                "size": len(chunks),
                "content_type": content_type,
            }
    except Exception as e:
        logger.warning(f"Failed to download URL file source {source_url}: {e}")
        return None


async def _process_url_sources_for_outline(
    source_urls: List[str],
    topic: str,
    target_audience: str,
    page_count_mode: str,
    min_pages: int,
    max_pages: int,
    fixed_pages: int,
    ppt_style: str,
    custom_style_prompt: str,
    file_processing_mode: str,
    content_analysis_depth: str,
    requirements: str = None,
    scenario: str = "general",
    language: str = "zh",
    user_id: int = None,
) -> Optional[Dict[str, Any]]:
    """Process URL sources (web pages + downloadable files) and generate file-style outline."""
    if not source_urls:
        return None

    saved_file_path: Optional[str] = None
    source_filename = f"url_sources_{int(time.time())}.md"
    downloaded_file_paths: List[str] = []

    try:
        from ...services.research.content_extractor import WebContentExtractor
        from ...services.file_processor import FileProcessor

        extractor = WebContentExtractor()
        file_processor = FileProcessor()

        downloaded_sources: List[Dict[str, Any]] = []
        web_source_urls: List[str] = []

        timeout = aiohttp.ClientTimeout(total=60)
        headers = {
            "User-Agent": "LandPPT Research Bot 1.0",
            "Accept": "*/*",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for idx, source_url in enumerate(source_urls, start=1):
                likely_file_source = await _url_likely_points_to_file(session, source_url)
                if not likely_file_source:
                    web_source_urls.append(source_url)
                    continue

                downloaded = await _download_supported_file_from_url(
                    session=session,
                    source_url=source_url,
                    index=idx,
                    max_size_bytes=100 * 1024 * 1024,
                )
                if downloaded:
                    downloaded_sources.append(downloaded)
                    downloaded_file_paths.append(downloaded["file_path"])
                else:
                    # Fallback to web extraction when file download could not be confirmed/completed.
                    web_source_urls.append(source_url)

        processed_file_sources: List[Dict[str, Any]] = []
        for downloaded in downloaded_sources:
            file_ext = Path(downloaded["filename"]).suffix.lower()
            if file_ext == ".pdf":
                is_valid = downloaded["size"] <= 100 * 1024 * 1024
                message = "文件大小超过限制 (100MB)" if not is_valid else "文件验证通过"
            else:
                is_valid, message = file_processor.validate_file(
                    downloaded["filename"],
                    downloaded["size"],
                )
            if not is_valid:
                logger.warning(
                    f"Skip downloaded URL file {downloaded['filename']} from {downloaded['source_url']}: {message}"
                )
                try:
                    await run_blocking_io(_cleanup_project_file_sync, downloaded["file_path"])
                    downloaded_file_paths = [p for p in downloaded_file_paths if p != downloaded["file_path"]]
                except Exception:
                    pass
                continue

            try:
                if file_ext == ".pdf":
                    processed_content, used_processing_mode = await file_processor.process_downloaded_pdf_with_priority(
                        downloaded["file_path"]
                    )
                else:
                    file_result = await file_processor.process_file(
                        downloaded["file_path"],
                        downloaded["filename"],
                        file_processing_mode=file_processing_mode,
                    )
                    processed_content = file_result.processed_content
                    used_processing_mode = file_processing_mode

                processed_file_sources.append({
                    **downloaded,
                    "content": processed_content,
                    "processing_mode": used_processing_mode,
                })
            except Exception as e:
                logger.warning(
                    f"Failed to process downloaded URL file {downloaded['filename']} from {downloaded['source_url']}: {e}"
                )
                try:
                    await run_blocking_io(_cleanup_project_file_sync, downloaded["file_path"])
                    downloaded_file_paths = [p for p in downloaded_file_paths if p != downloaded["file_path"]]
                except Exception:
                    pass

        extracted_contents = []
        if web_source_urls:
            extracted_contents = await extractor.extract_multiple(
                web_source_urls,
                max_concurrent=3,
                delay_between_requests=0.1,
            )

        if not processed_file_sources and not extracted_contents:
            logger.error("No URL content or downloadable files were processed successfully")
            return None

        markdown_parts: List[str] = []
        markdown_parts.append("# URL Source Content\n")
        if topic and topic.strip():
            markdown_parts.append(f"\nTopic: {topic.strip()}\n")

        if processed_file_sources:
            markdown_parts.append("\n## Downloaded File Sources\n")
            for idx, item in enumerate(processed_file_sources, 1):
                markdown_parts.append(f"\n### File {idx}: {item['filename']}\n")
                markdown_parts.append(f"- Source URL: {item['source_url']}\n")
                markdown_parts.append(f"- File Size: {item['size']} bytes\n")
                if item.get("content_type"):
                    markdown_parts.append(f"- Content Type: {item['content_type']}\n")
                if item.get("processing_mode"):
                    markdown_parts.append(f"- Processing Mode: {item['processing_mode']}\n")
                markdown_parts.append("\n")
                markdown_parts.append((item.get("content") or "").strip())
                markdown_parts.append("\n")

        if extracted_contents:
            markdown_parts.append("\n## Web Page Sources\n")
            for idx, item in enumerate(extracted_contents, 1):
                title = (item.title or "").strip() or item.url
                markdown_parts.append(f"\n### Page {idx}: {title}\n")
                markdown_parts.append(f"- URL: {item.url}\n")
                markdown_parts.append(f"- Word Count: {item.word_count}\n\n")
                markdown_parts.append((item.content or "").strip())
                markdown_parts.append("\n")

        merged_content = "".join(markdown_parts).strip()
        if not merged_content:
            logger.error("Processed URL content is empty after merge")
            return None

        saved_file_path = await run_blocking_io(
            _save_project_file_sync,
            merged_content.encode("utf-8"),
            source_filename,
        )

        outline_request = FileOutlineGenerationRequest(
            file_path=saved_file_path,
            filename=source_filename,
            topic=topic if (topic or "").strip() else None,
            scenario=scenario,
            requirements=requirements,
            target_audience=target_audience,
            language=language,
            page_count_mode=page_count_mode,
            min_pages=min_pages,
            max_pages=max_pages,
            fixed_pages=fixed_pages,
            ppt_style=ppt_style,
            custom_style_prompt=custom_style_prompt,
            file_processing_mode=file_processing_mode,
            content_analysis_depth=content_analysis_depth,
        )

        user_ppt_service = get_ppt_service_for_user(user_id) if user_id else ppt_service
        result = await user_ppt_service.generate_outline_from_file(outline_request)
        if not result.success or not result.outline:
            logger.error(f"Failed to generate outline from URL content: {getattr(result, 'error', 'unknown')}")
            if saved_file_path:
                await run_blocking_io(_cleanup_project_file_sync, saved_file_path)
            for downloaded_path in downloaded_file_paths:
                try:
                    await run_blocking_io(_cleanup_project_file_sync, downloaded_path)
                except Exception:
                    pass
            return None

        uploaded_files = [
            {
                "filename": item["filename"],
                "file_path": item["file_path"],
                "source_url": item["source_url"],
            }
            for item in processed_file_sources
        ]
        if not uploaded_files:
            uploaded_files = [{"filename": source_filename, "file_path": saved_file_path}]

        succeeded_urls = {item["source_url"] for item in processed_file_sources}
        succeeded_urls.update(item.url for item in extracted_contents)

        outline_with_url_info = result.outline.copy()
        url_outline_llm_call_count = _resolve_outline_llm_call_count(result, default=1)
        metadata = outline_with_url_info.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            outline_with_url_info["metadata"] = metadata
        metadata["llm_call_count"] = max(0, int(url_outline_llm_call_count))
        outline_with_url_info["file_info"] = {
            "file_path": saved_file_path,
            "filename": source_filename,
            "uploaded_files": uploaded_files,
            "source_type": "url",
            "source_urls": source_urls,
            "sources_count": len(source_urls),
            "downloaded_files_count": len(processed_file_sources),
            "web_sources_count": len(web_source_urls),
            "web_extracted_count": len(extracted_contents),
            "extracted_count": len(extracted_contents) + len(processed_file_sources),
        }
        outline_with_url_info["url_info"] = {
            "source_urls": source_urls,
            "web_source_urls": web_source_urls,
            "downloaded_files": [
                {
                    "source_url": item["source_url"],
                    "resolved_url": item["resolved_url"],
                    "filename": item["filename"],
                    "size": item["size"],
                    "content_type": item.get("content_type"),
                    "processing_mode": item.get("processing_mode"),
                }
                for item in processed_file_sources
            ],
            "downloaded_files_count": len(processed_file_sources),
            "web_extracted_count": len(extracted_contents),
            "extracted_count": len(extracted_contents) + len(processed_file_sources),
            "failed_count": max(len(source_urls) - len(succeeded_urls), 0),
            "titles": [(item.title or item.url) for item in extracted_contents],
        }
        return outline_with_url_info

    except Exception as e:
        logger.error(f"Error processing URL sources for outline: {e}")
        if saved_file_path:
            try:
                await run_blocking_io(_cleanup_project_file_sync, saved_file_path)
            except Exception:
                pass
        for downloaded_path in downloaded_file_paths:
            try:
                await run_blocking_io(_cleanup_project_file_sync, downloaded_path)
            except Exception:
                pass
        return None


async def _process_uploaded_files_for_outline(
    file_uploads: List[UploadFile],
    topic: str,
    target_audience: str,
    page_count_mode: str,
    min_pages: int,
    max_pages: int,
    fixed_pages: int,
    ppt_style: str,
    custom_style_prompt: str,
    file_processing_mode: str,
    content_analysis_depth: str,
    requirements: str = None,
    enable_web_search: bool = False,  # 新增参数
    scenario: str = "general",  # 新增参数
    language: str = "zh",  # 新增参数
    user_id: int = None  # 新增参数：用户ID，用于获取用户特定的AI配置
) -> Optional[Dict[str, Any]]:
    """处理上传的多个文件并生成PPT大纲，支持联网搜索集成"""
    try:
        from ...services.file_processor import FileProcessor
        file_processor = FileProcessor()

        # 过滤掉None值（如果没有文件上传）
        files = [f for f in file_uploads if f is not None]
        if not files:
            logger.error("No files provided")
            return None

        saved_file_paths = []
        all_processed_content = []

        try:
            # 处理每个文件
            for file_upload in files:
                # 验证文件
                is_valid, message = file_processor.validate_file(file_upload.filename, file_upload.size)
                if not is_valid:
                    logger.error(f"File validation failed for {file_upload.filename}: {message}")
                    continue

                # 读取文件内容并保存到项目文件目录
                content = await file_upload.read()
                # logger.info(f"文件内容: {content}")
                project_file_path = await run_blocking_io(
                    _save_project_file_sync, content, file_upload.filename
                )
                saved_file_paths.append(project_file_path)

                # 处理单个文件内容
                file_result = await file_processor.process_file(
                    project_file_path,
                    file_upload.filename,
                    file_processing_mode=file_processing_mode,
                )
                all_processed_content.append({
                    "filename": file_upload.filename,
                    "content": file_result.processed_content
                })
                logger.debug(f"文件处理内容: {file_result.processed_content}")
            if not all_processed_content:
                logger.error("No files were successfully processed")
                return None

            # 决定是否使用联网搜索并整合
            merged_file_path = None
            merged_filename = None

            if enable_web_search and topic and topic.strip():
                # 使用联网搜索并整合本地文件
                logger.info(f"启用联网搜索模式，主题: {topic}")

                # 构建上下文信息
                context = {
                    'scenario': scenario,
                    'target_audience': target_audience or '普通大众',
                    'requirements': requirements or '',
                    'ppt_style': ppt_style,
                    'description': f'文件数量: {len(files)}',
                    'file_processing_mode': file_processing_mode,
                }

                # 进行联网搜索并与文件整合
                merged_file_path = await ppt_service.conduct_research_and_merge_with_files(
                    topic=topic,
                    language=language,
                    file_paths=saved_file_paths,
                    context=context
                )

                merged_filename = f"merged_with_search_{len(files)}_files.md"
                logger.info(f"✅ 联网搜索和文件整合完成: {merged_file_path}")
            else:
                # 不使用联网搜索，仅合并所有文件内容
                merged_content = file_processor.merge_multiple_files_to_markdown(all_processed_content)

                # 创建临时合并文件
                import tempfile
                import os
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md', encoding='utf-8') as merged_file:
                    merged_file.write(merged_content)
                    merged_file_path = merged_file.name

                merged_filename = f"merged_content_{len(files)}_files.md"

            saved_file_paths.append(merged_file_path)

            # 创建文件大纲生成请求
            from ...api.models import FileOutlineGenerationRequest
            filenames_str = ", ".join([f.filename for f in files])
            merged_filename = f"merged_content_{len(files)}_files.md"
            outline_request = FileOutlineGenerationRequest(
                file_path=merged_file_path,
                filename=merged_filename,
                topic=topic if topic.strip() else None,
                scenario=scenario,
                requirements=requirements,
                target_audience=target_audience,
                language=language,
                page_count_mode=page_count_mode,
                min_pages=min_pages,
                max_pages=max_pages,
                fixed_pages=fixed_pages,
                ppt_style=ppt_style,
                custom_style_prompt=custom_style_prompt,
                file_processing_mode=file_processing_mode,
                content_analysis_depth=content_analysis_depth
            )

            # 使用用户特定的ppt_service生成大纲，确保使用用户的AI配置
            user_ppt_service = get_ppt_service_for_user(user_id) if user_id else ppt_service
            result = await user_ppt_service.generate_outline_from_file(outline_request)

            if result.success:
                logger.info(f"Successfully generated outline from {len(files)} files: {filenames_str}")
                # 在大纲中添加文件信息，用于重新生成
                outline_with_file_info = result.outline.copy()
                file_outline_llm_call_count = _resolve_outline_llm_call_count(result, default=1)
                metadata = outline_with_file_info.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                    outline_with_file_info["metadata"] = metadata
                metadata["llm_call_count"] = max(0, int(file_outline_llm_call_count))
                original_filenames = [f.filename for f in files]
                file_paths_without_merge = saved_file_paths[:-1]  # 排除临时合并文件
                uploaded_files_info = [
                    {'filename': name, 'file_path': path}
                    for name, path in zip(original_filenames, file_paths_without_merge)
                ]
                outline_with_file_info['file_info'] = {
                    'file_paths': file_paths_without_merge,
                    'merged_file_path': merged_file_path,
                    'merged_filename': merged_filename,
                    'filenames': original_filenames,
                    'files_count': len(files),
                    'processing_mode': file_processing_mode,
                    'analysis_depth': content_analysis_depth,
                    'file_path': merged_file_path,
                    'filename': merged_filename,
                    'uploaded_files': uploaded_files_info
                }
                return outline_with_file_info
            else:
                logger.error(f"Failed to generate outline from files: {result.error}")
                # 如果生成失败，清理文件
                for file_path in saved_file_paths:
                    await run_blocking_io(_cleanup_project_file_sync, file_path)
                return None

        except Exception as e:
            # 清理所有已保存的文件
            for file_path in saved_file_paths:
                try:
                    await run_blocking_io(_cleanup_project_file_sync, file_path)
                except:
                    pass
            raise e

    except Exception as e:
        logger.error(f"Error processing uploaded files for outline: {e}")
        return None


async def _process_uploaded_file_for_outline(
    file_upload: UploadFile,
    topic: str,
    target_audience: str,
    page_count_mode: str,
    min_pages: int,
    max_pages: int,
    fixed_pages: int,
    ppt_style: str,
    custom_style_prompt: str,
    file_processing_mode: str,
    content_analysis_depth: str,
    requirements: str = None
) -> Optional[Dict[str, Any]]:
    """处理上传的单个文件并生成PPT大纲（向后兼容）"""
    return await _process_uploaded_files_for_outline(
        [file_upload], topic, target_audience, page_count_mode, min_pages, max_pages,
        fixed_pages, ppt_style, custom_style_prompt, file_processing_mode,
        content_analysis_depth, requirements
    )


def _save_temp_file_sync(content: bytes, filename: str) -> str:
    """同步保存临时文件（在线程池中运行）"""
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=os.path.splitext(filename)[1]
    ) as temp_file:
        temp_file.write(content)
        return temp_file.name


def _save_project_file_sync(content: bytes, filename: str) -> str:
    """同步保存项目文件到永久位置（在线程池中运行）"""
    import os
    import time
    from pathlib import Path

    # 创建项目文件目录
    project_files_dir = Path("temp/project_files")
    project_files_dir.mkdir(parents=True, exist_ok=True)

    # 生成唯一文件名
    timestamp = int(time.time())
    file_ext = os.path.splitext(filename)[1]
    safe_filename = f"{timestamp}_{filename}"
    file_path = project_files_dir / safe_filename

    # 保存文件
    with open(file_path, 'wb') as f:
        f.write(content)

    return str(file_path)


def _cleanup_temp_file_sync(temp_file_path: str):
    """同步清理临时文件（在线程池中运行）"""
    import os
    if os.path.exists(temp_file_path):
        os.unlink(temp_file_path)


def _cleanup_project_file_sync(project_file_path: str):
    """同步清理项目文件（在线程池中运行）"""
    import os
    if os.path.exists(project_file_path):
        os.unlink(project_file_path)
