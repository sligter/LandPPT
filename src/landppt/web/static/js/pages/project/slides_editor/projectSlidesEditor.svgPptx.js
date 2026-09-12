/* SVG pages: editable DrawingML primitives, with SVG + PNG fallback for complex art.
 * Conversion is conservative: effects, nontrivial text and transforms stay vector.
 * The source DOM and stored page are never modified by export.
 */
const svgPptx = (() => {
    const NS = 'http://www.w3.org/2000/svg';
    const PX = 1 / 96;
    const paintProperties = ['fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width',
        'stroke-opacity', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray',
        'opacity', 'font-family', 'font-size', 'font-weight', 'font-style', 'letter-spacing',
        'text-anchor', 'dominant-baseline', 'alignment-baseline', 'word-spacing',
        'text-decoration', 'visibility', 'display', 'color'];
    const skipTags = new Set(['defs', 'symbol', 'clipPath', 'mask', 'filter', 'marker', 'pattern',
        'linearGradient', 'radialGradient', 'title', 'desc', 'metadata', 'style']);
    const serialize = node => new XMLSerializer().serializeToString(node);
    const dataUrl = text => 'data:image/svg+xml;base64,' + btoa(Array.from(new TextEncoder().encode(text), b => String.fromCharCode(b)).join(''));

    function color(value) {
        if (!value || value === 'none' || value.includes('url(')) return null;
        const ctx = document.createElement('canvas').getContext('2d');
        ctx.fillStyle = value;
        const parsed = ctx.fillStyle;
        if (/^#[0-9a-f]{6}$/i.test(parsed)) return {color: parsed.slice(1), alpha: 1};
        const rgb = parsed.match(/^rgba?\(([^)]+)\)$/);
        if (!rgb) return null;
        const parts = rgb[1].split(',').map(Number);
        return {color: parts.slice(0, 3).map(n => Math.round(n).toString(16).padStart(2, '0')).join(''), alpha: parts[3] ?? 1};
    }

    function clonePainted(node, win) {
        const clone = node.cloneNode(false);
        if (!skipTags.has(node.localName)) {
            const css = win.getComputedStyle(node);
            paintProperties.forEach(p => clone.style.setProperty(p, css.getPropertyValue(p)));
        }
        for (const child of node.childNodes) {
            clone.appendChild(child.nodeType === 1 && !skipTags.has(child.localName)
                ? clonePainted(child, win) : child.cloneNode(true));
        }
        return clone;
    }

    function vectorMarkup(root, target, win) {
        if (target === root) {
            const full = clonePainted(root, win);
            full.setAttribute('xmlns', NS);
            full.setAttribute('width', '1280'); full.setAttribute('height', '720');
            return serialize(full);
        }
        const full = clonePainted(root, win);
        full.replaceChildren();
        full.setAttribute('xmlns', NS);
        full.setAttribute('width', '1280'); full.setAttribute('height', '720');
        root.querySelectorAll('defs').forEach(def => full.appendChild(def.cloneNode(true)));
        let layer = clonePainted(target, win);
        for (let parent = target.parentElement; parent && parent !== root; parent = parent.parentElement) {
            const wrapper = clonePainted(parent, win); wrapper.replaceChildren(layer); layer = wrapper;
        }
        full.appendChild(layer);
        return serialize(full);
    }

    async function inlineImages(root, signal) {
        for (const img of root.querySelectorAll('image')) {
            const href = img.getAttribute('href') || img.getAttributeNS('http://www.w3.org/1999/xlink', 'href');
            if (!href || href.startsWith('data:')) continue;
            const response = await fetch(href, {signal});
            if (!response.ok) throw new Error('无法读取 SVG 图片资源：' + response.status);
            const blob = await response.blob();
            if (!blob.type.startsWith('image/')) throw new Error('SVG 图片地址未返回有效图片');
            const data = await new Promise((resolve, reject) => {
                const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob);
            });
            img.removeAttributeNS('http://www.w3.org/1999/xlink', 'href'); img.setAttribute('href', data);
        }
    }

    function hasEffect(node, css) {
        return ['filter', 'clip-path', 'mask', 'marker-start', 'marker-mid', 'marker-end'].some(p => {
            const v = css.getPropertyValue(p) || node.getAttribute(p); return v && v !== 'none';
        }) || (css.mixBlendMode && css.mixBlendMode !== 'normal');
    }

    function addNative(node, slide, win, stats) {
        const tag = node.localName, css = win.getComputedStyle(node), m = node.getCTM();
        if (!m || Math.abs(m.b) > .00001 || Math.abs(m.c) > .00001 || m.a <= 0 || m.d <= 0 || hasEffect(node, css)) return false;
        if (css.fill.includes('url(') || css.stroke.includes('url(') || css.strokeDasharray !== 'none') return false;
        const opacity = Number(css.opacity), f = color(css.fill), s = color(css.stroke);
        if (s && (Math.abs(m.a - m.d) > .00001 || css.strokeLinecap !== 'butt' || css.vectorEffect !== 'none')) return false;
        const options = {
            objectName: node.id || tag,
            fill: {color: f?.color || 'FFFFFF', transparency: 100 * (1 - (f ? f.alpha * Number(css.fillOpacity) * opacity : 0))},
            line: {color: s?.color || 'FFFFFF', transparency: 100 * (1 - (s ? s.alpha * Number(css.strokeOpacity) * opacity : 0)),
                width: parseFloat(css.strokeWidth) * m.a * .75}
        };
        if (!s || parseFloat(css.strokeWidth) <= 0) options.line = {type: 'none'};
        const x = v => (v * m.a + m.e) * PX, y = v => (v * m.d + m.f) * PX;
        const attr = name => node[name]?.baseVal?.value ?? Number(node.getAttribute(name) || 0);
        if (['rect', 'circle', 'ellipse'].includes(tag)) {
            const box = node.getBBox();
            if (!box.width || !box.height) return true;
            const rx = tag === 'rect' ? attr('rx') : 0, ry = tag === 'rect' ? attr('ry') : 0;
            if (rx && ry && Math.abs(rx * m.a - ry * m.d) > .1) return false;
            slide.addShape(tag === 'rect' ? (rx || ry ? 'roundRect' : 'rect') : 'ellipse', {
                ...options, x: x(box.x), y: y(box.y), w: box.width * m.a * PX, h: box.height * m.d * PX,
                rectRadius: Math.min((rx || ry) * m.a, box.width * m.a / 2, box.height * m.d / 2) * PX
            });
        } else if (tag === 'line') {
            const x1 = x(attr('x1')), x2 = x(attr('x2')), y1 = y(attr('y1')), y2 = y(attr('y2'));
            slide.addShape('line', {...options, x: Math.min(x1, x2), y: Math.min(y1, y2),
                w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), flipV: (x2 - x1) * (y2 - y1) < 0});
        } else if (tag === 'polygon' || tag === 'polyline') {
            if (css.fillRule === 'evenodd') return false;
            const box = node.getBBox();
            if (!box.width || !box.height || node.points.numberOfItems < 2) return false;
            const points = Array.from({length: node.points.numberOfItems}, (_, i) => {
                const p = node.points.getItem(i);
                return {x: (p.x - box.x) * m.a * PX, y: (p.y - box.y) * m.d * PX};
            });
            if (tag === 'polygon') points.push({close: true});
            slide.addShape('custGeom', {...options, x: x(box.x), y: y(box.y),
                w: box.width * m.a * PX, h: box.height * m.d * PX, points});
        } else if (tag === 'text') {
            // Independent, uniform lines can be represented by editable text boxes.
            if (Math.abs(m.a - m.d) > .00001 || !f || s || parseFloat(css.letterSpacing) ||
                parseFloat(css.wordSpacing) || css.textDecorationLine !== 'none' ||
                !['auto', 'alphabetic'].includes(css.dominantBaseline) || node.hasAttribute('textLength') || node.hasAttribute('rotate')) return false;
            const children = Array.from(node.children);
            if (children.some(c => c.localName !== 'tspan' || c.children.length || !c.hasAttribute('x')) ||
                (children.length && Array.from(node.childNodes).some(c => c.nodeType === 3 && c.textContent.trim()))) return false;
            const lines = children.length ? children : [node];
            if (lines.some(line => {
                const style = win.getComputedStyle(line);
                return ['fontSize', 'fontFamily', 'fontWeight', 'fontStyle', 'fill', 'opacity'].some(p => style[p] !== css[p]) ||
                    line.hasAttribute('rotate') || line.hasAttribute('textLength') ||
                    ['x', 'y', 'dx', 'dy'].some(p => (line.getAttribute(p) || '').trim().split(/[\s,]+/).length > 1);
            })) return false;
            for (const line of lines) {
                if (!line.textContent.trim()) continue;
                const b = line.getBBox(), fontPx = parseFloat(css.fontSize) * m.a;
                // SVG glyph boxes exclude leading; use the glyph top with zero PPT margins.
                slide.addText(line.textContent, {objectName: node.id || 'SVG text', x: x(b.x), y: y(b.y), w: Math.max(b.width * m.a * PX + .04, .05),
                    h: Math.max(fontPx * 1.3 * PX, b.height * m.d * PX), margin: 0, breakLine: false,
                    fontFace: css.fontFamily.split(',')[0].replace(/['"]/g, '').trim(), fontSize: fontPx * .75,
                    bold: Number(css.fontWeight) >= 600 || css.fontWeight === 'bold', italic: css.fontStyle === 'italic',
                    color: f.color, transparency: 100 * (1 - f.alpha * Number(css.fillOpacity) * opacity),
                    valign: 'top', paraSpaceAfterPt: 0, charSpacing: 0});
                stats.texts++;
            }
            return true;
        } else return false;
        stats.shapes++; return true;
    }

    async function convert(doc, pptx, mode, signal) {
        const root = doc.querySelector('svg'), win = doc.defaultView;
        if (!root || root.getAttribute('viewBox')?.trim().replace(/\s+/g, ' ') !== '0 0 1280 720') throw new Error('页面不是有效的 1280 × 720 SVG');
        await inlineImages(root, signal);
        await doc.fonts.ready;
        const slide = pptx.addSlide(), stats = {texts: 0, shapes: 0, vectors: 0};
        const background = color(win.getComputedStyle(doc.body).backgroundColor);
        if (background && background.alpha === 1) slide.background = {color: background.color};
        const vector = node => {
            slide.addImage({data: dataUrl(vectorMarkup(root, node, win)), x: 0, y: 0, w: 1280 * PX, h: 720 * PX}); stats.vectors++;
        };
        function walk(node) {
            if (signal?.aborted) throw new DOMException('导出已取消', 'AbortError');
            if (skipTags.has(node.localName)) return;
            const css = win.getComputedStyle(node);
            if (css.display === 'none') return;
            if (node.localName === 'g' || node === root) {
                if (hasEffect(node, css) || Number(css.opacity) < 1) { vector(node); return; }
                Array.from(node.children).forEach(walk); return;
            }
            if (css.visibility === 'hidden' || css.visibility === 'collapse') return;
            if (!addNative(node, slide, win, stats)) vector(node);
        }
        // A use referencing visible content depends on another layer. Keep the whole
        // page together rather than producing a broken isolated SVG reference.
        const hasCrossLayerUse = Array.from(root.querySelectorAll('use')).some(use => {
            const href = use.getAttribute('href') || use.getAttributeNS('http://www.w3.org/1999/xlink', 'href') || '';
            const target = href.startsWith('#') ? doc.getElementById(href.slice(1)) : null;
            return target && !target.closest('defs,symbol');
        });
        if (mode === 'vector' || hasCrossLayerUse) vector(root); else walk(root);
        return {slide, stats};
    }

    async function build(pages, mode, exporter, options = {}) {
        if (!['native', 'vector'].includes(mode)) throw new Error('未知 SVG 导出方式');
        if (!pages.length || pages.some(p => !p.html_content || !(p.render_mode === 'svg' || /data-render-mode=["']svg["']/.test(p.html_content)))) {
            throw new Error('此入口适用于 SVG 页面；HTML 页面请使用客户端导出');
        }
        const pptx = exporter.createPresentation();
        pptx.defineLayout({name: 'LANDPPT_SVG', width: 1280 * PX, height: 720 * PX}); pptx.layout = 'LANDPPT_SVG';
        pptx.author = 'LandPPT'; pptx.subject = mode === 'native' ? 'SVG native objects with vector fallback' : 'SVG vector pages';
        const frame = document.createElement('iframe');
        frame.setAttribute('sandbox', 'allow-same-origin');
        frame.style.cssText = 'position:fixed;left:-20000px;top:0;width:1280px;height:720px;border:0';
        document.body.appendChild(frame);
        const stats = [];
        try {
            for (let i = 0; i < pages.length; i++) {
                if (options.signal?.aborted) throw new DOMException('导出已取消', 'AbortError');
                await new Promise((resolve, reject) => {
                    const timer = setTimeout(() => reject(new Error('SVG 页面加载超时')), 15000);
                    frame.onload = () => { clearTimeout(timer); resolve(); }; frame.srcdoc = pages[i].html_content;
                });
                const result = await convert(frame.contentDocument, pptx, mode, options.signal);
                if (pages[i].speaker_notes) result.slide.addNotes(pages[i].speaker_notes);
                stats.push(result.stats); options.onProgress?.(i + 1, pages.length);
            }
            if (options.signal?.aborted) throw new DOMException('导出已取消', 'AbortError');
            const blob = await pptx.write({outputType: 'blob'});
            return {blob, stats};
        } finally { frame.remove(); }
    }
    return {build};
})();

async function exportSvgPagesToPptx(mode = 'native') {
    if (isClientExporting) return;
    isClientExporting = true; clientExportCancelRequested = false;
    clientExportAbortController = createClientExportAbortController();
    const signal = clientExportAbortController.signal;
    try {
        showExportOverlay(); updateExportCancelButton(true, false, '取消导出');
        updateExportUI('cog', 'spinning', mode === 'native' ? '正在导出 SVG 原生对象 PPTX' : '正在导出 SVG 矢量保真 PPTX', '准备页面和字体...', 0, '准备中');
        const exporter = await ensureDomToPptxReadyForExport();
        const result = await svgPptx.build([...slidesData].sort((a, b) => a.page_number - b.page_number), mode, exporter, {
            signal, onProgress: (done, total) => updateExportUI(null, null, null, '正在转换 SVG 页面...', done / total * 90, `${done}/${total}`)
        });
        throwIfClientExportCancelled(signal);
        const url = URL.createObjectURL(result.blob), a = document.createElement('a');
        const title = String(window.landpptEditorConfig?.exportTitle || 'LandPPT').replace(/[\\/:*?"<>|]/g, '_');
        a.href = url; a.download = `${title}-SVG-${mode}.pptx`; document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        const totals = result.stats.reduce((s, p) => ({texts: s.texts + p.texts, shapes: s.shapes + p.shapes, vectors: s.vectors + p.vectors}), {texts: 0, shapes: 0, vectors: 0});
        showNotification(mode === 'native' ? `已导出：${totals.texts} 个文本框、${totals.shapes} 个形状、${totals.vectors} 个 SVG 图层` : '已导出整页 SVG，内含 PNG 兼容图', 'success');
    } catch (error) {
        showNotification(error.name === 'AbortError' ? '已取消导出' : 'SVG 导出失败：' + error.message, error.name === 'AbortError' ? 'info' : 'error');
    } finally { hideExportOverlay(); updateExportCancelButton(false); isClientExporting = false; clientExportAbortController = null; }
}

// PPTX 导出菜单按页面渲染模式分流：全 SVG 页面只显示 SVG 导出，含 HTML 页面时只显示客户端导出。
function editorExportTargetsAllSvg() {
    if (Array.isArray(slidesData) && slidesData.length > 0) {
        return slidesData.every(isSvgRenderedSlide);
    }
    return String(window.landpptEditorConfig?.renderMode || 'html') === 'svg';
}

function updateExportDropdownModeVisibility() {
    const allSvg = editorExportTargetsAllSvg();
    [['exportClientModeItem', !allSvg], ['exportSvgNativeModeItem', allSvg], ['exportSvgVectorModeItem', allSvg]]
        .forEach(([id, visible]) => {
            const item = document.getElementById(id);
            if (item) item.style.display = visible ? '' : 'none';
        });
}

(function initExportDropdownModeVisibility() {
    const btn = document.getElementById('exportDropdownBtn');
    if (btn) btn.addEventListener('show.bs.dropdown', updateExportDropdownModeVisibility);
    updateExportDropdownModeVisibility();
})();
