"""
Gemini (Google) 图片生成提供者
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
import aiohttp
import json
import base64

from .base import ImageGenerationProvider
from ..models import (
    ImageInfo, ImageGenerationRequest, ImageOperationResult,
    ImageProvider, ImageSourceType, ImageFormat, ImageMetadata, ImageTag
)

logger = logging.getLogger(__name__)


class GeminiImageProvider(ImageGenerationProvider):
    """Gemini (Google) 图片生成提供者"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(ImageProvider.GEMINI, config)

        # API配置
        self.api_key = config.get('api_key')
        self.api_base = config.get('api_base', 'https://generativelanguage.googleapis.com/v1beta')
        self.model = config.get('model', 'gemini-nano-banana-2.1')
        self.default_size = config.get('default_size', '1024x1024')
        self.default_aspect = "1:1"
        self.default_image_size = "1K"  # 1K or 2K supported by Gemini image models

        # 速率限制
        self.rate_limit_requests = config.get('rate_limit_requests', 60)
        self.rate_limit_window = config.get('rate_limit_window', 60)

        # 请求历史（用于速率限制）
        self._request_history = []

        if not self.api_key:
            logger.warning("Gemini API key not configured for image generation")

    def _map_aspect_ratio(self, width: Optional[int], height: Optional[int]) -> str:
        """根据宽高映射到Gemini支持的aspectRatio字符串"""
        if not width or not height:
            return self.default_aspect

        ratio = width / height
        # 定义目标比例及阈值匹配
        targets = {
            "1:1": 1.0,
            "3:4": 0.75,
            "4:3": 1.3333,
            "9:16": 0.5625,
            "16:9": 1.7777,
        }
        best = "1:1"
        best_diff = 10.0
        for key, target in targets.items():
            diff = abs(ratio - target)
            if diff < best_diff:
                best = key
                best_diff = diff
        return best

    def _map_image_size(self, width: Optional[int], height: Optional[int]) -> str:
        """根据请求尺寸选择1K/2K（仅影响分辨率档位，不是精确像素）"""
        if not width or not height:
            return self.default_image_size
        longest = max(width, height)
        # 简单规则：>=1400 走 2K，否则 1K
        return "2K" if longest >= 1400 else "1K"

    async def generate(self, request: ImageGenerationRequest) -> ImageOperationResult:
        """生成图片"""
        if not self.api_key:
            return ImageOperationResult(
                success=False,
                message="Gemini API key not configured",
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

            # 调用Gemini API
            url = f"{self.api_base}/models/{self.model}:generateContent?key={self.api_key}"

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers={
                        "Content-Type": "application/json"
                    },
                    json=api_request,
                    timeout=aiohttp.ClientTimeout(total=180)  # 3分钟超时
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Gemini API error {response.status}: {error_text}")
                        return ImageOperationResult(
                            success=False,
                            message=f"Gemini API error: {response.status}",
                            error_code="api_error"
                        )

                    result_data = await response.json()

            # 处理API响应
            return await self._process_api_response(result_data, request)

        except asyncio.TimeoutError:
            logger.error("Gemini API request timeout")
            return ImageOperationResult(
                success=False,
                message="Request timeout",
                error_code="timeout"
            )
        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Generation failed: {str(e)}",
                error_code="generation_error"
            )

    def _prepare_api_request(self, request: ImageGenerationRequest) -> Dict[str, Any]:
        """准备API请求"""
        # Gemini图片生成使用generateContent API
        aspect_ratio = self._map_aspect_ratio(request.width, request.height)
        image_size = self._map_image_size(request.width, request.height)
        num_images = max(1, min(int(getattr(request, "num_images", 1)), 4))

        api_request = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": request.prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "aspectRatio": aspect_ratio,
                "imageSize": image_size,
                "numberOfImages": num_images,
                "personGeneration": "allow_adult"
            }
        }

        return api_request

    async def _process_api_response(self,
                                    response_data: Dict[str, Any],
                                    request: ImageGenerationRequest) -> ImageOperationResult:
        """处理API响应"""
        try:
            candidates = response_data.get('candidates', [])
            if not candidates:
                return ImageOperationResult(
                    success=False,
                    message="No candidates in response",
                    error_code="no_data"
                )

            # 查找图片数据
            image_data = None
            for candidate in candidates:
                content = candidate.get('content', {})
                parts = content.get('parts', [])
                for part in parts:
                    if 'inlineData' in part:
                        inline_data = part['inlineData']
                        if inline_data.get('mimeType', '').startswith('image/'):
                            image_data = inline_data.get('data')
                            break
                if image_data:
                    break

            if not image_data:
                return ImageOperationResult(
                    success=False,
                    message="No image data in response",
                    error_code="no_image"
                )

            # 解码并保存图片
            image_path, image_size = await self._save_image(image_data, request)

            # 创建图片信息
            image_info = self._create_image_info(
                image_path, image_size, request
            )

            return ImageOperationResult(
                success=True,
                message="Image generated successfully",
                image_info=image_info
            )

        except Exception as e:
            logger.error(f"Failed to process Gemini response: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Failed to process response: {str(e)}",
                error_code="response_processing_error"
            )

    async def _save_image(self,
                          image_data_base64: str,
                          request: ImageGenerationRequest) -> tuple[Path, int]:
        """保存生成的图片"""
        # 解码base64图片数据
        image_bytes = base64.b64decode(image_data_base64)

        # 生成文件名
        timestamp = int(time.time())
        filename = f"gemini_{timestamp}_{hash(request.prompt) % 10000}.png"

        # 创建保存路径
        save_dir = Path("temp/images_cache/ai_generated/gemini")
        save_dir.mkdir(parents=True, exist_ok=True)
        image_path = save_dir / filename

        # 保存图片
        with open(image_path, 'wb') as f:
            f.write(image_bytes)

        return image_path, len(image_bytes)

    def _create_image_info(self,
                           image_path: Path,
                           image_size: int,
                           request: ImageGenerationRequest) -> ImageInfo:
        """创建图片信息"""
        # 生成图片ID
        image_id = f"gemini_{int(time.time())}_{hash(request.prompt) % 10000}"

        # 使用请求中的尺寸，若缺失则根据aspectRatio提供大致占位
        width, height = request.width, request.height
        if not width or not height:
            ratio = self._map_aspect_ratio(width, height)
            # 默认1K分辨率下的估算像素，便于前端展示
            presets = {
                "16:9": (1600, 900),
                "9:16": (900, 1600),
                "4:3": (1333, 1000),
                "3:4": (1000, 1333),
                "1:1": (1024, 1024),
            }
            width, height = presets.get(ratio, (1024, 1024))

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
            description=f"Generated by Gemini with prompt: {request.prompt}",
            alt_text=request.prompt,
            source_type=ImageSourceType.AI_GENERATED,
            provider=ImageProvider.GEMINI,
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
        keywords = prompt.lower().split()
        stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        keywords = [word for word in keywords if word not in stop_words and len(word) > 2]

        tags = []
        for i, keyword in enumerate(keywords[:10]):
            confidence = max(0.5, 1.0 - i * 0.1)
            tags.append(ImageTag(
                name=keyword,
                confidence=confidence,
                category="ai_generated"
            ))

        return tags

    def _extract_keywords_from_prompt(self, prompt: str) -> List[str]:
        """从提示词提取关键词"""
        words = prompt.lower().split()
        stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        keywords = [word for word in words if word not in stop_words and len(word) > 2]
        return keywords[:20]

    async def _check_rate_limit(self) -> bool:
        """检查速率限制"""
        current_time = time.time()

        self._request_history = [
            req_time for req_time in self._request_history
            if current_time - req_time < self.rate_limit_window
        ]

        if len(self._request_history) >= self.rate_limit_requests:
            return False

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
            url = f"{self.api_base}/models?key={self.api_key}"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
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
                'id': 'gemini-nano-banana-2.1',
                'name': 'Gemini Nano Banana 2.1 (Image Generation)',
                'description': 'Google Gemini Nano Banana 2.1 model with image generation capability',
                'max_resolution': '1024x1024',
                'supported_styles': ['natural']
            }
        ]
