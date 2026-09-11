import base64
import io
import zipfile
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_layered_background_smoke.html"
EXPECTED_PATCH_VERSION = "2026-09-11-svg-native-v1"


def _read_pptx(result):
    pptx_bytes = base64.b64decode(result["pptxBase64"])
    return zipfile.ZipFile(io.BytesIO(pptx_bytes))


def test_dom_to_pptx_preserves_layered_root_background():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local dependency install
        pytest.skip(f"Playwright is not installed: {exc}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # pragma: no cover - depends on local browser install
            pytest.skip(f"Chromium is not available for Playwright: {exc}")

        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page_errors = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        try:
            page.goto(FIXTURE_PATH.resolve().as_uri(), wait_until="load")
            page.wait_for_function("window.domToPptx && window.runLayeredBackgroundPptxSmokeTest")
            result = page.evaluate("() => window.runLayeredBackgroundPptxSmokeTest()")
        finally:
            browser.close()

    assert not page_errors
    assert result["slideCount"] == 1
    assert result["patchVersion"] == EXPECTED_PATCH_VERSION
    assert result["blobSize"] > 10_000

    with _read_pptx(result) as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        media_entries = [name for name in archive.namelist() if name.startswith("ppt/media/")]
        media_payloads = [archive.read(name) for name in media_entries]

    assert "F2F2F2" in slide_xml
    assert "<p:pic>" in slide_xml
    assert any(payload.startswith(b"\x89PNG\r\n\x1a\n") for payload in media_payloads)
