from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from landppt.services import saved_narration


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["none", "script", "stale_audio", "file"])
async def test_load_saved_narration_requires_audio_for_the_current_script(
    monkeypatch, tmp_path, missing,
):
    path = tmp_path / "narration.mp3"
    if missing != "file":
        path.write_bytes(b"existing narration")
    script = SimpleNamespace(slide_index=0, script_content="现有讲稿", updated_at=10.)
    audio = SimpleNamespace(
        file_path=str(path), voice="voice", rate="+0%", duration_ms=1000,
        updated_at=9. if missing == "stale_audio" else 11.,
    )
    scripts = Mock(get_current_speech_scripts_by_project=AsyncMock(
        return_value=[] if missing == "script" else [script]
    ))
    audios = Mock(get_latest_for_slide=AsyncMock(return_value=audio))
    monkeypatch.setattr(saved_narration, "SpeechScriptRepository", lambda: scripts)
    monkeypatch.setattr(saved_narration, "NarrationAudioRepository", lambda: audios)

    if missing == "none":
        (result,) = await saved_narration.load_saved_narration("project", "zh", 1)
        assert result.audio_path == str(path) and result.cached
    else:
        with pytest.raises(RuntimeError, match="第 1 页"):
            await saved_narration.load_saved_narration("project", "zh", 1)
    scripts.close.assert_called_once()
    audios.close.assert_called_once()
