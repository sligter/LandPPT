__version__ = "0.1.0"
__author__ = "SummeryAnyFile Team"
__description__ = "通用文本转PPT大纲生成器 - 基于LLM的智能文档分析和演示大纲生成工具"

from .core.models import SlideInfo, PPTState
from .core.markitdown_converter import MarkItDownConverter
from .core.document_processor import DocumentProcessor

# Note: PPTOutlineGenerator is not imported here to avoid langgraph dependency issues
# Import it directly when needed: from summeryanyfile.generators.ppt_generator import PPTOutlineGenerator

__all__ = [
    "SlideInfo",
    "PPTState",
    "MarkItDownConverter",
    "DocumentProcessor",
    "__version__",
    "__author__",
    "__description__",
]
