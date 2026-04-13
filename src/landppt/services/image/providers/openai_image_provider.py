"""
OpenAI 图片生成提供者 (GPT-Image / gpt-image-1)
支持通过OpenAI兼容API进行图片生成
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


class OpenAIImageProvider(ImageGenerationProvider):
    """OpenAI 图片生成提供者 (支持自定义API端点)"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(ImageProvider.OPENAI_IMAGE, config)

        # API配置
        self.api_key = config.get('api_key')
        self.api_base = config.get('api_base', 'https://api.openai.com/v1')
        self.model = config.get('model', 'gpt-image-1')
        self.default_size = config.get('default_size', '1024x1024')
        self.default_quality = config.get('default_quality', 'auto')

        # 速率限制
        self.rate_limit_requests = config.get('rate_limit_requests', 50)
        self.rate_limit_window = config.get('rate_limit_window', 60)

        # 请求历史（用于速率限制）
        self._request_history = []

        if not self.api_key:
            logger.warning("OpenAI Image API key not configured")

    def _is_chat_completions_endpoint(self) -> bool:
        api_base = (self.api_base or "").lower().rstrip("/")
        return "/chat/completions" in api_base

    async def generate(self, request: ImageGenerationRequest) -> ImageOperationResult:
        """生成图片"""
        if not self.api_key:
            return ImageOperationResult(
                success=False,
                message="OpenAI Image API key not configured",
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

            if self._is_chat_completions_endpoint():
                return await self._generate_via_chat_completions(request)

            return await self._generate_via_images_api(request)

        except asyncio.TimeoutError:
            logger.error("OpenAI Image API request timeout")
            return ImageOperationResult(
                success=False,
                message="Request timeout",
                error_code="timeout"
            )
        except Exception as e:
            logger.error(f"OpenAI Image generation failed: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Generation failed: {str(e)}",
                error_code="generation_error"
            )

    async def _generate_via_images_api(self, request: ImageGenerationRequest) -> ImageOperationResult:
        api_request = self._prepare_api_request(request)
        url = f"{self.api_base.rstrip('/')}/images/generations"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=api_request,
                timeout=aiohttp.ClientTimeout(total=180)
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"OpenAI Image API error {response.status}: {error_text}")
                    return ImageOperationResult(
                        success=False,
                        message=f"OpenAI Image API error: {response.status}",
                        error_code="api_error"
                    )

                result_data = await response.json()

        return await self._process_api_response(result_data, request)

    async def _generate_via_chat_completions(self, request: ImageGenerationRequest) -> ImageOperationResult:
        url = self.api_base.rstrip("/")
        payload = {
            "model": self.model,
            "temperature": 0.7,
            "messages": [
                {
                    "role": "user",
                    "content": request.prompt
                }
            ],
            "stream": True,
            "stream_options": {"include_usage": True}
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=180)
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"OpenAI chat completions error {response.status}: {error_text}")
                    return ImageOperationResult(
                        success=False,
                        message=f"OpenAI chat completions error: {response.status}",
                        error_code="api_error"
                    )

                content_type = (response.headers.get("Content-Type") or "").lower()
                if "text/event-stream" in content_type:
                    image_payload = await self._extract_image_from_stream(response)
                else:
                    result_data = await response.json()
                    image_payload = self._extract_image_data_from_chat_response(result_data)

        if not image_payload:
            return ImageOperationResult(
                success=False,
                message="No image data in response",
                error_code="no_data"
            )

        image_path, image_size = await self._save_image_from_payload(image_payload, request)
        image_info = self._create_image_info(image_path, image_size, request)

        return ImageOperationResult(
            success=True,
            message="Image generated successfully",
            image_info=image_info
        )

    async def _extract_image_from_stream(self, response: aiohttp.ClientResponse) -> Optional[str]:
        buffer = ""
        async for chunk in response.content.iter_chunked(1024):
            buffer += chunk.decode("utf-8", errors="ignore")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return None
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                image_payload = self._extract_image_data_from_chat_response(payload)
                if image_payload:
                    return image_payload
        return None

    def _extract_image_data_from_chat_response(self, response_data: Dict[str, Any]) -> Optional[str]:
        choices = response_data.get("choices") or []
        for choice in choices:
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}
            for container in (delta, message):
                image_payload = self._extract_image_from_container(container)
                if image_payload:
                    return image_payload
        return None

    def _extract_image_from_container(self, container: Dict[str, Any]) -> Optional[str]:
        images = container.get("images")
        image_payload = self._extract_image_from_list(images)
        if image_payload:
            return image_payload
        content = container.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "image_url" in item:
                    url = item["image_url"].get("url")
                    if url:
                        return url
        return None

    def _extract_image_from_list(self, images: Any) -> Optional[str]:
        if not isinstance(images, list):
            return None
        for image in images:
            payload = self._extract_image_payload(image)
            if payload:
                return payload
        return None

    def _extract_image_payload(self, image: Any) -> Optional[str]:
        if isinstance(image, str):
            return image
        if not isinstance(image, dict):
            return None
        if "b64_json" in image:
            return image["b64_json"]
        if "image_url" in image:
            image_url = image.get("image_url") or {}
            if isinstance(image_url, dict):
                url = image_url.get("url")
                if url:
                    return url
        if "url" in image:
            return image.get("url")
        return None

    def _extract_base64_from_data_url(self, value: str) -> Optional[str]:
        if not value.startswith("data:"):
            return None
        comma_index = value.find(",")
        if comma_index == -1:
            return None
        return value[comma_index + 1:]

    async def _save_image_from_payload(
        self,
        payload: str,
        request: ImageGenerationRequest
    ) -> tuple[Path, int]:
        payload = str(payload)
        base64_data = self._extract_base64_from_data_url(payload)
        if base64_data:
            return await self._save_image_from_base64(base64_data, request)
        if payload.startswith("http://") or payload.startswith("https://"):
            return await self._download_image(payload, request)
        return await self._save_image_from_base64(payload, request)

    def _prepare_api_request(self, request: ImageGenerationRequest) -> Dict[str, Any]:
        """准备API请求"""
        # 将width和height转换为size格式
        size = f"{request.width}x{request.height}"

        api_request = {
            "model": self.model,
            "prompt": request.prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json"  # 使用base64格式便于保存
        }

        # 添加质量参数
        if request.quality:
            api_request["quality"] = request.quality
        elif self.default_quality:
            api_request["quality"] = self.default_quality

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

            # 支持两种响应格式：b64_json 和 url
            if 'b64_json' in image_data:
                image_base64 = image_data['b64_json']
                image_path, image_size = await self._save_image_from_base64(image_base64, request)
            elif 'url' in image_data:
                image_url = image_data['url']
                image_path, image_size = await self._download_image(image_url, request)
            else:
                return ImageOperationResult(
                    success=False,
                    message="No image URL or base64 data in response",
                    error_code="no_image"
                )

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
            logger.error(f"Failed to process OpenAI Image response: {e}")
            return ImageOperationResult(
                success=False,
                message=f"Failed to process response: {str(e)}",
                error_code="response_processing_error"
            )

    async def _save_image_from_base64(self,
                                       image_base64: str,
                                       request: ImageGenerationRequest) -> tuple[Path, int]:
        """从base64保存图片"""
        # 解码base64图片数据
        image_bytes = base64.b64decode(image_base64)

        # 生成文件名
        timestamp = int(time.time())
        filename = f"openai_image_{timestamp}_{hash(request.prompt) % 10000}.png"

        # 创建保存路径
        save_dir = Path("temp/images_cache/ai_generated/openai_image")
        save_dir.mkdir(parents=True, exist_ok=True)
        image_path = save_dir / filename

        # 保存图片
        with open(image_path, 'wb') as f:
            f.write(image_bytes)

        return image_path, len(image_bytes)

    async def _download_image(self,
                              image_url: str,
                              request: ImageGenerationRequest) -> tuple[Path, int]:
        """下载生成的图片"""
        # 生成文件名
        timestamp = int(time.time())
        filename = f"openai_image_{timestamp}_{hash(request.prompt) % 10000}.png"

        # 创建保存路径
        save_dir = Path("temp/images_cache/ai_generated/openai_image")
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
                           request: ImageGenerationRequest) -> ImageInfo:
        """创建图片信息"""
        # 生成图片ID
        image_id = f"openai_image_{int(time.time())}_{hash(request.prompt) % 10000}"

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
            description=f"Generated by OpenAI Image with prompt: {request.prompt}",
            alt_text=request.prompt,
            source_type=ImageSourceType.AI_GENERATED,
            provider=ImageProvider.OPENAI_IMAGE,
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
            base_url = self.api_base.rstrip('/')
            if self._is_chat_completions_endpoint():
                marker = "/chat/completions"
                lower_base = base_url.lower()
                marker_index = lower_base.rfind(marker)
                if marker_index != -1:
                    base_url = base_url[:marker_index]
            url = f"{base_url}/models"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
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
                'id': 'gpt-image-1',
                'name': 'GPT Image 1',
                'description': 'OpenAI GPT Image generation model',
                'max_resolution': '1536x1024',
                'supported_styles': ['natural', 'vivid']
            },
            {
                'id': 'dall-e-3',
                'name': 'DALL-E 3',
                'description': 'OpenAI DALL-E 3 image generation model',
                'max_resolution': '1792x1024',
                'supported_styles': ['natural', 'vivid']
            },
            {
                'id': 'dall-e-2',
                'name': 'DALL-E 2',
                'description': 'OpenAI DALL-E 2 image generation model',
                'max_resolution': '1024x1024',
                'supported_styles': ['natural']
            }
        ]
