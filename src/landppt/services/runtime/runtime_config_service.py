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

class RuntimeConfigService:
    """Extracted logic from RuntimeAIService."""

    def __init__(self, service: 'RuntimeAIService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _get_current_ai_config(self, role: str='default'):
        """获取当前最新的AI配置，支持用户级别配置，包括api_key和base_url（同步版本）"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            logger.debug('_get_current_ai_config called from running loop, using global config')
        except RuntimeError:
            if self.user_id is not None:
                try:
                    result = self._get_current_ai_config_sync_impl(role)
                    if result:
                        return result
                except Exception as e:
                    logger.warning(f'Failed to get user AI config: {e}')
        return self._get_fallback_ai_config(role)

    def _get_current_ai_config_sync_impl(self, role: str='default'):
        """同步获取用户AI配置的实现"""
        from ..db_config_service import get_db_config_service
        config_service = get_db_config_service()
        user_config = config_service.get_all_config_sync(user_id=self.user_id)
        return self._extract_ai_config_from_user_config(user_config, role)

    async def _get_current_ai_config_async(self, role: str='default'):
        """获取当前最新的AI配置（异步版本）"""
        if self.user_id is not None:
            try:
                from ..db_config_service import get_db_config_service
                config_service = get_db_config_service()
                user_config = await config_service.get_all_config(user_id=self.user_id)
                result = self._extract_ai_config_from_user_config(user_config, role)
                if result:
                    return result
            except Exception as e:
                logger.warning(f'Failed to get user AI config async, falling back to global: {e}')
        return self._get_fallback_ai_config(role)

    async def _get_current_mineru_config_async(self) -> Dict[str, Optional[str]]:
        """Load the current user's MinerU config in async context."""
        if self.user_id is None:
            return {'api_key': None, 'base_url': None}
        try:
            from ..db_config_service import get_db_config_service
            config_service = get_db_config_service()
            api_key = await config_service.get_config_value('mineru_api_key', user_id=self.user_id)
            base_url = await config_service.get_config_value('mineru_base_url', user_id=self.user_id)
            return {'api_key': api_key, 'base_url': base_url}
        except Exception as e:
            logger.warning(f'Failed to get MinerU config async, falling back to environment/defaults: {e}')
            return {'api_key': None, 'base_url': None}

    def _extract_ai_config_from_user_config(self, user_config: dict, role: str='default'):
        """从用户配置中提取AI配置"""
        role_key = (role or 'default').lower()
        role_provider_key, role_model_key = ai_config.MODEL_ROLE_FIELDS.get(role_key, ('default_model_provider', 'default_model_name') if role_key == 'default' else (f'{role_key}_model_provider', f'{role_key}_model_name'))
        provider = user_config.get(role_provider_key) or user_config.get('default_ai_provider') or 'openai'
        model = user_config.get(role_model_key)
        if not model:
            provider_model_key = f'{provider}_model'
            model = user_config.get(provider_model_key)
        api_key = None
        base_url = None
        use_responses_api = False
        enable_reasoning = False
        reasoning_effort = 'medium'
        if provider == 'openai':
            api_key = user_config.get('openai_api_key')
            base_url = user_config.get('openai_base_url')
            use_responses_api = bool(user_config.get('openai_use_responses_api'))
            enable_reasoning = bool(user_config.get('openai_enable_reasoning'))
            reasoning_effort = str(user_config.get('openai_reasoning_effort') or 'medium')
        elif provider == 'anthropic':
            api_key = user_config.get('anthropic_api_key')
            base_url = user_config.get('anthropic_base_url')
        elif provider == 'google' or provider == 'gemini':
            api_key = user_config.get('google_api_key')
            base_url = user_config.get('google_base_url')
        elif provider == 'landppt':
            api_key = user_config.get('landppt_api_key')
            base_url = user_config.get('landppt_base_url')
        logger.info(f'从数据库获取AI配置: provider={provider}, model={model}, has_api_key={bool(api_key)}, has_base_url={bool(base_url)}')
        return {'llm_model': model, 'llm_provider': provider, 'temperature': float(user_config.get('temperature', 0.7)), 'max_tokens': int(user_config.get('max_tokens', 20000)), 'api_key': api_key, 'base_url': base_url, 'use_responses_api': use_responses_api, 'enable_reasoning': enable_reasoning, 'reasoning_effort': reasoning_effort}

    def _get_fallback_ai_config(self, role: str='default'):
        """获取全局AI配置作为回退"""
        role_settings = ai_config.get_model_config_for_role(role, provider_override=self.provider_name)
        provider_config = ai_config.get_provider_config(role_settings.get('provider'))
        return {'llm_model': role_settings.get('model'), 'llm_provider': role_settings.get('provider'), 'temperature': getattr(ai_config, 'temperature', 0.7), 'max_tokens': getattr(ai_config, 'max_tokens', 2000), 'api_key': provider_config.get('api_key'), 'base_url': provider_config.get('base_url'), 'use_responses_api': bool(provider_config.get('use_responses_api')), 'enable_reasoning': bool(provider_config.get('enable_reasoning')), 'reasoning_effort': str(provider_config.get('reasoning_effort') or 'medium')}

    async def _get_user_generation_config(self) -> Dict[str, Any]:
        """获取用户生成配置，优先从数据库读取，回退到全局ai_config
    
                Returns:
                    Dict containing: max_tokens, temperature, top_p, enable_parallel_generation,
                    parallel_slides_count, and image service settings
                """
        config = {'max_tokens': ai_config.max_tokens, 'temperature': ai_config.temperature, 'top_p': getattr(ai_config, 'top_p', 1.0), 'enable_parallel_generation': ai_config.enable_parallel_generation, 'parallel_slides_count': ai_config.parallel_slides_count, 'enable_per_slide_creative_guidance': True, 'enable_image_service': False, 'enable_local_images': True, 'enable_network_search': False, 'enable_ai_generation': False, 'preferred_image_source': 'local'}
        if self.user_id is None:
            return config
        try:
            from ..db_config_service import get_db_config_service
            config_service = get_db_config_service()
            user_config = await config_service.get_all_config(user_id=self.user_id)
            if user_config.get('max_tokens') is not None:
                try:
                    max_tokens_val = int(user_config['max_tokens'])
                    if max_tokens_val > 0:
                        config['max_tokens'] = max_tokens_val
                except (ValueError, TypeError):
                    pass
            if user_config.get('temperature') is not None:
                try:
                    config['temperature'] = float(user_config['temperature'])
                except (ValueError, TypeError):
                    pass
            if user_config.get('top_p') is not None:
                try:
                    config['top_p'] = float(user_config['top_p'])
                except (ValueError, TypeError):
                    pass
            if user_config.get('enable_parallel_generation') is not None:
                val = user_config['enable_parallel_generation']
                if isinstance(val, str):
                    config['enable_parallel_generation'] = val.lower() == 'true'
                else:
                    config['enable_parallel_generation'] = bool(val)
            if user_config.get('parallel_slides_count'):
                try:
                    config['parallel_slides_count'] = int(user_config['parallel_slides_count'])
                except (ValueError, TypeError):
                    pass
            if user_config.get('enable_per_slide_creative_guidance') is not None:
                val = user_config['enable_per_slide_creative_guidance']
                if isinstance(val, str):
                    config['enable_per_slide_creative_guidance'] = val.lower() == 'true'
                else:
                    config['enable_per_slide_creative_guidance'] = bool(val)
            for key in ['enable_image_service', 'enable_local_images', 'enable_network_search', 'enable_ai_generation']:
                if user_config.get(key) is not None:
                    val = user_config[key]
                    if isinstance(val, str):
                        config[key] = val.lower() == 'true'
                    else:
                        config[key] = bool(val)
            if user_config.get('preferred_image_source'):
                config['preferred_image_source'] = user_config['preferred_image_source']
            logger.debug(f'从用户配置加载生成参数: user_id={self.user_id}, config={config}')
        except Exception as e:
            logger.warning(f'加载用户生成配置失败，使用默认值: {e}')
        return config

    def update_ai_config(self):
        """更新AI配置到最新状态"""
        self.config = self._get_current_ai_config()
        logger.info(f"AI配置已更新: provider={self.config['llm_provider']}, model={self.config['llm_model']}")

    def _build_execution_context(self, role: str, current_ai_config: Optional[Dict[str, Any]]=None) -> ExecutionContext:
        resolved_config = current_ai_config or self._get_current_ai_config()
        source = 'user_db' if self.user_id is not None else 'global_config'
        return ExecutionContext.from_mapping(role, resolved_config, user_id=self.user_id, source=source)

    def _build_summeryanyfile_processing_config(self, *, processing_config_cls, execution_context: ExecutionContext, target_language: str, min_slides: int, max_slides: int, chunk_size: int, chunk_strategy: Any):
        config_kwargs = execution_context.to_processing_config_kwargs()
        config_kwargs.update({'min_slides': min_slides, 'max_slides': max_slides, 'chunk_size': chunk_size, 'chunk_strategy': chunk_strategy, 'target_language': target_language})
        return processing_config_cls(**config_kwargs)
