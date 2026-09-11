"""Browser regression fixture for SVG editing and both PPTX modes.

Uses local assets and an intercepted save API backed by the real SVG validator.
No AI calls, project writes or external assets. Run with uv run python -m
scripts.svg_experiment.check_edit_export. Artifacts are written below artifacts/.
"""
import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from playwright.sync_api import sync_playwright

from landppt.services.slide.svg_page.edit import validate_svg_edit
from landppt.services.slide.svg_page.shell import build_slide_html


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
<defs><linearGradient id="gradient"><stop offset="0" stop-color="#334155"/><stop offset="1" stop-color="#0f172a"/></linearGradient>
<symbol id="star" viewBox="0 0 24 24"><path d="M12 2 L15 9 L23 9 L17 14 L19 22 L12 17 L5 22 L7 14 L1 9 L9 9 Z" fill="#fbbf24"/></symbol>
<clipPath id="clip"><circle cx="1050" cy="520" r="60"/></clipPath></defs>
<g data-role="background"><rect width="1280" height="720" fill="#f8fafc"/></g>
<g data-role="title"><text id="heading" x="80" y="105" fill="#0f172a" font-size="42" font-family="Arial" data-box-w="1000">SVG 页面编辑与导出</text></g>
<g data-role="main"><rect id="card" x="80" y="170" width="530" height="350" rx="24" fill="url(#gradient)"/>
<text id="body" x="120" y="250" font-size="28" font-family="Arial" fill="#ffffff"><tspan x="120">Editable text 2026</tspan><tspan x="120" dy="48">中文内容保持可编辑</tspan></text>
<g transform="translate(700 220)"><rect id="bar" x="0" y="0" width="130" height="260" fill="#38bdf8"/><circle cx="230" cy="60" r="50" fill="#fb7185"/></g>
<line x1="700" y1="530" x2="970" y2="490" stroke="#0f172a" stroke-width="4"/>
<polygon points="1000,250 1050,170 1100,250" fill="#14b8a6"/>
<use href="#star" x="460" y="390" width="70" height="70"/>
<g clip-path="url(#clip)"><rect x="970" y="440" width="180" height="180" fill="#818cf8"/></g>
</g></svg>'''


def main():
    out = Path('artifacts/svg-mode-verification/edit-export')
    out.mkdir(parents=True, exist_ok=True)
    baseline = build_slide_html(SVG)
    saved = []
    errors = []
    assets = Path('src/landppt/web/static/js')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1050})
        page.on('pageerror', lambda error: errors.append(str(error)))

        def serve(route):
            path = urlparse(route.request.url).path
            if path == '/api/ai/slide-edit-agent/apply':
                body = route.request.post_data_json
                assert body['expectedBaseHash'] == hashlib.sha256(baseline.strip().encode('utf-8')).hexdigest()
                result = validate_svg_edit(body['htmlContent'], baseline)
                assert result.valid, result.errors
                saved.append(result.sanitized_html)
                route.fulfill(json={'success': True, 'htmlContent': result.sanitized_html,
                    'slideData': {'render_mode': 'svg', 'html_content': result.sanitized_html, 'page_number': 1}})
            elif path == '/missing-image.png':
                route.fulfill(status=404, body='missing')
            elif path.startswith('/static/js/'):
                source = assets / path.removeprefix('/static/js/')
                route.fulfill(body=source.read_bytes(), content_type='text/javascript; charset=utf-8')
            else:
                route.fulfill(body='<html><head><meta charset="utf-8"></head><body><iframe id="slideFrame"></iframe><textarea id="codeEditor"></textarea></body></html>', content_type='text/html; charset=utf-8')

        page.route('**/*', serve)
        page.goto('http://localhost/svg-fixture')
        page.evaluate('''html => {
            window.slidesData = [{html_content:html,render_mode:'svg',page_number:1}];
            window.currentSlideIndex = 0; window.landpptEditorConfig = {projectId:'fixture'};
            window.setSafeIframeContent = (frame,content) => { frame.srcdoc=content; };
            window.showNotification = () => {};
        }''', baseline)
        page.add_script_tag(url='/static/js/dom-to-pptx.bundle.js')
        assert page.evaluate('typeof window.domToPptx !== "undefined"'), errors
        prefix = '/static/js/pages/project/slides_editor/projectSlidesEditor.'
        page.add_script_tag(url=prefix + 'svgEdit.js')
        page.add_script_tag(url=prefix + 'svgPptx.js')
        styles = Path('src/landppt/web/static/css/pages/project/slides_editor')
        page.add_style_tag(content=(styles / 'projectSlidesEditor.css').read_text(encoding='utf-8'))
        page.add_style_tag(content=(styles / 'projectSlidesEditor.svgEdit.css').read_text(encoding='utf-8'))
        page.evaluate('openSvgPageEditor()')
        editor = page.locator('#svg-page-editor')
        frame = page.frame_locator('#svg-page-editor iframe')
        # 图层列表先给出可选元素，不必在画布上碰运气点中
        assert editor.locator('[data-layers] .svg-layer').count() >= 8
        assert editor.locator('[data-zoom-label]').text_content() == '适应'
        frame.locator('#heading').click()
        assert 'heading' in editor.locator('[data-element]').text_content()
        assert editor.locator('[data-inspector]').is_visible()
        # 属性面板实时应用，不再需要“应用属性”按钮
        assert page.locator('[data-apply]').count() == 0
        editor.locator('[data-prop="content"]').fill('SVG 编辑成功：文字与图形')
        assert frame.locator('#heading').text_content() == 'SVG 编辑成功：文字与图形'
        # 未保存时关闭会先确认，不弹原生对话框
        editor.locator('[data-close]').click()
        assert editor.locator('[data-confirm]').is_visible()
        editor.locator('[data-keep]').click()
        assert editor.locator('[data-confirm]').is_hidden()
        editor.locator('[data-prop="size"]').fill('38')
        assert frame.locator('#heading').get_attribute('font-size') == '38'
        editor.locator('[data-prop="fill"]').fill('#0369a1')
        assert frame.locator('#heading').get_attribute('fill') == '#0369a1'
        # 撤销逐步回退三次修改
        for _ in range(3):
            editor.locator('[data-undo]').click()
        assert frame.locator('#heading').text_content() == 'SVG 页面编辑与导出'
        assert frame.locator('#heading').get_attribute('font-size') == '42'
        frame.locator('#heading').click()
        editor.locator('[data-prop="content"]').fill('SVG 编辑成功：文字与图形')
        assert frame.locator('#heading').text_content() == 'SVG 编辑成功：文字与图形'
        # 未旋转、未缩放时直接改几何属性，导出仍读得到原生形状
        frame.locator('#card').click()
        editor.locator('[data-prop="w"]').fill('300')
        assert float(frame.locator('#card').get_attribute('width')) == 300
        bar = frame.locator('#bar').bounding_box()
        page.mouse.move(bar['x'] + 30, bar['y'] + 30)
        page.mouse.down(); page.mouse.move(bar['x'] + 90, bar['y'] + 60, steps=5); page.mouse.up()
        assert 'translate(' in frame.locator('#bar').get_attribute('transform')
        assert editor.locator('[data-dirty]').is_visible()
        page.screenshot(path=str(out / 'svg-editor.png'))
        page.locator('[data-save]').click()
        page.wait_for_function("document.querySelector('[data-status]').textContent === '已保存'")
        assert editor.locator('[data-dirty]').is_hidden()
        assert saved and 'SVG 编辑成功' in saved[0] and 'data-svg-selected' not in saved[0]
        assert 'data-svg-overlay' not in saved[0] and 'data-svg-hover' not in saved[0]
        assert page.evaluate('document.querySelectorAll("iframe").length') == 2
        editor.locator('[data-close]').click()
        editor.wait_for(state='detached')
        reports = {}
        for mode in ['native', 'vector']:
            result = page.evaluate('''async mode => {
                const result = await svgPptx.build(slidesData, mode, window.domToPptx);
                const bytes = new Uint8Array(await result.blob.arrayBuffer());
                let binary = ''; for (const b of bytes) binary += String.fromCharCode(b);
                return {file:btoa(binary),stats:result.stats};
            }''', mode)
            target = out / f'svg-{mode}.pptx'
            target.write_bytes(base64.b64decode(result['file']))
            with ZipFile(target) as pptx:
                for name in pptx.namelist():
                    if name.endswith(('.xml', '.rels', '.svg')):
                        ET.fromstring(pptx.read(name))
                slide = pptx.read('ppt/slides/slide1.xml').decode()
                assert 'svgBlip' in slide
                assert any(n.endswith('.svg') for n in pptx.namelist())
                assert any(n.endswith('.png') for n in pptx.namelist())
                if mode == 'native':
                    assert 'SVG 编辑成功' in slide and 'Editable text 2026' in slide
                    assert result['stats'][0]['texts'] >= 3 and result['stats'][0]['shapes'] >= 5
                    assert '<a:custGeom>' in slide and '<a:close' in slide
                else:
                    assert result['stats'][0] == {'texts': 0, 'shapes': 0, 'vectors': 1}
            reports[mode] = result['stats']
        checks = page.evaluate('''async () => {
            const controller = new AbortController(); controller.abort();
            let cancelled = false, invalid = false, missing = false;
            try { await svgPptx.build(slidesData, 'native', domToPptx, {signal:controller.signal}); }
            catch (e) { cancelled = e.name === 'AbortError'; }
            try { await svgPptx.build([{html_content:'<div>HTML</div>'}], 'native', domToPptx); }
            catch (e) { invalid = true; }
            const bad = {...slidesData[0], html_content:slidesData[0].html_content.replace('</svg>', '<image href="/missing-image.png" width="20" height="20"/></svg>')};
            try { await svgPptx.build([bad], 'native', domToPptx); }
            catch (e) { missing = e.message.includes('404'); }
            const faded = {...slidesData[0], html_content:slidesData[0].html_content.replace('<svg ', '<svg opacity="0.5" ')};
            const multiple = await svgPptx.build([slidesData[0], faded], 'native', domToPptx);
            const bytes = new Uint8Array(await multiple.blob.arrayBuffer());
            let binary = ''; for (const b of bytes) binary += String.fromCharCode(b);
            return {cancelled,invalid,missing,stats:multiple.stats,file:btoa(binary),iframes:document.querySelectorAll('iframe').length};
        }''')
        assert checks['cancelled'] and checks['invalid'] and checks['missing'], checks
        assert checks['iframes'] == 1
        assert checks['stats'][1] == {'texts': 0, 'shapes': 0, 'vectors': 1}
        multi_path = out / 'svg-multiple.pptx'
        multi_path.write_bytes(base64.b64decode(checks.pop('file')))
        with ZipFile(multi_path) as pptx:
            assert 'ppt/slides/slide2.xml' in pptx.namelist()
        reports['edge_cases'] = checks
        assert not errors, errors
        browser.close()
    (out / 'result.json').write_text(json.dumps({'saved': len(saved), 'exports': reports, 'browser_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(reports, ensure_ascii=False))


if __name__ == '__main__':
    main()

