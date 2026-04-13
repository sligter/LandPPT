from landppt.services.subtitle_service import (
    _select_boundary_sequence,
    build_slide_cues_snapped,
    build_srt_for_slides,
)


def test_build_srt_for_slides_basic():
    srt = build_srt_for_slides(
        slides=[
            ("第一句。第二句！", 3000),
            ("第三句，比较长一些需要分段展示。", 5000),
        ],
        max_chars_per_line=10,
    )
    assert "00:00:00,000 -->" in srt
    # Ensure single-line cues (no blank text lines between timestamps and text).
    for block in srt.strip().split("\n\n"):
        lines = block.splitlines()
        assert len(lines) == 3
        assert "-->" in lines[1]
        assert lines[2].strip()


def test_build_srt_for_slides_ends_with_newline():
    srt = build_srt_for_slides(slides=[("Hello world.", 1000)])
    assert srt.endswith("\n")


def test_select_boundary_sequence_prefers_global_best_fit():
    boundaries = _select_boundary_sequence(
        desired_boundaries_ms=[1000, 2000],
        candidate_boundaries_ms=[400, 1400, 1600, 2800],
        start_ms=0,
        end_ms=4000,
        min_gap_ms=250,
        tolerance_ms=900,
    )
    assert boundaries == [400, 1600]


def test_build_slide_cues_snapped_uses_internal_pause_boundary():
    cues = build_slide_cues_snapped(
        slide_text="第一句。第二句。",
        slide_start_ms=180,
        slide_duration_ms=2720,
        boundary_mids_ms=[1220],
        max_chars_per_line=36,
        snap_tolerance_ms=900,
    )
    assert len(cues) == 2
    assert cues[0].start_ms == 180
    assert cues[0].end_ms == 1400
    assert cues[1].start_ms == 1400
    assert cues[1].end_ms == 2900
