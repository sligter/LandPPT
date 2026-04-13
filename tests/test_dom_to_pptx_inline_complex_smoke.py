from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dom_to_pptx_inline_complex_smoke.html"
EXPECTED_PATCH_VERSION = "2026-04-05-font-resolve-v3"


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
