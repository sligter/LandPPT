let domToPptxLoadPromise = null;
const DOM_TO_PPTX_BUNDLE_PATH = '/static/js/dom-to-pptx.bundle.js';
const DOM_TO_PPTX_BUNDLE_VERSION = '20260911-svg-native-v1';
const DOM_TO_PPTX_EXPECTED_PATCH_VERSION = '2026-09-11-svg-native-v1';

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
    const instance = window.domToPptx;
    if (!instance || typeof instance.exportToPptx !== 'function') return false;
    return String(instance.__landpptPatchVersion || '').trim() === DOM_TO_PPTX_EXPECTED_PATCH_VERSION;
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
        script.src = `${DOM_TO_PPTX_BUNDLE_PATH}?v=${encodeURIComponent(DOM_TO_PPTX_BUNDLE_VERSION)}&ts=${Date.now()}`;
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
