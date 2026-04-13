from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUICK_EDIT_JS = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.quickEdit.js"
QUICK_EDIT_STYLING_JS = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.quickEditStyling.js"
QUICK_AI_JS = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.quickAi.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_direct_text_save_uses_clean_quick_edit_html():
    text = _read(QUICK_EDIT_JS)

    assert "function getCleanSlideHtmlForQuickEdit(options = {}) {" in text
    assert "const updatedHtml = getCleanSlideHtmlForQuickEdit({" in text
    assert "stripQuickAiIds: true" in text


def test_other_quick_edit_flows_reuse_clean_html_helper():
    styling_text = _read(QUICK_EDIT_STYLING_JS)
    quick_ai_text = _read(QUICK_AI_JS)

    assert "const updatedHtml = getCleanSlideHtmlForQuickEdit({" in styling_text
    assert "stripQuickAiIds: true" in styling_text
    assert "return getCleanSlideHtmlForQuickEdit({ slideFrame });" in quick_ai_text
