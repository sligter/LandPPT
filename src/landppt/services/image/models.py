"""
图片服务数据模型
"""

from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from enum import Enum
import time
from pathlib import Path


class ImageSourceType(str, Enum):
    """图片来源类型"""
    AI_GENERATED = "ai_generated"
    WEB_SEARCH = "web_search"
    LOCAL_STORAGE = "local_storage"


class ImageProvider(str, Enum):
    """图片提供者"""
    # AI生成
    DALLE = "dalle"
    STABLE_DIFFUSION = "stable_diffusion"
    SILICONFLOW = "siliconflow"
    POLLINATIONS = "pollinations"

    GEMINI = "gemini"  # Google Gemini 图片生成
    OPENAI_IMAGE = "openai_image"  # OpenAI 图片生成 (支持自定义端点)

    # 网络搜索
    UNSPLASH = "unsplash"
    PIXABAY = "pixabay"
    SEARXNG = "searxng"
    GOOGLE_IMAGES = "google_images"

    # 本地存储
    LOCAL_STORAGE = "local_storage"
    USER_UPLOAD = "user_upload"
    SYSTEM_DEFAULT = "system_default"


class ImageFormat(str, Enum):
    """支持的图片格式"""
    JPEG = "jpeg"
    JPG = "jpg"
    PNG = "png"
    GIF = "gif"
    WEBP = "webp"
    BMP = "bmp"
    TIFF = "tiff"


class ImagePosition(str, Enum):
    """图片在幻灯片中的位置"""
    BACKGROUND = "background"
    CONTENT = "content"
    ICON = "icon"
    DECORATION = "decoration"
    HEADER = "header"
    FOOTER = "footer"


class ImageLicense(str, Enum):
    """图片许可证类型"""
    PUBLIC_DOMAIN = "public_domain"
    CC0 = "cc0"
    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    UNSPLASH_LICENSE = "unsplash_license"
    PIXABAY_LICENSE = "pixabay_license"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class ImageMetadata(BaseModel):
    """图片元数据"""
    width: int
    height: int
    format: ImageFormat
    file_size: int
    color_mode: Optional[str] = None
    has_transparency: bool = False
    dominant_colors: List[str] = Field(default_factory=list)
    average_color: Optional[str] = None
    brightness: Optional[float] = None
    contrast: Optional[float] = None


class ImageTag(BaseModel):
    """图片标签"""
    name: str
    category: Optional[str] = None
    confidence: float = 1.0
    source: Optional[str] = None  # 标签来源：user, ai, api等


class ImageInfo(BaseModel):
    """图片信息"""
    image_id: str
    # Data isolation / multi-tenant
    owner_user_id: Optional[int] = None  # Set for authenticated users; used to isolate gallery + management APIs
    source_image_id: Optional[str] = None  # Provider/original ID before caching (optional)
    source_type: ImageSourceType
    provider: ImageProvider
    original_url: Optional[str] = None
    local_path: str
    filename: str
    title: Optional[str] = None
    description: Optional[str] = None
    alt_text: Optional[str] = None
    
    # 元数据
    metadata: ImageMetadata
    
    # 标签和关键词
    tags: List[ImageTag] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    
    # 版权信息
    license: ImageLicense = ImageLicense.UNKNOWN
    license_info: Optional[str] = None
    author: Optional[str] = None
    author_url: Optional[str] = None
    source_url: Optional[str] = None
    
    # 使用统计
    usage_count: int = 0
    last_used_at: Optional[float] = None
    
    # 时间戳
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    
    def add_tag(self, name: str, category: Optional[str] = None, confidence: float = 1.0):
        """添加标签"""
        tag = ImageTag(name=name, category=category, confidence=confidence)
        if tag not in self.tags:
            self.tags.append(tag)
    
    def remove_tag(self, name: str):
        """移除标签"""
        self.tags = [tag for tag in self.tags if tag.name != name]
    
    def get_tags_by_category(self, category: str) -> List[ImageTag]:
        """按分类获取标签"""
        return [tag for tag in self.tags if tag.category == category]
    
    def update_usage(self):
        """更新使用统计"""
        self.usage_count += 1
        self.last_used_at = time.time()
        self.updated_at = time.time()


class ImageSearchRequest(BaseModel):
    """图片搜索请求"""
    query: str
    keywords: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    
    # 搜索参数
    page: int = 1
    per_page: int = 20
    orientation: Optional[str] = None  # landscape, portrait, squarish
    category: Optional[str] = None
    color: Optional[str] = None
    
    # 尺寸要求
    min_width: Optional[int] = None
    min_height: Optional[int] = None
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    
    # 许可证要求
    license_types: List[ImageLicense] = Field(default_factory=list)
    
    # 提供者偏好
    preferred_providers: List[ImageProvider] = Field(default_factory=list)
    excluded_providers: List[ImageProvider] = Field(default_factory=list)


class ImageGenerationRequest(BaseModel):
    """AI图片生成请求"""
    prompt: str
    negative_prompt: Optional[str] = None
    
    # 生成参数
    width: int = 1024
    height: int = 1024
    quality: str = "standard"  # standard, hd
    style: Optional[str] = None  # vivid, natural
    
    # 提供者特定参数
    provider: ImageProvider = ImageProvider.DALLE
    model: Optional[str] = None
    steps: Optional[int] = None
    guidance_scale: Optional[float] = None
    seed: Optional[int] = None
    
    # 批量生成
    num_images: int = 1


class ImageUploadRequest(BaseModel):
    """图片上传请求"""
    filename: str
    content_type: str
    file_size: int

    # 可选信息
    title: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None

    # 来源信息
    source_type: Optional[ImageSourceType] = None  # 实际来源类型，如果为None则默认为LOCAL_STORAGE
    original_url: Optional[str] = None  # 原始URL（用于网络图片）

    # 处理选项
    auto_resize: bool = True
    auto_optimize: bool = True
    generate_thumbnails: bool = True


class ImageProcessingOptions(BaseModel):
    """图片处理选项"""
    # 尺寸调整
    resize_width: Optional[int] = None
    resize_height: Optional[int] = None
    maintain_aspect_ratio: bool = True
    resize_method: str = "lanczos"  # lanczos, bicubic, bilinear
    
    # 格式转换
    output_format: Optional[ImageFormat] = None
    
    # 质量优化
    quality: Optional[int] = None  # 1-100
    optimize: bool = True
    progressive: bool = False
    
    # 图片增强
    auto_enhance: bool = False
    brightness: Optional[float] = None
    contrast: Optional[float] = None
    saturation: Optional[float] = None
    sharpness: Optional[float] = None
    
    # 水印
    add_watermark: bool = False
    watermark_text: Optional[str] = None
    watermark_position: str = "bottom_right"
    watermark_opacity: float = 0.5


class ImageSearchResult(BaseModel):
    """图片搜索结果"""
    images: List[ImageInfo]
    total_count: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool

    # 搜索统计
    search_time: float
    provider_results: Dict[str, int] = Field(default_factory=dict)
    provider: ImageProvider
    error: Optional[str] = None


class ImageOperationResult(BaseModel):
    """图片操作结果"""
    success: bool
    message: str
    image_info: Optional[ImageInfo] = None
    error_code: Optional[str] = None
    processing_time: Optional[float] = None


class ProjectImageAssociation(BaseModel):
    """项目图片关联"""
    project_id: str
    image_id: str
    slide_index: int
    position: ImagePosition
    
    # 位置和样式信息
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    z_index: Optional[int] = None
    
    # 样式属性
    opacity: float = 1.0
    rotation: float = 0.0
    border_radius: Optional[float] = None
    shadow: Optional[Dict[str, Any]] = None
    
    # 动画效果
    animation: Optional[Dict[str, Any]] = None
    
    created_at: float = Field(default_factory=time.time)


class ImageCacheInfo(BaseModel):
    """图片缓存信息"""
    cache_key: str
    file_path: str
    file_size: int
    created_at: float
    last_accessed: float
    access_count: int
    expires_at: Optional[float] = None
    
    def is_expired(self) -> bool:
        """检查是否过期 - 图片永不过期"""
        return False
    
    def update_access(self):
        """更新访问信息"""
        self.last_accessed = time.time()
        self.access_count += 1
