import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...api.models import (
    PPTGenerationRequest,
    PPTOutline,
    EnhancedPPTOutline,
    SlideContent,
    PPTProject,
    TodoBoard,
    FileOutlineGenerationResponse,
)
from ...ai import get_ai_provider, get_role_provider, AIMessage, MessageRole
from ...ai.base import TextContent, ImageContent
from ...core.config import ai_config, app_config
from .ai_execution import ExecutionContext
from ..prompts import prompts_manager
from ..research.enhanced_research_service import EnhancedResearchService
from ..research.enhanced_report_generator import EnhancedReportGenerator
from ..pyppeteer_pdf_converter import get_pdf_converter
from ..image.image_service import ImageService
from ..image.adapters.ppt_prompt_adapter import PPTSlideContext
from ...utils.thread_pool import run_blocking_io, to_thread


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .runtime_support_service import RuntimeSupportService


class RuntimeResearchService:
    """Research/runtime preview helpers extracted from RuntimeSupportService."""

    def __init__(self, service: "RuntimeSupportService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _initialize_research_services(self):
            """Initialize research services (enhanced + legacy) with best-effort fallbacks."""
            # Always define attributes so call sites can rely on them.
            self.enhanced_research_service = None
            self.enhanced_report_generator = None
            self.research_service = None
            self.report_generator = None

            # Prefer a stable, writable reports directory (instead of relying on CWD).
            reports_dir = None
            try:
                project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
                reports_dir = project_root / "temp" / "research_reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"Failed to create research reports directory, will fall back to CWD: {e}")
                reports_dir = None

            # Enhanced research service (Tavily + SearXNG + content extraction)
            try:
                self.enhanced_research_service = EnhancedResearchService(user_id=self.user_id)
            except Exception as e:
                logger.warning(f"Failed to initialize enhanced research service: {e}")
                self.enhanced_research_service = None

            try:
                if reports_dir is not None:
                    self.enhanced_report_generator = EnhancedReportGenerator(reports_dir=str(reports_dir))
                else:
                    self.enhanced_report_generator = EnhancedReportGenerator()
            except Exception as e:
                logger.warning(f"Failed to initialize enhanced report generator: {e}")
                self.enhanced_report_generator = None

            # Legacy DEEP research service (Tavily-only) used by older workflow paths.
            try:
                from ..deep_research_service import DEEPResearchService
                self.research_service = DEEPResearchService(user_id=self.user_id)
            except Exception as e:
                logger.warning(f"Failed to initialize legacy research service: {e}")
                self.research_service = None

            try:
                from ..research_report_generator import ResearchReportGenerator
                if reports_dir is not None:
                    self.report_generator = ResearchReportGenerator(reports_dir=str(reports_dir))
                else:
                    self.report_generator = ResearchReportGenerator()
            except Exception as e:
                logger.warning(f"Failed to initialize legacy report generator: {e}")
                self.report_generator = None

            # Best-effort status logging (do not fail init based on availability checks).
            try:
                if self.enhanced_research_service is not None:
                    providers = []
                    try:
                        providers = self.enhanced_research_service.get_available_providers()
                    except Exception:
                        providers = []
                    logger.info(
                        "Enhanced research service initialized (user_id=%s, providers=%s)",
                        self.user_id,
                        ", ".join(providers) if providers else "unknown",
                    )
                elif self.research_service is not None:
                    logger.info("Legacy research service initialized (user_id=%s)", self.user_id)
                else:
                    logger.warning("No research service initialized (user_id=%s)", self.user_id)
            except Exception:
                # Never fail initialization on logging.
                pass

    def _get_preferred_outline_research_runtime(self) -> Dict[str, Any]:
            """Return the preferred research runtime for outline generation."""
            enhanced_service = getattr(self, "enhanced_research_service", None)
            if enhanced_service is not None and getattr(enhanced_service, "is_available", lambda: True)():
                return {
                    "service": enhanced_service,
                    "report_generator": getattr(self, "enhanced_report_generator", None),
                    "provider": "enhanced",
                    "is_enhanced": True,
                }

            legacy_service = getattr(self, "research_service", None)
            if legacy_service is not None and getattr(legacy_service, "is_available", lambda: True)():
                return {
                    "service": legacy_service,
                    "report_generator": getattr(self, "report_generator", None),
                    "provider": "legacy",
                    "is_enhanced": False,
                }

            return {
                "service": None,
                "report_generator": None,
                "provider": None,
                "is_enhanced": False,
            }

    def _create_research_context(self, research_report: Any) -> str:
            """
            Convert a research report (DEEP or Enhanced) into a compact Markdown document.

            This Markdown is used as input for the file-based outline generation pipeline.
            """
            topic = getattr(research_report, "topic", "") or "Research"
            language = getattr(research_report, "language", "") or "auto"
            executive_summary = (getattr(research_report, "executive_summary", "") or "").strip()
            key_findings = getattr(research_report, "key_findings", None) or []
            recommendations = getattr(research_report, "recommendations", None) or []
            sources = getattr(research_report, "sources", None) or []

            lines: List[str] = []
            lines.append(f"# Research Report: {topic}")
            lines.append("")
            lines.append(f"- Language: {language}")
            total_duration = getattr(research_report, "total_duration", None)
            if isinstance(total_duration, (int, float)):
                lines.append(f"- Duration: {total_duration:.2f}s")
            lines.append("")

            if executive_summary:
                lines.append("## Executive Summary")
                lines.append("")
                lines.append(executive_summary)
                lines.append("")

            if key_findings:
                lines.append("## Key Findings")
                lines.append("")
                for finding in key_findings:
                    if finding:
                        lines.append(f"- {str(finding).strip()}")
                lines.append("")

            # Include step analyses when present (works for both ResearchStep and EnhancedResearchStep).
            steps = getattr(research_report, "steps", None) or []
            analyses: List[str] = []
            for step in steps:
                analysis = (getattr(step, "analysis", "") or "").strip()
                if analysis:
                    analyses.append(analysis)
            if analyses:
                lines.append("## Analysis Notes")
                lines.append("")
                for analysis in analyses[:10]:
                    lines.append(analysis)
                    lines.append("")

            if recommendations:
                lines.append("## Recommendations")
                lines.append("")
                for rec in recommendations:
                    if rec:
                        lines.append(f"- {str(rec).strip()}")
                lines.append("")

            if sources:
                lines.append("## Sources")
                lines.append("")
                for source in sources[:20]:
                    if source:
                        lines.append(f"- {str(source).strip()}")
                if len(sources) > 20:
                    lines.append(f"- ... and {len(sources) - 20} more")
                lines.append("")

            return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _trim_research_preview_text(text: str, limit: int = 16000) -> str:
            """Keep the research preview rich but bounded for SSE delivery."""
            normalized = (text or "").strip()
            if len(normalized) <= limit:
                return normalized
            return normalized[: limit - 32].rstrip() + "\n\n...[内容较长，已截断显示]"

    @staticmethod
    def _chunk_research_preview_text(text: str, chunk_size: int = 900) -> List[str]:
            if not text:
                return []
            return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    @staticmethod
    def _excerpt_research_preview_text(text: str, limit: int = 320) -> str:
            compact = re.sub(r"\s+", " ", (text or "")).strip()
            if len(compact) <= limit:
                return compact
            return compact[: limit - 3].rstrip() + "..."

    def _build_research_preview_payloads(
            self,
            header: str,
            body: str,
            *,
            status: Optional[Dict[str, Any]] = None,
        ) -> List[Dict[str, Any]]:
            payloads: List[Dict[str, Any]] = []
            if status:
                payloads.append({"status": status})
            payloads.append({
                "content_reset": True,
                "content_header": header,
            })
            trimmed_body = self._trim_research_preview_text(body)
            for chunk in self._chunk_research_preview_text(trimmed_body):
                payloads.append({"content": chunk})
            return payloads

    def iter_research_stream_payloads(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
            """Convert research events into the existing outline SSE payload shape."""
            if not isinstance(event, dict):
                return []

            event_type = str(event.get("type") or "").strip()
            step_number = event.get("step_number")
            total_steps = event.get("total_steps")

            if event_type == "plan":
                plan_items = event.get("plan") or []
                lines = [
                    f"研究主题: {event.get('topic') or ''}",
                    f"语言: {event.get('language') or ''}",
                    "",
                    "研究计划:",
                ]
                for index, item in enumerate(plan_items, 1):
                    query = (item or {}).get("query", "")
                    description = (item or {}).get("description", "")
                    lines.append(f"{index}. 查询: {query}")
                    if description:
                        lines.append(f"   目标: {description}")
                return self._build_research_preview_payloads(
                    "深度研究计划",
                    "\n".join(lines),
                    status={
                        "step": "research_plan",
                        "message": f"正在生成研究计划，共 {len(plan_items)} 个研究维度...",
                        "progress": 0.06,
                    },
                )

            if event_type == "step_started":
                progress = 0.08
                if isinstance(step_number, int) and isinstance(total_steps, int) and total_steps > 0:
                    progress = min(0.55, 0.08 + (step_number - 1) / total_steps * 0.32)
                return [{
                    "status": {
                        "step": "research_step",
                        "message": f"正在执行研究步骤 {step_number}/{total_steps}: {event.get('description') or event.get('query') or ''}",
                        "progress": progress,
                    }
                }]

            if event_type == "search_results":
                lines = [
                    f"步骤: {step_number or '-'}",
                    f"查询: {event.get('query') or ''}",
                    f"目标: {event.get('description') or ''}",
                    "",
                ]

                tavily_results = event.get("tavily_results")
                if not tavily_results and event.get("provider") == "tavily":
                    tavily_results = event.get("results") or []
                if tavily_results:
                    lines.append("Tavily 搜索结果:")
                    for index, result in enumerate(tavily_results[:6], 1):
                        lines.append(f"{index}. {result.get('title') or 'Untitled'}")
                        if result.get("url"):
                            lines.append(f"   URL: {result.get('url')}")
                        snippet = self._excerpt_research_preview_text(result.get("content") or result.get("snippet") or "")
                        if snippet:
                            lines.append(f"   摘要: {snippet}")
                        lines.append("")

                searxng_results = event.get("searxng_results") or {}
                searxng_items = (searxng_results or {}).get("results") or []
                if searxng_items:
                    lines.append("SearXNG 搜索结果:")
                    for index, result in enumerate(searxng_items[:6], 1):
                        lines.append(f"{index}. {result.get('title') or 'Untitled'}")
                        if result.get("url"):
                            lines.append(f"   URL: {result.get('url')}")
                        engine = result.get("engine")
                        if engine:
                            lines.append(f"   引擎: {engine}")
                        snippet = self._excerpt_research_preview_text(result.get("content") or "")
                        if snippet:
                            lines.append(f"   摘要: {snippet}")
                        lines.append("")

                return self._build_research_preview_payloads(
                    f"搜索结果 #{step_number or '?'}",
                    "\n".join(lines).strip(),
                    status={
                        "step": "research_search",
                        "message": f"已获取研究步骤 {step_number or '?'} 的搜索结果，正在整理重点信息...",
                        "progress": 0.18,
                    },
                )

            if event_type == "extracted_content":
                extracted_items = event.get("results") or []
                lines = [
                    f"步骤: {step_number or '-'}",
                    f"查询: {event.get('query') or ''}",
                    "",
                    "网页提取内容:",
                ]
                for index, item in enumerate(extracted_items[:4], 1):
                    lines.append(f"{index}. {item.get('title') or 'Untitled'}")
                    if item.get("url"):
                        lines.append(f"   URL: {item.get('url')}")
                    word_count = item.get("word_count")
                    if word_count:
                        lines.append(f"   字数: {word_count}")
                    excerpt = self._excerpt_research_preview_text(item.get("content") or "", limit=420)
                    if excerpt:
                        lines.append(f"   提取摘要: {excerpt}")
                    lines.append("")

                return self._build_research_preview_payloads(
                    f"网页内容提取 #{step_number or '?'}",
                    "\n".join(lines).strip(),
                    status={
                        "step": "research_extract",
                        "message": f"正在提取并清洗研究步骤 {step_number or '?'} 的网页正文...",
                        "progress": 0.26,
                    },
                )

            if event_type == "llm_start":
                title = event.get("title") or "LLM 实时输出"
                return self._build_research_preview_payloads(
                    str(title),
                    "",
                    status={
                        "step": "research_llm",
                        "message": f"正在生成: {title}",
                        "progress": 0.34,
                    },
                )

            if event_type == "llm_chunk":
                content = event.get("content")
                if not content:
                    return []
                return [{"content": chunk} for chunk in self._chunk_research_preview_text(str(content), chunk_size=700)]

            if event_type == "step_complete":
                duration = event.get("duration")
                duration_text = f"{duration:.2f}s" if isinstance(duration, (int, float)) else "已完成"
                return [{
                    "status": {
                        "step": "research_step_complete",
                        "message": f"研究步骤 {step_number or '?'} 已完成，耗时 {duration_text}",
                        "progress": 0.48,
                    }
                }]

            if event_type == "report_ready":
                lines = ["研究总结已生成。", ""]
                if event.get("executive_summary"):
                    lines.append("执行摘要:")
                    lines.append(str(event["executive_summary"]).strip())
                    lines.append("")
                key_findings = event.get("key_findings") or []
                if key_findings:
                    lines.append("关键发现:")
                    for finding in key_findings[:10]:
                        lines.append(f"- {finding}")
                    lines.append("")
                recommendations = event.get("recommendations") or []
                if recommendations:
                    lines.append("建议:")
                    for recommendation in recommendations[:10]:
                        lines.append(f"- {recommendation}")
                    lines.append("")
                content_analysis = event.get("content_analysis") or {}
                comprehensive_analysis = (content_analysis or {}).get("comprehensive_analysis")
                if comprehensive_analysis:
                    lines.append("综合分析:")
                    lines.append(str(comprehensive_analysis).strip())
                    lines.append("")
                sources = event.get("sources") or []
                if sources:
                    lines.append("参考来源:")
                    for source in sources[:12]:
                        lines.append(f"- {source}")

                return self._build_research_preview_payloads(
                    "深度研究总结",
                    "\n".join(lines).strip(),
                    status={
                        "step": "research_summary",
                        "message": "深度研究完成，正在将研究成果转为大纲...",
                        "progress": 0.62,
                    },
                )

            return []

    def reload_research_config(self):
            """Reload enhanced research service configuration"""
            if hasattr(self, 'enhanced_research_service') and self.enhanced_research_service:
                try:
                    # Enhanced research service doesn't have reload_config method, so reinitialize
                    self._initialize_research_services()
                    logger.info("Enhanced research service configuration reloaded in EnhancedPPTService")
                except Exception as e:
                    logger.warning(f"Failed to reload enhanced research service config: {e}")
                    # If reload fails, reinitialize
                    self._initialize_research_services()
