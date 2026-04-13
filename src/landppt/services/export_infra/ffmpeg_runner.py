"""
ffmpeg/ffprobe subprocess helpers used by export services.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_FFMPEG_ENCODERS_CACHE: Optional[str] = None


async def run_subprocess(
    args: list[str],
    *,
    cwd: Optional[str] = None,
    timeout_ms: Optional[int] = None,
) -> Tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else None
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        return (
            proc.returncode,
            out_b.decode("utf-8", errors="ignore"),
            err_b.decode("utf-8", errors="ignore"),
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
        return 124, "", f"Process timed out after {timeout_s:.1f}s"


def summarize_subprocess_stderr(err: str, *, max_lines: int = 25) -> str:
    lines = [line.strip() for line in (err or "").splitlines() if line.strip()]
    if not lines:
        return ""

    import re

    patterns = re.compile(
        r"(error|failed|invalid|cannot|no such|not found|permission|unknown|unsupported|device|driver|cuda|vaapi|qsv|nvenc)",
        re.IGNORECASE,
    )
    important = [line for line in lines if patterns.search(line)]
    chosen = important[-max_lines:] if important else lines[-max_lines:]
    return " | ".join(chosen)


async def ffprobe_duration_ms(audio_path: str) -> Optional[int]:
    if not shutil.which("ffprobe"):
        return None

    code, out, err = await run_subprocess(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
    )
    if code != 0:
        last = (err.splitlines()[-1] if err else "").strip()
        logger.warning("ffprobe failed for %s: %s", audio_path, last or "unknown")
        return None
    try:
        return max(0, int(float((out or "").strip()) * 1000))
    except Exception:
        return None


async def get_ffmpeg_encoders_text() -> str:
    global _FFMPEG_ENCODERS_CACHE
    if _FFMPEG_ENCODERS_CACHE is not None:
        return _FFMPEG_ENCODERS_CACHE
    code, out, err = await run_subprocess(["ffmpeg", "-hide_banner", "-encoders"])
    _FFMPEG_ENCODERS_CACHE = (out or "") + "\n" + (err or "")
    return _FFMPEG_ENCODERS_CACHE

