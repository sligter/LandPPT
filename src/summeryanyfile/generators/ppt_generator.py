"""
PPT大纲生成器 - 主要的生成器类
"""

from typing import AsyncGenerator, Dict, Any, Optional, Callable, List
import logging

from ..core.models import PPTState, PPTOutline, SlideInfo, ProcessingConfig, ChunkStrategy
from ..core.document_processor import DocumentProcessor
from ..core.llm_manager import LLMManager
from ..generators.chains import ChainManager
from ..graph.workflow import WorkflowManager, WorkflowExecutor
from ..utils.logger import LoggerMixin, ProgressLogger

logger = logging.getLogger(__name__)


class PPTOutlineGenerator(LoggerMixin):
    """基于迭代细化的PPT大纲生成器"""
    
    def __init__(
        self,
        config: ProcessingConfig,
        save_markdown: bool = False,
        temp_dir: Optional[str] = None,
        use_magic_pdf: bool = True,
        cache_dir: Optional[str] = None,
        mineru_api_key: Optional[str] = None,
        mineru_base_url: Optional[str] = None,
    ):
        """
        初始化PPT大纲生成器

        Args:
            config: 处理配置
            save_markdown: 是否保存转换后的Markdown文件
            temp_dir: 自定义temp目录路径
            use_magic_pdf: 是否使用Magic-PDF处理PDF文件（本地处理，优先级高于MarkItDown）
            cache_dir: 缓存目录路径
        """
        self.config = config
        # 根据use_magic_pdf确定处理模式
        processing_mode = "magic_pdf" if use_magic_pdf else "markitdown"

        self.document_processor = DocumentProcessor(
            save_markdown=save_markdown,
            temp_dir=temp_dir,
            use_magic_pdf=use_magic_pdf,
            cache_dir=cache_dir,
            processing_mode=processing_mode,
            mineru_api_key=mineru_api_key,
            mineru_base_url=mineru_base_url,
        )
        self.llm_manager = LLMManager()

        # 初始化LLM
        self.llm = self._initialize_llm()

        # 初始化处理链和工作流
        self.chain_manager = ChainManager(self.llm)
        self.workflow_manager = WorkflowManager(self.chain_manager, self.config)
        self.workflow_executor = WorkflowExecutor(self.workflow_manager)

        self.logger.info(f"PPT生成器初始化完成，使用模型: {config.llm_model}，缓存目录: {cache_dir}，处理模式: {processing_mode}")
    
    def _initialize_llm(self):
        """初始化LLM"""
        try:
            # 构建LLM参数，优先使用配置中的api_key和base_url
            llm_kwargs = {}
            if self.config.api_key:
                llm_kwargs["api_key"] = self.config.api_key
            if self.config.base_url:
                llm_kwargs["base_url"] = self.config.base_url
            if getattr(self.config, "use_responses_api", False):
                llm_kwargs["use_responses_api"] = True
            if getattr(self.config, "enable_reasoning", False):
                llm_kwargs["enable_reasoning"] = True
                llm_kwargs["reasoning_effort"] = getattr(self.config, "reasoning_effort", "medium")
            
            return self.llm_manager.get_llm(
                model=self.config.llm_model,
                provider=self.config.llm_provider,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                **llm_kwargs
            )
        except Exception as e:
            self.logger.error(f"LLM初始化失败: {e}")
            raise
    
    def _build_initial_state(
        self,
        chunks,
        title: Optional[str] = None,
        project_topic: str = "",
        project_scenario: str = "general",
        project_requirements: str = "",
        target_audience: str = "普通大众",
        custom_audience: str = "",
        ppt_style: str = "general",
        custom_style_prompt: str = "",
        page_count_mode: str = "ai_decide",
        min_pages: Optional[int] = None,
        max_pages: Optional[int] = None,
        fixed_pages: Optional[int] = None,
    ) -> PPTState:
        return {
            "document_chunks": chunks,
            "current_index": 0,
            "ppt_title": title or "",
            "slides": [],
            "total_pages": 0,
            "page_count_mode": page_count_mode,
            "document_structure": {},
            "accumulated_context": "",
            "project_topic": project_topic,
            "project_scenario": project_scenario,
            "project_requirements": project_requirements,
            "target_audience": target_audience,
            "custom_audience": custom_audience,
            "ppt_style": ppt_style,
            "custom_style_prompt": custom_style_prompt,
            "min_pages": min_pages,
            "max_pages": max_pages,
            "fixed_pages": fixed_pages,
        }

    async def generate_from_text(
        self,
        text: str,
        title: Optional[str] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        project_topic: str = "",
        project_scenario: str = "general",
        project_requirements: str = "",
        target_audience: str = "普通大众",
        custom_audience: str = "",
        ppt_style: str = "general",
        custom_style_prompt: str = "",
        page_count_mode: str = "ai_decide",
        min_pages: Optional[int] = None,
        max_pages: Optional[int] = None,
        fixed_pages: Optional[int] = None
    ) -> PPTOutline:
        """
        从文本生成PPT大纲
        
        Args:
            text: 输入文本
            title: 可选的标题
            progress_callback: 进度回调函数
            
        Returns:
            PPT大纲对象
        """
        self.logger.info("开始从文本生成PPT大纲...")
        
        if not text.strip():
            raise ValueError("输入文本不能为空")
        
        try:
            # 文档分块
            if progress_callback:
                progress_callback("正在分析文档...", 5)
            
            chunks = self.document_processor.chunk_document(
                text,
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                strategy=self.config.chunk_strategy,
                max_tokens=self.config.max_tokens if self.config.chunk_strategy == ChunkStrategy.FAST else None
            )
            
            self.logger.info(f"文档分块完成，共 {len(chunks)} 个块")
            
            # 准备初始状态
            initial_state: PPTState = {
                "document_chunks": chunks,
                "current_index": 0,
                "ppt_title": title or "",
                "slides": [],
                "total_pages": 0,
                "page_count_mode": page_count_mode,
                "document_structure": {},
                "accumulated_context": "",
                # 项目信息参数
                "project_topic": project_topic,
                "project_scenario": project_scenario,
                "project_requirements": project_requirements,
                "target_audience": target_audience,
                "custom_audience": custom_audience,
                "ppt_style": ppt_style,
                "custom_style_prompt": custom_style_prompt,
                # 页数设置参数
                "min_pages": min_pages,
                "max_pages": max_pages,
                "fixed_pages": fixed_pages
            }
            
            # 执行工作流
            final_state = await self.workflow_executor.execute_with_monitoring(
                initial_state,
                progress_callback
            )
            
            # 转换为PPT大纲对象
            outline = self._state_to_outline(final_state)
            
            self.logger.info(f"PPT大纲生成完成，共 {outline.total_pages} 页")
            return outline
            
        except Exception as e:
            self.logger.error(f"PPT大纲生成失败: {e}")
            raise
    
    async def generate_from_file(
        self,
        file_path: str,
        encoding: Optional[str] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        project_topic: str = "",
        project_scenario: str = "general",
        project_requirements: str = "",
        target_audience: str = "普通大众",
        custom_audience: str = "",
        ppt_style: str = "general",
        custom_style_prompt: str = "",
        page_count_mode: str = "ai_decide",
        min_pages: Optional[int] = None,
        max_pages: Optional[int] = None,
        fixed_pages: Optional[int] = None
    ) -> PPTOutline:
        """
        从文件生成PPT大纲

        Args:
            file_path: 文件路径
            encoding: 文件编码
            progress_callback: 进度回调函数

        Returns:
            PPT大纲对象
        """
        self.logger.info(f"开始从文件生成PPT大纲: {file_path}")

        try:
            # 加载文档（在线程池中执行以避免阻塞主服务）
            if progress_callback:
                progress_callback("正在加载文档...", 2)

            import asyncio
            loop = asyncio.get_running_loop()
            document_info = await loop.run_in_executor(
                None,
                self.document_processor.load_document,
                file_path,
                encoding
            )

            self.logger.info(f"文档加载完成: {document_info.title}")

            # 从文本生成
            return await self.generate_from_text(
                document_info.content,
                document_info.title,
                progress_callback,
                project_topic,
                project_scenario,
                project_requirements,
                target_audience,
                custom_audience,
                ppt_style,
                custom_style_prompt,
                page_count_mode,
                min_pages,
                max_pages,
                fixed_pages
            )

        except Exception as e:
            self.logger.error(f"从文件生成PPT大纲失败: {e}")
            raise
    
    async def stream_generate_from_text(
        self,
        text: str,
        title: Optional[str] = None,
        project_topic: str = "",
        project_scenario: str = "general",
        project_requirements: str = "",
        target_audience: str = "普通大众",
        custom_audience: str = "",
        ppt_style: str = "general",
        custom_style_prompt: str = "",
        page_count_mode: str = "ai_decide",
        min_pages: Optional[int] = None,
        max_pages: Optional[int] = None,
        fixed_pages: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式生成 PPT 大纲，逐步产出状态和 LLM 文本。"""
        self.logger.info("开始从文本流式生成 PPT 大纲...")

        if not text.strip():
            raise ValueError("输入文本不能为空")

        import asyncio

        chunks = self.document_processor.chunk_document(
            text,
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            strategy=self.config.chunk_strategy,
            max_tokens=self.config.max_tokens if self.config.chunk_strategy == ChunkStrategy.FAST else None,
        )

        self.logger.info(f"文档分块完成，共 {len(chunks)} 个块")
        yield {
            "status": {
                "step": "file_process",
                "message": f"文档解析完成，已切分为 {len(chunks)} 个内容块",
                "progress": 0.12,
            }
        }

        state = self._build_initial_state(
            chunks,
            title=title,
            project_topic=project_topic,
            project_scenario=project_scenario,
            project_requirements=project_requirements,
            target_audience=target_audience,
            custom_audience=custom_audience,
            ppt_style=ppt_style,
            custom_style_prompt=custom_style_prompt,
            page_count_mode=page_count_mode,
            min_pages=min_pages,
            max_pages=max_pages,
            fixed_pages=fixed_pages,
        )

        yield {
            "status": {
                "step": "file_process",
                "message": "正在分析文档结构与主题层次...",
                "progress": 0.24,
            }
        }
        structure_state = await self.workflow_manager.nodes.analyze_structure(state, {})
        state = {**state, **structure_state}

        yield {
            "content_reset": True,
            "content_header": "初始大纲生成中",
        }
        yield {
            "status": {
                "step": "generating",
                "message": "LLM 正在生成初始大纲...",
                "progress": 0.35,
            }
        }
        initial_chunk_queue = asyncio.Queue()

        async def _on_initial_chunk(chunk: str) -> None:
            await initial_chunk_queue.put(chunk)

        initial_task = asyncio.create_task(
            self.workflow_manager.nodes.generate_initial_outline_streaming(
                state,
                {},
                chunk_callback=_on_initial_chunk,
            )
        )
        while True:
            if initial_task.done() and initial_chunk_queue.empty():
                break
            try:
                chunk = await asyncio.wait_for(initial_chunk_queue.get(), timeout=0.2)
                if chunk:
                    yield {"content": chunk}
            except asyncio.TimeoutError:
                continue
        state = await initial_task

        total_chunks = len(state.get("document_chunks", []))
        while state.get("current_index", 0) < total_chunks:
            current_index = int(state.get("current_index", 0))
            progress_base = 0.45
            progress_span = 0.4
            refine_progress = progress_base + (current_index / max(total_chunks, 1)) * progress_span

            yield {
                "content_reset": True,
                "content_header": f"细化内容块 {current_index + 1}/{total_chunks}",
            }
            yield {
                "status": {
                    "step": "generating",
                    "message": f"LLM 正在细化大纲内容 ({current_index + 1}/{total_chunks})...",
                    "progress": min(refine_progress, 0.9),
                }
            }

            refine_chunk_queue = asyncio.Queue()

            async def _on_refine_chunk(chunk: str) -> None:
                await refine_chunk_queue.put(chunk)

            refine_task = asyncio.create_task(
                self.workflow_manager.nodes.refine_outline_streaming(
                    state,
                    {},
                    chunk_callback=_on_refine_chunk,
                )
            )

            while True:
                if refine_task.done() and refine_chunk_queue.empty():
                    break
                try:
                    chunk = await asyncio.wait_for(refine_chunk_queue.get(), timeout=0.2)
                    if chunk:
                        yield {"content": chunk}
                except asyncio.TimeoutError:
                    continue

            state = await refine_task

        outline = self._state_to_outline(state)
        llm_call_count = int(
            getattr(getattr(self.workflow_manager, "nodes", None), "chain_executor", None).llm_call_count or 0
        )
        yield {
            "outline_obj": outline,
            "llm_call_count": max(llm_call_count, 0),
        }

    async def stream_generate_from_file(
        self,
        file_path: str,
        encoding: Optional[str] = None,
        project_topic: str = "",
        project_scenario: str = "general",
        project_requirements: str = "",
        target_audience: str = "普通大众",
        custom_audience: str = "",
        ppt_style: str = "general",
        custom_style_prompt: str = "",
        page_count_mode: str = "ai_decide",
        min_pages: Optional[int] = None,
        max_pages: Optional[int] = None,
        fixed_pages: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式从文件生成 PPT 大纲。"""
        self.logger.info(f"开始从文件流式生成 PPT 大纲: {file_path}")
        yield {
            "status": {
                "step": "file_process",
                "message": "正在加载文档内容...",
                "progress": 0.02,
            }
        }

        import asyncio

        loop = asyncio.get_running_loop()
        document_info = await loop.run_in_executor(
            None,
            self.document_processor.load_document,
            file_path,
            encoding,
        )

        self.logger.info(f"文档加载完成: {document_info.title}")
        yield {
            "status": {
                "step": "file_process",
                "message": f"文档已加载：{document_info.title}",
                "progress": 0.08,
            }
        }

        async for event in self.stream_generate_from_text(
            document_info.content,
            document_info.title,
            project_topic=project_topic,
            project_scenario=project_scenario,
            project_requirements=project_requirements,
            target_audience=target_audience,
            custom_audience=custom_audience,
            ppt_style=ppt_style,
            custom_style_prompt=custom_style_prompt,
            page_count_mode=page_count_mode,
            min_pages=min_pages,
            max_pages=max_pages,
            fixed_pages=fixed_pages,
        ):
            yield event

    def _state_to_outline(self, state: Dict[str, Any]) -> PPTOutline:
        """将状态转换为PPT大纲对象"""
        slides = []
        
        for slide_data in state.get("slides", []):
            slide = SlideInfo.from_dict(slide_data)
            slides.append(slide)
        
        return PPTOutline(
            title=state.get("ppt_title", "PPT大纲"),
            total_pages=state.get("total_pages", len(slides)),
            page_count_mode=state.get("page_count_mode", "final"),
            slides=slides
        )
    
    def update_config(self, config: ProcessingConfig):
        """
        更新配置
        
        Args:
            config: 新的处理配置
        """
        self.logger.info("更新生成器配置...")
        
        # 检查是否需要重新初始化LLM
        if (config.llm_model != self.config.llm_model or 
            config.llm_provider != self.config.llm_provider or
            config.temperature != self.config.temperature or
            config.max_tokens != self.config.max_tokens or
            config.use_responses_api != self.config.use_responses_api or
            config.enable_reasoning != self.config.enable_reasoning or
            config.reasoning_effort != self.config.reasoning_effort):
            
            self.config = config
            self.llm = self._initialize_llm()
            self.chain_manager.update_llm(self.llm)
            # 重新创建工作流管理器以传递新配置
            self.workflow_manager = WorkflowManager(self.chain_manager, self.config)
        else:
            self.config = config
    
    def get_supported_formats(self) -> List[str]:
        """获取支持的文件格式"""
        return list(self.document_processor.SUPPORTED_EXTENSIONS.keys())
    
    def validate_input(self, text: str) -> bool:
        """
        验证输入文本
        
        Args:
            text: 输入文本
            
        Returns:
            是否有效
        """
        if not text or not isinstance(text, str):
            return False
        
        # 检查最小长度
        if len(text.strip()) < 100:
            self.logger.warning("输入文本太短，可能影响生成质量")
            return False
        
        # 检查最大长度
        max_length = self.config.chunk_size * 50  # 允许最多50个块
        if len(text) > max_length:
            self.logger.warning(f"输入文本太长 ({len(text)} 字符)，建议分段处理")
        
        return True
    
    async def generate_with_retry(
        self,
        text: str,
        title: Optional[str] = None,
        max_retries: int = 3,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        project_topic: str = "",
        project_scenario: str = "general",
        project_requirements: str = "",
        target_audience: str = "普通大众",
        custom_audience: str = "",
        ppt_style: str = "general",
        custom_style_prompt: str = ""
    ) -> PPTOutline:
        """
        带重试的生成方法
        
        Args:
            text: 输入文本
            title: 可选标题
            max_retries: 最大重试次数
            progress_callback: 进度回调
            
        Returns:
            PPT大纲对象
        """
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.logger.info(f"第 {attempt + 1} 次尝试生成PPT大纲...")
                
                return await self.generate_from_text(
                    text, title, progress_callback,
                    project_topic, project_scenario, project_requirements,
                    target_audience, custom_audience, ppt_style, custom_style_prompt
                )
                
            except Exception as e:
                last_exception = e
                self.logger.warning(f"第 {attempt + 1} 次尝试失败: {e}")
                
                if attempt < max_retries - 1:
                    # 可以在这里添加一些恢复策略
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # 指数退避
        
        self.logger.error(f"所有 {max_retries} 次尝试都失败了")
        raise last_exception
    
    def get_generation_stats(self) -> Dict[str, Any]:
        """获取生成统计信息"""
        return {
            "config": self.config.to_dict(),
            "llm_model": self.config.llm_model,
            "llm_provider": self.config.llm_provider,
            "supported_formats": self.get_supported_formats(),
            "workflow_info": self.workflow_manager.get_workflow_info()
        }
