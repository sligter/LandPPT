"""
Magic-PDF转换器 - 使用 MinerU 在线 API 进行 PDF 转 Markdown 转换
基于 MinerU 在线 API (https://mineru.net/apiManage/docs)
"""

import logging
import os
import tempfile
import shutil
from typing import Tuple, Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class MagicPDFConverter:
    """
    Magic-PDF转换器，使用 MinerU 在线 API 进行 PDF 转 Markdown 转换

    MinerU API 提供：
    - 高质量的 PDF 解析
    - OCR 文字识别（支持 109 种语言）
    - 布局分析
    - 表格和图片提取
    - 公式识别（LaTeX 格式）
    - 云端处理，无需本地模型
    
    使用前需要配置 MinerU API Key：
        - 优先：在 LandPPT 用户配置（DB）中设置 `mineru_api_key`
        - 或者：设置环境变量 `MINERU_API_KEY`（从 https://mineru.net/apiManage 获取）
    """

    def __init__(
        self,
        output_dir: Optional[str] = None,
        mineru_api_key: Optional[str] = None,
        mineru_base_url: Optional[str] = None,
    ):
        """
        初始化 Magic-PDF 转换器

        Args:
            output_dir: 输出目录，如果为 None 则使用临时目录
        """
        self.output_dir = output_dir or tempfile.mkdtemp(prefix="magic_pdf_")
        self.mineru_api_key = mineru_api_key
        self.mineru_base_url = mineru_base_url
        self._is_available = None
        self._api_client = None

        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(f"MinerU 转换器初始化，输出目录: {self.output_dir}")

    def _get_api_client(self):
        """获取 API 客户端实例"""
        if self._api_client is None:
            from .mineru_api_client import MineruAPIClient
            self._api_client = MineruAPIClient(
                api_key=self.mineru_api_key,
                base_url=self.mineru_base_url,
            )
        return self._api_client

    def is_available(self) -> bool:
        """检查 MinerU API 是否可用（API Key 是否已配置）"""
        if self._is_available is None:
            try:
                client = self._get_api_client()
                self._is_available = client.is_available
                if self._is_available:
                    logger.info("MinerU API 可用")
                else:
                    logger.warning("MinerU API Key 未配置，请在用户配置中设置 mineru_api_key 或设置环境变量 MINERU_API_KEY")
            except Exception as e:
                self._is_available = False
                logger.warning(f"MinerU API 客户端初始化失败: {e}")

        return self._is_available

    def convert_pdf_file(self, file_path: str,
                        lang: str = "ch",
                        backend: str = "pipeline",
                        method: str = "auto",
                        formula_enable: bool = True,
                        table_enable: bool = True) -> Tuple[str, str]:
        """
        转换 PDF 文件为 Markdown

        Args:
            file_path: PDF 文件路径
            lang: 语言选项，默认'ch'（中文），可选 'en'（英文）
            backend: 解析后端（参数保留，API 模式下忽略）
            method: 解析方法（参数保留，API 模式下忽略）
            formula_enable: 是否启用公式解析
            table_enable: 是否启用表格解析

        Returns:
            (转换后的 Markdown 内容, 编码)

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 转换失败
        """
        if not self.is_available():
            raise ValueError(
                "MinerU API 不可用。请在用户配置中设置 mineru_api_key（推荐），"
                "或设置环境变量 MINERU_API_KEY（可从 https://mineru.net/apiManage 获取）"
            )

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if not path.suffix.lower() == '.pdf':
            raise ValueError(f"不支持的文件格式: {path.suffix}")

        logger.info(f"开始使用 MinerU API 转换文件: {file_path}")

        try:
            client = self._get_api_client()
            
            # 调用 API 进行转换
            md_content, extra_info = client.extract_markdown_sync(
                file_path=file_path,
                enable_ocr=True,  # API 模式下始终启用 OCR
                enable_formula=formula_enable,
                enable_table=table_enable,
                language=lang
            )

            if not md_content or not md_content.strip():
                raise ValueError("MinerU API 转换结果为空")

            # 保存到本地文件（可选）
            name_without_suff = path.stem
            md_file_path = os.path.join(self.output_dir, f"{name_without_suff}.md")
            try:
                with open(md_file_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                logger.debug(f"Markdown 文件已保存: {md_file_path}")
            except Exception as e:
                logger.warning(f"保存 Markdown 文件失败: {e}")

            logger.info(f"MinerU API 转换成功，内容长度: {len(md_content)} 字符")
            return md_content, "utf-8"

        except Exception as e:
            logger.error(f"MinerU API 转换失败: {e}")
            raise ValueError(f"MinerU API 转换失败: {e}")

    def get_conversion_info(self, file_path: str) -> Dict[str, Any]:
        """
        获取转换信息（不执行实际转换）

        Args:
            file_path: PDF 文件路径

        Returns:
            转换信息字典
        """
        if not self.is_available():
            return {"available": False, "error": "MinerU API Key 未配置"}

        path = Path(file_path)
        if not path.exists():
            return {"available": False, "error": f"文件不存在: {file_path}"}

        return {
            "available": True,
            "file_path": str(path.absolute()),
            "file_size": path.stat().st_size,
            "mode": "api",  # 使用 API 模式
            "api_endpoint": "https://mineru.net/api/v4/extract/task",
            "output_dir": self.output_dir,
            "supported_languages": ["ch", "en"]
        }

    def parse_documents(self,
                       path_list: List[Path],
                       lang: str = "ch",
                       backend: str = "pipeline",
                       method: str = "auto",
                       server_url: Optional[str] = None,
                       start_page_id: int = 0,
                       end_page_id: Optional[int] = None) -> List[Tuple[str, str]]:
        """
        批量解析多个文档

        Args:
            path_list: 文档路径列表
            lang: 语言选项，默认'ch'
            backend: 解析后端（参数保留）
            method: 解析方法（参数保留）
            server_url: 服务器 URL（参数保留）
            start_page_id: 开始页面 ID（参数保留）
            end_page_id: 结束页面 ID（参数保留）

        Returns:
            (Markdown 内容, 编码) 的列表
        """
        if not self.is_available():
            raise ValueError("MinerU API Key 未配置")

        results = []
        for path in path_list:
            try:
                md_content, encoding = self.convert_pdf_file(
                    str(path), lang=lang
                )
                results.append((md_content, encoding))
                logger.info(f"成功处理文档: {path}")
            except Exception as e:
                logger.error(f"处理文档失败 {path}: {e}")
                results.append(("", "utf-8"))  # 失败时返回空内容

        return results

    def cleanup(self):
        """清理临时文件"""
        if self.output_dir and os.path.exists(self.output_dir):
            try:
                # 只清理临时目录
                if "magic_pdf_" in self.output_dir:
                    shutil.rmtree(self.output_dir)
                    logger.info(f"已清理临时目录: {self.output_dir}")
            except Exception as e:
                logger.warning(f"清理临时目录失败: {e}")

    def get_output_files(self, file_path: str, method: str = "auto") -> Dict[str, str]:
        """
        获取输出文件路径

        Args:
            file_path: 原始 PDF 文件路径
            method: 解析方法（参数保留）

        Returns:
            输出文件路径字典
        """
        name_without_suff = Path(file_path).stem

        return {
            "markdown": os.path.join(self.output_dir, f"{name_without_suff}.md"),
        }

    def __del__(self):
        """析构函数，自动清理临时文件"""
        self.cleanup()


def parse_doc(path_list: List[Path],
              output_dir: str,
              lang: str = "ch",
              backend: str = "pipeline",
              method: str = "auto",
              server_url: Optional[str] = None,
              start_page_id: int = 0,
              end_page_id: Optional[int] = None) -> None:
    """
    便利函数：解析文档列表

    Args:
        path_list: 文档路径列表
        output_dir: 输出目录
        lang: 语言选项，默认'ch'
        backend: 解析后端（参数保留）
        method: 解析方法（参数保留）
        server_url: 服务器 URL（参数保留）
        start_page_id: 开始页面 ID（参数保留）
        end_page_id: 结束页面 ID（参数保留）
    """
    try:
        converter = MagicPDFConverter(output_dir=output_dir)

        if not converter.is_available():
            raise ValueError("MinerU API Key 未配置。请设置环境变量 MINERU_API_KEY")

        for path in path_list:
            try:
                logger.info(f"开始处理文件: {path}")

                md_content, encoding = converter.convert_pdf_file(
                    str(path),
                    lang=lang
                )

                logger.info(f"成功处理文件: {path}, 输出目录: {output_dir}")

            except Exception as e:
                logger.error(f"处理文件失败 {path}: {e}")

    except Exception as e:
        logger.error(f"批量处理失败: {e}")
        raise
