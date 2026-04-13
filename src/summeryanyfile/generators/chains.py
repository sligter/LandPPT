"""
处理链管理器 - 管理LangChain处理链
"""

import inspect
from typing import AsyncGenerator, Awaitable, Callable, Dict, Any, Optional
import logging
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from ..config.prompts import PromptTemplates
from ..utils.logger import LoggerMixin

logger = logging.getLogger(__name__)


class ChainManager(LoggerMixin):
    """处理链管理器"""
    
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.prompt_templates = PromptTemplates()
        self._chains: Dict[str, Runnable] = {}
        self._setup_chains()
    
    def _setup_chains(self):
        """设置所有处理链"""
        self.logger.debug("正在设置处理链...")
        
        # 文档结构分析链
        self._chains["structure_analysis"] = (
            self.prompt_templates.get_structure_analysis_prompt() 
            | self.llm 
            | StrOutputParser()
        )
        
        # 初始PPT框架生成链
        self._chains["initial_outline"] = (
            self.prompt_templates.get_initial_outline_prompt()
            | self.llm
            | StrOutputParser()
        )
        
        # 内容细化链
        self._chains["refine_outline"] = (
            self.prompt_templates.get_refine_outline_prompt()
            | self.llm
            | StrOutputParser()
        )
        
        # 错误恢复链
        self._chains["error_recovery"] = (
            self.prompt_templates.get_error_recovery_prompt()
            | self.llm
            | StrOutputParser()
        )
        
        self.logger.debug(f"已设置 {len(self._chains)} 个处理链")
    
    def get_chain(self, chain_name: str) -> Runnable:
        """
        获取指定的处理链
        
        Args:
            chain_name: 链名称
            
        Returns:
            处理链实例
            
        Raises:
            KeyError: 链不存在
        """
        if chain_name not in self._chains:
            raise KeyError(f"处理链不存在: {chain_name}")
        
        return self._chains[chain_name]
    
    async def invoke_chain(
        self, 
        chain_name: str, 
        inputs: Dict[str, Any],
        config: Dict[str, Any] = None
    ) -> str:
        """
        调用指定的处理链
        
        Args:
            chain_name: 链名称
            inputs: 输入参数
            config: 运行配置
            
        Returns:
            处理结果
        """
        chain = self.get_chain(chain_name)
        
        try:
            self.logger.debug(f"调用处理链: {chain_name}")
            result = await chain.ainvoke(inputs, config or {})
            self.logger.debug(f"处理链 {chain_name} 执行成功")
            return result
        except Exception as e:
            self.logger.error(f"处理链 {chain_name} 执行失败: {e}")
            raise
    
    async def stream_chain(
        self,
        chain_name: str,
        inputs: Dict[str, Any],
        config: Dict[str, Any] = None,
    ) -> AsyncGenerator[str, None]:
        """流式调用指定处理链，逐块返回文本内容。"""
        chain = self.get_chain(chain_name)

        try:
            self.logger.debug(f"流式调用处理链: {chain_name}")
            async for chunk in chain.astream(inputs, config or {}):
                if not chunk:
                    continue
                yield str(chunk)
            self.logger.debug(f"处理链 {chain_name} 流式执行成功")
        except Exception as e:
            self.logger.error(f"处理链 {chain_name} 流式执行失败: {e}")
            raise

    def list_chains(self) -> list:
        """列出所有可用的处理链"""
        return list(self._chains.keys())
    
    def update_llm(self, llm: BaseChatModel):
        """更新LLM并重新设置处理链"""
        self.logger.info("更新LLM并重新设置处理链")
        self.llm = llm
        self._setup_chains()
    
    def add_custom_chain(self, name: str, chain: Runnable):
        """
        添加自定义处理链
        
        Args:
            name: 链名称
            chain: 处理链实例
        """
        self._chains[name] = chain
        self.logger.info(f"已添加自定义处理链: {name}")
    
    def remove_chain(self, name: str):
        """
        移除处理链
        
        Args:
            name: 链名称
        """
        if name in self._chains:
            del self._chains[name]
            self.logger.info(f"已移除处理链: {name}")
        else:
            self.logger.warning(f"尝试移除不存在的处理链: {name}")


class ChainExecutor:
    """处理链执行器，提供重试和错误处理功能"""
    
    def __init__(self, chain_manager: ChainManager, max_retries: int = 3):
        self.chain_manager = chain_manager
        self.max_retries = max_retries
        self.logger = logging.getLogger(self.__class__.__name__)
        # Count real LLM invocations (including retries) for downstream billing.
        self.llm_call_count = 0
    
    async def execute_with_retry(
        self,
        chain_name: str,
        inputs: Dict[str, Any],
        config: Dict[str, Any] = None
    ) -> str:
        """
        带重试的链执行
        
        Args:
            chain_name: 链名称
            inputs: 输入参数
            config: 运行配置
            
        Returns:
            处理结果
            
        Raises:
            Exception: 所有重试都失败后抛出最后一个异常
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                self.llm_call_count += 1
                result = await self.chain_manager.invoke_chain(chain_name, inputs, config)
                if attempt > 0:
                    self.logger.info(f"处理链 {chain_name} 在第 {attempt + 1} 次尝试后成功")
                return result
            except Exception as e:
                last_exception = e
                self.logger.warning(f"处理链 {chain_name} 第 {attempt + 1} 次尝试失败: {e}")
                
                if attempt < self.max_retries - 1:
                    # 可以在这里添加退避策略
                    import asyncio
                    await asyncio.sleep(1 * (attempt + 1))  # 简单的线性退避
        
        self.logger.error(f"处理链 {chain_name} 在 {self.max_retries} 次尝试后仍然失败")
        raise last_exception
    
    async def execute_with_retry_streaming(
        self,
        chain_name: str,
        inputs: Dict[str, Any],
        config: Dict[str, Any] = None,
        chunk_callback: Optional[Callable[[str], Optional[Awaitable[None]]]] = None
    ) -> str:
        """带重试的流式链执行，同时返回完整文本。"""
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                self.llm_call_count += 1
                collected_chunks = []

                async for chunk in self.chain_manager.stream_chain(chain_name, inputs, config):
                    if not chunk:
                        continue
                    collected_chunks.append(chunk)
                    if chunk_callback:
                        callback_result = chunk_callback(chunk)
                        if inspect.isawaitable(callback_result):
                            await callback_result

                result = "".join(collected_chunks)
                if attempt > 0:
                    self.logger.info(f"处理链 {chain_name} 在第 {attempt + 1} 次流式尝试后成功")
                return result
            except Exception as e:
                last_exception = e
                self.logger.warning(f"处理链 {chain_name} 第 {attempt + 1} 次流式尝试失败: {e}")

                if attempt < self.max_retries - 1:
                    import asyncio
                    await asyncio.sleep(1 * (attempt + 1))

        self.logger.error(f"处理链 {chain_name} 在 {self.max_retries} 次流式尝试后仍然失败")
        raise last_exception

    async def execute_with_fallback(
        self,
        primary_chain: str,
        fallback_chain: str,
        inputs: Dict[str, Any],
        fallback_inputs: Dict[str, Any] = None,
        config: Dict[str, Any] = None
    ) -> str:
        """
        带回退的链执行
        
        Args:
            primary_chain: 主要处理链
            fallback_chain: 回退处理链
            inputs: 主要链的输入参数
            fallback_inputs: 回退链的输入参数
            config: 运行配置
            
        Returns:
            处理结果
        """
        try:
            return await self.execute_with_retry(primary_chain, inputs, config)
        except Exception as e:
            self.logger.warning(f"主要处理链 {primary_chain} 失败，尝试回退链 {fallback_chain}: {e}")
            
            fallback_inputs = fallback_inputs or inputs
            try:
                return await self.execute_with_retry(fallback_chain, fallback_inputs, config)
            except Exception as fallback_e:
                self.logger.error(f"回退处理链 {fallback_chain} 也失败了: {fallback_e}")
                raise fallback_e
