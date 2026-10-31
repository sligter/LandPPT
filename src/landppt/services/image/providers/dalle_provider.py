"""
DALL-E 图片生成提供者
"""

import asyncio
import base64
import logging
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
import aiohttp
import json

from .base import ImageGenerationProvider
from ..models import (
    ImageInfo, ImageGenerationRequest, ImageOperationResult, 
    ImageProvider, ImageSourceType, ImageFormat, ImageMetadata, ImageTag
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'gpt-image-2.5-sunburst'
GPT_IMAGE_QUALITIES = {'low', 'medium', 'high', 'auto'}
# gpt-image-2.5-sunburst (and its dated snapshots) also accept xhigh and max.
GPT_IMAGE_EXTENDED_QUALITY_MODELS = ('gpt-image-2.5-sunburst',)
GPT_IMAGE_EXTENDED_QUALITIES = {'xhigh', 'max'}


def _gpt_image_qualities(model: str) -> set:
    """Quality values the given GPT Image model accepts."""
    if model.startswith(GPT_IMAGE_EXTENDED_QUALITY_MODELS):
        return GPT_IMAGE_QUALITIES | GPT_IMAGE_EXTENDED_QUALITIES
    return GPT_IMAGE_QUALITIES


class DalleProvider(ImageGenerationProvider):
    """DALL-E 图片生成提供者"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(ImageProvider.DALLE, config)
        
        # API配置
        self.api_key = config.get('api_key')
        self.api_base = config.get('api_base', 'https://api.openai.com/v1')
        self.model = config.get('model', DEFAULT_MODEL)
        self.default_size = config.get('default_size', '1024x1024')
        self.default_quality = config.get('default_quality', 'auto')
        self.default_style = config.get('default_style', 'vivid')
        
        # 速率限制
        self.rate_limit_requests = config.get('rate_limit_requests', 50)
        self.rate_limit_window = config.get('rate_limit_window', 60)
        
        # 请求历史（用于速率限制）
        self._request_history = []
        
        if not self.api_key:
            logger.warning("DALL-E API key not configured")
    
    async def generate(self, request: ImageGenerationRequest) -> ImageOperationResult:
        """生成图片"""
        if not self.api_key:
            return ImageOperationResult(
                success=False,
                message="DALL-E API key not configured",
                error_code="api_key_missing"
            )
        
        try:
            # 检查速率限制
            if not await self._check_rate_limit():
                return ImageOperationResult(
                    success=False,
                    message="Rate limit exceeded",
                    error_code="rate_limit_exceeded"
                )
            
            # 准备API请求
            api_request = self._prepare_api_request(request)
            
            # 调用DALL-E API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base}/images/generations",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=api_request,
                    timeout=aiohttp.ClientTimeout(total=120)  # 2分钟超时
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"DALL-E API error {response.status}: {error_text}")
                        return ImageOperationResult(
                            success=False,
                            message=f"DALL-E API error: {response.status}",
                            error_code="api_error"
                        )
                    
                    result_data = await response.json()
            
            # 处理API响应
            return await self._process_api_response(result_data, request)
            
        except asyncio.TimeoutError:
            logger.error("DALL-E API request timeout")
            return ImageOperationResult(
                success=False,
                message="Request timeout",
                error_code="timeout"
            )
        except Exception as e:
            logger.error(f"DALL-E generation failed: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Generation failed: {str(e)}",
                error_code="generation_error"
            )
    
    def _prepare_api_request(self, request: ImageGenerationRequest) -> Dict[str, Any]:
        """准备API请求"""
        # 将width和height转换为DALL-E期望的size格式
        size = f"{request.width}x{request.height}"

        api_request = {
            "model": self.model,
            "prompt": request.prompt,
            "n": 1,  # DALL-E 3只支持生成1张图片
            "size": size,
        }

        quality = request.quality or self.default_quality
        if self.model.startswith("dall-e"):
            api_request["quality"] = quality
            api_request["response_format"] = "url"
            # DALL-E 3支持style参数
            if self.model == "dall-e-3":
                api_request["style"] = request.style or self.default_style
        else:
            # GPT Image models reject response_format and style, return base64
            # data and only accept the qualities listed for the model.
            api_request["quality"] = quality if quality in _gpt_image_qualities(self.model) else "auto"

        return api_request
    
    async def _process_api_response(self, 
                                  response_data: Dict[str, Any], 
                                  request: ImageGenerationRequest) -> ImageOperationResult:
        """处理API响应"""
        try:
            if 'data' not in response_data or not response_data['data']:
                return ImageOperationResult(
                    success=False,
                    message="No image data in response",
                    error_code="no_data"
                )
            
            image_data = response_data['data'][0]
            image_url = image_data.get('url')
            image_b64 = image_data.get('b64_json')
            revised_prompt = image_data.get('revised_prompt', request.prompt)
            
            if image_b64:
                image_path, image_size = self._save_base64_image(image_b64, request)
            elif image_url:
                # 下载图片
                image_path, image_size = await self._download_image(image_url, request)
            else:
                return ImageOperationResult(
                    success=False,
                    message="No image URL in response",
                    error_code="no_url"
                )
            
            # 创建图片信息
            image_info = self._create_image_info(
                image_path, image_size, request, revised_prompt
            )
            
            return ImageOperationResult(
                success=True,
                message="Image generated successfully",
                image_info=image_info
            )
            
        except Exception as e:
            logger.error(f"Failed to process DALL-E response: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Failed to process response: {str(e)}",
                error_code="response_processing_error"
            )
    
    def _save_base64_image(self, image_b64: str, request: ImageGenerationRequest) -> tuple[Path, int]:
        """保存base64编码的图片"""
        timestamp = int(time.time())
        filename = f"dalle_{timestamp}_{hash(request.prompt) % 10000}.png"
        
        save_dir = Path("temp/images_cache/ai_generated/dalle")
        save_dir.mkdir(parents=True, exist_ok=True)
        image_path = save_dir / filename
        
        image_data = base64.b64decode(image_b64)
        with open(image_path, 'wb') as f:
            f.write(image_data)
        
        return image_path, len(image_data)
    
    async def _download_image(self, 
                            image_url: str, 
                            request: ImageGenerationRequest) -> tuple[Path, int]:
        """下载生成的图片"""
        # 生成文件名
        timestamp = int(time.time())
        filename = f"dalle_{timestamp}_{hash(request.prompt) % 10000}.png"
        
        # 创建保存路径
        save_dir = Path("temp/images_cache/ai_generated/dalle")
        save_dir.mkdir(parents=True, exist_ok=True)
        image_path = save_dir / filename
        
        # 下载图片
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download image: {response.status}")
                
                image_data = await response.read()
                
                # 保存图片
                with open(image_path, 'wb') as f:
                    f.write(image_data)
                
                return image_path, len(image_data)
    
    def _create_image_info(self, 
                          image_path: Path, 
                          image_size: int,
                          request: ImageGenerationRequest,
                          revised_prompt: str) -> ImageInfo:
        """创建图片信息"""
        # 生成图片ID
        image_id = f"dalle_{int(time.time())}_{hash(request.prompt) % 10000}"
        
        # 使用请求中的尺寸
        width, height = request.width, request.height
        
        # 创建元数据
        metadata = ImageMetadata(
            width=width,
            height=height,
            format=ImageFormat.PNG,
            file_size=image_size,
            color_mode="RGB",
            has_transparency=True
        )
        
        # 创建标签（基于提示词）
        tags = self._generate_tags_from_prompt(request.prompt)
        
        return ImageInfo(
            image_id=image_id,
            filename=image_path.name,
            title=f"AI Generated: {request.prompt[:50]}...",
            description=f"Generated by DALL-E with prompt: {revised_prompt}",
            alt_text=request.prompt,
            source_type=ImageSourceType.AI_GENERATED,
            provider=ImageProvider.DALLE,
            original_url="",
            local_path=str(image_path),
            metadata=metadata,
            tags=tags,
            keywords=self._extract_keywords_from_prompt(request.prompt),
            usage_count=0,
            created_at=time.time(),
            updated_at=time.time()
        )
    
    def _generate_tags_from_prompt(self, prompt: str) -> List[ImageTag]:
        """从提示词生成标签"""
        # 简单的关键词提取和标签生成
        keywords = prompt.lower().split()
        
        # 过滤常见词汇
        stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        keywords = [word for word in keywords if word not in stop_words and len(word) > 2]
        
        # 生成标签
        tags = []
        for i, keyword in enumerate(keywords[:10]):  # 最多10个标签
            confidence = max(0.5, 1.0 - i * 0.1)  # 递减的置信度
            tags.append(ImageTag(
                name=keyword,
                confidence=confidence,
                category="ai_generated"
            ))
        
        return tags
    
    def _extract_keywords_from_prompt(self, prompt: str) -> List[str]:
        """从提示词提取关键词"""
        # 简单的关键词提取
        words = prompt.lower().split()
        stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        keywords = [word for word in words if word not in stop_words and len(word) > 2]
        
        return keywords[:20]  # 最多20个关键词
    
    async def _check_rate_limit(self) -> bool:
        """检查速率限制"""
        current_time = time.time()
        
        # 清理过期的请求记录
        self._request_history = [
            req_time for req_time in self._request_history
            if current_time - req_time < self.rate_limit_window
        ]
        
        # 检查是否超过限制
        if len(self._request_history) >= self.rate_limit_requests:
            return False
        
        # 记录当前请求
        self._request_history.append(current_time)
        return True
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        if not self.api_key:
            return {
                'status': 'unhealthy',
                'message': 'API key not configured',
                'provider': self.provider.value
            }
        
        try:
            # 简单的API连通性检查
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.api_base}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    
                    if response.status == 200:
                        return {
                            'status': 'healthy',
                            'message': 'API accessible',
                            'provider': self.provider.value,
                            'model': self.model,
                            'rate_limit_remaining': self.rate_limit_requests - len(self._request_history)
                        }
                    else:
                        return {
                            'status': 'unhealthy',
                            'message': f'API error: {response.status}',
                            'provider': self.provider.value
                        }
        
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Health check failed: {str(e)}',
                'provider': self.provider.value
            }

    async def get_available_models(self) -> List[Dict[str, Any]]:
        """获取可用模型列表"""
        return [
            {
                'id': 'gpt-image-2.5-sunburst',
                'name': 'GPT Image 2.5 Sunburst',
                'description': 'OpenAI GPT Image generation model',
                'max_resolution': '1536x1024',
                'supported_styles': []
            },
            {
                'id': 'dall-e-3',
                'name': 'DALL-E 3',
                'description': 'Latest DALL-E model with improved quality and understanding',
                'max_resolution': '1792x1024',
                'supported_styles': ['natural', 'vivid']
            },
            {
                'id': 'dall-e-2',
                'name': 'DALL-E 2',
                'description': 'Previous generation DALL-E model',
                'max_resolution': '1024x1024',
                'supported_styles': ['natural']
            }
        ]
