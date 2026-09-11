import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "src/landppt/web/static/js/dom-to-pptx.bundle.js"
LOADER_PATHS = [
    ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.exportRender.js",
    ROOT / "src/landppt/web/static/js/pages/template/global_master/globalMasterTemplates.exportHelpers.js",
]
PROJECT_EDITOR_TEMPLATE_PATH = ROOT / "src/landppt/web/templates/pages/project/project_slides_editor.html"


def _extract_single(pattern: str, text: str) -> str:
    matches = re.findall(pattern, text)
    assert len(matches) == 1
    return matches[0]


def test_dom_to_pptx_loader_versions_match_bundle_patch_version():
    bundle_text = BUNDLE_PATH.read_text(encoding="utf-8")
    patch_version = _extract_single(
        r"LANDPPT_DOM_TO_PPTX_PATCH_VERSION\s*=\s*'([^']+)'",
        bundle_text,
    )
    cache_version = patch_version.replace("-", "", 2)

    for loader_path in LOADER_PATHS:
        loader_text = loader_path.read_text(encoding="utf-8")
        assert _extract_single(r"DOM_TO_PPTX_EXPECTED_PATCH_VERSION\s*=\s*'([^']+)'", loader_text) == patch_version
        assert _extract_single(r"DOM_TO_PPTX_BUNDLE_VERSION\s*=\s*'([^']+)'", loader_text) == cache_version

    master_entry = LOADER_PATHS[1].with_name("globalMasterTemplates.js").read_text(encoding="utf-8")
    assert f"globalMasterTemplates.exportHelpers.js?v={cache_version}" in master_entry


def test_project_editor_export_render_cache_bust_matches_bundle_version():
    bundle_text = BUNDLE_PATH.read_text(encoding="utf-8")
    patch_version = _extract_single(
        r"LANDPPT_DOM_TO_PPTX_PATCH_VERSION\s*=\s*'([^']+)'",
        bundle_text,
    )
    cache_version = patch_version.replace("-", "", 2)
    template_text = PROJECT_EDITOR_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert f"dom-to-pptx.bundle.js?v={cache_version}" in template_text
    assert f"projectSlidesEditor.exportRender.js?v={cache_version}" in template_text
