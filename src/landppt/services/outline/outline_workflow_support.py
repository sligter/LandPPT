"""
Support helpers for file-based outline generation workflows.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def build_validation_requirements(request: Any, outline_title: str) -> Dict[str, Any]:
    return {
        "topic": getattr(request, "topic", None) or outline_title or "Document Presentation",
        "target_audience": getattr(request, "target_audience", None) or "General audience",
        "focus_content": list(getattr(request, "focus_content", []) or []),
        "tech_highlights": list(getattr(request, "tech_highlights", []) or []),
        "page_count_settings": {
            "mode": getattr(request, "page_count_mode", "ai_decide"),
            "min_pages": getattr(request, "min_pages", None),
            "max_pages": getattr(request, "max_pages", None),
            "fixed_pages": getattr(request, "fixed_pages", None),
        },
    }


def build_file_info(request: Any, *, used_summeryanyfile: bool) -> Dict[str, Any]:
    return {
        "filename": request.filename,
        "file_path": request.file_path,
        "processing_mode": request.file_processing_mode,
        "analysis_depth": request.content_analysis_depth,
        "used_summeryanyfile": used_summeryanyfile,
    }


def build_processing_stats(
    request: Any,
    *,
    slides_count: int,
    total_pages: int,
    generator_name: str,
    llm_call_count: int,
) -> Dict[str, Any]:
    return {
        "total_pages": total_pages,
        "page_count_mode": request.page_count_mode,
        "slides_count": slides_count,
        "processing_time": "completed",
        "generator": generator_name,
        "llm_call_count": max(0, int(llm_call_count or 0)),
    }


def get_slides_range_from_request(request: Any) -> tuple[int, int]:
    if request.page_count_mode == "fixed":
        fixed_pages = request.fixed_pages or 10
        return fixed_pages, fixed_pages
    if request.page_count_mode == "custom_range":
        return request.min_pages or 8, request.max_pages or 15
    return 5, 30


def get_chunk_size_from_request(request: Any) -> int:
    if request.content_analysis_depth == "fast":
        return 1500
    if request.content_analysis_depth == "deep":
        return 4000
    return 3000


def get_chunk_strategy_from_request(request: Any):
    try:
        from summeryanyfile.core.models import ChunkStrategy

        if is_enhanced_research_file(request):
            return ChunkStrategy.FAST
        if request.content_analysis_depth == "fast":
            return ChunkStrategy.FAST
        if request.content_analysis_depth == "deep":
            return ChunkStrategy.HYBRID
        return ChunkStrategy.PARAGRAPH
    except ImportError:
        return "paragraph"


def is_enhanced_research_file(request: Any) -> bool:
    try:
        filename = getattr(request, "filename", "") or ""
        file_path = getattr(request, "file_path", "") or ""
        for pattern in ("enhanced_research_", "research_reports/", "enhanced_research"):
            if pattern in filename or pattern in file_path:
                return True

        if file_path and Path(file_path).exists():
            try:
                first_lines = Path(file_path).read_text(encoding="utf-8")[:1000]
            except Exception:
                first_lines = ""
            for indicator in (
                "Enhanced Research Report",
                "# 深度研究报告",
                "## 研究概览",
                "## 核心发现",
                "## 详细分析",
            ):
                if indicator in first_lines:
                    return True
        return False
    except Exception as exc:
        logger.debug("Failed to detect enhanced research file: %s", exc)
        return False


def create_outline_from_file_content(content: str, request: Any) -> Dict[str, Any]:
    try:
        lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
        title = (
            getattr(request, "topic", None)
            or (lines[0] if lines else "Document Presentation")
        ).strip()

        sections = []
        current_section = None
        for line in lines:
            is_heading = (
                line.startswith(tuple(f"{idx}." for idx in range(1, 10)))
                or line.startswith(("#", "##", "###"))
                or (len(line) < 50 and not line.endswith(("。", ".", "?", "!", "；", ";", "：", ":")))
            )
            if is_heading:
                if current_section:
                    sections.append(current_section)
                current_section = {
                    "title": (
                        line.replace("#", "")
                        .replace("1.", "")
                        .replace("2.", "")
                        .replace("3.", "")
                        .strip()
                    ),
                    "content": [],
                }
                continue
            if current_section:
                current_section["content"].append(line)

        if current_section:
            sections.append(current_section)

        slides = [
            {
                "page_number": 1,
                "title": title,
                "content_points": ["Based on uploaded content", "Presenter", "Date"],
                "slide_type": "title",
            }
        ]

        if len(sections) > 1:
            slides.append(
                {
                    "page_number": 2,
                    "title": "Agenda",
                    "content_points": [section["title"] for section in sections[:8]],
                    "slide_type": "agenda",
                }
            )

        for index, section in enumerate(sections[:10], start=len(slides) + 1):
            slides.append(
                {
                    "page_number": index,
                    "title": section["title"],
                    "content_points": section["content"][:5] or ["Key point 1", "Key point 2"],
                    "slide_type": "content",
                }
            )

        slides.append(
            {
                "page_number": len(slides) + 1,
                "title": "Thank You",
                "content_points": ["Thanks for listening", "Questions are welcome"],
                "slide_type": "thankyou",
            }
        )

        if request.page_count_mode == "fixed" and request.fixed_pages:
            target_pages = request.fixed_pages
            slides = slides[:target_pages]
            while len(slides) < target_pages:
                slides.append(
                    {
                        "page_number": len(slides) + 1,
                        "title": f"Supplement {len(slides)}",
                        "content_points": ["Additional point", "Details to expand"],
                        "slide_type": "content",
                    }
                )

        return {
            "title": title,
            "slides": slides,
            "metadata": {
                "scenario": request.scenario,
                "language": getattr(request, "language", "zh"),
                "total_slides": len(slides),
                "generated_with_file": True,
                "file_source": request.filename,
                "page_count_mode": request.page_count_mode,
                "total_pages": len(slides),
                "ppt_style": getattr(request, "ppt_style", "general"),
                "focus_content": list(getattr(request, "focus_content", []) or []),
                "tech_highlights": list(getattr(request, "tech_highlights", []) or []),
                "target_audience": getattr(request, "target_audience", None),
            },
        }
    except Exception as exc:
        logger.error("Failed to create outline from file content: %s", exc)
        return {
            "title": getattr(request, "topic", None) or "Document Presentation",
            "slides": [
                {
                    "page_number": 1,
                    "title": getattr(request, "topic", None) or "Document Presentation",
                    "content_points": ["Based on uploaded content", "Presenter", "Date"],
                    "slide_type": "title",
                }
            ],
            "metadata": {
                "scenario": getattr(request, "scenario", "general"),
                "language": getattr(request, "language", "zh"),
                "total_slides": 1,
                "generated_with_file": False,
                "error": str(exc),
            },
        }
