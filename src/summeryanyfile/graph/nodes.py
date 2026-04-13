"""
图节点实现 - 定义LangGraph工作流中的各个节点
"""

import json
import inspect
from typing import Awaitable, Callable, Dict, Any, Literal, Optional
import logging
from langchain_core.runnables import RunnableConfig

from ..core.models import PPTState
from ..core.json_parser import JSONParser
from ..generators.chains import ChainManager, ChainExecutor
from ..utils.logger import LoggerMixin

logger = logging.getLogger(__name__)


class GraphNodes(LoggerMixin):
    """图节点集合，包含所有工作流节点的实现"""

    def __init__(self, chain_manager: ChainManager, config=None):
        self.chain_manager = chain_manager
        self.chain_executor = ChainExecutor(chain_manager)
        self.json_parser = JSONParser()
        self.config = config  # 添加配置参数

    def _get_slides_range_text(self, state: Dict[str, Any]) -> str:
        """根据状态中的页数模式生成页数约束文本"""
        page_count_mode = state.get("page_count_mode", "ai_decide")
        min_pages = state.get("min_pages")
        max_pages = state.get("max_pages")
        fixed_pages = state.get("fixed_pages")

        if page_count_mode == "fixed" and fixed_pages:
            result = f"【强制要求】必须生成恰好{fixed_pages}页的PPT，不能多也不能少"
        elif page_count_mode == "custom_range" and min_pages and max_pages:
            result = f"【强制要求】必须严格控制在{min_pages}-{max_pages}页范围内，最少{min_pages}页，最多{max_pages}页，不能超出此范围"
        else:  # ai_decide
            result = "根据内容的复杂度、深度和逻辑结构，自主决定最合适的页数，确保内容充实且逻辑清晰"

        return result

    async def _emit_stream_chunk(
        self,
        chunk_callback: Optional[Callable[[str], Optional[Awaitable[None]]]],
        chunk: str,
    ) -> None:
        if not chunk_callback or not chunk:
            return

        callback_result = chunk_callback(chunk)
        if inspect.isawaitable(callback_result):
            await callback_result
    
    async def analyze_structure(self, state: PPTState, config: RunnableConfig) -> Dict[str, Any]:
        """
        分析文档结构节点
        
        Args:
            state: 当前状态
            config: 运行配置
            
        Returns:
            更新的状态字段
        """
        self.logger.info("开始分析文档结构...")
        
        try:
            # 获取第一个文档块
            first_chunk = state["document_chunks"][0] if state["document_chunks"] else ""
            
            if not first_chunk.strip():
                self.logger.warning("第一个文档块为空，使用默认结构")
                structure = {
                    "title": "文档分析",
                    "type": "通用文档",
                    "sections": [],
                    "key_concepts": [],
                    "language": "中文",
                    "complexity": "中等"
                }
            else:
                # 调用结构分析链
                structure_response = await self.chain_executor.execute_with_retry(
                    "structure_analysis",
                    {
                        "content": first_chunk,
                        "project_topic": state.get("project_topic", ""),
                        "project_scenario": state.get("project_scenario", "general"),
                        "project_requirements": state.get("project_requirements", ""),
                        "target_audience": state.get("target_audience", "普通大众"),
                        "custom_audience": state.get("custom_audience", ""),
                        "ppt_style": state.get("ppt_style", "general"),
                        "custom_style_prompt": state.get("custom_style_prompt", "")
                    },
                    config
                )
                
                # 解析JSON响应
                structure = self.json_parser.extract_json_from_response(structure_response)
                
                # 验证结构
                if not isinstance(structure, dict):
                    raise ValueError("结构分析返回的不是有效的字典")
            
            self.logger.info(f"文档结构分析完成: {structure.get('title', '未知标题')}")
            
            return {
                "document_structure": structure,
                "accumulated_context": first_chunk[:500]  # 保留前500字作为上下文
            }
            
        except Exception as e:
            self.logger.error(f"文档结构分析失败: {e}")
            # 返回默认结构
            return {
                "document_structure": {
                    "title": "文档分析",
                    "type": "通用文档",
                    "sections": [],
                    "key_concepts": [],
                    "language": "中文",
                    "complexity": "中等"
                },
                "accumulated_context": first_chunk[:500] if state["document_chunks"] else ""
            }
    
    async def generate_initial_outline(self, state: PPTState, config: RunnableConfig) -> Dict[str, Any]:
        """
        生成初始PPT框架节点
        
        Args:
            state: 当前状态
            config: 运行配置
            
        Returns:
            更新的状态字段
        """
        self.logger.info("开始生成初始PPT框架...")
        
        try:
            # 准备输入
            structure_json = json.dumps(state["document_structure"], ensure_ascii=False)
            first_chunk = state["document_chunks"][0] if state["document_chunks"] else ""
            
            # 准备输入参数，包含页数范围、目标语言和项目信息
            chain_inputs = {
                "structure": structure_json,
                "content": first_chunk,
                "project_topic": state.get("project_topic", ""),
                "project_scenario": state.get("project_scenario", "general"),
                "project_requirements": state.get("project_requirements", ""),
                "target_audience": state.get("target_audience", "普通大众"),
                "custom_audience": state.get("custom_audience", ""),
                "ppt_style": state.get("ppt_style", "general"),
                "custom_style_prompt": state.get("custom_style_prompt", "")
            }

            # 添加页数范围信息
            slides_range_text = self._get_slides_range_text(state)
            chain_inputs["slides_range"] = slides_range_text
            if self.config:
                chain_inputs["target_language"] = self.config.target_language
            else:
                chain_inputs["target_language"] = "zh"  # 默认中文

            # 调用初始大纲生成链
            outline_response = await self.chain_executor.execute_with_retry(
                "initial_outline",
                chain_inputs,
                config
            )
            
            # 解析JSON响应
            outline = self.json_parser.extract_json_from_response(outline_response)
            
            # 验证和修复大纲结构
            outline = self.json_parser.validate_ppt_structure(outline)
            
            self.logger.info(f"初始PPT框架生成完成: {outline.get('title', '未知标题')}")
            
            return {
                **state,  # 保留所有原始状态
                "ppt_title": outline.get("title", "学术演示"),
                "total_pages": outline.get("total_pages", 15),
                "page_count_mode": state.get("page_count_mode", "estimated"),  # 保持原始页数模式
                "slides": outline.get("slides", []),
                "current_index": 1
            }
            
        except Exception as e:
            self.logger.error(f"初始PPT框架生成失败: {e}")
            # 返回默认框架
            return {
                "ppt_title": "学术演示",
                "total_pages": 15,
                "page_count_mode": "estimated",
                "slides": [
                    {
                        "page_number": 1,
                        "title": "标题页",
                        "content_points": ["演示标题", "演示者", "日期"],
                        "slide_type": "title",
                        "description": "PPT开场标题页"
                    }
                ],
                "current_index": 1
            }
    
    async def generate_initial_outline_streaming(
        self,
        state: PPTState,
        config: RunnableConfig,
        chunk_callback: Optional[Callable[[str], Optional[Awaitable[None]]]] = None,
    ) -> Dict[str, Any]:
        """流式生成初始 PPT 框架。"""
        self.logger.info("开始流式生成初始 PPT 框架...")

        try:
            structure_json = json.dumps(state["document_structure"], ensure_ascii=False)
            first_chunk = state["document_chunks"][0] if state["document_chunks"] else ""

            chain_inputs = {
                "structure": structure_json,
                "content": first_chunk,
                "project_topic": state.get("project_topic", ""),
                "project_scenario": state.get("project_scenario", "general"),
                "project_requirements": state.get("project_requirements", ""),
                "target_audience": state.get("target_audience", "普通大众"),
                "custom_audience": state.get("custom_audience", ""),
                "ppt_style": state.get("ppt_style", "general"),
                "custom_style_prompt": state.get("custom_style_prompt", ""),
                "slides_range": self._get_slides_range_text(state),
                "target_language": self.config.target_language if self.config else "zh",
            }

            outline_response = await self.chain_executor.execute_with_retry_streaming(
                "initial_outline",
                chain_inputs,
                config,
                chunk_callback=chunk_callback,
            )

            outline = self.json_parser.extract_json_from_response(outline_response)
            outline = self.json_parser.validate_ppt_structure(outline)

            self.logger.info(f"流式初始 PPT 框架生成完成: {outline.get('title', '未知标题')}")

            return {
                **state,
                "ppt_title": outline.get("title", "学术演示"),
                "total_pages": outline.get("total_pages", 15),
                "page_count_mode": state.get("page_count_mode", "estimated"),
                "slides": outline.get("slides", []),
                "current_index": 1,
            }
        except Exception as e:
            self.logger.error(f"流式初始 PPT 框架生成失败: {e}")
            return {
                "ppt_title": "学术演示",
                "total_pages": 15,
                "page_count_mode": "estimated",
                "slides": [
                    {
                        "page_number": 1,
                        "title": "标题页",
                        "content_points": ["演示标题", "演示者", "日期"],
                        "slide_type": "title",
                        "description": "PPT 开场标题页",
                    }
                ],
                "current_index": 1,
            }

    async def refine_outline(self, state: PPTState, config: RunnableConfig) -> Dict[str, Any]:
        """
        细化PPT大纲节点
        
        Args:
            state: 当前状态
            config: 运行配置
            
        Returns:
            更新的状态字段
        """
        current_index = state["current_index"]
        total_chunks = len(state["document_chunks"])
        
        self.logger.info(f"正在细化PPT大纲 ({current_index + 1}/{total_chunks})...")
        
        # 检查是否还有内容需要处理
        if current_index >= total_chunks:
            self.logger.info("所有文档块已处理完成")
            return state
        
        try:
            # 获取当前文档块
            current_content = state["document_chunks"][current_index]
            
            # 准备现有大纲
            existing_outline = {
                "title": state["ppt_title"],
                "total_pages": state["total_pages"],
                "slides": state["slides"]
            }
            existing_outline_json = json.dumps(existing_outline, ensure_ascii=False)
            
            # 准备输入参数，包含页数范围、目标语言和项目信息
            chain_inputs = {
                "existing_outline": existing_outline_json,
                "new_content": current_content,
                "context": state["accumulated_context"],
                "project_topic": state.get("project_topic", ""),
                "project_scenario": state.get("project_scenario", "general"),
                "project_requirements": state.get("project_requirements", ""),
                "target_audience": state.get("target_audience", "普通大众"),
                "custom_audience": state.get("custom_audience", ""),
                "ppt_style": state.get("ppt_style", "general"),
                "custom_style_prompt": state.get("custom_style_prompt", "")
            }

            # 添加页数范围信息和目标语言
            slides_range_text = self._get_slides_range_text(state)
            chain_inputs["slides_range"] = slides_range_text
            if self.config:
                chain_inputs["target_language"] = self.config.target_language
            else:
                chain_inputs["target_language"] = "zh"  # 默认中文

            # 调用细化链
            refined_response = await self.chain_executor.execute_with_retry(
                "refine_outline",
                chain_inputs,
                config
            )
            
            # 解析JSON响应
            refined_outline = self.json_parser.extract_json_from_response(refined_response)
            
            # 验证和修复结构
            refined_outline = self.json_parser.validate_ppt_structure(refined_outline)
            
            # 更新累积上下文
            new_context = state["accumulated_context"] + "\n" + current_content[:300]
            if len(new_context) > 2000:  # 限制上下文长度
                new_context = new_context[-2000:]
            
            return {
                **state,  # 保留所有原始状态
                "ppt_title": refined_outline.get("title", state["ppt_title"]),
                "total_pages": refined_outline.get("total_pages", state["total_pages"]),
                "slides": refined_outline.get("slides", state["slides"]),
                "current_index": current_index + 1,
                "accumulated_context": new_context
            }
            
        except Exception as e:
            self.logger.error(f"PPT大纲细化失败: {e}")
            # 继续处理下一个块
            return {
                **state,
                "current_index": current_index + 1
            }
    
    async def refine_outline_streaming(
        self,
        state: PPTState,
        config: RunnableConfig,
        chunk_callback: Optional[Callable[[str], Optional[Awaitable[None]]]] = None,
    ) -> Dict[str, Any]:
        """流式细化 PPT 大纲。"""
        current_index = state["current_index"]
        total_chunks = len(state["document_chunks"])

        self.logger.info(f"正在流式细化 PPT 大纲 ({current_index + 1}/{total_chunks})...")

        if current_index >= total_chunks:
            self.logger.info("所有文档块已处理完成")
            return state

        try:
            current_content = state["document_chunks"][current_index]
            existing_outline = {
                "title": state["ppt_title"],
                "total_pages": state["total_pages"],
                "slides": state["slides"],
            }
            existing_outline_json = json.dumps(existing_outline, ensure_ascii=False)

            chain_inputs = {
                "existing_outline": existing_outline_json,
                "new_content": current_content,
                "context": state["accumulated_context"],
                "project_topic": state.get("project_topic", ""),
                "project_scenario": state.get("project_scenario", "general"),
                "project_requirements": state.get("project_requirements", ""),
                "target_audience": state.get("target_audience", "普通大众"),
                "custom_audience": state.get("custom_audience", ""),
                "ppt_style": state.get("ppt_style", "general"),
                "custom_style_prompt": state.get("custom_style_prompt", ""),
                "slides_range": self._get_slides_range_text(state),
                "target_language": self.config.target_language if self.config else "zh",
            }

            refined_response = await self.chain_executor.execute_with_retry_streaming(
                "refine_outline",
                chain_inputs,
                config,
                chunk_callback=chunk_callback,
            )

            refined_outline = self.json_parser.extract_json_from_response(refined_response)
            refined_outline = self.json_parser.validate_ppt_structure(refined_outline)

            new_context = state["accumulated_context"] + "\n" + current_content[:300]
            if len(new_context) > 2000:
                new_context = new_context[-2000:]

            return {
                **state,
                "ppt_title": refined_outline.get("title", state["ppt_title"]),
                "total_pages": refined_outline.get("total_pages", state["total_pages"]),
                "slides": refined_outline.get("slides", state["slides"]),
                "current_index": current_index + 1,
                "accumulated_context": new_context,
            }
        except Exception as e:
            self.logger.error(f"流式细化 PPT 大纲失败: {e}")
            return {
                **state,
                "current_index": current_index + 1,
            }

    def should_continue_refining(self, state: PPTState) -> Literal["refine_outline", "end"]:
        """
        判断是否继续细化的条件函数
        
        Args:
            state: 当前状态
            
        Returns:
            下一个节点名称
        """
        current_index = state["current_index"]
        total_chunks = len(state["document_chunks"])
        
        if current_index >= total_chunks:
            self.logger.info("所有文档块已处理，完成大纲生成")
            return "end"
        else:
            self.logger.debug(f"继续处理文档块 {current_index + 1}/{total_chunks}")
            return "refine_outline"
