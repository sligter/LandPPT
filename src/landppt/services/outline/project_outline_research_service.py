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
from ...core.config import ai_config, app_config
from ..runtime.ai_execution import ExecutionContext
from ..prompts import prompts_manager
from ..research.enhanced_research_service import EnhancedResearchService
from ..research.enhanced_report_generator import EnhancedReportGenerator
from ..pyppeteer_pdf_converter import get_pdf_converter
from ..image.image_service import ImageService
from ..image.adapters.ppt_prompt_adapter import PPTSlideContext
from ...utils.thread_pool import run_blocking_io, to_thread


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .project_outline_creation_service import ProjectOutlineCreationService

class ProjectOutlineResearchService:
    """Extracted logic from ProjectOutlineCreationService."""

    def __init__(self, service: 'ProjectOutlineCreationService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _generate_outline_from_research_runtime(self, request: PPTGenerationRequest, page_count_settings: Dict[str, Any]=None) -> Optional[PPTOutline]:
        if not getattr(self, 'enhanced_research_service', None) and not getattr(self, 'research_service', None):
            try:
                self._initialize_research_services()
            except Exception:
                pass

        research_runtime = self._get_preferred_outline_research_runtime()
        research_service = research_runtime.get('service')
        report_generator = research_runtime.get('report_generator')
        provider = research_runtime.get('provider')
        is_enhanced = bool(research_runtime.get('is_enhanced'))

        if research_service is None:
            logger.warning('Network mode enabled but no research service initialized')
            return None

        research_input_context = {
            'scenario': request.scenario,
            'target_audience': getattr(request, 'target_audience', '普通大众'),
            'requirements': request.requirements,
            'ppt_style': getattr(request, 'ppt_style', 'general'),
            'description': getattr(request, 'description', ''),
        }

        logger.info('Starting %s research for topic: %s', provider, request.topic)
        research_report = None
        try:
            if provider == 'enhanced':
                research_report = await research_service.conduct_enhanced_research(
                    topic=request.topic,
                    language=request.language,
                    context=research_input_context,
                )
            else:
                research_report = await research_service.conduct_deep_research(
                    topic=request.topic,
                    language=request.language,
                    context=research_input_context,
                )
        except Exception as research_error:
            if provider == 'enhanced' and getattr(self, 'research_service', None) is not None:
                logger.warning('Enhanced research failed, falling back to legacy research: %s', research_error)
                research_service = self.research_service
                report_generator = getattr(self, 'report_generator', None)
                provider = 'legacy'
                is_enhanced = False
                try:
                    research_report = await research_service.conduct_deep_research(
                        topic=request.topic,
                        language=request.language,
                        context=research_input_context,
                    )
                except Exception as fallback_error:
                    logger.error('Legacy research fallback also failed: %s', fallback_error)
                    import traceback
                    logger.error(f'Traceback: {traceback.format_exc()}')
                    return None
            else:
                logger.error(f'{provider or "unknown"} research failed: {research_error}')
                import traceback
                logger.error(f'Traceback: {traceback.format_exc()}')
                return None

        report_path = None
        report_path_is_temp = False
        if report_generator is not None:
            try:
                report_path = report_generator.save_report_to_file(research_report)
                logger.info('%s research report saved to: %s', provider, report_path)
            except Exception as save_error:
                logger.warning('Failed to save %s research report: %s', provider, save_error)
                report_path = None
        if not report_path:
            try:
                report_markdown = self._create_research_context(research_report)
                report_path = await run_blocking_io(self._save_research_to_temp_file, report_markdown)
                report_path_is_temp = True
                logger.info('%s research report saved to temporary file: %s', provider, report_path)
            except Exception as tmp_error:
                logger.warning('Failed to create temporary %s research report file: %s', provider, tmp_error)
                report_path = None

        if report_path and Path(report_path).exists():
            logger.info('Using %s research report file for outline generation: %s', provider, report_path)
            try:
                from ...api.models import FileOutlineGenerationRequest
                file_request = FileOutlineGenerationRequest(file_path=report_path, filename=Path(report_path).name, topic=request.topic, scenario=request.scenario, requirements=request.requirements, target_audience=getattr(request, 'target_audience', '普通大众'), ppt_style=getattr(request, 'ppt_style', 'general'), custom_style_prompt=getattr(request, 'custom_style_prompt', ''), page_count_mode=page_count_settings.get('mode', 'ai_decide') if page_count_settings else 'ai_decide', min_pages=page_count_settings.get('min_pages') if page_count_settings else None, max_pages=page_count_settings.get('max_pages') if page_count_settings else None, fixed_pages=page_count_settings.get('fixed_pages') if page_count_settings else None, language=request.language)
                file_outline_result = await self.generate_outline_from_file(file_request)
                if file_outline_result.success and file_outline_result.outline:
                    outline_data = file_outline_result.outline
                    outline = PPTOutline(
                        title=outline_data.get('title', request.topic),
                        slides=outline_data.get('slides', []),
                        metadata={
                            **outline_data.get('metadata', {}),
                            'research_enhanced': is_enhanced,
                            'research_provider': provider,
                            'research_sources': len(getattr(research_report, 'sources', []) or []),
                            'research_duration': getattr(research_report, 'total_duration', None),
                            'research_file_path': report_path,
                            'generated_from_research_file': True,
                        },
                    )
                    if page_count_settings:
                        outline.metadata['page_count_settings'] = page_count_settings
                    logger.info('Successfully generated outline from %s research report file', provider)
                    return outline
                logger.warning('File-based outline generation failed after %s research, falling back to traditional method', provider)
            except Exception as file_error:
                logger.warning('Failed to generate outline from %s research file, falling back to traditional method: %s', provider, file_error)
            finally:
                if report_path_is_temp and report_path:
                    try:
                        await run_blocking_io(self._cleanup_temp_file, report_path)
                    except Exception:
                        pass

        logger.info('%s research completed but file-based outline generation failed', provider)
        return None

    async def generate_outline(self, request: PPTGenerationRequest, page_count_settings: Dict[str, Any]=None) -> PPTOutline:
        """Generate PPT outline using real AI with optional Enhanced research and page count settings"""
        try:
            if request.network_mode:
                researched_outline = await self._generate_outline_from_research_runtime(request, page_count_settings)
                if researched_outline is not None:
                    return researched_outline
            prompt = self._create_outline_prompt(request, '', page_count_settings)
            response = await self._text_completion_for_role('outline', prompt=prompt, temperature=ai_config.temperature)
            outline = self._parse_ai_outline(response.content, request)
            if page_count_settings:
                outline.metadata['page_count_settings'] = page_count_settings
            return outline
        except Exception as e:
            logger.error(f'Error generating AI outline: {str(e)}')
            if 'timeout' in str(e).lower() or 'request timed out' in str(e).lower():
                raise Exception('AI服务响应超时，请检查网络连接后重新生成大纲。')
            elif 'api' in str(e).lower() and 'error' in str(e).lower():
                raise Exception('AI服务暂时不可用，请稍后重新生成大纲。')
            else:
                raise Exception(f'AI生成大纲失败：{str(e)}。请重新生成大纲。')

    def _standardize_summeryfile_outline(self, summeryfile_outline: Dict[str, Any]) -> Dict[str, Any]:
        """
                    将summeryanyfile生成的大纲格式标准化为LandPPT格式
        
                    Args:
                        summeryfile_outline: summeryanyfile生成的大纲数据
        
                    Returns:
                        标准化后的LandPPT格式大纲
                    """
        try:
            title = summeryfile_outline.get('title', 'PPT大纲')
            slides_data = summeryfile_outline.get('slides', [])
            metadata = summeryfile_outline.get('metadata', {})
            standardized_slides = []
            for slide in slides_data:
                content_points = slide.get('content_points', [])
                if not content_points or not isinstance(content_points, list):
                    content = slide.get('content', '')
                    content_points = []
                    if content:
                        lines = content.split('\n')
                        for line in lines:
                            line = line.strip()
                            if line:
                                line = re.sub('^[•\\-\\*]\\s*', '', line)
                                if line:
                                    content_points.append(line)
                if not content_points:
                    content_points = ['内容要点']
                slide_type = slide.get('slide_type', slide.get('type', 'content'))
                page_number = slide.get('page_number', slide.get('id', 1))
                title_text = slide.get('title', '').lower()
                if slide_type not in ['title', 'content', 'agenda', 'thankyou', 'conclusion']:
                    if page_number == 1 or '标题' in title_text or 'title' in title_text:
                        slide_type = 'title'
                    elif '目录' in title_text or 'agenda' in title_text or '大纲' in title_text:
                        slide_type = 'agenda'
                    elif '谢谢' in title_text or 'thank' in title_text or '致谢' in title_text:
                        slide_type = 'thankyou'
                    elif '总结' in title_text or '结论' in title_text or 'conclusion' in title_text or ('summary' in title_text):
                        slide_type = 'conclusion'
                    else:
                        slide_type = 'content'
                elif ('目录' in title_text or 'agenda' in title_text or '大纲' in title_text) and slide_type == 'content':
                    slide_type = 'agenda'
                elif ('谢谢' in title_text or 'thank' in title_text or '致谢' in title_text) and slide_type == 'content':
                    slide_type = 'thankyou'
                elif ('总结' in title_text or '结论' in title_text or 'conclusion' in title_text or ('summary' in title_text)) and slide_type == 'content':
                    slide_type = 'conclusion'
                type_mapping = {'title': 'title', 'content': 'content', 'conclusion': 'thankyou', 'agenda': 'agenda'}
                mapped_type = type_mapping.get(slide_type, 'content')
                standardized_slide = {'page_number': slide.get('page_number', slide.get('id', len(standardized_slides) + 1)), 'title': slide.get('title', f'第{len(standardized_slides) + 1}页'), 'content_points': content_points, 'slide_type': slide_type, 'type': mapped_type, 'description': slide.get('description', '')}
                if 'chart_config' in slide and slide['chart_config']:
                    standardized_slide['chart_config'] = slide['chart_config']
                standardized_slides.append(standardized_slide)
            standardized_metadata = {'generated_with_summeryfile': True, 'page_count_settings': {'mode': metadata.get('page_count_mode', 'ai_decide'), 'min_pages': None, 'max_pages': None, 'fixed_pages': None}, 'actual_page_count': len(standardized_slides), 'generated_at': time.time(), 'original_metadata': metadata}
            if 'total_pages' in metadata:
                standardized_metadata['page_count_settings']['expected_pages'] = metadata['total_pages']
            standardized_outline = {'title': title, 'slides': standardized_slides, 'metadata': standardized_metadata}
            logger.info(f'Successfully standardized summeryfile outline: {title}, {len(standardized_slides)} slides')
            return standardized_outline
        except Exception as e:
            logger.error(f'Error standardizing summeryfile outline: {e}')
            return {'title': 'PPT大纲', 'slides': [{'page_number': 1, 'title': '标题页', 'content_points': ['演示标题', '演示者', '日期'], 'slide_type': 'title', 'type': 'title', 'description': 'PPT标题页'}], 'metadata': {'generated_with_summeryfile': True, 'page_count_settings': {'mode': 'ai_decide'}, 'actual_page_count': 1, 'generated_at': time.time(), 'error': str(e)}}

    async def conduct_research_and_merge_with_files(self, topic: str, language: str, file_paths: Optional[List[str]]=None, context: Optional[Dict[str, Any]]=None, event_callback=None) -> str:
        """
                    进行联网搜索并与本地文件整合
        
                    Args:
                        topic: 研究主题
                        language: 语言
                        file_paths: 本地文件路径列表
                        context: 上下文信息(scenario, target_audience等)
        
                    Returns:
                        整合后的Markdown文件路径
                    """
        try:
            logger.info(f'开始联网搜索和文件整合流程，主题: {topic}')
            logger.info('Step 1: 执行联网搜索...')
            research_markdown = None
            if self.enhanced_research_service is None:
                try:
                    self._initialize_research_services()
                except Exception:
                    pass
            if self.enhanced_research_service:
                try:
                    research_report = await self.enhanced_research_service.conduct_enhanced_research(topic=topic, language=language, context=context, event_callback=event_callback)
                    if self.enhanced_report_generator:
                        research_markdown = self.enhanced_report_generator.save_report_to_file(research_report)
                        logger.info(f'✅ 联网搜索完成，研究报告已保存: {research_markdown}')
                    else:
                        logger.warning('增强报告生成器不可用')
                    if not research_markdown:
                        try:
                            report_markdown = self._create_research_context(research_report)
                            research_markdown = await run_blocking_io(self._save_research_to_temp_file, report_markdown)
                            logger.info(f'Enhanced research report saved to temporary file: {research_markdown}')
                        except Exception as tmp_error:
                            logger.warning(f'Failed to create temporary enhanced research report file: {tmp_error}')
                except Exception as e:
                    logger.error(f'联网搜索失败: {e}')
            else:
                logger.warning('增强研究服务不可用，跳过联网搜索')
            logger.info('Step 2: 处理本地文件...')
            local_files_content = []
            if file_paths:
                from ..services.file_processor import FileProcessor
                file_processor = FileProcessor()
                selected_processing_mode = None
                try:
                    selected_processing_mode = (context or {}).get('file_processing_mode')
                except Exception:
                    selected_processing_mode = None
                for file_path in file_paths:
                    try:
                        filename = os.path.basename(file_path)
                        file_result = await file_processor.process_file(file_path, filename, file_processing_mode=selected_processing_mode)
                        local_files_content.append({'filename': filename, 'content': file_result.processed_content})
                        logger.info(f'✅ 文件处理完成: {filename}')
                    except Exception as e:
                        logger.error(f'文件处理失败 {file_path}: {e}')
            logger.info('Step 3: 整合搜索结果和本地文件...')
            merged_content_parts = []
            merged_content_parts.append(f'# {topic}\n')
            merged_content_parts.append(f"*整合文档 - 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n")
            merged_content_parts.append('---\n\n')
            if research_markdown and os.path.exists(research_markdown):
                merged_content_parts.append('## 📡 联网搜索结果\n\n')
                with open(research_markdown, 'r', encoding='utf-8') as f:
                    search_content = f.read()
                merged_content_parts.append(search_content)
                merged_content_parts.append('\n\n---\n\n')
                logger.info('✅ 已添加联网搜索内容')
            if local_files_content:
                merged_content_parts.append('## 📁 本地文件内容\n\n')
                for i, file_info in enumerate(local_files_content, 1):
                    merged_content_parts.append(f"### {i}. {file_info['filename']}\n\n")
                    merged_content_parts.append(file_info['content'])
                    merged_content_parts.append('\n\n---\n\n')
                logger.info(f'✅ 已添加 {len(local_files_content)} 个本地文件内容')
            merged_content = ''.join(merged_content_parts)
            temp_dir = Path(tempfile.gettempdir()) / 'landppt_merged'
            temp_dir.mkdir(exist_ok=True)
            merged_filename = f'merged_{int(time.time())}_{topic[:30]}.md'
            merged_file_path = temp_dir / merged_filename
            with open(merged_file_path, 'w', encoding='utf-8') as f:
                f.write(merged_content)
            logger.info(f'✅ 整合完成，文件保存至: {merged_file_path}')
            return str(merged_file_path)
        except Exception as e:
            logger.error(f'联网搜索和文件整合失败: {e}')
            raise

    def _extract_summeryanyfile_llm_call_count(self, generator) -> int:
        try:
            chain_executor = getattr(getattr(getattr(generator, 'workflow_manager', None), 'nodes', None), 'chain_executor', None)
            llm_call_count = int(getattr(chain_executor, 'llm_call_count', 0) or 0)
            return max(llm_call_count, 0)
        except Exception:
            return 0
