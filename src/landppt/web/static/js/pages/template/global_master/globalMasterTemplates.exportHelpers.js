let domToPptxLoadPromise = null;
const DOM_TO_PPTX_BUNDLE_PATH = '/static/js/dom-to-pptx.bundle.js';

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function sanitizeFileName(name, fallback = 'template') {
    const safe = String(name || '')
        .replace(/[\\/:*?"<>|]+/g, '_')
        .replace(/\s+/g, ' ')
        .trim();
    return safe || fallback;
}

function setButtonLoadingState(button, isLoading, loadingLabel = '处理中...') {
    if (!button) return;

    if (isLoading) {
        if (!button.dataset.originalHtml) {
            button.dataset.originalHtml = button.innerHTML;
        }
        button.disabled = true;
        button.classList.add('disabled');
        button.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${loadingLabel}`;
        return;
    }

    button.disabled = false;
    button.classList.remove('disabled');
    if (button.dataset.originalHtml) {
        button.innerHTML = button.dataset.originalHtml;
        delete button.dataset.originalHtml;
    }
}

function isDomToPptxReady() {
    return Boolean(window.domToPptx && typeof window.domToPptx.exportToPptx === 'function');
}

async function loadDomToPptxBundle(force = false) {
    if (!force && isDomToPptxReady()) {
        return window.domToPptx;
    }
    if (domToPptxLoadPromise) {
        return domToPptxLoadPromise;
    }

    domToPptxLoadPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = `${DOM_TO_PPTX_BUNDLE_PATH}?ts=${Date.now()}`;
        script.async = true;

        let settled = false;
        const finish = (ok, err) => {
            if (settled) return;
            settled = true;
            domToPptxLoadPromise = null;
            if (ok) resolve(window.domToPptx);
            else reject(err || new Error('加载PPTX导出库失败'));
        };

        script.onload = () => {
            if (isDomToPptxReady()) {
                finish(true);
                return;
            }
            finish(false, new Error('PPTX导出库加载完成但不可用'));
        };
        script.onerror = () => finish(false, new Error('无法加载 dom-to-pptx.bundle.js'));

        document.head.appendChild(script);
        setTimeout(() => finish(false, new Error('加载PPTX导出库超时')), 12000);
    });

    return domToPptxLoadPromise;
}

async function ensureDomToPptxReady() {
    if (isDomToPptxReady()) {
        return window.domToPptx;
    }
    return loadDomToPptxBundle(true);
}

function ensureHtmlDocument(htmlTemplate) {
    let html = String(htmlTemplate || '');
    if (!html.includes('<html')) {
        html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title }}</title>
    <style>html,body{margin:0;padding:0;width:1280px;height:720px;overflow:hidden;} body{background:#fff;}</style>
</head>
<body>${html}</body>
</html>`;
    }
    return html;
}

function buildTemplatePptxSampleSlides(templateName, includeTransition = false) {
    const slides = [
        {
            kind: 'title',
            pageTitle: `${templateName} 模板预览`,
            mainHeading: `${templateName} 标题页`,
            subtitle: 'PPTX模板导出示例',
            pageContent: `
                <div style="display:flex;flex-direction:column;gap:14px;">
                    <div style="font-size:1.15em;font-weight:600;">标题页 / Cover Slide</div>
                    <div>用于展示主题、副标题、演讲人信息与日期。</div>
                    <div style="opacity:.85;">导出时间：${new Date().toLocaleString()}</div>
                </div>
            `,
            notes: '标题页模板（封面页）'
        },
        {
            kind: 'agenda',
            pageTitle: '目录页',
            mainHeading: '目录页',
            subtitle: 'Agenda / 目录结构',
            pageContent: `
                <div style="display:flex;flex-direction:column;gap:12px;">
                    <div style="font-weight:600;">本模板目录页示例</div>
                    <ol style="margin:0;padding-left:1.4em;line-height:1.8;">
                        <li>项目背景与目标</li>
                        <li>现状分析与关键发现</li>
                        <li>方案设计与实施路径</li>
                        <li>结果评估与总结建议</li>
                    </ol>
                </div>
            `,
            notes: '目录页模板（agenda）'
        }
    ];

    if (includeTransition) {
        slides.push({
            kind: 'transition',
            pageTitle: '过渡页',
            mainHeading: '章节过渡页',
            subtitle: 'Transition Slide',
            pageContent: `
                <div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:1.25em;font-weight:700;">
                    第二部分 · 方案设计与执行路径
                </div>
            `,
            notes: '过渡页模板（可选）'
        });
    }

    slides.push(
        {
            kind: 'content',
            pageTitle: '内容页',
            mainHeading: '内容页示例',
            subtitle: 'Content Slide',
            pageContent: `
                <div style="display:grid;grid-template-columns:1.2fr .8fr;gap:16px;align-items:start;">
                    <div>
                        <div style="font-weight:600;margin-bottom:8px;">核心结论</div>
                        <ul style="margin:0;padding-left:1.2em;line-height:1.7;">
                            <li>建议采用分阶段推进策略，先验证后扩展。</li>
                            <li>通过标准化模板降低设计与制作成本。</li>
                            <li>统一视觉规范，提升输出一致性与品牌感。</li>
                        </ul>
                    </div>
                    <div style="border:1px dashed rgba(128,128,128,.45);border-radius:12px;padding:12px;">
                        <div style="font-weight:600;margin-bottom:6px;">数据占位区</div>
                        <div style="opacity:.85;font-size:.95em;line-height:1.6;">
                            可替换为图表、指标卡片、流程图或图片内容。
                        </div>
                    </div>
                </div>
            `,
            notes: '内容页模板（content）'
        },
        {
            kind: 'summary',
            pageTitle: '总结页',
            mainHeading: '总结与下一步',
            subtitle: 'Summary / Conclusion',
            pageContent: `
                <div style="display:flex;flex-direction:column;gap:12px;">
                    <div style="font-weight:600;">总结页示例</div>
                    <ul style="margin:0;padding-left:1.2em;line-height:1.8;">
                        <li>模板结构已覆盖标题页、目录页、内容页、总结页。</li>
                        <li>可选增加过渡页，适配章节型汇报场景。</li>
                        <li>建议后续补充图表页、数据看板页等扩展版式。</li>
                    </ul>
                </div>
            `,
            notes: '总结页模板（conclusion / summary）'
        }
    );

    return slides;
}

function replaceTemplatePlaceholders(htmlTemplate, variables) {
    const aliasMap = {
        page_title: ['page_title', 'title', 'slide_title', 'topic_title'],
        main_heading: ['main_heading', 'heading', 'headline', 'main_title'],
        page_content: ['page_content', 'content', 'slide_content', 'body_content'],
        subtitle: ['subtitle', 'sub_title', 'subheading'],
        current_page_number: ['current_page_number', 'page_number', 'slide_number'],
        total_page_count: ['total_page_count', 'total_pages', 'total_slides']
    };

    const expanded = { ...variables };
    Object.entries(aliasMap).forEach(([canonical, aliases]) => {
        const value = variables[canonical];
        if (value === undefined || value === null) return;
        aliases.forEach((key) => { expanded[key] = value; });
    });

    return String(htmlTemplate || '').replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (match, key) => {
        if (Object.prototype.hasOwnProperty.call(expanded, key)) {
            const value = expanded[key];
            return value === null || value === undefined ? '' : String(value);
        }

        const keyLower = String(key || '').toLowerCase();
        if (keyLower.includes('page') && keyLower.includes('title')) {
            return String(expanded.page_title || '');
        }
        if (keyLower.includes('heading') || keyLower.includes('title')) {
            return String(expanded.main_heading || expanded.page_title || '');
        }
        if (keyLower.includes('content')) {
            return String(expanded.page_content || '');
        }
        if (keyLower.includes('subtitle')) {
            return String(expanded.subtitle || '');
        }
        if (keyLower.includes('current') && keyLower.includes('page')) {
            return String(expanded.current_page_number || '');
        }
        if ((keyLower.includes('total') && keyLower.includes('page')) || keyLower.includes('slides')) {
            return String(expanded.total_page_count || '');
        }

        return '';
    });
}

function renderTemplateSampleHtml(htmlTemplate, sampleSlide, pageNumber, totalPages) {
    const source = ensureHtmlDocument(htmlTemplate);
    return replaceTemplatePlaceholders(source, {
        page_title: sampleSlide.pageTitle || sampleSlide.mainHeading || '模板示例',
        main_heading: sampleSlide.mainHeading || sampleSlide.pageTitle || '模板示例',
        subtitle: sampleSlide.subtitle || '',
        page_content: sampleSlide.pageContent || '',
        current_page_number: pageNumber,
        total_page_count: totalPages
    });
}

async function loadHtmlIntoIframe(iframe, html) {
    return new Promise((resolve, reject) => {
        let done = false;
        const finish = (ok, err) => {
            if (done) return;
            done = true;
            iframe.onload = null;
            iframe.onerror = null;
            if (ok) resolve();
            else reject(err || new Error('iframe加载失败'));
        };

        iframe.onload = () => finish(true);
        iframe.onerror = () => finish(false, new Error('模板渲染失败'));
        iframe.srcdoc = html;

        setTimeout(() => finish(false, new Error('模板渲染超时')), 12000);
    });
}

async function waitForFontsReady(doc, timeoutMs = 1500) {
    if (!doc?.fonts?.ready) return;
    try {
        await Promise.race([
            doc.fonts.ready.catch(() => null),
            sleep(timeoutMs)
        ]);
    } catch (_) {
        // ignore
    }
}

async function waitForImagesReady(doc, timeoutMs = 2800) {
    if (!doc) return;
    const imgs = Array.from(doc.images || []);
    const pending = imgs.filter((img) => !img.complete);
    if (pending.length === 0) return;

    await Promise.race([
        Promise.allSettled(
            pending.map((img) => new Promise((resolve) => {
                const done = () => {
                    img.removeEventListener('load', done);
                    img.removeEventListener('error', done);
                    resolve(true);
                };
                img.addEventListener('load', done, { once: true });
                img.addEventListener('error', done, { once: true });
            }))
        ),
        sleep(timeoutMs)
    ]);
}

function isCanvasPainted(canvas) {
    if (!canvas) return true;
    if (canvas.width <= 1 || canvas.height <= 1) return false;
    try {
        const dataUrl = canvas.toDataURL('image/png');
        if (dataUrl && dataUrl.length > 1800) return true;
    } catch (_) {
        return true;
    }
    return false;
}

async function waitForCanvasesReady(doc, timeoutMs = 2200) {
    if (!doc) return;
    const canvases = Array.from(doc.querySelectorAll('canvas'));
    if (canvases.length === 0) return;
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        if (canvases.every(isCanvasPainted)) return;
        await sleep(120);
    }
}

async function waitForAnimationFrames(win, count = 2) {
    if (!win || typeof win.requestAnimationFrame !== 'function') {
        await sleep(count * 34);
        return;
    }
    for (let i = 0; i < count; i += 1) {
        await new Promise((resolve) => win.requestAnimationFrame(() => resolve()));
    }
}

async function waitForIframeVisualReady(iframe) {
    const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
    const iframeWin = iframe.contentWindow;
    if (!iframeDoc || !iframeDoc.body) {
        throw new Error('无法读取模板渲染内容');
    }

    await waitForFontsReady(iframeDoc, 1500);
    await waitForImagesReady(iframeDoc, 3200);
    await waitForCanvasesReady(iframeDoc, 2600);
    await waitForAnimationFrames(iframeWin, 2);
    await sleep(250);

    try {
        const animations = typeof iframeDoc.getAnimations === 'function'
            ? iframeDoc.getAnimations({ subtree: true })
            : [];
        animations.forEach((animation) => {
            try {
                if (animation && typeof animation.finish === 'function') {
                    animation.finish();
                }
            } catch (_) {
                // ignore
            }
        });
    } catch (_) {
        // ignore
    }

    await waitForAnimationFrames(iframeWin, 1);
}


export {
    sleep,
    sanitizeFileName,
    setButtonLoadingState,
    isDomToPptxReady,
    loadDomToPptxBundle,
    ensureDomToPptxReady,
    ensureHtmlDocument,
    buildTemplatePptxSampleSlides,
    replaceTemplatePlaceholders,
    renderTemplateSampleHtml,
    loadHtmlIntoIframe,
    waitForFontsReady,
    waitForImagesReady,
    isCanvasPainted,
    waitForCanvasesReady,
    waitForAnimationFrames,
    waitForIframeVisualReady,
};
