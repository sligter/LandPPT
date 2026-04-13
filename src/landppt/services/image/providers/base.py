"""
图片提供者抽象基类
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, AsyncGenerator
import logging
import asyncio
from pathlib import Path

from ..models import (
    ImageInfo, ImageSearchRequest, ImageGenerationRequest, 
    ImageUploadRequest, ImageSearchResult, ImageOperationResult,
    ImageProvider, ImageSourceType
)

logger = logging.getLogger(__name__)


class BaseImageProvider(ABC):
    """图片提供者抽象基类"""
    
    def __init__(self, provider: ImageProvider, config: Dict[str, Any]):
        self.provider = provider
        self.config = config
        self.enabled = config.get('enabled', True)
        self.rate_limit = config.get('rate_limit', 60)  # 每分钟请求限制
        self.timeout = config.get('timeout', 30)  # 请求超时时间
        
        # 请求计数器（简单的速率限制）
        self._request_count = 0
        self._last_reset = asyncio.get_event_loop().time()
    
    @property
    @abstractmethod
    def source_type(self) -> ImageSourceType:
        """返回图片来源类型"""
        pass
    
    @property
    @abstractmethod
    def supported_operations(self) -> List[str]:
        """返回支持的操作列表"""
        pass
    
    async def _check_rate_limit(self) -> bool:
        """检查速率限制"""
        current_time = asyncio.get_event_loop().time()
        
        # 每分钟重置计数器
        if current_time - self._last_reset > 60:
            self._request_count = 0
            self._last_reset = current_time
        
        if self._request_count >= self.rate_limit:
            logger.warning(f"Rate limit exceeded for {self.provider}")
            return False
        
        self._request_count += 1
        return True
    
    async def _validate_config(self) -> bool:
        """验证配置"""
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            config_valid = await self._validate_config()
            rate_limit_ok = await self._check_rate_limit()
            
            return {
                'provider': self.provider,
                'enabled': self.enabled,
                'config_valid': config_valid,
                'rate_limit_ok': rate_limit_ok,
                'status': 'healthy' if (self.enabled and config_valid) else 'unhealthy'
            }
        except Exception as e:
            logger.error(f"Health check failed for {self.provider}: {e}")
            return {
                'provider': self.provider,
                'enabled': False,
                'status': 'error',
                'error': str(e)
            }


class ImageSearchProvider(BaseImageProvider):
    """图片搜索提供者基类"""
    
    @property
    def source_type(self) -> ImageSourceType:
        return ImageSourceType.WEB_SEARCH
    
    @property
    def supported_operations(self) -> List[str]:
        return ['search', 'get_details', 'download']
    
    @abstractmethod
    async def search(self, request: ImageSearchRequest) -> ImageSearchResult:
        """搜索图片"""
        pass
    
    @abstractmethod
    async def get_image_details(self, image_id: str) -> Optional[ImageInfo]:
        """获取图片详细信息"""
        pass
    
    @abstractmethod
    async def download_image(self, image_info: ImageInfo, save_path: Path) -> ImageOperationResult:
        """下载图片到本地"""
        pass
    
    async def batch_search(self, requests: List[ImageSearchRequest]) -> List[ImageSearchResult]:
        """批量搜索图片"""
        results = []
        for request in requests:
            try:
                if not await self._check_rate_limit():
                    break
                result = await self.search(request)
                results.append(result)
                # 添加延迟避免过快请求
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Batch search failed for request {request.query}: {e}")
                # 创建空结果
                results.append(ImageSearchResult(
                    images=[], total_count=0, page=request.page, 
                    per_page=request.per_page, has_next=False, has_prev=False,
                    search_time=0.0
                ))
        return results


class ImageGenerationProvider(BaseImageProvider):
    """AI图片生成提供者基类"""
    
    @property
    def source_type(self) -> ImageSourceType:
        return ImageSourceType.AI_GENERATED
    
    @property
    def supported_operations(self) -> List[str]:
        return ['generate', 'get_models', 'get_styles']
    
    @abstractmethod
    async def generate(self, request: ImageGenerationRequest) -> ImageOperationResult:
        """生成图片"""
        pass
    
    @abstractmethod
    async def get_available_models(self) -> List[Dict[str, Any]]:
        """获取可用模型列表"""
        pass
    
    async def get_available_styles(self) -> List[Dict[str, Any]]:
        """获取可用样式列表"""
        return []
    
    async def batch_generate(self, requests: List[ImageGenerationRequest]) -> List[ImageOperationResult]:
        """批量生成图片"""
        results = []
        for request in requests:
            try:
                if not await self._check_rate_limit():
                    break
                result = await self.generate(request)
                results.append(result)
                # AI生成通常需要更长时间，添加更长延迟
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Batch generation failed for prompt {request.prompt}: {e}")
                results.append(ImageOperationResult(
                    success=False,
                    message=f"Generation failed: {str(e)}",
                    error_code="generation_error"
                ))
        return results


class LocalStorageProvider(BaseImageProvider):
    """本地存储提供者基类"""
    
    @property
    def source_type(self) -> ImageSourceType:
        return ImageSourceType.LOCAL_STORAGE
    
    @property
    def supported_operations(self) -> List[str]:
        return ['upload', 'list', 'get', 'delete', 'update']
    
    @abstractmethod
    async def upload(self, request: ImageUploadRequest, file_data: bytes) -> ImageOperationResult:
        """上传图片"""
        pass
    
    @abstractmethod
    async def list_images(self, 
                         page: int = 1, 
                         per_page: int = 20,
                         category: Optional[str] = None,
                         tags: Optional[List[str]] = None) -> ImageSearchResult:
        """列出图片"""
        pass
    
    @abstractmethod
    async def get_image(self, image_id: str) -> Optional[ImageInfo]:
        """获取图片信息"""
        pass
    
    @abstractmethod
    async def delete_image(self, image_id: str) -> ImageOperationResult:
        """删除图片"""
        pass
    
    @abstractmethod
    async def update_image(self, image_id: str, updates: Dict[str, Any]) -> ImageOperationResult:
        """更新图片信息"""
        pass
    
    async def search_local(self, query: str, **kwargs) -> ImageSearchResult:
        """在本地图片中搜索"""
        # 默认实现：通过标签和关键词搜索
        tags = kwargs.get('tags', [])
        if query:
            tags.append(query)
        
        return await self.list_images(
            page=kwargs.get('page', 1),
            per_page=kwargs.get('per_page', 20),
            tags=tags
        )


class ProviderRegistry:
    """提供者注册表"""
    
    def __init__(self):
        self._providers: Dict[ImageProvider, BaseImageProvider] = {}
        self._search_providers: List[ImageSearchProvider] = []
        self._generation_providers: List[ImageGenerationProvider] = []
        self._storage_providers: List[LocalStorageProvider] = []
    
    def register(self, provider: BaseImageProvider):
        """注册提供者"""
        # 检查是否已经注册了相同的提供者
        if provider.provider in self._providers:
            logger.debug(f"Provider {provider.provider} already registered, skipping")
            return

        self._providers[provider.provider] = provider

        if isinstance(provider, ImageSearchProvider):
            # 检查是否已经存在相同类型的搜索提供者
            existing = [p for p in self._search_providers if p.provider == provider.provider]
            if not existing:
                self._search_providers.append(provider)
        elif isinstance(provider, ImageGenerationProvider):
            # 检查是否已经存在相同类型的生成提供者
            existing = [p for p in self._generation_providers if p.provider == provider.provider]
            if not existing:
                self._generation_providers.append(provider)
        elif isinstance(provider, LocalStorageProvider):
            # 检查是否已经存在相同类型的存储提供者
            existing = [p for p in self._storage_providers if p.provider == provider.provider]
            if not existing:
                self._storage_providers.append(provider)
    
    def get_provider(self, provider: ImageProvider) -> Optional[BaseImageProvider]:
        """获取指定提供者"""
        return self._providers.get(provider)
    
    def get_search_providers(self, enabled_only: bool = True) -> List[ImageSearchProvider]:
        """获取搜索提供者"""
        if enabled_only:
            return [p for p in self._search_providers if p.enabled]
        return self._search_providers
    
    def get_generation_providers(self, enabled_only: bool = True) -> List[ImageGenerationProvider]:
        """获取生成提供者"""
        if enabled_only:
            return [p for p in self._generation_providers if p.enabled]
        return self._generation_providers
    
    def get_storage_providers(self, enabled_only: bool = True) -> List[LocalStorageProvider]:
        """获取存储提供者"""
        if enabled_only:
            return [p for p in self._storage_providers if p.enabled]
        return self._storage_providers
    
    def unregister(self, provider: ImageProvider):
        """注销提供者"""
        if provider in self._providers:
            old_provider = self._providers[provider]
            del self._providers[provider]
            
            # 从相应的列表中移除
            if isinstance(old_provider, ImageSearchProvider):
                self._search_providers = [p for p in self._search_providers if p.provider != provider]
            elif isinstance(old_provider, ImageGenerationProvider):
                self._generation_providers = [p for p in self._generation_providers if p.provider != provider]
            elif isinstance(old_provider, LocalStorageProvider):
                self._storage_providers = [p for p in self._storage_providers if p.provider != provider]
            
            logger.debug(f"Provider {provider} unregistered successfully")
        else:
            logger.debug(f"Provider {provider} was not registered")
    
    async def health_check_all(self) -> Dict[str, Any]:
        """检查所有提供者健康状态"""
        results = {}
        for provider_name, provider in self._providers.items():
            results[provider_name] = await provider.health_check()
        return results


# 全局提供者注册表
provider_registry = ProviderRegistry()
