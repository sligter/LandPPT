import base64
import io
import zipfile
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_svg_css_vars_smoke.html"
EXPECTED_PATCH_VERSION = "2026-09-11-svg-native-v1"


def _read_pptx(result):
    pptx_bytes = base64.b64decode(result["pptxBase64"])
    return zipfile.ZipFile(io.BytesIO(pptx_bytes))


def _count_blue_pixels(image):
    pixels = image.convert("RGBA").getdata()
    count = 0
    for r, g, b, a in pixels:
        if a > 80 and 20 <= r <= 80 and 60 <= g <= 120 and 130 <= b <= 220:
            count += 1
    return count


def test_dom_to_pptx_renders_svg_css_variables():
    try:
        from PIL import Image
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local dependency install
        pytest.skip(f"Browser/image dependencies are not installed: {exc}")

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
            page.wait_for_function("window.domToPptx && window.runSvgCssVarsPptxSmokeTest")
            result = page.evaluate("() => window.runSvgCssVarsPptxSmokeTest()")
        finally:
            browser.close()

    assert not page_errors
    assert result["slideCount"] == 1
    assert result["patchVersion"] == EXPECTED_PATCH_VERSION
    assert result["blobSize"] > 10_000

    chart_candidates = []
    with _read_pptx(result) as archive:
        for name in archive.namelist():
            if not name.startswith("ppt/media/") or not name.lower().endswith(".png"):
                continue
            image = Image.open(io.BytesIO(archive.read(name)))
            if image.width >= 400 and image.height >= 180:
                chart_candidates.append((name, image.size, _count_blue_pixels(image)))

    assert chart_candidates
    assert max(blue_pixels for _, _, blue_pixels in chart_candidates) > 250
