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
    from .runtime_support_service import RuntimeSupportService


class RuntimeImageService:
    """Image-service initialization helpers extracted from RuntimeSupportService."""

    def __init__(self, service: "RuntimeSupportService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    @property
    def _owner(self):
        return self._service._service

    def _initialize_image_service(self):
            """Initialize image service"""
            try:
                from ..image.config.image_config import get_image_config

                # 获取图片服务配置
                config_manager = get_image_config()

                # Prefer per-user (or system) configuration stored in the database over environment variables.
                # This aligns image provider keys with the settings UI.
                import asyncio

                try:
                    asyncio.get_running_loop()
                    loop_running = True
                except RuntimeError:
                    loop_running = False

                if loop_running:
                    async def _load_image_config_from_db():
                        try:
                            await config_manager.load_config_from_db_async(self.user_id)
                        except Exception as db_error:  # noqa: BLE001
                            logger.warning(
                                f"Failed to load image config from database (user_id={self.user_id}): {db_error}"
                            )

                    asyncio.create_task(_load_image_config_from_db())
                else:
                    try:
                        config_manager.load_config_from_db_sync(self.user_id)
                    except Exception as db_error:  # noqa: BLE001
                        logger.warning(f"Failed to load image config from database (user_id={self.user_id}): {db_error}")

                image_config = config_manager.get_config()

                # 更新缓存目录配置
                if self.cache_dirs:
                    image_config['cache']['base_dir'] = str(self.cache_dirs['ai_responses'] / 'images_cache')

                # 验证配置
                config_errors = config_manager.validate_config()
                if config_errors:
                    logger.warning(f"Image service configuration errors: {config_errors}")

                # 检查已配置的提供者
                if loop_running:
                    logger.info("Loading image provider config from database asynchronously...")
                else:
                    configured_providers = config_manager.get_configured_providers()
                    if configured_providers:
                        logger.info(f"Configured image providers: {configured_providers}")
                    else:
                        logger.warning(
                            "No image providers configured. Please set image provider API keys in the settings UI (per-user/system config)."
                        )

                self._owner.image_service = ImageService(image_config)
                image_service = self._owner.image_service

                # Ensure providers are registered using database configuration (per-user/system),
                # instead of relying on environment variables.
                try:
                    if loop_running:
                        asyncio.create_task(image_service.reload_providers_for_user(self.user_id))
                    else:
                        image_service.reload_providers_for_user_sync(self.user_id)
                except Exception as reload_error:  # noqa: BLE001
                    logger.warning(
                        f"Failed to reload image providers from database (user_id={self.user_id}): {reload_error}"
                    )
                # 异步初始化图片服务
                if loop_running:
                    # 如果在异步环境中，创建任务来初始化
                    asyncio.create_task(self._async_initialize_image_service())
                else:
                    # 如果不在异步环境中，同步初始化
                    asyncio.run(image_service.initialize())
                logger.info("Image service initialized successfully")

            except Exception as e:
                logger.warning(f"Failed to initialize image service: {e}")
                self._owner.image_service = None

    async def _async_initialize_image_service(self):
            """异步初始化图片服务"""
            try:
                if self.image_service and not self.image_service.initialized:
                    await self.image_service.initialize()
                    logger.debug("Image service async initialization completed")
            except Exception as e:
                logger.error(f"Failed to async initialize image service: {e}")
