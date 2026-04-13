"""
Narration (TTS) service.

Primary provider: Edge-TTS (edge-tts).
OpenAI TTS can be added later behind the same interface.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import app_config
from .subtitle_service import build_slide_cues_snapped

logger = logging.getLogger(__name__)


DEFAULT_VOICE_ZH = "zh-CN-XiaoxiaoNeural"
DEFAULT_VOICE_EN = "en-US-JennyNeural"


@dataclass(frozen=True)
class NarrationAudioResult:
    slide_index: int
    language: str
    voice: str
    rate: str
    audio_path: str
    duration_ms: Optional[int]
    cached: bool


def _hash_for_tts(*, provider: str, language: str, voice: str, rate: str, text: str) -> str:
    payload = f"{provider}|{language}|{voice}|{rate}|{text}".encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def is_edge_tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        return False


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def sha256_for_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _run_subprocess(args: List[str]) -> Tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    out = out_b.decode("utf-8", errors="ignore")
    err = err_b.decode("utf-8", errors="ignore")
    return proc.returncode, out, err


async def ffprobe_duration_ms(audio_path: str) -> Optional[int]:
    if not shutil.which("ffprobe"):
        return None

    args = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    code, out, err = await _run_subprocess(args)
    if code != 0:
        logger.warning(f"ffprobe failed for {audio_path}: {err.strip()}")
        return None
    try:
        seconds = float(out.strip())
        return max(0, int(seconds * 1000))
    except Exception:
        return None


_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")
CUE_PAYLOAD_VERSION = 2


def _parse_silence_spans_ms(ffmpeg_stderr: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    current_start: Optional[float] = None
    for line in (ffmpeg_stderr or "").splitlines():
        m1 = _SILENCE_START_RE.search(line)
        if m1:
            try:
                current_start = float(m1.group(1))
            except Exception:
                current_start = None
            continue
        m2 = _SILENCE_END_RE.search(line)
        if m2 and current_start is not None:
            try:
                end = float(m2.group(1))
                start_ms = max(0, int(current_start * 1000))
                end_ms = max(start_ms, int(end * 1000))
                if end_ms > start_ms:
                    spans.append((start_ms, end_ms))
            except Exception:
                pass
            current_start = None
    return spans


def _derive_speech_window_ms(duration_ms: int, silence_spans_ms: List[Tuple[int, int]]) -> Tuple[int, int]:
    duration_ms = max(0, int(duration_ms))
    if duration_ms <= 0:
        return 0, 0

    speech_start_ms = 0
    speech_end_ms = duration_ms
    if silence_spans_ms:
        first_start_ms, first_end_ms = silence_spans_ms[0]
        if first_start_ms <= 120:
            speech_start_ms = min(duration_ms, max(0, first_end_ms))

        last_start_ms, last_end_ms = silence_spans_ms[-1]
        if last_end_ms >= duration_ms - 120:
            speech_end_ms = max(speech_start_ms, min(duration_ms, last_start_ms))

    if speech_end_ms - speech_start_ms < 250:
        return 0, duration_ms
    return speech_start_ms, speech_end_ms


def _extract_internal_boundary_mids_ms(
    silence_spans_ms: List[Tuple[int, int]],
    *,
    speech_start_ms: int,
    speech_end_ms: int,
) -> List[int]:
    mids: List[int] = []
    for start_ms, end_ms in silence_spans_ms:
        mid_ms = (int(start_ms) + int(end_ms)) // 2
        if mid_ms <= speech_start_ms + 120:
            continue
        if mid_ms >= speech_end_ms - 120:
            continue
        mids.append(mid_ms)
    return sorted(set(mids))


def _extract_cue_payload_version(cues_json: Optional[str]) -> int:
    if not cues_json:
        return 0
    try:
        payload = json.loads(cues_json)
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            version = payload[0].get("__lp_cue_version")
            if version is not None:
                return int(version)
    except Exception:
        pass
    return 1


async def detect_silence_spans_ms(audio_path: str) -> List[Tuple[int, int]]:
    if not shutil.which("ffmpeg"):
        return []

    args = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-v",
        "info",
        "-i",
        audio_path,
        "-af",
        "silencedetect=n=-35dB:d=0.15",
        "-f",
        "null",
        "-",
    ]
    code, _, err = await _run_subprocess(args)
    if code != 0:
        return []
    return _parse_silence_spans_ms(err)


async def detect_silence_boundary_mids_ms(audio_path: str) -> List[int]:
    """
    Detect pause boundaries in audio using ffmpeg silencedetect.
    Returns a list of silence midpoints (ms), relative to audio start.
    """
    silence_spans_ms = await detect_silence_spans_ms(audio_path)
    return [((start_ms + end_ms) // 2) for start_ms, end_ms in silence_spans_ms if end_ms > start_ms]


async def build_cues_json_for_audio(*, text: str, audio_path: str, duration_ms: int) -> Optional[str]:
    """
    Build per-sentence subtitle cues for a slide, aligned to detected pauses when possible.
    Stored as JSON list with fields: start_ms, end_ms, text (all relative to slide start).
    """
    text = (text or "").strip()
    if not text or duration_ms <= 0:
        return None

    silence_spans_ms: List[Tuple[int, int]] = []
    try:
        silence_spans_ms = await detect_silence_spans_ms(audio_path)
    except Exception:
        silence_spans_ms = []

    speech_start_ms, speech_end_ms = _derive_speech_window_ms(duration_ms, silence_spans_ms)
    effective_duration_ms = max(250, speech_end_ms - speech_start_ms)
    boundary_mids_ms = [
        mid_ms - speech_start_ms
        for mid_ms in _extract_internal_boundary_mids_ms(
            silence_spans_ms,
            speech_start_ms=speech_start_ms,
            speech_end_ms=speech_end_ms,
        )
    ]

    cues = build_slide_cues_snapped(
        slide_text=text,
        slide_start_ms=speech_start_ms,
        slide_duration_ms=effective_duration_ms,
        boundary_mids_ms=boundary_mids_ms,
        max_chars_per_line=36,
        snap_tolerance_ms=900,
    )
    cue_items = [{"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text} for c in cues if c.text]
    if not cue_items:
        return None

    payload: List[Dict[str, Any]] = [
        {
            "__lp_cue_version": CUE_PAYLOAD_VERSION,
            "speech_start_ms": speech_start_ms,
            "speech_end_ms": speech_end_ms,
            "duration_ms": int(duration_ms),
        }
    ]
    payload.extend(cue_items)
    return json.dumps(payload, ensure_ascii=False)


class NarrationService:
    def __init__(self, *, user_id: Optional[int] = None):
        # Normalize user_id to int when possible (some call sites may pass a string).
        try:
            self.user_id = int(user_id) if user_id is not None else None
        except Exception:
            self.user_id = None

    async def _get_default_voice_from_config(self, *, language: str) -> Optional[str]:
        """
        Resolve per-language default voice from database config.

        Returns None if user_id is not set or config is unavailable/empty.
        """
        if self.user_id is None:
            return None

        lang = (language or "").strip().lower()
        if lang.startswith("zh"):
            key = "tts_voice_zh"
        elif lang.startswith("en"):
            key = "tts_voice_en"
        else:
            return None

        try:
            from .db_config_service import get_db_config_service

            config_service = get_db_config_service()
            value = await config_service.get_config_value(key, user_id=self.user_id)
            value = (str(value) if value is not None else "").strip()
            return value or None
        except Exception:
            return None

    @staticmethod
    def _resolve_comfyui_workflow_path(workflow_path: str) -> Optional[str]:
        """
        Resolve workflow_path safely to a JSON file under the project working directory.

        Returns None if invalid/not found.
        """
        raw = (workflow_path or "").strip()
        if not raw:
            return None
        # Allow remote JSON URLs (useful for cloud deployments).
        if raw.lower().startswith(("http://", "https://")):
            try:
                url = raw
                cache_dir = (Path.cwd() / "uploads" / "comfyui_workflows").resolve()
                cache_dir.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
                out_path = (cache_dir / f"{digest}.json").resolve()

                if out_path.exists() and out_path.is_file() and out_path.stat().st_size > 0:
                    return str(out_path)

                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "LandPPT/ComfyUI-TTS-Workflow-Fetcher",
                        "Accept": "application/json,text/plain,*/*",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()

                text = data.decode("utf-8-sig")
                obj = json.loads(text)

                tmp_path = (cache_dir / f".{digest}.tmp").resolve()
                tmp_path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                tmp_path.replace(out_path)
                return str(out_path)
            except Exception:
                return None
        try:
            p = Path(raw)
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            else:
                p = p.resolve()

            root = Path.cwd().resolve()
            if p != root and root not in p.parents:
                return None
            if p.suffix.lower() != ".json":
                return None
            if not p.exists() or not p.is_file():
                return None
            return str(p)
        except Exception:
            return None

    async def _get_comfyui_tts_settings_from_config(self) -> Dict[str, Any]:
        """
        Read ComfyUI TTS settings from per-user DB config (generation_params).
        Returns a dict with optional keys: base_url, workflow_path, timeout_s.
        """
        if self.user_id is None:
            return {}
        try:
            from .db_config_service import get_db_config_service

            config_service = get_db_config_service()
            base_url = await config_service.get_config_value("comfyui_base_url", user_id=self.user_id)
            workflow_path = await config_service.get_config_value("comfyui_tts_workflow_path", user_id=self.user_id)
            timeout_s = await config_service.get_config_value("comfyui_tts_timeout_seconds", user_id=self.user_id)
            chunk_chars = await config_service.get_config_value("comfyui_tts_chunk_chars", user_id=self.user_id)
            force_precision = await config_service.get_config_value("comfyui_tts_force_precision", user_id=self.user_id)

            base_url_s = (str(base_url) if base_url is not None else "").strip()
            workflow_s = (str(workflow_path) if workflow_path is not None else "").strip()
            timeout_raw = (str(timeout_s) if timeout_s is not None else "").strip()
            chunk_raw = (str(chunk_chars) if chunk_chars is not None else "").strip()
            force_precision_s = (str(force_precision) if force_precision is not None else "").strip()

            parsed_timeout = None
            if timeout_raw:
                try:
                    parsed_timeout = int(float(timeout_raw))
                except Exception:
                    parsed_timeout = None

            parsed_chunk = None
            if chunk_raw:
                try:
                    parsed_chunk = int(float(chunk_raw))
                except Exception:
                    parsed_chunk = None

            out: Dict[str, Any] = {}
            if base_url_s:
                out["base_url"] = base_url_s
            if workflow_s:
                out["workflow_path"] = workflow_s
            if parsed_timeout is not None:
                out["timeout_s"] = parsed_timeout
            if parsed_chunk is not None:
                out["chunk_chars"] = parsed_chunk
            if force_precision_s:
                out["force_precision"] = force_precision_s
            return out
        except Exception:
            return {}

    @staticmethod
    def _split_text_for_tts(text: str, *, max_chars: int = 180) -> List[str]:
        """
        Split text into shorter chunks to reduce TTS memory/latency spikes (helps avoid GPU OOM).
        """
        t = (text or "").strip()
        if not t:
            return []
        max_chars = max(60, int(max_chars or 180))
        if len(t) <= max_chars:
            return [t]

        # Prefer sentence-ish boundaries.
        seps = set("。！？!?；;…\n")
        chunks: List[str] = []
        buf: List[str] = []
        buf_len = 0

        def flush():
            nonlocal buf, buf_len
            s = "".join(buf).strip()
            if s:
                chunks.append(s)
            buf = []
            buf_len = 0

        for ch in t:
            buf.append(ch)
            buf_len += 1
            if buf_len >= max_chars:
                flush()
                continue
            if ch in seps and buf_len >= max(40, max_chars // 3):
                flush()

        flush()
        return [c for c in chunks if c]

    @staticmethod
    def _is_oom_error(exc: Exception) -> bool:
        msg = (str(exc) or "").lower()
        return (
            ("outofmemory" in msg)
            or ("allocation on device" in msg)
            or ("cuda" in msg and "oom" in msg)
            or ("torch.oom" in msg)
        )

    @staticmethod
    def _split_chunk_in_half(text: str) -> List[str]:
        t = (text or "").strip()
        if not t:
            return []
        if len(t) <= 60:
            return [t]

        mid = len(t) // 2
        # Prefer split near punctuation/space around the middle.
        candidates = []
        for i in range(max(0, mid - 60), min(len(t), mid + 60)):
            if t[i] in "。！？!?；;，,、 \n\t":
                candidates.append(i)
        if candidates:
            # Choose closest to mid
            split_at = min(candidates, key=lambda i: abs(i - mid))
        else:
            split_at = mid

        left = t[: split_at + 1].strip()
        right = t[split_at + 1 :].strip()
        parts = [p for p in [left, right] if p]
        return parts or [t]

    async def _ensure_speech_scripts(
        self,
        *,
        project_id: str,
        language: str,
        slide_indices: Optional[List[int]] = None,
    ):
        """
        Ensure speech scripts exist for the requested language.

        When missing, auto-generate scripts from the current slide content and persist them
        so narration/audio/video export can proceed without a separate manual script step.
        """
        language = (language or "zh").strip().lower() or "zh"

        from .speech_script_repository import SpeechScriptRepository

        speech_repo = SpeechScriptRepository()
        try:
            existing = await speech_repo.get_current_speech_scripts_by_project(project_id, language=language)
            wanted = set(slide_indices) if slide_indices else None
            existing_by_index = {s.slide_index: s for s in (existing or [])}

            # Need project to know slide count and titles (and to ensure full coverage when slide_indices is None).
            from .db_project_manager import DatabaseProjectManager
            from .speech_script_service import SpeechScriptCustomization, SpeechScriptService

            db_manager = DatabaseProjectManager()
            project = await db_manager.get_project(project_id, user_id=self.user_id)
            if not project or not getattr(project, "slides_data", None):
                raise RuntimeError("Project slides not found; cannot auto-generate speech scripts.")

            if wanted is None:
                wanted = set(range(len(project.slides_data)))
            wanted = set(i for i in wanted if 0 <= i < len(project.slides_data))
            if not wanted:
                return []

            # If all requested slides already have scripts, return them in order.
            if all(i in existing_by_index for i in wanted):
                return [existing_by_index[i] for i in sorted(wanted)]

            # Generate only missing indices.
            missing = [i for i in sorted(wanted) if i not in existing_by_index]
            if not missing:
                return [existing_by_index[i] for i in sorted(wanted)]

            speech_service = SpeechScriptService(user_id=self.user_id)
            await speech_service.initialize_async()
            customization = SpeechScriptCustomization(language=language)
            result = await speech_service.generate_multi_slide_scripts(project, missing, customization)
            if not result.success:
                raise RuntimeError(result.error_message or f"Failed to auto-generate speech scripts for '{language}'.")

            generation_params = {
                "generation_type": "multi",
                "tone": customization.tone.value,
                "target_audience": customization.target_audience.value,
                "language_complexity": customization.language_complexity.value,
                "custom_audience": None,
                "custom_style_prompt": customization.custom_style_prompt,
                "include_transitions": customization.include_transitions,
                "include_timing_notes": customization.include_timing_notes,
                "speaking_pace": customization.speaking_pace,
            }

            for script in result.scripts:
                await speech_repo.save_speech_script(
                    project_id=project_id,
                    slide_index=script.slide_index,
                    language=language,
                    slide_title=script.slide_title,
                    script_content=script.script_content,
                    generation_params=generation_params,
                    estimated_duration=script.estimated_duration,
                )

            # Re-read to return the persisted scripts.
            persisted = await speech_repo.get_current_speech_scripts_by_project(project_id, language=language)
            persisted_by_index = {s.slide_index: s for s in (persisted or [])}
            return [persisted_by_index[i] for i in sorted(wanted) if i in persisted_by_index]
        finally:
            speech_repo.close()

    async def generate_project_slide_audios(
        self,
        *,
        project_id: str,
        slide_indices: Optional[List[int]] = None,
        provider: str = "auto",
        language: str = "zh",
        voice: Optional[str] = None,
        rate: str = "+0%",
        reference_audio_path: Optional[str] = None,
        reference_text: str = "",
        force_regenerate: bool = False,
        uploads_dir: str = "uploads",
    ) -> List[NarrationAudioResult]:
        provider = (provider or "auto").strip().lower()
        if provider not in {"auto", "edge_tts", "comfyuiapi"}:
            raise RuntimeError(f"Unsupported TTS provider: {provider}")

        language = (language or "zh").strip().lower() or "zh"

        if provider == "auto":
            # Prefer existing latest audio for each slide; generate missing with Edge-TTS.
            from .narration_audio_repository import NarrationAudioRepository

            audio_repo = NarrationAudioRepository()
            try:
                scripts = await self._ensure_speech_scripts(
                    project_id=project_id,
                    language=language,
                    slide_indices=slide_indices,
                )
                if not scripts:
                    raise RuntimeError(
                        f"No speech scripts found for language='{language}' and auto-generation produced none."
                    )

                wanted = set(slide_indices) if slide_indices else None
                outputs: List[NarrationAudioResult] = []
                missing: List[int] = []

                for script in scripts:
                    if wanted is not None and script.slide_index not in wanted:
                        continue
                    row = await audio_repo.get_latest_for_slide(
                        project_id=project_id, slide_index=int(script.slide_index), language=language
                    )
                    if (
                        (not force_regenerate)
                        and row
                        and getattr(row, "file_path", None)
                        and os.path.exists(row.file_path)
                        and os.path.getsize(row.file_path) > 0
                    ):
                        outputs.append(
                            NarrationAudioResult(
                                slide_index=int(script.slide_index),
                                language=language,
                                voice=getattr(row, "voice", "") or "",
                                rate=getattr(row, "rate", "+0%") or "+0%",
                                audio_path=row.file_path,
                                duration_ms=getattr(row, "duration_ms", None),
                                cached=True,
                            )
                        )
                    else:
                        missing.append(int(script.slide_index))
            finally:
                audio_repo.close()

            if not missing:
                return sorted(outputs, key=lambda r: r.slide_index)

            generated = await self.generate_project_slide_audios(
                project_id=project_id,
                slide_indices=missing,
                provider="edge_tts",
                language=language,
                voice=voice,
                rate=rate,
                force_regenerate=force_regenerate,
                uploads_dir=uploads_dir,
            )
            by_index = {r.slide_index: r for r in outputs}
            for r in generated:
                by_index[r.slide_index] = r
            return [by_index[i] for i in sorted(by_index.keys())]

        if provider == "comfyuiapi":
            return await self._generate_project_slide_audios_comfyuiapi(
                project_id=project_id,
                slide_indices=slide_indices,
                language=language,
                voice=voice,
                rate=rate,
                reference_audio_path=reference_audio_path,
                reference_text=reference_text,
                force_regenerate=force_regenerate,
                uploads_dir=uploads_dir,
            )

        # edge_tts provider
        if not is_edge_tts_available():
            raise RuntimeError("edge-tts not installed. Please install: pip install edge-tts")
        requested_voice = (str(voice) if voice is not None else "").strip()
        if requested_voice:
            voice = requested_voice
        else:
            config_voice = await self._get_default_voice_from_config(language=language)
            voice = (config_voice or (DEFAULT_VOICE_ZH if language.startswith("zh") else DEFAULT_VOICE_EN)).strip()
        rate = (rate or "+0%").strip()

        logger.info(
            "Narration TTS settings: project_id=%s language=%s voice=%s rate=%s user_id=%s",
            project_id,
            language,
            voice,
            rate,
            self.user_id,
        )

        from .narration_audio_repository import NarrationAudioRepository

        audio_repo = NarrationAudioRepository()
        try:
            # Auto-generate missing speech scripts for the requested language when needed.
            scripts = await self._ensure_speech_scripts(
                project_id=project_id,
                language=language,
                slide_indices=slide_indices,
            )
            if not scripts:
                raise RuntimeError(
                    f"No speech scripts found for language='{language}' and auto-generation produced none."
                )

            wanted = set(slide_indices) if slide_indices else None
            outputs: List[NarrationAudioResult] = []

            base_dir = os.path.join(uploads_dir, "narration", project_id, language)
            _ensure_dir(base_dir)

            # Generate in order for deterministic playback.
            for script in scripts:
                if wanted is not None and script.slide_index not in wanted:
                    continue

                text = (script.script_content or "").strip()
                if not text:
                    continue

                content_hash = _hash_for_tts(
                    provider=provider, language=language, voice=voice, rate=rate, text=text
                )
                filename = f"slide_{script.slide_index}_{content_hash[:12]}.mp3"
                out_path = os.path.join(base_dir, filename)

                cached_row = await audio_repo.get_cached_audio(
                    project_id=project_id,
                    slide_index=script.slide_index,
                    language=language,
                    provider=provider,
                    voice=voice,
                    rate=rate,
                    content_hash=content_hash,
                )

                if (
                    not force_regenerate
                    and cached_row
                    and cached_row.file_path
                    and os.path.exists(cached_row.file_path)
                ):
                    cue_version = _extract_cue_payload_version(getattr(cached_row, "cues_json", None))
                    if cue_version < CUE_PAYLOAD_VERSION:
                        try:
                            duration_ms = cached_row.duration_ms
                            if duration_ms is None:
                                duration_ms = await ffprobe_duration_ms(cached_row.file_path)
                            if duration_ms is not None:
                                cues_json = await build_cues_json_for_audio(
                                    text=text, audio_path=cached_row.file_path, duration_ms=int(duration_ms)
                                )
                                await audio_repo.upsert_audio(
                                    project_id=project_id,
                                    slide_index=script.slide_index,
                                    language=language,
                                    provider=provider,
                                    voice=voice,
                                    rate=rate,
                                    audio_format="mp3",
                                    content_hash=content_hash,
                                    file_path=cached_row.file_path,
                                    duration_ms=duration_ms,
                                    cues_json=cues_json,
                                )
                                cached_row.duration_ms = duration_ms
                                cached_row.cues_json = cues_json
                        except Exception:
                            pass

                    outputs.append(
                        NarrationAudioResult(
                            slide_index=script.slide_index,
                            language=language,
                            voice=voice,
                            rate=rate,
                            audio_path=cached_row.file_path,
                            duration_ms=cached_row.duration_ms,
                            cached=True,
                        )
                    )
                    continue

                if not force_regenerate and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    duration_ms = await ffprobe_duration_ms(out_path)
                    cues_json = None
                    try:
                        if duration_ms is not None:
                            cues_json = await build_cues_json_for_audio(
                                text=text, audio_path=out_path, duration_ms=int(duration_ms)
                            )
                    except Exception:
                        cues_json = None
                    await audio_repo.upsert_audio(
                        project_id=project_id,
                        slide_index=script.slide_index,
                        language=language,
                        provider=provider,
                        voice=voice,
                        rate=rate,
                        audio_format="mp3",
                        content_hash=content_hash,
                        file_path=out_path,
                        duration_ms=duration_ms,
                        cues_json=cues_json,
                    )
                    outputs.append(
                        NarrationAudioResult(
                            slide_index=script.slide_index,
                            language=language,
                            voice=voice,
                            rate=rate,
                            audio_path=out_path,
                            duration_ms=duration_ms,
                            cached=True,
                        )
                    )
                    continue

                # Write atomically: tmp then replace.
                # Create temp dir on the same filesystem as the destination to avoid cross-device rename errors
                # when /tmp is on a different mount (e.g., container tmpfs vs bind-mounted uploads).
                tmp_dir = tempfile.mkdtemp(prefix="landppt_tts_", dir=base_dir)
                try:
                    tmp_path = os.path.join(tmp_dir, filename)
                    import edge_tts

                    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
                    await communicate.save(tmp_path)
                    if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                        raise RuntimeError("TTS produced empty audio output")
                    try:
                        os.replace(tmp_path, out_path)
                    except OSError as exc:
                        # Fallback for rare cases where rename still crosses devices.
                        if getattr(exc, "errno", None) == 18:  # EXDEV
                            shutil.copyfile(tmp_path, out_path)
                            os.unlink(tmp_path)
                        else:
                            raise
                finally:
                    try:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

                duration_ms = await ffprobe_duration_ms(out_path)
                cues_json = None
                try:
                    if duration_ms is not None:
                        cues_json = await build_cues_json_for_audio(
                            text=text, audio_path=out_path, duration_ms=int(duration_ms)
                        )
                except Exception:
                    cues_json = None
                await audio_repo.upsert_audio(
                    project_id=project_id,
                    slide_index=script.slide_index,
                    language=language,
                    provider=provider,
                    voice=voice,
                    rate=rate,
                    audio_format="mp3",
                    content_hash=content_hash,
                    file_path=out_path,
                    duration_ms=duration_ms,
                    cues_json=cues_json,
                )

                outputs.append(
                    NarrationAudioResult(
                        slide_index=script.slide_index,
                        language=language,
                        voice=voice,
                        rate=rate,
                        audio_path=out_path,
                        duration_ms=duration_ms,
                        cached=False,
                    )
                )

            return outputs
        finally:
            audio_repo.close()

    async def _generate_project_slide_audios_comfyuiapi(
        self,
        *,
        project_id: str,
        slide_indices: Optional[List[int]],
        language: str,
        voice: Optional[str],
        rate: str,
        reference_audio_path: Optional[str],
        reference_text: str,
        force_regenerate: bool,
        uploads_dir: str,
    ) -> List[NarrationAudioResult]:
        ref_path = (reference_audio_path or "").strip()
        if not ref_path:
            raise RuntimeError("comfyuiapi provider requires reference_audio_path")
        if not os.path.exists(ref_path):
            raise RuntimeError(f"reference_audio_path not found: {ref_path}")

        provider = "comfyuiapi"
        voice_id = (str(voice) if voice is not None else "").strip() or "qwen3_td_voice_clone"
        rate = (rate or "+0%").strip()

        cfg = await self._get_comfyui_tts_settings_from_config()
        base_url = (
            (cfg.get("base_url") or getattr(app_config, "comfyui_base_url", None) or "http://127.0.0.1:8188")
        )
        base_url = (str(base_url) if base_url is not None else "").strip().rstrip("/") or "http://127.0.0.1:8188"

        workflow_raw = (cfg.get("workflow_path") or getattr(app_config, "comfyui_tts_workflow_path", None) or "").strip()
        resolved_workflow = self._resolve_comfyui_workflow_path(workflow_raw)
        if not resolved_workflow:
            resolved_workflow = self._resolve_comfyui_workflow_path("tests/Qwen3-TD-TTS.json")
        workflow_path = resolved_workflow or "tests/Qwen3-TD-TTS.json"

        timeout_s = cfg.get("timeout_s", None)
        if timeout_s is None:
            timeout_s = getattr(app_config, "comfyui_tts_timeout_seconds", 600) or 600
        try:
            timeout_s = int(timeout_s)
        except Exception:
            timeout_s = 600
        timeout_s = max(30, min(3600, timeout_s))

        ref_hash = sha256_for_file(ref_path)
        try:
            workflow_hash = sha256_for_file(workflow_path)
        except Exception:
            workflow_hash = "workflow_unknown"

        logger.info(
            "Narration TTS settings: provider=%s project_id=%s language=%s voice=%s rate=%s comfyui=%s user_id=%s",
            provider,
            project_id,
            language,
            voice_id,
            rate,
            base_url,
            self.user_id,
        )

        from .comfyui_tts_client import (
            build_qwen3_td_tts_workflow,
            download_file_via_view,
            extract_first_audio_fileinfo,
            load_workflow_template,
            submit_prompt,
            upload_input_file,
            wait_for_history,
        )

        from .narration_audio_repository import NarrationAudioRepository

        audio_repo = NarrationAudioRepository()
        try:
            scripts = await self._ensure_speech_scripts(
                project_id=project_id,
                language=language,
                slide_indices=slide_indices,
            )
            if not scripts:
                raise RuntimeError(
                    f"No speech scripts found for language='{language}' and auto-generation produced none."
                )

            wanted = set(slide_indices) if slide_indices else None
            outputs: List[NarrationAudioResult] = []

            base_dir = os.path.join(uploads_dir, "narration", project_id, language)
            _ensure_dir(base_dir)

            template = load_workflow_template(workflow_path)

            import aiohttp

            timeout = aiohttp.ClientTimeout(total=max(30, timeout_s))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                comfy_ref_name = await upload_input_file(session=session, base_url=base_url, file_path=ref_path)

                for script in scripts:
                    if wanted is not None and script.slide_index not in wanted:
                        continue

                    text = (script.script_content or "").strip()
                    if not text:
                        continue

                    # Chunk long text to reduce peak memory usage in ComfyUI Qwen3-TTS.
                    chunk_chars = int(cfg.get("chunk_chars", 120) or 120)
                    chunk_chars = max(40, min(500, chunk_chars))
                    chunks = self._split_text_for_tts(text, max_chars=chunk_chars)

                    extra = f"ref={ref_hash};wf={workflow_hash}"
                    content_hash = _hash_for_tts(
                        provider=provider,
                        language=language,
                        voice=voice_id,
                        rate=rate,
                        text=f"{extra}|{text}",
                    )

                    filename = f"slide_{script.slide_index}_{content_hash[:12]}.mp3"
                    out_path = os.path.join(base_dir, filename)

                    cached_row = await audio_repo.get_cached_audio(
                        project_id=project_id,
                        slide_index=script.slide_index,
                        language=language,
                        provider=provider,
                        voice=voice_id,
                        rate=rate,
                        content_hash=content_hash,
                    )
                    if (
                        not force_regenerate
                        and cached_row
                        and cached_row.file_path
                        and os.path.exists(cached_row.file_path)
                        and os.path.getsize(cached_row.file_path) > 0
                    ):
                        cue_version = _extract_cue_payload_version(getattr(cached_row, "cues_json", None))
                        if cue_version < CUE_PAYLOAD_VERSION:
                            try:
                                duration_ms = cached_row.duration_ms
                                if duration_ms is None:
                                    duration_ms = await ffprobe_duration_ms(cached_row.file_path)
                                cues_json = None
                                if duration_ms is not None:
                                    cues_json = await build_cues_json_for_audio(
                                        text=text,
                                        audio_path=cached_row.file_path,
                                        duration_ms=int(duration_ms),
                                    )
                                await audio_repo.upsert_audio(
                                    project_id=project_id,
                                    slide_index=script.slide_index,
                                    language=language,
                                    provider=provider,
                                    voice=voice_id,
                                    rate=rate,
                                    audio_format=(getattr(cached_row, "audio_format", None) or "mp3"),
                                    content_hash=content_hash,
                                    file_path=cached_row.file_path,
                                    duration_ms=duration_ms,
                                    cues_json=cues_json,
                                )
                                cached_row.duration_ms = duration_ms
                                cached_row.cues_json = cues_json
                            except Exception:
                                pass
                        outputs.append(
                            NarrationAudioResult(
                                slide_index=script.slide_index,
                                language=language,
                                voice=voice_id,
                                rate=rate,
                                audio_path=cached_row.file_path,
                                duration_ms=cached_row.duration_ms,
                                cached=True,
                            )
                        )
                        continue

                    # Always write atomically via tmp dir.
                    tmp_dir = tempfile.mkdtemp(prefix="landppt_tts_", dir=base_dir)
                    try:
                        segment_paths: List[str] = []
                        segment_ext: Optional[str] = None

                        forced_precision = (str(cfg.get("force_precision") or "")).strip() or None
                        seg_counter = 0

                        async def try_generate_segment(seg_text: str, *, precision: Optional[str]) -> str:
                            nonlocal segment_ext, seg_counter
                            workflow = build_qwen3_td_tts_workflow(
                                template,
                                text=seg_text,
                                ref_audio_filename=comfy_ref_name,
                                language=language,
                                ref_text=reference_text,
                                model_precision=precision,
                            )
                            prompt_id = await submit_prompt(session=session, base_url=base_url, workflow=workflow)
                            entry = await wait_for_history(
                                session=session, base_url=base_url, prompt_id=prompt_id, timeout_s=timeout_s
                            )
                            fn, subfolder, ftype = extract_first_audio_fileinfo(entry)
                            audio_bytes = await download_file_via_view(
                                session=session,
                                base_url=base_url,
                                filename=fn,
                                subfolder=subfolder,
                                file_type=ftype,
                            )
                            if not audio_bytes:
                                raise RuntimeError("ComfyUI returned empty audio output")

                            ext = os.path.splitext(fn)[1].lower() or ".wav"
                            if segment_ext is None:
                                segment_ext = ext
                            out_idx = seg_counter
                            seg_counter += 1
                            out_seg_path = os.path.join(tmp_dir, f"seg_{script.slide_index}_{out_idx}{ext}")
                            with open(out_seg_path, "wb") as f:
                                f.write(audio_bytes)
                            return out_seg_path

                        async def generate_with_backoff(seg_text: str, *, depth: int = 0) -> List[str]:
                            # 1) Try forced precision (if any) or default.
                            try:
                                p = forced_precision
                                return [await try_generate_segment(seg_text, precision=p)]
                            except Exception as e:
                                if forced_precision:
                                    # User forced precision; don't auto split unless it's OOM and text is big.
                                    if self._is_oom_error(e) and depth < 6 and len(seg_text) > 80:
                                        parts = self._split_chunk_in_half(seg_text)
                                        out: List[str] = []
                                        for part in parts:
                                            out.extend(await generate_with_backoff(part, depth=depth + 1))
                                        return out
                                    raise

                                # 2) Retry with fp16 when it looks like OOM.
                                if self._is_oom_error(e):
                                    try:
                                        return [await try_generate_segment(seg_text, precision="fp16")]
                                    except Exception as e2:
                                        # 3) If still OOM, split and recurse.
                                        if self._is_oom_error(e2) and depth < 8 and len(seg_text) > 60:
                                            parts = self._split_chunk_in_half(seg_text)
                                            out: List[str] = []
                                            for part in parts:
                                                out.extend(await generate_with_backoff(part, depth=depth + 1))
                                            return out
                                        raise e2

                                raise

                        for chunk in chunks:
                            seg_paths = await generate_with_backoff(chunk, depth=0)
                            segment_paths.extend(seg_paths)

                        final_path = out_path
                        audio_format = "mp3"
                        if is_ffmpeg_available():
                            if len(segment_paths) == 1:
                                ffmpeg_args = [
                                    "ffmpeg",
                                    "-y",
                                    "-i",
                                    segment_paths[0],
                                    "-vn",
                                    "-c:a",
                                    "libmp3lame",
                                    "-b:a",
                                    "192k",
                                    final_path,
                                ]
                                code, _, err = await _run_subprocess(ffmpeg_args)
                                if code != 0 or (not os.path.exists(final_path)) or os.path.getsize(final_path) == 0:
                                    last = (err.splitlines()[-1] if err else "").strip()
                                    raise RuntimeError(f"ffmpeg mp3 transcode failed: {last or 'unknown error'}")
                            else:
                                list_path = os.path.join(tmp_dir, "concat_list.txt")
                                with open(list_path, "w", encoding="utf-8") as f:
                                    for p in segment_paths:
                                        f.write(f"file '{str(Path(p).resolve())}'\n")
                                ffmpeg_args = [
                                    "ffmpeg",
                                    "-y",
                                    "-f",
                                    "concat",
                                    "-safe",
                                    "0",
                                    "-i",
                                    list_path,
                                    "-vn",
                                    "-c:a",
                                    "libmp3lame",
                                    "-b:a",
                                    "192k",
                                    final_path,
                                ]
                                code, _, err = await _run_subprocess(ffmpeg_args)
                                if code != 0 or (not os.path.exists(final_path)) or os.path.getsize(final_path) == 0:
                                    last = (err.splitlines()[-1] if err else "").strip()
                                    raise RuntimeError(f"ffmpeg audio concat failed: {last or 'unknown error'}")
                        else:
                            if len(segment_paths) != 1:
                                raise RuntimeError("ffmpeg not available; cannot merge multi-part ComfyUI TTS output")
                            ext = segment_ext or ".wav"
                            final_path = os.path.join(base_dir, f"slide_{script.slide_index}_{content_hash[:12]}{ext}")
                            audio_format = ext.lstrip(".")
                            shutil.copyfile(segment_paths[0], final_path)

                        duration_ms = await ffprobe_duration_ms(final_path)
                        cues_json = None
                        try:
                            if duration_ms is not None:
                                cues_json = await build_cues_json_for_audio(
                                    text=text, audio_path=final_path, duration_ms=int(duration_ms)
                                )
                        except Exception:
                            cues_json = None

                        await audio_repo.upsert_audio(
                            project_id=project_id,
                            slide_index=script.slide_index,
                            language=language,
                            provider=provider,
                            voice=voice_id,
                            rate=rate,
                            audio_format=audio_format,
                            content_hash=content_hash,
                            file_path=final_path,
                            duration_ms=duration_ms,
                            cues_json=cues_json,
                        )

                        outputs.append(
                            NarrationAudioResult(
                                slide_index=script.slide_index,
                                language=language,
                                voice=voice_id,
                                rate=rate,
                                audio_path=final_path,
                                duration_ms=duration_ms,
                                cached=False,
                            )
                        )
                    finally:
                        try:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                        except Exception:
                            pass

            return outputs
        finally:
            audio_repo.close()
