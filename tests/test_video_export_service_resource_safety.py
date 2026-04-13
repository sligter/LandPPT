import os
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_run_subprocess_timeout_returns_124():
    from landppt.services.video_export_service import _run_subprocess

    code, out, err = await _run_subprocess(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        timeout_ms=50,
    )
    assert code == 124
    assert out == ""
    assert "timed out" in (err or "").lower()


def test_calculate_safe_parallelism_respects_worker_slice(monkeypatch):
    from landppt.services.video_export_service import _calculate_safe_parallelism

    monkeypatch.setenv("LANDPPT_AVAILABLE_MEMORY_MB", "16384")
    monkeypatch.setenv("LANDPPT_NARRATION_VIDEO_PARALLELISM", "8")

    monkeypatch.setenv("WORKERS", "1")
    p1 = _calculate_safe_parallelism(width=64, height=64, fps=30)

    monkeypatch.setenv("WORKERS", "4")
    p4 = _calculate_safe_parallelism(width=64, height=64, fps=30)

    assert p1 >= p4
    assert p4 >= 1


def test_calculate_safe_screenshot_parallelism_respects_worker_slice(monkeypatch):
    import os

    from landppt.services.video_export_service import _calculate_safe_screenshot_parallelism

    monkeypatch.setenv("LANDPPT_AVAILABLE_MEMORY_MB", "16384")
    monkeypatch.setenv("LANDPPT_NARRATION_SCREENSHOT_PARALLELISM", "12")
    monkeypatch.setattr(os, "cpu_count", lambda: 32)

    monkeypatch.setenv("WORKERS", "1")
    p1 = _calculate_safe_screenshot_parallelism(width=1920, height=1080)

    monkeypatch.setenv("WORKERS", "4")
    p4 = _calculate_safe_screenshot_parallelism(width=1920, height=1080)

    assert p1 >= p4
    assert p4 >= 1


def test_normalize_audio_cache_path_matches_relative_and_absolute(tmp_path, monkeypatch):
    from landppt.services.video_export_service import _normalize_audio_cache_path

    audio = tmp_path / "slide_0.mp3"
    audio.write_bytes(b"ok")
    monkeypatch.chdir(tmp_path)

    assert _normalize_audio_cache_path("slide_0.mp3") == _normalize_audio_cache_path(str(audio.resolve()))


def test_build_cues_by_audio_path_keeps_distinct_audio_versions():
    from landppt.services.video_export_service import _build_cues_by_audio_path, _normalize_audio_cache_path

    old_path = "uploads/narration/project/zh/slide_0_old.mp3"
    new_path = "uploads/narration/project/zh/slide_0_new.mp3"

    rows = [
        SimpleNamespace(slide_index=0, file_path=old_path, cues_json='[{"text":"old"}]'),
        SimpleNamespace(slide_index=0, file_path=new_path, cues_json='[{"text":"new"}]'),
    ]

    mapped = _build_cues_by_audio_path(rows)
    assert mapped[_normalize_audio_cache_path(old_path)] == '[{"text":"old"}]'
    assert mapped[_normalize_audio_cache_path(new_path)] == '[{"text":"new"}]'


def test_build_subtitle_filter_pins_original_size():
    from landppt.services.video_export_service import SubtitleStyle, _build_subtitle_filter

    vf = _build_subtitle_filter(
        subtitle_path=r"C:\temp\subtitles.srt",
        width=1920,
        height=1080,
        style=SubtitleStyle(font_size=14, margin_v=26),
    )

    assert "subtitles=subtitles.srt" in vf
    assert "original_size=1920x1080" in vf
    assert "FontSize=14" in vf
    assert "MarginV=26" in vf


def test_resolve_subtitle_style_compacts_live_defaults_only():
    from landppt.services.video_export_service import _resolve_subtitle_style

    live_default = _resolve_subtitle_style(None, height=1080, render_mode="live")
    static_default = _resolve_subtitle_style(None, height=1080, render_mode="static")
    live_explicit = _resolve_subtitle_style(
        {"font_size": 24, "margin_v": 40},
        height=1080,
        render_mode="live",
    )

    assert live_default.font_size == 14
    assert live_default.margin_v == 26
    assert static_default.font_size == 16
    assert static_default.margin_v == 30
    assert live_explicit.font_size == 24
    assert live_explicit.margin_v == 40


def test_build_live_single_slide_html_waits_for_stable_frame():
    from landppt.services.video_export_service import NarrationVideoExportService

    html = NarrationVideoExportService()._build_live_single_slide_html("<div>slide</div>", width=1920, height=1080)

    assert "const LOAD_TIMEOUT_MS = 15000;" in html
    assert "const STABLE_CHECKS = 3;" in html
    assert "function collectCssImageUrls(doc)" in html
    assert "await waitForCssImages(doc);" in html
    assert "img.loading = 'eager';" in html
    assert "await waitForFrameStable(doc);" in html
    assert "transition: opacity" not in html


def test_prepare_slide_html_for_video_export_rewrites_image_resources(monkeypatch):
    from landppt.services import video_export_service as ves
    from landppt.services.video_export_service import NarrationVideoExportService

    monkeypatch.setattr(
        ves,
        "resolve_background_export_base_url",
        lambda: "https://slides.example.com",
    )

    prepared = NarrationVideoExportService()._prepare_slide_html_for_video_export(
        """
        <div style="background-image:url('/temp/rendered/hero.png')">
          <img src="/static/images/landppt-logo.png" alt="logo">
        </div>
        """,
        title="Slide 1",
    )

    assert '<base href="https://slides.example.com/">' in prepared
    assert 'src="https://slides.example.com/static/images/landppt-logo.png"' in prepared
    assert "https://slides.example.com/temp/rendered/hero.png" in prepared


def test_prepare_slide_html_for_video_export_rewrites_absolute_localhost_image_urls(monkeypatch):
    from landppt.services import video_export_service as ves
    from landppt.services.video_export_service import NarrationVideoExportService

    monkeypatch.setattr(
        ves,
        "resolve_background_export_base_url",
        lambda: "http://127.0.0.1:8000",
    )

    prepared = NarrationVideoExportService()._prepare_slide_html_for_video_export(
        """
        <img src="http://localhost:8001/api/image/view/u1_demo?width=1261px&height=559px" alt="demo">
        """,
        title="Slide 3",
    )

    assert (
        'src="http://127.0.0.1:8000/api/image/view/u1_demo?width=1261px&height=559px"' in prepared
    )


def test_resolve_background_export_base_url_prefers_internal_port_for_localhost(monkeypatch):
    from landppt.services.export_infra import file_export_html_preparer as preparer

    monkeypatch.delenv("LANDPPT_BACKGROUND_EXPORT_BASE_URL", raising=False)
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setattr(preparer, "get_current_base_url", lambda: "http://localhost:8001")

    assert preparer.resolve_background_export_base_url() == "http://127.0.0.1:8000"


@pytest.mark.asyncio
async def test_static_export_uses_fixed_stage_wrapper_without_content_crop(tmp_path, monkeypatch):
    from landppt.services import video_export_service as ves

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_paths = []
    for idx in range(2):
        audio_path = audio_dir / f"slide_{idx}.mp3"
        audio_path.write_bytes(b"fake-audio")
        audio_paths.append(audio_path)

    class FakeNarrationService:
        def __init__(self, user_id=None):
            self.user_id = user_id

        async def generate_project_slide_audios(self, project_id, language, uploads_dir):
            return [
                SimpleNamespace(slide_index=idx, audio_path=str(path), duration_ms=1200)
                for idx, path in enumerate(audio_paths)
            ]

    class FakeSpeechScriptRepository:
        async def get_current_speech_scripts_by_project(self, project_id, language="zh"):
            return []

        def close(self):
            return None

    class FakeNarrationAudioRepository:
        async def list_by_project(self, project_id, language="zh"):
            return []

        def close(self):
            return None

    class FakeConverter:
        def __init__(self):
            self.calls = []

        async def screenshot_html(self, html_file_path, screenshot_path, **kwargs):
            self.calls.append(
                {
                    "html_file_path": html_file_path,
                    "screenshot_path": screenshot_path,
                    "kwargs": kwargs,
                    "html": Path(html_file_path).read_text(encoding="utf-8"),
                }
            )
            Path(screenshot_path).write_bytes(b"png")
            return True

    fake_converter = FakeConverter()

    async def fake_run_subprocess(args, *, cwd=None, timeout_ms=None):
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"ok")
        return 0, "", ""

    fake_narration_service_module = ModuleType("landppt.services.narration_service")
    fake_narration_service_module.NarrationService = FakeNarrationService
    fake_speech_repo_module = ModuleType("landppt.services.speech_script_repository")
    fake_speech_repo_module.SpeechScriptRepository = FakeSpeechScriptRepository
    fake_audio_repo_module = ModuleType("landppt.services.narration_audio_repository")
    fake_audio_repo_module.NarrationAudioRepository = FakeNarrationAudioRepository

    monkeypatch.setitem(sys.modules, "landppt.services.narration_service", fake_narration_service_module)
    monkeypatch.setitem(sys.modules, "landppt.services.speech_script_repository", fake_speech_repo_module)
    monkeypatch.setitem(sys.modules, "landppt.services.narration_audio_repository", fake_audio_repo_module)
    monkeypatch.setattr(ves, "get_pdf_converter", lambda: fake_converter)
    monkeypatch.setattr(ves, "_run_subprocess", fake_run_subprocess)

    project = SimpleNamespace(
        project_id="proj-static",
        user_id="user-1",
        topic="Static Export",
        slides_data=[
            {"html_content": "<div style='width:1280px;height:720px;background:#123;color:#fff;'>Slide 1</div>"},
            {"html_content": "<div style='width:1280px;height:720px;background:#456;color:#fff;'>Slide 2</div>"},
        ],
    )

    result = await ves.NarrationVideoExportService()._export_project_video_static(
        project=project,
        language="zh",
        fps=30,
        width=1920,
        height=1080,
        embed_subtitles=True,
        subtitle_style=None,
        uploads_dir=str(tmp_path / "uploads"),
    )

    assert result["success"] is True
    assert len(fake_converter.calls) == 2
    assert all(call["kwargs"]["crop_to_content"] is False for call in fake_converter.calls)
    assert all("window.__lpSlideReady = false;" in call["html"] for call in fake_converter.calls)
    assert all("<iframe id=\"frame\" title=\"slide\"></iframe>" in call["html"] for call in fake_converter.calls)
