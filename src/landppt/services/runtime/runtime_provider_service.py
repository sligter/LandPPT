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

class RuntimeProviderService:
    """Extracted logic from RuntimeAIService."""

    def __init__(self, service: 'RuntimeAIService'):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    @property
    def ai_provider(self):
        """Dynamically get AI provider to ensure latest config"""
        if self.user_id is not None:
            try:
                from ..db_config_service import get_db_config_service, get_user_ai_provider_sync
                try:
                    asyncio.get_running_loop()
                    loop_running = True
                except RuntimeError:
                    loop_running = False
                if loop_running:
                    provider_name = self.provider_name or getattr(self, '_user_default_provider', None) or ai_config.default_ai_provider
                    return get_ai_provider(provider_name)
                self._user_default_provider = self.provider_name or get_db_config_service().get_config_value_sync('default_ai_provider', user_id=self.user_id) or 'openai'
                provider_name = self.provider_name or self._user_default_provider
                return get_user_ai_provider_sync(self.user_id, provider_name)
            except Exception as e:
                logger.warning(f'Failed to get user AI provider, falling back to default: {e}')
        provider_name = self.provider_name or ai_config.default_ai_provider
        return get_ai_provider(provider_name)

    def _get_role_provider(self, role: str):
        """获取指定任务角色的提供者和配置，支持用户级别配置"""
        if self.user_id is not None:
            try:
                from ..db_config_service import get_user_role_provider_sync
                try:
                    asyncio.get_running_loop()
                    loop_running = True
                except RuntimeError:
                    loop_running = False
                if not loop_running:
                    return get_user_role_provider_sync(self.user_id, role, provider_override=self.provider_name)
            except Exception as e:
                logger.warning(f'Failed to get user role provider, falling back to global: {e}')
        return get_role_provider(role, provider_override=self.provider_name)

    async def _get_role_provider_async(self, role: str):
        """获取指定任务角色的提供者和配置（异步版本，正确处理 landppt 系统级配置）"""
        if self.user_id is not None:
            try:
                from ..db_config_service import get_db_config_service, get_user_ai_provider
                config_service = get_db_config_service()
                user_config = await config_service.get_all_config(user_id=self.user_id)
                role_key = (role or 'default').lower()
                role_provider_key, role_model_key = ai_config.MODEL_ROLE_FIELDS.get(role_key, ('default_model_provider', 'default_model_name') if role_key == 'default' else (f'{role_key}_model_provider', f'{role_key}_model_name'))
                provider_name = self.provider_name or user_config.get(role_provider_key) or user_config.get('default_ai_provider') or 'landppt'
                model = user_config.get(role_model_key)
                if not model:
                    provider_model_key = f'{provider_name}_model'
                    model = user_config.get(provider_model_key)
                settings = {'role': role, 'provider': provider_name, 'model': model}
                provider = await get_user_ai_provider(self.user_id, provider_name)
                logger.info(f"Got provider for role '{role}': {provider_name}, model: {model}")
                return (provider, settings)
            except Exception as e:
                logger.warning(f'Failed to get user role provider async, falling back to global: {e}')
        return get_role_provider(role, provider_override=self.provider_name)

    def get_role_provider(self, role: str):
        """Public wrapper for role provider lookup (sync)."""
        return self._get_role_provider(role)

    async def get_role_provider_async(self, role: str):
        """Public wrapper for role provider lookup (async)."""
        return await self._get_role_provider_async(role)

    async def _text_completion_for_role(self, role: str, *, prompt: str, **kwargs):
        """调用指定角色的模型进行文本补全"""
        provider, settings = await self._get_role_provider_async(role)
        if settings.get('model'):
            kwargs.setdefault('model', settings['model'])
        if 'temperature' not in kwargs or 'top_p' not in kwargs:
            try:
                user_gen_config = await self._get_user_generation_config()
                kwargs.setdefault('temperature', user_gen_config['temperature'])
                kwargs.setdefault('top_p', user_gen_config.get('top_p', ai_config.top_p))
            except Exception:
                kwargs.setdefault('temperature', ai_config.temperature)
                kwargs.setdefault('top_p', ai_config.top_p)
        system_prompt = str(kwargs.pop('system_prompt', '') or '').strip()
        if system_prompt:
            # 统一把 system_prompt 转成系统消息，避免上层传参后被静默忽略。
            messages = [
                AIMessage(role=MessageRole.SYSTEM, content=system_prompt),
                AIMessage(role=MessageRole.USER, content=prompt),
            ]
            return await provider.chat_completion(messages=messages, **kwargs)
        if role == 'outline' and settings.get('provider') == 'anthropic':
            full_response = ''
            async for chunk in provider.stream_text_completion(prompt=prompt, **kwargs):
                full_response += chunk
            from ...ai.base import AIResponse
            return AIResponse(content=full_response, model=settings.get('model', 'anthropic'), usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}, finish_reason='stop', metadata={'provider': 'anthropic', 'streamed': True})
        return await provider.text_completion(prompt=prompt, **kwargs)

    async def _stream_text_completion_for_role(self, role: str, *, prompt: str, **kwargs):
        """流式调用指定角色的模型进行文本补全，逐 token yield"""
        provider, settings = await self._get_role_provider_async(role)
        if settings.get('model'):
            kwargs.setdefault('model', settings['model'])
        if 'temperature' not in kwargs or 'top_p' not in kwargs:
            try:
                user_gen_config = await self._get_user_generation_config()
                kwargs.setdefault('temperature', user_gen_config['temperature'])
                kwargs.setdefault('top_p', user_gen_config.get('top_p', ai_config.top_p))
            except Exception:
                kwargs.setdefault('temperature', ai_config.temperature)
                kwargs.setdefault('top_p', ai_config.top_p)
        system_prompt = str(kwargs.pop('system_prompt', '') or '').strip()
        if system_prompt:
            messages = [
                AIMessage(role=MessageRole.SYSTEM, content=system_prompt),
                AIMessage(role=MessageRole.USER, content=prompt),
            ]
            async for chunk in provider.stream_chat_completion(messages=messages, **kwargs):
                yield chunk
            return
        async for chunk in provider.stream_text_completion(prompt=prompt, **kwargs):
            yield chunk

    async def _chat_completion_for_role(self, role: str, *, messages: List[AIMessage], **kwargs):
        """调用指定角色的模型进行对话补全"""
        provider, settings = await self._get_role_provider_async(role)
        if settings.get('model'):
            kwargs.setdefault('model', settings['model'])
        if 'temperature' not in kwargs or 'top_p' not in kwargs:
            try:
                user_gen_config = await self._get_user_generation_config()
                kwargs.setdefault('temperature', user_gen_config['temperature'])
                kwargs.setdefault('top_p', user_gen_config.get('top_p', ai_config.top_p))
            except Exception:
                kwargs.setdefault('temperature', ai_config.temperature)
                kwargs.setdefault('top_p', ai_config.top_p)
        return await provider.chat_completion(messages=messages, **kwargs)
