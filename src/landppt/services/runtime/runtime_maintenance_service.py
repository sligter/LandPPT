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
from .ai_execution import ExecutionContext
from ..prompts import prompts_manager
from ..research.enhanced_research_service import EnhancedResearchService
from ..research.enhanced_report_generator import EnhancedReportGenerator
from ..pyppeteer_pdf_converter import get_pdf_converter
from ..image.image_service import ImageService
from ..image.adapters.ppt_prompt_adapter import PPTSlideContext
from ...utils.thread_pool import run_blocking_io, to_thread


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .runtime_ai_service import RuntimeAIService

class RuntimeMaintenanceService:
    """Extracted logic from RuntimeAIService."""

    def __init__(self, service: 'RuntimeAIService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _configure_summeryfile_api(self, generator, role: str='default'):
        """配置summeryanyfile的API设置"""
        execution_context = self._build_execution_context(role)
        logger.info('Prepared summeryanyfile execution context: provider=%s, model=%s, source=%s', execution_context.provider.provider, execution_context.provider.model, execution_context.source)
        return execution_context
        try:
            import os
            role_settings = ai_config.get_model_config_for_role(role, provider_override=self.provider_name)
            current_provider = role_settings.get('provider')
            provider_config = ai_config.get_provider_config(current_provider).copy()
            if role_settings.get('model'):
                provider_config['model'] = role_settings['model']
            if provider_config.get('max_tokens'):
                os.environ['MAX_TOKENS'] = str(provider_config['max_tokens'])
            if provider_config.get('temperature'):
                os.environ['TEMPERATURE'] = str(provider_config['temperature'])
            if current_provider == 'openai':
                if provider_config.get('api_key'):
                    os.environ['OPENAI_API_KEY'] = provider_config['api_key']
                if provider_config.get('base_url'):
                    os.environ['OPENAI_BASE_URL'] = provider_config['base_url']
                if provider_config.get('model'):
                    os.environ['OPENAI_MODEL'] = provider_config['model']
                os.environ['OPENAI_USE_RESPONSES_API'] = 'true' if provider_config.get('use_responses_api') else 'false'
                os.environ['OPENAI_ENABLE_REASONING'] = 'true' if provider_config.get('enable_reasoning') else 'false'
                os.environ['OPENAI_REASONING_EFFORT'] = str(provider_config.get('reasoning_effort') or 'medium')
                logger.info(f"已配置summeryanyfile OpenAI API: model={provider_config.get('model')}, base_url={provider_config.get('base_url')}")
            elif current_provider == 'anthropic':
                if provider_config.get('api_key'):
                    os.environ['ANTHROPIC_API_KEY'] = provider_config['api_key']
                if provider_config.get('model'):
                    os.environ['ANTHROPIC_MODEL'] = provider_config['model']
                logger.info(f"已配置summeryanyfile Anthropic API: model={provider_config.get('model')}")
            elif current_provider in ('google', 'gemini'):
                if provider_config.get('api_key'):
                    os.environ['GOOGLE_API_KEY'] = provider_config['api_key']
                if provider_config.get('model'):
                    os.environ['GOOGLE_MODEL'] = provider_config['model']
                if provider_config.get('base_url'):
                    os.environ['GOOGLE_BASE_URL'] = provider_config['base_url']
                logger.info(f"已配置summeryanyfile Google/Gemini API: model={provider_config.get('model')}")
            elif current_provider == 'ollama':
                if provider_config.get('base_url'):
                    os.environ['OLLAMA_BASE_URL'] = provider_config['base_url']
                if provider_config.get('model'):
                    os.environ['OLLAMA_MODEL'] = provider_config['model']
                logger.info(f"已配置summeryanyfile Ollama API: model={provider_config.get('model')}, base_url={provider_config.get('base_url')}")
            logger.info(f"已配置summeryanyfile通用参数: max_tokens={provider_config.get('max_tokens')}, temperature={provider_config.get('temperature')}")
        except Exception as e:
            logger.warning(f'配置summeryanyfile API时出现问题: {e}')

    def get_cache_stats(self) -> Dict[str, Any]:
        """
                获取文件缓存统计信息
    
                Returns:
                    缓存统计信息字典
                """
        if getattr(self, 'file_cache_managers', None):
            stats: Dict[str, Any] = {}
            for mode, manager in self.file_cache_managers.items():
                try:
                    stats[mode] = manager.get_cache_stats()
                except Exception as e:
                    stats[mode] = {'error': str(e)}
            return {'modes': stats}
        if self.file_cache_manager:
            return self.file_cache_manager.get_cache_stats()
        return {'error': '缓存管理器未初始化'}

    def cleanup_cache(self):
        """清理过期的缓存条目"""
        if getattr(self, 'file_cache_managers', None):
            for mode, manager in self.file_cache_managers.items():
                try:
                    manager.cleanup_expired_cache()
                    logger.info(f'summeryanyfile缓存清理完成: {mode}')
                except Exception as e:
                    logger.error(f'summeryanyfile缓存清理失败 ({mode}): {e}')
        elif self.file_cache_manager:
            try:
                self.file_cache_manager.cleanup_expired_cache()
                logger.info('summeryanyfile缓存清理完成')
            except Exception as e:
                logger.error(f'summeryanyfile缓存清理失败: {e}')
        self._cleanup_style_genes_cache()
        if hasattr(self, '_cached_style_genes'):
            self._cached_style_genes.clear()
            logger.info('内存中的设计基因缓存已清理')

    def _cleanup_style_genes_cache(self, max_age_days: int=7):
        """清理过期的设计基因缓存文件"""
        if not hasattr(self, 'cache_dirs') or not self.cache_dirs:
            return
        try:
            import json
            import time
            from pathlib import Path
            cache_dir = self.cache_dirs['style_genes']
            if not cache_dir.exists():
                return
            current_time = time.time()
            max_age_seconds = max_age_days * 24 * 3600
            cleaned_count = 0
            for cache_file in cache_dir.glob('*_style_genes.json'):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                        created_at = cache_data.get('created_at', 0)
                    if current_time - created_at > max_age_seconds:
                        cache_file.unlink()
                        cleaned_count += 1
                        logger.debug(f'删除过期的设计基因缓存文件: {cache_file.name}')
                except Exception as e:
                    logger.warning(f'处理缓存文件 {cache_file} 时出错: {e}')
            if cleaned_count > 0:
                logger.info(f'设计基因缓存清理完成，删除了 {cleaned_count} 个过期文件')
            else:
                logger.info('设计基因缓存清理完成，没有过期文件需要删除')
        except Exception as e:
            logger.error(f'设计基因缓存清理失败: {e}')
