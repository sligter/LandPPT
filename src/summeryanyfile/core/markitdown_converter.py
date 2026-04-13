"""
MarkItDown转换器 - 支持多种文件格式转换为Markdown
"""

import logging
import tempfile
import os
from typing import Tuple, Optional, Dict, Any
from pathlib import Path
import re

logger = logging.getLogger(__name__)


class MarkItDownConverter:
    """
    MarkItDown转换器，支持将多种文件格式转换为Markdown
    
    支持的格式：
    - PDF
    - PowerPoint (.pptx, .ppt)
    - Word (.docx, .doc) 
    - Excel (.xlsx, .xls)
    - Images (EXIF metadata and OCR)
    - Audio (EXIF metadata and speech transcription)
    - HTML
    - Text-based formats (CSV, JSON, XML)
    - ZIP files (iterates over contents)
    - YouTube URLs
    - EPubs
    """
    
    def __init__(
        self,
        enable_plugins: bool = False,
        use_magic_pdf: bool = True,
        enable_cache: bool = True,
        cache_dir: Optional[str] = None,
        processing_mode: Optional[str] = None,
        mineru_api_key: Optional[str] = None,
        mineru_base_url: Optional[str] = None,
    ):
        """
        初始化MarkItDown转换器

        Args:
            enable_plugins: 是否启用插件（默认False以提高安全性）
            use_magic_pdf: 是否使用Magic-PDF处理PDF文件（本地处理，优先级高于MarkItDown）
            enable_cache: 是否启用文件缓存（默认True）
            cache_dir: 缓存目录
            processing_mode: 处理模式
        """
        self.enable_plugins = enable_plugins
        self.use_magic_pdf = use_magic_pdf
        self.enable_cache = enable_cache
        self.mineru_api_key = mineru_api_key
        self.mineru_base_url = mineru_base_url
        self._markitdown = None
        self._magic_pdf_converter = None
        self._cache_manager = None

        # 初始化缓存管理器
        if enable_cache:
            try:
                from .file_cache_manager import FileCacheManager
                # 根据use_magic_pdf确定处理模式
                if processing_mode is None:
                    processing_mode = "magic_pdf" if use_magic_pdf else "markitdown"
                self._cache_manager = FileCacheManager(
                    cache_dir=cache_dir,
                    processing_mode=processing_mode
                )
                logger.info("MarkItDown转换器缓存功能已启用")
            except ImportError as e:
                logger.warning(f"无法导入缓存管理器，缓存功能已禁用: {e}")
                self.enable_cache = False
        
    def _get_markitdown_instance(self):
        """延迟初始化MarkItDown实例"""
        if self._markitdown is None:
            try:
                from markitdown import MarkItDown
                self._markitdown = MarkItDown(enable_plugins=self.enable_plugins)
                logger.info(f"MarkItDown初始化成功，插件状态: {self.enable_plugins}")
            except ImportError:
                raise ImportError(
                    "请安装markitdown: pip install 'markitdown[all]' 或 uv add 'markitdown[all]'"
                )
        return self._markitdown



    def _get_magic_pdf_converter(self):
        """延迟初始化Magic-PDF转换器"""
        if self._magic_pdf_converter is None and self.use_magic_pdf:
            try:
                # 尝试导入Magic-PDF转换器
                try:
                    from .magic_pdf_converter import MagicPDFConverter
                except ImportError:
                    # 如果相对导入失败，尝试绝对导入
                    from summeryanyfile.core.magic_pdf_converter import MagicPDFConverter

                self._magic_pdf_converter = MagicPDFConverter(
                    mineru_api_key=self.mineru_api_key,
                    mineru_base_url=self.mineru_base_url,
                )
                if self._magic_pdf_converter.is_available():
                    logger.info("Magic-PDF转换器初始化成功，将优先用于PDF转换")
                else:
                    logger.info("Magic-PDF(MinerU) 不可用（未配置 MinerU Key 或初始化失败），PDF转换将使用MarkItDown")
                    self._magic_pdf_converter = None
            except ImportError as e:
                logger.debug(f"Magic-PDF转换器不可用，使用MarkItDown: {e}")
                self._magic_pdf_converter = None
        return self._magic_pdf_converter
    
    def convert_file(self, file_path: str) -> Tuple[str, str]:
        """
        转换文件为Markdown格式
        
        Args:
            file_path: 文件路径
            
        Returns:
            (转换后的Markdown内容, 检测到的编码)
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 转换失败
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        if not path.is_file():
            raise ValueError(f"路径不是文件: {file_path}")
        
        logger.info(f"开始转换文件: {file_path}")

        # 检查缓存
        # 对于 PDF：当启用 magic_pdf 且 MinerU 可用时，避免复用非 magic_pdf 的旧缓存
        # （例如之前 MinerU 不可用时落盘的 markitdown 缓存），否则会导致 magic_pdf 模式不再调用 MinerU。
        require_magic_pdf_cache = False
        magic_pdf_converter_for_cache = None
        if path.suffix.lower() == '.pdf' and self.use_magic_pdf:
            magic_pdf_converter_for_cache = self._get_magic_pdf_converter()
            require_magic_pdf_cache = magic_pdf_converter_for_cache is not None

        if self.enable_cache and self._cache_manager:
            is_cached, md5_hash = self._cache_manager.is_cached(file_path)
            if is_cached and md5_hash:
                logger.info(f"使用缓存的转换结果: {md5_hash}")
                cached_content, cached_metadata = self._cache_manager.get_cached_content(md5_hash)

                if cached_content:
                    cached_method = None
                    try:
                        cached_method = (cached_metadata or {}).get('processing_metadata', {}).get('processing_method')
                    except Exception:
                        cached_method = None

                    if require_magic_pdf_cache and cached_method != 'magic_pdf':
                        logger.info(f"magic_pdf已启用且MinerU可用，忽略非magic_pdf缓存: {md5_hash} (method={cached_method})")
                    else:
                        # 从缓存元数据中获取编码信息
                        encoding = (cached_metadata or {}).get('processing_metadata', {}).get('detected_encoding', 'utf-8')
                        logger.info(f"成功从缓存恢复转换结果: {path.name}")
                        return cached_content, encoding

        # 对于PDF文件，优先尝试Magic-PDF
        if path.suffix.lower() == '.pdf':
            # 优先尝试Magic-PDF（本地处理）
            if self.use_magic_pdf:
                magic_pdf_converter = magic_pdf_converter_for_cache or self._get_magic_pdf_converter()
                if magic_pdf_converter:
                    try:
                        logger.info(f"使用Magic-PDF转换PDF文件: {file_path}")
                        content, encoding = magic_pdf_converter.convert_pdf_file(file_path)
                        if content.strip():
                            logger.info(f"Magic-PDF转换成功，内容长度: {len(content)} 字符")

                            # 保存到缓存
                            if self.enable_cache and self._cache_manager:
                                try:
                                    processing_metadata = {
                                        'detected_encoding': encoding,
                                        'processing_method': 'magic_pdf'
                                    }
                                    md5_hash = self._cache_manager.save_to_cache(file_path, content, processing_metadata)
                                    logger.info(f"Magic-PDF转换结果已缓存: {md5_hash}")
                                except Exception as e:
                                    logger.warning(f"保存Magic-PDF缓存失败: {e}")

                            return content, encoding
                        else:
                            logger.warning("Magic-PDF转换结果为空，回退到MarkItDown")
                    except Exception as e:
                        logger.warning(f"Magic-PDF转换失败，回退到MarkItDown: {e}")
                else:
                    logger.debug("Magic-PDF转换器不可用，使用MarkItDown")

        # 使用MarkItDown转换（默认方法或回退方法）
        try:
            md_instance = self._get_markitdown_instance()
            result = md_instance.convert(str(path))

            if result and hasattr(result, 'text_content'):
                content = result.text_content
                if content:
                    logger.info(f"MarkItDown转换成功，内容长度: {len(content)} 字符")

                    # 保存到缓存
                    if self.enable_cache and self._cache_manager:
                        try:
                            processing_metadata = {
                                'detected_encoding': 'utf-8',
                                'processing_method': 'markitdown'
                            }
                            md5_hash = self._cache_manager.save_to_cache(file_path, content, processing_metadata)
                            logger.info(f"MarkItDown转换结果已缓存: {md5_hash}")
                        except Exception as e:
                            logger.warning(f"保存MarkItDown缓存失败: {e}")

                    return content, "utf-8"
                else:
                    logger.warning(f"转换结果为空: {file_path}")
                    return "", "utf-8"
            else:
                logger.error(f"转换失败，无效的结果: {file_path}")
                raise ValueError(f"MarkItDown转换失败: {file_path}")

        except Exception as e:
            logger.error(f"MarkItDown转换错误: {e}")
            raise ValueError(f"文件转换失败: {e}")
    
    def convert_url(self, url: str) -> Tuple[str, str]:
        """
        转换URL内容为Markdown格式
        
        Args:
            url: URL地址（支持YouTube等）
            
        Returns:
            (转换后的Markdown内容, 编码)
            
        Raises:
            ValueError: 转换失败
        """
        logger.info(f"开始转换URL: {url}")
        
        try:
            md_instance = self._get_markitdown_instance()
            result = md_instance.convert(url)
            
            if result and hasattr(result, 'text_content'):
                content = result.text_content
                if content:
                    logger.info(f"URL转换成功，内容长度: {len(content)} 字符")
                    return content, "utf-8"
                else:
                    logger.warning(f"URL转换结果为空: {url}")
                    return "", "utf-8"
            else:
                logger.error(f"URL转换失败，无效的结果: {url}")
                raise ValueError(f"MarkItDown URL转换失败: {url}")
                
        except Exception as e:
            logger.error(f"MarkItDown URL转换错误: {e}")
            raise ValueError(f"URL转换失败: {e}")

    def convert_pdf_url(self, pdf_url: str, enable_ocr: bool = True, enable_formula: bool = False) -> Tuple[str, str]:
        """
        转换PDF URL为Markdown格式（使用MarkItDown）

        Args:
            pdf_url: PDF文件URL
            enable_ocr: 是否启用OCR识别（参数保留但MarkItDown可能不支持）
            enable_formula: 是否启用公式识别（参数保留但MarkItDown可能不支持）

        Returns:
            (转换后的Markdown内容, 编码)

        Raises:
            ValueError: 转换失败
        """
        logger.info(f"开始转换PDF URL: {pdf_url}")

        # 使用MarkItDown的URL转换
        return self.convert_url(pdf_url)
    
    def is_supported_format(self, file_path: str) -> bool:
        """
        检查文件格式是否被MarkItDown支持
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否支持该格式
        """
        supported_extensions = {
            '.pdf', '.pptx', '.ppt', '.docx', '.doc', '.xlsx', '.xls',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp',
            '.mp3', '.wav', '.m4a', '.flac', '.zip', '.epub', '.xml',
            '.html', '.htm', '.csv', '.json', '.txt', '.md'
        }
        
        extension = Path(file_path).suffix.lower()
        return extension in supported_extensions
    
    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取文件信息
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件信息字典
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        stat = path.stat()
        extension = path.suffix.lower()
        
        # 确定文件类型
        file_type = "unknown"
        if extension in ['.pdf']:
            file_type = "document"
        elif extension in ['.pptx', '.ppt']:
            file_type = "presentation"
        elif extension in ['.docx', '.doc']:
            file_type = "document"
        elif extension in ['.xlsx', '.xls']:
            file_type = "spreadsheet"
        elif extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']:
            file_type = "image"
        elif extension in ['.mp3', '.wav', '.m4a', '.flac']:
            file_type = "audio"
        elif extension in ['.zip']:
            file_type = "archive"
        elif extension in ['.epub']:
            file_type = "ebook"
        elif extension in ['.xml', '.html', '.htm']:
            file_type = "markup"
        elif extension in ['.csv', '.json', '.txt', '.md']:
            file_type = "text"
        
        return {
            "path": str(path.absolute()),
            "name": path.name,
            "size": stat.st_size,
            "extension": extension,
            "file_type": file_type,
            "modified_time": stat.st_mtime,
            "is_supported": self.is_supported_format(file_path)
        }
    
    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        提取文件元数据（如果可用）
        
        Args:
            file_path: 文件路径
            
        Returns:
            元数据字典
        """
        metadata = {"source_file": file_path}
        
        try:
            # 对于图片文件，尝试提取EXIF数据
            extension = Path(file_path).suffix.lower()
            if extension in ['.jpg', '.jpeg', '.png', '.tiff']:
                try:
                    from PIL import Image
                    from PIL.ExifTags import TAGS
                    
                    with Image.open(file_path) as img:
                        exif_data = img.getexif()
                        if exif_data:
                            exif_dict = {}
                            for tag_id, value in exif_data.items():
                                tag = TAGS.get(tag_id, tag_id)
                                exif_dict[tag] = value
                            metadata["exif"] = exif_dict
                            
                except ImportError:
                    logger.debug("PIL未安装，无法提取EXIF数据")
                except Exception as e:
                    logger.debug(f"提取EXIF数据失败: {e}")
            
            # 添加基本文件信息
            file_info = self.get_file_info(file_path)
            metadata.update(file_info)
            
        except Exception as e:
            logger.debug(f"提取元数据失败: {e}")
        
        return metadata
    
    def clean_markdown_content(self, content: str) -> str:
        """
        清理和优化Markdown内容
        
        Args:
            content: 原始Markdown内容
            
        Returns:
            清理后的Markdown内容
        """
        if not content:
            return content
        
        # 移除过多的空行
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # 清理行首行尾空白
        lines = [line.rstrip() for line in content.split('\n')]
        content = '\n'.join(lines)
        
        # 确保标题前后有适当的空行
        content = re.sub(r'\n(#{1,6}\s)', r'\n\n\1', content)
        content = re.sub(r'(#{1,6}.*)\n([^#\n])', r'\1\n\n\2', content)
        
        return content.strip()
