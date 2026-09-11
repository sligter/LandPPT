import base64
import io
import re
import zipfile
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_inline_complex_smoke.html"
EXPECTED_PATCH_VERSION = "2026-09-11-svg-native-v1"


def _read_pptx_entry(result, entry_name):
    pptx_bytes = base64.b64decode(result["pptxBase64"])
    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as archive:
        return archive.read(entry_name).decode("utf-8")


def test_dom_to_pptx_inline_complex_smoke():
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
            page.wait_for_function("window.domToPptx && window.runComplexInlinePptxSmokeTest")
            result = page.evaluate("() => window.runComplexInlinePptxSmokeTest()")
        finally:
            browser.close()

    assert not page_errors
    assert result["slideCount"] == 2
    assert result["patchVersion"] == EXPECTED_PATCH_VERSION
    assert result["blobSize"] > 10_000

    slide_xml = _read_pptx_entry(result, "ppt/slides/slide1.xml")
    line_spacing_values = [
        int(value)
        for value in re.findall(r"<a:lnSpc><a:spcPts val=\"(\d+)\"/></a:lnSpc>", slide_xml)
    ]
    assert line_spacing_values
    assert max(line_spacing_values) >= 1400
    assert 'anchor="t"' in slide_xml
    assert "<a:highlight>" in slide_xml
