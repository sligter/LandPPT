import copy


def test_build_qwen3_td_tts_workflow_patches_nodes():
    from landppt.services.comfyui_tts_client import load_workflow_template, build_qwen3_td_tts_workflow

    template = load_workflow_template("tests/Qwen3-TD-TTS.json")
    original = copy.deepcopy(template)

    wf = build_qwen3_td_tts_workflow(
        template,
        text="你好，世界",
        ref_audio_filename="ref.wav",
        language="zh",
        ref_text="",
    )

    assert wf["19"]["inputs"]["audio"] == "ref.wav"
    assert wf["31"]["inputs"]["text"] == "你好，世界"
    assert wf["31"]["inputs"]["language"] == "Chinese"
    assert wf["31"]["inputs"]["ref_text"] == ""

    # Ensure the template is not mutated.
    assert template == original


def test_build_qwen3_td_tts_workflow_language_english():
    from landppt.services.comfyui_tts_client import load_workflow_template, build_qwen3_td_tts_workflow

    template = load_workflow_template("tests/Qwen3-TD-TTS.json")
    wf = build_qwen3_td_tts_workflow(
        template,
        text="Hello world",
        ref_audio_filename="ref.flac",
        language="en",
        ref_text="",
    )

    assert wf["31"]["inputs"]["language"] == "English"

