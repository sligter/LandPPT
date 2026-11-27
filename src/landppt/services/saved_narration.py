"""Load the existing soundtrack for a render that must not synthesize speech."""

from pathlib import Path

from .narration_audio_repository import NarrationAudioRepository
from .narration_service import NarrationAudioResult
from .speech_script_repository import SpeechScriptRepository


async def load_saved_narration(
    project_id: str, language: str, slide_count: int
) -> list[NarrationAudioResult]:
    speech_repo = SpeechScriptRepository()
    try:
        scripts = await speech_repo.get_current_speech_scripts_by_project(project_id, language)
        current_scripts = {script.slide_index: script for script in scripts}
        audio_repo = NarrationAudioRepository()
        try:
            audios = []
            for index in range(slide_count):
                script = current_scripts.get(index)
                row = await audio_repo.get_latest_for_slide(
                    project_id=project_id, slide_index=index, language=language
                )
                if not script or not script.script_content.strip():
                    raise RuntimeError(f"仅渲染成片缺少第 {index + 1} 页的讲稿")
                if not row or not row.file_path or row.updated_at < script.updated_at:
                    raise RuntimeError(f"仅渲染成片缺少第 {index + 1} 页对应当前讲稿的配音")
                path = Path(row.file_path)
                if not path.is_file() or not path.stat().st_size:
                    raise RuntimeError(f"仅渲染成片无法读取第 {index + 1} 页的配音")
                audios.append(NarrationAudioResult(
                    slide_index=index, language=language, voice=row.voice, rate=row.rate,
                    audio_path=row.file_path, duration_ms=row.duration_ms, cached=True,
                ))
            return audios
        finally:
            audio_repo.close()
    finally:
        speech_repo.close()
