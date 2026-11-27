"""
Unattended (无人值守) generation pipeline.

Runs the whole authoring chain for one project without any human step:

    outline -> template -> ppt -> speech_script -> narration_audio -> video

The caller chooses how far to go with ``stop_after``; every stage up to and
including that one runs, the rest are reported as "skipped". Progress is written
into the owning ``BackgroundTask`` result so the existing
``GET /api/landppt/tasks/{task_id}`` endpoint and the workspace monitor panel can
poll it, and the final outcome is delivered through the notification service.

The pipeline drives the service layer directly rather than the HTTP routes, so it
works identically inline (web process) and in a queue worker process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .video_explainer import is_video_explainer

logger = logging.getLogger(__name__)

UNATTENDED_TASK_TYPE = "unattended_pipeline"


@dataclass(frozen=True)
class StageSpec:
    id: str
    name: str
    description: str


# Ordered pipeline. `stop_after` must be one of these ids.
STAGE_SPECS: List[StageSpec] = [
    StageSpec("outline", "生成大纲", "根据确认的需求生成 PPT 大纲"),
    StageSpec("template", "选择模板", "为项目选定全局母版模板"),
    StageSpec("ppt", "生成 PPT", "逐页生成幻灯片 HTML"),
    StageSpec("speech_script", "生成演讲稿", "为每页生成演讲稿"),
    StageSpec("narration_audio", "生成配音", "将演讲稿合成为语音"),
    StageSpec("video", "导出讲解视频", "合成带字幕的讲解视频"),
]

STAGE_IDS: List[str] = [spec.id for spec in STAGE_SPECS]
STAGE_NAMES: Dict[str, str] = {spec.id: spec.name for spec in STAGE_SPECS}
DEFAULT_STOP_AFTER = "ppt"

# TTS providers an unattended run can actually drive. `comfyuiapi` is excluded on
# purpose: it raises unless given a reference audio file, and nothing in an
# unattended run can supply one.
DEFAULT_TTS_PROVIDER = "edge_tts"
SUPPORTED_TTS_PROVIDERS = ("edge_tts", "xiaomimimo", "custom_tts_api")

# How the template stage decides which template to use.
#   auto   - the user's default global master template
#   global - a specific global master template (template_id)
#   free   - an AI template generated from this project's outline
TEMPLATE_MODES = ("auto", "global", "free")


class UnattendedCancelled(Exception):
    """Raised internally when a cancellation request is observed between stages."""


def normalize_stop_after(value: Optional[str]) -> str:
    """Coerce an arbitrary stop_after value to a valid stage id."""
    candidate = (value or "").strip().lower()
    return candidate if candidate in STAGE_IDS else DEFAULT_STOP_AFTER


def planned_stage_ids(stop_after: Optional[str]) -> List[str]:
    """Stage ids that will actually run for the given stop_after."""
    stop = normalize_stop_after(stop_after)
    return STAGE_IDS[: STAGE_IDS.index(stop) + 1]


def build_config(raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize a user/UI supplied config dict into the shape the runner expects."""
    raw = raw or {}

    def _flag(key: str, default: bool) -> bool:
        value = raw.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return bool(value)

    template_id = raw.get("template_id")
    try:
        template_id = int(template_id) if template_id not in (None, "", "auto") else None
    except (TypeError, ValueError):
        template_id = None

    template_mode = str(raw.get("template_mode") or "").strip().lower()
    if template_mode not in TEMPLATE_MODES:
        # Legacy/implicit form: a bare template_id means "use this global template".
        template_mode = "global" if template_id else "auto"
    if template_mode == "global" and not template_id:
        # "指定模板" without an id is just the default pick.
        template_mode = "auto"
    if template_mode != "global":
        template_id = None

    fps = 60 if str(raw.get("fps") or "30").strip() == "60" else 30
    render_mode = str(raw.get("render_mode") or "live").strip().lower()
    if render_mode not in ("live", "static"):
        render_mode = "live"

    provider = (str(raw.get("tts_provider") or "").strip().lower() or DEFAULT_TTS_PROVIDER)
    if provider not in SUPPORTED_TTS_PROVIDERS:
        # comfyuiapi hard-requires a reference audio file, which an unattended run has
        # no way to supply, so it would fail on the first slide every time.
        logger.warning(
            "TTS provider %r is not usable unattended; falling back to %s",
            provider, DEFAULT_TTS_PROVIDER,
        )
        provider = DEFAULT_TTS_PROVIDER

    return {
        "stop_after": normalize_stop_after(raw.get("stop_after")),
        "language": (str(raw.get("language") or "zh").strip().lower() or "zh"),
        "template_mode": template_mode,
        "template_id": template_id,
        "tts_provider": provider,
        "tts_voice": (str(raw.get("tts_voice") or "").strip() or None),
        "tts_rate": (str(raw.get("tts_rate") or "+0%").strip() or "+0%"),
        "fps": fps,
        "render_mode": render_mode,
        "embed_subtitles": _flag("embed_subtitles", True),
        "notify_in_app": _flag("notify_in_app", True),
        "notify_email": _flag("notify_email", False),
        "speech_requirements": str(raw.get("speech_requirements") or "").strip(),
        "target_duration_seconds": raw.get("target_duration_seconds"),
        "max_duration_seconds": raw.get("max_duration_seconds"),
        "start_from": raw.get("start_from"),
        "request_id": raw.get("request_id"),
    }


CONFIG_KEY_DEFAULTS = {
    "unattended_default_stop_stage": DEFAULT_STOP_AFTER,
    "unattended_notify_in_app": True,
    "unattended_notify_email": False,
    "unattended_tts_provider": "edge_tts",
    "unattended_video_fps": 30,
    "unattended_video_render_mode": "live",
}


async def load_config_defaults(user_id: Optional[int]) -> Dict[str, Any]:
    """Read the user's saved unattended defaults, falling back to the built-ins."""
    resolved = dict(CONFIG_KEY_DEFAULTS)
    try:
        from .db_config_service import get_db_config_service

        # One resolved read: get_config_value opens its own session per key, and the
        # creation page calls this on every load.
        stored = await get_db_config_service().get_all_config(user_id=user_id)
        for key in CONFIG_KEY_DEFAULTS:
            value = stored.get(key)
            if value is not None and value != "":
                resolved[key] = value
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falling back to built-in unattended defaults: %s", exc)

    return {
        "stop_after": normalize_stop_after(str(resolved["unattended_default_stop_stage"])),
        "notify_in_app": resolved["unattended_notify_in_app"],
        "notify_email": resolved["unattended_notify_email"],
        "tts_provider": str(resolved["unattended_tts_provider"]),
        "fps": resolved["unattended_video_fps"],
        "render_mode": str(resolved["unattended_video_render_mode"]),
    }


def _cancel_cache_key(project_id: str) -> str:
    return f"unattended_cancel:{project_id}"


async def request_cancel(project_id: str) -> bool:
    """Ask a running pipeline to stop at the next stage boundary."""
    _LOCAL_CANCEL_FLAGS[project_id] = True
    try:
        from .cache_service import get_cache_service

        cache = await get_cache_service()
        if cache and cache.is_connected:
            await cache.set(_cancel_cache_key(project_id), "1", ttl=3600)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not set distributed unattended cancel flag for %s: %s", project_id, exc)
    return True


async def clear_cancel(project_id: str) -> bool:
    """Clear a previously set cancellation request."""
    _LOCAL_CANCEL_FLAGS.pop(project_id, None)
    try:
        from .cache_service import get_cache_service

        cache = await get_cache_service()
        if cache and cache.is_connected:
            await cache.delete(_cancel_cache_key(project_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not clear distributed unattended cancel flag for %s: %s", project_id, exc)
    return True


async def is_cancelled(project_id: str) -> bool:
    if _LOCAL_CANCEL_FLAGS.get(project_id):
        return True
    try:
        from .cache_service import get_cache_service

        cache = await get_cache_service()
        if cache and cache.is_connected:
            return bool(await cache.get(_cancel_cache_key(project_id)))
    except Exception:  # noqa: BLE001
        return False
    return False


# Cancellation is cooperative; the cache mirror covers multi-worker deployments and
# this dict covers the single-process/no-cache case.
_LOCAL_CANCEL_FLAGS: Dict[str, bool] = {}


@dataclass
class StageState:
    id: str
    name: str
    status: str = "pending"  # pending | running | completed | failed | skipped | cancelled
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "progress": round(float(self.progress), 2),
            "message": self.message,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "detail": self.detail,
        }


ProgressCallback = Callable[[float, Dict[str, Any]], Any]


class UnattendedPipelineRunner:
    """Executes the ordered pipeline for one project."""

    def __init__(
        self,
        *,
        project_id: str,
        user_id: int,
        config: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        task_id: Optional[str] = None,
    ):
        self.project_id = project_id
        self.user_id = int(user_id)
        # Artifact rows are keyed by task id when the runner is driven by a task.
        self.task_id = task_id
        self.config = build_config(config)
        self.stop_after = self.config["stop_after"]
        self.language = self.config["language"]
        self._progress_callback = progress_callback
        self.planned = planned_stage_ids(self.stop_after)
        if self.config["start_from"] == "speech_script":
            self.planned = [stage for stage in self.planned if stage in STAGE_IDS[3:]]
        self.stages: Dict[str, StageState] = {
            spec.id: StageState(
                id=spec.id,
                name=spec.name,
                status="pending" if spec.id in self.planned else "skipped",
                message="" if spec.id in self.planned else "未选择该阶段",
            )
            for spec in STAGE_SPECS
        }
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.status = "running"
        self.error: Optional[str] = None
        self.artifact_id: Optional[str] = None
        self._narration_audio = None
        self.topic: str = ""
        # Set when a stage ends the run, so current_stage_id keeps naming it.
        self._terminal_stage_id: Optional[str] = None
        # Strong refs for fire-and-forget progress updates; asyncio only keeps weak
        # references, so an unreferenced task can be garbage collected mid-flight.
        self._pending_updates: set = set()

    # ------------------------------------------------------------------ state

    def snapshot(self) -> Dict[str, Any]:
        """The payload persisted into the task result and rendered by the UI."""
        return {
            "success": self.status == "completed",
            "unattended": True,
            "project_id": self.project_id,
            "topic": self.topic,
            "status": self.status,
            "stop_after": self.stop_after,
            "request_id": self.config["request_id"],
            "stop_after_name": STAGE_NAMES.get(self.stop_after, self.stop_after),
            "language": self.language,
            "planned_stages": list(self.planned),
            "stages": [self.stages[spec.id].to_dict() for spec in STAGE_SPECS],
            "current_stage": self.current_stage_id(),
            "overall_progress": self.overall_progress(),
            "error": self.error,
            "artifact_id": self.artifact_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def current_stage_id(self) -> Optional[str]:
        # Once a stage has failed it stays the current stage: reporting the next
        # (never-run) stage would make the UI blame the wrong step.
        if self._terminal_stage_id:
            return self._terminal_stage_id
        for stage_id in self.planned:
            if self.stages[stage_id].status in ("running", "pending"):
                return stage_id
        return None

    def overall_progress(self) -> float:
        if not self.planned:
            return 100.0
        total = 0.0
        for stage_id in self.planned:
            stage = self.stages[stage_id]
            if stage.status == "completed":
                total += 100.0
            elif stage.status == "running":
                total += max(0.0, min(100.0, stage.progress))
            elif stage.status in ("failed", "cancelled"):
                # Contribute only the work actually done, and never a full 100: the
                # last progress tick before a failure can legitimately have been 100
                # (e.g. the final page was emitted, then the stage failed overall),
                # and a run that aborted must never read as fully complete.
                total += max(0.0, min(99.0, stage.progress))
        return round(total / len(self.planned), 2)

    async def _publish(self) -> None:
        if self._progress_callback is None:
            return
        try:
            result = self._progress_callback(self.overall_progress(), self.snapshot())
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            logger.debug("Unattended progress callback failed: %s", exc)

    async def _set_stage(
        self,
        stage_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        stage = self.stages[stage_id]
        if status is None and stage.status in ("completed", "failed", "cancelled", "skipped"):
            # A late progress tick (e.g. a speech-script callback scheduled just
            # before the stage finished) must not reopen a settled stage.
            return

        if status is not None:
            if status == "running" and stage.started_at is None:
                stage.started_at = time.time()
            if status in ("completed", "failed", "cancelled", "skipped"):
                stage.finished_at = time.time()
            stage.status = status
        if progress is not None:
            value = max(0.0, min(100.0, float(progress)))
            # Progress must not go backwards within a stage: the outline stream
            # resets to 0 when it switches from generating to validating, which
            # would otherwise drag the whole run's bar down mid-flight.
            stage.progress = value if status is not None else max(stage.progress, value)
        if status == "completed":
            stage.progress = 100.0
        if message is not None:
            stage.message = message
        if error is not None:
            stage.error = error
        if detail:
            stage.detail.update(detail)
        await self._publish()

    async def _check_cancelled(self) -> None:
        if await is_cancelled(self.project_id):
            raise UnattendedCancelled()

    async def _mark_cancelled(self) -> None:
        self.status = "cancelled"
        self.error = "任务已取消"
        if self._terminal_stage_id is None:
            self._terminal_stage_id = self.current_stage_id()
        for stage_id in self.planned:
            if self.stages[stage_id].status in ("pending", "running"):
                await self._set_stage(stage_id, status="cancelled", message="已取消")

    def _track_update(self, coro) -> None:
        """Schedule a state update from a synchronous callback, keeping a ref."""
        task = asyncio.get_running_loop().create_task(coro)
        self._pending_updates.add(task)
        task.add_done_callback(self._pending_updates.discard)

    # -------------------------------------------------------------- execution

    async def run(self) -> Dict[str, Any]:
        """Run the pipeline. Always returns a snapshot; never raises."""
        from ..auth.request_context import current_user_id

        ctx_token = None
        try:
            if current_user_id.get() != self.user_id:
                ctx_token = current_user_id.set(self.user_id)
        except Exception:  # noqa: BLE001
            ctx_token = None

        try:
            # NOTE: the cancel flag is deliberately NOT cleared here. In queue mode a
            # user can cancel while the job is still waiting for a worker, and clearing
            # on start would discard that request. Submission clears any stale flag.
            await self._check_cancelled()
            # Resolve the topic up front so progress payloads and the terminal
            # notification can name the project even if stage 1 fails immediately.
            project = await self._load_project()
            if self.config["start_from"] == "speech_script":
                self._verify_rendered_pages(project)
            await self._publish()

            for stage_id in self.planned:
                await self._check_cancelled()
                await self._set_stage(stage_id, status="running", progress=0.0, message="进行中…")
                handler = getattr(self, f"_run_{stage_id}")
                await handler()

            self.status = "completed"
        except UnattendedCancelled:
            await self._mark_cancelled()
        except Exception as exc:  # noqa: BLE001
            # A cancel raised mid-stage surfaces as a stage error (the slide loop, for
            # instance, only reports "生成已停止"), so classify it as a cancel, not a failure.
            if await is_cancelled(self.project_id):
                await self._mark_cancelled()
            else:
                logger.error(
                    "Unattended pipeline failed for project %s: %s", self.project_id, exc, exc_info=True
                )
                self.status = "failed"
                self.error = str(exc)
                failing = self.current_stage_id()
                if failing:
                    self._terminal_stage_id = failing
                    await self._set_stage(failing, status="failed", message="失败", error=str(exc))
        finally:
            self.finished_at = time.time()
            await clear_cancel(self.project_id)
            if ctx_token is not None:
                try:
                    from ..auth.request_context import current_user_id as _cuid

                    _cuid.reset(ctx_token)
                except Exception:  # noqa: BLE001
                    pass

        await self._publish()
        return self.snapshot()

    # ------------------------------------------------------------ stage impls

    @staticmethod
    def _verify_rendered_pages(project) -> None:
        outline = project.outline if isinstance(project.outline, dict) else {}
        expected = len(outline.get("slides") or [])
        rendered = project.slides_data or []
        if not expected or len(rendered) != expected or any(
            not slide.get("html_content") or slide.get("generation_failed")
            for slide in rendered
        ):
            raise RuntimeError("从讲稿重做需要完整的已生成幻灯片")

    def _service(self):
        from .service_instances import get_ppt_service_for_user

        return get_ppt_service_for_user(self.user_id)

    # Credit enforcement lives in the HTTP routes, not the services. Driving the
    # services directly would hand out free generation, so the pipeline reproduces
    # the same pre-check / post-charge the routes perform.

    async def _resolve_provider(self, role: str) -> Optional[str]:
        try:
            _, settings = await self._service().get_role_provider_async(role)
            return (settings or {}).get("provider")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not resolve %s provider for billing: %s", role, exc)
            return None

    async def _require_credits(self, operation: str, quantity: int, provider: Optional[str]) -> None:
        from ..web.route_modules.support import check_credits_for_operation

        has_credits, required, balance = await check_credits_for_operation(
            self.user_id, operation, max(1, quantity), provider_name=provider
        )
        if not has_credits:
            raise RuntimeError(f"积分不足，本阶段需要 {required} 积分，当前余额 {balance} 积分")

    async def _charge_credits(
        self, operation: str, quantity: int, provider: Optional[str], description: str
    ) -> None:
        if quantity <= 0:
            return
        from ..web.route_modules.support import consume_credits_for_operation

        billed, message = await consume_credits_for_operation(
            self.user_id,
            operation,
            quantity,
            description=description,
            reference_id=self.project_id,
            provider_name=provider,
        )
        if not billed:
            logger.error("Unattended billing failed for %s on %s: %s", operation, self.project_id, message)

    async def _load_project(self):
        service = self._service()
        project = await service.project_manager.get_project(self.project_id, user_id=self.user_id)
        if not project:
            raise RuntimeError("项目不存在或无访问权限")
        self.topic = project.topic or self.topic
        return project

    async def _run_outline(self) -> None:
        service = self._service()
        project = await self._load_project()
        confirmed_requirements = project.confirmed_requirements or {}
        if not confirmed_requirements:
            raise RuntimeError("项目需求尚未确认，无法生成大纲")

        existing_slides = (project.outline or {}).get("slides") if isinstance(project.outline, dict) else None
        force_file_regeneration = bool(confirmed_requirements.get("force_file_outline_regeneration"))
        if existing_slides and not force_file_regeneration:
            await self._set_stage(
                "outline",
                status="completed",
                message=f"已存在大纲，共 {len(existing_slides)} 页",
                detail={"slide_count": len(existing_slides), "reused": True},
            )
            return

        outline_provider = await self._resolve_provider("outline")
        await self._require_credits("outline_generation", 1, outline_provider)

        content_source = confirmed_requirements.get("content_source")
        if content_source in ("file", "url", "mixed"):
            # File/URL sourced outlines are produced by the web-layer helper: it merges
            # uploads, optionally runs research, and persists the result itself.
            from ..web.route_modules.outline_support import _stream_outline_from_confirmed_sources_v2

            await service.project_manager.update_stage_status(
                self.project_id, "outline_generation", "running", 0.0, user_id=self.user_id
            )
            chunk_source = _stream_outline_from_confirmed_sources_v2(
                self.project_id, project, confirmed_requirements, user_id=self.user_id
            )
        else:
            chunk_source = service.generate_outline_streaming(
                self.project_id, force_regenerate=force_file_regeneration
            )

        stream_error: Optional[str] = None
        research_skip_message: Optional[str] = None
        done = False
        llm_call_count = 0
        # Own the stream: an abandoned generator would unwind the conversation
        # scope in a copied Context when the loop's finalizer gets to it.
        async with aclosing(chunk_source):
            async for chunk in chunk_source:
                for line in str(chunk).splitlines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        payload = json.loads(line[6:])
                    except Exception:  # noqa: BLE001
                        continue
                    if payload.get("error"):
                        stream_error = str(payload["error"])
                    elif payload.get("done") is True:
                        done = True
                        try:
                            llm_call_count = max(0, int(payload.get("llm_call_count", 1)))
                        except (TypeError, ValueError):
                            llm_call_count = 1
                    elif isinstance(payload.get("status"), dict):
                        status_payload = payload["status"]
                        message = str(status_payload.get("message") or "生成大纲中…")
                        if status_payload.get("step") == "research_skip":
                            research_skip_message = message
                        raw_progress = status_payload.get("progress")
                        try:
                            # The outline stream reports 0..1, not 0..100.
                            progress = float(raw_progress) * 100.0 if raw_progress is not None else None
                        except (TypeError, ValueError):
                            progress = None
                        await self._set_stage(
                            "outline",
                            progress=progress,
                            message=message,
                        )

        if stream_error:
            raise RuntimeError(f"大纲生成失败：{stream_error}")

        refreshed = await self._load_project()
        slides = (refreshed.outline or {}).get("slides") if isinstance(refreshed.outline, dict) else None
        if not slides:
            raise RuntimeError("大纲生成失败：未产生任何页面")

        await self._charge_credits(
            "outline_generation", llm_call_count, outline_provider, f"大纲生成(无人值守): {self.topic}"
        )

        completion_message = f"大纲完成，共 {len(slides)} 页"
        if research_skip_message:
            completion_message = f"{completion_message}。{research_skip_message}"
        await self._set_stage(
            "outline",
            status="completed",
            message=completion_message,
            detail={"slide_count": len(slides), "stream_completed": done},
        )

    async def _run_template(self) -> None:
        service = self._service()
        project = await self._load_project()
        metadata = project.project_metadata or {}

        mode = self.config.get("template_mode") or "auto"
        if is_video_explainer(getattr(project, "confirmed_requirements", None)):
            mode = "free"
        # A project already switched to free mode keeps that choice unless the run
        # explicitly asked for a global template.
        if mode == "auto" and metadata.get("template_mode") == "free":
            mode = "free"

        if mode == "free":
            await self._run_free_template(service)
            return

        result = await service.select_global_template_for_project(
            self.project_id, self.config.get("template_id"), user_id=self.user_id
        )
        if not result.get("success"):
            raise RuntimeError(f"模板选择失败：{result.get('message')}")

        template = result.get("selected_template") or {}
        await self._set_stage(
            "template",
            status="completed",
            message=f"已选择模板：{template.get('template_name', '默认模板')}",
            detail={
                "template_mode": "global",
                "template_id": template.get("id"),
                "template_name": template.get("template_name"),
            },
        )

    async def _run_free_template(self, service) -> None:
        """Switch to free-template mode, generate the template, and confirm it.

        Confirmation is normally a human step (POST /free-template/confirm); an
        unattended run performs the same write itself, because the slides stream
        refuses to start while free_template_confirmed is falsy.
        """
        switched = await service.select_free_template_for_project(self.project_id, user_id=self.user_id)
        if not switched.get("success"):
            raise RuntimeError(f"切换自由模板失败：{switched.get('message')}")

        await self._set_stage("template", progress=10.0, message="正在生成自由模板…")

        completed = False
        template_name: Optional[str] = None
        # The generator raises on failure rather than yielding an error event.
        async for event in service.stream_free_template_generation(
            self.project_id, user_id=self.user_id, force=False
        ):
            event_type = (event or {}).get("type")
            if event_type == "status":
                await self._set_stage(
                    "template", progress=25.0, message=str(event.get("message") or "生成模板中…")
                )
            elif event_type == "preview":
                await self._set_stage("template", progress=70.0, message="正在渲染模板预览…")
            elif event_type == "complete":
                completed = True
                template_name = event.get("template_name")

        if not completed:
            raise RuntimeError("自由模板生成失败：未收到完成事件")

        await self._set_stage("template", progress=90.0, message="正在确认模板…")
        template_name = await self._confirm_free_template(service) or template_name

        await self._set_stage(
            "template",
            status="completed",
            message=f"已生成自由模板：{template_name or 'AI 自由模板'}",
            detail={"template_mode": "free", "template_name": template_name},
        )

    async def _confirm_free_template(self, service) -> Optional[str]:
        """Mirror the minimal path of POST /api/projects/{id}/free-template/confirm."""
        project = await self._load_project()
        metadata = dict(project.project_metadata or {})
        html = metadata.get("free_template_html")
        if not (isinstance(html, str) and html.strip()):
            raise RuntimeError("自由模板生成失败：未产生模板内容")

        metadata["free_template_confirmed"] = True
        metadata["free_template_confirmed_at"] = time.time()
        metadata["free_template_status"] = "ready"
        saved = await service.project_manager.update_project_metadata(
            self.project_id, metadata, user_id=self.user_id
        )
        if not saved:
            raise RuntimeError("自由模板确认失败：无法保存项目元数据")

        try:
            service.clear_cached_style_genes(self.project_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not clear cached style genes for %s: %s", self.project_id, exc)

        return metadata.get("free_template_name")

    async def _run_ppt(self) -> None:
        service = self._service()
        project = await self._load_project()
        outline = project.outline if isinstance(project.outline, dict) else {}
        total = len(outline.get("slides") or [])
        if total <= 0:
            raise RuntimeError("大纲中没有页面，无法生成 PPT")

        # A sticky cancel flag from an earlier manual stop would abort the first batch.
        await service.clear_cancel_slides_generation(self.project_id)

        stream_error: Optional[str] = None
        # The stream's `current` is the slide's PAGE NUMBER, not a count of finished
        # pages: parallel batches complete out of order and a resume replays every
        # already-persisted page first. Count distinct pages instead.
        seen_pages: set = set()
        # Own the stream, same reason as the outline stage above.
        async with aclosing(service.generate_slides_streaming(self.project_id)) as slides_stream:
            async for chunk in slides_stream:
                for line in str(chunk).splitlines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        payload = json.loads(line[6:])
                    except Exception:  # noqa: BLE001
                        continue
                    event_type = payload.get("type")
                    if event_type == "progress":
                        page_number = int(payload.get("current") or 0)
                        stage_total = int(payload.get("total") or total) or total
                        if page_number > 0:
                            seen_pages.add(page_number)
                        done = min(len(seen_pages), stage_total)
                        await self._set_stage(
                            "ppt",
                            progress=(done / stage_total) * 100.0,
                            message=f"已生成 {done}/{stage_total} 页",
                        )
                    elif event_type == "error":
                        stream_error = str(payload.get("message") or "PPT 生成失败")

        if stream_error:
            raise RuntimeError(f"PPT 生成失败：{stream_error}")

        slides = await service.project_manager.list_slides(self.project_id, user_id=self.user_id)
        rendered = [s for s in slides if s.get("html_content") and not s.get("generation_failed")]
        if len(rendered) < total:
            raise RuntimeError(f"PPT 生成不完整：{len(rendered)}/{total} 页成功")

        await self._set_stage(
            "ppt",
            status="completed",
            message=f"PPT 完成，共 {len(rendered)} 页",
            detail={"slide_count": len(rendered)},
        )

    async def _run_speech_script(self) -> None:
        from .speech_script_repository import SpeechScriptRepository
        from .speech_script_service import (
            LanguageComplexity,
            SpeechScriptCustomization,
            SpeechScriptService,
            SpeechTone,
            TargetAudience,
        )

        project = await self._load_project()
        slides = project.slides_data or []
        if not slides:
            raise RuntimeError("尚未生成 PPT，无法生成演讲稿")

        repo = SpeechScriptRepository()
        try:
            existing = await repo.get_current_speech_scripts_by_project(self.project_id, self.language)
            covered = {
                script.slide_index
                for script in existing
                if str(getattr(script, "script_content", "") or "").strip()
            }
        finally:
            repo.close()

        rewriting = self.config["start_from"] == "speech_script"
        missing = [index for index in range(len(slides)) if rewriting or index not in covered]
        if not missing:
            await self._set_stage(
                "speech_script",
                status="completed",
                message=f"演讲稿已存在，共 {len(slides)} 页",
                detail={"script_count": len(slides), "reused": True},
            )
            return

        speech_service = SpeechScriptService(user_id=self.user_id)
        await speech_service.initialize_async()
        if speech_service.ai_provider is None:
            raise RuntimeError("演讲稿生成失败：没有可用的 AI 提供商")

        speech_provider = (speech_service.provider_settings or {}).get("provider")
        await self._require_credits("ai_other", len(missing), speech_provider)

        duration_limit = self.config["max_duration_seconds"]
        duration_target = self.config["target_duration_seconds"] or duration_limit
        if duration_target and duration_limit:
            duration_target = min(duration_target, max(1, int(duration_limit * 0.88)))
        customization = SpeechScriptCustomization(
            language=self.language,
            tone=SpeechTone.CONVERSATIONAL,
            target_audience=TargetAudience.GENERAL_PUBLIC,
            language_complexity=LanguageComplexity.MODERATE,
            speaking_pace="normal",
            custom_style_prompt=self.config["speech_requirements"] or None,
            target_seconds=(
                max(1, duration_target // len(slides)) if duration_target else None
            ),
            strict_duration=duration_limit is not None,
        )

        total_missing = len(missing)

        def _on_progress(event: Dict[str, Any]) -> None:
            if not isinstance(event, dict) or event.get("type") not in ("progress", "slide_completed"):
                return
            try:
                completed = int(event.get("completed"))
            except (TypeError, ValueError):
                return
            total_slides = int(event.get("total_slides") or total_missing) or total_missing
            # The service invokes this callback synchronously from its generation loop,
            # so hand the async state update back to the running loop.
            self._track_update(
                self._set_stage(
                    "speech_script",
                    progress=(completed / total_slides) * 100.0,
                    message=f"演讲稿 {completed}/{total_slides} 页",
                )
            )

        result = await speech_service.generate_multi_slide_scripts_with_retry(
            project, missing, customization, progress_callback=_on_progress
        )

        scripts = list(getattr(result, "scripts", None) or [])
        if not scripts:
            raise RuntimeError(
                f"演讲稿生成失败：{getattr(result, 'error_message', None) or '未生成任何内容'}"
            )

        generation_params = {
            "generation_type": "full",
            "tone": customization.tone.value,
            "target_audience": customization.target_audience.value,
            "language_complexity": customization.language_complexity.value,
            "custom_audience": None,
            "custom_style_prompt": customization.custom_style_prompt,
            "include_transitions": customization.include_transitions,
            "include_timing_notes": customization.include_timing_notes,
            "speaking_pace": customization.speaking_pace,
        }

        generated_indices = {script.slide_index for script in scripts}
        if rewriting and set(missing) - generated_indices:
            await self._charge_credits(
                "ai_other", len(scripts), speech_provider, f"演讲稿生成(无人值守): {len(scripts)}页"
            )
            raise RuntimeError("讲稿重写结果不完整，原讲稿已保留")
        repo = SpeechScriptRepository()
        try:
            for script in scripts:
                await repo.save_speech_script(
                    project_id=self.project_id,
                    slide_index=script.slide_index,
                    language=self.language,
                    slide_title=script.slide_title,
                    script_content=script.script_content,
                    generation_params=generation_params,
                    estimated_duration=script.estimated_duration,
                    **({"commit": False} if rewriting else {}),
                )
            repo.db.commit()
        finally:
            repo.close()

        await self._charge_credits(
            "ai_other", len(scripts), speech_provider, f"演讲稿生成(无人值守): {len(scripts)}页"
        )

        saved_indices = covered | {script.slide_index for script in scripts}
        still_missing = [index for index in range(len(slides)) if index not in saved_indices]
        if still_missing:
            # Narration and video both hard-fail on a gap, so stop with a clear reason.
            raise RuntimeError(
                "演讲稿生成不完整，缺少第 "
                + "、".join(str(index + 1) for index in still_missing[:10])
                + " 页"
            )

        await self._set_stage(
            "speech_script",
            status="completed",
            message=f"演讲稿完成，共 {len(saved_indices)} 页",
            detail={"script_count": len(saved_indices), "generated": len(scripts)},
        )

    async def _count_narration_audios(self) -> Optional[int]:
        """How many slides already have narration audio, for progress only.

        Returns None when the count cannot be read, so a transient DB error just
        skips a progress tick instead of failing the stage.
        """
        from .narration_audio_repository import NarrationAudioRepository

        repository = NarrationAudioRepository()
        try:
            rows = await repository.list_by_project(
                project_id=self.project_id, language=self.language
            )
            return len({row.slide_index for row in rows})
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read narration progress for %s: %s", self.project_id, exc)
            return None
        finally:
            try:
                repository.close()
            except Exception:  # noqa: BLE001
                pass

    async def _run_narration_audio(self) -> None:
        from .narration_service import NarrationService, ffprobe_duration_ms, is_ffmpeg_available

        project = await self._load_project()
        slides = project.slides_data or []
        if not slides:
            raise RuntimeError("尚未生成 PPT，无法生成配音")

        if not is_ffmpeg_available():
            logger.warning(
                "ffmpeg/ffprobe unavailable; narration durations and subtitle cues will be missing"
            )

        total = len(slides)
        service = NarrationService(user_id=self.user_id)

        # One call for the whole deck: each invocation re-hydrates the project and all
        # speech scripts, so a per-slide loop would be O(N^2). NarrationService only
        # honours progress_callback on the custom_tts_api path, so progress is instead
        # observed from the rows the synthesis loop persists as it goes.
        synthesis = asyncio.ensure_future(
            service.generate_project_slide_audios(
                project_id=self.project_id,
                slide_indices=None,
                provider=self.config["tts_provider"],
                language=self.language,
                voice=self.config["tts_voice"],
                rate=self.config["tts_rate"],
                reference_text="",
                voice_prompt="",
                force_regenerate=False,
                uploads_dir="uploads",
            )
        )
        try:
            while not synthesis.done():
                done = await self._count_narration_audios()
                if done is not None:
                    await self._set_stage(
                        "narration_audio",
                        progress=(min(done, total) / total) * 100.0,
                        message=f"配音 {min(done, total)}/{total} 页",
                    )
                await asyncio.wait({synthesis}, timeout=3)
            items = await synthesis
        except BaseException:
            synthesis.cancel()
            raise

        covered = {item.slide_index for item in items}
        missing = [index for index in range(total) if index not in covered]
        if missing:
            raise RuntimeError(
                "配音生成不完整，缺少第 "
                + "、".join(str(index + 1) for index in missing[:10])
                + " 页"
            )

        limit = self.config["max_duration_seconds"]
        if limit is not None and self.stop_after == "video":
            duration_ms = 0
            measured_items = []
            for item in items:
                measured = item.duration_ms or await ffprobe_duration_ms(item.audio_path)
                if not measured or measured <= 0:
                    raise RuntimeError(f"无法核验第 {item.slide_index + 1} 页配音时长")
                duration_ms += measured
                measured_items.append(replace(item, duration_ms=measured))
            if duration_ms > limit * 1000:
                await self._set_stage("narration_audio", detail={
                    "duration_exceeded": True, "duration_seconds": duration_ms / 1000,
                    "max_duration_seconds": limit,
                })
                raise RuntimeError(f"配音总时长 {duration_ms / 1000:.1f} 秒，超过上限 {limit} 秒")
            items = measured_items
        self._narration_audio = items

        await self._set_stage(
            "narration_audio",
            status="completed",
            message=f"配音完成，共 {len(covered)} 段",
            detail={
                "audio_count": len(covered),
                "provider": self.config["tts_provider"],
                "cached": sum(1 for item in items if getattr(item, "cached", False)),
            },
        )

    async def _run_video(self) -> None:
        from .storage import get_artifact_service
        from .video_export_service import NarrationVideoExportService

        project = await self._load_project()
        await self._set_stage("video", progress=5.0, message="正在合成视频…")

        result = await NarrationVideoExportService().export_project_video(
            project=project,
            language=self.language,
            fps=self.config["fps"],
            width=1920,
            height=1080,
            embed_subtitles=self.config["embed_subtitles"],
            subtitle_style=None,
            render_mode=self.config["render_mode"],
            uploads_dir="uploads",
            narration_audio=self._narration_audio,
        )

        if not isinstance(result, dict) or not result.get("success"):
            error = (result or {}).get("error") if isinstance(result, dict) else None
            raise RuntimeError(f"视频导出失败：{error or '未知错误'}")

        video_path = result.get("video_path")
        if not video_path or not Path(video_path).exists():
            raise RuntimeError("视频导出失败：未找到输出文件")

        await self._set_stage("video", progress=92.0, message="正在保存视频…")
        artifact = await get_artifact_service().save_file(
            local_path=str(video_path),
            user_id=self.user_id,
            project_id=self.project_id,
            task_id=self.task_id,
            artifact_type="narration_video_export",
            filename=f"{project.topic}_narration_{self.language}.mp4",
            content_type="video/mp4",
        )
        self.artifact_id = artifact.id

        await self._set_stage(
            "video",
            status="completed",
            message="讲解视频导出完成",
            detail={
                "artifact_id": artifact.id,
                "render_mode": result.get("render_mode"),
                "fps": result.get("fps"),
                "filename": artifact.filename,
            },
        )


async def run_unattended_pipeline(
    *,
    project_id: str,
    user_id: int,
    config: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
    notify: bool = True,
) -> Dict[str, Any]:
    """Run the pipeline end to end and deliver the completion notification."""
    runner = UnattendedPipelineRunner(
        project_id=project_id,
        user_id=user_id,
        config=config,
        progress_callback=progress_callback,
        task_id=task_id,
    )
    snapshot = await runner.run()

    if notify:
        try:
            await send_completion_notification(snapshot=snapshot, user_id=user_id, config=runner.config)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to deliver unattended completion notification: %s", exc)

    return snapshot


def _project_link(project_id: str) -> str:
    try:
        from .url_service import build_absolute_url

        return build_absolute_url(f"/projects/{project_id}/todo")
    except Exception:  # noqa: BLE001
        return f"/projects/{project_id}/todo"


async def send_completion_notification(
    *,
    snapshot: Dict[str, Any],
    user_id: int,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Build and dispatch the terminal notification for a finished pipeline."""
    from .notification_service import notify_user

    project_id = snapshot.get("project_id")
    status = snapshot.get("status")
    topic = snapshot.get("topic") or ""

    if not topic:
        try:
            from .service_instances import get_project_manager

            project = await get_project_manager().get_project(str(project_id), user_id=user_id)
            topic = project.topic if project else str(project_id)
        except Exception:  # noqa: BLE001
            topic = str(project_id)

    level = {"completed": "success", "cancelled": "warning"}.get(status, "error")
    title = {
        "completed": f"无人值守任务完成：{topic}",
        "cancelled": f"无人值守任务已取消：{topic}",
    }.get(status, f"无人值守任务失败：{topic}")

    completed = [
        stage["name"] for stage in snapshot.get("stages", []) if stage.get("status") == "completed"
    ]
    failed = [
        stage for stage in snapshot.get("stages", []) if stage.get("status") == "failed"
    ]

    body_lines = []
    if completed:
        body_lines.append("已完成：" + "、".join(completed))
    if failed:
        failed_stage = failed[0]
        body_lines.append(f"失败于：{failed_stage.get('name')}")
    if snapshot.get("error"):
        body_lines.append(f"原因：{snapshot['error']}")

    detail_rows = [
        ("主题", topic),
        ("目标阶段", snapshot.get("stop_after_name") or snapshot.get("stop_after")),
        ("已完成", "、".join(completed) if completed else "无"),
    ]
    if snapshot.get("error"):
        detail_rows.append(("错误", snapshot["error"]))

    return await notify_user(
        user_id=user_id,
        title=title,
        body="\n".join(body_lines) or None,
        notification_type="unattended_run",
        level=level,
        project_id=str(project_id) if project_id else None,
        link_url=f"/projects/{project_id}/todo" if project_id else None,
        payload={
            "status": status,
            "stop_after": snapshot.get("stop_after"),
            "artifact_id": snapshot.get("artifact_id"),
            "stages": [
                {"id": stage.get("id"), "name": stage.get("name"), "status": stage.get("status")}
                for stage in snapshot.get("stages", [])
            ],
        },
        send_in_app=bool(config.get("notify_in_app", True)),
        send_email_notification=bool(config.get("notify_email", False)),
        email_subject=f"LandPPT · {title}",
        email_detail_rows=detail_rows,
        email_action_url=_project_link(str(project_id)) if project_id else None,
    )
