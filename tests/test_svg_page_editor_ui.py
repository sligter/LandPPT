"""SVG 页面编辑器回归：面板接线、字段可见性、快捷键、缺陷提示与保存标记。

浏览器部分用真实的编辑器脚本 + 真实的服务端 SVG 校验器（路由拦截，无 AI 调用）；
浏览器依赖缺失时按仓库既有约定跳过。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from landppt.services.slide.svg_page.constants import ALLOWED_ATTRIBUTES
from landppt.services.slide.svg_page.shell import build_slide_html

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "src" / "landppt" / "web" / "static"
EDITOR_JS = STATIC / "js" / "pages" / "project" / "slides_editor" / "projectSlidesEditor.svgEdit.js"
EDITOR_CSS = STATIC / "css" / "pages" / "project" / "slides_editor" / "projectSlidesEditor.svgEdit.css"
TEMPLATE = REPO / "src" / "landppt" / "web" / "templates" / "pages" / "project" / "project_slides_editor.html"

# 编辑器里以变量形式写入的属性名（svgSetAttribute(node, name, ...)）
DYNAMIC_ATTRIBUTES = {
    "x", "y", "width", "height", "r", "rx", "ry", "x1", "y1", "x2", "y2",
    "fill", "stroke", "stroke-width", "font-size", "font-weight", "text-anchor",
    "opacity", "transform", "id", "color", "data-box-w",
}

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
<defs><linearGradient id="gradient"><stop offset="0" stop-color="#334155"/><stop offset="1" stop-color="#0f172a"/></linearGradient></defs>
<g data-role="background"><rect width="1280" height="720" fill="#f8fafc"/></g>
<g data-role="title"><text id="heading" x="80" y="105" fill="#0f172a" font-size="42" font-family="Arial" data-box-w="1000">SVG 页面编辑与导出</text></g>
<g data-role="main"><rect id="card" x="80" y="170" width="530" height="350" rx="24" fill="url(#gradient)"/>
<text id="body" x="120" y="250" font-size="28" font-family="Arial" fill="#ffffff"><tspan x="120">Editable text 2026</tspan><tspan x="120" dy="48">中文内容保持可编辑</tspan></text>
<g transform="translate(700 220)"><rect id="bar" x="0" y="0" width="130" height="260" fill="#38bdf8"/><circle cx="230" cy="60" r="50" fill="#fb7185"/></g>
<line x1="700" y1="530" x2="970" y2="490" stroke="#0f172a" stroke-width="4"/></g></svg>"""


# HTML 侧（图层列表按钮、对话框）专用的属性，不属于 SVG 清洗范围
HTML_ONLY_ATTRIBUTES = {"role"}


def test_editor_only_writes_whitelisted_attributes():
    """编辑器写入的属性必须在清洗器白名单内，否则保存时会被静默剥离。"""
    source = EDITOR_JS.read_text(encoding="utf-8")
    literals = set(re.findall(r"setAttribute\(\s*'([^'\"]+)'", source))
    assert literals, "没有解析到任何 setAttribute 调用"
    for name in sorted(literals | DYNAMIC_ATTRIBUTES):
        if name in HTML_ONLY_ATTRIBUTES:
            continue
        assert name.startswith(("data-", "aria-")) or name in ALLOWED_ATTRIBUTES, name


def test_template_loads_editor_stylesheet_and_script():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "projectSlidesEditor.svgEdit.css" in template
    assert "projectSlidesEditor.svgEdit.js" in template
    assert EDITOR_CSS.exists() and EDITOR_JS.exists()


@pytest.fixture
def browser_page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runner:
        try:
            browser = runner.chromium.launch()
        except Exception as exc:  # pragma: no cover - depends on local browser install
            pytest.skip(f"Chromium is not available for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1440, "height": 990})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        posts: list[dict] = []
        baseline = build_slide_html(SVG)

        def serve(route):
            path = urlparse(route.request.url).path
            if path == "/api/ai/slide-edit-agent/apply":
                body = route.request.post_data_json
                assert body["expectedBaseHash"] == hashlib.sha256(baseline.strip().encode()).hexdigest()
                posts.append(body)
                route.fulfill(json={"success": True, "htmlContent": body["htmlContent"],
                    "slideData": {"render_mode": "svg", "html_content": body["htmlContent"], "page_number": 1}})
            elif path.startswith("/static/js/"):
                route.fulfill(body=(STATIC / "js" / path.removeprefix("/static/js/")).read_bytes(),
                    content_type="text/javascript; charset=utf-8")
            else:
                route.fulfill(body="<html><head><meta charset='utf-8'></head><body>"
                    "<iframe id='slideFrame'></iframe><textarea id='codeEditor'></textarea></body></html>",
                    content_type="text/html; charset=utf-8")

        page.route("**/*", serve)
        page.goto("http://localhost/svg-editor-ui")
        page.evaluate("""html => {
            window.slidesData = [{html_content: html, render_mode: 'svg', page_number: 1}];
            window.currentSlideIndex = 0;
            window.landpptEditorConfig = {projectId: 'ui-fixture'};
            window.setSafeIframeContent = () => {};
            window.showNotification = () => {};
        }""", baseline)
        page.add_script_tag(path=str(EDITOR_JS))
        page.add_style_tag(content=EDITOR_CSS.read_text(encoding="utf-8"))
        yield page, posts, errors
        browser.close()


def open_editor(page):
    page.evaluate("openSvgPageEditor()")
    page.wait_for_function("document.querySelectorAll('#svg-page-editor iframe').length === 1")
    return page.locator("#svg-page-editor")


def test_editor_layout_and_panels(browser_page):
    page, _, errors = browser_page
    editor = open_editor(page)
    assert editor.is_visible()
    box = editor.bounding_box()
    assert 0 < box["x"] < 200 and box["x"] + box["width"] <= 1440
    assert box["y"] + box["height"] <= 990
    stage = editor.locator("[data-stage]").bounding_box()
    panel = editor.locator(".svg-editor__panel").bounding_box()
    assert panel["x"] >= stage["x"] + stage["width"] - 2, "属性面板应在画布右侧"
    assert 300 <= panel["width"] <= 372
    # 适应窗口：画布完整落在可视区域内，且面板不需要纵向滚动
    paper = editor.locator("[data-paper]").bounding_box()
    assert paper["width"] <= stage["width"] and paper["height"] <= stage["height"]
    assert editor.locator(".svg-editor__panel").evaluate("el => el.scrollHeight <= el.clientHeight + 2")
    assert editor.locator("[data-layers] .svg-layer").count() >= 8
    assert editor.locator("[data-zoom-label]").text_content() == "适应"

    # 展开属性面板后，工具栏与面板内不应有横向/纵向溢出
    page.frame_locator("#svg-page-editor iframe").locator("#heading").click()
    assert editor.locator("[data-inspector]").is_visible()
    overflow = page.evaluate("""() => {
        const dialog = document.querySelector('#svg-page-editor');
        const box = dialog.getBoundingClientRect();
        const bad = [];
        dialog.querySelectorAll('.svg-editor__topbar *, .svg-editor__panel *').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width && (rect.right > box.right + 1 || rect.left < box.left - 1)) {
                bad.push(`${el.className}|${el.textContent.slice(0, 12)}`);
            }
        });
        const bars = ['.svg-editor__topbar', '.svg-editor__statusbar', '.svg-editor__panel'];
        bars.forEach(selector => {
            const el = dialog.querySelector(selector);
            if (el.scrollWidth - el.clientWidth > 1) bad.push(`${selector}:scrollWidth`);
        });
        return bad;
    }""")
    assert overflow == [], overflow
    assert editor.locator(".svg-panel__body").first.evaluate("el => el.scrollWidth <= el.clientWidth + 1")

    # 窄屏（笔记本）切到上下布局后同样不能溢出
    snapshot = """() => {
        const dialog = document.querySelector('#svg-page-editor');
        const box = dialog.getBoundingClientRect();
        const bad = [];
        dialog.querySelectorAll('.svg-editor__topbar *, .svg-editor__panel *').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width && (rect.right > box.right + 1 || rect.left < box.left - 1)) {
                bad.push(`${el.className}|${el.textContent.slice(0, 12)}`);
            }
        });
        ['.svg-editor__topbar', '.svg-editor__statusbar', '.svg-editor__panel'].forEach(selector => {
            const el = dialog.querySelector(selector);
            if (el.scrollWidth - el.clientWidth > 1) bad.push(`${selector}:scrollWidth`);
        });
        return bad;
    }"""
    page.set_viewport_size({"width": 1024, "height": 768})
    page.wait_for_timeout(200)
    narrow = page.evaluate(snapshot)
    assert narrow == [], narrow
    page.set_viewport_size({"width": 1440, "height": 990})
    page.wait_for_timeout(200)
    assert page.evaluate(snapshot) == []
    editor.locator("[data-close]").click()
    assert not errors, errors


def test_segmented_controls_never_wrap_labels(browser_page):
    """对齐类控件必须单行显示：面板只有 ~336px，折行会把文字挤到药丸外面。"""
    page, _, errors = browser_page
    editor = open_editor(page)
    frame = page.frame_locator("#svg-page-editor iframe")
    frame.locator("#card").click()

    # 矩形只显示「对齐到安全区」，两个轴各一行，标签短到不会折行
    assert [text.strip() for text in editor.locator(".svg-align__axis").all_text_contents()] == ["水平", "垂直"]
    assert editor.locator(".svg-seg__btn:visible").count() == 6
    assert [text.strip() for text in editor.locator("[data-align] .svg-seg__btn").all_text_contents()] == [
        "左", "居中", "右", "上", "居中", "下"]

    probe = """() => {
        const bad = [];
        document.querySelectorAll('#svg-page-editor .svg-seg__btn').forEach(el => {
            if (!el.offsetParent) return;
            const range = document.createRange();
            range.selectNodeContents(el);
            const rows = new Set(Array.from(range.getClientRects()).map(r => Math.round(r.top)));
            const label = el.textContent.trim();
            if (rows.size > 1) bad.push(`wrapped:${label}`);
            if (el.scrollWidth > el.clientWidth + 1) bad.push(`clipped:${label}`);
            if (el.scrollHeight > el.clientHeight + 1) bad.push(`tall:${label}`);
        });
        return bad;
    }"""
    for width, height in ((1440, 990), (1280, 800), (1024, 768)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(200)
        assert page.evaluate(probe) == [], f"{width}x{height}"
    page.set_viewport_size({"width": 1440, "height": 990})
    page.wait_for_timeout(200)

    # 短标签并没有把行为改掉：水平/垂直居中仍然居中于安全区
    editor.locator("[data-align-x='center']").click()
    assert editor.locator("[data-prop='x']").input_value() == "375"
    editor.locator("[data-align-y='middle']").click()
    assert editor.locator("[data-prop='y']").input_value() == "185"

    # 文字元素额外出现「水平对齐」一行，同样不得折行
    frame.locator("#heading").click()
    assert editor.locator(".svg-seg__btn:visible").count() == 9
    assert page.evaluate(probe) == []
    editor.locator("[data-close]").click()
    editor.locator("[data-discard]").click()
    editor.wait_for(state="detached")
    assert not errors, errors


def test_hover_field_visibility_and_layers(browser_page):
    page, _, _ = browser_page
    editor = open_editor(page)
    frame = page.frame_locator("#svg-page-editor iframe")

    frame.locator("#heading").click()
    assert editor.locator("[data-prop='content']").is_visible()
    assert editor.locator("[data-prop='boxw']").is_visible()
    assert editor.locator("[data-prop='w']").is_hidden()
    assert "文本" in editor.locator("[data-element]").text_content()
    assert editor.locator("[data-lines]").text_content().startswith("1 行")

    frame.locator("#card").click()
    assert editor.locator("[data-prop='w']").is_visible()
    assert editor.locator("[data-prop='radius']").is_visible()
    assert editor.locator("[data-prop='content']").is_hidden()
    assert editor.locator("[data-prop='boxw']").is_hidden()

    # 图层列表可以直接选中分组，不必在画布上找空白处；契约内的 role 显示中文名
    editor.locator(".svg-layer", has_text='data-role="main"').click()
    assert editor.locator("[data-element]").text_content().startswith("分组")
    assert editor.locator("[data-crumbs] .svg-crumb").last.text_content() == "main"
    editor.locator(".svg-layer", has_text='data-role="title"').click()
    assert editor.locator("[data-crumbs] .svg-crumb").last.text_content() == "标题"
    editor.locator("[data-close]").click()


def test_keyboard_shortcuts_and_alignment(browser_page):
    page, _, _ = browser_page
    editor = open_editor(page)
    frame = page.frame_locator("#svg-page-editor iframe")
    editor.locator(".svg-layer", has_text="bar").click()
    assert editor.locator("[data-prop='x']").input_value() == "700"

    page.keyboard.press("ArrowRight")
    assert editor.locator("[data-prop='x']").input_value() == "701"
    page.keyboard.press("Shift+ArrowDown")
    assert editor.locator("[data-prop='y']").input_value() == "230"

    editor.locator("[data-align-x='left']").click()
    assert editor.locator("[data-prop='x']").input_value() == "48"

    rows = editor.locator("[data-layers] .svg-layer").count()
    page.keyboard.press("Control+d")
    assert editor.locator("[data-layers] .svg-layer").count() > rows
    page.keyboard.press("Control+z")
    assert editor.locator("[data-layers] .svg-layer").count() == rows

    # 删除与撤销：撤销会清空选择，重新点选后再删
    editor.locator(".svg-layer", has_text="bar").click()
    page.keyboard.press("Delete")
    assert frame.locator("#bar").count() == 0
    page.keyboard.press("Control+z")
    assert frame.locator("#bar").count() == 1
    editor.locator("[data-close]").click()


def test_layer_rebuild_restores_focus_without_stealing_text_input(browser_page):
    page, _, errors = browser_page
    editor = open_editor(page)
    frame = page.frame_locator('#svg-page-editor iframe')
    editor.locator('.svg-layer', has_text='bar').click()
    page.keyboard.press('Control+d')
    assert editor.locator('.svg-layer.is-active').evaluate('el => el === document.activeElement')
    page.keyboard.press('ArrowRight')
    assert editor.locator("[data-prop='x']").input_value() == '717'
    page.keyboard.press('Control+z')
    assert editor.evaluate('el => el.contains(document.activeElement)'), '撤销重建图层后焦点不能落到 body'
    page.keyboard.press('Control+Shift+z')
    assert editor.evaluate('el => el.contains(document.activeElement)')
    editor.locator('.svg-layer', has_text='bar').first.click()
    page.keyboard.press('Delete')
    assert editor.evaluate('el => el.contains(document.activeElement)')
    page.keyboard.press('Control+z')
    assert frame.locator('#bar').count() == 1

    # 实时修改文字会重建图层摘要，焦点必须继续留在输入框内。
    frame.locator('#heading').click()
    content = editor.locator("[data-prop='content']")
    content.fill('持续输入')
    assert content.evaluate('el => el === document.activeElement')
    page.keyboard.type(' ABC')
    assert content.input_value() == '持续输入 ABC'
    assert editor.locator('[data-dirty]').is_visible()
    assert not errors, errors


def test_zoom_and_diagnostics(browser_page):
    page, _, _ = browser_page
    editor = open_editor(page)
    frame = page.frame_locator("#svg-page-editor iframe")

    fitted = editor.locator("[data-paper]").bounding_box()["width"]
    editor.locator("[data-zoom='in']").click()
    assert editor.locator("[data-paper]").bounding_box()["width"] > fitted
    assert editor.locator("[data-zoom-label]").text_content().endswith("%")
    editor.locator("[data-zoom='fit']").click()
    assert editor.locator("[data-zoom-label]").text_content() == "适应"

    frame.locator("#heading").click()
    editor.locator("[data-prop='x']").fill("1240")
    assert editor.locator("[data-issues]").is_visible()
    assert "超出画布" in editor.locator("[data-issues]").text_content()
    assert frame.locator("#heading").get_attribute("data-svg-issue") == ""

    editor.locator("[data-prop='x']").fill("80")
    editor.locator("[data-prop='size']").fill("12")
    assert "字号低于" in editor.locator("[data-issues]").text_content()

    editor.locator("[data-close]").click()
    assert editor.locator("[data-confirm]").is_visible()
    editor.locator("[data-discard]").click()
    editor.wait_for(state="detached")


def test_resize_handles_and_text_rewrap(browser_page):
    page, _, _ = browser_page
    editor = open_editor(page)
    frame = page.frame_locator("#svg-page-editor iframe")

    # 四角手柄只在无旋转/无缩放时出现，拖动直接改几何属性，导出仍是原生形状
    frame.locator("#card").click()
    before = float(frame.locator("#card").get_attribute("width"))
    handle = frame.locator('[data-svg-handle="se"]').bounding_box()
    assert handle, "无旋转无缩放的元素应出现缩放手柄"
    page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
    page.mouse.down()
    page.mouse.move(handle["x"] + handle["width"] / 2 + 90, handle["y"] + handle["height"] / 2 + 60, steps=6)
    page.mouse.up()
    assert float(frame.locator("#card").get_attribute("width")) > before
    assert editor.locator("[data-dirty]").is_visible()

    # 换行宽度改小后按真实字宽重排成多行，与服务端行版一致
    frame.locator("#heading").click()
    editor.locator("[data-prop='boxw']").fill("200")
    lines = frame.locator("#heading tspan").count()
    assert lines >= 3, lines
    hint = editor.locator("[data-lines]").text_content()
    assert int(hint.split()[0]) == lines
    assert frame.locator("#heading").get_attribute("data-box-w") == "200"

    editor.locator("[data-close]").click()
    editor.locator("[data-discard]").click()
    editor.wait_for(state="detached")


def test_save_posts_clean_markup(browser_page):
    page, posts, errors = browser_page
    editor = open_editor(page)
    assert editor.locator('[data-dirty]').is_hidden()
    frame = page.frame_locator("#svg-page-editor iframe")
    frame.locator("#heading").click()
    editor.locator("[data-prop='content']").fill("SVG 编辑器保存校验")
    editor.locator("[data-prop='fill']").fill("#0369a1")
    # 文字面板不显示描边；切换到矩形验证描边颜色的独立输入路径。
    frame.locator('#card').click()
    editor.locator("[data-prop='stroke']").fill("#f97316")
    assert editor.locator('[data-dirty]').is_visible()
    assert frame.locator('#heading').get_attribute('fill') == '#0369a1'
    assert frame.locator('#card').get_attribute('stroke') == '#f97316'
    editor.locator("[data-save]").click()
    page.wait_for_function("document.querySelector('[data-status]').textContent === '已保存'")
    assert editor.locator("[data-dirty]").is_hidden()
    assert len(posts) == 1
    markup = posts[0]["htmlContent"]
    assert "SVG 编辑器保存校验" in markup
    assert 'fill="#0369a1"' in markup
    assert 'stroke="#f97316"' in markup
    assert 'viewBox="0 0 1280 720"' in markup, "viewBox 大小写必须保留"
    assert "landppt-svg-page" in markup
    for marker in ("data-svg-selected", "data-svg-hover", "data-svg-overlay", "data-svg-issue"):
        assert marker not in markup
    editor.locator("[data-close]").click()
    editor.wait_for(state="detached")
    assert page.evaluate("document.querySelectorAll('iframe').length") == 1
    assert not errors, errors
