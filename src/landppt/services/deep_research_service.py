"""
DEEP Research Service - Agent research using Tavily or DeepSeek tools
"""

import asyncio
import ipaddress
import inspect
import json
import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
from tavily import TavilyClient
from ..core.config import ai_config
from ..ai import get_ai_provider
from .prompts.system_prompts import SystemPrompts
from .runtime.ai_execution import scoped_ai_conversation

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


def _normalize_url_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


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


@dataclass
class ResearchAgentAction:
    """One ReAct action chosen by the research agent."""

    thought: str
    action: str
    action_input: Dict[str, Any]
    raw_response: str


class DEEPResearchService:
    """
    DEEP Research Service implementing comprehensive research methodology:
    D - Define research objectives
    E - Explore multiple perspectives
    E - Evaluate sources and evidence
    P - Present comprehensive findings
    """

    def __init__(self, user_id: Optional[int] = None):
        from .research.deepseek_provider import DeepSeekContentProvider

        self.user_id = user_id
        self.deepseek_provider = DeepSeekContentProvider(user_id=user_id)
        self._research_provider = None
        self.tavily_client = None
        self._active_tavily_key_source = None
        self._tavily_client_initialized = False
        # 不在构造函数中初始化，改为懒加载

    def _get_research_provider_sync(self) -> str:
        from .db_config_service import get_db_config_service

        try:
            provider = get_db_config_service().get_config_value_sync(
                "research_provider", user_id=self.user_id
            )
        except Exception:
            provider = None
        return str(provider or ai_config.research_provider or "tavily").strip().lower()

    async def _get_research_provider_async(self) -> str:
        from .db_config_service import get_db_config_service

        try:
            provider = await get_db_config_service().get_config_value(
                "research_provider", user_id=self.user_id
            )
        except Exception:
            provider = None
        return str(provider or ai_config.research_provider or "tavily").strip().lower()

    def _initialize_tavily_client_sync(self):
        """Initialize Tavily client synchronously (fallback)"""
        try:
            current_api_key = _normalize_secret_value(ai_config.tavily_api_key)
            current_base_url = _normalize_url_value(
                getattr(ai_config, "tavily_base_url", None)
            )
            logger.info(
                "Initializing Tavily client with API key: %s",
                _mask_secret_suffix(current_api_key),
            )

            if current_api_key:
                client_kwargs = {"api_key": current_api_key}
                if current_base_url:
                    client_kwargs["api_base_url"] = current_base_url
                self.tavily_client = TavilyClient(**client_kwargs)
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

        runtime_config = await self._get_tavily_runtime_config_async()
        source, api_key = candidates[0]
        return self._create_tavily_client(
            api_key, source, runtime_config.get("base_url")
        )

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
                if await db_config_service.is_user_override(
                    self.user_id, "tavily_api_key"
                ):
                    add_candidate(
                        "user database override",
                        await db_config_service.get_config_value(
                            "tavily_api_key",
                            user_id=self.user_id,
                        ),
                    )

                add_candidate(
                    "system database default",
                    await db_config_service.get_config_value(
                        "tavily_api_key", user_id=None
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to get Tavily API key from database: {e}")

        add_candidate("process environment", ai_config.tavily_api_key)
        return candidates

    async def _get_tavily_runtime_config_async(self) -> Dict[str, Any]:
        config = {
            "base_url": _normalize_url_value(
                getattr(ai_config, "tavily_base_url", None)
            ),
            "max_results": getattr(ai_config, "tavily_max_results", 10),
            "search_depth": getattr(ai_config, "tavily_search_depth", "advanced")
            or "advanced",
            "include_domains": None,
            "exclude_domains": None,
        }

        if ai_config.tavily_include_domains:
            config["include_domains"] = [
                domain.strip()
                for domain in str(ai_config.tavily_include_domains).split(",")
                if domain.strip()
            ]
        if ai_config.tavily_exclude_domains:
            config["exclude_domains"] = [
                domain.strip()
                for domain in str(ai_config.tavily_exclude_domains).split(",")
                if domain.strip()
            ]

        if self.user_id is None:
            return config

        try:
            from ..database.database import AsyncSessionLocal
            from ..database.repositories import UserConfigRepository

            async with AsyncSessionLocal() as session:
                repo = UserConfigRepository(session)
                db_configs = await repo.get_all_configs(self.user_id)

            if "tavily_base_url" in db_configs:
                normalized_db_base_url = _normalize_url_value(
                    db_configs["tavily_base_url"].get("value")
                )
                if normalized_db_base_url:
                    config["base_url"] = normalized_db_base_url
            if "tavily_max_results" in db_configs:
                try:
                    config["max_results"] = max(
                        1, int(float(db_configs["tavily_max_results"].get("value")))
                    )
                except (TypeError, ValueError):
                    pass
            if "tavily_search_depth" in db_configs:
                search_depth = str(
                    db_configs["tavily_search_depth"].get("value") or ""
                ).strip()
                if search_depth:
                    config["search_depth"] = search_depth
        except Exception as e:
            logger.warning(f"Failed to load Tavily runtime config from database: {e}")

        return config

    def _create_tavily_client(
        self, api_key: str, source: str, base_url: Optional[str] = None
    ):
        try:
            client_kwargs = {"api_key": api_key}
            normalized_base_url = _normalize_url_value(base_url)
            if normalized_base_url:
                client_kwargs["api_base_url"] = normalized_base_url
            self.tavily_client = TavilyClient(**client_kwargs)
            self._active_tavily_key_source = source
            logger.info(
                "Tavily client initialized using %s key: %s%s",
                source,
                _mask_secret_suffix(api_key),
                f" via {normalized_base_url}" if normalized_base_url else "",
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
        logger.info("Research service reload completed.")

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
        prompt = SystemPrompts.with_text_cache_prefix(prompt)
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
            logger.warning(
                f"Streaming LLM response failed for stage '{stage}': {stream_error}"
            )
            response = await ai_provider.text_completion(
                prompt=prompt, temperature=temperature
            )
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
                    logger.info(
                        f"DEEPResearchService: Using AI provider from user database config (user_id={self.user_id})"
                    )
                    return provider
            except Exception as e:
                logger.warning(f"Failed to get user AI provider from database: {e}")
                from .managed_provider_service import ManagedProviderError
                if isinstance(e, ManagedProviderError):
                    raise

        # 回退到全局配置
        return get_ai_provider()

    @scoped_ai_conversation("deep-research")
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
        logger.info(f"Starting ReAct DEEP research agent for topic: {topic}")

        try:
            self._research_provider = await self._get_research_provider_async()
            if progress_callback:
                await progress_callback("正在启动深度研究 Agent...", 0.03)

            await self._emit_stream_event(
                event_callback,
                {
                    "type": "agent_loop_start",
                    "strategy": "react",
                    "topic": topic,
                    "language": language,
                    "tools": self._available_research_tool_names(),
                },
            )

            report = await self._run_react_research_agent(
                topic,
                language,
                context,
                start_time=start_time,
                progress_callback=progress_callback,
                event_callback=event_callback,
            )

            if progress_callback:
                source_count = len(report.sources)
                await progress_callback(
                    f"深度研究完成，发现 {source_count} 个来源", 1.0
                )

            logger.info(
                f"ReAct DEEP research completed in {report.total_duration:.2f} seconds"
            )
            return report

        except Exception as e:
            logger.error(f"DEEP research failed: {e}")
            raise

    async def _run_react_research_agent(
        self,
        topic: str,
        language: str,
        context: Optional[Dict[str, Any]],
        *,
        start_time: float,
        progress_callback=None,
        event_callback=None,
    ) -> ResearchReport:
        """Run DEEP research as a ReAct agent loop with tool observations."""
        max_iterations = self._get_agent_max_iterations(context)
        transcript: List[Dict[str, Any]] = []
        research_steps: List[ResearchStep] = []

        for iteration in range(1, max_iterations + 1):
            if progress_callback:
                progress = min(0.85, 0.05 + (iteration - 1) / max_iterations * 0.75)
                await progress_callback(
                    f"Agent 正在推理并选择工具 ({iteration}/{max_iterations})...",
                    progress,
                )

            prompt = self._build_react_agent_prompt(
                topic=topic,
                language=language,
                context=context,
                transcript=transcript,
                max_iterations=max_iterations,
            )
            response_text = await self._collect_llm_response(
                prompt=prompt,
                temperature=0.2,
                event_callback=event_callback,
                stage="research_agent_reasoning",
                title=f"ReAct Agent #{iteration}",
                step_number=iteration,
            )
            action = self._parse_react_action(response_text)

            await self._emit_stream_event(
                event_callback,
                {
                    "type": "agent_iteration",
                    "iteration": iteration,
                    "thought": action.thought,
                    "action": action.action,
                    "action_input": action.action_input,
                },
            )

            if self._is_final_react_action(action.action):
                final_payload = self._normalize_final_payload(
                    action.action_input, response_text
                )
                return await self._build_react_report_from_final(
                    topic=topic,
                    language=language,
                    research_steps=research_steps,
                    final_payload=final_payload,
                    duration=time.time() - start_time,
                    event_callback=event_callback,
                )

            await self._emit_stream_event(
                event_callback,
                {
                    "type": "step_started",
                    "step_number": iteration,
                    "total_steps": max_iterations,
                    "query": self._format_tool_input_for_step(
                        action.action, action.action_input
                    ),
                    "description": f"ReAct tool: {action.action}",
                },
            )
            await self._emit_stream_event(
                event_callback,
                {
                    "type": "tool_call",
                    "iteration": iteration,
                    "tool": action.action,
                    "tool_input": action.action_input,
                    "thought": action.thought,
                },
            )

            if action.action not in self._available_research_tool_names():
                observation = {
                    "success": False,
                    "error": f"Unsupported research tool: {action.action}",
                    "available_tools": self._available_research_tool_names(),
                }
            else:
                observation = await self._execute_research_tool(
                    action.action, action.action_input, language
                )

            results = self._normalize_tool_results(observation)
            observation_text = self._compact_tool_observation(observation)
            step = ResearchStep(
                step_number=iteration,
                query=self._format_tool_input_for_step(
                    action.action, action.action_input
                ),
                description=f"Thought: {action.thought}\nAction: {action.action}",
                results=results,
                analysis=observation_text,
                completed=bool(observation.get("success", False)),
            )
            research_steps.append(step)

            transcript.append(
                {
                    "iteration": iteration,
                    "thought": action.thought,
                    "action": action.action,
                    "action_input": action.action_input,
                    "observation": observation_text,
                }
            )

            await self._emit_stream_event(
                event_callback,
                {
                    "type": "tool_result",
                    "iteration": iteration,
                    "tool": action.action,
                    "success": observation.get("success", False),
                    "observation": observation,
                },
            )
            if action.action in {"tavily_search", "deepseek_search"}:
                await self._emit_stream_event(
                    event_callback,
                    {
                        "type": "search_results",
                        "provider": action.action.removesuffix("_search"),
                        "step_number": iteration,
                        "query": step.query,
                        "description": step.description,
                        "results": results,
                    },
                )
            await self._emit_stream_event(
                event_callback,
                {
                    "type": "step_complete",
                    "step_number": iteration,
                    "query": step.query,
                    "description": step.description,
                    "results_count": len(results),
                    "completed": step.completed,
                },
            )

        logger.warning(
            "ReAct research agent reached max iterations without final answer"
        )
        if progress_callback:
            await progress_callback(
                "Agent 已达到最大轮次，正在根据已有观察生成报告...", 0.9
            )
        return await self._generate_comprehensive_report(
            topic,
            language,
            research_steps,
            time.time() - start_time,
            event_callback=event_callback,
        )

    def _get_agent_max_iterations(self, context: Optional[Dict[str, Any]]) -> int:
        raw_value = (context or {}).get("max_agent_iterations")
        try:
            if raw_value is not None:
                return max(2, min(50, int(raw_value)))
        except (TypeError, ValueError):
            pass
        return 8

    def _available_research_tool_names(self) -> List[str]:
        if (self._research_provider or ai_config.research_provider) == "deepseek":
            return ["deepseek_search", "deepseek_fetch"]
        return [
            "tavily_search",
            "tavily_extract",
            "tavily_crawl",
            "tavily_map",
            "tavily_qna",
            "tavily_context",
            "fetch",
            "curl",
        ]

    def _build_react_agent_prompt(
        self,
        *,
        topic: str,
        language: str,
        context: Optional[Dict[str, Any]],
        transcript: List[Dict[str, Any]],
        max_iterations: int,
    ) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        context_json = json.dumps(
            context or {}, ensure_ascii=False, default=str, indent=2
        )
        scratchpad = self._format_agent_scratchpad(transcript)
        tools = json.dumps(self._research_tool_schemas(), ensure_ascii=False, indent=2)
        use_deepseek = (self._research_provider or ai_config.research_provider) == "deepseek"
        search_tool = "deepseek_search" if use_deepseek else "tavily_search"
        count_field = "count" if use_deepseek else "max_results"
        tool_guidance = (
            "用 deepseek_search 发现资料（query 不超过 128 个字符），用 deepseek_fetch 读取关键来源的 Markdown 正文。"
            if use_deepseek else
            "用 tavily_search 发现资料，用 tavily_extract/fetch/curl 读取关键来源正文。\n"
            "- 可用 tavily_qna/tavily_context 快速获取背景，用 tavily_map/tavily_crawl 探索特定站点。"
        )

        return f"""当前日期/Current date: {today}

你是 LandPPT 的深度研究 Agent。使用 ReAct 策略循环完成研究：
1. Thought: 判断当前还缺什么证据或分析。
2. Action: 从工具列表中选择一个工具。
3. Observation: 系统会执行工具并把结果返回给你。
4. 当证据足够时，Action 使用 final，输出最终报告字段。

研究主题: {topic}
输出语言: {language}
项目上下文:
{context_json}

可用工具:
{tools}

已有 ReAct 轨迹:
{scratchpad or "暂无。请先调用检索或抓取工具。"}

约束:
- 你必须优先调用工具获取外部证据，不要凭空编造来源。
- {tool_guidance}
- 最多 {max_iterations} 轮。证据足够后立即 final。
- 每次只选择一个 action。
- 严格只返回 JSON 对象，不要返回 Markdown 代码块以外的说明。

普通工具调用格式:
{{
  "thought": "为什么下一步要调用这个工具",
  "action": "{search_tool}",
  "action_input": {{"query": "具体查询词", "{count_field}": 5}}
}}

最终回答格式:
{{
  "thought": "为什么证据已经足够",
  "action": "final",
  "action_input": {{
    "executive_summary": "面向 PPT 生成的研究摘要",
    "key_findings": ["关键发现 1", "关键发现 2"],
    "recommendations": ["建议 1", "建议 2"],
    "sources": ["https://example.com/source"]
  }}
}}
"""

    def _research_tool_schemas(self) -> List[Dict[str, Any]]:
        if (self._research_provider or ai_config.research_provider) == "deepseek":
            return [
                {
                    "name": "deepseek_search",
                    "description": "Search the web using DeepSeek's search engine.",
                    "input": {
                        "query": "string, required, 1–128 Unicode characters",
                        "count": "integer, optional, 1–50",
                        "ori_question": "original user question, optional, 1–128 characters",
                        "need_content": "boolean, optional, default false",
                    },
                },
                {
                    "name": "deepseek_fetch",
                    "description": "Fetch a URL's title and Markdown content via DeepSeek.",
                    "input": {"url": "HTTP(S) URL without credentials, required"},
                },
            ]
        return [
            {
                "name": "tavily_search",
                "description": "Tavily web search for discovering relevant sources.",
                "input": {
                    "query": "string, required",
                    "max_results": "integer, optional",
                    "search_depth": "basic|advanced|fast|ultra-fast, optional",
                    "topic": "general|news|finance, optional",
                    "include_raw_content": "boolean or markdown/text, optional",
                },
            },
            {
                "name": "tavily_extract",
                "description": "Extract readable content from one or more URLs via Tavily.",
                "input": {
                    "url": "string, optional",
                    "urls": "array[string], optional",
                    "extract_depth": "basic|advanced, optional",
                    "format": "markdown|text, optional",
                    "query": "string, optional",
                },
            },
            {
                "name": "tavily_crawl",
                "description": "Crawl a website starting from a URL.",
                "input": {
                    "url": "string, required",
                    "max_depth": "integer, optional",
                    "limit": "integer, optional",
                },
            },
            {
                "name": "tavily_map",
                "description": "Map a website and return relevant URLs.",
                "input": {
                    "url": "string, required",
                    "max_depth": "integer, optional",
                    "limit": "integer, optional",
                },
            },
            {
                "name": "tavily_qna",
                "description": "Tavily Q&A search that returns a concise answer.",
                "input": {
                    "query": "string, required",
                    "max_results": "integer, optional",
                },
            },
            {
                "name": "tavily_context",
                "description": "Tavily search context for compact evidence snippets.",
                "input": {
                    "query": "string, required",
                    "max_results": "integer, optional",
                    "max_tokens": "integer, optional",
                },
            },
            {
                "name": "fetch",
                "description": "HTTP fetch and lightweight HTML text extraction for a URL.",
                "input": {
                    "url": "string, required",
                    "timeout": "integer seconds, optional",
                },
            },
            {
                "name": "curl",
                "description": "curl-style HTTP fetch for a URL, implemented without shell interpolation.",
                "input": {
                    "url": "string, required",
                    "timeout": "integer seconds, optional",
                },
            },
        ]

    def _format_agent_scratchpad(self, transcript: List[Dict[str, Any]]) -> str:
        if not transcript:
            return ""

        entries = []
        for item in transcript[-8:]:
            observation = self._truncate_text(str(item.get("observation", "")), 2500)
            entries.append(
                "\n".join(
                    [
                        f"Iteration {item.get('iteration')}:",
                        f"Thought: {item.get('thought', '')}",
                        f"Action: {item.get('action', '')}",
                        f"Action Input: {json.dumps(item.get('action_input', {}), ensure_ascii=False, default=str)}",
                        f"Observation: {observation}",
                    ]
                )
            )
        return "\n\n".join(entries)

    def _parse_react_action(self, response_text: str) -> ResearchAgentAction:
        data = self._extract_json_object(response_text)
        if isinstance(data, dict) and any(
            key in data
            for key in ("action", "tool", "action_input", "thought", "reasoning")
        ):
            action = str(data.get("action") or data.get("tool") or "").strip().lower()
            action_input = data.get("action_input", data.get("input", {}))
            if not isinstance(action_input, dict):
                action_input = {"value": action_input}
            return ResearchAgentAction(
                thought=str(data.get("thought") or data.get("reasoning") or ""),
                action=self._normalize_research_tool_name(action),
                action_input=action_input,
                raw_response=response_text,
            )
        if isinstance(data, dict) and any(
            key in data
            for key in (
                "executive_summary",
                "summary",
                "answer",
                "key_findings",
                "recommendations",
            )
        ):
            return ResearchAgentAction(
                thought="Model returned a final payload.",
                action="final",
                action_input=data,
                raw_response=response_text,
            )

        final_match = re.search(
            r"Final(?: Answer)?:\s*(.+)", response_text, flags=re.IGNORECASE | re.DOTALL
        )
        if final_match:
            return ResearchAgentAction(
                thought="Model returned a final answer.",
                action="final",
                action_input={"executive_summary": final_match.group(1).strip()},
                raw_response=response_text,
            )

        action_match = re.search(
            r"Action:\s*([A-Za-z0-9_\-]+)", response_text, flags=re.IGNORECASE
        )
        input_match = re.search(
            r"Action Input:\s*(.+)", response_text, flags=re.IGNORECASE | re.DOTALL
        )
        thought_match = re.search(
            r"Thought:\s*(.*?)(?:\nAction:|$)",
            response_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if action_match:
            raw_input = input_match.group(1).strip() if input_match else ""
            parsed_input = self._extract_json_object(raw_input)
            action_input = (
                parsed_input if isinstance(parsed_input, dict) else {"value": raw_input}
            )
            return ResearchAgentAction(
                thought=(thought_match.group(1).strip() if thought_match else ""),
                action=self._normalize_research_tool_name(action_match.group(1)),
                action_input=action_input,
                raw_response=response_text,
            )

        return ResearchAgentAction(
            thought="Model did not return a parseable ReAct action.",
            action="invalid",
            action_input={"response": self._truncate_text(response_text, 2000)},
            raw_response=response_text,
        )

    def _extract_json_object(self, text: str) -> Optional[Any]:
        if not text:
            return None
        candidates = [text.strip()]
        candidates.extend(
            match.group(1).strip()
            for match in re.finditer(
                r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE
            )
        )
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start: end + 1])

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    def _normalize_research_tool_name(self, tool_name: str) -> str:
        normalized = str(tool_name or "").strip().lower().replace("-", "_")
        aliases = {
            "search": "tavily_search",
            "tavily": "tavily_search",
            "tavily_answer": "tavily_qna",
            "qna": "tavily_qna",
            "answer": "tavily_qna",
            "extract": "tavily_extract",
            "crawl": "tavily_crawl",
            "map": "tavily_map",
            "get_search_context": "tavily_context",
            "search_context": "tavily_context",
            "http_fetch": "fetch",
            "url_fetch": "fetch",
            "curl_fetch": "curl",
            "finish": "final",
            "final_answer": "final",
        }
        if (self._research_provider or ai_config.research_provider) == "deepseek":
            aliases.update({
                "search": "deepseek_search",
                "deepseek": "deepseek_search",
                "fetch": "deepseek_fetch",
                "extract": "deepseek_fetch",
                "http_fetch": "deepseek_fetch",
                "url_fetch": "deepseek_fetch",
            })
        return aliases.get(normalized, normalized)

    def _is_final_react_action(self, action: str) -> bool:
        return self._normalize_research_tool_name(action) == "final"

    async def _execute_research_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        language: str,
    ) -> Dict[str, Any]:
        tool_name = self._normalize_research_tool_name(tool_name)
        tool_input = self._normalize_tool_input(tool_name, tool_input)

        try:
            if tool_name == "deepseek_search":
                results = await self.deepseek_provider.search(
                    tool_input.get("query", ""),
                    max_results=tool_input.get("count", tool_input.get("max_results")),
                    ori_question=tool_input.get("ori_question"),
                    need_content=tool_input.get("need_content", False),
                )
                return {
                    "success": True,
                    "tool": tool_name,
                    "query": tool_input.get("query", ""),
                    "results": results,
                }
            if tool_name == "deepseek_fetch":
                url = str(tool_input.get("url") or "").strip()
                validation_error = self._validate_public_http_url(url)
                if validation_error:
                    return {
                        "success": False,
                        "tool": tool_name,
                        "error": validation_error,
                    }
                result = await self.deepseek_provider.fetch(url)
                return {"success": True, "tool": tool_name, **result}
            if tool_name == "tavily_search":
                return await self._tool_tavily_search(tool_input, language)
            if tool_name == "tavily_extract":
                return await self._tool_tavily_extract(tool_input)
            if tool_name == "tavily_crawl":
                return await self._tool_tavily_crawl(tool_input)
            if tool_name == "tavily_map":
                return await self._tool_tavily_map(tool_input)
            if tool_name == "tavily_qna":
                return await self._tool_tavily_qna(tool_input)
            if tool_name == "tavily_context":
                return await self._tool_tavily_context(tool_input)
            if tool_name == "fetch":
                return await self._tool_fetch(tool_input)
            if tool_name == "curl":
                return await self._tool_curl(tool_input)
            return {
                "success": False,
                "error": f"Unsupported research tool: {tool_name}",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Research tool '%s' failed: %s", tool_name, exc)
            return {"success": False, "tool": tool_name, "error": str(exc)}

    def _normalize_tool_input(self, tool_name: str, tool_input: Any) -> Dict[str, Any]:
        if isinstance(tool_input, dict):
            return dict(tool_input)
        if isinstance(tool_input, list):
            return {"urls": tool_input}
        key = (
            "url"
            if tool_name
            in {"fetch", "curl", "deepseek_fetch", "tavily_extract", "tavily_crawl", "tavily_map"}
            else "query"
        )
        return {key: "" if tool_input is None else str(tool_input)}

    async def _call_tavily_method_with_config_fallback(
        self,
        method_name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        candidates = await self._get_tavily_api_key_candidates_async()
        if not candidates:
            return {"success": False, "error": "Tavily API key may be missing"}

        runtime_config = await self._get_tavily_runtime_config_async()
        last_auth_error = None
        for index, (source, api_key) in enumerate(candidates):
            tavily_client = self._create_tavily_client(
                api_key, source, runtime_config.get("base_url")
            )
            if not tavily_client:
                continue
            try:
                method = getattr(tavily_client, method_name)
                response = await asyncio.to_thread(method, **params)
                return {
                    "success": True,
                    "method": method_name,
                    "key_source": source,
                    "response": response,
                }
            except Exception as exc:  # noqa: BLE001
                if _is_tavily_auth_error(exc):
                    last_auth_error = exc
                    logger.warning(
                        "Tavily auth failed for %s using %s key", method_name, source
                    )
                    if index + 1 < len(candidates):
                        continue
                logger.warning("Tavily %s failed: %s", method_name, exc)
                return {"success": False, "method": method_name, "error": str(exc)}

        if last_auth_error:
            return {
                "success": False,
                "method": method_name,
                "error": str(last_auth_error),
            }
        return {
            "success": False,
            "method": method_name,
            "error": "Unable to initialize Tavily client",
        }

    async def _tool_tavily_search(
        self, tool_input: Dict[str, Any], language: str
    ) -> Dict[str, Any]:
        query = str(tool_input.get("query") or tool_input.get("value") or "").strip()
        if not query:
            return {
                "success": False,
                "tool": "tavily_search",
                "error": "query is required",
            }

        runtime_config = await self._get_tavily_runtime_config_async()
        params = {
            "query": query,
            "search_depth": tool_input.get("search_depth")
            or runtime_config["search_depth"],
            "max_results": self._coerce_int(
                tool_input.get("max_results"), runtime_config["max_results"], 1, 20
            ),
            "include_answer": tool_input.get("include_answer", True),
            "include_raw_content": tool_input.get("include_raw_content", False),
        }
        for key in (
            "topic",
            "time_range",
            "start_date",
            "end_date",
            "days",
            "country",
            "auto_parameters",
        ):
            if tool_input.get(key) not in (None, ""):
                params[key] = tool_input[key]
        include_domains = tool_input.get("include_domains") or runtime_config.get(
            "include_domains"
        )
        exclude_domains = tool_input.get("exclude_domains") or runtime_config.get(
            "exclude_domains"
        )
        if include_domains:
            params["include_domains"] = self._coerce_string_list(include_domains)
        if exclude_domains:
            params["exclude_domains"] = self._coerce_string_list(exclude_domains)

        call_result = await self._call_tavily_method_with_config_fallback(
            "search", params
        )
        if not call_result.get("success"):
            return {
                "success": False,
                "tool": "tavily_search",
                "query": query,
                "error": call_result.get("error"),
            }

        response = call_result.get("response") or {}
        results = self._normalize_tavily_results(response.get("results", []))
        return {
            "success": True,
            "tool": "tavily_search",
            "query": query,
            "answer": response.get("answer", ""),
            "results": results,
            "key_source": call_result.get("key_source"),
        }

    async def _tool_tavily_extract(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        urls = self._coerce_string_list(
            tool_input.get("urls") or tool_input.get("url") or tool_input.get("value")
        )
        if not urls:
            return {
                "success": False,
                "tool": "tavily_extract",
                "error": "url or urls is required",
            }

        params = {
            "urls": urls,
            "extract_depth": tool_input.get("extract_depth", "advanced"),
            "format": tool_input.get("format", "markdown"),
            "timeout": self._coerce_int(tool_input.get("timeout"), 30, 5, 120),
        }
        if tool_input.get("query"):
            params["query"] = str(tool_input["query"])
        call_result = await self._call_tavily_method_with_config_fallback(
            "extract", params
        )
        if not call_result.get("success"):
            return {
                "success": False,
                "tool": "tavily_extract",
                "urls": urls,
                "error": call_result.get("error"),
            }

        response = call_result.get("response") or {}
        results = self._normalize_tavily_results(response.get("results", []))
        return {
            "success": True,
            "tool": "tavily_extract",
            "urls": urls,
            "results": results,
            "failed_results": response.get("failed_results", []),
            "key_source": call_result.get("key_source"),
        }

    async def _tool_tavily_crawl(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        url = str(tool_input.get("url") or tool_input.get("value") or "").strip()
        if not url:
            return {
                "success": False,
                "tool": "tavily_crawl",
                "error": "url is required",
            }
        params = {
            "url": url,
            "max_depth": self._coerce_int(tool_input.get("max_depth"), 1, 1, 5),
            "limit": self._coerce_int(tool_input.get("limit"), 5, 1, 30),
            "extract_depth": tool_input.get("extract_depth", "basic"),
            "format": tool_input.get("format", "markdown"),
            "timeout": self._coerce_int(tool_input.get("timeout"), 60, 5, 150),
        }
        if tool_input.get("instructions"):
            params["instructions"] = str(tool_input["instructions"])
        call_result = await self._call_tavily_method_with_config_fallback(
            "crawl", params
        )
        return self._format_tavily_structured_response(
            "tavily_crawl", call_result, url=url
        )

    async def _tool_tavily_map(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        url = str(tool_input.get("url") or tool_input.get("value") or "").strip()
        if not url:
            return {"success": False, "tool": "tavily_map", "error": "url is required"}
        params = {
            "url": url,
            "max_depth": self._coerce_int(tool_input.get("max_depth"), 1, 1, 5),
            "limit": self._coerce_int(tool_input.get("limit"), 10, 1, 50),
            "timeout": self._coerce_int(tool_input.get("timeout"), 60, 5, 150),
        }
        if tool_input.get("instructions"):
            params["instructions"] = str(tool_input["instructions"])
        call_result = await self._call_tavily_method_with_config_fallback("map", params)
        return self._format_tavily_structured_response(
            "tavily_map", call_result, url=url
        )

    async def _tool_tavily_qna(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        query = str(tool_input.get("query") or tool_input.get("value") or "").strip()
        if not query:
            return {
                "success": False,
                "tool": "tavily_qna",
                "error": "query is required",
            }
        params = {
            "query": query,
            "search_depth": tool_input.get("search_depth", "advanced"),
            "max_results": self._coerce_int(tool_input.get("max_results"), 5, 1, 20),
            "timeout": self._coerce_int(tool_input.get("timeout"), 60, 5, 120),
        }
        if tool_input.get("topic"):
            params["topic"] = str(tool_input["topic"])
        call_result = await self._call_tavily_method_with_config_fallback(
            "qna_search", params
        )
        if not call_result.get("success"):
            return {
                "success": False,
                "tool": "tavily_qna",
                "query": query,
                "error": call_result.get("error"),
            }
        return {
            "success": True,
            "tool": "tavily_qna",
            "query": query,
            "answer": str(call_result.get("response") or ""),
            "key_source": call_result.get("key_source"),
        }

    async def _tool_tavily_context(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        query = str(tool_input.get("query") or tool_input.get("value") or "").strip()
        if not query:
            return {
                "success": False,
                "tool": "tavily_context",
                "error": "query is required",
            }
        params = {
            "query": query,
            "search_depth": tool_input.get("search_depth", "basic"),
            "max_results": self._coerce_int(tool_input.get("max_results"), 5, 1, 20),
            "max_tokens": self._coerce_int(
                tool_input.get("max_tokens"), 4000, 500, 12000
            ),
            "timeout": self._coerce_int(tool_input.get("timeout"), 60, 5, 120),
        }
        if tool_input.get("topic"):
            params["topic"] = str(tool_input["topic"])
        call_result = await self._call_tavily_method_with_config_fallback(
            "get_search_context", params
        )
        if not call_result.get("success"):
            return {
                "success": False,
                "tool": "tavily_context",
                "query": query,
                "error": call_result.get("error"),
            }
        return {
            "success": True,
            "tool": "tavily_context",
            "query": query,
            "context": str(call_result.get("response") or ""),
            "key_source": call_result.get("key_source"),
        }

    def _format_tavily_structured_response(
        self,
        tool_name: str,
        call_result: Dict[str, Any],
        *,
        url: str,
    ) -> Dict[str, Any]:
        if not call_result.get("success"):
            return {
                "success": False,
                "tool": tool_name,
                "url": url,
                "error": call_result.get("error"),
            }
        response = call_result.get("response") or {}
        results = (
            self._normalize_tavily_results(response.get("results", []))
            if isinstance(response, dict)
            else []
        )
        mapped_urls = (
            self._coerce_string_list(response.get("urls", []))
            if isinstance(response, dict)
            else []
        )
        if not results and mapped_urls:
            results = [
                {
                    "title": "",
                    "url": mapped_url,
                    "content": "",
                    "score": 0,
                    "published_date": "",
                }
                for mapped_url in mapped_urls
            ]
        return {
            "success": True,
            "tool": tool_name,
            "url": url,
            "results": results,
            "response": response,
            "key_source": call_result.get("key_source"),
        }

    async def _tool_fetch(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        url = str(tool_input.get("url") or tool_input.get("value") or "").strip()
        if not url:
            return {"success": False, "tool": "fetch", "error": "url is required"}
        validation_error = self._validate_public_http_url(url)
        if validation_error:
            return {
                "success": False,
                "tool": "fetch",
                "url": url,
                "error": validation_error,
            }

        timeout_seconds = self._coerce_int(tool_input.get("timeout"), 30, 3, 90)
        from .research.content_extractor import WEB_FETCH_HEADER_LIMITS, WEB_FETCH_USER_AGENT

        headers = {
            "User-Agent": WEB_FETCH_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        }
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                headers=headers,
                **WEB_FETCH_HEADER_LIMITS,
            ) as session:
                async with session.get(url, allow_redirects=True) as response:
                    raw_text = await response.text(errors="replace")
                    content_type = response.headers.get("content-type", "")
                    final_url = str(response.url)

            title = ""
            content = raw_text
            if "html" in content_type.lower():
                soup = BeautifulSoup(raw_text, "html.parser")
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
                for node in soup(["script", "style", "noscript"]):
                    node.decompose()
                content = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()

            return {
                "success": 200 <= response.status < 400,
                "tool": "fetch",
                "url": final_url,
                "status": response.status,
                "content_type": content_type,
                "title": title,
                "content": self._truncate_text(content, 12000),
            }
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "tool": "fetch", "url": url, "error": str(exc)}

    async def _tool_curl(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        url = str(tool_input.get("url") or tool_input.get("value") or "").strip()
        if not url:
            return {"success": False, "tool": "curl", "error": "url is required"}
        validation_error = self._validate_public_http_url(url)
        if validation_error:
            return {
                "success": False,
                "tool": "curl",
                "url": url,
                "error": validation_error,
            }

        timeout_seconds = self._coerce_int(tool_input.get("timeout"), 30, 3, 90)
        args = [
            "curl",
            "--location",
            "--silent",
            "--show-error",
            "--compressed",
            "--max-time",
            str(timeout_seconds),
            "--connect-timeout",
            str(min(timeout_seconds, 10)),
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds + 5
            )
            content = stdout.decode("utf-8", errors="replace")
            error_text = stderr.decode("utf-8", errors="replace")
            return {
                "success": proc.returncode == 0,
                "tool": "curl",
                "url": url,
                "returncode": proc.returncode,
                "content": self._truncate_text(content, 12000),
                "stderr": self._truncate_text(error_text, 2000),
            }
        except FileNotFoundError:
            fallback = await self._tool_fetch(tool_input)
            fallback["tool"] = "curl"
            fallback["fallback"] = "fetch"
            return fallback
        except asyncio.TimeoutError:
            return {
                "success": False,
                "tool": "curl",
                "url": url,
                "error": "curl timed out",
            }
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "tool": "curl", "url": url, "error": str(exc)}

    def _validate_public_http_url(self, url: str) -> Optional[str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return "Only http and https URLs are supported"
        if not parsed.hostname:
            return "URL hostname is required"
        hostname = parsed.hostname.lower()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
            ".local"
        ):
            return "Localhost and .local URLs are not allowed"
        try:
            ip_address = ipaddress.ip_address(hostname)
            if (
                ip_address.is_private
                or ip_address.is_loopback
                or ip_address.is_link_local
                or ip_address.is_reserved
            ):
                return "Private, loopback, link-local, and reserved IP URLs are not allowed"
        except ValueError:
            pass
        return None

    def _normalize_tavily_results(self, raw_results: Any) -> List[Dict[str, Any]]:
        normalized_results: List[Dict[str, Any]] = []
        if not isinstance(raw_results, list):
            return normalized_results
        for result in raw_results:
            if isinstance(result, str):
                normalized_results.append(
                    {
                        "title": "",
                        "url": result,
                        "content": "",
                        "score": 0,
                        "published_date": "",
                    }
                )
                continue
            if not isinstance(result, dict):
                continue
            normalized_results.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "content": self._truncate_text(
                        str(
                            result.get("content")
                            or result.get("raw_content")
                            or result.get("text")
                            or ""
                        ),
                        12000,
                    ),
                    "score": result.get("score", 0),
                    "published_date": result.get("published_date", ""),
                }
            )
        return normalized_results

    def _normalize_tool_results(
        self, observation: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if not isinstance(observation, dict):
            return []
        if isinstance(observation.get("results"), list):
            return self._normalize_tavily_results(observation["results"])
        if observation.get("url"):
            return [
                {
                    "title": observation.get("title", ""),
                    "url": observation.get("url", ""),
                    "content": self._truncate_text(
                        str(
                            observation.get("content")
                            or observation.get("answer")
                            or observation.get("context")
                            or ""
                        ),
                        12000,
                    ),
                    "score": 0,
                    "published_date": "",
                }
            ]
        if observation.get("answer") or observation.get("context"):
            return [
                {
                    "title": observation.get("tool", ""),
                    "url": "",
                    "content": self._truncate_text(
                        str(
                            observation.get("answer")
                            or observation.get("context")
                            or ""
                        ),
                        12000,
                    ),
                    "score": 0,
                    "published_date": "",
                }
            ]
        return []

    def _format_tool_input_for_step(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> str:
        if not isinstance(tool_input, dict):
            return str(tool_input)
        for key in ("query", "url", "value"):
            if tool_input.get(key):
                return str(tool_input[key])
        if tool_input.get("urls"):
            return ", ".join(self._coerce_string_list(tool_input["urls"])[:3])
        return json.dumps(tool_input, ensure_ascii=False, default=str)

    def _compact_tool_observation(
        self, observation: Dict[str, Any], max_chars: int = 6000
    ) -> str:
        return self._truncate_text(
            json.dumps(observation, ensure_ascii=False, default=str), max_chars
        )

    async def _build_react_report_from_final(
        self,
        *,
        topic: str,
        language: str,
        research_steps: List[ResearchStep],
        final_payload: Dict[str, Any],
        duration: float,
        event_callback=None,
    ) -> ResearchReport:
        executive_summary = str(
            final_payload.get("executive_summary")
            or final_payload.get("summary")
            or final_payload.get("answer")
            or ""
        ).strip()
        key_findings = self._coerce_string_list(
            final_payload.get("key_findings") or final_payload.get("findings")
        )
        recommendations = self._coerce_string_list(
            final_payload.get("recommendations") or final_payload.get("next_steps")
        )
        sources = self._merge_unique_strings(
            self._coerce_string_list(final_payload.get("sources")),
            self._collect_sources_from_steps(research_steps),
        )

        if not executive_summary:
            executive_summary = (
                "研究 Agent 已完成工具调用，但未返回执行摘要。"
                if language == "zh"
                else "The research agent completed tool calls but returned no executive summary."
            )
        if not key_findings:
            key_findings = self._derive_bullets_from_text(
                executive_summary, max_items=8
            )

        report = ResearchReport(
            topic=topic,
            language=language,
            steps=research_steps,
            executive_summary=executive_summary,
            key_findings=key_findings,
            recommendations=recommendations,
            sources=sources,
            created_at=datetime.now(),
            total_duration=duration,
        )

        await self._emit_stream_event(
            event_callback,
            {
                "type": "report_ready",
                "topic": topic,
                "language": language,
                "executive_summary": executive_summary,
                "key_findings": key_findings,
                "recommendations": recommendations,
                "sources_count": len(sources),
                "strategy": "react",
            },
        )
        return report

    def _normalize_final_payload(
        self, action_input: Dict[str, Any], response_text: str
    ) -> Dict[str, Any]:
        if isinstance(action_input, dict) and action_input:
            if "value" in action_input and len(action_input) == 1:
                parsed = self._extract_json_object(str(action_input["value"]))
                if isinstance(parsed, dict):
                    return parsed
            return action_input
        parsed = self._extract_json_object(response_text)
        if isinstance(parsed, dict):
            payload = parsed.get("action_input")
            if isinstance(payload, dict):
                return payload
        return {"executive_summary": response_text.strip()}

    def _collect_sources_from_steps(
        self, research_steps: List[ResearchStep]
    ) -> List[str]:
        sources: List[str] = []
        for step in research_steps:
            for result in step.results:
                url = result.get("url")
                if url:
                    sources.append(str(url))
        return self._merge_unique_strings(sources)

    def _coerce_string_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            if not value.strip():
                return []
            if "," in value:
                return [item.strip() for item in value.split(",") if item.strip()]
            return [value.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _merge_unique_strings(self, *groups: List[str]) -> List[str]:
        merged: List[str] = []
        seen = set()
        for group in groups:
            for item in group or []:
                text = str(item).strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                merged.append(text)
        return merged

    def _derive_bullets_from_text(self, text: str, max_items: int) -> List[str]:
        bullets = []
        for line in str(text or "").splitlines():
            clean = line.strip().lstrip("-•0123456789.、) ")
            if clean:
                bullets.append(clean)
            if len(bullets) >= max_items:
                break
        if bullets:
            return bullets
        return [self._truncate_text(str(text or ""), 240)] if text else []

    def _coerce_int(self, value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            coerced = int(default)
        return max(minimum, min(maximum, coerced))

    def _truncate_text(self, text: str, max_chars: int) -> str:
        text = "" if text is None else str(text)
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}... [truncated]"

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
        scenario = context.get("scenario", "通用") if context else "通用"
        target_audience = (
            context.get("target_audience", "普通大众") if context else "普通大众"
        )
        requirements = context.get("requirements", "") if context else ""
        ppt_style = context.get("ppt_style", "general") if context else "general"
        description = context.get("description", "") if context else ""

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
            json_start = content.find("[")
            json_end = content.rfind("]") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                research_plan = json.loads(json_str)

                # Validate plan structure
                if isinstance(research_plan, list) and len(research_plan) > 0:
                    for step in research_plan:
                        if (
                            not isinstance(step, dict)
                            or "query" not in step
                            or "description" not in step
                        ):
                            raise ValueError("Invalid research plan structure")

                    logger.info(
                        f"Generated research plan with {len(research_plan)} steps"
                    )
                    return research_plan

            raise ValueError("Failed to parse research plan JSON")

        except Exception as e:
            logger.error(f"Failed to generate AI research plan: {e}")
            raise Exception(
                f"Unable to generate research plan for topic '{topic}': {e}"
            )

        else:
            return [
                {
                    "query": f"{topic} definition concepts overview",
                    "description": "Understanding basic concepts and definitions",
                },
                {
                    "query": f"{topic} current status trends 2024",
                    "description": "Analyzing current status and latest trends",
                },
                {
                    "query": f"{topic} case studies practical applications",
                    "description": "Collecting real cases and practical applications",
                },
                {
                    "query": f"{topic} expert opinions research reports",
                    "description": "Gathering expert opinions and authoritative research",
                },
                {
                    "query": f"{topic} future development predictions",
                    "description": "Exploring future directions and predictions",
                },
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
            search_results = await self._tavily_search(step_plan["query"], language)
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
                step_plan["query"],
                step_plan["description"],
                search_results,
                topic,
                language,
                event_callback=event_callback,
                step_number=step_number,
            )

            step = ResearchStep(
                step_number=step_number,
                query=step_plan["query"],
                description=step_plan["description"],
                results=search_results,
                analysis=analysis,
                completed=True,
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
                query=step_plan["query"],
                description=step_plan["description"],
                results=[],
                analysis=f"研究步骤执行失败: {str(e)}",
                completed=False,
            )

    async def _tavily_search(self, query: str, language: str) -> List[Dict[str, Any]]:
        """Perform search using Tavily API"""
        return await self._tavily_search_with_config_fallback(query, language)

    async def _tavily_search_with_config_fallback(
        self, query: str, language: str
    ) -> List[Dict[str, Any]]:
        candidates = await self._get_tavily_api_key_candidates_async()
        if not candidates:
            raise ValueError("Tavily client not initialized - API key may be missing")

        runtime_config = await self._get_tavily_runtime_config_async()
        search_params = {
            "query": query,
            "search_depth": runtime_config["search_depth"],
            "max_results": runtime_config["max_results"],
            "include_answer": True,
            "include_raw_content": False,
        }
        if runtime_config["include_domains"]:
            search_params["include_domains"] = runtime_config["include_domains"]
        if runtime_config["exclude_domains"]:
            search_params["exclude_domains"] = runtime_config["exclude_domains"]

        last_auth_error = None
        for index, (source, api_key) in enumerate(candidates):
            tavily_client = self._create_tavily_client(
                api_key, source, runtime_config.get("base_url")
            )
            if not tavily_client:
                continue

            try:
                response = tavily_client.search(**search_params)

                results = []
                for result in response.get("results", []):
                    processed_result = {
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "content": result.get("content", ""),
                        "score": result.get("score", 0),
                        "published_date": result.get("published_date", ""),
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
            return (
                "未找到相关搜索结果"
                if language == "zh"
                else "No relevant search results found"
            )
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
            return (
                f"分析失败: {str(e)}"
                if language == "zh"
                else f"Analysis failed: {str(e)}"
            )

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
                    if result.get("url"):
                        all_sources.add(result["url"])

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
                total_duration=duration,
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
            return (
                "执行摘要生成失败"
                if language == "zh"
                else "Executive summary generation failed"
            )

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
            for line in content.split("\n"):
                line = line.strip()
                if line and (
                    line[0].isdigit() or line.startswith("-") or line.startswith("•")
                ):
                    # Remove numbering and clean up
                    clean_finding = line.split(".", 1)[-1].strip()
                    if clean_finding:
                        findings_list.append(clean_finding)

            return findings_list[:8]  # Limit to 8 findings

        except Exception as e:
            logger.error(f"Failed to extract key findings: {e}")
            return (
                ["关键发现提取失败"]
                if language == "zh"
                else ["Key findings extraction failed"]
            )

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
            for line in content.split("\n"):
                line = line.strip()
                if line and (
                    line[0].isdigit() or line.startswith("-") or line.startswith("•")
                ):
                    # Remove numbering and clean up
                    clean_rec = line.split(".", 1)[-1].strip()
                    if clean_rec:
                        recommendations_list.append(clean_rec)

            return recommendations_list[:5]  # Limit to 5 recommendations

        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            return (
                ["建议生成失败"]
                if language == "zh"
                else ["Recommendations generation failed"]
            )

    def is_available(self) -> bool:
        """Check if research service is available"""
        if self._get_research_provider_sync() == "deepseek":
            return self.ai_provider is not None and self.deepseek_provider.is_available()
        return self.is_tavily_available()

    def is_tavily_available(self) -> bool:
        """Whether the Tavily research tools are configured."""
        return self.ai_provider is not None and (
            self.tavily_client is not None
            or bool(_normalize_secret_value(ai_config.tavily_api_key))
        )

    def get_status(self) -> Dict[str, Any]:
        """Get service status information"""
        self._research_provider = self._get_research_provider_sync()
        deepseek_config = self.deepseek_provider.get_config_sync()
        use_deepseek = self._research_provider == "deepseek"
        return {
            "mode": "agent_loop",
            "strategy": "react",
            "tools": self._available_research_tool_names(),
            "tavily_available": self.tavily_client is not None,
            "deepseek_available": bool(deepseek_config["api_key"]),
            "research_provider": self._research_provider,
            "ai_provider_available": self.ai_provider is not None,
            "ai_provider_type": ai_config.default_ai_provider,
            "base_url": (
                deepseek_config["base_url"] if use_deepseek
                else getattr(ai_config, "tavily_base_url", None)
            ),
            "max_results": (
                deepseek_config["max_results"] if use_deepseek
                else ai_config.tavily_max_results
            ),
            "search_depth": None if use_deepseek else ai_config.tavily_search_depth,
        }
