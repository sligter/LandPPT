"""Deck-wide composition planning without changing the confirmed outline schema."""

import asyncio
import hashlib
import json
import logging
import re
import time

from ..prompts import prompts_manager
from ...core.config import ai_config, resolve_timeout_seconds

logger = logging.getLogger(__name__)
GUIDANCE_VERSION = "composition-v1"
COMPOSITION_FIELDS = (
    "intent",
    "relation",
    "layout_family",
    "focal",
    "content_sufficiency",
    "rhythm",
)


def outline_design_data(slides):
    """Exclude mutable runtime media/status fields from planning and cache keys."""
    fields = (
        "title",
        "subtitle",
        "slide_type",
        "type",
        "content_points",
        "content",
        "chart_config",
        "image_suggestions",
        "notes",
    )
    return [
        {key: slide[key] for key in fields if key in slide}
        for slide in (slides or [])
        if isinstance(slide, dict)
    ]


def guidance_fingerprint(*inputs):
    def stable(value):
        if isinstance(value, dict):
            return {
                k: stable(v) for k, v in value.items() if not str(k).startswith("_")
            }
        if isinstance(value, (list, tuple)):
            return [stable(v) for v in value]
        return value

    payload = json.dumps(
        [GUIDANCE_VERSION, stable(inputs)],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_composition_briefs(raw, total_pages):
    """Accept only a complete, unambiguous mapping of physical page numbers."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    data = json.loads(match.group(1) if match else raw)
    entries = data.get("slides") if isinstance(data, dict) else data
    if not isinstance(entries, list) or len(entries) != total_pages:
        raise ValueError("Composition plan must cover every page")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid composition entry")
        page = entry.get("page")
        if isinstance(page, str) and re.fullmatch(r"[0-9]+", page.strip()):
            page = int(page.strip())
        if type(page) is not int or not 1 <= page <= total_pages or page in result:
            raise ValueError("Invalid or duplicate composition page")
        brief = entry.get("composition_brief")
        if not isinstance(brief, dict) or any(
            not isinstance(brief.get(key), str) or not brief[key].strip()
            for key in COMPOSITION_FIELDS
        ):
            raise ValueError("Incomplete composition brief")
        normalized = {key: brief[key].strip() for key in COMPOSITION_FIELDS}
        normalized["content_sufficiency"] = normalized["content_sufficiency"].lower()
        if normalized["content_sufficiency"] not in {
            "sufficient",
            "focus",
            "missing_evidence",
        }:
            raise ValueError("Invalid content sufficiency")
        result[page] = normalized
    return [
        {"page": page, "composition_brief": result[page]} for page in sorted(result)
    ]


class CompositionPlanningService:
    def __init__(self, owner):
        self.owner = owner
        for name in ("_cached_composition_briefs", "_composition_ready_tasks"):
            if not hasattr(owner, name):
                setattr(owner, name, {})

    async def get_or_generate(
        self, project_id, requirements, slides, total_pages, template_html
    ):
        # A partial outline cannot establish deck-wide rhythm reliably.
        if (
            not slides
            or len(slides) != total_pages
            or any(not isinstance(s, dict) for s in slides)
        ):
            logger.info(
                "Composition availability project=%s source=incomplete_outline "
                "planned_pages=0 expected_pages=%s",
                project_id,
                total_pages,
            )
            return []
        prompt = prompts_manager.design.get_composition_briefs_prompt(
            requirements or {},
            outline_design_data(slides),
            total_pages,
            template_html,
        )
        fingerprint = guidance_fingerprint(prompt)
        key = f"{project_id}:{fingerprint}"
        cache = self.owner._cached_composition_briefs
        cached = cache.get(key)
        # Brief failures are shared by concurrent pages, but never persisted.
        if cached and (cached[1] or time.monotonic() - cached[0] < 30):
            self._log_availability(
                project_id, fingerprint, "memory_cache", cached[1], total_pages
            )
            return cached[1]
        tasks = self.owner._composition_ready_tasks
        if key not in tasks:
            tasks[key] = asyncio.create_task(
                self._generate(project_id, fingerprint, prompt, total_pages)
            )
        task = tasks[key]
        try:
            result = await asyncio.shield(task)
            cache[key] = (time.monotonic(), result)
            return result
        finally:
            if task.done() and tasks.get(key) is task:
                tasks.pop(key, None)

    @staticmethod
    def _log_availability(project_id, fingerprint, source, result, total_pages):
        logger.info(
            "Composition availability project=%s fingerprint=%s source=%s "
            "planned_pages=%s expected_pages=%s",
            project_id,
            fingerprint,
            source,
            len(result),
            total_pages,
        )

    async def _generate(self, project_id, fingerprint, prompt, total_pages):
        cache_file = None
        if project_id and getattr(self.owner, "cache_dirs", None):
            cache_file = (
                self.owner.cache_dirs["style_genes"]
                / f"{project_id}_composition_briefs.json"
            )
        if cache_file and cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Invalid composition cache envelope")
                if data.get("fingerprint") == fingerprint:
                    result = parse_composition_briefs(
                        json.dumps(data["slides"]), total_pages
                    )
                    self._log_availability(
                        project_id, fingerprint, "disk_cache", result, total_pages
                    )
                    return result
            except (ValueError, KeyError, OSError):
                logger.warning("Invalid composition cache for project %s", project_id)
        started = time.monotonic()
        try:
            for attempt in range(1, 3):
                response = await asyncio.wait_for(
                    self.owner._text_completion_for_role(
                        "creative", prompt=prompt, temperature=0.6
                    ),
                    timeout=resolve_timeout_seconds(ai_config.llm_timeout_seconds, 600),
                )
                try:
                    result = parse_composition_briefs(response.content, total_pages)
                    break
                except ValueError as exc:
                    logger.warning(
                        "Composition parse failed project=%s attempt=%s/2 reason=%s",
                        project_id,
                        attempt,
                        exc,
                    )
                    if attempt == 2:
                        raise
            logger.info(
                "Composition planned project=%s pages=%s elapsed_seconds=%.2f",
                project_id,
                total_pages,
                time.monotonic() - started,
            )
            self._log_availability(
                project_id, fingerprint, "generated", result, total_pages
            )
        except Exception as exc:
            logger.warning(
                "Composition planning failed for project %s; using existing guidance: %s",
                project_id,
                exc,
            )
            self._log_availability(project_id, fingerprint, "fallback", [], total_pages)
            return []
        if cache_file:
            try:
                cache_file.write_text(
                    json.dumps(
                        {
                            "fingerprint": fingerprint,
                            "slides": result,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("Cannot persist composition plan: %s", exc)
        return result
