"""SVG 页面生成：提示词 → 模型 → 提取 → 清洗 → 分行 → 检查 → 修复 → 复检。

不可机械修复的缺陷会连同当前 SVG 一起交给模型定点修复，最多三轮。
仍有阻断性缺陷时保留最好的候选但打上降级标记，让"待重新生成"的提示照常出现；
连一个可解析的候选都没有时输出占位页。全程不落 HTML 兜底页，避免污染对照实验。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from ...core.config import ai_config
from ..prompts import prompts_manager
from ..prompts.prompt_utils import should_include_page_numbers
from .svg_page.extract import extract_svg_markup, looks_truncated
from .svg_page.metrics import get_text_measurer
from .svg_page.pipeline import (
    CandidateResult,
    build_placeholder_svg,
    defects_to_prompt_lines,
    process_svg_candidate,
)
from .svg_page.render_mode import (
    RENDER_MODE_HTML,
    RENDER_MODE_SVG,
    attach_render_mode,
    render_mode_from_requirements,
)
from .svg_page.sanitize import SvgSanitizeError
from .svg_page.shell import build_slide_html

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .slide_html_service import SlideHtmlService

SVG_PAGE_MAX_ATTEMPTS = 3
SVG_REPORT_SUFFIX = "_svg_pages.jsonl"
_TEMPLATE_CACHE_KEY = "_cached_selected_global_template"
_IMAGE_URL_KEYS = ("absolute_url", "url")


def collect_image_urls(images_info: Any) -> List[str]:
    """从图片信息里收集页面可引用的地址，作为 ``<image href>`` 的白名单。"""
    urls: List[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _IMAGE_URL_KEYS and isinstance(item, str) and item.strip():
                    urls.append(item.strip())
                else:
                    walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(images_info)
    return list(dict.fromkeys(urls))


class SlideSvgPageService:
    """Extracted SVG page generation for SlideHtmlService."""

    def __init__(self, service: "SlideHtmlService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    # ------------------------------------------------------------------
    # 模式解析
    # ------------------------------------------------------------------
    async def _resolve_render_mode(
        self, project_id: Optional[str], confirmed_requirements: Dict[str, Any]
    ) -> str:
        mode = render_mode_from_requirements(confirmed_requirements)
        if mode is not None:
            return mode
        if not project_id:
            return RENDER_MODE_HTML
        try:
            project = await self.project_manager.get_project(project_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not resolve render mode for project %s: %s", project_id, exc
            )
            project = None
        if project is None:
            return RENDER_MODE_HTML
        return attach_render_mode(confirmed_requirements, project)

    async def _svg_template_html(
        self, project_id: Optional[str], confirmed_requirements: Dict[str, Any]
    ) -> str:
        """SVG 页不继承 HTML 母版结构，只借它提炼设计基因。"""
        template: Any = None
        if (
            isinstance(confirmed_requirements, dict)
            and _TEMPLATE_CACHE_KEY in confirmed_requirements
        ):
            template = confirmed_requirements[_TEMPLATE_CACHE_KEY]
        else:
            if project_id:
                try:
                    template = await self.get_selected_global_template(project_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "SVG page: could not read global template for %s: %s",
                        project_id,
                        exc,
                    )
                    template = None
            if isinstance(confirmed_requirements, dict):
                confirmed_requirements[_TEMPLATE_CACHE_KEY] = template
        if isinstance(template, dict):
            return template.get("html_template", "") or ""
        return ""

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------
    async def _generate_single_slide_svg_with_prompts(
        self,
        slide_data: Dict[str, Any],
        confirmed_requirements: Dict[str, Any],
        system_prompt: str,
        page_number: int,
        total_pages: int,
        all_slides: Optional[List[Dict[str, Any]]] = None,
        existing_slides_data: Optional[List[Dict[str, Any]]] = None,
        project_id: Optional[str] = None,
    ) -> str:
        started = time.monotonic()
        slide_data.pop("_generation_degraded", None)
        slide_data.pop("svg_report", None)
        slide_data["_include_page_numbers"] = should_include_page_numbers(
            confirmed_requirements
        )
        title = str(slide_data.get("title") or f"第{page_number}页")
        report: Dict[str, Any] = {
            "render_mode": RENDER_MODE_SVG,
            "project_id": project_id,
            "page": page_number,
            "total_pages": total_pages,
            "attempts": [],
            "outcome": None,
        }

        try:
            prompt, image_urls = await self._build_svg_prompt(
                slide_data,
                confirmed_requirements,
                page_number,
                total_pages,
                all_slides,
                project_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "SVG page prompt build failed page=%s: %s",
                page_number,
                exc,
                exc_info=True,
            )
            report["outcome"] = "prompt-failed"
            report["error"] = str(exc)
            return self._finish_degraded(
                slide_data, report, page_number, total_pages, title, project_id, started
            )

        measurer = get_text_measurer()
        svg_system_prompt = prompts_manager.get_svg_page_system_prompt()
        temperature = float(getattr(ai_config, "temperature", 0.7))
        best: Optional[CandidateResult] = None
        request_prompt = prompt

        for attempt in range(1, SVG_PAGE_MAX_ATTEMPTS + 1):
            record: Dict[str, Any] = {
                "attempt": attempt,
                "prompt_chars": len(request_prompt),
            }
            attempt_started = time.monotonic()
            try:
                response = await self._text_completion_for_role(
                    "slide_generation",
                    prompt=request_prompt,
                    system_prompt=svg_system_prompt,
                    temperature=temperature,
                )
            except Exception as exc:  # noqa: BLE001
                record["error"] = f"model:{exc}"
                record["elapsed"] = round(time.monotonic() - attempt_started, 2)
                report["attempts"].append(record)
                logger.error(
                    "SVG page model call failed page=%s attempt=%s: %s",
                    page_number,
                    attempt,
                    exc,
                )
                continue

            record["model"] = getattr(response, "model", None)
            record["finish_reason"] = getattr(response, "finish_reason", None)
            record["usage"] = _plain(getattr(response, "usage", None))
            content = getattr(response, "content", "") or ""
            markup = extract_svg_markup(content)
            if not markup:
                record["error"] = "truncated" if looks_truncated(content) else "no-svg"
                record["elapsed"] = round(time.monotonic() - attempt_started, 2)
                report["attempts"].append(record)
                logger.warning(
                    "SVG page=%s attempt=%s returned no usable svg (%s)",
                    page_number,
                    attempt,
                    record["error"],
                )
                request_prompt = self._format_retry_prompt(prompt, record["error"])
                continue

            try:
                candidate = process_svg_candidate(
                    markup, measurer=measurer, allowed_image_urls=image_urls
                )
            except (SvgSanitizeError, ValueError, OverflowError) as exc:
                record["error"] = f"sanitize:{exc}"
                record["elapsed"] = round(time.monotonic() - attempt_started, 2)
                report["attempts"].append(record)
                logger.warning(
                    "SVG page=%s attempt=%s unparsable: %s", page_number, attempt, exc
                )
                request_prompt = f"{prompt}\n\n上一次回复的 SVG 无法解析：{exc}。请输出格式正确的 XML：属性值都加引号、标签全部闭合、不要写注释。"
                continue

            record.update(candidate.summary())
            record["before_repair"] = candidate.before_repair
            record["artifacts"] = self._write_candidate(
                project_id, page_number, attempt, markup, candidate.markup
            )
            record["repairs"] = candidate.repair_actions
            record["elapsed"] = round(time.monotonic() - attempt_started, 2)
            report["attempts"].append(record)
            logger.info(
                "SVG page=%s attempt=%s blocking=%s advisory=%s sanitize_issues=%s repairs=%s coverage=%s",
                page_number,
                attempt,
                len(candidate.blocking),
                len(candidate.advisory),
                len(candidate.sanitize_issues),
                len(candidate.repair_actions),
                candidate.metrics.get("stage_coverage"),
            )

            if best is None or len(candidate.blocking) < len(best.blocking):
                best = candidate
            if not candidate.blocking:
                break
            if attempt < SVG_PAGE_MAX_ATTEMPTS:
                request_prompt = prompts_manager.get_svg_page_repair_prompt(
                    candidate.markup,
                    defects_to_prompt_lines(candidate.blocking),
                    defects_to_prompt_lines(candidate.advisory),
                    page_number,
                    total_pages,
                )
                request_prompt += (
                    "\n\n保留以下原始资料中的事实、语言和页码要求：\n" + prompt
                )

        slide_data["render_mode"] = RENDER_MODE_SVG
        if best is None:
            report["outcome"] = "placeholder"
            return self._finish_degraded(
                slide_data, report, page_number, total_pages, title, project_id, started
            )

        if best.blocking:
            slide_data["_generation_degraded"] = True
            report["outcome"] = "accepted-with-defects"
        else:
            report["outcome"] = "ok"
        report["final"] = best.summary()
        report["elapsed"] = round(time.monotonic() - started, 2)
        slide_data["svg_report"] = report
        self._write_report(project_id, report)
        return build_slide_html(best.markup, title=title)

    def _write_candidate(self, project_id, page_number, attempt, raw, repaired):
        """Keep immutable samples locally; reports contain paths, never duplicate SVG bodies."""
        if not project_id:
            return {}
        try:
            from uuid import uuid4

            directory = (
                Path(self.cache_dirs["style_genes"]) / f"{project_id}_svg_samples"
            )
            directory.mkdir(parents=True, exist_ok=True)
            stem = f"page-{page_number}-attempt-{attempt}-{uuid4().hex[:12]}"
            paths = {}
            for kind, content in (("raw", raw), ("repaired", repaired)):
                target = directory / f"{stem}-{kind}.svg"
                target.write_text(content, encoding="utf-8")
                paths[kind] = str(target)
            return paths
        except Exception as exc:
            logger.warning("Could not save SVG experiment candidate: %s", exc)
            return {}

    # ------------------------------------------------------------------
    async def _build_svg_prompt(
        self,
        slide_data: Dict[str, Any],
        confirmed_requirements: Dict[str, Any],
        page_number: int,
        total_pages: int,
        all_slides: Optional[List[Dict[str, Any]]],
        project_id: Optional[str],
    ) -> Tuple[str, List[str]]:
        template_html = await self._svg_template_html(
            project_id, confirmed_requirements
        )
        style_genes, global_constitution, current_page_brief = (
            await self._get_creative_design_inputs(
                project_id,
                template_html,
                slide_data,
                page_number,
                total_pages,
                confirmed_requirements=confirmed_requirements,
                all_slides=all_slides,
            )
        )
        images_collection = await self._process_slide_image(
            slide_data, confirmed_requirements, page_number, total_pages, template_html
        )
        if (
            images_collection is not None
            and getattr(images_collection, "total_count", 0) > 0
        ):
            slide_data["images_collection"] = images_collection
            slide_data["images_info"] = images_collection.to_dict()
            slide_data["images_summary"] = images_collection.get_summary_for_ai()
        image_urls = collect_image_urls(slide_data.get("images_info"))
        context_info = self._build_slide_context(slide_data, page_number, total_pages)
        prompt = prompts_manager.get_single_slide_svg_prompt(
            slide_data,
            confirmed_requirements,
            page_number,
            total_pages,
            context_info,
            style_genes,
            global_constitution=global_constitution,
            current_page_brief=current_page_brief,
            image_urls=image_urls,
        )
        return prompt, image_urls

    @staticmethod
    def _format_retry_prompt(prompt: str, reason: str) -> str:
        if reason == "truncated":
            hint = (
                "上一次输出在 </svg> 之前被截断。请保留全部内容元素，但精简 defs 里的渐变与装饰、"
                "缩短 path 数据，确保完整输出到 </svg>。"
            )
        else:
            hint = "上一次回复没有包含完整的 <svg>…</svg>。请只输出一个 ```svg 代码块，不要解释文字。"
        return f"{prompt}\n\n{hint}"

    def _finish_degraded(
        self,
        slide_data: Dict[str, Any],
        report: Dict[str, Any],
        page_number: int,
        total_pages: int,
        title: str,
        project_id: Optional[str],
        started: float,
    ) -> str:
        slide_data["_generation_degraded"] = True
        slide_data["render_mode"] = RENDER_MODE_SVG
        points = [str(p) for p in (slide_data.get("content_points") or []) if p]
        placeholder = build_placeholder_svg(title, points, page_number, total_pages)
        report["elapsed"] = round(time.monotonic() - started, 2)
        slide_data["svg_report"] = report
        self._write_report(project_id, report)
        logger.warning(
            "SVG page=%s degraded outcome=%s", page_number, report.get("outcome")
        )
        return build_slide_html(placeholder, title=title)

    def _write_report(self, project_id: Optional[str], report: Dict[str, Any]) -> None:
        """每次生成追加一行 JSONL，供实验脚本聚合；写失败只记日志。"""
        if not project_id:
            return
        try:
            cache_dirs = getattr(self, "cache_dirs", None)
            if not cache_dirs or "style_genes" not in cache_dirs:
                return
            path = cache_dirs["style_genes"] / f"{project_id}{SVG_REPORT_SUFFIX}"
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.debug("SVG page report not written for %s: %s", project_id, exc)


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "__dict__"):
        return {k: _plain(v) for k, v in vars(value).items() if not k.startswith("_")}
    return str(value)
