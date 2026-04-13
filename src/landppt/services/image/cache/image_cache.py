"""
图片缓存管理器
"""

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import hashlib
from datetime import datetime, timedelta

from ..models import (
    ImageInfo, ImageCacheInfo, ImageSourceType, ImageProvider
)
from ....auth.request_context import current_user_id

logger = logging.getLogger(__name__)

class StorageQuotaExceededError(RuntimeError):
    """Raised when a user exceeds their image hosting storage quota."""

    def __init__(self, *, user_id: int, used_bytes: int, quota_bytes: int):
        super().__init__(
            f"Storage quota exceeded for user {user_id}: used={used_bytes}B quota={quota_bytes}B"
        )
        self.user_id = user_id
        self.used_bytes = used_bytes
        self.quota_bytes = quota_bytes


class ImageCacheManager:
    """图片缓存管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config

        # 缓存配置 - 移除过期和清理设置，图片永久有效
        self.cache_root = Path(config.get('base_dir', config.get('cache_root', 'temp/images_cache')))

        # 缓存大小和清理配置（虽然图片永久有效，但保留配置项）
        self.max_size_gb = config.get('max_size_gb', 100.0)
        self.cleanup_interval_hours = config.get('cleanup_interval_hours', 240000)

        # 缓存目录结构
        self.ai_generated_dir = self.cache_root / 'ai_generated'
        self.web_search_dir = self.cache_root / 'web_search'
        self.local_storage_dir = self.cache_root / 'local_storage'
        self.metadata_dir = self.cache_root / 'metadata'
        self.thumbnails_dir = self.cache_root / 'thumbnails'

        # 创建目录结构
        self._create_cache_directories()

        # 缓存索引
        self._cache_index: Dict[str, ImageCacheInfo] = {}
        self._load_cache_index()
    
    def _create_cache_directories(self):
        """创建缓存目录结构"""
        directories = [
            self.cache_root,
            self.ai_generated_dir,
            self.ai_generated_dir / 'dalle',
            self.ai_generated_dir / 'stable_diffusion',
            self.ai_generated_dir / 'siliconflow',
            self.ai_generated_dir / 'pollinations',
            self.web_search_dir,
            self.web_search_dir / 'unsplash',
            self.web_search_dir / 'pixabay',
            self.local_storage_dir,
            self.local_storage_dir / 'user_uploads',
            self.local_storage_dir / 'processed',
            self.metadata_dir,
            self.metadata_dir / 'references',  # 用于存储同一内容的多个引用
            self.thumbnails_dir
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, source_type: ImageSourceType, provider: ImageProvider) -> Path:
        """获取缓存路径"""
        if source_type == ImageSourceType.AI_GENERATED:
            if provider == ImageProvider.DALLE:
                return self.ai_generated_dir / 'dalle'
            elif provider == ImageProvider.STABLE_DIFFUSION:
                return self.ai_generated_dir / 'stable_diffusion'
            elif provider == ImageProvider.POLLINATIONS:
                return self.ai_generated_dir / 'pollinations'
            else:
                return self.ai_generated_dir
        
        elif source_type == ImageSourceType.WEB_SEARCH:
            if provider == ImageProvider.UNSPLASH:
                return self.web_search_dir / 'unsplash'
            elif provider == ImageProvider.PIXABAY:
                return self.web_search_dir / 'pixabay'
            else:
                return self.web_search_dir
        
        elif source_type == ImageSourceType.LOCAL_STORAGE:
            if provider == ImageProvider.USER_UPLOAD:
                return self.local_storage_dir / 'user_uploads'
            else:
                return self.local_storage_dir / 'processed'
        
        return self.cache_root
    
    def _generate_content_hash(self, image_data: bytes) -> str:
        """生成图片内容哈希值"""
        return hashlib.sha256(image_data).hexdigest()

    async def get_user_storage_usage_bytes(self, user_id: int, *, refresh_index: bool = True) -> int:
        """Return total cached bytes for a user scope (best-effort, file-exists checked)."""
        if refresh_index:
            await asyncio.get_event_loop().run_in_executor(None, self._load_cache_index)

        prefix = f"u{user_id}_"
        total_size = 0
        for cache_key, cache_info in list(self._cache_index.items()):
            if not cache_key.startswith(prefix):
                continue
            try:
                if Path(cache_info.file_path).exists():
                    total_size += int(cache_info.file_size or 0)
            except Exception:
                continue
        return total_size

    def _get_owner_user_id(self, image_info: ImageInfo) -> Optional[int]:
        owner = image_info.owner_user_id
        if owner is None:
            owner = current_user_id.get()
        return owner

    def _scoped_cache_key(self, owner_user_id: Optional[int], content_hash: str) -> str:
        scope = f"u{owner_user_id}" if owner_user_id is not None else "public"
        return f"{scope}_{content_hash}"

    def _generate_cache_key(self, image_info: ImageInfo, image_data: bytes = None) -> str:
        """生成缓存键 - 用户隔离 + 内容哈希。

        新的缓存键为 `{scope}_{sha256}`，其中 scope 为 `u{user_id}` 或 `public`。
        """
        owner_user_id = self._get_owner_user_id(image_info)
        if image_data:
            return self._scoped_cache_key(owner_user_id, self._generate_content_hash(image_data))

        # 如果 image_id 已经是缓存键，直接复用
        if image_info.image_id and image_info.image_id in self._cache_index:
            return image_info.image_id

        # 如果没有图片数据，使用图片ID作为临时键（这种情况应该避免）
        logger.warning(f"Generating cache key without image data for {image_info.image_id}")
        return hashlib.md5(f"temp_{image_info.image_id}".encode()).hexdigest()
    
    async def cache_image(self, image_info: ImageInfo, image_data: bytes) -> str:
        """缓存图片 - 基于内容去重"""
        try:
            # 绑定 owner（用于隔离图床数据）
            owner_user_id = self._get_owner_user_id(image_info)
            image_info.owner_user_id = owner_user_id
            if image_info.source_image_id is None:
                image_info.source_image_id = image_info.image_id

            # 生成用户隔离的缓存键
            content_hash = self._generate_content_hash(image_data)
            cache_key = self._scoped_cache_key(owner_user_id, content_hash)

            # 以 cache_key 作为对外暴露的 image_id，避免跨用户 ID 冲突
            image_info.image_id = cache_key

            # 检查是否已经缓存了相同内容的图片
            if cache_key in self._cache_index:
                existing_cache_info = self._cache_index[cache_key]
                existing_file_path = Path(existing_cache_info.file_path)

                # 如果文件存在，更新访问信息并保存新的图片元数据引用
                if existing_file_path.exists():
                    existing_cache_info.update_access()

                    # 更新图片信息中的本地路径
                    image_info.local_path = str(existing_file_path)

                    # 更新该 key 的元数据（幂等）
                    await self._save_image_metadata(cache_key, image_info)

                    asyncio.create_task(self._save_cache_index())
                    logger.debug(f"Image content already cached for user scope: {cache_key}")
                    return cache_key
                else:
                    # 如果文件不存在，从索引中移除
                    del self._cache_index[cache_key]

            # Enforce per-user storage quota (only when writing a new cache entry)
            quota_mb = self.config.get("user_quota_mb", 0) if isinstance(self.config, dict) else 0
            try:
                quota_mb = int(float(quota_mb))
            except Exception:
                quota_mb = 0

            if owner_user_id is not None and quota_mb > 0:
                quota_bytes = quota_mb * 1024 * 1024

                # Multi-worker processes: refresh filesystem index so new uploads/deletes are visible across workers.
                await asyncio.get_event_loop().run_in_executor(None, self._load_cache_index)

                used_bytes = await self.get_user_storage_usage_bytes(owner_user_id, refresh_index=False)
                if used_bytes + len(image_data) > quota_bytes:
                    raise StorageQuotaExceededError(
                        user_id=owner_user_id,
                        used_bytes=used_bytes,
                        quota_bytes=quota_bytes,
                    )

            # 选择存储路径 - 优先使用AI生成或网络搜索的路径
            if image_info.source_type.value in ['ai_generated', 'web_search']:
                cache_path = self._get_cache_path(image_info.source_type, image_info.provider)
            else:
                # 对于本地上传，使用通用路径
                cache_path = self.local_storage_dir / 'user_uploads'
            
            # 确定文件扩展名
            file_extension = Path(image_info.filename).suffix
            if not file_extension:
                file_extension = f".{image_info.metadata.format.value}"

            file_path = cache_path / f"{cache_key}{file_extension}"

            # 保存图片文件
            await asyncio.get_event_loop().run_in_executor(
                None, self._save_image_file, file_path, image_data
            )

            # 更新图片信息中的本地路径
            image_info.local_path = str(file_path)

            # 创建缓存信息 - 移除过期时间，图片永久有效
            cache_info = ImageCacheInfo(
                cache_key=cache_key,
                file_path=str(file_path),
                file_size=len(image_data),
                created_at=time.time(),
                last_accessed=time.time(),
                access_count=1,
                expires_at=None  # 永不过期
            )

            # 更新缓存索引
            self._cache_index[cache_key] = cache_info

            # 保存图片元数据
            await self._save_image_metadata(cache_key, image_info)

            # 异步保存缓存索引
            asyncio.create_task(self._save_cache_index())

            logger.debug(f"Image cached successfully: {cache_key}")
            return cache_key
            
        except Exception as e:
            logger.error(f"Failed to cache image {image_info.image_id}: {e}")
            raise
    
    def _save_image_file(self, file_path: Path, image_data: bytes):
        """保存图片文件"""
        with open(file_path, 'wb') as f:
            f.write(image_data)
    
    async def get_cached_image(self, cache_key: str) -> Optional[Tuple[ImageInfo, Path]]:
        """获取缓存的图片"""
        try:
            cache_info = self._cache_index.get(cache_key)
            if not cache_info:
                # Fallback: multi-worker processes may have stale in-memory index.
                # Discover the cached file on disk by cache_key and rebuild index entry on demand.
                cache_info = await self._discover_cache_info(cache_key)
                if not cache_info:
                    return None

            # 检查文件是否存在
            file_path = Path(cache_info.file_path)
            if not file_path.exists():
                await self.remove_from_cache(cache_key)
                return None

            # 加载图片元数据
            image_info = await self._load_image_metadata(cache_key)
            if not image_info:
                # 如果没有元数据文件，创建一个基础的ImageInfo对象
                # 这在PDF转换等场景下是正常的，只需要图片文件本身
                logger.debug(f"No metadata found for {cache_key}, creating basic ImageInfo")
                from ..models import ImageInfo, ImageMetadata, ImageFormat, ImageSourceType, ImageProvider

                # 从文件路径推断基本信息
                file_extension = file_path.suffix.lower()
                format_map = {
                    '.jpg': ImageFormat.JPEG,
                    '.jpeg': ImageFormat.JPEG,
                    '.png': ImageFormat.PNG,
                    '.webp': ImageFormat.WEBP,
                    '.gif': ImageFormat.GIF
                }

                image_format = format_map.get(file_extension, ImageFormat.JPEG)

                # 创建基础元数据
                metadata = ImageMetadata(
                    format=image_format,
                    width=0,  # 未知尺寸
                    height=0,
                    file_size=cache_info.file_size
                )

                # 创建基础ImageInfo
                image_info = ImageInfo(
                    image_id=cache_key,
                    filename=file_path.name,
                    local_path=str(file_path),
                    source_type=ImageSourceType.LOCAL_STORAGE,
                    provider=ImageProvider.LOCAL_STORAGE,
                    metadata=metadata
                )

            # 更新访问信息
            cache_info.update_access()
            asyncio.create_task(self._save_cache_index())

            logger.debug(f"Cache hit: {cache_key}")
            return image_info, file_path

        except Exception as e:
            logger.error(f"Failed to get cached image {cache_key}: {e}")
            return None

    async def _discover_cache_info(self, cache_key: str) -> Optional[ImageCacheInfo]:
        """Discover a cached image file on disk and rebuild a minimal cache index entry."""
        cache_dirs = [self.ai_generated_dir, self.web_search_dir, self.local_storage_dir]
        exts = [".webp", ".jpg", ".jpeg", ".png", ".gif"]

        def _find_file() -> Optional[Path]:
            for base_dir in cache_dirs:
                if not base_dir.exists():
                    continue
                for ext in exts:
                    matches = list(base_dir.glob(f"**/{cache_key}{ext}"))
                    if matches:
                        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                        return matches[0]
            return None

        try:
            found = await asyncio.get_event_loop().run_in_executor(None, _find_file)
            if not found or not found.exists():
                return None

            stat = found.stat()
            cache_info = ImageCacheInfo(
                cache_key=cache_key,
                file_path=str(found),
                file_size=stat.st_size,
                created_at=stat.st_ctime,
                last_accessed=stat.st_atime,
                access_count=1,
                expires_at=None,
            )
            self._cache_index[cache_key] = cache_info
            logger.debug(f"Discovered cache entry from filesystem: {cache_key} -> {found}")
            return cache_info
        except Exception as e:
            logger.warning(f"Failed to discover cache entry for {cache_key}: {e}")
            return None
    
    async def is_cached(self, image_info: ImageInfo, image_data: bytes = None) -> Optional[str]:
        """检查图片是否已缓存"""
        # 如果 image_id 本身就是缓存键，直接校验
        if image_info.image_id:
            cache_info = self._cache_index.get(image_info.image_id)
            if cache_info and Path(cache_info.file_path).exists():
                return image_info.image_id

        # 如果有图片数据，使用内容哈希检查
        if image_data:
            cache_key = self._generate_cache_key(image_info, image_data)
            cache_info = self._cache_index.get(cache_key)
            if cache_info:
                file_path = Path(cache_info.file_path)
                if file_path.exists():
                    return cache_key

        # 否则使用传统方式检查
        cache_key = self._generate_cache_key(image_info)
        cache_info = self._cache_index.get(cache_key)

        if cache_info:
            file_path = Path(cache_info.file_path)
            if file_path.exists():
                return cache_key

        return None
    
    async def remove_from_cache(self, cache_key: str) -> bool:
        """从缓存中移除图片"""
        try:
            cache_info = self._cache_index.get(cache_key)
            if not cache_info:
                return False
            
            # 删除图片文件
            file_path = Path(cache_info.file_path)
            if file_path.exists():
                await asyncio.get_event_loop().run_in_executor(None, file_path.unlink)
            
            # 删除缩略图
            thumbnail_path = self.thumbnails_dir / f"{cache_key}.jpg"
            if thumbnail_path.exists():
                await asyncio.get_event_loop().run_in_executor(None, thumbnail_path.unlink)
            
            # 删除元数据
            metadata_path = self.metadata_dir / f"{cache_key}.json"
            if metadata_path.exists():
                await asyncio.get_event_loop().run_in_executor(None, metadata_path.unlink)
            
            # 从索引中移除
            del self._cache_index[cache_key]
            
            # 保存索引
            await self._save_cache_index()
            
            logger.info(f"Removed from cache: {cache_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove from cache {cache_key}: {e}")
            return False
    
    async def _save_image_metadata(self, cache_key: str, image_info: ImageInfo):
        """保存图片元数据"""
        metadata_path = self.metadata_dir / f"{cache_key}.json"
        metadata = image_info.model_dump()

        def _save():
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

        await asyncio.get_event_loop().run_in_executor(None, _save)

    async def _save_image_metadata_reference(self, content_hash: str, image_info: ImageInfo):
        """保存图片元数据引用 - 为同一内容的图片保存多个引用"""
        # 创建引用文件名：content_hash_image_id.json
        reference_filename = f"{content_hash}_{image_info.image_id}.json"
        reference_path = self.metadata_dir / "references" / reference_filename

        # 确保引用目录存在
        reference_path.parent.mkdir(exist_ok=True)

        metadata = image_info.model_dump()

        def _save():
            with open(reference_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

        await asyncio.get_event_loop().run_in_executor(None, _save)
        logger.debug(f"Saved metadata reference: {reference_filename}")
    
    async def _load_image_metadata(self, cache_key: str) -> Optional[ImageInfo]:
        """加载图片元数据"""
        metadata_path = self.metadata_dir / f"{cache_key}.json"
        if not metadata_path.exists():
            # 降低日志级别，避免在PDF转换等场景下产生不必要的警告
            logger.debug(f"Metadata file not found: {metadata_path}")
            return None

        def _load():
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        try:
            metadata = await asyncio.get_event_loop().run_in_executor(None, _load)
            image_info = ImageInfo(**metadata)
            logger.debug(f"Successfully loaded metadata for cache key: {cache_key}")
            return image_info
        except Exception as e:
            logger.error(f"Failed to load image metadata {cache_key}: {e}")
            logger.error(f"Metadata file path: {metadata_path}")
            return None
    
    def _load_cache_index(self):
        """加载缓存索引 - 简化版本，直接扫描文件系统"""
        try:
            # 清空现有索引
            self._cache_index.clear()

            # 扫描所有缓存目录
            cache_dirs = [
                self.ai_generated_dir,
                self.web_search_dir,
                self.local_storage_dir
            ]

            total_files = 0
            for cache_dir in cache_dirs:
                if cache_dir.exists():
                    # 递归扫描所有图片文件
                    for file_path in cache_dir.rglob('*'):
                        if file_path.is_file() and file_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                            try:
                                # 使用文件名作为缓存键
                                cache_key = file_path.stem

                                # 创建缓存信息
                                stat = file_path.stat()
                                cache_info = ImageCacheInfo(
                                    cache_key=cache_key,
                                    file_path=str(file_path),
                                    file_size=stat.st_size,
                                    created_at=stat.st_ctime,
                                    last_accessed=stat.st_atime,
                                    access_count=1,
                                    expires_at=None  # 永不过期
                                )

                                self._cache_index[cache_key] = cache_info
                                total_files += 1

                            except Exception as e:
                                logger.warning(f"Failed to process cache file {file_path}: {e}")

            logger.debug(f"Loaded {total_files} cached images from filesystem")

        except Exception as e:
            logger.error(f"Failed to load cache index: {e}")
            # 确保索引不为空，即使出错也继续运行
            if not self._cache_index:
                self._cache_index = {}
    
    async def _save_cache_index(self):
        """保存缓存索引 - 简化版本，不再保存JSON文件"""
        # 不再保存索引文件，直接从文件系统读取
        logger.debug("Cache index save skipped - using filesystem-based indexing")
    
    # 移除清理任务相关方法，因为图片永久有效，无需清理
    
    async def get_cache_size(self) -> int:
        """获取缓存总大小"""
        total_size = 0
        for cache_info in self._cache_index.values():
            total_size += cache_info.file_size
        return total_size
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_entries = len(self._cache_index)
        total_size = await self.get_cache_size()
        
        # 按来源类型统计
        source_stats = {}
        for cache_info in self._cache_index.values():
            file_path = Path(cache_info.file_path)
            source_type = file_path.parent.parent.name if file_path.parent.parent.name in ['ai_generated', 'web_search', 'local_storage'] else 'unknown'
            
            if source_type not in source_stats:
                source_stats[source_type] = {'count': 0, 'size': 0}
            
            source_stats[source_type]['count'] += 1
            source_stats[source_type]['size'] += cache_info.file_size
        
        # 转换为API需要的格式
        categories = {}
        for source_type, stats in source_stats.items():
            categories[source_type] = stats['count']

        return {
            'total_entries': total_entries,
            'total_size_bytes': total_size,
            'total_size_mb': total_size / (1024 * 1024),
            'categories': categories,
            'source_stats': source_stats
        }
    
    async def clear_cache(self, source_type: Optional[ImageSourceType] = None) -> int:
        """清空缓存"""
        if source_type:
            # 清空特定来源的缓存
            keys_to_remove = []
            for cache_key, cache_info in self._cache_index.items():
                file_path = Path(cache_info.file_path)
                if source_type.value in str(file_path):
                    keys_to_remove.append(cache_key)

            for cache_key in keys_to_remove:
                await self.remove_from_cache(cache_key)

            return len(keys_to_remove)
        else:
            # 清空所有缓存
            keys_to_remove = list(self._cache_index.keys())

            # 先通过索引删除已知的文件
            for cache_key in keys_to_remove:
                await self.remove_from_cache(cache_key)

            # 然后清理可能存在的孤立文件
            await self._clear_orphaned_files()

            return len(keys_to_remove)

    async def _clear_orphaned_files(self):
        """清理孤立的缓存文件"""
        try:
            def _clear_directory_contents(directory: Path):
                """清理目录中的所有文件，但保留目录结构"""
                if not directory.exists():
                    return

                for item in directory.iterdir():
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        # 递归清理子目录
                        _clear_directory_contents(item)

            # 清理所有缓存目录中的文件
            directories_to_clear = [
                self.ai_generated_dir,
                self.web_search_dir,
                self.local_storage_dir,
                self.metadata_dir,
                self.thumbnails_dir
            ]

            for directory in directories_to_clear:
                await asyncio.get_event_loop().run_in_executor(None, _clear_directory_contents, directory)

            logger.info("Cleared all orphaned cache files")

        except Exception as e:
            logger.error(f"Failed to clear orphaned files: {e}")
            # 不抛出异常，因为主要的清理已经完成

    async def deduplicate_cache(self) -> int:
        """去重缓存中的重复图片"""
        try:
            content_hash_to_keys = {}
            keys_to_remove = []

            # 按内容哈希分组
            for cache_key, cache_info in self._cache_index.items():
                file_path = Path(cache_info.file_path)
                if not file_path.exists():
                    keys_to_remove.append(cache_key)
                    continue

                try:
                    # 读取文件内容并计算哈希
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    content_hash = hashlib.md5(content).hexdigest()

                    if content_hash not in content_hash_to_keys:
                        content_hash_to_keys[content_hash] = []
                    content_hash_to_keys[content_hash].append((cache_key, cache_info))

                except Exception as e:
                    logger.warning(f"Failed to read file for deduplication {file_path}: {e}")
                    keys_to_remove.append(cache_key)

            # 对于每个内容哈希，保留最新的一个，删除其他的
            for content_hash, key_info_list in content_hash_to_keys.items():
                if len(key_info_list) > 1:
                    # 按创建时间排序，保留最新的
                    key_info_list.sort(key=lambda x: x[1].created_at, reverse=True)

                    # 删除除了第一个（最新的）之外的所有条目
                    for cache_key, cache_info in key_info_list[1:]:
                        keys_to_remove.append(cache_key)
                        logger.info(f"Marking duplicate cache entry for removal: {cache_key}")

            # 删除重复和无效的条目
            for cache_key in keys_to_remove:
                await self.remove_from_cache(cache_key)

            logger.info(f"Removed {len(keys_to_remove)} duplicate/invalid cache entries")
            return len(keys_to_remove)

        except Exception as e:
            logger.error(f"Failed to deduplicate cache: {e}")
            return 0
