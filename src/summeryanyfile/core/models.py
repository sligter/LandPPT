"""
数据模型定义
"""

import os
from dataclasses import dataclass
from typing import List, Dict, Any, Literal, TypedDict, Optional
from enum import Enum


def _get_default_max_tokens() -> int:
    """
    从环境变量获取默认的 max_tokens 值

    Returns:
        默认的 max_tokens 值
    """
    try:
        # 尝试从环境变量读取
        env_value = os.getenv("MAX_TOKENS")
        if env_value:
            return int(env_value)
    except (ValueError, TypeError):
        pass

    # 如果环境变量不存在或无效，返回默认值
    return 4000


def _get_default_temperature() -> float:
    """
    从环境变量获取默认的 temperature 值

    Returns:
        默认的 temperature 值
    """
    try:
        # 尝试从环境变量读取
        env_value = os.getenv("TEMPERATURE")
        if env_value:
            return float(env_value)
    except (ValueError, TypeError):
        pass

    # 如果环境变量不存在或无效，返回默认值
    return 0.7


class ChunkStrategy(Enum):
    """文档分块策略"""
    PARAGRAPH = "paragraph"  # 基于段落分块
    SEMANTIC = "semantic"    # 语义分块
    RECURSIVE = "recursive"  # 递归分块
    HYBRID = "hybrid"        # 混合策略
    FAST = "fast"            # 快速分块策略


@dataclass
class SlideInfo:
    """幻灯片信息数据类"""
    page_number: int
    title: str
    content_points: List[str]
    slide_type: Literal["title", "content", "conclusion"]
    description: str
    chart_config: Optional[Dict[str, Any]] = None  # 新增：图表配置

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            "page_number": self.page_number,
            "title": self.title,
            "content_points": self.content_points,
            "slide_type": self.slide_type,
            "description": self.description,
        }

        # 只有当chart_config存在时才添加到字典中
        if self.chart_config is not None:
            result["chart_config"] = self.chart_config

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SlideInfo":
        """从字典创建实例"""
        return cls(
            page_number=data.get("page_number", 1),
            title=data.get("title", ""),
            content_points=data.get("content_points", []),
            slide_type=data.get("slide_type", "content"),
            description=data.get("description", ""),
            chart_config=data.get("chart_config"),  # 新增：图表配置
        )


class PPTState(TypedDict):
    """PPT生成状态"""
    document_chunks: List[str]
    current_index: int
    ppt_title: str
    slides: List[Dict[str, Any]]
    total_pages: int
    page_count_mode: str
    document_structure: Dict[str, Any]
    accumulated_context: str
    # 项目信息参数
    project_topic: str
    project_scenario: str
    project_requirements: str
    target_audience: str
    custom_audience: str
    ppt_style: str
    custom_style_prompt: str
    # 页数设置参数
    min_pages: Optional[int]
    max_pages: Optional[int]
    fixed_pages: Optional[int]


@dataclass
class DocumentInfo:
    """文档信息"""
    title: str
    content: str
    file_path: str
    file_type: str
    encoding: str
    size: int
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "title": self.title,
            "content": self.content,
            "file_path": self.file_path,
            "file_type": self.file_type,
            "encoding": self.encoding,
            "size": self.size,
        }


@dataclass
class ProcessingConfig:
    """处理配置"""
    max_slides: int = 25
    min_slides: int = 5  # 新增：最小页数
    chunk_size: int = 3000
    chunk_overlap: int = 200
    chunk_strategy: ChunkStrategy = ChunkStrategy.PARAGRAPH
    llm_model: str = "gpt-4o-mini"
    llm_provider: str = "openai"
    temperature: float = None  # 将在 __post_init__ 中设置默认值
    max_tokens: int = None  # 将在 __post_init__ 中设置默认值
    recursion_limit: Optional[int] = None  # 工作流递归限制，None表示自动计算
    target_language: str = "zh"  # 新增：目标语言，由用户在表单中选择
    # API配置（从数据库读取，不使用环境变量）
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    use_responses_api: bool = False
    enable_reasoning: bool = False
    reasoning_effort: str = "medium"

    def __post_init__(self):
        """后处理验证和默认值设置"""
        # 如果 max_tokens 为 None，从环境变量获取默认值
        if self.max_tokens is None:
            self.max_tokens = _get_default_max_tokens()

        # 如果 temperature 为 None，从环境变量获取默认值
        if self.temperature is None:
            self.temperature = _get_default_temperature()

        # 验证逻辑
        if self.min_slides > self.max_slides:
            raise ValueError(f"最小页数({self.min_slides})不能大于最大页数({self.max_slides})")
        if self.min_slides < 1:
            raise ValueError("最小页数不能小于1")
        if self.max_slides > 1000:
            raise ValueError("最大页数不能超过1000")
        if self.recursion_limit is not None and self.recursion_limit < 10:
            raise ValueError("递归限制不能小于10")



    @property
    def slides_range(self) -> str:
        """获取页数范围的字符串表示"""
        if self.min_slides == self.max_slides:
            return f"{self.min_slides}页"
        return f"{self.min_slides}-{self.max_slides}页"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "max_slides": self.max_slides,
            "min_slides": self.min_slides,
            "slides_range": self.slides_range,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "chunk_strategy": self.chunk_strategy.value,
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "recursion_limit": self.recursion_limit,
            "target_language": self.target_language,
            "use_responses_api": self.use_responses_api,
            "enable_reasoning": self.enable_reasoning,
            "reasoning_effort": self.reasoning_effort,
        }


@dataclass
class PPTOutline:
    """PPT大纲结果"""
    title: str
    total_pages: int
    page_count_mode: str
    slides: List[SlideInfo]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "title": self.title,
            "total_pages": self.total_pages,
            "page_count_mode": self.page_count_mode,
            "slides": [slide.to_dict() for slide in self.slides],
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PPTOutline":
        """从字典创建实例"""
        slides = [SlideInfo.from_dict(slide_data) for slide_data in data.get("slides", [])]
        return cls(
            title=data.get("title", ""),
            total_pages=data.get("total_pages", 0),
            page_count_mode=data.get("page_count_mode", "final"),
            slides=slides,
        )
