"""
DEEP Research Service - Advanced research functionality using Tavily API
"""

import asyncio
import inspect
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path

from tavily import TavilyClient
from ..core.config import ai_config
from ..ai import get_ai_provider

logger = logging.getLogger(__name__)

_MASKED_SECRET_VALUES = {"********", "••••••••", "***"}


def _normalize_secret_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if normalized in _MASKED_SECRET_VALUES:
        return None
    return normalized


def _mask_secret_suffix(value: Optional[str]) -> str:
    if not value:
        return "None"
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


def _is_tavily_auth_error(error: Exception) -> bool:
    message = str(error).lower()
    auth_markers = (
        "unauthorized",
        "invalid api key",
        "missing api key",
        "missing or invalid api key",
        "invalid_api_key",
    )
    return any(marker in message for marker in auth_markers)

@dataclass
class ResearchStep:
    """Represents a single research step"""
    step_number: int
    query: str
    description: str
    results: List[Dict[str, Any]]
    analysis: str
    completed: bool = False

@dataclass
class ResearchReport:
    """Complete research report"""
    topic: str
    language: str
    steps: List[ResearchStep]
    executive_summary: str
    key_findings: List[str]
    recommendations: List[str]
    sources: List[str]
    created_at: datetime
    total_duration: float

class DEEPResearchService:
    """
    DEEP Research Service implementing comprehensive research methodology:
    D - Define research objectives
    E - Explore multiple perspectives  
    E - Evaluate sources and evidence
    P - Present comprehensive findings
    """
    
    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id
        self.tavily_client = None
        self._active_tavily_key_source = None
        self._tavily_client_initialized = False
        # 不在构造函数中初始化，改为懒加载

    def _initialize_tavily_client_sync(self):
        """Initialize Tavily client synchronously (fallback)"""
        try:
            current_api_key = _normalize_secret_value(ai_config.tavily_api_key)
            logger.info(
                "Initializing Tavily client with API key: %s",
                _mask_secret_suffix(current_api_key),
            )

            if current_api_key:
                self.tavily_client = TavilyClient(api_key=current_api_key)
                logger.info("Tavily client initialized successfully")
            else:
                logger.warning("Tavily API key not found in configuration")
                self.tavily_client = None
        except Exception as e:
            logger.error(f"Failed to initialize Tavily client: {e}")
            self.tavily_client = None
        self._tavily_client_initialized = True

    async def _get_tavily_client_async(self):
        """Get Tavily client, always reading fresh config from user database"""
        # 每次都尝试从数据库读取最新配置，确保配置更新能被及时应用
        candidates = await self._get_tavily_api_key_candidates_async()
        if not candidates:
            logger.warning("Tavily API key not found in any configuration")
            self.tavily_client = None
            self._active_tavily_key_source = None
            return None

        source, api_key = candidates[0]
        return self._create_tavily_client(api_key, source)

        api_key = None
        if self.user_id is not None:
            try:
                from .db_config_service import get_db_config_service
                db_config_service = get_db_config_service()
                user_config = await db_config_service.get_all_config(user_id=self.user_id)
                api_key = user_config.get("tavily_api_key")
                if api_key:
                    logger.info(f"DEEPResearchService: Using Tavily API key from user database (user_id={self.user_id})")
            except Exception as e:
                logger.warning(f"Failed to get Tavily API key from database: {e}")
        
        # 如果数据库没有配置，使用全局配置
        if not api_key:
            api_key = ai_config.tavily_api_key
        
        # 如果 API key 变化了或者客户端未初始化，重新创建客户端
        if api_key:
            try:
                # 总是创建新客户端以使用最新配置
                self.tavily_client = TavilyClient(api_key=api_key)
                logger.info(f"Tavily client initialized with API key: {'***' + api_key[-4:] if len(api_key) > 4 else '***'}")
            except Exception as e:
                logger.error(f"Failed to initialize Tavily client: {e}")
                self.tavily_client = None
        else:
            logger.warning("Tavily API key not found in any configuration")
            self.tavily_client = None
        
        return self.tavily_client

    async def _get_tavily_api_key_candidates_async(self) -> List[Tuple[str, str]]:
        candidates: List[Tuple[str, str]] = []
        seen_keys = set()

        def add_candidate(source: str, value: Any) -> None:
            api_key = _normalize_secret_value(value)
            if not api_key or api_key in seen_keys:
                return
            seen_keys.add(api_key)
            candidates.append((source, api_key))

        if self.user_id is not None:
            try:
                from .db_config_service import get_db_config_service

                db_config_service = get_db_config_service()
                if await db_config_service.is_user_override(self.user_id, "tavily_api_key"):
                    add_candidate(
                        "user database override",
                        await db_config_service.get_config_value(
                            "tavily_api_key",
                            user_id=self.user_id,
                        ),
                    )

                add_candidate(
                    "system database default",
                    await db_config_service.get_config_value("tavily_api_key", user_id=None),
                )
            except Exception as e:
                logger.warning(f"Failed to get Tavily API key from database: {e}")

        add_candidate("process environment", ai_config.tavily_api_key)
        return candidates

    def _create_tavily_client(self, api_key: str, source: str):
        try:
            self.tavily_client = TavilyClient(api_key=api_key)
            self._active_tavily_key_source = source
            logger.info(
                "Tavily client initialized using %s key: %s",
                source,
                _mask_secret_suffix(api_key),
            )
            return self.tavily_client
        except Exception as e:
            logger.error(f"Failed to initialize Tavily client: {e}")
            self.tavily_client = None
            self._active_tavily_key_source = None
            return None


    def reload_config(self):
        """Reload configuration and reinitialize Tavily client"""
        logger.info("Reloading research service configuration...")
        # Clear existing client first
        self.tavily_client = None
        self._active_tavily_key_source = None
        self._tavily_client_initialized = False
        logger.info(f"Research service reload completed.")


    @property
    def ai_provider(self):
        """Dynamically get AI provider to ensure latest config - 同步版本"""
        return get_ai_provider()

    async def _emit_stream_event(self, event_callback, event: Dict[str, Any]) -> None:
        """Best-effort event emission for research streaming."""
        if not event_callback:
            return
        try:
            maybe_awaitable = event_callback(event)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to emit research event: {exc}")

    async def _collect_llm_response(
        self,
        prompt: str,
        *,
        temperature: float,
        event_callback=None,
        stage: str,
        title: str,
        step_number: Optional[int] = None,
    ) -> str:
        """Collect a full LLM response while emitting every visible chunk."""
        await self._emit_stream_event(
            event_callback,
            {
                "type": "llm_start",
                "stage": stage,
                "title": title,
                "step_number": step_number,
            },
        )

        ai_provider = await self.get_ai_provider_async()
        chunks: List[str] = []

        try:
            async for chunk in ai_provider.stream_text_completion(
                prompt=prompt,
                temperature=temperature,
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                await self._emit_stream_event(
                    event_callback,
                    {
                        "type": "llm_chunk",
                        "stage": stage,
                        "title": title,
                        "step_number": step_number,
                        "content": chunk,
                    },
                )
        except Exception as stream_error:  # noqa: BLE001
            logger.warning(f"Streaming LLM response failed for stage '{stage}': {stream_error}")
            response = await ai_provider.text_completion(prompt=prompt, temperature=temperature)
            fallback_content = (response.content or "").strip()
            if fallback_content:
                chunks.append(fallback_content)
                await self._emit_stream_event(
                    event_callback,
                    {
                        "type": "llm_chunk",
                        "stage": stage,
                        "title": title,
                        "step_number": step_number,
                        "content": fallback_content,
                    },
                )

        content = "".join(chunks).strip()
        await self._emit_stream_event(
            event_callback,
            {
                "type": "llm_complete",
                "stage": stage,
                "title": title,
                "step_number": step_number,
                "content_length": len(content),
            },
        )
        return content
    
    async def get_ai_provider_async(self):
        """Get AI provider from user database config - 异步版本"""
        if self.user_id is not None:
            try:
                from .db_config_service import get_user_ai_provider
                provider = await get_user_ai_provider(self.user_id)
                if provider:
                    logger.info(f"DEEPResearchService: Using AI provider from user database config (user_id={self.user_id})")
                    return provider
            except Exception as e:
                logger.warning(f"Failed to get user AI provider from database: {e}")
        
        # 回退到全局配置
        return get_ai_provider()

    
    async def conduct_deep_research(
        self,
        topic: str,
        language: str = "zh",
        context: Optional[Dict[str, Any]] = None,
        progress_callback=None,
        event_callback=None,
    ) -> ResearchReport:
        """
        Conduct comprehensive DEEP research on a given topic

        Args:
            topic: Research topic
            language: Language for research and report (zh/en)
            context: Additional context information (scenario, audience, requirements, etc.)
            progress_callback: Optional async callback(message: str, progress: float) for real-time progress

        Returns:
            Complete research report
        """
        start_time = time.time()
        logger.info(f"Starting DEEP research for topic: {topic}")

        try:
            # Step 1: Define research objectives and generate research plan with context
            if progress_callback:
                await progress_callback("正在制定研究计划...", 0.05)
            research_plan = await self._define_research_objectives(
                topic,
                language,
                context,
                event_callback=event_callback,
            )
            if progress_callback:
                await progress_callback(f"研究计划已生成，共 {len(research_plan)} 个研究维度", 0.1)

            await self._emit_stream_event(
                event_callback,
                {
                    "type": "plan",
                    "topic": topic,
                    "language": language,
                    "plan": research_plan,
                },
            )

            # Step 2: Execute research steps
            research_steps = []
            total_steps = len(research_plan)
            for i, step_plan in enumerate(research_plan, 1):
                if progress_callback:
                    step_progress = 0.1 + (i - 1) / total_steps * 0.7
                    await progress_callback(f"正在研究: {step_plan.get('description', step_plan.get('query', ''))} ({i}/{total_steps})", step_progress)

                await self._emit_stream_event(
                    event_callback,
                    {
                        "type": "step_started",
                        "step_number": i,
                        "total_steps": total_steps,
                        "query": step_plan.get("query", ""),
                        "description": step_plan.get("description", ""),
                    },
                )
                step = await self._execute_research_step(
                    i,
                    step_plan,
                    topic,
                    language,
                    event_callback=event_callback,
                )
                research_steps.append(step)

                # Add delay between requests to respect rate limits
                if i < len(research_plan):
                    await asyncio.sleep(1)

            if progress_callback:
                await progress_callback("正在综合分析研究成果...", 0.85)

            # Step 3: Synthesize findings and generate report
            report = await self._generate_comprehensive_report(
                topic,
                language,
                research_steps,
                time.time() - start_time,
                event_callback=event_callback,
            )

            if progress_callback:
                source_count = len(report.sources)
                await progress_callback(f"深度研究完成，发现 {source_count} 个权威来源", 1.0)

            logger.info(f"DEEP research completed in {report.total_duration:.2f} seconds")
            return report

        except Exception as e:
            logger.error(f"DEEP research failed: {e}")
            raise
    
    async def _define_research_objectives(
        self,
        topic: str,
        language: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        event_callback=None,
    ) -> List[Dict[str, str]]:
        """Define research objectives and create research plan with context"""
        today = datetime.now().strftime("%Y-%m-%d")
        date_hint = f"当前日期/Current date：{today}\n"

        # Extract context information
        scenario = context.get('scenario', '通用') if context else '通用'
        target_audience = context.get('target_audience', '普通大众') if context else '普通大众'
        requirements = context.get('requirements', '') if context else ''
        ppt_style = context.get('ppt_style', 'general') if context else 'general'
        description = context.get('description', '') if context else ''

        # Build context description
        context_info = f"""
项目背景信息：
- 应用场景：{scenario}
- 目标受众：{target_audience}
- 具体要求：{requirements or '无特殊要求'}
- 演示风格：{ppt_style}
- 补充说明：{description or '无'}
"""

        prompt = f"""{date_hint}
作为专业研究员，请根据以下项目信息制定精准的研究计划：

研究主题：{topic}
语言环境：{language}

{context_info}

请基于上述项目背景，生成5-6个针对性的研究步骤，每个步骤应该：

1. **场景适配**：根据应用场景（{scenario}）调整研究重点和深度
2. **受众导向**：考虑目标受众（{target_audience}）的知识背景和关注点
3. **需求匹配**：紧密结合具体要求，确保研究内容的实用性
4. **专业精准**：使用专业术语和关键词，获取高质量权威信息

请严格按照以下JSON格式返回：

```json
[
    {{
        "query": "具体的搜索查询词",
        "description": "这个步骤的研究目标和预期收获"
    }},
    {{
        "query": "另一个搜索查询词",
        "description": "另一个研究目标"
    }}
]
```

要求：
- 查询词要具体、专业，能获取高质量信息
- 根据应用场景和受众特点调整研究角度和深度
- 覆盖基础概念、现状分析、趋势预测、案例研究、专家观点等维度
- 适合{language}语言环境的搜索习惯
- 确保研究内容与项目需求高度匹配
"""

        try:
            content = await self._collect_llm_response(
                prompt=prompt,
                temperature=0.3,
                event_callback=event_callback,
                stage="research_plan",
                title="深度研究计划",
            )

            # Extract JSON from response
            json_start = content.find('[')
            json_end = content.rfind(']') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                research_plan = json.loads(json_str)
                
                # Validate plan structure
                if isinstance(research_plan, list) and len(research_plan) > 0:
                    for step in research_plan:
                        if not isinstance(step, dict) or 'query' not in step or 'description' not in step:
                            raise ValueError("Invalid research plan structure")
                    
                    logger.info(f"Generated research plan with {len(research_plan)} steps")
                    return research_plan
            
            raise ValueError("Failed to parse research plan JSON")
            
        except Exception as e:
            logger.error(f"Failed to generate AI research plan: {e}")
            raise Exception(f"Unable to generate research plan for topic '{topic}': {e}")


        else:
            return [
                {"query": f"{topic} definition concepts overview", "description": "Understanding basic concepts and definitions"},
                {"query": f"{topic} current status trends 2024", "description": "Analyzing current status and latest trends"},
                {"query": f"{topic} case studies practical applications", "description": "Collecting real cases and practical applications"},
                {"query": f"{topic} expert opinions research reports", "description": "Gathering expert opinions and authoritative research"},
                {"query": f"{topic} future development predictions", "description": "Exploring future directions and predictions"}
            ]

    async def _execute_research_step(
        self,
        step_number: int,
        step_plan: Dict[str, str],
        topic: str,
        language: str,
        *,
        event_callback=None,
    ) -> ResearchStep:
        """Execute a single research step"""
        logger.info(f"Executing research step {step_number}: {step_plan['query']}")

        try:
            # Perform Tavily search
            search_results = await self._tavily_search(step_plan['query'], language)
            await self._emit_stream_event(
                event_callback,
                {
                    "type": "search_results",
                    "provider": "tavily",
                    "step_number": step_number,
                    "query": step_plan["query"],
                    "description": step_plan["description"],
                    "results": search_results,
                },
            )

            # Analyze results with AI
            analysis = await self._analyze_search_results(
                step_plan['query'],
                step_plan['description'],
                search_results,
                topic,
                language,
                event_callback=event_callback,
                step_number=step_number,
            )

            step = ResearchStep(
                step_number=step_number,
                query=step_plan['query'],
                description=step_plan['description'],
                results=search_results,
                analysis=analysis,
                completed=True
            )

            await self._emit_stream_event(
                event_callback,
                {
                    "type": "step_complete",
                    "step_number": step_number,
                    "query": step_plan["query"],
                    "description": step_plan["description"],
                    "results_count": len(search_results),
                    "completed": True,
                },
            )

            logger.info(f"Completed research step {step_number}")
            return step

        except Exception as e:
            logger.error(f"Failed to execute research step {step_number}: {e}")
            # Return partial step with error info
            return ResearchStep(
                step_number=step_number,
                query=step_plan['query'],
                description=step_plan['description'],
                results=[],
                analysis=f"研究步骤执行失败: {str(e)}",
                completed=False
            )

    async def _tavily_search(self, query: str, language: str) -> List[Dict[str, Any]]:
        """Perform search using Tavily API"""
        return await self._tavily_search_with_config_fallback(query, language)

    async def _tavily_search_with_config_fallback(self, query: str, language: str) -> List[Dict[str, Any]]:
        candidates = await self._get_tavily_api_key_candidates_async()
        if not candidates:
            raise ValueError("Tavily client not initialized - API key may be missing")

        search_params = {
            "query": query,
            "search_depth": "advanced",
            "max_results": ai_config.tavily_max_results,
            "include_answer": True,
            "include_raw_content": False
        }
        if ai_config.tavily_include_domains:
            search_params["include_domains"] = ai_config.tavily_include_domains.split(',')
        if ai_config.tavily_exclude_domains:
            search_params["exclude_domains"] = ai_config.tavily_exclude_domains.split(',')

        last_auth_error = None
        for index, (source, api_key) in enumerate(candidates):
            tavily_client = self._create_tavily_client(api_key, source)
            if not tavily_client:
                continue

            try:
                response = tavily_client.search(**search_params)

                results = []
                for result in response.get('results', []):
                    processed_result = {
                        'title': result.get('title', ''),
                        'url': result.get('url', ''),
                        'content': result.get('content', ''),
                        'score': result.get('score', 0),
                        'published_date': result.get('published_date', '')
                    }
                    results.append(processed_result)

                logger.info(
                    "Tavily search returned %s results for query: %s (key source: %s)",
                    len(results),
                    query,
                    source,
                )
                return results
            except Exception as e:
                if _is_tavily_auth_error(e):
                    last_auth_error = e
                    logger.warning(
                        "Tavily auth failed for query '%s' using %s key",
                        query,
                        source,
                    )
                    if index + 1 < len(candidates):
                        continue
                logger.error(f"Tavily search failed for query '{query}': {e}")
                return []

        if last_auth_error:
            logger.error(f"Tavily search failed for query '{query}': {last_auth_error}")
        return []

    async def _analyze_search_results(
        self,
        query: str,
        description: str,
        results: List[Dict[str, Any]],
        topic: str,
        language: str,
        *,
        event_callback=None,
        step_number: Optional[int] = None,
    ) -> str:
        """Analyze search results using AI"""
        if not results:
            return "未找到相关搜索结果" if language == "zh" else "No relevant search results found"
        today = datetime.now().strftime("%Y-%m-%d")
        date_hint = f"当前日期/Current date：{today}\n"

        # Prepare results summary for AI analysis
        results_summary = ""
        for i, result in enumerate(results[:5], 1):  # Limit to top 5 results
            results_summary += f"\n{i}. 标题: {result['title']}\n"
            results_summary += f"   来源: {result['url']}\n"
            results_summary += f"   内容摘要: {result['content'][:300]}...\n"

        prompt = f"""{date_hint}
作为专业研究分析师，请分析以下搜索结果：

研究主题：{topic}
搜索查询：{query}
研究目标：{description}

搜索结果：{results_summary}

请提供深入的分析，包括：
1. 关键信息提取和总结
2. 信息的可靠性和权威性评估
3. 与研究目标的相关性分析
4. 发现的重要趋势或模式
5. 需要进一步关注的要点

请用{language}语言撰写分析报告，要求客观、专业、有深度。
"""

        try:
            response_text = await self._collect_llm_response(
                prompt=prompt,
                temperature=0.4,
                event_callback=event_callback,
                stage="research_step_analysis",
                title=f"研究分析 #{step_number or '?'}",
                step_number=step_number,
            )
            return response_text.strip()

        except Exception as e:
            logger.error(f"Failed to analyze search results: {e}")
            return f"分析失败: {str(e)}" if language == "zh" else f"Analysis failed: {str(e)}"

    async def _generate_comprehensive_report(
        self,
        topic: str,
        language: str,
        research_steps: List[ResearchStep],
        duration: float,
        *,
        event_callback=None,
    ) -> ResearchReport:
        """Generate comprehensive research report"""
        logger.info("Generating comprehensive research report")

        try:
            # Collect all findings
            all_findings = []
            all_sources = set()

            for step in research_steps:
                if step.completed and step.analysis:
                    all_findings.append(f"**{step.description}**\n{step.analysis}")

                for result in step.results:
                    if result.get('url'):
                        all_sources.add(result['url'])

            # Generate executive summary and recommendations
            summary_analysis = await self._generate_executive_summary(
                topic,
                language,
                all_findings,
                event_callback=event_callback,
            )

            # Extract key findings and recommendations
            key_findings = await self._extract_key_findings(
                topic,
                language,
                all_findings,
                event_callback=event_callback,
            )
            recommendations = await self._generate_recommendations(
                topic,
                language,
                all_findings,
                event_callback=event_callback,
            )

            report = ResearchReport(
                topic=topic,
                language=language,
                steps=research_steps,
                executive_summary=summary_analysis,
                key_findings=key_findings,
                recommendations=recommendations,
                sources=list(all_sources),
                created_at=datetime.now(),
                total_duration=duration
            )

            await self._emit_stream_event(
                event_callback,
                {
                    "type": "report_ready",
                    "topic": topic,
                    "language": language,
                    "executive_summary": summary_analysis,
                    "key_findings": key_findings,
                    "recommendations": recommendations,
                    "sources_count": len(all_sources),
                },
            )

            logger.info("Research report generated successfully")
            return report

        except Exception as e:
            logger.error(f"Failed to generate research report: {e}")
            raise

    async def _generate_executive_summary(
        self,
        topic: str,
        language: str,
        findings: List[str],
        *,
        event_callback=None,
    ) -> str:
        """Generate executive summary"""
        findings_text = "\n\n".join(findings)
        today = datetime.now().strftime("%Y-%m-%d")
        date_hint = f"当前日期/Current date：{today}\n"

        prompt = f"""{date_hint}
基于以下研究发现，为主题"{topic}"撰写一份执行摘要：

研究发现：
{findings_text}

请撰写一份简洁而全面的执行摘要，包括：
1. 研究主题的核心要点
2. 主要发现的概述
3. 关键趋势和模式
4. 重要结论

要求：
- 使用{language}语言
- 长度控制在200-300字
- 客观、专业、易懂
- 突出最重要的信息
"""

        try:
            return await self._collect_llm_response(
                prompt=prompt,
                temperature=0.3,
                event_callback=event_callback,
                stage="research_summary",
                title="研究执行摘要",
            )
        except Exception as e:
            logger.error(f"Failed to generate executive summary: {e}")
            return "执行摘要生成失败" if language == "zh" else "Executive summary generation failed"

    async def _extract_key_findings(
        self,
        topic: str,
        language: str,
        findings: List[str],
        *,
        event_callback=None,
    ) -> List[str]:
        """Extract key findings from research"""
        findings_text = "\n\n".join(findings)
        today = datetime.now().strftime("%Y-%m-%d")
        date_hint = f"当前日期/Current date：{today}\n"

        prompt = f"""{date_hint}
从以下研究发现中提取5-8个最重要的关键发现：

研究主题：{topic}
研究发现：
{findings_text}

请提取最重要的关键发现，每个发现用一句话概括。

要求：
- 使用{language}语言
- 每个发现独立成句
- 突出最有价值的信息
- 避免重复内容

请按以下格式返回：
1. 第一个关键发现
2. 第二个关键发现
3. 第三个关键发现
...
"""

        try:
            content = await self._collect_llm_response(
                prompt=prompt,
                temperature=0.3,
                event_callback=event_callback,
                stage="research_key_findings",
                title="研究关键发现",
            )

            # Parse numbered list
            content = content.strip()
            findings_list = []
            for line in content.split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                    # Remove numbering and clean up
                    clean_finding = line.split('.', 1)[-1].strip()
                    if clean_finding:
                        findings_list.append(clean_finding)

            return findings_list[:8]  # Limit to 8 findings

        except Exception as e:
            logger.error(f"Failed to extract key findings: {e}")
            return ["关键发现提取失败"] if language == "zh" else ["Key findings extraction failed"]

    async def _generate_recommendations(
        self,
        topic: str,
        language: str,
        findings: List[str],
        *,
        event_callback=None,
    ) -> List[str]:
        """Generate actionable recommendations"""
        findings_text = "\n\n".join(findings)
        today = datetime.now().strftime("%Y-%m-%d")
        date_hint = f"当前日期/Current date：{today}\n"

        prompt = f"""{date_hint}
基于以下研究发现，为主题"{topic}"生成3-5个可行的建议或推荐：

研究发现：
{findings_text}

请生成具体、可行的建议，每个建议应该：
1. 基于研究发现
2. 具有可操作性
3. 对相关人员有实际价值

要求：
- 使用{language}语言
- 每个建议独立成句
- 突出实用性和可行性

请按以下格式返回：
1. 第一个建议
2. 第二个建议
3. 第三个建议
...
"""

        try:
            content = await self._collect_llm_response(
                prompt=prompt,
                temperature=0.4,
                event_callback=event_callback,
                stage="research_recommendations",
                title="研究建议",
            )

            # Parse numbered list
            content = content.strip()
            recommendations_list = []
            for line in content.split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                    # Remove numbering and clean up
                    clean_rec = line.split('.', 1)[-1].strip()
                    if clean_rec:
                        recommendations_list.append(clean_rec)

            return recommendations_list[:5]  # Limit to 5 recommendations

        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            return ["建议生成失败"] if language == "zh" else ["Recommendations generation failed"]

    def is_available(self) -> bool:
        """Check if research service is available"""
        return self.ai_provider is not None and (
            self.tavily_client is not None or bool(_normalize_secret_value(ai_config.tavily_api_key))
        )

    def get_status(self) -> Dict[str, Any]:
        """Get service status information"""
        return {
            "tavily_available": self.tavily_client is not None,
            "ai_provider_available": self.ai_provider is not None,
            "ai_provider_type": ai_config.default_ai_provider,
            "max_results": ai_config.tavily_max_results,
            "search_depth": ai_config.tavily_search_depth
        }
