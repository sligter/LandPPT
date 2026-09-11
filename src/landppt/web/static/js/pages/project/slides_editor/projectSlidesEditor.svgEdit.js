// SVG 页面编辑器：图层列表 + 实时属性面板 + 画布直接操作。
// 所有编辑都写成 XML 属性；保存仍走服务端 XML 校验接口，与编辑 agent 共用同一份基线校验。
async function saveSvgSlideContent(index, html, baseline = slidesData[index].html_content) {
    if (!window.crypto?.subtle) throw new Error('请通过 localhost 或 HTTPS 打开页面后保存 SVG 编辑');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(baseline.trim()));
    const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
    const response = await fetch('/api/ai/slide-edit-agent/apply', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({proposalId: 'svg-editor', projectId: window.landpptEditorConfig.projectId,
            slideIndex: index + 1, expectedBaseHash: hash, htmlContent: html})
    });
    const result = await response.json();
    if (!response.ok || !result.success) {
        const detail = result.detail;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || result));
    }
    slidesData[index] = result.slideData;
    if (typeof setInitialSlideState === 'function') setInitialSlideState(index, result.htmlContent);
    if (typeof refreshSidebar === 'function') refreshSidebar();
    if (currentSlideIndex === index) {
        setSafeIframeContent(document.getElementById('slideFrame'), result.htmlContent);
        if (typeof codeMirrorEditor !== 'undefined' && codeMirrorEditor) codeMirrorEditor.setValue(result.htmlContent);
        const source = document.getElementById('codeEditor');
        if (source) source.value = result.htmlContent;
    }
    return result;
}

const SVG_PAGE = {
    ns: 'http://www.w3.org/2000/svg',
    width: 1280,
    height: 720,
    left: 48,
    top: 40,
    right: 1232,
    bottom: 680,
    lineHeight: 1.4,
    fontFloor: 14,
    tolerance: 2,
    handles: ['rect', 'image', 'use', 'circle', 'ellipse'],
    selectable: 'text,rect,circle,ellipse,path,line,polyline,polygon,image,use,g',
    strip: ['data-svg-selected', 'data-svg-hover', 'data-svg-issue'],
    roles: {background: '背景', title: '标题', stage: '主舞台', footer: '页脚'},
    tags: {text: '文本', rect: '矩形', circle: '圆形', ellipse: '椭圆', path: '路径', line: '直线',
        polyline: '折线', polygon: '多边形', image: '图片', use: '图标', g: '分组'},
    fields: {
        text: ['x', 'y', 'boxw', 'lines', 'align', 'content', 'size', 'weight', 'anchor', 'fill', 'opacity'],
        rect: ['x', 'y', 'w', 'h', 'align', 'radius', 'fill', 'stroke', 'strokeWidth', 'opacity'],
        image: ['x', 'y', 'w', 'h', 'align', 'opacity'],
        use: ['x', 'y', 'w', 'h', 'align', 'fill', 'opacity'],
        circle: ['x', 'y', 'r', 'align', 'fill', 'stroke', 'strokeWidth', 'opacity'],
        ellipse: ['x', 'y', 'rx', 'ry', 'align', 'fill', 'stroke', 'strokeWidth', 'opacity'],
        line: ['x1', 'y1', 'x2', 'y2', 'align', 'stroke', 'strokeWidth', 'opacity'],
        default: ['x', 'y', 'w', 'h', 'align', 'fill', 'stroke', 'strokeWidth', 'opacity']
    },
    presets: ['#0f172a', '#334155', '#94a3b8', '#ffffff', '#0ea5e9', '#14b8a6', '#f59e0b', '#f43f5e', '#6366f1']
};

function svgNum(value, fallback = 0) {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function svgRound(value) {
    return Math.round((Number(value) || 0) * 100) / 100;
}

function svgTextOf(node) {
    return (node.textContent || '').replace(/\s+/g, ' ').trim();
}

function svgInert(node) {
    return !node || node.closest('defs, symbol, clipPath, mask, marker, pattern, filter, [data-svg-overlay]');
}

// 元素局部坐标 -> 画布（viewBox）坐标
function svgChain(root, node) {
    const rootCtm = root.getScreenCTM();
    const nodeCtm = node.getScreenCTM();
    return rootCtm && nodeCtm ? rootCtm.inverse().multiply(nodeCtm) : null;
}

function svgGeometry(root, node) {
    let box;
    try { box = node.getBBox(); } catch (error) { return null; }
    const matrix = svgChain(root, node);
    if (!matrix) return null;
    const corners = [[box.x, box.y], [box.x + box.width, box.y],
        [box.x + box.width, box.y + box.height], [box.x, box.y + box.height]]
        .map(([x, y]) => new DOMPoint(x, y).matrixTransform(matrix));
    const xs = corners.map(point => point.x), ys = corners.map(point => point.y);
    const x = Math.min(...xs), y = Math.min(...ys);
    return {local: box, x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y,
        scaleX: Math.hypot(matrix.a, matrix.b), scaleY: Math.hypot(matrix.c, matrix.d),
        rotated: Math.abs(matrix.a - 1) > 1e-3 || Math.abs(matrix.d - 1) > 1e-3};
}

// 视口坐标 -> 指定元素所在坐标空间
function svgPointIn(view, x, y) {
    const ctm = view.getScreenCTM();
    return ctm ? new DOMPoint(x, y).matrixTransform(ctm.inverse()) : new DOMPoint(x, y);
}

// 画布位移量换算到元素所在的父坐标空间
function svgRootDelta(root, node, dx, dy) {
    const rootCtm = root.getScreenCTM();
    const parentCtm = node.parentElement?.getScreenCTM();
    if (!rootCtm || !parentCtm) return {x: dx, y: dy};
    const inverse = parentCtm.inverse().multiply(rootCtm);
    const from = new DOMPoint(0, 0).matrixTransform(inverse);
    const to = new DOMPoint(dx, dy).matrixTransform(inverse);
    return {x: to.x - from.x, y: to.y - from.y};
}

function svgPrepend(node, transform) {
    const current = node.getAttribute('transform') || '';
    node.setAttribute('transform', (transform + (current ? ' ' + current : '')).trim());
}

function svgMove(node, root, dx, dy) {
    if (!root || !node || (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01)) return;
    const delta = svgRootDelta(root, node, dx, dy);
    svgPrepend(node, `translate(${svgRound(delta.x)} ${svgRound(delta.y)})`);
}

function svgScaleAbout(node, root, fx, fy) {
    const geometry = svgGeometry(root, node);
    if (!geometry || !(fx > 0) || !(fy > 0)) return;
    const cx = svgRound(geometry.x + geometry.width / 2);
    const cy = svgRound(geometry.y + geometry.height / 2);
    svgPrepend(node, `translate(${cx} ${cy}) scale(${svgRound(fx)} ${svgRound(fy)}) translate(${-cx} ${-cy})`);
}

function svgSetAttribute(node, name, value) {
    if (value === null || value === undefined || value === '') node.removeAttribute(name);
    else node.setAttribute(name, typeof value === 'number' ? String(svgRound(value)) : String(value));
    if (node.style?.length) {
        node.style.removeProperty(name);
        if (!node.getAttribute('style')) node.removeAttribute('style');
    }
}

// 无旋转、无缩放时直接改几何属性，导出成 PPTX 原生形状时更干净
function svgDirectGeometry(root, node) {
    const geometry = svgGeometry(root, node);
    if (!geometry || geometry.rotated) return null;
    if (Math.abs(geometry.scaleX - 1) > 1e-3 || Math.abs(geometry.scaleY - 1) > 1e-3) return null;
    return geometry;
}

function svgResize(node, root, target) {
    const geometry = svgGeometry(root, node);
    if (!geometry || !node.localName) return false;
    const tag = node.localName;
    const direct = svgDirectGeometry(root, node);
    if (direct && (tag === 'rect' || tag === 'image' || tag === 'use')) {
        if (target.width != null) {
            const width = svgNum(node.getAttribute('width'), geometry.local.width);
            svgSetAttribute(node, 'width', Math.max(1, width * (target.width / (geometry.width || 1))));
        }
        if (target.height != null) {
            const height = svgNum(node.getAttribute('height'), geometry.local.height);
            svgSetAttribute(node, 'height', Math.max(1, height * (target.height / (geometry.height || 1))));
        }
        if (target.left != null) svgSetAttribute(node, 'x', svgNum(node.getAttribute('x'), 0) + (target.left - geometry.x));
        if (target.top != null) svgSetAttribute(node, 'y', svgNum(node.getAttribute('y'), 0) + (target.top - geometry.y));
        return true;
    }
    if (direct && tag === 'circle' && target.width != null) {
        svgSetAttribute(node, 'r', Math.max(0.5, target.width / 2));
        return true;
    }
    if (direct && tag === 'ellipse') {
        if (target.width != null) svgSetAttribute(node, 'rx', Math.max(0.5, target.width / 2));
        if (target.height != null) svgSetAttribute(node, 'ry', Math.max(0.5, target.height / 2));
        return true;
    }
    svgScaleAbout(node, root,
        target.width != null && geometry.width ? target.width / geometry.width : 1,
        target.height != null && geometry.height ? target.height / geometry.height : 1);
    return true;
}

function svgMeasure(win, node) {
    const style = win.getComputedStyle(node);
    const context = document.createElement('canvas').getContext('2d');
    context.font = `${style.fontStyle || 'normal'} ${style.fontWeight || '400'} ${style.fontSize || '16px'} ${style.fontFamily || 'sans-serif'}`;
    return context;
}

function svgFontSize(node, win) {
    const declared = svgNum(node.getAttribute('font-size'), 0);
    return declared > 0 ? declared : svgNum(win.getComputedStyle(node).fontSize, 16);
}

function svgWrapWidth(node) {
    const declared = svgNum(node.getAttribute('data-box-w'), 0);
    if (declared > 0) return {width: declared, declared: true};
    const x = svgNum(node.getAttribute('x'), SVG_PAGE.left);
    const anchor = (node.getAttribute('text-anchor') || 'start').trim();
    let width = SVG_PAGE.right - x;
    if (anchor === 'middle') width = 2 * Math.min(x - SVG_PAGE.left, SVG_PAGE.right - x);
    else if (anchor === 'end') width = x - SVG_PAGE.left;
    return {width: Math.max(160, width), declared: false};
}

// 中文按字、拉丁按词折行，超过一行宽度的长词按字符硬拆
function svgBreakLines(text, limit, measure) {
    const lines = [];
    for (const paragraph of String(text).split(/\r?\n/)) {
        let line = '';
        const flush = () => { lines.push(line.replace(/\s+$/, '')); line = ''; };
        for (const token of paragraph.match(/[A-Za-z0-9@#$%&*+\-./:=_'"]+|\s+|[\s\S]/g) || []) {
            if (/^\s+$/.test(token)) { if (line) line += ' '; continue; }
            if (line && limit > 0 && measure(line + token) > limit) flush();
            if (limit > 0 && measure(token) > limit) {
                for (const character of token) {
                    if (line && measure(line + character) > limit) flush();
                    line += character;
                }
                continue;
            }
            line += token;
        }
        flush();
    }
    return lines;
}

function svgApplyText(node, win, value) {
    const document_ = node.ownerDocument;
    const fontSize = svgFontSize(node, win);
    const limit = svgWrapWidth(node).width;
    const measure = svgMeasure(win, node);
    const lines = svgBreakLines(value, limit, text => measure.measureText(text).width);
    const x = node.getAttribute('x') || '0';
    node.textContent = '';
    lines.forEach((text, index) => {
        const tspan = document_.createElementNS(SVG_PAGE.ns, 'tspan');
        tspan.setAttribute('x', x);
        if (index) tspan.setAttribute('dy', String(svgRound(fontSize * SVG_PAGE.lineHeight)));
        tspan.textContent = text;
        node.appendChild(tspan);
    });
    return lines;
}

function svgLayoutText(node, win) {
    const style = win.getComputedStyle(node);
    const declared = svgNum(node.getAttribute('font-size'), 0);
    const fontSize = declared > 0 ? declared : svgNum(style.fontSize, 16);
    const limit = svgWrapWidth(node).width;
    const context = svgMeasure(win, node);
    const lines = [];
    for (const child of node.childNodes) {
        const text = child.textContent || '';
        if (child.nodeType === 3 || (child.localName === 'tspan' && !child.childNodes.length)) {
            lines.push(...svgBreakLines(text, limit, value => context.measureText(value).width));
        } else if (child.nodeType === 1) {
            lines.push(...svgBreakLines(text, limit, value => context.measureText(value).width));
        }
    }
    if (!lines.length) lines.push('');
    return {lines, fontSize,
        width: Math.max(...lines.map(line => context.measureText(line).width), 0),
        limit};
}

function svgPaintValue(node, win) {
    const style = win.getComputedStyle(node);
    const fill = style.fill === 'none' ? style.stroke : style.fill;
    const context = document.createElement('canvas').getContext('2d');
    context.fillStyle = fill;
    return /^#[0-9a-f]{6}$/i.test(context.fillStyle) ? context.fillStyle : '#000000';
}

function openSvgPageEditor() {
    const index = currentSlideIndex;
    const page = slidesData[index];
    if (!page) return;
    const dialog = document.createElement('dialog');
    dialog.id = 'svg-page-editor';
    dialog.className = 'svg-editor';
    dialog.setAttribute('aria-label', 'SVG 页面编辑器');
    dialog.innerHTML = `
        <div class="svg-editor__shell">
          <header class="svg-editor__topbar">
            <div class="svg-editor__heading">
              <span class="svg-editor__title">SVG 页面编辑</span>
              <span class="svg-editor__page">第 ${index + 1} / ${slidesData.length} 页</span>
            </div>
            <div class="svg-editor__spacer"></div>
            <div class="svg-editor__tools">
              <div class="svg-zoom">
                <button type="button" class="svg-btn svg-btn--icon" data-zoom="out" title="缩小 (Ctrl + 滚轮)"><i class="fas fa-minus"></i></button>
                <span class="svg-zoom__value" data-zoom-label>适应</span>
                <button type="button" class="svg-btn svg-btn--icon" data-zoom="in" title="放大 (Ctrl + 滚轮)"><i class="fas fa-plus"></i></button>
                <button type="button" class="svg-btn" data-zoom="fit">适应窗口</button>
              </div>
              <button type="button" class="svg-btn svg-btn--icon" data-undo title="撤销 (Ctrl+Z)"><i class="fas fa-undo"></i></button>
              <button type="button" class="svg-btn svg-btn--icon" data-redo title="重做 (Ctrl+Shift+Z)"><i class="fas fa-redo"></i></button>
              <button type="button" class="svg-btn svg-btn--primary" data-save title="保存 (Ctrl+S)"><i class="fas fa-save"></i>保存</button>
              <button type="button" class="svg-btn" data-close>关闭</button>
            </div>
          </header>
          <div class="svg-editor__main">
            <div class="svg-editor__stage" data-stage>
              <div class="svg-editor__paper" data-paper>
                <iframe class="svg-editor__frame" data-frame title="SVG 编辑画布" sandbox="allow-same-origin"></iframe>
              </div>
              <span class="svg-editor__badge" data-badge hidden></span>
            </div>
            <aside class="svg-editor__panel">
              <div class="svg-panel__group">
                <div class="svg-panel__head">图层<span class="svg-panel__count" data-layer-count></span></div>
                <div class="svg-panel__body svg-layers" data-layers role="listbox" aria-label="页面元素" tabindex="-1"></div>
              </div>
              <div class="svg-panel__group">
                <div class="svg-panel__head">属性</div>
                <div class="svg-panel__body">
                  <div class="svg-empty" data-empty>
                    在画布上点选元素，或从上方图层列表选择。<br>
                    拖动移动位置，Shift 锁定方向，Alt 吸附 8px；方向键微移，Delete 删除，Ctrl+D 复制，Ctrl+Z 撤销。
                  </div>
                  <div data-inspector hidden>
                    <div class="svg-elementbar">
                      <span class="svg-elementbar__name" data-element></span>
                      <div class="svg-elementbar__actions">
                        <button type="button" class="svg-btn svg-btn--icon" data-action="duplicate" title="复制 (Ctrl+D)"><i class="fas fa-clone"></i></button>
                        <button type="button" class="svg-btn svg-btn--icon" data-action="raise" title="上移一层"><i class="fas fa-arrow-up"></i></button>
                        <button type="button" class="svg-btn svg-btn--icon" data-action="lower" title="下移一层"><i class="fas fa-arrow-down"></i></button>
                        <button type="button" class="svg-btn svg-btn--icon svg-btn--danger" data-action="delete" title="删除 (Delete)"><i class="fas fa-trash"></i></button>
                      </div>
                    </div>
                    <fieldset class="svg-fieldset">
                      <legend class="svg-fieldset__legend">位置与尺寸</legend>
                      <div class="svg-fields">
                        <label class="svg-field" data-field="x"><span class="svg-field__label">X</span><input class="svg-input" type="number" step="1" data-prop="x"></label>
                        <label class="svg-field" data-field="y"><span class="svg-field__label">Y</span><input class="svg-input" type="number" step="1" data-prop="y"></label>
                        <label class="svg-field" data-field="w"><span class="svg-field__label">宽</span><input class="svg-input" type="number" min="1" step="1" data-prop="w"></label>
                        <label class="svg-field" data-field="h"><span class="svg-field__label">高</span><input class="svg-input" type="number" min="1" step="1" data-prop="h"></label>
                        <label class="svg-field" data-field="boxw"><span class="svg-field__label">换行宽度</span><input class="svg-input" type="number" min="40" step="10" data-prop="boxw"></label>
                        <label class="svg-field" data-field="r"><span class="svg-field__label">半径</span><input class="svg-input" type="number" min="0.5" step="1" data-prop="r"></label>
                        <label class="svg-field" data-field="rx"><span class="svg-field__label">水平半径</span><input class="svg-input" type="number" min="0.5" step="1" data-prop="rx"></label>
                        <label class="svg-field" data-field="ry"><span class="svg-field__label">垂直半径</span><input class="svg-input" type="number" min="0.5" step="1" data-prop="ry"></label>
                        <label class="svg-field" data-field="x1"><span class="svg-field__label">X1</span><input class="svg-input" type="number" step="1" data-prop="x1"></label>
                        <label class="svg-field" data-field="y1"><span class="svg-field__label">Y1</span><input class="svg-input" type="number" step="1" data-prop="y1"></label>
                        <label class="svg-field" data-field="x2"><span class="svg-field__label">X2</span><input class="svg-input" type="number" step="1" data-prop="x2"></label>
                        <label class="svg-field" data-field="y2"><span class="svg-field__label">Y2</span><input class="svg-input" type="number" step="1" data-prop="y2"></label>
                        <div class="svg-field svg-field--full" data-field="align">
                          <span class="svg-field__label">对齐到安全区</span>
                          <div class="svg-align" data-align>
                            <div class="svg-align__row">
                              <span class="svg-align__axis">水平</span>
                              <div class="svg-seg">
                                <button type="button" class="svg-seg__btn" data-align-x="left" title="左边缘对齐安全区左边">左</button>
                                <button type="button" class="svg-seg__btn" data-align-x="center" title="水平居中于安全区">居中</button>
                                <button type="button" class="svg-seg__btn" data-align-x="right" title="右边缘对齐安全区右边">右</button>
                              </div>
                            </div>
                            <div class="svg-align__row">
                              <span class="svg-align__axis">垂直</span>
                              <div class="svg-seg">
                                <button type="button" class="svg-seg__btn" data-align-y="top" title="顶部对齐安全区上边">上</button>
                                <button type="button" class="svg-seg__btn" data-align-y="middle" title="垂直居中于安全区">居中</button>
                                <button type="button" class="svg-seg__btn" data-align-y="bottom" title="底部对齐安全区下边">下</button>
                              </div>
                            </div>
                          </div>
                        </div>
                        <div class="svg-field svg-field--full" data-field="lines"><span class="svg-field__hint" data-lines></span></div>
                      </div>
                    </fieldset>
                    <fieldset class="svg-fieldset" data-group="text">
                      <legend class="svg-fieldset__legend">文字</legend>
                      <div class="svg-fields">
                        <label class="svg-field svg-field--full" data-field="content"><span class="svg-field__label">内容</span><textarea class="svg-textarea" rows="4" data-prop="content"></textarea></label>
                        <label class="svg-field" data-field="size"><span class="svg-field__label">字号</span><input class="svg-input" type="number" min="8" max="512" step="1" data-prop="size"></label>
                        <label class="svg-field" data-field="weight"><span class="svg-field__label">字重</span><select class="svg-select" data-prop="weight"><option value="400">常规</option><option value="500">中等</option><option value="700">粗体</option></select></label>
                        <div class="svg-field svg-field--full" data-field="anchor">
                          <span class="svg-field__label">水平对齐</span>
                          <div class="svg-seg" data-anchor>
                            <button type="button" class="svg-seg__btn" data-anchor-value="start">左</button>
                            <button type="button" class="svg-seg__btn" data-anchor-value="middle">中</button>
                            <button type="button" class="svg-seg__btn" data-anchor-value="end">右</button>
                          </div>
                        </div>
                        <span class="svg-field__hint svg-field--full" data-field="text-hint">编辑内容会按真实字宽重新折行，原有 tspan 样式会统一为整段样式。</span>
                      </div>
                    </fieldset>
                    <fieldset class="svg-fieldset">
                      <legend class="svg-fieldset__legend">外观</legend>
                      <div class="svg-fields">
                        <div class="svg-field svg-field--full" data-field="fill">
                          <span class="svg-field__label" data-fill-label>填充</span>
                          <div class="svg-swatches">
                            <input class="svg-input svg-input--color" type="color" data-prop="fill">
                            <label class="svg-checkbox"><input type="checkbox" data-prop="no-fill">无填充</label>
                          </div>
                          <div class="svg-swatches" data-presets></div>
                        </div>
                        <label class="svg-field" data-field="stroke"><span class="svg-field__label">描边</span><input class="svg-input svg-input--color" type="color" data-prop="stroke"></label>
                        <label class="svg-field" data-field="strokeWidth"><span class="svg-field__label">描边宽度</span><input class="svg-input" type="number" min="0" step="0.5" data-prop="strokeWidth"></label>
                        <label class="svg-field" data-field="radius"><span class="svg-field__label">圆角</span><input class="svg-input" type="number" min="0" step="1" data-prop="radius"></label>
                        <div class="svg-field svg-field--full" data-field="opacity">
                          <span class="svg-field__label">不透明度 <span data-opacity-value>100%</span></span>
                          <input class="svg-range" type="range" min="0" max="1" step="0.05" data-prop="opacity">
                        </div>
                      </div>
                    </fieldset>
                  </div>
                </div>
              </div>
            </aside>
          </div>
          <footer class="svg-editor__statusbar">
            <div class="svg-crumbs" data-crumbs></div>
            <div class="svg-status">
              <span class="svg-editor__confirm" data-confirm>有未保存的修改
                <button type="button" class="svg-btn svg-btn--danger" data-discard>放弃并关闭</button>
                <button type="button" class="svg-btn" data-keep>继续编辑</button>
              </span>
              <span class="svg-chip svg-chip--dirty" data-dirty hidden>未保存</span>
              <span class="svg-chip" data-status role="status"></span>
              <span class="svg-chip svg-chip--warn" data-issues hidden></span>
            </div>
          </footer>
        </div>`;
    document.body.appendChild(dialog);
    dialog.showModal();

    const pick = selector => dialog.querySelector(selector);
    const frame = pick('[data-frame]'), stage = pick('[data-stage]'), paper = pick('[data-paper]');
    const badge = pick('[data-badge]'), layersBox = pick('[data-layers]'), countBox = pick('[data-layer-count]');
    const crumbs = pick('[data-crumbs]'), status = pick('[data-status]'), issues = pick('[data-issues]');
    const dirtyChip = pick('[data-dirty]');
    const inspector = pick('[data-inspector]'), empty = pick('[data-empty]');
    const elementName = pick('[data-element]'), linesHint = pick('[data-lines]');
    const fillLabel = pick('[data-fill-label]'), opacityValue = pick('[data-opacity-value]');
    const undoButton = pick('[data-undo]'), redoButton = pick('[data-redo]');
    const confirmBar = pick('[data-confirm]');
    const fields = {}, inputs = {};
    dialog.querySelectorAll('[data-field]').forEach(node => { fields[node.dataset.field] = node; });
    dialog.querySelectorAll('[data-prop]').forEach(node => { inputs[node.dataset.prop] = node; });
    const presets = pick('[data-presets]');
    SVG_PAGE.presets.forEach(color => {
        const swatch = document.createElement('button');
        swatch.type = 'button';
        swatch.className = 'svg-swatch';
        swatch.dataset.swatch = color;
        swatch.style.background = color;
        swatch.title = color;
        presets.appendChild(swatch);
    });

    let document_ = null, root = null, selected = null, hovered = null;
    let drag = null, resizing = null, zoom = 1, fitMode = true;
    let savedMarkup = '', dirty = false;
    const history = [], future = [], rows = new Map();
    let lastHistory = {key: '', time: 0};

    const currentMarkup = () => {
        if (!root) return '';
        const clone = root.cloneNode(true);
        clone.querySelectorAll('[data-svg-overlay]').forEach(node => node.remove());
        SVG_PAGE.strip.forEach(name => {
            clone.querySelectorAll(`[${name}]`).forEach(node => node.removeAttribute(name));
        });
        return new XMLSerializer().serializeToString(clone);
    };

    const notify = (message, type) => {
        if (typeof showNotification === 'function') showNotification(message, type);
    };

    const setStatus = (message, type = '') => {
        status.textContent = message;
        status.className = `svg-chip${type ? ` svg-chip--${type}` : ''}`;
    };

    const setDirty = value => {
        dirty = value;
        dirtyChip.hidden = !dirty;
        if (!dirty) {
            confirmBar.dataset.requested = '0';
            confirmBar.classList.remove('is-visible');
        }
    };

    const pushHistory = key => {
        const now = performance.now();
        if (key && lastHistory.key === key && now - lastHistory.time < 700) {
            lastHistory.time = now;
            return;
        }
        lastHistory = {key: key || '', time: now};
        if (root) history.push(currentMarkup());
        if (history.length > 60) history.shift();
        future.length = 0;
        refreshHistoryButtons();
    };

    function refreshHistoryButtons() {
        undoButton.disabled = !history.length;
        redoButton.disabled = !future.length;
    }

    // ---------- 画布叠加层 ----------
    function refreshOverlay() {
        if (!root || !document_) return;
        let overlay = root.querySelector('[data-svg-overlay]');
        if (!overlay) {
            overlay = document_.createElementNS(SVG_PAGE.ns, 'g');
            overlay.setAttribute('data-svg-overlay', '');
            root.appendChild(overlay);
        }
        while (overlay.firstChild) overlay.removeChild(overlay.firstChild);
        if (!selected || !selected.isConnected) {
            overlay.style.display = 'none';
            return;
        }
        overlay.style.display = '';
        const geometry = svgGeometry(root, selected);
        if (!geometry) return;
        const unit = 1 / (zoom || 1);
        const frame = document_.createElementNS(SVG_PAGE.ns, 'rect');
        frame.setAttribute('class', 'svg-selection');
        frame.setAttribute('x', svgRound(geometry.x - 3 * unit));
        frame.setAttribute('y', svgRound(geometry.y - 3 * unit));
        frame.setAttribute('width', svgRound(geometry.width + 6 * unit));
        frame.setAttribute('height', svgRound(geometry.height + 6 * unit));
        frame.setAttribute('vector-effect', 'non-scaling-stroke');
        overlay.appendChild(frame);
        if (!canResize(selected, geometry)) return;
        const size = 11 * unit;
        for (const corner of ['nw', 'ne', 'sw', 'se']) {
            const handle = document_.createElementNS(SVG_PAGE.ns, 'rect');
            handle.setAttribute('data-svg-handle', corner);
            handle.setAttribute('class', 'svg-handle');
            handle.setAttribute('width', svgRound(size));
            handle.setAttribute('height', svgRound(size));
            handle.setAttribute('x', svgRound(corner.includes('w') ? geometry.x - size / 2 : geometry.x + geometry.width - size / 2));
            handle.setAttribute('y', svgRound(corner.includes('n') ? geometry.y - size / 2 : geometry.y + geometry.height - size / 2));
            handle.setAttribute('vector-effect', 'non-scaling-stroke');
            overlay.appendChild(handle);
        }
    }

    function canResize(node, geometry = svgGeometry(root, node)) {
        if (!geometry || geometry.rotated) return false;
        if (Math.abs(geometry.scaleX - 1) > 1e-3 || Math.abs(geometry.scaleY - 1) > 1e-3) return false;
        return SVG_PAGE.handles.includes(node.localName);
    }

    // ---------- 图层列表 ----------
    function elementLabel(node) {
        const id = node.getAttribute('id');
        if (node.localName === 'text') {
            const text = svgTextOf(node).slice(0, 16);
            return `${id ? `${id} · ` : ''}${text || '文字'}`;
        }
        if (node.localName === 'use') return `图标 ${node.getAttribute('href') || ''}`;
        if (node.localName === 'image') {
            const href = node.getAttribute('href') || '';
            return `图片 ${href.split('/').pop().slice(0, 18) || href.slice(0, 18)}`;
        }
        return id ? `${node.localName} · ${id}` : node.localName;
    }

    function buildLayers() {
        const restoreFocus = layersBox.contains(document.activeElement);
        rows.clear();
        layersBox.innerHTML = '';
        if (!root) return;
        const addRow = (node, depth, locked) => {
            const row = document.createElement('button');
            row.type = 'button';
            row.className = `svg-layer${locked ? ' svg-layer--locked' : ''}`;
            row.dataset.depth = String(depth);
            row.setAttribute('role', 'option');
            row.title = `${node.localName}${node.getAttribute('id') ? ` #${node.getAttribute('id')}` : ''}`;
            const tag = document.createElement('span');
            tag.className = 'svg-layer__tag';
            const role = node.getAttribute('data-role');
            tag.textContent = (role && (SVG_PAGE.roles[role] || role)) || SVG_PAGE.tags[node.localName] || node.localName;
            const label = document.createElement('span');
            label.className = 'svg-layer__label';
            label.textContent = node.localName === 'g' && node.getAttribute('data-role')
                ? `data-role="${node.getAttribute('data-role')}" · ${node.children.length} 项`
                : elementLabel(node);
            row.append(tag, label);
            if (locked) {
                const lock = document.createElement('span');
                lock.className = 'svg-layer__lock';
                lock.textContent = '已锁定';
                row.appendChild(lock);
            }
            if (node.localName === 'g' && node.getAttribute('data-role')) row.classList.add('svg-layer--role');
            row.addEventListener('click', () => selectNode(node));
            row.addEventListener('mouseenter', () => setHover(node));
            row.addEventListener('mouseleave', () => setHover(null));
            rows.set(node, row);
            layersBox.appendChild(row);
        };
        const walk = (node, depth, locked) => {
            if (depth > 3 || svgInert(node) || node.hasAttribute('data-svg-overlay')) return;
            const isLocked = locked || node.getAttribute?.('data-role') === 'background';
            if (depth === 0 && node.localName === 'g' && node.getAttribute('data-role')) addRow(node, 0, isLocked);
            else if (depth === 0 && !SVG_PAGE.tags[node.localName]) return;
            else addRow(node, depth, isLocked);
            if (node.localName !== 'g') return;
            for (const child of node.children) walk(child, depth + 1, isLocked);
        };
        for (const child of root.children) walk(child, 0, false);
        countBox.textContent = rows.size ? `${rows.size} 个元素` : '空';
        // 撤销/删除可能清空选择；让列表本身承接焦点。属性输入框不受影响。
        if (restoreFocus) (rows.get(selected) || layersBox).focus({preventScroll: true});
    }

    function setHover(node) {
        if (hovered === node) return;
        if (hovered) hovered.removeAttribute('data-svg-hover');
        hovered = node && !svgInert(node) ? node : null;
        if (hovered) hovered.setAttribute('data-svg-hover', '');
    }

    function selectNode(node) {
        if (selected && selected !== node) selected.removeAttribute('data-svg-selected');
        selected = node || null;
        if (selected) {
            selected.setAttribute('data-svg-selected', '');
            const row = rows.get(selected);
            if (row) {
                layersBox.querySelectorAll('.is-active').forEach(item => item.classList.remove('is-active'));
                row.classList.add('is-active');
                row.scrollIntoView({block: 'nearest'});
                // 图层重建会移除原焦点，把焦点拉回当前行，快捷键才不会落到 body 上
                if (document.activeElement === document.body || layersBox.contains(document.activeElement)) {
                    row.focus({preventScroll: true});
                }
            }
        }
        refreshOverlay();
        refreshInspector();
        refreshCrumbs();
        if (!selected) setStatus('未选择元素');
    }

    function refreshCrumbs() {
        crumbs.innerHTML = '';
        if (!selected) return;
        const chain = [];
        for (let node = selected; node && node !== root; node = node.parentElement) chain.unshift(node);
        chain.forEach((node, position) => {
            if (position) {
                const separator = document.createElement('span');
                separator.className = 'svg-crumbs__sep';
                separator.textContent = '›';
                crumbs.appendChild(separator);
            }
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'svg-crumb';
            const role = node.getAttribute('data-role');
            button.textContent = node.localName === 'g' && role
                ? (SVG_PAGE.roles[role] || role)
                : (node.getAttribute('id') || node.localName);
            button.addEventListener('click', () => selectNode(node));
            crumbs.appendChild(button);
        });
    }

    // ---------- 属性面板 ----------
    function refreshInspector(options = {}) {
        inspector.hidden = !selected;
        empty.hidden = Boolean(selected);
        if (!selected) return;
        const tag = selected.localName;
        const visible = SVG_PAGE.fields[tag] || SVG_PAGE.fields.default;
        for (const [name, node] of Object.entries(fields)) {
            node.hidden = !(visible.includes(name) || name === 'text-hint');
        }
        fields['text-hint'].hidden = tag !== 'text';
        pick('[data-group="text"]').hidden = tag !== 'text';
        fillLabel.textContent = tag === 'text' ? '文字颜色' : (tag === 'use' ? '图标颜色' : '填充');
        elementName.textContent = `${SVG_PAGE.tags[tag] || tag}${selected.getAttribute('id') ? ` · #${selected.getAttribute('id')}` : ''}`;

        const geometry = svgGeometry(root, selected);
        const set = (name, value) => {
            const input = inputs[name];
            if (!input || document.activeElement === input) return;
            input.value = value === null || value === undefined ? '' : value;
        };
        set('x', geometry ? svgRound(geometry.x) : '');
        set('y', geometry ? svgRound(geometry.y) : '');
        set('w', geometry ? svgRound(geometry.width) : '');
        set('h', geometry ? svgRound(geometry.height) : '');
        set('r', svgNum(selected.getAttribute('r'), geometry ? svgRound(geometry.width / 2) : ''));
        set('rx', svgNum(selected.getAttribute('rx'), ''));
        set('ry', svgNum(selected.getAttribute('ry'), ''));
        set('x1', svgNum(selected.getAttribute('x1'), ''));
        set('y1', svgNum(selected.getAttribute('y1'), ''));
        set('x2', svgNum(selected.getAttribute('x2'), ''));
        set('y2', svgNum(selected.getAttribute('y2'), ''));
        set('radius', svgNum(selected.getAttribute('rx'), svgNum(selected.getAttribute('ry'), '')));
        set('strokeWidth', svgNum(selected.getAttribute('stroke-width'), ''));
        set('opacity', svgRound(Math.min(1, Math.max(0, svgNum(selected.getAttribute('opacity'), 1)))));
        opacityValue.textContent = `${Math.round(svgNum(inputs.opacity.value, 1) * 100)}%`;

        const wrap = svgWrapWidth(selected);
        set('boxw', wrap.declared ? wrap.width : '');
        inputs['no-fill'].checked = (selected.getAttribute('fill') || '').trim() === 'none';

        const fill = svgPaintValue(selected, frame.contentWindow);
        set('fill', fill);
        inputs.stroke.value = /^#[0-9a-f]{6}$/i.test(selected.getAttribute('stroke') || '') ? selected.getAttribute('stroke') : '#000000';
        inputs.weight.value = String(svgNum(selected.getAttribute('font-weight'), 400));
        set('size', tag === 'text' ? svgFontSize(selected, frame.contentWindow) : '');
        set('content', tag === 'text' ? svgTextOf(selected) : '');
        dialog.querySelectorAll('[data-anchor-value]').forEach(button => {
            button.setAttribute('aria-pressed', String((selected.getAttribute('text-anchor') || 'start') === button.dataset.anchorValue));
        });
        if (tag === 'text' && options.layout !== false) {
            const layout = svgLayoutText(selected, frame.contentWindow);
            linesHint.textContent = `${layout.lines.length} 行 · 每行可用 ${Math.round(layout.limit)}px · 实际最宽 ${Math.round(layout.width)}px${wrap.declared ? '' : '（未声明换行宽度，按安全区自动折行）'}`;
        }
        if (!canResize(selected, geometry) && tag !== 'text') {
            if (['path', 'polygon', 'polyline', 'line', 'g'].includes(tag)) {
                linesHint.textContent = '该元素用数值面板缩放（画布上是等比拉伸）。';
            }
        }
    }

    // ---------- 缺陷提示（与服务端检查器同一套口径） ----------
    function refreshDiagnostics() {
        if (!root || !frame.contentWindow) return;
        const found = [];
        root.querySelectorAll('[data-svg-issue]').forEach(node => node.removeAttribute('data-svg-issue'));
        for (const node of root.querySelectorAll('text,rect,circle,ellipse,image,use,path,polygon,polyline,line')) {
            if (svgInert(node) || found.length >= 6) continue;
            if (node.closest('[data-role="background"]')) continue;
            const geometry = svgGeometry(root, node);
            if (!geometry) continue;
            const inCanvas = geometry.x >= -SVG_PAGE.tolerance && geometry.y >= -SVG_PAGE.tolerance
                && geometry.x + geometry.width <= SVG_PAGE.width + SVG_PAGE.tolerance
                && geometry.y + geometry.height <= SVG_PAGE.height + SVG_PAGE.tolerance;
            if (!inCanvas) {
                node.setAttribute('data-svg-issue', '');
                found.push(`${node.getAttribute('id') || node.localName} 超出画布`);
                continue;
            }
            if (node.localName !== 'text') continue;
            if (!node.closest('[data-role="footer"]')
                && (geometry.x < SVG_PAGE.left - SVG_PAGE.tolerance || geometry.x + geometry.width > SVG_PAGE.right + SVG_PAGE.tolerance
                    || geometry.y < SVG_PAGE.top - SVG_PAGE.tolerance || geometry.y + geometry.height > SVG_PAGE.bottom + SVG_PAGE.tolerance)) {
                node.setAttribute('data-svg-issue', '');
                found.push(`${node.getAttribute('id') || node.localName} 超出安全区`);
            } else if (svgFontSize(node, frame.contentWindow) < SVG_PAGE.fontFloor) {
                node.setAttribute('data-svg-issue', '');
                found.push(`${node.getAttribute('id') || node.localName} 字号低于 ${SVG_PAGE.fontFloor}`);
            }
        }
        issues.hidden = !found.length;
        issues.textContent = found.length ? `检查：${found.join('；')}` : '';
        issues.title = found.join('\n');
    }

    function afterMutation() {
        refreshOverlay();
        refreshInspector();
        refreshDiagnostics();
        setDirty(true);
    }

    function mutate(key, apply) {
        if (!root || !selected && key !== 'overlay') return;
        pushHistory(key);
        apply();
        afterMutation();
    }

    function rewrapText(value) {
        const textarea = inputs.content;
        svgApplyText(selected, frame.contentWindow, value === undefined ? textarea.value : value);
    }

    function setPaint(node, name, value) {
        svgSetAttribute(node, name, value);
    }

    function applyField(name, raw) {
        if (!selected || !root) return;
        const isColor = name === 'fill' || name === 'stroke';
        const value = isColor ? String(raw || '').trim() : parseFloat(raw);
        if (isColor ? !value : !Number.isFinite(value)) return;
        const geometry = svgGeometry(root, selected);
        const tag = selected.localName;
        mutate(`prop:${name}`, () => {
            if (name === 'x' && geometry) svgMove(selected, root, value - geometry.x, 0);
            else if (name === 'y' && geometry) svgMove(selected, root, 0, value - geometry.y);
            else if (name === 'w') svgResize(selected, root, {width: Math.max(1, value)});
            else if (name === 'h') svgResize(selected, root, {height: Math.max(1, value)});
            else if (name === 'boxw') {
                svgSetAttribute(selected, 'data-box-w', Math.max(40, Math.round(value)));
                rewrapText();
            } else if (name === 'r') svgSetAttribute(selected, 'r', Math.max(0.5, value));
            else if (name === 'rx' || name === 'ry') svgSetAttribute(selected, name, Math.max(0.5, value));
            else if (name === 'x1' || name === 'y1' || name === 'x2' || name === 'y2') svgSetAttribute(selected, name, value);
            else if (name === 'size') {
                svgSetAttribute(selected, 'font-size', Math.max(8, Math.min(512, value)));
                rewrapText();
            } else if (name === 'strokeWidth') svgSetAttribute(selected, 'stroke-width', Math.max(0, value));
            else if (name === 'radius') {
                svgSetAttribute(selected, 'rx', Math.max(0, value));
                svgSetAttribute(selected, 'ry', Math.max(0, value));
            } else if (name === 'opacity') svgSetAttribute(selected, 'opacity', Math.min(1, Math.max(0, value)));
            else if (name === 'fill') setPaint(selected, tag === 'use' ? 'color' : 'fill', value);
            else if (name === 'stroke') setPaint(selected, 'stroke', value);
        });
        if (name === 'fill' && tag === 'use') refreshInspector();
    }

    function bindField(name, event = 'input') {
        const input = inputs[name];
        input?.addEventListener(event, () => applyField(name, input.value));
    }

    ['x', 'y', 'w', 'h', 'boxw', 'r', 'rx', 'ry', 'x1', 'y1', 'x2', 'y2', 'size', 'strokeWidth', 'radius']
        .forEach(name => bindField(name));
    inputs.content.addEventListener('input', () => {
        if (!selected || selected.localName !== 'text') return;
        mutate('prop:content', () => rewrapText(inputs.content.value));
    });
    inputs.weight.addEventListener('change', () => {
        mutate('prop:weight', () => {
            svgSetAttribute(selected, 'font-weight', inputs.weight.value);
            rewrapText();
        });
    });
    inputs.fill.addEventListener('input', () => applyField('fill', inputs.fill.value));
    inputs.stroke.addEventListener('input', () => applyField('stroke', inputs.stroke.value));
    inputs.opacity.addEventListener('input', () => {
        opacityValue.textContent = `${Math.round(svgNum(inputs.opacity.value, 1) * 100)}%`;
        applyField('opacity', inputs.opacity.value);
    });
    inputs['no-fill'].addEventListener('change', () => {
        if (!selected) return;
        mutate('prop:no-fill', () => {
            const name = selected.localName === 'use' ? 'color' : 'fill';
            svgSetAttribute(selected, name, inputs['no-fill'].checked ? 'none' : inputs.fill.value);
        });
    });
    presets.addEventListener('click', event => {
        const swatch = event.target.closest('[data-swatch]');
        if (!swatch || !selected) return;
        inputs.fill.value = swatch.dataset.swatch;
        applyField('fill', swatch.dataset.swatch);
    });
    dialog.querySelectorAll('[data-anchor-value]').forEach(button => {
        button.addEventListener('click', () => {
            if (!selected || selected.localName !== 'text') return;
            mutate(`anchor:${button.dataset.anchorValue}`, () => {
                svgSetAttribute(selected, 'text-anchor', button.dataset.anchorValue);
                rewrapText();
            });
            refreshInspector();
        });
    });
    dialog.querySelector('[data-align]').addEventListener('click', event => {
        const button = event.target.closest('[data-align-x], [data-align-y]');
        if (!button || !selected) return;
        const geometry = svgGeometry(root, selected);
        if (!geometry) return;
        mutate(`align:${button.dataset.alignX || button.dataset.alignY}`, () => {
            if (button.dataset.alignX === 'left') svgMove(selected, root, SVG_PAGE.left - geometry.x, 0);
            else if (button.dataset.alignX === 'right') svgMove(selected, root, SVG_PAGE.right - (geometry.x + geometry.width), 0);
            else if (button.dataset.alignX === 'center') svgMove(selected, root, (SVG_PAGE.left + SVG_PAGE.right) / 2 - (geometry.x + geometry.width / 2), 0);
            else if (button.dataset.alignY === 'top') svgMove(selected, root, 0, SVG_PAGE.top - geometry.y);
            else if (button.dataset.alignY === 'bottom') svgMove(selected, root, 0, SVG_PAGE.bottom - (geometry.y + geometry.height));
            else if (button.dataset.alignY === 'middle') svgMove(selected, root, 0, (SVG_PAGE.top + SVG_PAGE.bottom) / 2 - (geometry.y + geometry.height / 2));
        });
    });

    // ---------- 元素操作 ----------
    function elementAction(action) {
        if (!selected || !root) return;
        if (action === 'delete') mutate('delete', () => {
            const parent = selected.parentElement;
            selected.remove();
            selectNode(parent && parent !== root ? parent : null);
            buildLayers();
        });
        else if (action === 'duplicate') mutate('duplicate', () => {
            const clone = selected.cloneNode(true);
            renameIds(clone);
            clone.removeAttribute('data-svg-selected');
            clone.removeAttribute('data-svg-hover');
            clone.removeAttribute('data-svg-issue');
            svgPrepend(clone, 'translate(16 16)');
            selected.after(clone);
            buildLayers();
            selectNode(clone);
        });
        else if (action === 'raise' || action === 'lower') mutate(action, () => {
            const siblings = Array.from(selected.parentElement.children).filter(node => !node.hasAttribute('data-svg-overlay'));
            const position = siblings.indexOf(selected);
            const target = action === 'raise' ? siblings[position + 1] : siblings[position - 1];
            if (!target) return;
            if (action === 'raise') target.after(selected);
            else target.before(selected);
            buildLayers();
        });
        if (selected) selectNode(selected);
        refreshInspector();
    }

    function renameIds(node) {
        const rename = element => {
            const id = element.getAttribute('id');
            if (id) element.setAttribute('id', `${id}-c${Math.random().toString(36).slice(2, 6)}`);
        };
        rename(node);
        node.querySelectorAll('[id]').forEach(rename);
    }

    function nudge(key, step) {
        if (!selected) return;
        const delta = {
            arrowleft: [-1, 0], arrowright: [1, 0], arrowup: [0, -1], arrowdown: [0, 1]
        }[key];
        if (!delta) return;
        mutate(`nudge:${key}:${step}`, () => svgMove(selected, root, delta[0] * step, delta[1] * step));
    }

    dialog.querySelectorAll('[data-action]').forEach(button => {
        button.addEventListener('click', () => elementAction(button.dataset.action));
    });

    // ---------- 画布交互 ----------
    const HINT_STYLE = `
        .svg-selection{fill:none;stroke:#0ea5e9;stroke-width:1.5;stroke-dasharray:6 4}
        .svg-handle{fill:#fff;stroke:#0ea5e9;stroke-width:1.5;pointer-events:all}
        .svg-handle[data-svg-handle="nw"],.svg-handle[data-svg-handle="se"]{cursor:nwse-resize}
        .svg-handle[data-svg-handle="ne"],.svg-handle[data-svg-handle="sw"]{cursor:nesw-resize}
        [data-svg-overlay]{pointer-events:none}
        [data-svg-hover]{outline:1.5px dashed #2563eb;outline-offset:2px;cursor:move}
        [data-svg-issue]{outline:1.5px dashed #ef4444;outline-offset:3px}
        svg{touch-action:none;user-select:none}`;

    function pickTarget(event) {
        const node = event.target?.closest?.(SVG_PAGE.selectable);
        if (!node || node === root || svgInert(node)) return null;
        if (!event.altKey && node.closest('[data-role="background"]')) return null;
        if (!node.getAttribute('data-role') && event.altKey && node.parentElement?.localName === 'g') return node.parentElement;
        return node;
    }

    function showBadge(text, event) {
        const rect = frame.getBoundingClientRect();
        badge.hidden = false;
        badge.textContent = text;
        badge.style.left = `${rect.left + event.clientX * zoom + 14}px`;
        badge.style.top = `${rect.top + event.clientY * zoom + 14}px`;
    }

    function startDrag(node, event) {
        drag = {
            node,
            inverse: node.parentElement.getScreenCTM().inverse(),
            start: svgPointIn(node.parentElement, event.clientX, event.clientY),
            before: node.getAttribute('transform') || '',
            pushed: false
        };
    }

    function startResize(handle, event) {
        const geometry = svgGeometry(root, selected);
        if (!geometry) return;
        const corner = handle.getAttribute('data-svg-handle');
        resizing = {
            corner,
            anchor: {
                x: corner.includes('w') ? geometry.x + geometry.width : geometry.x,
                y: corner.includes('n') ? geometry.y + geometry.height : geometry.y
            },
            ratio: geometry.width ? geometry.height / geometry.width : 1,
            geometry,
            pushed: false
        };
    }

    function bindFrame() {
        document_ = frame.contentDocument;
        if (!document_) return;
        root = document_.querySelector('svg');
        if (!root) {
            setStatus('未找到 SVG 页面', 'error');
            return;
        }
        const style = document_.createElement('style');
        style.textContent = HINT_STYLE;
        document_.head.appendChild(style);
        savedMarkup = currentMarkup();
        buildLayers();
        selectNode(null);
        refreshDiagnostics();
        setDirty(false);

        document_.addEventListener('pointerdown', event => {
            if (event.button !== 0) return;
            const handle = event.target?.closest?.('[data-svg-handle]');
            if (handle) {
                event.preventDefault();
                startResize(handle, event);
                return;
            }
            const node = pickTarget(event);
            if (!node) {
                selectNode(null);
                return;
            }
            event.preventDefault();
            selectNode(node);
            startDrag(node, event);
        });

        document_.addEventListener('pointerover', event => {
            if (drag || resizing) return;
            const node = pickTarget(event);
            if (node && node !== selected) setHover(node);
        });

        document_.addEventListener('pointerout', event => {
            if (!drag && !resizing && !event.relatedTarget) setHover(null);
        });

        document_.addEventListener('pointermove', event => {
            if (resizing && selected) {
                const point = svgPointIn(root, event.clientX, event.clientY);
                let {x, y} = point;
                if (event.altKey) { x = Math.round(x / 8) * 8; y = Math.round(y / 8) * 8; }
                const width = Math.max(1, Math.abs(x - resizing.anchor.x));
                let height = Math.max(1, Math.abs(y - resizing.anchor.y));
                if (selected.localName === 'image') height = Math.max(1, width * resizing.ratio);
                if (!resizing.pushed) {
                    pushHistory(`resize:${resizing.corner}`);
                    resizing.pushed = true;
                }
                svgResize(selected, root, {
                    width,
                    height,
                    left: Math.min(x, resizing.anchor.x),
                    top: Math.min(y, resizing.anchor.y)
                });
                showBadge(`${Math.round(width)} × ${Math.round(height)}`, event);
                refreshOverlay();
                refreshInspector({layout: false});
                setDirty(true);
                return;
            }
            if (!drag) return;
            const point = svgPointIn(drag.node.parentElement, event.clientX, event.clientY);
            let dx = point.x - drag.start.x, dy = point.y - drag.start.y;
            if (event.shiftKey) {
                if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0;
            }
            if (event.altKey) { dx = Math.round(dx / 8) * 8; dy = Math.round(dy / 8) * 8; }
            if (!drag.pushed) {
                pushHistory('drag');
                drag.pushed = true;
            }
            if (Math.abs(dx) < 0.05 && Math.abs(dy) < 0.05) drag.node.setAttribute('transform', drag.before);
            else drag.node.setAttribute('transform', `translate(${svgRound(dx)} ${svgRound(dy)}) ${drag.before}`.trim());
            const geometry = svgGeometry(root, drag.node);
            if (geometry) showBadge(`x ${Math.round(geometry.x)} · y ${Math.round(geometry.y)}`, event);
            refreshOverlay();
            refreshInspector({layout: false});
            setDirty(true);
        });

        const endPointer = () => {
            if (!drag && !resizing) return;
            const wasDragging = Boolean(drag);
            drag = null;
            resizing = null;
            badge.hidden = true;
            if (wasDragging) setStatus(`已选择 ${elementName.textContent}`);
            refreshOverlay();
            refreshInspector();
            refreshHistoryButtons();
        };
        document_.addEventListener('pointerup', endPointer);
        document_.addEventListener('pointercancel', endPointer);
        document_.addEventListener('dblclick', event => {
            const node = pickTarget(event);
            if (node && node.localName === 'text') {
                selectNode(node);
                inputs.content.focus();
                inputs.content.select();
            }
        });
        document_.addEventListener('keydown', handleKeydown);
        document_.addEventListener('wheel', event => {
            if (!event.ctrlKey) return;
            event.preventDefault();
            setZoom(zoom * (event.deltaY < 0 ? 1.1 : 1 / 1.1));
        }, {passive: false});
    }

    // ---------- 缩放 ----------
    function fitZoom() {
        const width = stage.clientWidth - 48, height = stage.clientHeight - 48;
        return Math.max(0.2, Math.min(1.5, Math.min(width / SVG_PAGE.width, height / SVG_PAGE.height)));
    }

    function setZoom(next, options = {}) {
        const previous = zoom;
        zoom = Math.max(0.2, Math.min(2, next));
        fitMode = Boolean(options.fit);
        frame.style.transform = `scale(${zoom})`;
        paper.style.width = `${SVG_PAGE.width * zoom}px`;
        paper.style.height = `${SVG_PAGE.height * zoom}px`;
        pick('[data-zoom-label]').textContent = fitMode ? '适应' : `${Math.round(zoom * 100)}%`;
        if (previous && Math.abs(previous - zoom) > 1e-3 && !options.keepCenter) {
            const ratio = zoom / previous;
            stage.scrollLeft = (stage.scrollLeft + stage.clientWidth / 2) * ratio - stage.clientWidth / 2;
            stage.scrollTop = (stage.scrollTop + stage.clientHeight / 2) * ratio - stage.clientHeight / 2;
        }
        refreshOverlay();
    }

    dialog.querySelector('[data-zoom]').parentElement.addEventListener('click', event => {
        const button = event.target.closest('[data-zoom]');
        if (!button) return;
        if (button.dataset.zoom === 'fit') setZoom(fitZoom(), {fit: true});
        else if (button.dataset.zoom === 'in') setZoom(zoom * 1.2);
        else setZoom(zoom / 1.2);
    });

    const observer = new ResizeObserver(() => {
        if (fitMode) setZoom(fitZoom(), {fit: true, keepCenter: true});
    });
    observer.observe(stage);

    // ---------- 撤销 / 重做 ----------
    function restore(markupText) {
        if (!document_ || !root) return;
        const parsed = new DOMParser().parseFromString(markupText, 'image/svg+xml');
        const restored = document_.importNode(parsed.documentElement, true);
        root.replaceWith(restored);
        root = restored;
        selected = null;
        hovered = null;
        buildLayers();
        selectNode(null);
        refreshDiagnostics();
        setDirty(currentMarkup() !== savedMarkup);
    }

    undoButton.addEventListener('click', () => {
        if (!history.length || !root) return;
        future.push(currentMarkup());
        restore(history.pop());
        refreshHistoryButtons();
        setStatus('已撤销');
    });

    redoButton.addEventListener('click', () => {
        if (!future.length || !root) return;
        history.push(currentMarkup());
        restore(future.pop());
        refreshHistoryButtons();
        setStatus('已重做');
    });

    // ---------- 保存 / 关闭 ----------
    async function save() {
        if (!root) return;
        const button = pick('[data-save]');
        button.disabled = true;
        setStatus('正在保存…');
        try {
            const markup = currentMarkup();
            await saveSvgSlideContent(index, markup, slidesData[index].html_content);
            savedMarkup = markup;
            setDirty(false);
            setStatus('已保存', 'saved');            notify('SVG 页面已保存', 'success');
        } catch (error) {
            setStatus(error.message, 'error');
        } finally {
            button.disabled = false;
        }
    }

    function requestClose() {
        if (dirty) {
            confirmBar.dataset.requested = '1';
            confirmBar.classList.add('is-visible');
            return;
        }
        close();
    }

    function close() {
        observer.disconnect();
        dialog.close();
    }

    pick('[data-save]').addEventListener('click', save);
    pick('[data-close]').addEventListener('click', requestClose);
    pick('[data-discard]').addEventListener('click', () => { dirty = false; close(); });
    pick('[data-keep]').addEventListener('click', () => {
        confirmBar.dataset.requested = '0';
        confirmBar.classList.remove('is-visible');
    });

    function handleKeydown(event) {
        if (!dialog.open) return;
        const key = (event.key || '').toLowerCase();
        const editing = /^(input|textarea|select)$/i.test(event.target?.tagName || '');
        const meta = event.ctrlKey || event.metaKey;
        if (meta && key === 's') { event.preventDefault(); save(); return; }
        if (meta && key === 'z') { event.preventDefault(); (event.shiftKey ? redoButton : undoButton).click(); return; }
        if (meta && key === 'y') { event.preventDefault(); redoButton.click(); return; }
        if (editing) return;
        if (meta && key === 'd') { event.preventDefault(); elementAction('duplicate'); return; }
        if (key === 'escape') {
            if (selected) selectNode(null); else requestClose();
            return;
        }
        if (key === 'delete' || key === 'backspace') { event.preventDefault(); elementAction('delete'); return; }
        if (key.startsWith('arrow')) { event.preventDefault(); nudge(key, event.shiftKey ? 10 : 1); }
    }

    // 监听在 document 上：图层重建、画布内操作都不会把快捷键弄丢
    document.addEventListener('keydown', handleKeydown);
    dialog.addEventListener('cancel', event => {
        event.preventDefault();
        requestClose();
    });
    dialog.addEventListener('close', () => {
        document.removeEventListener('keydown', handleKeydown);
        observer.disconnect();
        dialog.remove();
    });

    frame.srcdoc = slidesData[index].html_content;
    frame.addEventListener('load', bindFrame);
    dialog.addEventListener('click', event => {
        if (event.target === dialog) requestClose();
    });    setZoom(fitZoom(), {fit: true, keepCenter: true});
    setStatus('未选择元素');
    refreshHistoryButtons();
}
