import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from contextlib import aclosing
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...api.models import (
    PPTGenerationRequest,
    PPTOutline,
    EnhancedPPTOutline,
    SlideContent,
    PPTProject,
    TodoBoard,
    FileOutlineGenerationResponse,
)
from ...ai import get_ai_provider, get_role_provider, AIMessage, MessageRole
from ...ai.base import TextContent, ImageContent
from ...ai.providers import strip_think_content
from ...core.config import ai_config, app_config
from ..runtime.ai_execution import (
    ExecutionContext,
    ai_conversation_context,
    get_current_ai_conversation_id,
    is_provider_protocol_error,
    new_ai_conversation_id,
)
from ..prompts import prompts_manager
from ..template_package.outline_reference import with_package_reference
from ..video_explainer import is_video_explainer
from ..research.enhanced_research_service import EnhancedResearchService
from ..research.keenable_provider import KeenableSearchError
from ..research.enhanced_report_generator import EnhancedReportGenerator
from ..pyppeteer_pdf_converter import get_pdf_converter
from ..image.image_service import ImageService
from ..image.adapters.ppt_prompt_adapter import PPTSlideContext
from ...utils.thread_pool import run_blocking_io, to_thread


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .project_outline_generation_service import ProjectOutlineGenerationService

class ProjectOutlineStreamingService:
    """Extracted logic from ProjectOutlineGenerationService."""

    def __init__(self, service: 'ProjectOutlineGenerationService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _mark_streaming_outline_failed(self, project_id: str, reason: str) -> None:
        """Record a real failure so the UI shows an error and a retry button.

        Without this the stage stays "running" forever and the todo board spins.
        """
        try:
            from ..db_project_manager import DatabaseProjectManager
            db_manager = DatabaseProjectManager()
            await db_manager.update_stage_status(
                project_id,
                'outline_generation',
                'failed',
                None,
                {'message': reason, 'failed_at': time.time()},
            )
        except Exception as stage_error:
            logger.error(
                'Could not mark outline_generation as failed for project %s: %s',
                project_id, stage_error
            )

    @staticmethod
    def _get_outline_streaming_system_prompt() -> str:
        """流式大纲生成需要更强的输出约束，避免模型复述任务说明。"""
        from ..prompts.system_prompts import SystemPrompts
        return SystemPrompts.with_cache_prefix(
            "你是专业的PPT大纲生成器。\n"
            "你只能输出合法的 JSON 大纲，并使用 ```json 代码块包裹。\n"
            "不要复述题目、受众、页数要求、字段说明、示例格式或任务描述。\n"
            "如果无法完全确定，请直接给出最合理的 JSON 大纲，而不是解释原因。"
        )

    async def _parse_streaming_outline_content(
        self,
        content: str,
        project: PPTProject,
        confirmed_requirements: Dict[str, Any],
    ) -> tuple[Dict[str, Any], bool]:
        """优先解析 JSON；若模型跑偏为文本说明，则退回文本大纲解析。"""
        content = strip_think_content(content)
        json_parse_error: Exception | None = None

        try:
            json_block_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            code_block_match = re.search(r'```\s*(\{.*?\})\s*```', content, re.DOTALL) if not json_block_match else None
            json_match = re.search(r'\{.*\}', content, re.DOTALL) if not json_block_match and not code_block_match else None

            if json_block_match:
                json_str = json_block_match.group(1)
            elif code_block_match:
                json_str = code_block_match.group(1)
            elif json_match:
                json_str = json_match.group()
            else:
                json_str = content

            structured_outline = json.loads(json_str)
            # Normalise locally BEFORE validating. Skipping this turned cosmetic
            # variants (a `pages` key, a nested `outline`, page-number gaps) into
            # up to 10 sequential blocking LLM repair calls for data one local
            # function already knows how to fix.
            structured_outline = self._standardize_outline_format(structured_outline)
            structured_outline = await self._validate_and_repair_outline_json(structured_outline, confirmed_requirements)
            return structured_outline, False
        except Exception as parse_error:
            json_parse_error = parse_error

        logger.warning('Streaming outline JSON parse failed, falling back to text outline parsing: %s', json_parse_error)
        structured_outline = self._parse_outline_content(content, project)
        structured_outline = self._standardize_outline_format(structured_outline)
        # No further fallback: if this also fails the caller must report a failure
        # rather than persist an unusable outline and emit success.
        structured_outline = await self._validate_and_repair_outline_json(structured_outline, confirmed_requirements)
        return structured_outline, True

    async def _build_streaming_research_status_event(self, step: str, message: str, progress: float) -> str:
        import json
        return f"data: {json.dumps({'status': {'step': step, 'message': message, 'progress': progress}}, ensure_ascii=False)}\n\n"

    async def _run_streaming_outline_research(self, project_id: str, project: PPTProject, confirmed_requirements: Dict[str, Any], network_mode: bool):
        if not network_mode:
            logger.info(f'Project {project_id} does not have network mode enabled')
            return

        if not getattr(self, 'enhanced_research_service', None) and not getattr(self, 'research_service', None):
            try:
                self._initialize_research_services()
            except Exception:
                pass

        research_runtime = self._get_preferred_outline_research_runtime()
        research_service = research_runtime.get('service')
        provider = research_runtime.get('provider')
        is_enhanced = bool(research_runtime.get('is_enhanced'))
        report_generator = research_runtime.get('report_generator')

        if research_service is None:
            logger.warning(f'Project {project_id} has network mode enabled but no research service is available')
            yield await self._build_streaming_research_status_event('research_skip', '已启用联网模式，但研究服务不可用，改为直接生成大纲...', 0.02)
            return

        research_context_data = {'scenario': project.scenario, 'target_audience': confirmed_requirements.get('target_audience', '普通大众'), 'custom_audience': confirmed_requirements.get('custom_audience', ''), 'requirements': confirmed_requirements.get('requirements', project.requirements), 'ppt_style': confirmed_requirements.get('ppt_style', 'general'), 'description': confirmed_requirements.get('description', '')}
        research_language = 'zh'
        if project.project_metadata and isinstance(project.project_metadata, dict):
            research_language = project.project_metadata.get('language', 'zh')

        provider_display_name = '增强研究' if provider == 'enhanced' else '标准研究'
        yield await self._build_streaming_research_status_event('research', f'🔍 开始{provider_display_name}...', 0.0)

        async def _execute_research(selected_service, selected_provider: str):
            if selected_provider == 'enhanced':
                return await selected_service.conduct_enhanced_research(
                    topic=project.topic,
                    language=research_language,
                    context=research_context_data,
                    event_callback=_research_event_cb,
                )
            return await selected_service.conduct_deep_research(
                topic=project.topic,
                language=research_language,
                context=research_context_data,
                progress_callback=_research_progress_cb,
                event_callback=_research_event_cb,
            )

        _research_status_queue = asyncio.Queue()
        _research_event_queue = asyncio.Queue()

        async def _research_progress_cb(message: str, progress: float):
            await _research_status_queue.put((message, progress))

        async def _research_event_cb(event: Dict[str, Any]):
            await _research_event_queue.put(event)

        research_report = None
        last_ping_at = time.time()
        # Cancel any still-running research when this generator is closed (client
        # disconnect). Left detached it keeps consuming LLM/search budget for a
        # result nobody will read.
        spawned_research_tasks: List[asyncio.Task] = []
        try:
            research_task = asyncio.create_task(_execute_research(research_service, provider))
            spawned_research_tasks.append(research_task)
            while not research_task.done():
                done, _ = await asyncio.wait({research_task}, timeout=1.0)
                while not _research_status_queue.empty():
                    msg, prog = _research_status_queue.get_nowait()
                    yield await self._build_streaming_research_status_event('research', msg, prog)
                while not _research_event_queue.empty():
                    research_event = _research_event_queue.get_nowait()
                    for payload in self.iter_research_stream_payloads(research_event):
                        yield f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'
                if done:
                    break
                now = time.time()
                if now - last_ping_at >= 5:
                    yield f"data: {json.dumps({'ping': True})}\n\n"
                    last_ping_at = now
            research_report = await research_task
        except KeenableSearchError:
            raise
        except Exception as research_error:
            if is_provider_protocol_error(research_error):
                raise
            if provider == 'enhanced' and getattr(self, 'research_service', None) is not None:
                logger.warning('Enhanced research failed for project %s, falling back to legacy research: %s', project_id, research_error)
                yield await self._build_streaming_research_status_event('research_fallback', '增强研究不可用，正在切换到标准研究...', 0.05)
                while not _research_status_queue.empty():
                    _research_status_queue.get_nowait()
                while not _research_event_queue.empty():
                    _research_event_queue.get_nowait()
                research_service = self.research_service
                provider = 'legacy'
                is_enhanced = False
                report_generator = getattr(self, 'report_generator', None)
                last_ping_at = time.time()
                try:
                    research_task = asyncio.create_task(_execute_research(research_service, provider))
                    spawned_research_tasks.append(research_task)
                    while not research_task.done():
                        done, _ = await asyncio.wait({research_task}, timeout=1.0)
                        while not _research_status_queue.empty():
                            msg, prog = _research_status_queue.get_nowait()
                            yield await self._build_streaming_research_status_event('research', msg, prog)
                        while not _research_event_queue.empty():
                            research_event = _research_event_queue.get_nowait()
                            for payload in self.iter_research_stream_payloads(research_event):
                                yield f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'
                        if done:
                            break
                        now = time.time()
                        if now - last_ping_at >= 5:
                            yield f"data: {json.dumps({'ping': True})}\n\n"
                            last_ping_at = now
                    research_report = await research_task
                except Exception as fallback_error:
                    if is_provider_protocol_error(fallback_error):
                        raise
                    logger.warning('Legacy research fallback failed for project %s, proceeding without research context: %s', project_id, fallback_error)
                    yield await self._build_streaming_research_status_event('research_skip', '联网研究失败，改为直接生成大纲...', 0.08)
                    return
            else:
                logger.warning('Research failed for project %s, proceeding without research context: %s', project_id, research_error)
                yield await self._build_streaming_research_status_event('research_skip', '联网研究失败，改为直接生成大纲...', 0.08)
                return
        finally:
            for task in spawned_research_tasks:
                if not task.done():
                    logger.info('Cancelling orphaned research task for project %s', project_id)
                    task.cancel()

        while not _research_status_queue.empty():
            msg, prog = _research_status_queue.get_nowait()
            yield await self._build_streaming_research_status_event('research', msg, prog)
        while not _research_event_queue.empty():
            research_event = _research_event_queue.get_nowait()
            for payload in self.iter_research_stream_payloads(research_event):
                yield f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'

        if research_report is None:
            return

        report_path = None
        report_path_is_temp = False
        if report_generator is not None:
            try:
                report_path = report_generator.save_report_to_file(research_report)
                logger.info('📄 %s research report saved to: %s', provider, report_path)
            except Exception as save_error:
                logger.warning('Failed to save %s research report: %s', provider, save_error)
                report_path = None
        if is_video_explainer(confirmed_requirements):
            yield {
                "research_context": self._create_research_context(research_report),
                "research_metadata": {
                    "research_enhanced": is_enhanced,
                    "research_provider": provider,
                    "research_duration": getattr(research_report, "total_duration", None),
                    "research_sources": len(getattr(research_report, "sources", []) or []),
                },
            }
            return
        if not report_path:
            try:
                research_context = self._create_research_context(research_report)
                report_path = await run_blocking_io(self._save_research_to_temp_file, research_context)
                report_path_is_temp = True
                logger.info('📄 %s research content saved to temporary file: %s', provider, report_path)
            except Exception as tmp_error:
                logger.warning('Failed to create temporary %s research file: %s', provider, tmp_error)
                return

        if not report_path or not Path(report_path).exists():
            return

        yield await self._build_streaming_research_status_event('file_process', '正在基于研究成果生成大纲...', 0.0)
        try:
            from ...api.models import FileOutlineGenerationRequest
            language = 'zh'
            if project.project_metadata and isinstance(project.project_metadata, dict):
                language = project.project_metadata.get('language', 'zh')
            file_request = FileOutlineGenerationRequest(file_path=report_path, filename=Path(report_path).name, topic=confirmed_requirements.get('topic', project.topic), scenario=confirmed_requirements.get('type', project.scenario), requirements=with_package_reference(confirmed_requirements.get('requirements', project.requirements), confirmed_requirements), description=confirmed_requirements.get('description'), language=language, page_count_mode=confirmed_requirements.get('page_count_settings', {}).get('mode', 'ai_decide'), min_pages=confirmed_requirements.get('page_count_settings', {}).get('min_pages', 8), max_pages=confirmed_requirements.get('page_count_settings', {}).get('max_pages', 15), fixed_pages=confirmed_requirements.get('page_count_settings', {}).get('fixed_pages', 10), ppt_style=confirmed_requirements.get('ppt_style', 'general'), custom_style_prompt=confirmed_requirements.get('custom_style_prompt'), include_transition_pages=bool(confirmed_requirements.get('include_transition_pages', False)), target_audience=confirmed_requirements.get('target_audience', '普通大众'), custom_audience=confirmed_requirements.get('custom_audience'), file_processing_mode='markitdown', content_analysis_depth='fast')
            structured_outline = None
            llm_call_count = 0
            last_ping_at = time.time()
            # Own the nested file-outline stream: breaking out on the first
            # outline would otherwise abandon it to the loop's finalizer, which
            # unwinds its conversation scope in a copied Context.
            async with aclosing(self.generate_outline_from_file_streaming(file_request)) as file_stream:
                async for event in file_stream:
                    if event.get('error'):
                        raise ValueError(event['error'])
                    if event.get('outline'):
                        structured_outline = event['outline']
                        try:
                            llm_call_count = max(0, int(event.get('llm_call_count') or 0))
                        except Exception:
                            llm_call_count = 0
                        break
                    yield f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
                    now = time.time()
                    if now - last_ping_at >= 5:
                        yield f"data: {json.dumps({'ping': True})}\n\n"
                        last_ping_at = now
            if structured_outline:
                if 'metadata' not in structured_outline:
                    structured_outline['metadata'] = {}
                structured_outline['metadata']['research_enhanced'] = is_enhanced
                structured_outline['metadata']['research_provider'] = provider
                structured_outline['metadata']['research_duration'] = getattr(research_report, 'total_duration', None)
                structured_outline['metadata']['research_sources'] = len(getattr(research_report, 'sources', []) or [])
                structured_outline['metadata']['generated_from_research_file'] = True
                structured_outline['metadata']['generated_at'] = time.time()
                yield {'outline': structured_outline, 'llm_call_count': llm_call_count}
                return
        finally:
            if report_path_is_temp and report_path:
                try:
                    await run_blocking_io(self._cleanup_temp_file, report_path)
                    logger.info('Cleaned up temporary research file: %s', report_path)
                except Exception as cleanup_error:
                    logger.warning('Failed to cleanup temporary research file: %s', cleanup_error)

        return

    async def generate_outline_streaming(self, project_id: str, *, force_regenerate: bool = False):
        conversation_id = (
            get_current_ai_conversation_id()
            or new_ai_conversation_id("outline")
        )
        with ai_conversation_context(conversation_id):
            stream = self._generate_outline_streaming(
                project_id, force_regenerate=force_regenerate
            )
            async with aclosing(stream):
                async for event in stream:
                    yield event

    async def _generate_outline_streaming(self, project_id: str, *, force_regenerate: bool = False):
        """Generate outline with streaming output"""
        try:
            project = await self.project_manager.get_project(project_id)
            if not project:
                raise ValueError('Project not found')
            from ..file_outline_utils import extract_saved_file_outline, should_force_file_outline_regeneration
            force_file_outline_regeneration = should_force_file_outline_regeneration(project.confirmed_requirements or {})
            ignore_saved_outline = bool(force_regenerate or force_file_outline_regeneration)
            existing_outline = project.outline if isinstance(project.outline, dict) else None
            existing_slides = existing_outline.get('slides', []) if existing_outline else []
            if existing_slides and not ignore_saved_outline:
                import json
                logger.info(
                    'Project %s already has an outline with %s slides, streaming saved outline',
                    project_id,
                    len(existing_slides),
                )
                await self._update_outline_generation_stage(project_id, existing_outline)
                yield f"data: {json.dumps({'status': {'step': 'cached', 'message': '已加载已有大纲', 'progress': 1.0}}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'outline': existing_outline}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'llm_call_count': 0})}\n\n"
                return
            if ignore_saved_outline:
                logger.info(
                    'Project %s requested fresh outline generation, skipping saved outline cache',
                    project_id,
                )
            file_generated_outline = extract_saved_file_outline(
                project.outline,
                project.confirmed_requirements or {},
                ignore_saved_outline=ignore_saved_outline,
            )
            if file_generated_outline:
                logger.info('Project %s already has reusable outline generated from file, using existing outline', project_id)
            if file_generated_outline:
                import json
                yield f"data: {json.dumps({'status': {'step': 'file_process', 'message': '检测到已有文件大纲，正在加载...', 'progress': 0.5}})}\n\n"
                existing_outline = {'title': file_generated_outline.get('title', project.topic), 'slides': file_generated_outline.get('slides', []), 'metadata': file_generated_outline.get('metadata', {})}
                if 'metadata' not in existing_outline:
                    existing_outline['metadata'] = {}
                existing_outline['metadata']['generated_with_summeryfile'] = True
                existing_outline['metadata']['generated_at'] = time.time()
                formatted_json = json.dumps(existing_outline, ensure_ascii=False, indent=2)
                for i, char in enumerate(formatted_json):
                    yield f"data: {json.dumps({'content': char})}\n\n"
                    if i % 10 == 0:
                        await asyncio.sleep(0.02)
                project.outline = existing_outline
                project.updated_at = time.time()
                try:
                    from ..db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()
                    save_success = await db_manager.save_project_outline(project_id, project.outline)
                    if save_success:
                        logger.info(f'✅ Successfully saved file-generated outline to database for project {project_id}')
                        projects_cache = getattr(self.project_manager, 'projects', None)
                        if isinstance(projects_cache, dict):
                            projects_cache[project_id] = project
                    else:
                        logger.error(f'❌ Failed to save file-generated outline to database for project {project_id}')
                except Exception as save_error:
                    logger.error(f'❌ Exception while saving file-generated outline: {str(save_error)}')
                    import traceback
                    traceback.print_exc()
                await self._update_outline_generation_stage(project_id, existing_outline)
                yield f"data: {json.dumps({'done': True, 'llm_call_count': 0})}\n\n"
                return
            await self.project_manager.update_project_status(project_id, 'in_progress')
            if project.todo_board:
                for stage in project.todo_board.stages:
                    if stage.id == 'outline_generation':
                        stage.status = 'running'
                        break
            import json
            yield f"data: {json.dumps({'ping': True})}\n\n"
            yield f"data: {json.dumps({'status': {'step': 'init', 'message': '正在准备大纲生成...', 'progress': 0.0}})}\n\n"
            confirmed_requirements = project.confirmed_requirements or {}
            video_mode = is_video_explainer(confirmed_requirements)
            research_context = ""
            research_metadata = {}
            network_mode = False
            if project.project_metadata and isinstance(project.project_metadata, dict):
                network_mode = project.project_metadata.get('network_mode', False)

            # Own the research stream for the same reason: this loop returns as
            # soon as it has an outline, which would abandon the research
            # generator and the file-outline stream nested inside it.
            async with aclosing(
                self._run_streaming_outline_research(project_id, project, confirmed_requirements, network_mode)
            ) as research_stream:
                async for research_event in research_stream:
                    if isinstance(research_event, str):
                        yield research_event
                        continue
                    if not isinstance(research_event, dict):
                        continue

                    if video_mode and isinstance(research_event.get("research_context"), str):
                        research_context = research_event["research_context"]
                        research_metadata = research_event.get("research_metadata", {})
                    structured_outline = research_event.get('outline')
                    if structured_outline:
                        project.outline = structured_outline
                        project.updated_at = time.time()
                        try:
                            from ..db_project_manager import DatabaseProjectManager
                            db_manager = DatabaseProjectManager()
                            save_success = await db_manager.save_project_outline(project_id, project.outline)
                            if save_success:
                                logger.info(f'✅ Successfully saved research-enhanced outline to database for project {project_id}')
                                projects_cache = getattr(self.project_manager, 'projects', None)
                                if isinstance(projects_cache, dict):
                                    projects_cache[project_id] = project
                            else:
                                logger.error(f'❌ Failed to save research-enhanced outline to database for project {project_id}')
                        except Exception as save_error:
                            logger.error(f'❌ Exception while saving research-enhanced outline: {str(save_error)}')
                        await self._update_outline_generation_stage(project_id, structured_outline)
                        yield f"data: {json.dumps({'outline': structured_outline}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'done': True, 'llm_call_count': research_event.get('llm_call_count', 0)})}\n\n"
                        return
            page_count_settings = confirmed_requirements.get('page_count_settings', {})
            page_count_mode = page_count_settings.get('mode', 'ai_decide')
            page_count_instruction = ''
            if page_count_mode == 'custom_range':
                min_pages = page_count_settings.get('min_pages', 8)
                max_pages = page_count_settings.get('max_pages', 15)
                page_count_instruction = f'- 页数要求：必须严格生成{min_pages}-{max_pages}页的PPT，确保页数在此范围内'
            elif page_count_mode == 'fixed':
                fixed_pages = page_count_settings.get('fixed_pages', 10)
                page_count_instruction = f'- 页数要求：必须生成恰好{fixed_pages}页的PPT'
            else:
                page_count_instruction = '- 页数要求：根据内容复杂度自主决定合适的页数（建议8-15页）'
            topic = confirmed_requirements.get('topic', project.topic)
            target_audience = confirmed_requirements.get('target_audience', '普通大众')
            ppt_style = confirmed_requirements.get('ppt_style', 'general')
            # The direct-generation branch previously ignored the project language,
            # so an English project received a Chinese outline.
            outline_language = 'zh'
            if getattr(project, 'project_metadata', None):
                outline_language = project.project_metadata.get('language') or 'zh'
            if video_mode:
                prompt = prompts_manager.outline.get_video_storyboard_prompt(
                    topic=topic,
                    target_audience=target_audience,
                    requirements=confirmed_requirements.get("requirements") or project.requirements or "",
                    visual_style=confirmed_requirements.get("custom_style_prompt") or "",
                    page_count_instruction=page_count_instruction.replace("的PPT", "").replace(
                        "页数", "镜头数"
                    ).replace("页", "镜"),
                    research_context=research_context,
                    language=outline_language,
                )
                system_prompt = "你为技术图解视频设计逐镜大纲，只输出合法的 JSON 代码块。"
            else:
                prompt = prompts_manager.get_streaming_outline_prompt(topic=topic, target_audience=target_audience, ppt_style=ppt_style, page_count_instruction=page_count_instruction, research_section='', include_transition_pages=bool(confirmed_requirements.get('include_transition_pages', False)), language=outline_language)
                system_prompt = self._get_outline_streaming_system_prompt()
            prompt = with_package_reference(prompt, confirmed_requirements)
            yield f"data: {json.dumps({'status': {'step': 'generating', 'message': 'AI 正在构建大纲...', 'progress': 0.0}})}\n\n"
            try:
                content = ''
                token_count = 0
                async for chunk in self._stream_text_completion_for_role(
                    'outline',
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=ai_config.temperature,
                ):
                    content += chunk
                    token_count += 1
                    if not video_mode:
                        yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                    if token_count % 50 == 0:
                        yield f"data: {json.dumps({'status': {'step': 'generating', 'message': f'AI 正在构建大纲... ({token_count} tokens)', 'progress': min(0.9, token_count / 500)}})}\n\n"
                content = content.strip()
                if not content or len(content.strip()) < 10:
                    error_message = 'AI生成的内容为空或过短，请重新生成大纲。'
                    yield f"data: {json.dumps({'error': error_message})}\n\n"
                    return
            except Exception as ai_error:
                logger.error(f'AI provider error during outline generation: {str(ai_error)}')
                if 'timeout' in str(ai_error).lower() or 'request timed out' in str(ai_error).lower():
                    error_message = 'AI服务响应超时，请检查网络连接后重新生成大纲。'
                elif 'api' in str(ai_error).lower() and 'error' in str(ai_error).lower():
                    error_message = 'AI服务暂时不可用，请稍后重新生成大纲。'
                else:
                    error_message = f'AI生成大纲失败：{str(ai_error)}。请重新生成大纲。'
                yield f"data: {json.dumps({'error': error_message})}\n\n"
                return
            structured_outline = None
            yield f"data: {json.dumps({'status': {'step': 'validating', 'message': '正在验证大纲结构...', 'progress': 0.0}})}\n\n"
            try:
                structured_outline, used_text_fallback = await self._parse_streaming_outline_content(
                    content,
                    project,
                    confirmed_requirements,
                )
                validating_message = '正在修复和优化大纲...' if not used_text_fallback else 'AI 未返回标准 JSON，正在自动修复文本大纲...'
                yield f"data: {json.dumps({'status': {'step': 'validating', 'message': validating_message, 'progress': 0.5}})}\n\n"
                actual_page_count = len(structured_outline.get('slides', []))
                if page_count_mode == 'custom_range':
                    min_pages = page_count_settings.get('min_pages', 8)
                    max_pages = page_count_settings.get('max_pages', 15)
                    if actual_page_count < min_pages or actual_page_count > max_pages:
                        logger.warning(f'Generated outline has {actual_page_count} pages, but expected {min_pages}-{max_pages} pages')
                elif page_count_mode == 'fixed':
                    fixed_pages = page_count_settings.get('fixed_pages', 10)
                    if actual_page_count != fixed_pages:
                        logger.warning(f'Generated outline has {actual_page_count} pages, but expected exactly {fixed_pages} pages')
                yield f"data: {json.dumps({'status': {'step': 'validating', 'message': f'大纲验证完成，共 {actual_page_count} 页', 'progress': 1.0}})}\n\n"
                structured_outline['metadata'] = {'generated_with_summeryfile': False, 'page_count_settings': page_count_settings, 'actual_page_count': actual_page_count, 'generated_at': time.time()}
                structured_outline["metadata"].update(research_metadata)
                project.outline = structured_outline
                project.updated_at = time.time()
                # A failed save must not be followed by a success event, or the user
                # sees a finished outline that no longer exists after a reload.
                try:
                    from ..db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()
                    save_success = await db_manager.save_project_outline(project_id, project.outline)
                except Exception as save_error:
                    logger.error(f'❌ Exception while saving outline during streaming: {str(save_error)}', exc_info=True)
                    save_success = False

                if not save_success:
                    logger.error(f'❌ Failed to save outline to database during streaming for project {project_id}')
                    await self._mark_streaming_outline_failed(project_id, '大纲保存到数据库失败')
                    yield f"data: {json.dumps({'error': '大纲已生成但保存失败，请重新生成大纲。'})}\n\n"
                    return

                logger.info(f'✅ Successfully saved outline to database during streaming for project {project_id}')
                projects_cache = getattr(self.project_manager, 'projects', None)
                if isinstance(projects_cache, dict):
                    projects_cache[project_id] = project

                await self._update_outline_generation_stage(project_id, structured_outline)
                yield f"data: {json.dumps({'outline': structured_outline}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'llm_call_count': 1})}\n\n"
                return
            except Exception as parse_error:
                from .outline_errors import OutlineRepairFailedError

                logger.error(f'Failed to build a valid outline: {parse_error}')
                logger.error(f'AI response content: {content[:500]}...')
                if isinstance(parse_error, OutlineRepairFailedError):
                    error_message = (
                        'AI生成的大纲不符合要求且自动修复失败：'
                        f"{'; '.join(parse_error.validation_errors)}。请重新生成大纲。"
                    )
                else:
                    error_message = 'AI生成的大纲格式无效，无法解析。请重新生成大纲。'
                await self._mark_streaming_outline_failed(project_id, error_message)
                yield f"data: {json.dumps({'error': error_message})}\n\n"
                return
        except Exception as e:
            logger.error(f'Error in outline streaming generation: {str(e)}')
            if 'timeout' in str(e).lower() or 'api error' in str(e).lower() or 'request timed out' in str(e).lower():
                error_message = f'AI服务暂时不可用：{str(e)}。请稍后重试或检查网络连接。'
            else:
                error_message = f'生成大纲时出现错误：{str(e)}'
            yield f"data: {json.dumps({'error': error_message})}\n\n"
