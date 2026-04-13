"""
Narration video export service (MP4 + subtitles).

Pipeline (MVP):
1) Ensure per-slide audio exists (Edge-TTS).
2) Render each slide HTML to 1920x1080 PNG using Playwright screenshot.
3) Build per-slide MP4 clips (still image + audio).
4) Concatenate clips into final MP4.
5) Generate SRT subtitles from speech scripts and burn-in / embed as soft subtitles.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .export_infra.ffmpeg_runner import (
    ffprobe_duration_ms as _ffprobe_duration_ms_impl,
    run_subprocess as _run_subprocess_impl,
    summarize_subprocess_stderr as _summarize_subprocess_stderr_impl,
)
from .export_infra.html_render_service import HtmlRenderService
from .export_infra.file_export_html_preparer import (
    prepare_html_for_file_based_export,
    resolve_background_export_base_url,
)
from .export_infra.subtitle_mux_service import (
    SubtitleStyle,
    build_cues_by_audio_path as _build_cues_by_audio_path_impl,
    build_subtitle_filter as _build_subtitle_filter_impl,
    normalize_audio_cache_path as _normalize_audio_cache_path_impl,
    resolve_subtitle_style as _resolve_subtitle_style_impl,
)
from .export_infra.temp_artifact_manager import TempArtifactManager
from .subtitle_service import SubtitleCue, build_slide_cues, build_srt
from .pyppeteer_pdf_converter import get_pdf_converter

logger = logging.getLogger(__name__)


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


async def ffprobe_duration_ms(audio_path: str) -> Optional[int]:
    return await _ffprobe_duration_ms_impl(audio_path)


def _resolve_subtitle_style(
    subtitle_style: Optional[Dict[str, Any]],
    *,
    height: int,
    render_mode: str,
) -> SubtitleStyle:
    return _resolve_subtitle_style_impl(subtitle_style, height=height, render_mode=render_mode)


def _build_subtitle_filter(*, subtitle_path: str, width: int, height: int, style: SubtitleStyle) -> str:
    return _build_subtitle_filter_impl(subtitle_path=subtitle_path, width=width, height=height, style=style)


async def _run_subprocess(
    args: List[str],
    *,
    cwd: Optional[str] = None,
    timeout_ms: Optional[int] = None,
) -> Tuple[int, str, str]:
    return await _run_subprocess_impl(args, cwd=cwd, timeout_ms=timeout_ms)


def _summarize_subprocess_stderr(err: str, *, max_lines: int = 25) -> str:
    return _summarize_subprocess_stderr_impl(err, max_lines=max_lines)


def _normalize_audio_cache_path(path: Optional[str]) -> str:
    return _normalize_audio_cache_path_impl(path)


def _build_cues_by_audio_path(rows: List[Any]) -> Dict[str, Optional[str]]:
    return _build_cues_by_audio_path_impl(rows)


def _calculate_safe_parallelism(width: int, height: int, fps: int = 30) -> int:
    """
    Calculate safe parallelism based on available memory to prevent OOM.

    Each video recording session consumes memory for:
    - Chromium browser instance (~200-500MB)
    - Frame buffer (width * height * 4 bytes per frame)
    - 10 seconds of recording buffer at target fps

    Args:
        width: Video width in pixels
        height: Video height in pixels
        fps: Target frames per second

    Returns:
        Safe parallelism value (minimum 1)
    """
    def _read_int(path: str) -> Optional[int]:
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
            if not raw or raw.lower() == "max":
                return None
            return int(raw)
        except Exception:
            return None

    def _available_mb_from_cgroup() -> Optional[float]:
        # cgroup v2
        limit = _read_int("/sys/fs/cgroup/memory.max")
        current = _read_int("/sys/fs/cgroup/memory.current")
        if limit is not None and current is not None and limit > 0 and current >= 0:
            # Some environments report a very large "no limit" number; treat as unset.
            if limit >= (1 << 60):
                return None
            return max(0.0, (limit - current) / (1024 * 1024))

        # cgroup v1
        limit = _read_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        current = _read_int("/sys/fs/cgroup/memory/memory.usage_in_bytes")
        if limit is not None and current is not None and limit > 0 and current >= 0:
            if limit >= (1 << 60):
                return None
            return max(0.0, (limit - current) / (1024 * 1024))
        return None

    available_mb_env = (os.environ.get("LANDPPT_AVAILABLE_MEMORY_MB") or "").strip()
    if available_mb_env:
        try:
            available_mb = float(available_mb_env)
        except Exception:
            available_mb = None
    else:
        available_mb = None

    if available_mb is None:
        available_mb = _available_mb_from_cgroup()

    if available_mb is None:
        try:
            import psutil

            available_mb = psutil.virtual_memory().available / (1024 * 1024)
        except ImportError:
            # psutil not available, assume 4GB available
            available_mb = 4096

    # In multi-worker deployments, each worker should assume only a slice of memory.
    try:
        workers = int(os.environ.get("WORKERS", "1") or 1)
    except Exception:
        workers = 1
    workers = max(1, workers)
    available_mb = max(0.0, float(available_mb) / workers)

    # Estimate memory per recording session (in MB)
    frame_size_mb = (width * height * 4) / (1024 * 1024)  # RGBA frame
    buffer_frames = fps * 10  # 10 seconds of buffering
    browser_overhead_mb = 400  # Chromium overhead
    ffmpeg_overhead_mb = 100  # FFmpeg process overhead
    safety_factor = 1.5  # Additional safety margin

    memory_per_session_mb = (
        frame_size_mb * buffer_frames + browser_overhead_mb + ffmpeg_overhead_mb
    ) * safety_factor

    # Reserve memory for the rest of the process (FastAPI, caches, other tasks).
    reserve_mb = min(2048.0, max(512.0, available_mb * 0.5))
    usable_mb = max(256.0, available_mb - reserve_mb)

    # Calculate safe parallelism
    safe_parallel = max(1, int(usable_mb / memory_per_session_mb))

    # Cap at configured maximum and CPU count
    env_max = int(os.environ.get("LANDPPT_NARRATION_VIDEO_PARALLELISM", "4") or 4)
    cpu_count = os.cpu_count() or 2

    result = min(safe_parallel, env_max, cpu_count, 8)

    logger.debug(
        f"Memory-aware parallelism: available={available_mb:.0f}MB, "
        f"per_session={memory_per_session_mb:.0f}MB, result={result}"
    )

    return max(1, result)


def _calculate_safe_screenshot_parallelism(width: int, height: int) -> int:
    """
    Calculate safe parallelism for Playwright *screenshots* (much lighter than video recording).

    Notes:
    - Uses the same memory detection logic as video parallelism but a smaller per-task estimate.
    - Caps conservatively to avoid Chromium OOM / context crashes under load.
    """
    def _read_int(path: str) -> Optional[int]:
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
            if not raw or raw.lower() == "max":
                return None
            return int(raw)
        except Exception:
            return None

    def _available_mb_from_cgroup() -> Optional[float]:
        limit = _read_int("/sys/fs/cgroup/memory.max")
        current = _read_int("/sys/fs/cgroup/memory.current")
        if limit is not None and current is not None and limit > 0 and current >= 0:
            if limit >= (1 << 60):
                return None
            return max(0.0, (limit - current) / (1024 * 1024))

        limit = _read_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        current = _read_int("/sys/fs/cgroup/memory/memory.usage_in_bytes")
        if limit is not None and current is not None and limit > 0 and current >= 0:
            if limit >= (1 << 60):
                return None
            return max(0.0, (limit - current) / (1024 * 1024))
        return None

    available_mb_env = (os.environ.get("LANDPPT_AVAILABLE_MEMORY_MB") or "").strip()
    if available_mb_env:
        try:
            available_mb = float(available_mb_env)
        except Exception:
            available_mb = None
    else:
        available_mb = None

    if available_mb is None:
        available_mb = _available_mb_from_cgroup()

    if available_mb is None:
        try:
            import psutil

            available_mb = psutil.virtual_memory().available / (1024 * 1024)
        except ImportError:
            available_mb = 4096

    try:
        workers = int(os.environ.get("WORKERS", "1") or 1)
    except Exception:
        workers = 1
    workers = max(1, workers)
    available_mb = max(0.0, float(available_mb) / workers)

    # Estimate memory per screenshot task (MB).
    # Chromium is shared; per-page tends to be ~100-300MB depending on slide complexity.
    frame_size_mb = (width * height * 4) / (1024 * 1024)
    per_task_mb = (200.0 + frame_size_mb * 4.0) * 1.3

    reserve_mb = min(1536.0, max(512.0, available_mb * 0.5))
    usable_mb = max(256.0, available_mb - reserve_mb)

    safe_parallel = max(1, int(usable_mb / per_task_mb))
    env_max = int(os.environ.get("LANDPPT_NARRATION_SCREENSHOT_PARALLELISM", os.environ.get("LANDPPT_NARRATION_VIDEO_PARALLELISM", "4")) or 4)
    cpu_count = os.cpu_count() or 2

    result = min(safe_parallel, env_max, cpu_count, 12)
    logger.debug(
        f"Screenshot parallelism: available={available_mb:.0f}MB, per_task={per_task_mb:.0f}MB, result={result}"
    )
    return max(1, result)


def _safe_filename_stem(name: str, fallback: str = "landppt") -> str:
    # Windows-safe, path-safe, ffmpeg-safe-ish.
    name = (name or "").strip()
    if not name:
        return fallback
    # Replace forbidden characters on Windows: \ / : * ? " < > |
    bad = '\\/:*?"<>|'
    for ch in bad:
        name = name.replace(ch, "_")
    name = name.replace("\n", " ").replace("\r", " ").strip()
    name = " ".join(name.split())
    return name[:80] or fallback


def _wrap_html_if_needed(html: str, *, title: str) -> str:
    html = (html or "").strip()
    if not html:
        html = "<div></div>"

    lower = html.lstrip().lower()
    if lower.startswith("<!doctype") or lower.startswith("<html"):
        return html

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0" />
  <title>{title}</title>
  <style>html,body{{margin:0;padding:0;background:#fff;}}</style>
</head>
<body>
{html}
</body>
</html>
"""


class NarrationVideoExportService:
    @staticmethod
    def _get_html_render_service() -> HtmlRenderService:
        return HtmlRenderService(converter_factory=get_pdf_converter)

    @staticmethod
    def _prepare_slide_html_for_video_export(slide_html: str, *, title: str) -> str:
        """在 file:// 导出上下文中重写资源地址，避免图片与样式资源失效。"""
        prepared_html = _wrap_html_if_needed(slide_html, title=title)

        try:
            export_base_url = resolve_background_export_base_url()
            if export_base_url:
                return prepare_html_for_file_based_export(prepared_html, export_base_url)
        except Exception as exc:
            logger.warning("Failed to prepare slide HTML resources for video export: %s", exc)

        return prepared_html

    async def export_project_video(
        self,
        *,
        project: Any,
        language: str = "zh",
        fps: int = 30,
        width: int = 1920,
        height: int = 1080,
        embed_subtitles: bool = True,
        subtitle_style: Optional[Dict[str, Any]] = None,
        render_mode: str = "live",
        uploads_dir: str = "uploads",
    ) -> Dict[str, Any]:
        language = (language or "zh").strip().lower()
        fps = 60 if int(fps) == 60 else 30
        render_mode = (render_mode or "live").strip().lower()

        if not is_ffmpeg_available():
            return {"success": False, "error": "ffmpeg/ffprobe not found in PATH"}

        if not project or not getattr(project, "slides_data", None):
            return {"success": False, "error": "Project has no slides_data"}

        render_service = self._get_html_render_service()
        if not render_service.is_available():
            return {"success": False, "error": "Playwright is not available for slide rendering"}

        if render_mode not in {"live", "static"}:
            render_mode = "live"

        if render_mode == "live" and fps == 60:
            allow_60 = str(os.environ.get("LANDPPT_NARRATION_LIVE_ALLOW_60FPS", "")).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
                "y",
            }
            if not allow_60:
                # Playwright's built-in recorder is effectively fixed/low-fps; upsampling to 60fps
                # tends to look choppy and increases CPU usage during transcode.
                logger.info("Live narration recording: forcing 30fps (set LANDPPT_NARRATION_LIVE_ALLOW_60FPS=1 to keep 60fps).")
                fps = 30

        # Prefer live slideshow recording to preserve animations/effects.
        if render_mode == "live":
            try:
                result = await self._export_project_video_live(
                    project=project,
                    language=language,
                    fps=fps,
                    width=width,
                    height=height,
                    embed_subtitles=embed_subtitles,
                    subtitle_style=subtitle_style,
                    uploads_dir=uploads_dir,
                )
                if result.get("success"):
                    return result
                logger.warning(f"Live narration video export failed, fallback to static: {result.get('error')}")
            except Exception as e:
                logger.warning(f"Live narration video export crashed, fallback to static: {e}")

        return await self._export_project_video_static(
            project=project,
            language=language,
            fps=fps,
            width=width,
            height=height,
            embed_subtitles=embed_subtitles,
            subtitle_style=subtitle_style,
            uploads_dir=uploads_dir,
        )

    async def _export_project_video_live(
        self,
        *,
        project: Any,
        language: str,
        fps: int,
        width: int,
        height: int,
        embed_subtitles: bool,
        subtitle_style: Optional[Dict[str, Any]],
        uploads_dir: str,
    ) -> Dict[str, Any]:
        """
        Render video by recording a real slideshow playback (preserves CSS/JS animations).
        Audio is merged later via ffmpeg.
        """
        render_service = self._get_html_render_service()
        if not render_service.is_available():
            return {"success": False, "error": "Playwright is not available for live rendering"}

        from .narration_service import NarrationService
        from .narration_audio_repository import NarrationAudioRepository
        from .speech_script_repository import SpeechScriptRepository

        narration_service = NarrationService(user_id=getattr(project, "user_id", None))
        speech_repo = SpeechScriptRepository()
        audio_repo = NarrationAudioRepository()

        temp_artifacts = TempArtifactManager(prefix="landppt_video_live_")
        tmp_dir = temp_artifacts.create()
        try:
            # 1) Ensure audio per slide
            audios = await narration_service.generate_project_slide_audios(
                project_id=project.project_id,
                language=language,
                uploads_dir=uploads_dir,
            )
            audio_by_index = {a.slide_index: a for a in audios}

            slide_count = len(project.slides_data)
            audio_paths: List[str] = []
            durations_ms: List[int] = []
            for i in range(slide_count):
                audio = audio_by_index.get(i)
                if not audio or not audio.audio_path or not os.path.exists(audio.audio_path):
                    return {"success": False, "error": f"Missing narration audio for slide {i+1} (language={language})"}
                duration_ms = int(audio.duration_ms or 0)
                if duration_ms <= 0:
                    duration_ms = int(await ffprobe_duration_ms(audio.audio_path) or 0)
                if duration_ms <= 0:
                    duration_ms = 2000
                audio_paths.append(audio.audio_path)
                durations_ms.append(duration_ms)

            # 2) Build SRT subtitles
            scripts = await speech_repo.get_current_speech_scripts_by_project(project.project_id, language=language)
            script_by_index = {s.slide_index: s for s in scripts}
            subtitle_cues_by_audio_path: Dict[str, Optional[str]] = {}
            try:
                rows = await audio_repo.list_by_project(project_id=project.project_id, language=language)
                subtitle_cues_by_audio_path = _build_cues_by_audio_path(rows)
            except Exception:
                subtitle_cues_by_audio_path = {}

            all_cues: List[SubtitleCue] = []
            cursor_ms = 0
            for i in range(slide_count):
                duration_ms = durations_ms[i]
                audio = audio_by_index.get(i)
                audio_key = _normalize_audio_cache_path(getattr(audio, "audio_path", None))
                cues_json = subtitle_cues_by_audio_path.get(audio_key)
                used = False
                if cues_json:
                    try:
                        items = json.loads(cues_json) or []
                        for it in items:
                            t = (it.get("text") or "").strip()
                            if not t:
                                continue
                            s = int(it.get("start_ms") or 0)
                            e = int(it.get("end_ms") or 0)
                            if e <= s:
                                continue
                            all_cues.append(
                                SubtitleCue(
                                    start_ms=cursor_ms + max(0, s),
                                    end_ms=cursor_ms + min(duration_ms, e),
                                    text=t,
                                )
                            )
                        used = True
                    except Exception:
                        used = False

                if not used:
                    slide_text = (script_by_index.get(i).script_content if script_by_index.get(i) else "") or ""
                    all_cues.extend(
                        build_slide_cues(
                            slide_text=slide_text,
                            slide_start_ms=cursor_ms,
                            slide_duration_ms=duration_ms,
                            max_chars_per_line=36,
                        )
                    )

                cursor_ms += duration_ms

            srt = build_srt(all_cues)
            srt_path = os.path.join(tmp_dir, "subtitles.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt)

            # 3) Concatenate narration audio (AAC) for muxing
            audio_list_path = os.path.join(tmp_dir, "audio_list.txt")
            with open(audio_list_path, "w", encoding="utf-8") as f:
                for p in audio_paths:
                    f.write(f"file '{str(Path(p).resolve())}'\n")

            merged_audio_path = os.path.join(tmp_dir, "merged_audio.m4a")
            aac_args = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                audio_list_path,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                merged_audio_path,
            ]
            code, _, err = await _run_subprocess(aac_args)
            if code != 0:
                last = (err.splitlines()[-1] if err else "").strip()
                return {"success": False, "error": f"ffmpeg audio concat failed: {last or 'unknown error'}"}

            # 4) Record each slide in parallel using real rendering (preserves animations).
            #
            # We record only a short "good frames" segment, then clone-pad frames to match narration duration.
            # This avoids stretching incomplete/blank frames (e.g., during initial animations or slow loads).

            record_mode = (os.environ.get("LANDPPT_NARRATION_VIDEO_RECORD_MODE", "pad") or "pad").strip().lower()
            if record_mode not in {"pad", "full"}:
                record_mode = "pad"

            # "pad": record a short usable segment, then clone-pad to full narration duration (more stable).
            # "full": record the full narration duration (preserves animations), optionally starting after a delay.
            full_record_cap_ms = int(os.environ.get("LANDPPT_NARRATION_VIDEO_FULL_RECORD_MAX_MS", "600000") or 600000)
            full_record_cap_ms = max(10_000, full_record_cap_ms)
            record_start_delay_ms = int(
                os.environ.get("LANDPPT_NARRATION_VIDEO_RECORD_START_DELAY_MS", "0") or 0
            )
            record_start_delay_ms = max(0, min(60_000, record_start_delay_ms))

            max_record_ms = int(os.environ.get("LANDPPT_NARRATION_VIDEO_MAX_RECORD_MS", "10000") or 10000)
            max_record_ms = max(600, max_record_ms)
            min_usable_ms = int(os.environ.get("LANDPPT_NARRATION_VIDEO_MIN_USABLE_MS", "1800") or 1800)
            min_usable_ms = max(300, min_usable_ms)
            pad_record_ms_env = (os.environ.get("LANDPPT_NARRATION_VIDEO_PAD_RECORD_MS") or "").strip()
            pad_record_ms = None
            # Default to "a few seconds" of good frames, then clone-pad to narration duration.
            if pad_record_ms_env:
                try:
                    pad_record_ms = int(pad_record_ms_env)
                except Exception:
                    pad_record_ms = 10000
            else:
                pad_record_ms = 10000
            # Use memory-aware parallelism to prevent OOM
            parallelism = _calculate_safe_parallelism(width=width, height=height, fps=fps)
            # Recording is CPU-heavy (Chromium render + video capture). Default to low parallelism
            # to reduce dropped frames/stutter and worker instability.
            try:
                record_parallelism = int(os.environ.get("LANDPPT_NARRATION_VIDEO_RECORD_PARALLELISM", "1") or 1)
            except Exception:
                record_parallelism = 1
            if record_parallelism > 0:
                parallelism = min(parallelism, record_parallelism)
            parallelism = max(1, parallelism)

            html_dir = os.path.join(tmp_dir, "live_html")
            os.makedirs(html_dir, exist_ok=True)
            raw_dir = os.path.join(tmp_dir, "raw")
            os.makedirs(raw_dir, exist_ok=True)
            seg_dir = os.path.join(tmp_dir, "segments")
            os.makedirs(seg_dir, exist_ok=True)

            slides_payload: List[str] = []
            for i in range(slide_count):
                slide = project.slides_data[i] or {}
                slides_payload.append(
                    self._prepare_slide_html_for_video_export(
                        slide.get("html_content", ""),
                        title=f"Slide {i+1}",
                    )
                )

            plans: List[Tuple[int, int, int, int]] = []
            # (index, duration_ms, usable_ms, record_total_ms)
            for i in range(slide_count):
                dur = int(durations_ms[i])
                if record_mode == "full":
                    usable = max(500, min(dur, full_record_cap_ms))
                    record_total = usable
                else:
                    usable = int(pad_record_ms) if pad_record_ms is not None else 3500
                    usable = max(min_usable_ms, min(usable, min(max_record_ms, dur)))
                    record_total = usable
                plans.append((i, dur, usable, record_total))

            sem = asyncio.Semaphore(parallelism)

            async def _record_one(i: int, record_ms: int) -> Tuple[int, str, int, str, str]:
                html_path = os.path.join(html_dir, f"slide_{i}.html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(self._build_live_single_slide_html(slides_payload[i], width=width, height=height))
                out_path = os.path.join(raw_dir, f"slide_{i}.webm")
                async with sem:
                    ok = await render_service.record_html_video(
                        html_path,
                        out_path,
                        width=width,
                        height=height,
                        duration_ms=record_ms,
                        start_delay_ms=record_start_delay_ms,
                    )
                if not ok or not os.path.exists(out_path):
                    raise RuntimeError(f"Live record failed at slide {i+1}")
                trim_ms = 0
                try:
                    sidecar = out_path + ".json"
                    if os.path.exists(sidecar):
                        with open(sidecar, "r", encoding="utf-8") as f:
                            data = json.loads(f.read() or "{}")
                        trim_ms = int(data.get("ready_at_ms") or 0)
                except Exception:
                    trim_ms = 0
                return i, out_path, max(0, trim_ms)

            record_tasks = [_record_one(i, record_total_ms) for (i, _, _, record_total_ms) in plans]
            recorded = await asyncio.gather(*record_tasks)
            recorded_by_index = {i: {"path": p, "trim_ms": t} for i, p, t in recorded}

            # 5) Transcode segments to MP4 with consistent FPS so we can concat quickly.
            # We record only a short usable segment and then clone-pad frames to the target duration.
            trans_parallelism = int(
                os.environ.get("LANDPPT_NARRATION_VIDEO_TRANSCODE_PARALLELISM", str(min(2, parallelism))) or 2
            )
            trans_parallelism = max(1, min(8, trans_parallelism))
            # Never exceed recording parallelism; helps prevent OOM when env overrides are too aggressive.
            trans_parallelism = max(1, min(trans_parallelism, parallelism))
            trans_sem = asyncio.Semaphore(trans_parallelism)
            video_encoder = "libx264"
            logger.info(
                "Live export: encoder=%s (CPU), parallelism=%s",
                video_encoder,
                trans_parallelism,
            )

            async def _transcode_one(
                i: int,
                raw_path: str,
                trim_ms: int,
                usable_ms: int,
                dur_ms: int,
            ) -> str:
                out_mp4 = os.path.join(seg_dir, f"seg_{i}.mp4")
                try:
                    extra_trim_ms = int(os.environ.get("LANDPPT_NARRATION_VIDEO_EXTRA_TRIM_MS", "0") or 0)
                except Exception:
                    extra_trim_ms = 0
                extra_trim_ms = max(0, min(5000, extra_trim_ms))
                trim_sec = max(0.0, float(trim_ms + extra_trim_ms) / 1000.0)
                dur_sec = max(0.1, float(dur_ms) / 1000.0)
                usable_sec = max(0.1, float(usable_ms) / 1000.0)
                if record_mode == "full":
                    # Preserve animations: keep the real recorded timeline.
                    # If we had to cap recording shorter than narration, pad the tail with last frame.
                    if usable_sec + 0.05 >= dur_sec:
                        vf = f"fps={fps},setpts=PTS-STARTPTS"
                    else:
                        tail = max(0.0, dur_sec - usable_sec)
                        vf = f"fps={fps},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={tail:.3f}"
                else:
                    # Stable fallback: record a short "good frames" clip, then clone-pad to narration duration.
                    vf = f"fps={fps},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={dur_sec:.3f}"
                args: List[str] = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{trim_sec:.3f}",
                    "-i",
                    raw_path,
                    "-t",
                    f"{dur_sec:.3f}",
                    "-vf",
                    vf,
                    "-an",
                    "-c:v",
                    video_encoder,
                ]
                threads = (os.environ.get("LANDPPT_X264_THREADS") or "2").strip()
                if threads and threads != "0":
                    args.extend(["-threads", threads])
                args.extend(
                    [
                        "-preset",
                        os.environ.get("LANDPPT_X264_PRESET", "ultrafast"),
                        "-crf",
                        os.environ.get("LANDPPT_X264_CRF", "23"),
                        "-pix_fmt",
                        "yuv420p",
                        "-max_muxing_queue_size",
                        os.environ.get("LANDPPT_MAX_MUXING_QUEUE_SIZE", "1024"),
                        "-movflags",
                        "+faststart",
                        out_mp4,
                    ]
                )
                async with trans_sem:
                    code, _, err = await _run_subprocess(args)
                if code != 0:
                    summary = _summarize_subprocess_stderr(err) or "unknown error"
                    logger.error(
                        "ffmpeg transcode failed on slide %s (rc=%s, encoder=%s). args=%s err=%s",
                        i + 1,
                        code,
                        video_encoder,
                        " ".join(args),
                        (err[-4000:] if err else ""),
                    )
                    if code in {137, -9}:
                        summary = f"{summary} (process killed; possible OOM/resource limit)"
                    raise RuntimeError(f"ffmpeg transcode failed on slide {i+1} (rc={code}): {summary}")
                return out_mp4

            trans_tasks = []
            for (i, dur_ms, usable_ms, _record_total_ms) in plans:
                info = recorded_by_index[i]
                trans_tasks.append(_transcode_one(i, info["path"], int(info["trim_ms"]), usable_ms, dur_ms))
            seg_paths = await asyncio.gather(*trans_tasks)

            concat_list = os.path.join(tmp_dir, "video_concat.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                for i in range(slide_count):
                    f.write(f"file '{str(Path(os.path.join(seg_dir, f'seg_{i}.mp4')).resolve())}'\n")

            merged_video_path = os.path.join(tmp_dir, "merged_video.mp4")
            concat_args = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-c",
                "copy",
                merged_video_path,
            ]
            code, _, err = await _run_subprocess(concat_args)
            if code != 0 or not os.path.exists(merged_video_path):
                last = (err.splitlines()[-1] if err else "").strip()
                return {"success": False, "error": f"ffmpeg concat segments failed: {last or 'unknown error'}"}

            # 6) Final mp4 (mux audio, optionally burn-in subtitles)
            out_dir = os.path.join(uploads_dir, "narration_videos", project.project_id, language)
            out_dir_abs = str(Path(out_dir).resolve())
            os.makedirs(out_dir_abs, exist_ok=True)
            topic_stem = _safe_filename_stem(getattr(project, "topic", "") or "PPT")
            output_mp4 = os.path.join(out_dir_abs, f"{topic_stem}_{language}_{fps}fps_1080p.mp4")
            output_srt = os.path.join(out_dir_abs, f"{topic_stem}_{language}.srt")
            shutil.copyfile(srt_path, output_srt)

            style = _resolve_subtitle_style(subtitle_style, height=height, render_mode="live")
            if embed_subtitles:
                vf = _build_subtitle_filter(subtitle_path=srt_path, width=width, height=height, style=style)
                final_args: List[str] = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    merged_video_path,
                    "-i",
                    merged_audio_path,
                    "-vf",
                    vf,
                    "-c:v",
                    video_encoder,
                ]
                threads = (os.environ.get("LANDPPT_X264_THREADS") or "2").strip()
                if threads and threads != "0":
                    final_args.extend(["-threads", threads])
                final_args.extend(
                    [
                        "-preset",
                        os.environ.get("LANDPPT_X264_PRESET", "ultrafast"),
                        "-crf",
                        os.environ.get("LANDPPT_X264_CRF", "23"),
                        "-pix_fmt",
                        "yuv420p",
                        "-max_muxing_queue_size",
                        os.environ.get("LANDPPT_MAX_MUXING_QUEUE_SIZE", "1024"),
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-shortest",
                        "-movflags",
                        "+faststart",
                        output_mp4,
                    ]
                )
                code, _, err = await _run_subprocess(final_args, cwd=tmp_dir)
                if code != 0:
                    summary = _summarize_subprocess_stderr(err) or "unknown error"
                    return {"success": False, "error": f"ffmpeg burn-in/mux failed (rc={code}): {summary}"}
            else:
                soft_args = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    merged_video_path,
                    "-i",
                    merged_audio_path,
                    "-i",
                    srt_path,
                    "-c:v",
                    "copy",
                    "-c:a",
                    "copy",
                    "-c:s",
                    "mov_text",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    output_mp4,
                ]
                code, _, err = await _run_subprocess(soft_args, cwd=tmp_dir)
                if code != 0:
                    summary = _summarize_subprocess_stderr(err) or "unknown error"
                    return {"success": False, "error": f"ffmpeg soft-sub mux failed (rc={code}): {summary}"}

            return {
                "success": True,
                "video_path": output_mp4,
                "subtitle_path": output_srt,
                "language": language,
                "fps": fps,
                "width": width,
                "height": height,
                "embed_subtitles": embed_subtitles,
                "render_mode": "live",
                "video_encoder": video_encoder,
                "transcode_parallelism": trans_parallelism,
            }
        finally:
            speech_repo.close()
            audio_repo.close()
            temp_artifacts.cleanup()

    def _build_live_single_slide_html(self, slide_html: str, *, width: int, height: int) -> str:
        slide_json = json.dumps(slide_html or "", ensure_ascii=False).replace("</", "<\\/")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LandPPT Slide</title>
  <style>
    html, body {{
      width: 100%;
      height: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: #000;
      /* Start hidden to prevent recording loading process */
      opacity: 0;
    }}
    html.ready, body.ready {{
      opacity: 1;
    }}
    #stage {{
      position: fixed;
      inset: 0;
      background: #000;
    }}
    #frame {{
      position: absolute;
      top: 50%;
      left: 50%;
      width: 1280px;
      height: 720px;
      border: 0;
      background: transparent;
      transform: translate(-50%, -50%) scale(1);
      transform-origin: center center;
    }}
  </style>
</head>
<body>
  <div id="stage">
    <iframe id="frame" title="slide"></iframe>
  </div>
  <script>
    const BASE_W = 1280;
    const BASE_H = 720;
    const READY_EXTRA_MS = 250;
    const LOAD_TIMEOUT_MS = 15000;
    const STABLE_CHECKS = 3;
    const STABLE_INTERVAL_MS = 200;
    const SLIDE = {slide_json};
    const frame = document.getElementById('frame');
    
    function applyScale() {{
      const w = window.innerWidth || {width};
      const h = window.innerHeight || {height};
      const sx = w / BASE_W;
      const sy = h / BASE_H;
      const scale = Math.max(sx, sy);
      frame.style.transform = 'translate(-50%, -50%) scale(' + scale + ')';
    }}
    
    window.addEventListener('DOMContentLoaded', async () => {{
      applyScale();
      window.addEventListener('resize', applyScale);
      window.__lpSlideReady = false;
      window.__lpReadyAt = 0;
      
      const sleep = (ms) => new Promise(r => setTimeout(r, ms));
      const raf2 = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const withTimeout = async (promise, timeoutMs) => {{
        await Promise.race([
          Promise.resolve(promise).catch(() => null),
          sleep(timeoutMs),
        ]);
      }};

      function getFrameState(doc) {{
        const body = doc && doc.body ? doc.body : null;
        const canvases = Array.from(doc ? (doc.querySelectorAll('canvas') || []) : []);
        const svgs = Array.from(doc ? (doc.querySelectorAll('svg') || []) : []);
        const images = Array.from(doc ? (doc.images || []) : []);
        const visible = !!(
          body &&
          (
            Array.from(body.querySelectorAll('*')).some(el => {{
              const rect = el.getBoundingClientRect();
              return rect.width > 2 && rect.height > 2;
            }}) ||
            canvases.length > 0 ||
            svgs.length > 0
          )
        );
        const imagesReady = images.every(img => img.complete);
        const canvasSig = canvases.map(c => `${{c.width}}x${{c.height}}`).join(',');
        const svgSig = svgs.map(svg => svg.childElementCount || 0).join(',');
        const textLen = body && body.innerText ? body.innerText.replace(/\\s+/g, '').length : 0;
        const hash = [
          doc && (doc.readyState === 'complete' || doc.readyState === 'interactive') ? 1 : 0,
          imagesReady ? 1 : 0,
          visible ? 1 : 0,
          body ? body.scrollWidth : 0,
          body ? body.scrollHeight : 0,
          canvasSig,
          svgSig,
          textLen,
        ].join('|');
        return {{
          ready: !!(doc && (doc.readyState === 'complete' || doc.readyState === 'interactive')),
          imagesReady,
          visible,
          hash,
        }};
      }}

      async function waitForFrameStable(doc) {{
        const start = performance.now();
        let lastHash = '';
        let stableCount = 0;

        while (performance.now() - start < LOAD_TIMEOUT_MS) {{
          const state = getFrameState(doc);
          if (state.ready && state.imagesReady && state.visible && state.hash === lastHash) {{
            stableCount += 1;
            if (stableCount >= STABLE_CHECKS) {{
              return true;
            }}
          }} else {{
            stableCount = 0;
          }}
          lastHash = state.hash;
          await sleep(STABLE_INTERVAL_MS);
        }}
        return false;
      }}

      function collectCssImageUrls(doc) {{
        const urls = new Set();
        const URL_RE = /url\\(\\s*(['"]?)(.*?)\\1\\s*\\)/gi;

        function addFromText(text) {{
          if (!text || typeof text !== 'string') return;
          let match;
          while ((match = URL_RE.exec(text)) !== null) {{
            const value = (match[2] || '').trim();
            if (!value || value === 'none') continue;
            const lower = value.toLowerCase();
            if (
              lower.startsWith('data:') ||
              lower.startsWith('blob:') ||
              lower.startsWith('javascript:') ||
              lower.startsWith('about:')
            ) {{
              continue;
            }}
            urls.add(value);
          }}
        }}

        if (!doc) return [];

        const allElements = Array.from(doc.querySelectorAll('*') || []);
        allElements.forEach(el => {{
          try {{
            addFromText(el.getAttribute('style') || '');
          }} catch (e) {{}}
          try {{
            const view = doc.defaultView || window;
            const style = view.getComputedStyle(el);
            addFromText(style.backgroundImage);
            addFromText(style.borderImageSource);
            addFromText(style.maskImage);
            addFromText(style.webkitMaskImage);
            addFromText(style.content);
          }} catch (e) {{}}
        }});

        Array.from(doc.querySelectorAll('style') || []).forEach(styleEl => {{
          try {{
            addFromText(styleEl.textContent || '');
          }} catch (e) {{}}
        }});

        return Array.from(urls);
      }}

      async function waitForCssImages(doc) {{
        const urls = collectCssImageUrls(doc);
        if (!urls.length) return;

        await withTimeout(Promise.all(urls.map(url => new Promise(resolve => {{
          try {{
            const img = new Image();
            let done = false;
            const finish = () => {{
              if (done) return;
              done = true;
              resolve();
            }};
            img.addEventListener('load', finish, {{ once: true }});
            img.addEventListener('error', finish, {{ once: true }});
            img.src = url;
            if (img.complete) finish();
          }} catch (e) {{
            resolve();
          }}
        }}))), 8000);
      }}

      async function waitFullyLoaded() {{
        try {{
          // Stage 1: Wait for all top-level resources
          await withTimeout(new Promise(resolve => {{
            if (document.readyState === 'complete') {{
              resolve();
            }} else {{
              window.addEventListener('load', resolve, {{ once: true }});
            }}
          }}), LOAD_TIMEOUT_MS);
          
          // Stage 2: Wait for fonts
          if (document.fonts) {{
            await withTimeout(document.fonts.ready, 5000);
          }}
          
          // Stage 3: Wait for iframe load
          await withTimeout(new Promise(resolve => {{
            const doc = frame.contentDocument;
            if (doc && (doc.readyState === 'complete' || doc.readyState === 'interactive')) {{
              resolve();
            }} else {{
              frame.addEventListener('load', resolve, {{ once: true }});
            }}
          }}), LOAD_TIMEOUT_MS);
          
          // Stage 4: Wait for iframe content
          const doc = frame.contentDocument;
          if (doc) {{
            // Inject reset styles
            if (doc.head && !doc.getElementById('lp-export-reset')) {{
              const style = doc.createElement('style');
              style.id = 'lp-export-reset';
              style.textContent = 'html,body{{margin:0;padding:0;overflow:hidden;}}';
              doc.head.appendChild(style);
            }}
            
            // Wait for iframe fonts
            if (doc.fonts) {{
              await withTimeout(doc.fonts.ready, 5000);
            }}
            
            // Wait for iframe images
            const imgs = Array.from(doc.images || []);
            imgs.forEach(img => {{
              try {{
                img.loading = 'eager';
                img.decoding = 'sync';
              }} catch (e) {{}}
            }});
            await withTimeout(Promise.all(imgs.map(img => {{
              if (img.complete) return Promise.resolve();
              return new Promise(resolve => {{
                img.addEventListener('load', resolve, {{ once: true }});
                img.addEventListener('error', resolve, {{ once: true }});
              }});
            }})), 8000);

            await waitForCssImages(doc);

            await waitForFrameStable(doc);
          }}
          
          // Stage 5: RAF double-buffering to ensure rendering complete
          await raf2();
          
          // Stage 6: Extra stability time
          await sleep(READY_EXTRA_MS);
          
        }} catch (e) {{
          console.warn('Loading wait error:', e);
        }}
      }}

      frame.onload = async () => {{
        applyScale();
        
        // Wait for everything to fully load
        await waitFullyLoaded();
        
        // Now make page visible
        document.documentElement.classList.add('ready');
        document.body.classList.add('ready');
        
        // Signal ready AFTER page is visible
        await raf2();
        if (!window.__lpSlideReady) {{
          window.__lpSlideReady = true;
          window.__lpReadyAt = performance.now();
        }}
      }};
      
      // Safety timeout
      setTimeout(() => {{
        if (!window.__lpSlideReady) {{
          // Force visible even if loading incomplete
          document.documentElement.classList.add('ready');
          document.body.classList.add('ready');
          window.__lpSlideReady = true;
          window.__lpReadyAt = performance.now();
        }}
      }}, LOAD_TIMEOUT_MS + 2000);
      
      frame.srcdoc = SLIDE;
    }});
  </script>
</body>
</html>
"""

    def _build_live_player_html(
        self,
        *,
        slides: List[str],
        durations_ms: List[int],
        width: int,
        height: int,
    ) -> str:
        # Escape </script> to avoid breaking out of the JSON script tag.
        slides_json = json.dumps(slides, ensure_ascii=False).replace("</", "<\\/")
        durations_json = json.dumps([int(x) for x in durations_ms], ensure_ascii=False)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LandPPT Playback</title>
  <style>
    html, body {{
      width: 100%;
      height: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: #000;
    }}
    #stage {{
      position: fixed;
      inset: 0;
      background: #000;
    }}
    #frame {{
      position: absolute;
      top: 50%;
      left: 50%;
      width: 1280px;
      height: 720px;
      border: 0;
      background: transparent;
      transform: translate(-50%, -50%) scale(1);
      transform-origin: center center;
    }}
  </style>
</head>
<body>
  <div id="stage">
    <iframe id="frame" title="slide"></iframe>
  </div>
  <script>
    const BASE_W = 1280;
    const BASE_H = 720;
    const SLIDES = {slides_json};
    const DURATIONS = {durations_json};
    const frame = document.getElementById('frame');
    let current = 0;
    let token = 0;

    function applyScale() {{
      const w = window.innerWidth || {width};
      const h = window.innerHeight || {height};
      const sx = w / BASE_W;
      const sy = h / BASE_H;
      const scale = Math.max(sx, sy); // cover
      frame.style.width = BASE_W + 'px';
      frame.style.height = BASE_H + 'px';
      frame.style.transform = 'translate(-50%, -50%) scale(' + scale + ')';
    }}

    function loadSlide(index) {{
      token += 1;
      const t = token;
      frame.onload = () => {{
        if (t !== token) return;
        applyScale();
        try {{
          const doc = frame.contentDocument;
          if (doc && doc.head && !doc.getElementById('lp-export-reset')) {{
            const style = doc.createElement('style');
            style.id = 'lp-export-reset';
            style.textContent = 'html,body{{margin:0;padding:0;overflow:hidden;}}';
            doc.head.appendChild(style);
          }}
        }} catch (e) {{}}
      }};
      frame.srcdoc = SLIDES[index] || '<html><body></body></html>';
    }}

    function scheduleNext() {{
      const d = Math.max(250, Number(DURATIONS[current] || 2000));
      setTimeout(() => {{
        current += 1;
        if (current >= SLIDES.length) {{
          window.__lpPlaybackDone = true;
          return;
        }}
        loadSlide(current);
        scheduleNext();
      }}, d);
    }}

    window.__lpPlaybackDone = false;
    window.addEventListener('DOMContentLoaded', () => {{
      applyScale();
      window.addEventListener('resize', applyScale);
      current = 0;
      loadSlide(0);
      scheduleNext();
    }});
  </script>
</body>
</html>
"""

    async def _export_project_video_static(
        self,
        *,
        project: Any,
        language: str,
        fps: int,
        width: int,
        height: int,
        embed_subtitles: bool,
        subtitle_style: Optional[Dict[str, Any]],
        uploads_dir: str,
    ) -> Dict[str, Any]:
        """Static fallback: screenshot each slide and stitch into a video."""
        render_service = self._get_html_render_service()

        from .narration_service import NarrationService
        from .narration_audio_repository import NarrationAudioRepository
        from .speech_script_repository import SpeechScriptRepository

        narration_service = NarrationService(user_id=getattr(project, "user_id", None))
        speech_repo = SpeechScriptRepository()
        audio_repo = NarrationAudioRepository()

        temp_artifacts = TempArtifactManager(prefix="landppt_video_")
        tmp_dir = temp_artifacts.create()
        try:
            # 1) Ensure audio per slide
            audios = await narration_service.generate_project_slide_audios(
                project_id=project.project_id,
                language=language,
                uploads_dir=uploads_dir,
            )
            audio_by_index = {a.slide_index: a for a in audios}

            # 2) Get speech scripts to build subtitles
            scripts = await speech_repo.get_current_speech_scripts_by_project(project.project_id, language=language)
            script_by_index = {s.slide_index: s for s in scripts}

            # 3) Render PNGs
            images_dir = os.path.join(tmp_dir, "images")
            os.makedirs(images_dir, exist_ok=True)

            html_dir = os.path.join(tmp_dir, "html")
            os.makedirs(html_dir, exist_ok=True)

            slide_count = len(project.slides_data)
            html_paths: Dict[int, str] = {}
            png_paths: Dict[int, str] = {}
            for i in range(slide_count):
                slide = project.slides_data[i] or {}
                slide_html = self._prepare_slide_html_for_video_export(
                    slide.get("html_content", ""),
                    title=f"Slide {i+1}",
                )
                # Wrap static screenshots in the same fixed 16:9 stage used by live export so we
                # always capture the full slide canvas instead of an inferred inner content box.
                html_content = self._build_live_single_slide_html(slide_html, width=width, height=height)
                html_path = os.path.join(html_dir, f"slide_{i}.html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                html_paths[i] = html_path
                png_paths[i] = os.path.join(images_dir, f"slide_{i}.png")

            # Render screenshots in parallel to speed up static exports.
            parallelism = _calculate_safe_screenshot_parallelism(width, height)
            sem = asyncio.Semaphore(parallelism)
            screenshot_dsf_env = (os.environ.get("LANDPPT_NARRATION_SCREENSHOT_DSF") or "").strip()
            try:
                screenshot_dsf = float(screenshot_dsf_env) if screenshot_dsf_env else 2.0
            except Exception:
                screenshot_dsf = 2.0
            screenshot_dsf = max(0.75, min(3.0, screenshot_dsf))

            rendered_indices: List[int] = []

            async def _render_one(idx: int) -> Tuple[int, bool]:
                async with sem:
                    ok = await render_service.screenshot_html(
                        html_paths[idx],
                        png_paths[idx],
                        width=width,
                        height=height,
                        crop_to_content=False,
                        wait_for_stable=True,
                        device_scale_factor=screenshot_dsf,
                    )
                    return idx, ok

            tasks = [asyncio.create_task(_render_one(i)) for i in range(slide_count)]
            try:
                for fut in asyncio.as_completed(tasks):
                    idx, ok = await fut
                    if not ok:
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        return {"success": False, "error": f"Slide screenshot failed at index={idx}"}
                    rendered_indices.append(idx)
            finally:
                # Ensure all tasks are awaited to avoid "Task was destroyed but it is pending!" warnings.
                await asyncio.gather(*tasks, return_exceptions=True)

            rendered_indices.sort()

            # 4) Build per-slide clips
            clips_dir = os.path.join(tmp_dir, "clips")
            os.makedirs(clips_dir, exist_ok=True)
            clips: List[str] = []
            subtitle_cues_by_audio_path: Dict[str, Optional[str]] = {}
            try:
                rows = await audio_repo.list_by_project(project_id=project.project_id, language=language)
                subtitle_cues_by_audio_path = _build_cues_by_audio_path(rows)
            except Exception:
                subtitle_cues_by_audio_path = {}

            for i in rendered_indices:
                audio = audio_by_index.get(i)
                if not audio or not audio.audio_path or not os.path.exists(audio.audio_path):
                    return {"success": False, "error": f"Missing narration audio for slide {i+1} (language={language})"}
                duration_ms = int(audio.duration_ms or 0)
                if duration_ms <= 0:
                    # fallback: 2s minimum
                    duration_ms = 2000

                png_path = os.path.join(images_dir, f"slide_{i}.png")
                clip_path = os.path.join(clips_dir, f"clip_{i}.mp4")
                duration_sec = max(0.1, duration_ms / 1000.0)

                ffmpeg_args = [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-t",
                    f"{duration_sec:.3f}",
                    "-i",
                    png_path,
                    "-i",
                    audio.audio_path,
                    "-r",
                    str(fps),
                    "-vf",
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
                    "-c:v",
                    "libx264",
                    "-threads",
                    (os.environ.get("LANDPPT_X264_THREADS") or "2"),
                    "-preset",
                    os.environ.get("LANDPPT_X264_PRESET", "ultrafast"),
                    "-crf",
                    os.environ.get("LANDPPT_X264_CRF", "23"),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    clip_path,
                ]
                code, _, err = await _run_subprocess(ffmpeg_args)
                if code != 0:
                    last = (err.splitlines()[-1] if err else "").strip()
                    return {"success": False, "error": f"ffmpeg clip failed on slide {i+1}: {last or 'unknown error'}"}

                clips.append(clip_path)

            # 5) Concat clips
            concat_list = os.path.join(tmp_dir, "concat.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                for clip in clips:
                    f.write(f"file '{clip}'\n")

            merged_path = os.path.join(tmp_dir, "merged.mp4")
            concat_args = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-c",
                "copy",
                merged_path,
            ]
            code, _, err = await _run_subprocess(concat_args)
            if code != 0:
                last = (err.splitlines()[-1] if err else "").strip()
                return {"success": False, "error": f"ffmpeg concat failed: {last or 'unknown error'}"}

            # 6) Build SRT from cues_json (preferred) or script text (fallback)
            cursor_ms = 0
            all_cues: List[SubtitleCue] = []
            for i in rendered_indices:
                audio = audio_by_index.get(i)
                duration_ms = int(audio.duration_ms or 0) if audio else 0
                if duration_ms <= 0:
                    duration_ms = 2000

                audio_key = _normalize_audio_cache_path(getattr(audio, "audio_path", None))
                cues_json = subtitle_cues_by_audio_path.get(audio_key)
                used = False
                if cues_json:
                    try:
                        items = json.loads(cues_json) or []
                        for it in items:
                            t = (it.get("text") or "").strip()
                            if not t:
                                continue
                            s = int(it.get("start_ms") or 0)
                            e = int(it.get("end_ms") or 0)
                            if e <= s:
                                continue
                            all_cues.append(
                                SubtitleCue(
                                    start_ms=cursor_ms + max(0, s),
                                    end_ms=cursor_ms + min(duration_ms, e),
                                    text=t,
                                )
                            )
                        used = True
                    except Exception:
                        used = False

                if not used:
                    slide_text = (script_by_index.get(i).script_content if script_by_index.get(i) else "") or ""
                    all_cues.extend(
                        build_slide_cues(
                            slide_text=slide_text,
                            slide_start_ms=cursor_ms,
                            slide_duration_ms=duration_ms,
                            max_chars_per_line=36,
                        )
                    )

                cursor_ms += duration_ms

            srt = build_srt(all_cues)
            srt_path = os.path.join(tmp_dir, "subtitles.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt)

            # 7) Final mp4 (burn-in or soft subs)
            out_dir = os.path.join(uploads_dir, "narration_videos", project.project_id, language)
            out_dir_abs = str(Path(out_dir).resolve())
            os.makedirs(out_dir_abs, exist_ok=True)
            topic_stem = _safe_filename_stem(getattr(project, "topic", "") or "PPT")
            output_mp4 = os.path.join(out_dir_abs, f"{topic_stem}_{language}_{fps}fps_1080p.mp4")
            output_srt = os.path.join(out_dir_abs, f"{topic_stem}_{language}.srt")
            shutil.copyfile(srt_path, output_srt)

            style = _resolve_subtitle_style(subtitle_style, height=height, render_mode="static")
            if embed_subtitles:
                vf = _build_subtitle_filter(subtitle_path=srt_path, width=width, height=height, style=style)
                burn_args = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    merged_path,
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-threads",
                    (os.environ.get("LANDPPT_X264_THREADS") or "2"),
                    "-preset",
                    os.environ.get("LANDPPT_X264_PRESET", "ultrafast"),
                    "-crf",
                    os.environ.get("LANDPPT_X264_CRF", "23"),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "copy",
                    "-movflags",
                    "+faststart",
                    output_mp4,
                ]
                code, _, err = await _run_subprocess(burn_args, cwd=tmp_dir)
                if code != 0:
                    last = (err.splitlines()[-1] if err else "").strip()
                    return {"success": False, "error": f"ffmpeg burn-in subtitles failed: {last or 'unknown error'}"}
            else:
                soft_args = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    merged_path,
                    "-i",
                    srt_path,
                    "-c",
                    "copy",
                    "-c:s",
                    "mov_text",
                    "-movflags",
                    "+faststart",
                    output_mp4,
                ]
                code, _, err = await _run_subprocess(soft_args, cwd=tmp_dir)
                if code != 0:
                    last = (err.splitlines()[-1] if err else "").strip()
                    return {"success": False, "error": f"ffmpeg soft subtitles failed: {last or 'unknown error'}"}

            return {
                "success": True,
                "video_path": output_mp4,
                "subtitle_path": output_srt,
                "language": language,
                "fps": fps,
                "width": width,
                "height": height,
                "embed_subtitles": embed_subtitles,
                "render_mode": "static",
            }
        finally:
            speech_repo.close()
            audio_repo.close()
            temp_artifacts.cleanup()
