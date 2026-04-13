"""
本地存储提供者
"""

import asyncio
import logging
import time
import shutil
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import uuid
from PIL import Image
import io

from .base import LocalStorageProvider
from ..models import (
    ImageInfo, ImageUploadRequest, ImageOperationResult, 
    ImageProvider, ImageSourceType, ImageFormat, ImageMetadata, ImageTag,
    ImageSearchResult
)

logger = logging.getLogger(__name__)


class FileSystemStorageProvider(LocalStorageProvider):
    """文件系统本地存储提供者"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(ImageProvider.LOCAL_STORAGE, config)
        
        # 存储配置
        self.base_dir = Path(config.get('base_dir', 'temp/images_cache/local_storage'))
        self.max_file_size = config.get('max_file_size_mb', 50) * 1024 * 1024  # MB to bytes
        self.supported_formats = config.get('supported_formats', ['jpg', 'jpeg', 'png', 'webp', 'gif'])
        
        # 创建存储目录
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Local storage provider initialized: {self.base_dir}")
    
    async def upload(self, request: ImageUploadRequest, file_data: bytes) -> ImageOperationResult:
        """上传图片到本地存储"""
        try:
            # 验证文件大小
            if len(file_data) > self.max_file_size:
                return ImageOperationResult(
                    success=False,
                    message=f"File size exceeds limit ({self.max_file_size / 1024 / 1024:.1f}MB)",
                    error_code="file_too_large"
                )
            
            # 验证文件格式
            file_ext = Path(request.filename).suffix.lower().lstrip('.')
            if file_ext not in self.supported_formats:
                return ImageOperationResult(
                    success=False,
                    message=f"Unsupported file format: {file_ext}",
                    error_code="unsupported_format"
                )
            
            # 生成唯一的文件名
            image_id = str(uuid.uuid4())
            timestamp = int(time.time())
            safe_filename = f"{timestamp}_{image_id}.{file_ext}"
            
            # 创建分类目录
            category_dir = self.base_dir / (request.category or 'uncategorized')
            category_dir.mkdir(parents=True, exist_ok=True)
            
            # 保存文件
            file_path = category_dir / safe_filename
            
            def _save():
                with open(file_path, 'wb') as f:
                    f.write(file_data)
            
            await asyncio.get_event_loop().run_in_executor(None, _save)
            
            # 创建图片信息
            image_info = await self._create_image_info(
                image_id, file_path, len(file_data), request, file_data
            )
            
            logger.info(f"Image uploaded successfully: {image_id}")
            
            return ImageOperationResult(
                success=True,
                message="Image uploaded successfully",
                image_info=image_info
            )
            
        except Exception as e:
            logger.error(f"Image upload failed: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Upload failed: {str(e)}",
                error_code="upload_error"
            )
    
    async def list_images(self, 
                         page: int = 1, 
                         per_page: int = 20,
                         category: Optional[str] = None,
                         tags: Optional[List[str]] = None) -> ImageSearchResult:
        """列出本地存储的图片"""
        try:
            # 获取所有图片文件
            all_images = []
            
            search_dirs = [self.base_dir / category] if category else [self.base_dir]
            
            for search_dir in search_dirs:
                if not search_dir.exists():
                    continue
                    
                for file_path in search_dir.rglob('*'):
                    if file_path.is_file() and file_path.suffix.lower().lstrip('.') in self.supported_formats:
                        try:
                            image_info = await self._create_image_info_from_file(file_path)
                            if image_info:
                                all_images.append(image_info)
                        except Exception as e:
                            logger.warning(f"Failed to process image {file_path}: {e}")
            
            # 按创建时间排序
            all_images.sort(key=lambda x: x.created_at, reverse=True)
            
            # 分页
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            page_images = all_images[start_idx:end_idx]
            
            return ImageSearchResult(
                images=page_images,
                total_count=len(all_images),
                page=page,
                per_page=per_page,
                provider=self.provider,
                query_time=time.time()
            )
            
        except Exception as e:
            logger.error(f"Failed to list images: {e}")
            return ImageSearchResult(
                images=[],
                total_count=0,
                page=page,
                per_page=per_page,
                provider=self.provider,
                query_time=time.time(),
                error=str(e)
            )
    
    async def get_image(self, image_id: str) -> Optional[ImageInfo]:
        """获取图片信息"""
        try:
            # 搜索所有子目录中的图片文件
            for file_path in self.base_dir.rglob('*'):
                if file_path.is_file() and image_id in file_path.name:
                    return await self._create_image_info_from_file(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get image {image_id}: {e}")
            return None
    
    async def delete_image(self, image_id: str) -> ImageOperationResult:
        """删除图片"""
        try:
            # 搜索并删除图片文件
            for file_path in self.base_dir.rglob('*'):
                if file_path.is_file() and image_id in file_path.name:
                    file_path.unlink()
                    logger.info(f"Image deleted: {image_id}")
                    return ImageOperationResult(
                        success=True,
                        message="Image deleted successfully"
                    )

            return ImageOperationResult(
                success=False,
                message="Image not found",
                error_code="not_found"
            )

        except Exception as e:
            logger.error(f"Failed to delete image {image_id}: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Delete failed: {str(e)}",
                error_code="delete_error"
            )

    async def update_image(self, image_id: str, updates: Dict[str, Any]) -> ImageOperationResult:
        """更新图片信息"""
        try:
            # 搜索图片文件
            target_file = None
            for file_path in self.base_dir.rglob('*'):
                if file_path.is_file() and image_id in file_path.name:
                    target_file = file_path
                    break

            if not target_file:
                return ImageOperationResult(
                    success=False,
                    message="Image not found",
                    error_code="not_found"
                )

            # 目前只支持移动文件到新分类
            if 'category' in updates:
                new_category = updates['category'] or 'uncategorized'
                new_category_dir = self.base_dir / new_category
                new_category_dir.mkdir(parents=True, exist_ok=True)

                new_file_path = new_category_dir / target_file.name
                shutil.move(str(target_file), str(new_file_path))

                logger.info(f"Image moved to new category: {image_id} -> {new_category}")

            return ImageOperationResult(
                success=True,
                message="Image updated successfully"
            )

        except Exception as e:
            logger.error(f"Failed to update image {image_id}: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Update failed: {str(e)}",
                error_code="update_error"
            )
    
    async def _create_image_info(self,
                          image_id: str,
                          file_path: Path,
                          file_size: int,
                          request: ImageUploadRequest,
                          file_data: Optional[bytes] = None) -> ImageInfo:
        """创建图片信息"""
        # 检测图片格式
        file_ext = file_path.suffix.lower().lstrip('.')
        format_map = {
            'jpg': ImageFormat.JPEG,
            'jpeg': ImageFormat.JPEG,
            'png': ImageFormat.PNG,
            'gif': ImageFormat.GIF,
            'webp': ImageFormat.WEBP,
            'bmp': ImageFormat.BMP,
            'tiff': ImageFormat.TIFF,
        }
        image_format = format_map.get(file_ext, ImageFormat.JPEG)

        # 获取图片尺寸
        width, height, color_mode, has_transparency = await self._get_image_dimensions(file_path, file_data)

        # 创建元数据
        metadata = ImageMetadata(
            width=width,
            height=height,
            format=image_format,
            file_size=file_size,
            color_mode=color_mode,
            has_transparency=has_transparency
        )
        
        # 创建标签
        tags = []
        for tag_name in request.tags:
            tags.append(ImageTag(
                name=tag_name,
                confidence=1.0,
                category="user_defined"
            ))
        
        # 根据请求中的source_type设置正确的来源类型
        actual_source_type = request.source_type or ImageSourceType.LOCAL_STORAGE

        # 根据来源类型设置相应的提供者
        # 对于网络搜索的图片，我们无法确定具体的提供者，所以使用通用的本地存储标识
        # 但保持正确的source_type来区分来源
        if actual_source_type == ImageSourceType.WEB_SEARCH:
            provider = ImageProvider.USER_UPLOAD  # 使用USER_UPLOAD来表示用户通过网络搜索获得的图片
        elif actual_source_type == ImageSourceType.AI_GENERATED:
            provider = ImageProvider.USER_UPLOAD  # 使用USER_UPLOAD来表示用户通过AI生成获得的图片
        else:
            provider = ImageProvider.LOCAL_STORAGE

        return ImageInfo(
            image_id=image_id,
            filename=file_path.name,
            title=request.title or file_path.stem,
            description=request.description or f"Uploaded image: {request.filename}",
            alt_text=request.title or file_path.stem,
            source_type=actual_source_type,
            provider=provider,
            original_url=request.original_url or "",
            local_path=str(file_path),
            metadata=metadata,
            tags=tags,
            keywords=request.tags,
            usage_count=0,
            created_at=time.time(),
            updated_at=time.time()
        )
    
    async def _get_image_dimensions(self, file_path: Path, file_data: Optional[bytes] = None) -> Tuple[int, int, str, bool]:
        """获取图片尺寸和其他属性"""
        try:
            if file_data:
                # 从内存数据读取
                def _get_dims():
                    with Image.open(io.BytesIO(file_data)) as img:
                        width, height = img.size
                        color_mode = img.mode
                        has_transparency = img.mode in ['RGBA', 'LA'] or 'transparency' in img.info
                        return width, height, color_mode, has_transparency

                return await asyncio.get_event_loop().run_in_executor(None, _get_dims)
            else:
                # 从文件读取
                def _get_dims():
                    with Image.open(file_path) as img:
                        width, height = img.size
                        color_mode = img.mode
                        has_transparency = img.mode in ['RGBA', 'LA'] or 'transparency' in img.info
                        return width, height, color_mode, has_transparency

                return await asyncio.get_event_loop().run_in_executor(None, _get_dims)

        except Exception as e:
            logger.warning(f"Failed to get image dimensions for {file_path}: {e}")
            return 0, 0, "RGB", False

    async def _create_image_info_from_file(self, file_path: Path) -> Optional[ImageInfo]:
        """从文件创建图片信息"""
        try:
            # 从文件名提取信息
            file_stat = file_path.stat()
            file_ext = file_path.suffix.lower().lstrip('.')
            
            # 生成图片ID（从文件名或路径生成）
            image_id = file_path.stem.split('_')[-1] if '_' in file_path.stem else file_path.stem
            
            # 检测图片格式
            format_map = {
                'jpg': ImageFormat.JPEG,
                'jpeg': ImageFormat.JPEG,
                'png': ImageFormat.PNG,
                'gif': ImageFormat.GIF,
                'webp': ImageFormat.WEBP,
                'bmp': ImageFormat.BMP,
                'tiff': ImageFormat.TIFF,
            }
            image_format = format_map.get(file_ext, ImageFormat.JPEG)

            # 获取图片尺寸
            width, height, color_mode, has_transparency = await self._get_image_dimensions(file_path)

            # 创建元数据
            metadata = ImageMetadata(
                width=width,
                height=height,
                format=image_format,
                file_size=file_stat.st_size,
                color_mode=color_mode,
                has_transparency=has_transparency
            )
            
            return ImageInfo(
                image_id=image_id,
                filename=file_path.name,
                title=file_path.stem,
                description=f"Local image: {file_path.name}",
                alt_text=file_path.stem,
                source_type=ImageSourceType.LOCAL_STORAGE,
                provider=ImageProvider.LOCAL_STORAGE,
                original_url="",
                local_path=str(file_path),
                metadata=metadata,
                tags=[],
                keywords=[],
                usage_count=0,
                created_at=file_stat.st_ctime,
                updated_at=file_stat.st_mtime
            )
            
        except Exception as e:
            logger.error(f"Failed to create image info from file {file_path}: {e}")
            return None
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            # 检查存储目录是否可写
            test_file = self.base_dir / '.health_check'
            test_file.write_text('test')
            test_file.unlink()
            
            # 统计存储信息
            total_files = len(list(self.base_dir.rglob('*')))
            
            return {
                'status': 'healthy',
                'message': 'Local storage accessible',
                'provider': self.provider.value,
                'base_dir': str(self.base_dir),
                'total_files': total_files
            }
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Storage check failed: {str(e)}',
                'provider': self.provider.value
            }
