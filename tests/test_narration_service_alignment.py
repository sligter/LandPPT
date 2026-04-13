import os
import json

import pytest

os.environ["DEBUG"] = "false"


def test_parse_silence_spans_and_speech_window():
    from landppt.services.narration_service import _derive_speech_window_ms, _parse_silence_spans_ms

    stderr = """
    [silencedetect @ 0x1] silence_start: 0
    [silencedetect @ 0x1] silence_end: 0.18 | silence_duration: 0.18
    [silencedetect @ 0x1] silence_start: 1.30
    [silencedetect @ 0x1] silence_end: 1.50 | silence_duration: 0.20
    [silencedetect @ 0x1] silence_start: 2.90
    [silencedetect @ 0x1] silence_end: 3.20 | silence_duration: 0.30
    """
    spans = _parse_silence_spans_ms(stderr)
    assert spans == [(0, 180), (1300, 1500), (2900, 3200)]
    assert _derive_speech_window_ms(3200, spans) == (180, 2900)


def test_extract_cue_payload_version_defaults_for_legacy_payload():
    from landppt.services.narration_service import _extract_cue_payload_version

    assert _extract_cue_payload_version(None) == 0
    assert _extract_cue_payload_version('[{"start_ms":0,"end_ms":1000,"text":"legacy"}]') == 1
    assert _extract_cue_payload_version('[{"__lp_cue_version":2},{"start_ms":10,"end_ms":20,"text":"ok"}]') == 2


@pytest.mark.asyncio
async def test_build_cues_json_for_audio_trims_edge_silence(monkeypatch):
    from landppt.services.narration_service import build_cues_json_for_audio

    async def fake_detect_silence_spans_ms(_audio_path: str):
        return [(0, 180), (1300, 1500), (2900, 3200)]

    monkeypatch.setattr(
        "landppt.services.narration_service.detect_silence_spans_ms",
        fake_detect_silence_spans_ms,
    )

    raw = await build_cues_json_for_audio(
        text="第一句。第二句。",
        audio_path="dummy.mp3",
        duration_ms=3200,
    )
    payload = json.loads(raw)
    meta = payload[0]
    cues = [item for item in payload if item.get("text")]

    assert meta["__lp_cue_version"] == 2
    assert meta["speech_start_ms"] == 180
    assert meta["speech_end_ms"] == 2900
    assert len(cues) == 2
    assert cues[0]["start_ms"] == 180
    assert cues[0]["end_ms"] == 1400
    assert cues[1]["start_ms"] == 1400
    assert cues[1]["end_ms"] == 2900
