"""
Pollinations 图片生成提供者（gen.pollinations.ai）
"""

import asyncio
import logging
import time
import urllib.parse
import tempfile
from typing import Dict, Any, List
from pathlib import Path
import aiohttp

from ..models import (
    ImageProvider, ImageGenerationRequest, ImageOperationResult,
    ImageInfo, ImageFormat, ImageLicense, ImageSourceType, ImageMetadata, ImageTag
)
from .base import ImageGenerationProvider

logger = logging.getLogger(__name__)


class PollinationsProvider(ImageGenerationProvider):
    """Pollinations 图片生成提供者"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(ImageProvider.POLLINATIONS, config)
        
        # API配置
        self.api_key = config.get('api_key', '')
        self.api_base = config.get('api_base', 'https://gen.pollinations.ai')
        self.model = config.get('model', 'flux')
        self.default_width = config.get('default_width', 1024)
        self.default_height = config.get('default_height', 1024)
        self.default_negative_prompt = config.get('default_negative_prompt', 'worst quality, blurry')
        self.default_enhance = bool(config.get('default_enhance', False))
        self.default_safe = bool(config.get('default_safe', False))
        
        # 速率限制
        self.rate_limit_requests = config.get('rate_limit_requests', 60)
        self.rate_limit_window = config.get('rate_limit_window', 60)
        
        # 请求历史（用于速率限制）
        self._request_history = []
        
        if not self.api_key:
            logger.warning("Pollinations API key not configured")
        logger.debug(f"Pollinations provider initialized with model: {self.model}")

    async def generate(self, request: ImageGenerationRequest) -> ImageOperationResult:
        """生成图片"""
        if not self.api_key:
            return ImageOperationResult(
                success=False,
                message="Pollinations API key not configured",
                error_code="api_key_missing"
            )

        try:
            # 检查速率限制
            if not self._check_rate_limit():
                return ImageOperationResult(
                    success=False,
                    message="Rate limit exceeded. Please try again later."
                )
            
            # 记录请求时间
            self._request_history.append(time.time())
            
            # 准备API请求
            api_url = self._build_api_url(request)
            
            logger.debug(f"Generating image with Pollinations API: {api_url}")
            
            # 准备请求头
            headers = {
                'Authorization': f'Bearer {self.api_key}'
            }

            # 发送请求
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.get(api_url, headers=headers) as response:
                    if response.status == 200:
                        # 读取图片数据
                        image_data = await response.read()
                        content_type = (response.headers.get('Content-Type') or '').lower()
                        
                        # 创建图片信息
                        image_id = f"pollinations_{int(time.time() * 1000)}"
                        file_ext = "png"
                        image_format = ImageFormat.PNG
                        if "image/jpeg" in content_type or "image/jpg" in content_type:
                            file_ext = "jpg"
                            image_format = ImageFormat.JPG
                        elif "image/webp" in content_type:
                            file_ext = "webp"
                            image_format = ImageFormat.WEBP
                        filename = f"{image_id}.{file_ext}"

                        # 创建元数据
                        metadata = ImageMetadata(
                            width=request.width or self.default_width,
                            height=request.height or self.default_height,
                            format=image_format,
                            file_size=len(image_data)
                        )

                        # 创建标签
                        tags = [
                            ImageTag(name="ai-generated", category="type", source="system"),
                            ImageTag(name="pollinations", category="provider", source="system"),
                            ImageTag(name=(request.model or self.model), category="model", source="system")
                        ]

                        # 保存图片到临时文件
                        temp_dir = Path(tempfile.gettempdir()) / "pollinations_images"
                        temp_dir.mkdir(exist_ok=True)
                        temp_file_path = temp_dir / filename

                        with open(temp_file_path, 'wb') as f:
                            f.write(image_data)

                        image_info = ImageInfo(
                            image_id=image_id,
                            source_type=ImageSourceType.AI_GENERATED,
                            provider=self.provider,
                            original_url=api_url,
                            local_path=str(temp_file_path),
                            filename=filename,
                            title=f"Generated: {request.prompt[:50]}...",
                            description=f"Generated by Pollinations AI using prompt: {request.prompt}",
                            metadata=metadata,
                            tags=tags,
                            license=ImageLicense.UNKNOWN
                        )

                        return ImageOperationResult(
                            success=True,
                            message="Image generated successfully",
                            image_info=image_info
                        )
                    else:
                        error_text = await response.text()
                        logger.error(f"Pollinations API error {response.status}: {error_text}")
                        return ImageOperationResult(
                            success=False,
                            message=f"API request failed with status {response.status}: {error_text}"
                        )
                        
        except asyncio.TimeoutError:
            logger.error("Pollinations API request timeout")
            return ImageOperationResult(
                success=False,
                message="Request timeout. Please try again."
            )
        except Exception as e:
            logger.error(f"Pollinations generation error: {str(e)}")
            return ImageOperationResult(
                success=False,
                message=f"Generation failed: {str(e)}"
            )

    def _build_api_url(self, request: ImageGenerationRequest) -> str:
        """构建API请求URL"""
        encoded_prompt = urllib.parse.quote(request.prompt, safe='')

        # gen.pollinations.ai: /image/{prompt}
        url = f"{self.api_base}/image/{encoded_prompt}"

        params: List[str] = []

        model = (request.model or self.model or '').strip()
        if model:
            params.append(f"model={urllib.parse.quote(model, safe='')}")

        width = request.width or self.default_width
        height = request.height or self.default_height
        params.append(f"width={int(width)}")
        params.append(f"height={int(height)}")

        if request.seed is not None:
            params.append(f"seed={int(request.seed)}")

        enhance = (request.style == "enhanced") if request.style else self.default_enhance
        if enhance:
            params.append("enhance=true")

        negative_prompt = request.negative_prompt or self.default_negative_prompt
        if negative_prompt and str(negative_prompt).strip():
            params.append(f"negative_prompt={urllib.parse.quote(str(negative_prompt), safe='')}")

        if self.default_safe:
            params.append("safe=true")

        if model in {"gptimage", "gptimage-large"} and request.quality:
            q = request.quality.strip().lower()
            params.append("quality=hd" if q == "hd" else "quality=medium")

        if params:
            url += "?" + "&".join(params)

        return url

    def _check_rate_limit(self) -> bool:
        """检查速率限制"""
        current_time = time.time()
        
        # 清理过期的请求记录
        self._request_history = [
            req_time for req_time in self._request_history
            if current_time - req_time < self.rate_limit_window
        ]
        
        # 检查是否超过限制
        return len(self._request_history) < self.rate_limit_requests

    async def get_available_models(self) -> List[Dict[str, Any]]:
        """获取可用模型列表"""
        return [
            {
                "id": "flux",
                "name": "Flux",
                "description": "High-quality image generation model",
                "default": True
            },
            {
                "id": "zimage",
                "name": "ZImage",
                "description": "Default model on gen.pollinations.ai"
            },
            {
                "id": "turbo",
                "name": "Turbo",
                "description": "Fast image generation with good quality"
            },
            {
                "id": "gptimage",
                "name": "GPT Image",
                "description": "GPT-based image generation (supports quality parameter)"
            }
        ]

    async def get_available_styles(self) -> List[Dict[str, Any]]:
        """获取可用样式列表"""
        return [
            {
                "id": "natural",
                "name": "Natural",
                "description": "Natural style generation"
            },
            {
                "id": "enhanced",
                "name": "Enhanced",
                "description": "Enhanced prompt with more detail"
            }
        ]

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}

            # 健康检查 - 尝试访问模型列表
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                test_url = f"{self.api_base}/image/models"
                async with session.get(test_url, headers=headers) as response:
                    if response.status in [200, 401]:
                        return {
                            "status": "healthy",
                            "message": "Pollinations API is reachable",
                            "model": self.model,
                            "authenticated": bool(self.api_key),
                            "rate_limit": f"{self.rate_limit_requests}/{self.rate_limit_window}s"
                        }
                    return {
                        "status": "unhealthy",
                        "message": f"API returned status {response.status}",
                        "model": self.model
                    }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Health check failed: {str(e)}",
                "model": self.model
            }
