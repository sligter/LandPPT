"""
图片服务主入口
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
import time
import hashlib

from .models import (
    ImageInfo, ImageSearchRequest, ImageGenerationRequest, ImageUploadRequest,
    ImageSearchResult, ImageOperationResult, ImageProcessingOptions,
    ImageSourceType, ImageProvider, ImageFormat
)
from .providers.base import provider_registry, ImageSearchProvider, ImageGenerationProvider, LocalStorageProvider
from .processors.image_processor import ImageProcessor
from .processors.webp_converter import convert_image_bytes_to_webp
from .cache.image_cache import ImageCacheManager, StorageQuotaExceededError
from .matching.image_matcher import ImageMatcher
from .adapters.ppt_prompt_adapter import PPTPromptAdapter, PPTSlideContext

logger = logging.getLogger(__name__)

from ...auth.request_context import current_user_id, USER_SCOPE_ALL


class ImageService:
    """图片服务主类"""

    _instance = None
    _class_initialized = False

    def __new__(cls, config: Dict[str, Any]):
        if cls._instance is None:
            cls._instance = super(ImageService, cls).__new__(cls)
        return cls._instance

    def __init__(self, config: Dict[str, Any]):
        # 避免重复初始化
        if self._class_initialized:
            return

        self.config = config

        # 初始化组件
        self.processor = ImageProcessor(config.get('processing', {}))
        self.cache_manager = ImageCacheManager(config.get('cache', {}))
        self.matcher = ImageMatcher(config.get('matching', {}))
        self.ppt_adapter = PPTPromptAdapter(config.get('ppt_adapter', {}))

        # 服务状态
        self.initialized = False

        # 搜索去重：防止重复搜索
        self._active_searches = {}  # query -> Future
        self._search_lock = asyncio.Lock()

        ImageService._class_initialized = True

    async def initialize(self):
        """初始化服务"""
        if self.initialized:
            return
        
        try:
            # 初始化提供者（这里需要在具体实现中注册）
            await self._initialize_providers()
            
            logger.debug("Image service initialized successfully")
            self.initialized = True
            
        except Exception as e:
            logger.error(f"Failed to initialize image service: {e}")
            raise
    
    async def _initialize_providers(self):
        """初始化图片提供者"""
        try:
            # 检查是否已经初始化过本地存储提供者
            existing_storage = provider_registry.get_storage_providers(enabled_only=False)
            if not existing_storage:
                # 初始化本地存储提供者（总是注册）
                from .providers.local_storage_provider import FileSystemStorageProvider

                storage_config = self.config.get('storage', {})
                storage_provider = FileSystemStorageProvider(storage_config)
                provider_registry.register(storage_provider)
                logger.debug("Local storage provider registered")
            else:
                logger.debug("Local storage provider already registered")

            # 初始化AI图片生成提供者
            from .providers.dalle_provider import DalleProvider
            from .providers.stable_diffusion_provider import StableDiffusionProvider
            from .providers.silicon_flow_provider import SiliconFlowProvider

            from .config.image_config import is_provider_configured

            # 注册DALL-E提供者
            if is_provider_configured('dalle'):
                dalle_config = self.config.get('dalle', {})
                dalle_provider = DalleProvider(dalle_config)
                provider_registry.register(dalle_provider)
                logger.debug("DALL-E provider registered")
            else:
                logger.debug("DALL-E API key not configured, skipping provider registration")

            # 注册Stable Diffusion提供者
            if is_provider_configured('stable_diffusion'):
                sd_config = self.config.get('stable_diffusion', {})
                sd_provider = StableDiffusionProvider(sd_config)
                provider_registry.register(sd_provider)
                logger.debug("Stable Diffusion provider registered")
            else:
                logger.debug("Stable Diffusion API key not configured, skipping provider registration")

            # 注册SiliconFlow提供者
            if is_provider_configured('siliconflow'):
                sf_config = self.config.get('siliconflow', {})
                sf_provider = SiliconFlowProvider(sf_config)
                provider_registry.register(sf_provider)
                logger.debug("SiliconFlow provider registered")
            else:
                logger.debug("SiliconFlow API key not configured, skipping provider registration")

            # 注册Gemini图片生成提供者
            if is_provider_configured('gemini'):
                from .providers.gemini_provider import GeminiImageProvider
                gemini_config = self.config.get('gemini', {})
                gemini_provider = GeminiImageProvider(gemini_config)
                provider_registry.register(gemini_provider)
                logger.debug("Gemini image provider registered")
            else:
                logger.debug("Gemini API key not configured, skipping provider registration")

            # 注册OpenAI图片生成提供者
            if is_provider_configured('openai_image'):
                from .providers.openai_image_provider import OpenAIImageProvider
                openai_image_config = self.config.get('openai_image', {})
                openai_image_provider = OpenAIImageProvider(openai_image_config)
                provider_registry.register(openai_image_provider)
                logger.debug("OpenAI image provider registered")
            else:
                logger.debug("OpenAI Image API key not configured, skipping provider registration")

            # 注册 Pollinations 图片生成提供者
            if is_provider_configured('pollinations'):
                from .providers.pollinations_provider import PollinationsProvider
                pollinations_config = self.config.get('pollinations', {})
                pollinations_provider = PollinationsProvider(pollinations_config)
                provider_registry.register(pollinations_provider)
                logger.debug("Pollinations image provider registered")
            else:
                logger.debug("Pollinations API key not configured, skipping provider registration")

            # 初始化网络搜索提供者
            from .config.image_config import ImageServiceConfig
            config_manager = ImageServiceConfig()

            # 注册Unsplash提供者
            if config_manager.should_enable_search_provider('unsplash'):
                unsplash_config = self.config.get('unsplash', {})
                from .providers.unsplash_provider import UnsplashSearchProvider
                unsplash_provider = UnsplashSearchProvider(unsplash_config)
                provider_registry.register(unsplash_provider)
                logger.debug("Unsplash search provider registered (default provider)")
            elif is_provider_configured('unsplash'):
                logger.debug("Unsplash API configured but not set as default network search provider")
            else:
                logger.debug("Unsplash API key not configured, skipping provider registration")

            # 注册Pixabay提供者
            if config_manager.should_enable_search_provider('pixabay'):
                pixabay_config = self.config.get('pixabay', {})
                from .providers.pixabay_provider import PixabaySearchProvider
                pixabay_provider = PixabaySearchProvider(pixabay_config)
                provider_registry.register(pixabay_provider)
                logger.debug("Pixabay search provider registered (default provider)")
            elif is_provider_configured('pixabay'):
                logger.debug("Pixabay API configured but not set as default network search provider")

            # 注册SearXNG提供者
            if config_manager.should_enable_search_provider('searxng'):
                searxng_config = self.config.get('searxng', {})
                from .providers.searxng_image_provider import SearXNGSearchProvider
                searxng_provider = SearXNGSearchProvider(searxng_config)
                provider_registry.register(searxng_provider)
                logger.debug("SearXNG search provider registered (default provider)")
            elif is_provider_configured('searxng'):
                logger.debug("SearXNG host configured but not set as default network search provider")

            # 统计已注册的提供者数量
            total_providers = (len(provider_registry.get_generation_providers()) +
                             len(provider_registry.get_search_providers()) +
                             len(provider_registry.get_storage_providers()))
            logger.debug(f"Initialized {total_providers} image providers")

        except Exception as e:
            logger.error(f"Failed to initialize image providers: {e}")

    async def reload_providers_for_user(self, user_id: Optional[int] = None):
        """
        重新加载用户特定的图片提供者配置。
        这会从数据库加载用户配置的API密钥，并重新创建相应的提供者。
        
        Args:
            user_id: 用户ID，如果为None则使用系统级配置
        """
        try:
            from .config.image_config import ImageServiceConfig, is_provider_configured
            
            # 创建新的配置实例并从数据库加载用户配置
            config_manager = ImageServiceConfig()
            await config_manager.load_config_from_db_async(user_id)
            
            # 更新实例的config
            self.config = config_manager.get_config()
            
            # 清除现有的AI生成提供者（保留存储提供者）
            from .providers.base import provider_registry
            
            # 获取当前的生成提供者列表副本并逐个移除
            existing_generation_providers = list(provider_registry.get_generation_providers())
            for provider in existing_generation_providers:
                try:
                    provider_registry.unregister(provider.provider)
                except Exception as e:
                    logger.warning(f"Failed to unregister provider {provider.provider}: {e}")
            
            # 重新注册AI图片生成提供者
            from .providers.dalle_provider import DalleProvider
            from .providers.stable_diffusion_provider import StableDiffusionProvider
            from .providers.silicon_flow_provider import SiliconFlowProvider
            
            # 注册DALL-E提供者
            dalle_config = self.config.get('dalle', {})
            if dalle_config.get('api_key'):
                dalle_provider = DalleProvider(dalle_config)
                provider_registry.register(dalle_provider)
                logger.debug(f"DALL-E provider reloaded for user {user_id}")
            
            # 注册Stable Diffusion提供者
            sd_config = self.config.get('stable_diffusion', {})
            if sd_config.get('api_key'):
                sd_provider = StableDiffusionProvider(sd_config)
                provider_registry.register(sd_provider)
                logger.debug(f"Stable Diffusion provider reloaded for user {user_id}")
            
            # 注册SiliconFlow提供者
            sf_config = self.config.get('siliconflow', {})
            sf_api_key = sf_config.get('api_key')
            logger.info(f"SiliconFlow config for user {user_id}: api_key={'***' + sf_api_key[-4:] if sf_api_key and len(sf_api_key) > 4 else '(empty)'}")
            if sf_api_key:
                sf_provider = SiliconFlowProvider(sf_config)
                provider_registry.register(sf_provider)
                logger.info(f"SiliconFlow provider registered for user {user_id}")
            
            # 注册Gemini图片生成提供者
            gemini_config = self.config.get('gemini', {})
            if gemini_config.get('api_key'):
                from .providers.gemini_provider import GeminiImageProvider
                gemini_provider = GeminiImageProvider(gemini_config)
                provider_registry.register(gemini_provider)
                logger.debug(f"Gemini image provider reloaded for user {user_id}")
            
            # 注册OpenAI图片生成提供者
            openai_image_config = self.config.get('openai_image', {})
            if openai_image_config.get('api_key'):
                from .providers.openai_image_provider import OpenAIImageProvider
                openai_image_provider = OpenAIImageProvider(openai_image_config)
                provider_registry.register(openai_image_provider)
                logger.debug(f"OpenAI image provider reloaded for user {user_id}")

            # 注册 Pollinations 图片生成提供者
            pollinations_config = self.config.get('pollinations', {})
            if pollinations_config.get('api_key'):
                from .providers.pollinations_provider import PollinationsProvider
                pollinations_provider = PollinationsProvider(pollinations_config)
                provider_registry.register(pollinations_provider)
                logger.debug(f"Pollinations image provider reloaded for user {user_id}")
             
            logger.info(f"Successfully reloaded image providers for user {user_id}")
             
        except Exception as e:
            logger.error(f"Failed to reload image providers for user {user_id}: {e}")

    def reload_providers_for_user_sync(self, user_id: Optional[int] = None):
        """Sync variant of provider reload that avoids async DB access."""
        try:
            from .config.image_config import ImageServiceConfig

            config_manager = ImageServiceConfig()
            config_manager.load_config_from_db_sync(user_id)

            self.config = config_manager.get_config()

            from .providers.base import provider_registry

            existing_generation_providers = list(provider_registry.get_generation_providers())
            for provider in existing_generation_providers:
                try:
                    provider_registry.unregister(provider.provider)
                except Exception as e:
                    logger.warning(f"Failed to unregister provider {provider.provider}: {e}")

            from .providers.dalle_provider import DalleProvider
            from .providers.stable_diffusion_provider import StableDiffusionProvider
            from .providers.silicon_flow_provider import SiliconFlowProvider

            dalle_config = self.config.get('dalle', {})
            if dalle_config.get('api_key'):
                dalle_provider = DalleProvider(dalle_config)
                provider_registry.register(dalle_provider)
                logger.debug(f"DALL-E provider reloaded for user {user_id}")

            sd_config = self.config.get('stable_diffusion', {})
            if sd_config.get('api_key'):
                sd_provider = StableDiffusionProvider(sd_config)
                provider_registry.register(sd_provider)
                logger.debug(f"Stable Diffusion provider reloaded for user {user_id}")

            sf_config = self.config.get('siliconflow', {})
            sf_api_key = sf_config.get('api_key')
            logger.info(
                "SiliconFlow config for user %s: api_key=%s",
                user_id,
                "***" + sf_api_key[-4:] if sf_api_key and len(sf_api_key) > 4 else "(empty)",
            )
            if sf_api_key:
                sf_provider = SiliconFlowProvider(sf_config)
                provider_registry.register(sf_provider)
                logger.info(f"SiliconFlow provider registered for user {user_id}")

            gemini_config = self.config.get('gemini', {})
            if gemini_config.get('api_key'):
                from .providers.gemini_provider import GeminiImageProvider

                gemini_provider = GeminiImageProvider(gemini_config)
                provider_registry.register(gemini_provider)
                logger.debug(f"Gemini image provider reloaded for user {user_id}")

            openai_image_config = self.config.get('openai_image', {})
            if openai_image_config.get('api_key'):
                from .providers.openai_image_provider import OpenAIImageProvider

                openai_image_provider = OpenAIImageProvider(openai_image_config)
                provider_registry.register(openai_image_provider)
                logger.debug(f"OpenAI image provider reloaded for user {user_id}")

            pollinations_config = self.config.get('pollinations', {})
            if pollinations_config.get('api_key'):
                from .providers.pollinations_provider import PollinationsProvider

                pollinations_provider = PollinationsProvider(pollinations_config)
                provider_registry.register(pollinations_provider)
                logger.debug(f"Pollinations image provider reloaded for user {user_id}")

            logger.info(f"Successfully reloaded image providers for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to reload image providers for user {user_id}: {e}")


    def _sort_providers_by_preference(self, providers: List[ImageSearchProvider]) -> List[ImageSearchProvider]:
        """根据默认配置对搜索提供者进行排序"""
        try:
            # 获取默认网络搜索提供商配置
            from ..config_service import get_config_service
            config_service = get_config_service()
            all_config = config_service.get_all_config()
            default_provider = all_config.get('default_network_search_provider', 'unsplash')

            # 将默认提供者排在前面
            preferred_providers = []
            other_providers = []

            for provider in providers:
                provider_name = provider.provider.value.lower()
                if provider_name == default_provider.lower():
                    preferred_providers.append(provider)
                else:
                    other_providers.append(provider)

            # 返回排序后的列表：默认提供者在前，其他提供者在后
            return preferred_providers + other_providers

        except Exception as e:
            logger.warning(f"Failed to sort providers by preference: {e}")
            return providers

    async def search_images(self, request: ImageSearchRequest) -> ImageSearchResult:
        """搜索图片"""
        if not self.initialized:
            await self.initialize()

        # 生成搜索键用于去重
        search_key = f"{request.query}_{request.page}_{request.per_page}"

        # 检查是否有相同的搜索正在进行
        async with self._search_lock:
            if search_key in self._active_searches:
                logger.debug(f"Reusing active search for: {request.query}")
                return await self._active_searches[search_key]

            # 创建新的搜索任务
            search_future = asyncio.create_task(self._perform_search(request))
            self._active_searches[search_key] = search_future

        try:
            result = await search_future
            return result
        finally:
            # 清理完成的搜索
            async with self._search_lock:
                self._active_searches.pop(search_key, None)

    async def _perform_search(self, request: ImageSearchRequest) -> ImageSearchResult:
        """执行实际的搜索操作"""
        start_time = time.time()
        all_images = []
        provider_results = {}

        try:
            # 获取启用的搜索提供者
            search_providers = provider_registry.get_search_providers()
            
            if not search_providers:
                return ImageSearchResult(
                    images=[], total_count=0, page=request.page,
                    per_page=request.per_page, has_next=False, has_prev=False,
                    search_time=time.time() - start_time
                )
            
            # 过滤提供者
            if request.preferred_providers:
                search_providers = [
                    p for p in search_providers
                    if p.provider in request.preferred_providers
                ]

            if request.excluded_providers:
                search_providers = [
                    p for p in search_providers
                    if p.provider not in request.excluded_providers
                ]

            # 如果没有指定优先提供者，根据默认配置排序
            if not request.preferred_providers:
                search_providers = self._sort_providers_by_preference(search_providers)
            
            # 并行搜索
            search_tasks = []
            for provider in search_providers:
                task = asyncio.create_task(self._search_with_provider(provider, request))
                search_tasks.append(task)
            
            # 等待所有搜索完成
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            # 处理结果
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Search failed for provider {search_providers[i].provider}: {result}")
                    continue
                
                if isinstance(result, ImageSearchResult):
                    all_images.extend(result.images)
                    provider_results[search_providers[i].provider.value] = len(result.images)
            
            # 使用智能匹配器排序和过滤结果
            if all_images:
                all_images = await self.matcher.rank_images(request.query, all_images)
            
            # 分页处理
            total_count = len(all_images)
            start_idx = (request.page - 1) * request.per_page
            end_idx = start_idx + request.per_page
            page_images = all_images[start_idx:end_idx]
            
            return ImageSearchResult(
                images=page_images,
                total_count=total_count,
                page=request.page,
                per_page=request.per_page,
                has_next=end_idx < total_count,
                has_prev=request.page > 1,
                search_time=time.time() - start_time,
                provider_results=provider_results
            )
            
        except Exception as e:
            logger.error(f"Image search failed: {e}")
            return ImageSearchResult(
                images=[], total_count=0, page=request.page,
                per_page=request.per_page, has_next=False, has_prev=False,
                search_time=time.time() - start_time
            )
    
    async def _search_with_provider(self, provider: ImageSearchProvider, request: ImageSearchRequest) -> ImageSearchResult:
        """使用特定提供者搜索"""
        try:
            result = await provider.search(request)

            # 不再自动缓存搜索到的图片，避免重复缓存
            # 缓存将在实际使用图片时进行

            return result

        except Exception as e:
            logger.error(f"Search failed for provider {provider.provider}: {e}")
            return ImageSearchResult(
                images=[], total_count=0, page=request.page,
                per_page=request.per_page, has_next=False, has_prev=False,
                search_time=0.0
            )
    
    async def _cache_image_from_provider(self, provider: ImageSearchProvider, image_info: ImageInfo):
        """从提供者缓存图片"""
        import uuid
        import time

        temp_path = None
        try:
            # 创建唯一的临时文件路径，避免冲突
            temp_filename = f"temp_{uuid.uuid4().hex}_{int(time.time())}"
            temp_path = Path(f"temp/{temp_filename}")

            # 确保temp目录存在
            temp_path.parent.mkdir(exist_ok=True)

            # 下载图片
            download_result = await provider.download_image(image_info, temp_path)
            if not download_result.success:
                return

            # 检查文件是否存在
            if not temp_path.exists():
                logger.warning(f"Downloaded file not found: {temp_path}")
                return

            # 读取图片数据
            try:
                with open(temp_path, 'rb') as f:
                    image_data = f.read()
            except Exception as read_error:
                logger.error(f"Failed to read downloaded file {temp_path}: {read_error}")
                return

            # 缓存图片
            await self.cache_manager.cache_image(image_info, image_data)
            logger.debug(f"Successfully cached image from provider: {image_info.image_id}")

        except Exception as e:
            logger.error(f"Failed to cache image {image_info.image_id}: {e}")
        finally:
            # 安全清理临时文件
            if temp_path and temp_path.exists():
                try:
                    # 等待一小段时间确保文件句柄被释放
                    await asyncio.sleep(0.1)
                    temp_path.unlink(missing_ok=True)
                    logger.debug(f"Cleaned up temp file: {temp_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp file {temp_path}: {cleanup_error}")
                    # 如果立即删除失败，尝试延迟删除
                    asyncio.create_task(self._delayed_cleanup(temp_path))

    async def _delayed_cleanup(self, file_path: Path, max_retries: int = 5):
        """延迟清理临时文件"""
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(1 + attempt)  # 递增等待时间
                if file_path.exists():
                    file_path.unlink()
                    logger.debug(f"Delayed cleanup successful for: {file_path}")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to cleanup temp file after {max_retries} attempts: {file_path}, error: {e}")
                else:
                    logger.debug(f"Cleanup attempt {attempt + 1} failed for {file_path}: {e}")
    
    async def generate_image(self, request: ImageGenerationRequest) -> ImageOperationResult:
        """生成图片"""
        if not self.initialized:
            await self.initialize()
        
        try:
            # 获取生成提供者
            generation_providers = provider_registry.get_generation_providers()
            
            # 选择提供者
            provider = None
            for p in generation_providers:
                if p.provider == request.provider:
                    provider = p
                    break
            
            if not provider:
                return ImageOperationResult(
                    success=False,
                    message=f"Generation provider {request.provider} not available",
                    error_code="provider_not_found"
                )
            
            # 生成图片
            result = await provider.generate(request)
            
            # 如果生成成功，缓存图片
            if result.success and result.image_info:
                original_path = Path(result.image_info.local_path) if result.image_info.local_path else None
                # 读取生成的图片
                with open(result.image_info.local_path, 'rb') as f:
                    image_data = f.read()

                # Convert to WebP to reduce storage usage (AI-generated images are often large PNGs)
                processing_cfg = self.config.get("processing", {}) or {}
                if bool(processing_cfg.get("upload_convert_to_webp", True)):
                    webp_quality = int(processing_cfg.get("upload_webp_quality", processing_cfg.get("default_quality", 80)))
                    webp_quality = max(1, min(100, webp_quality))
                    webp_method = int(processing_cfg.get("upload_webp_method", 6))
                    skip_animated = bool(processing_cfg.get("upload_skip_animated", True))
                    try:
                        converted_bytes, info = convert_image_bytes_to_webp(
                            image_data,
                            quality=webp_quality,
                            method=webp_method,
                            skip_if_webp=True,
                            skip_animated=skip_animated,
                        )
                        if info.converted:
                            result.image_info.filename = f"{Path(result.image_info.filename).stem}.webp"
                            result.image_info.metadata.format = ImageFormat.WEBP
                            result.image_info.metadata.file_size = len(converted_bytes)
                            result.image_info.metadata.width = info.width
                            result.image_info.metadata.height = info.height
                            result.image_info.metadata.color_mode = info.color_mode
                            result.image_info.metadata.has_transparency = info.has_transparency
                            image_data = converted_bytes
                    except Exception as e:
                        logger.warning(f"WebP conversion skipped for generated image {result.image_info.filename}: {e}")
                 
                # 缓存图片
                try:
                    cache_key = await self.cache_manager.cache_image(result.image_info, image_data)
                    logger.info(f"Generated image cached: {cache_key}")
                except StorageQuotaExceededError as e:
                    used_mb = e.used_bytes / (1024 * 1024)
                    quota_mb = e.quota_bytes / (1024 * 1024)
                    return ImageOperationResult(
                        success=False,
                        message=f"存储空间已满：已使用 {used_mb:.1f}MB，单用户上限 {quota_mb:.0f}MB。请先删除部分图片再生成。",
                        error_code="storage_quota_exceeded",
                    )

                # Remove original provider file (cache holds the persisted artifact)
                try:
                    if original_path and original_path.exists() and str(original_path) != result.image_info.local_path:
                        original_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.debug(f"Failed to remove original generated image file {original_path}: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Image generation failed: {str(e)}",
                error_code="generation_error"
            )
    
    async def upload_image(self, request: ImageUploadRequest, file_data: bytes) -> ImageOperationResult:
        """上传图片"""
        if not self.initialized:
            await self.initialize()
        
        try:
            # 获取本地存储提供者
            # Convert to WebP first to reduce storage usage for any uploaded images
            processing_cfg = self.config.get("processing", {}) or {}
            if bool(processing_cfg.get("upload_convert_to_webp", True)):
                webp_quality = int(processing_cfg.get("upload_webp_quality", processing_cfg.get("default_quality", 80)))
                webp_quality = max(1, min(100, webp_quality))
                webp_method = int(processing_cfg.get("upload_webp_method", 6))
                skip_animated = bool(processing_cfg.get("upload_skip_animated", True))
                try:
                    converted_bytes, info = convert_image_bytes_to_webp(
                        file_data,
                        quality=webp_quality,
                        method=webp_method,
                        skip_if_webp=True,
                        skip_animated=skip_animated,
                    )
                    if info.converted:
                        original_name = request.filename or "image"
                        new_filename = f"{Path(original_name).stem}.webp"
                        request = request.model_copy(
                            update={
                                "filename": new_filename,
                                "content_type": "image/webp",
                                "file_size": len(converted_bytes),
                            }
                        )
                        file_data = converted_bytes
                except Exception as e:
                    logger.warning(f"WebP conversion skipped for upload {request.filename}: {e}")

            # Enforce per-user quota before writing any staging files.
            user_id = current_user_id.get()
            quota_mb = (self.cache_manager.config or {}).get("user_quota_mb", 0)
            try:
                quota_mb = int(float(quota_mb))
            except Exception:
                quota_mb = 0

            if user_id is not None and user_id != USER_SCOPE_ALL and quota_mb > 0:
                quota_bytes = quota_mb * 1024 * 1024

                # Multi-worker processes: refresh filesystem index so new uploads/deletes are visible across workers.
                await asyncio.get_event_loop().run_in_executor(None, self.cache_manager._load_cache_index)

                content_hash = hashlib.sha256(file_data).hexdigest()
                cache_key = f"u{user_id}_{content_hash}"
                existing = self.cache_manager._cache_index.get(cache_key)
                if not (existing and Path(existing.file_path).exists()):
                    used_bytes = await self.cache_manager.get_user_storage_usage_bytes(user_id, refresh_index=False)
                    if used_bytes + len(file_data) > quota_bytes:
                        used_mb = used_bytes / (1024 * 1024)
                        return ImageOperationResult(
                            success=False,
                            message=f"存储空间已满：已使用 {used_mb:.1f}MB，单用户上限 {quota_mb}MB。请先删除部分图片再上传。",
                            error_code="storage_quota_exceeded",
                        )

            storage_providers = provider_registry.get_storage_providers()
             
            if not storage_providers:
                return ImageOperationResult(
                    success=False,
                    message="No storage provider available",
                    error_code="no_storage_provider"
                )
            
            # 使用第一个可用的存储提供者
            provider = storage_providers[0]
            staging_path: Optional[Path] = None
             
            # 上传图片
            result = await provider.upload(request, file_data)
            if result.success and result.image_info and result.image_info.local_path:
                try:
                    staging_path = Path(result.image_info.local_path)
                except Exception:
                    staging_path = None
             
            # 如果上传成功，缓存图片
            if result.success and result.image_info:
                try:
                    cache_key = await self.cache_manager.cache_image(result.image_info, file_data)
                    logger.info(f"Uploaded image cached: {cache_key}")
                except StorageQuotaExceededError as e:
                    used_mb = e.used_bytes / (1024 * 1024)
                    quota_mb = e.quota_bytes / (1024 * 1024)
                    return ImageOperationResult(
                        success=False,
                        message=f"存储空间已满：已使用 {used_mb:.1f}MB，单用户上限 {quota_mb:.0f}MB。请先删除部分图片再上传。",
                        error_code="storage_quota_exceeded",
                    )
                finally:
                    # Avoid keeping duplicated staging copies on disk (quota enforcement relies on cache usage).
                    try:
                        if staging_path and staging_path.exists() and staging_path.is_file():
                            staging_path.unlink(missing_ok=True)
                    except Exception:
                        pass
             
            return result
            
        except Exception as e:
            logger.error(f"Image upload failed: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Image upload failed: {str(e)}",
                error_code="upload_error"
            )
    
    async def get_image(self, image_id: str) -> Optional[ImageInfo]:
        """获取图片信息"""
        if not self.initialized:
            await self.initialize()
        
        try:
            effective_user_id = current_user_id.get()

            # Fast path: image_id is a cache_key (new format)
            cached_result = await self.cache_manager.get_cached_image(image_id)
            if cached_result:
                image_info, _ = cached_result
                if effective_user_id is None or image_info.owner_user_id == effective_user_id:
                    return image_info
                return None

            # Legacy path: scan cache for matching image_id
            for cache_key, cache_info in cache_entries:
                cached_result = await self.cache_manager.get_cached_image(cache_key)
                if cached_result:
                    image_info, _ = cached_result
                    if image_info.image_id == image_id and (effective_user_id is None or image_info.owner_user_id == effective_user_id):
                        return image_info
            
            # 如果缓存中没有，尝试从存储提供者获取
            storage_providers = provider_registry.get_storage_providers()
            for provider in storage_providers:
                image_info = await provider.get_image(image_id)
                if image_info:
                    return image_info
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get image {image_id}: {e}")
            return None
    
    async def process_image(self, image_id: str, options: ImageProcessingOptions) -> ImageOperationResult:
        """处理图片"""
        if not self.initialized:
            await self.initialize()
        
        try:
            # 获取原始图片
            image_info = await self.get_image(image_id)
            if not image_info:
                return ImageOperationResult(
                    success=False,
                    message=f"Image {image_id} not found",
                    error_code="image_not_found"
                )
            
            # 获取缓存的图片文件
            cache_key = await self.cache_manager.is_cached(image_info)
            if not cache_key:
                return ImageOperationResult(
                    success=False,
                    message=f"Image {image_id} not in cache",
                    error_code="image_not_cached"
                )
            
            cached_result = await self.cache_manager.get_cached_image(cache_key)
            if not cached_result:
                return ImageOperationResult(
                    success=False,
                    message=f"Failed to load cached image {image_id}",
                    error_code="cache_load_error"
                )
            
            _, input_path = cached_result
            
            # 生成输出路径
            output_path = input_path.parent / f"processed_{input_path.name}"
            
            # 处理图片
            result = await self.processor.process_image(input_path, output_path, options)
            
            # 如果处理成功，缓存处理后的图片
            if result.success and result.image_info:
                with open(output_path, 'rb') as f:
                    processed_data = f.read()
                
                try:
                    await self.cache_manager.cache_image(result.image_info, processed_data)
                except StorageQuotaExceededError:
                    return ImageOperationResult(
                        success=False,
                        message="存储空间已满：请先删除部分图片再处理。",
                        error_code="storage_quota_exceeded",
                    )
             
            return result
            
        except Exception as e:
            logger.error(f"Image processing failed for {image_id}: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Image processing failed: {str(e)}",
                error_code="processing_error"
            )
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        user_id = current_user_id.get()
        if user_id is None:
            return await self.cache_manager.get_cache_stats()

        # Multi-worker processes: refresh filesystem index so new uploads/deletes are visible across workers.
        await asyncio.get_event_loop().run_in_executor(None, self.cache_manager._load_cache_index)

        prefix = f"u{user_id}_"
        total_entries = 0
        total_size = 0
        source_stats: Dict[str, Dict[str, int]] = {}

        cache_entries = list(self.cache_manager._cache_index.items())
        for cache_key, cache_info in cache_entries:
            if not cache_key.startswith(prefix):
                continue
            if not Path(cache_info.file_path).exists():
                await self.cache_manager.remove_from_cache(cache_key)
                continue
            total_entries += 1
            total_size += cache_info.file_size

            file_path = Path(cache_info.file_path)
            source_type = file_path.parent.parent.name if file_path.parent.parent.name in ['ai_generated', 'web_search', 'local_storage'] else 'unknown'
            source_stats.setdefault(source_type, {'count': 0, 'size': 0})
            source_stats[source_type]['count'] += 1
            source_stats[source_type]['size'] += cache_info.file_size

        categories = {k: v['count'] for k, v in source_stats.items()}
        return {
            'total_entries': total_entries,
            'total_size_bytes': total_size,
            'total_size_mb': total_size / (1024 * 1024) if total_size else 0,
            'categories': categories,
            'source_stats': source_stats
        }

    async def list_cached_images(self,
                                page: int = 1,
                                per_page: int = 20,
                                category: Optional[str] = None,
                                search: Optional[str] = None,
                                sort: str = "created_desc") -> Dict[str, Any]:
        """列出缓存的图片"""
        if not self.initialized:
            await self.initialize()

        try:
            # 获取所有缓存的图片，包括引用
            all_images = []
            processed_content_hashes = set()

            # Multi-worker processes: refresh filesystem index so new uploads/deletes are visible across workers.
            await asyncio.get_event_loop().run_in_executor(None, self.cache_manager._load_cache_index)

            cache_entries = list(self.cache_manager._cache_index.items())
            logger.info(f"Processing {len(cache_entries)} cached images")
            effective_user_id = current_user_id.get()

            # 首先处理主要的缓存条目
            for cache_key, cache_info in cache_entries:
                try:
                    # 检查文件是否存在
                    file_path = Path(cache_info.file_path)
                    if not file_path.exists():
                        # Multi-worker processes: the in-memory index can be stale after clear/delete in another worker.
                        await self.cache_manager.remove_from_cache(cache_key)
                        continue

                    # 加载图片元数据
                    image_info = await self.cache_manager._load_image_metadata(cache_key)
                    if not image_info:
                        logger.warning(f"Failed to load metadata for cache key: {cache_key}")
                        continue

                    # 用户隔离：仅返回当前用户的图片（owner_user_id 必须匹配）
                    if effective_user_id is not None and image_info.owner_user_id != effective_user_id:
                        continue

                    # 分类筛选
                    if category and image_info.source_type.value != category:
                        continue

                    # 搜索筛选
                    if search:
                        if not self._matches_search_criteria(image_info, search):
                            continue

                    # 构建图片信息
                    from ..url_service import build_image_url
                    image_data = {
                        "id": image_info.image_id,  # 添加id字段
                        "image_id": image_info.image_id,
                        "title": image_info.title,
                        "description": image_info.description,
                        "filename": image_info.filename,
                        "url": build_image_url(
                            image_info.image_id,
                            width=image_info.metadata.width if image_info.metadata else None,
                            height=image_info.metadata.height if image_info.metadata else None,
                        ),  # 使用URL服务生成绝对URL
                        "file_size": cache_info.file_size,
                        "width": image_info.metadata.width if image_info.metadata else 0,  # 添加宽度
                        "height": image_info.metadata.height if image_info.metadata else 0,  # 添加高度
                        "source_type": image_info.source_type.value,
                        "source": image_info.source_type.value,  # 添加source字段用于分类
                        "category": image_info.source_type.value,  # 添加category字段用于分类
                        "provider": image_info.provider.value,
                        "alt_text": image_info.title or image_info.filename,  # 添加alt_text
                        "created_at": cache_info.created_at,
                        "last_accessed": cache_info.last_accessed,
                        "access_count": cache_info.access_count,
                        "tags": [tag.name if hasattr(tag, 'name') else str(tag) for tag in (image_info.tags or [])]
                    }

                    all_images.append(image_data)
                    processed_content_hashes.add(cache_key)
                    logger.debug(f"Successfully processed image: {image_info.image_id}")

                except Exception as e:
                    logger.warning(f"Failed to process cached image {cache_key}: {e}")
                    continue

            # 然后处理引用文件
            references_dir = self.cache_manager.metadata_dir / "references"
            if references_dir.exists():
                for reference_file in references_dir.glob("*.json"):
                    try:
                        # 从文件名提取内容哈希
                        filename = reference_file.stem
                        if '_' in filename:
                            content_hash = filename.split('_')[0]

                            # 如果这个内容哈希已经处理过，跳过
                            if content_hash in processed_content_hashes:
                                continue

                            # 加载引用的图片信息
                            import json
                            with open(reference_file, 'r', encoding='utf-8') as f:
                                metadata = json.load(f)

                            from .models import ImageInfo
                            image_info = ImageInfo(**metadata)

                            # 分类筛选
                            if category and image_info.source_type.value != category:
                                continue

                            # 搜索筛选
                            if search:
                                if not self._matches_search_criteria(image_info, search):
                                    continue

                            # 查找对应的缓存信息
                            cache_info = self.cache_manager._cache_index.get(content_hash)
                            if not cache_info:
                                continue

                            # 构建图片信息
                            from ..url_service import build_image_url
                            image_data = {
                                "id": image_info.image_id,  # 添加id字段
                                "image_id": image_info.image_id,
                                "title": image_info.title,
                                "description": image_info.description,
                                "filename": image_info.filename,
                                "url": build_image_url(
                                    image_info.image_id,
                                    width=image_info.metadata.width if image_info.metadata else None,
                                    height=image_info.metadata.height if image_info.metadata else None,
                                ),  # 使用URL服务生成绝对URL
                                "file_size": cache_info.file_size,
                                "width": image_info.metadata.width if image_info.metadata else 0,  # 添加宽度
                                "height": image_info.metadata.height if image_info.metadata else 0,  # 添加高度
                                "source_type": image_info.source_type.value,
                                "source": image_info.source_type.value,  # 添加source字段用于分类
                                "category": image_info.source_type.value,  # 添加category字段用于分类
                                "provider": image_info.provider.value,
                                "alt_text": image_info.title or image_info.filename,  # 添加alt_text
                                "created_at": cache_info.created_at,
                                "last_accessed": cache_info.last_accessed,
                                "access_count": cache_info.access_count,
                                "tags": [tag.name if hasattr(tag, 'name') else str(tag) for tag in (image_info.tags or [])]
                            }

                            all_images.append(image_data)

                    except Exception as e:
                        logger.warning(f"Failed to process reference file {reference_file}: {e}")
                        continue

            # 排序
            if sort == "created_desc":
                all_images.sort(key=lambda x: x["created_at"], reverse=True)
            elif sort == "created_asc":
                all_images.sort(key=lambda x: x["created_at"])
            elif sort == "accessed_desc":
                all_images.sort(key=lambda x: x["last_accessed"], reverse=True)
            elif sort == "size_desc":
                all_images.sort(key=lambda x: x["file_size"], reverse=True)
            elif sort == "size_asc":
                all_images.sort(key=lambda x: x["file_size"])

            # 分页
            total_count = len(all_images)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            page_images = all_images[start_idx:end_idx]

            return {
                "images": page_images,
                "total_count": total_count
            }

        except Exception as e:
            logger.error(f"Failed to list cached images: {e}")
            return {
                "images": [],
                "total_count": 0
            }

    def _matches_search_criteria(self, image_info: ImageInfo, search: str) -> bool:
        """检查图片是否匹配搜索条件"""
        if not search:
            return True

        # 将搜索词分割成多个关键词，支持空格分隔的多关键词搜索
        search_terms = [term.strip().lower() for term in search.split() if term.strip()]
        if not search_terms:
            return True

        # 构建所有可搜索的文本内容
        searchable_texts = []

        # 添加标题
        if image_info.title:
            searchable_texts.append(image_info.title.lower())

        # 添加描述
        if image_info.description:
            searchable_texts.append(image_info.description.lower())

        # 添加文件名（去掉扩展名）
        if image_info.filename:
            filename_without_ext = image_info.filename.rsplit('.', 1)[0]
            searchable_texts.append(filename_without_ext.lower())

        # 添加标签
        if image_info.tags:
            for tag in image_info.tags:
                tag_name = tag.name if hasattr(tag, 'name') else str(tag)
                if tag_name:
                    searchable_texts.append(tag_name.lower())

        # 合并所有文本
        combined_text = " ".join(searchable_texts)

        # 检查是否所有搜索词都能在文本中找到（支持部分匹配）
        for term in search_terms:
            if term not in combined_text:
                return False

        return True

    async def delete_image(self, image_id: str) -> bool:
        """删除图片"""
        if not self.initialized:
            await self.initialize()

        try:
            effective_user_id = current_user_id.get()

            # Prefer direct cache-key deletion (new format)
            if image_id in self.cache_manager._cache_index:
                image_info = await self.cache_manager._load_image_metadata(image_id)
                if not image_info:
                    return False
                if effective_user_id is not None and image_info.owner_user_id != effective_user_id:
                    return False
                await self.cache_manager.remove_from_cache(image_id)
                return True

            # Legacy path: scan by metadata image_id
            for cache_key in list(self.cache_manager._cache_index.keys()):
                try:
                    image_info = await self.cache_manager._load_image_metadata(cache_key)
                    if not image_info:
                        continue
                    if image_info.image_id != image_id:
                        continue
                    if effective_user_id is not None and image_info.owner_user_id != effective_user_id:
                        return False
                    await self.cache_manager.remove_from_cache(cache_key)
                    return True
                except Exception:
                    continue

            return False

        except Exception as e:
            logger.error(f"Failed to delete image {image_id}: {e}")
            return False

    async def get_thumbnail(self, image_id: str) -> Optional[str]:
        """获取图片缩略图路径"""
        if not self.initialized:
            await self.initialize()

        try:
            # 查找图片信息
            image_info = await self.get_image(image_id)
            if not image_info:
                return None

            # 生成缩略图路径
            thumbnail_dir = self.cache_manager.thumbnails_dir
            # Use cache-manager naming so cleanup works (remove_from_cache deletes `{cache_key}.jpg`)
            thumbnail_path = thumbnail_dir / f"{image_id}.jpg"

            # 如果缩略图已存在，直接返回
            if thumbnail_path.exists():
                return str(thumbnail_path)

            # 如果原图存在，生成缩略图
            if image_info.local_path and Path(image_info.local_path).exists():
                try:
                    from PIL import Image

                    # 创建缩略图目录
                    thumbnail_dir.mkdir(parents=True, exist_ok=True)

                    # 生成缩略图
                    with Image.open(image_info.local_path) as img:
                        # 如果是RGBA模式，转换为RGB以支持JPEG保存
                        if img.mode in ('RGBA', 'LA', 'P'):
                            # 创建白色背景
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            # 将原图粘贴到白色背景上
                            if img.mode == 'RGBA':
                                background.paste(img, mask=img.split()[-1])
                            else:
                                background.paste(img)
                            img = background

                        img.thumbnail((300, 200), Image.Resampling.LANCZOS)
                        img.save(str(thumbnail_path), "JPEG", quality=85)

                    return str(thumbnail_path)

                except ImportError:
                    logger.warning("PIL not available, cannot generate thumbnail")
                    return image_info.local_path
                except Exception as e:
                    logger.warning(f"Failed to generate thumbnail for {image_id}: {e}")
                    return image_info.local_path

            return None

        except Exception as e:
            logger.error(f"Failed to get thumbnail for {image_id}: {e}")
            return None
    
    async def cleanup_cache(self) -> Dict[str, int]:
        """清理缓存 - 由于图片永久有效，此方法仅返回统计信息"""
        return {
            'expired_removed': 0,
            'oversized_removed': 0,
            'total_removed': 0
        }

    async def clear_all_cache(self) -> int:
        """清空所有缓存"""
        if not self.initialized:
            await self.initialize()

        try:
            # 清空所有缓存
            deleted_count = await self.cache_manager.clear_cache()
            logger.info(f"Cleared all cache, deleted {deleted_count} images")
            return deleted_count
        except Exception as e:
            logger.error(f"Failed to clear all cache: {e}")
            raise

    async def clear_user_cache(self, user_id: Optional[int] = None) -> int:
        """清空指定用户作用域下的缓存图片。"""
        if not self.initialized:
            await self.initialize()

        effective_user_id = current_user_id.get() if user_id is None else user_id
        if effective_user_id is None or effective_user_id == USER_SCOPE_ALL:
            return await self.clear_all_cache()

        try:
            # Multi-worker processes: refresh filesystem index so new uploads/deletes are visible across workers.
            await asyncio.get_event_loop().run_in_executor(None, self.cache_manager._load_cache_index)

            deleted_count = 0
            prefix = f"u{effective_user_id}_"
            cache_keys = list(self.cache_manager._cache_index.keys())
            for cache_key in cache_keys:
                if not cache_key.startswith(prefix):
                    continue
                await self.cache_manager.remove_from_cache(cache_key)
                deleted_count += 1

            logger.info(
                "Cleared user-scoped image cache for user %s, deleted %s images",
                effective_user_id,
                deleted_count,
            )
            return deleted_count
        except Exception as e:
            logger.error(f"Failed to clear user cache for user {effective_user_id}: {e}")
            raise

    async def deduplicate_cache(self) -> Dict[str, int]:
        """去重缓存中的重复图片"""
        if not self.initialized:
            await self.initialize()

        try:
            removed_count = await self.cache_manager.deduplicate_cache()
            return {
                'duplicates_removed': removed_count,
                'total_removed': removed_count
            }
        except Exception as e:
            logger.error(f"Failed to deduplicate cache: {e}")
            return {
                'duplicates_removed': 0,
                'total_removed': 0
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        provider_health = await provider_registry.health_check_all()
        cache_stats = await self.get_cache_stats()
        
        return {
            'service_initialized': self.initialized,
            'providers': provider_health,
            'cache': cache_stats,
            'status': 'healthy' if self.initialized else 'not_initialized'
        }

    # PPT集成相关方法
    async def generate_ppt_slide_image(self,
                                     slide_context: PPTSlideContext,
                                     provider: ImageProvider = ImageProvider.DALLE) -> ImageOperationResult:
        """为PPT幻灯片生成图片"""
        if not self.initialized:
            await self.initialize()

        try:
            # 使用PPT适配器创建生成请求
            generation_request = await self.ppt_adapter.create_generation_request(
                slide_context, provider
            )

            # 生成图片
            result = await self.generate_image(generation_request)

            if result.success:
                logger.info(f"Generated PPT slide image for slide {slide_context.page_number}")

            return result

        except Exception as e:
            logger.error(f"Failed to generate PPT slide image: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Failed to generate slide image: {str(e)}",
                error_code="ppt_generation_error"
            )

    async def suggest_images_for_ppt_slide(self,
                                         slide_context: PPTSlideContext,
                                         max_suggestions: int = 5) -> List[ImageInfo]:
        """为PPT幻灯片推荐图片"""
        if not self.initialized:
            await self.initialize()

        try:
            # 构建搜索查询
            search_query = f"{slide_context.title} {slide_context.topic} {slide_context.scenario}"

            # 搜索相关图片
            search_request = ImageSearchRequest(
                query=search_query,
                per_page=max_suggestions * 2,  # 搜索更多以便筛选
                filters={
                    'scenario': slide_context.scenario,
                    'language': slide_context.language
                }
            )

            search_result = await self.search_images(search_request)

            # 使用智能匹配器进一步筛选和排序
            if search_result.images:
                content_text = f"{slide_context.title}\n{slide_context.content}"
                suggested_images = await self.matcher.suggest_images_for_content(
                    content_text, search_result.images, max_suggestions
                )
                return suggested_images

            return []

        except Exception as e:
            logger.error(f"Failed to suggest images for PPT slide: {e}")
            return []

    async def create_ppt_image_prompt(self, slide_context: PPTSlideContext) -> str:
        """为PPT幻灯片创建图片生成提示词"""
        return await self.ppt_adapter.generate_image_prompt(slide_context)


# 全局图片服务实例
_global_image_service = None


def get_image_service() -> ImageService:
    """获取全局图片服务实例"""
    global _global_image_service
    if _global_image_service is None:
        from .config.image_config import get_image_config
        config_manager = get_image_config()
        config = config_manager.get_config()
        _global_image_service = ImageService(config)
    return _global_image_service
