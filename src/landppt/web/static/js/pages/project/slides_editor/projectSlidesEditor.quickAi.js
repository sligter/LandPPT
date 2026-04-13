// ==================== 增强快速编辑功能 ====================

// 撤销/重做系统
let undoStack = [];
let redoStack = [];
const MAX_UNDO_STEPS = 50;
let selectedQuickEditElement = null;

// 快捷 AI 元素编辑（浮窗）
let quickAiEditSending = false;
let quickAiTargetElementId = null;
let quickAiPopoverDragging = false;
let quickAiPopoverDragOffsetX = 0;
let quickAiPopoverDragOffsetY = 0;
let quickAiPopoverMinimized = false;
let quickAiVisionEnabled = false;

function getQuickAiPopoverEl() {
    return document.getElementById('quickAiEditPopover');
}

function getQuickAiInputEl() {
    return document.getElementById('quickAiEditInput');
}

function getQuickAiStatusEl() {
    return document.getElementById('quickAiEditStatus');
}

function getQuickAiMinBtnEl() {
    return document.getElementById('quickAiEditPopoverMinBtn');
}

function getQuickAiVisionBtnEl() {
    return document.getElementById('quickAiVisionToggleBtn');
}

function setQuickAiStatus(text) {
    const statusEl = getQuickAiStatusEl();
    if (!statusEl) return;
    statusEl.textContent = text || '';
    if (text) {
        statusEl.classList.add('visible');
    } else {
        statusEl.classList.remove('visible');
    }
}

function setQuickAiSendingState(sending) {
    quickAiEditSending = !!sending;
    const sendBtn = document.getElementById('quickAiEditSendBtn');
    const inputEl = getQuickAiInputEl();
    const pop = getQuickAiPopoverEl();
    const statusEl = getQuickAiStatusEl();
    if (sendBtn) sendBtn.disabled = quickAiEditSending;
    if (inputEl) inputEl.disabled = quickAiEditSending;
    if (pop) pop.classList.toggle('loading', quickAiEditSending);
    if (statusEl) statusEl.classList.toggle('loading', quickAiEditSending);
}

function setQuickAiVisionEnabledState(enabled, options = {}) {
    const { persist = true } = options || {};
    quickAiVisionEnabled = !!enabled;

    const btn = getQuickAiVisionBtnEl();
    if (btn) {
        btn.classList.toggle('active', quickAiVisionEnabled);
        btn.title = quickAiVisionEnabled
            ? '关闭视觉参考（不再发送所选元素截图）'
            : '开启视觉参考（将发送所选元素截图）';
    }

    if (persist) {
        try {
            localStorage.setItem('quickAiVisionEnabled', JSON.stringify(quickAiVisionEnabled));
        } catch (e) { }
    }
}

function restoreQuickAiVisionEnabledState() {
    try {
        const raw = localStorage.getItem('quickAiVisionEnabled');
        if (!raw) return;
        const value = JSON.parse(raw);
        setQuickAiVisionEnabledState(!!value, { persist: false });
    } catch (e) { }
}

async function captureQuickAiElementScreenshot(element) {
    try {
        const slideFrame = document.getElementById('slideFrame');
        if (!slideFrame || !element) return null;

        const iframeWindow = slideFrame.contentWindow;
        const iframeDoc = slideFrame.contentDocument || iframeWindow?.document;
        if (!iframeWindow || !iframeDoc) return null;

        async function ensureHtml2CanvasInIframe() {
            if (iframeWindow.html2canvas) return;

            // 如果主页面已加载 html2canvas，仍需在 iframe 内加载一份，避免跨 document 节点渲染异常/空白
            return new Promise((resolve, reject) => {
                try {
                    if (iframeWindow.html2canvas) {
                        resolve();
                        return;
                    }

                    const existing = iframeDoc.getElementById('html2canvasInjectedScript');
                    if (existing) {
                        existing.addEventListener('load', () => resolve(), { once: true });
                        existing.addEventListener('error', () => reject(new Error('html2canvas iframe load failed')), { once: true });
                        // 超时保护
                        setTimeout(() => resolve(), 1500);
                        return;
                    }

                    const script = iframeDoc.createElement('script');
                    script.id = 'html2canvasInjectedScript';
                    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
                    script.onload = () => resolve();
                    script.onerror = () => reject(new Error('html2canvas iframe load failed'));
                    (iframeDoc.head || iframeDoc.documentElement || iframeDoc.body).appendChild(script);
                    setTimeout(() => resolve(), 1500);
                } catch (e) {
                    reject(e);
                }
            });
        }

        // 等待 iframe 文档与资源尽可能加载完毕，避免截图模糊/比例异常（图片/字体未就绪）
        await new Promise(resolve => {
            if (iframeDoc.readyState === 'complete') {
                resolve();
                return;
            }
            const onLoad = () => resolve();
            slideFrame.addEventListener('load', onLoad, { once: true });
            setTimeout(resolve, 1500);
        });

        // 等待字体加载
        try {
            if (iframeDoc.fonts && iframeDoc.fonts.ready) {
                await Promise.race([
                    iframeDoc.fonts.ready.catch(() => null),
                    new Promise(resolve => setTimeout(resolve, 1200))
                ]);
            }
        } catch (e) {
            // ignore
        }

        // 等待图片加载（尽力而为：跨域图片可能永远加载失败）
        try {
            const pendingImgs = Array.from(iframeDoc.images || []).filter(img => !img.complete);
            if (pendingImgs.length > 0) {
                await Promise.race([
                    new Promise(resolve => {
                        let remaining = pendingImgs.length;
                        const done = () => {
                            remaining -= 1;
                            if (remaining <= 0) resolve();
                        };
                        pendingImgs.forEach(img => {
                            img.addEventListener('load', done, { once: true });
                            img.addEventListener('error', done, { once: true });
                        });
                    }),
                    new Promise(resolve => setTimeout(resolve, 1500))
                ]);
            }
        } catch (e) {
            // ignore
        }

        // 给浏览器一次渲染机会
        try {
            await new Promise(resolve => iframeWindow.requestAnimationFrame(() => iframeWindow.requestAnimationFrame(resolve)));
        } catch (e) {
            // ignore
        }

        // 确保在 iframe 内有 html2canvas，避免跨 document 捕获出现“只剩背景/空白”
        await ensureHtml2CanvasInIframe();
        if (!iframeWindow.html2canvas) {
            return null;
        }

        const scaleFactor = Math.max(1, Math.min(2, (window.devicePixelRatio || 1)));

        function toJpegDataUrlWithMaxSide(srcCanvas, maxSide = 900) {
            if (!srcCanvas) return null;
            try {
                const w = Math.max(1, Math.round(srcCanvas.width || 0));
                const h = Math.max(1, Math.round(srcCanvas.height || 0));
                if (w <= 2 || h <= 2) return null;

                const maxCurrent = Math.max(w, h);
                if (maxCurrent > maxSide) {
                    const ratio = maxSide / maxCurrent;
                    const resized = iframeDoc.createElement('canvas');
                    resized.width = Math.max(1, Math.round(w * ratio));
                    resized.height = Math.max(1, Math.round(h * ratio));
                    const rctx = resized.getContext('2d');
                    if (!rctx) return null;
                    rctx.imageSmoothingEnabled = true;
                    rctx.imageSmoothingQuality = 'high';
                    rctx.drawImage(srcCanvas, 0, 0, resized.width, resized.height);
                    return resized.toDataURL('image/jpeg', 0.86);
                }

                return srcCanvas.toDataURL('image/jpeg', 0.86);
            } catch (e) {
                return null;
            }
        }

        // 优先直接渲染“所选元素”本身（在 iframe 上下文内），避免整页裁剪出现坐标/变换偏差导致只截到背景
        const rect = element.getBoundingClientRect();
        if (!rect || rect.width <= 2 || rect.height <= 2) return null;

        try {
            const elementCanvas = await iframeWindow.html2canvas(element, {
                scale: scaleFactor,
                useCORS: true,
                allowTaint: true,
                backgroundColor: '#ffffff',
                logging: false,
                windowWidth: Math.max(1, Math.round(iframeWindow.innerWidth || 1280)),
                windowHeight: Math.max(1, Math.round(iframeWindow.innerHeight || 720)),
                scrollX: -(iframeWindow.scrollX || 0),
                scrollY: -(iframeWindow.scrollY || 0),
            });

            const direct = toJpegDataUrlWithMaxSide(elementCanvas);
            if (direct) return direct;
        } catch (e) {
            // fallback below
        }

        // 兜底：基于“整页渲染后裁剪选中元素区域”
        const pad = 8;
        const slideWidth = Math.max(1, Math.round(iframeWindow.innerWidth || 1280));
        const slideHeight = Math.max(1, Math.round(iframeWindow.innerHeight || 720));

        const captureRoot = (() => {
            const candidates = [
                iframeDoc.querySelector('#slide'),
                iframeDoc.querySelector('.slide'),
                iframeDoc.querySelector('.ppt-slide'),
                iframeDoc.querySelector('.pptx-slide'),
                iframeDoc.querySelector('.slide-container'),
                iframeDoc.body,
                iframeDoc.documentElement,
            ].filter(Boolean);

            let best = candidates[0] || iframeDoc.documentElement || iframeDoc.body;
            let bestArea = 0;
            candidates.forEach(el => {
                try {
                    const r = el.getBoundingClientRect();
                    const area = Math.max(0, r.width) * Math.max(0, r.height);
                    if (area > bestArea) {
                        bestArea = area;
                        best = el;
                    }
                } catch (e) { }
            });
            return best || iframeDoc.documentElement || iframeDoc.body;
        })();

        const rootRect = captureRoot?.getBoundingClientRect?.() || { left: 0, top: 0 };

        const fullCanvas = await iframeWindow.html2canvas(captureRoot || iframeDoc.documentElement || iframeDoc.body, {
            width: slideWidth,
            height: slideHeight,
            windowWidth: slideWidth,
            windowHeight: slideHeight,
            scale: scaleFactor,
            useCORS: true,
            allowTaint: true,
            backgroundColor: '#ffffff',
            logging: false,
            scrollX: -(iframeWindow.scrollX || 0),
            scrollY: -(iframeWindow.scrollY || 0),
        });

        const sx = Math.max(0, (rect.left - rootRect.left - pad) * scaleFactor);
        const sy = Math.max(0, (rect.top - rootRect.top - pad) * scaleFactor);
        const sw = Math.min(fullCanvas.width - sx, (rect.width + pad * 2) * scaleFactor);
        const sh = Math.min(fullCanvas.height - sy, (rect.height + pad * 2) * scaleFactor);

        if (sw <= 2 || sh <= 2) return null;

        const cropCanvas = iframeDoc.createElement('canvas');
        cropCanvas.width = Math.round(sw);
        cropCanvas.height = Math.round(sh);

        const ctx = cropCanvas.getContext('2d');
        if (!ctx) return null;

        ctx.drawImage(fullCanvas, sx, sy, sw, sh, 0, 0, cropCanvas.width, cropCanvas.height);
        return toJpegDataUrlWithMaxSide(cropCanvas);
    } catch (error) {
        console.error('captureQuickAiElementScreenshot failed:', error);
        return null;
    }
}

async function toggleQuickAiVisionMode() {
    const nextEnabled = !quickAiVisionEnabled;

    if (nextEnabled) {
        if (!selectedQuickEditElement) {
            showToolbarStatus('请先选中一个元素', 'info');
            return;
        }

        showToolbarStatus('视觉模式启用中：正在捕获元素截图…', 'info');
        const testShot = await captureQuickAiElementScreenshot(selectedQuickEditElement);
        if (!testShot) {
            setQuickAiVisionEnabledState(false);
            showToolbarStatus('视觉模式启用失败：无法捕获元素截图（可能是跨域资源）', 'warning');
            return;
        }

        setQuickAiVisionEnabledState(true);
        showToolbarStatus('视觉参考已启用', 'success');
        return;
    }

    setQuickAiVisionEnabledState(false);
    showToolbarStatus('视觉参考已关闭', 'info');
}

function setQuickAiPopoverMinimizedState(minimized, options = {}) {
    const { persist = true } = options || {};
    quickAiPopoverMinimized = !!minimized;

    const pop = getQuickAiPopoverEl();
    if (pop) {
        pop.classList.toggle('minimized', quickAiPopoverMinimized);
    }

    const minBtn = getQuickAiMinBtnEl();
    if (minBtn) {
        minBtn.innerHTML = quickAiPopoverMinimized
            ? '<i class="fas fa-window-maximize"></i>'
            : '<i class="fas fa-minus"></i>';
        minBtn.title = quickAiPopoverMinimized ? '还原' : '最小化';
    }

    // 最小化时收起高度到标题栏，避免外框仍保持大高度导致“看起来没最小化”
    if (pop) {
        if (quickAiPopoverMinimized) {
            try {
                const rect = pop.getBoundingClientRect();
                pop.dataset.quickAiPrevWidth = String(Math.round(rect.width));
                pop.dataset.quickAiPrevHeight = String(Math.round(rect.height));
            } catch (e) { }

            pop.style.height = '46px';
            pop.style.minHeight = '46px';
            pop.style.resize = 'horizontal';
            clampQuickAiPopoverToViewport();
        } else {
            const prevW = Number(pop.dataset.quickAiPrevWidth || '');
            const prevH = Number(pop.dataset.quickAiPrevHeight || '');

            pop.style.minHeight = '';
            pop.style.resize = 'both';

            if (Number.isFinite(prevW) && prevW > 0) {
                pop.style.width = `${prevW}px`;
            }
            if (Number.isFinite(prevH) && prevH > 0) {
                pop.style.height = `${prevH}px`;
            } else {
                restoreQuickAiPopoverSize();
            }
            clampQuickAiPopoverToViewport();
        }
    }

    if (persist) {
        try {
            localStorage.setItem('quickAiPopoverMinimized', JSON.stringify(quickAiPopoverMinimized));
        } catch (e) { }
    }
}

function toggleQuickAiPopoverMinimize() {
    setQuickAiPopoverMinimizedState(!quickAiPopoverMinimized);
}

function restoreQuickAiPopoverMinimizedState() {
    try {
        const raw = localStorage.getItem('quickAiPopoverMinimized');
        if (!raw) return;
        const value = JSON.parse(raw);
        setQuickAiPopoverMinimizedState(!!value, { persist: false });
    } catch (e) { }
}

function ensureQuickAiElementId(element) {
    if (!element) return null;
    const existing = element.getAttribute('data-quick-ai-id');
    if (existing) return existing;
    const id = `qai_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    element.setAttribute('data-quick-ai-id', id);
    return id;
}

function clampQuickAiPopoverToViewport() {
    const pop = getQuickAiPopoverEl();
    if (!pop) return;

    const margin = 10;
    const rect = pop.getBoundingClientRect();
    let left = rect.left;
    let top = rect.top;

    left = Math.max(margin, Math.min(left, window.innerWidth - rect.width - margin));
    top = Math.max(margin, Math.min(top, window.innerHeight - rect.height - margin));

    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
}

function saveQuickAiPopoverPosition() {
    const pop = getQuickAiPopoverEl();
    if (!pop) return;

    try {
        const rect = pop.getBoundingClientRect();
        const data = { left: rect.left, top: rect.top };
        localStorage.setItem('quickAiPopoverPos', JSON.stringify(data));
    } catch (e) {
        // ignore
    }
}

function saveQuickAiPopoverSize() {
    const pop = getQuickAiPopoverEl();
    if (!pop) return;
    if (pop.classList.contains('minimized')) return;

    try {
        const rect = pop.getBoundingClientRect();
        const data = {
            width: Math.round(rect.width),
            height: Math.round(rect.height),
        };
        localStorage.setItem('quickAiPopoverSize', JSON.stringify(data));
    } catch (e) {
        // ignore
    }
}

function restoreQuickAiPopoverSize() {
    const pop = getQuickAiPopoverEl();
    if (!pop) return false;

    try {
        const raw = localStorage.getItem('quickAiPopoverSize');
        if (!raw) return false;
        const data = JSON.parse(raw);
        if (!data || typeof data.width !== 'number' || typeof data.height !== 'number') return false;

        // Apply as inline styles so ResizeObserver can pick up changes too
        pop.style.width = `${data.width}px`;
        pop.style.height = `${data.height}px`;
        clampQuickAiPopoverToViewport();
        return true;
    } catch (e) {
        return false;
    }
}

function restoreQuickAiPopoverPosition() {
    const pop = getQuickAiPopoverEl();
    if (!pop) return false;

    try {
        const raw = localStorage.getItem('quickAiPopoverPos');
        if (!raw) return false;
        const data = JSON.parse(raw);
        if (!data || typeof data.left !== 'number' || typeof data.top !== 'number') return false;
        pop.style.left = `${data.left}px`;
        pop.style.top = `${data.top}px`;
        clampQuickAiPopoverToViewport();
        return true;
    } catch (e) {
        return false;
    }
}

function isQuickAiPopoverVisible() {
    const pop = getQuickAiPopoverEl();
    return !!(pop && pop.classList.contains('visible'));
}

function hideQuickAiEditPopover(options = {}) {
    const { clearInput = false } = options || {};
    const pop = getQuickAiPopoverEl();
    if (pop) {
        pop.classList.remove('visible');
        pop.setAttribute('aria-hidden', 'true');
    }

    if (clearInput) {
        const inputEl = getQuickAiInputEl();
        if (inputEl) inputEl.value = '';
        setQuickAiStatus('');
    }

    quickAiTargetElementId = null;
}

function showQuickAiEditPopover(element, options = {}) {
    const { focus = false } = options || {};
    if (!quickEditMode) return;
    if (!element) return;

    const pop = getQuickAiPopoverEl();
    const inputEl = getQuickAiInputEl();
    if (!pop || !inputEl) return;

    // 还原上次尺寸（先恢复完整尺寸；若后续处于最小化会再收起）
    restoreQuickAiPopoverSize();

    // 还原上次的最小化状态
    restoreQuickAiPopoverMinimizedState();
    if (focus && quickAiPopoverMinimized) {
        setQuickAiPopoverMinimizedState(false);
    }

    // 根据元素类型调整placeholder
    const tag = (element.tagName || '').toUpperCase();
    if (tag === 'IMG' || tag === 'SVG') {
        inputEl.placeholder = '对选中元素说：例如“增加圆角和阴影，稍微缩小并右移”';
    } else if (tag === 'TABLE' || tag === 'UL' || tag === 'OL') {
        inputEl.placeholder = '对选中元素说：例如“把要点改成更清晰的三条，并保持风格一致”';
    } else {
        inputEl.placeholder = '对选中元素说：例如“把这段文字改得更简洁有力，两行以内”';
    }

    // 优先使用用户拖动过的固定位置；没有则定位到选中元素附近
    if (!restoreQuickAiPopoverPosition()) {
        positionQuickAiEditPopover(element);
    }

    pop.classList.add('visible');
    pop.setAttribute('aria-hidden', 'false');

    if (focus) {
        inputEl.focus();
    }
}

function positionQuickAiEditPopover(element) {
    const pop = getQuickAiPopoverEl();
    const slideFrame = document.getElementById('slideFrame');
    if (!pop || !slideFrame || !element || !slideFrame.getBoundingClientRect) return;

    try {
        const iframeRect = slideFrame.getBoundingClientRect();
        const elementRect = element.getBoundingClientRect();

        // 先确保可测量尺寸
        const prevDisplay = pop.style.display;
        if (!isQuickAiPopoverVisible()) {
            pop.style.display = 'block';
        }

        const popRect = pop.getBoundingClientRect();
        const popW = popRect.width || 360;
        const popH = popRect.height || 160;

        // 恢复 display（避免影响动画）
        if (!isQuickAiPopoverVisible()) {
            pop.style.display = prevDisplay || '';
        }

        const targetCenterX = iframeRect.left + elementRect.left + elementRect.width / 2;
        const targetTop = iframeRect.top + elementRect.top;
        const targetBottom = iframeRect.top + elementRect.bottom;

        const margin = 10;
        let left = targetCenterX - popW / 2;
        left = Math.max(margin, Math.min(left, window.innerWidth - popW - margin));

        // 优先放到元素上方，空间不足则放下方
        let top = targetTop - popH - 12;
        if (top < margin) {
            top = targetBottom + 12;
        }
        top = Math.max(margin, Math.min(top, window.innerHeight - popH - margin));

        pop.style.left = `${left}px`;
        pop.style.top = `${top}px`;
    } catch (e) {
        // ignore positioning errors
    }
}

function initializeQuickAiEditPopover() {
    const inputEl = getQuickAiInputEl();
    if (inputEl && !inputEl._quickAiInitialized) {
        inputEl._quickAiInitialized = true;
        inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                quickAiEditApply();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                hideQuickAiEditPopover({ clearInput: false });
            }
        });
    }

    // 读取并应用上次最小化状态（仅影响 UI 状态，不自动显示浮窗）
    restoreQuickAiPopoverMinimizedState();

    // 读取并应用视觉开关状态（仅影响 UI 状态，不自动显示浮窗）
    restoreQuickAiVisionEnabledState();

    // 跟随窗口变化重定位（浮窗打开且有选中元素时）
    if (!window._quickAiPopoverWindowListeners) {
        window._quickAiPopoverWindowListeners = true;
        window.addEventListener('resize', function () {
            if (isQuickAiPopoverVisible() && selectedQuickEditElement) {
                clampQuickAiPopoverToViewport();
            }
        });

        // 捕获阶段监听滚动，兼容容器滚动
        window.addEventListener('scroll', function () {
            if (isQuickAiPopoverVisible() && selectedQuickEditElement) {
                // 若用户已拖动固定位置，则不跟随元素；仅确保在视口内
                clampQuickAiPopoverToViewport();
            }
        }, true);
    }

    // 初始化拖拽
    const header = document.getElementById('quickAiEditPopoverHeader');
    const pop = getQuickAiPopoverEl();
    if (header && pop && !header._quickAiDragInitialized) {
        header._quickAiDragInitialized = true;

        header.addEventListener('mousedown', function (e) {
            // 点击关闭按钮不触发拖拽
            if (e.target && (e.target.closest && (e.target.closest('.quick-ai-edit-popover-close') || e.target.closest('.quick-ai-edit-popover-minimize') || e.target.closest('.quick-ai-edit-popover-vision')))) {
                return;
            }
            if (e.button !== 0) return;
            if (!isQuickAiPopoverVisible()) return;

            const rect = pop.getBoundingClientRect();
            quickAiPopoverDragging = true;
            quickAiPopoverDragOffsetX = e.clientX - rect.left;
            quickAiPopoverDragOffsetY = e.clientY - rect.top;
            e.preventDefault();
        });

        document.addEventListener('mousemove', function (e) {
            if (!quickAiPopoverDragging) return;
            const margin = 10;
            const popRect = pop.getBoundingClientRect();
            let left = e.clientX - quickAiPopoverDragOffsetX;
            let top = e.clientY - quickAiPopoverDragOffsetY;
            left = Math.max(margin, Math.min(left, window.innerWidth - popRect.width - margin));
            top = Math.max(margin, Math.min(top, window.innerHeight - popRect.height - margin));
            pop.style.left = `${left}px`;
            pop.style.top = `${top}px`;
        });

        document.addEventListener('mouseup', function () {
            if (!quickAiPopoverDragging) return;
            quickAiPopoverDragging = false;
            saveQuickAiPopoverPosition();
        });

        // 双击标题栏：重置定位缓存
        header.addEventListener('dblclick', function () {
            try {
                localStorage.removeItem('quickAiPopoverPos');
            } catch (e) { }
            if (selectedQuickEditElement) {
                positionQuickAiEditPopover(selectedQuickEditElement);
                saveQuickAiPopoverPosition();
            }
        });
    }

    // 监听 resize（用户拖拽改大小）并持久化
    if (pop && !pop._quickAiResizeObserver) {
        try {
            const ro = new ResizeObserver(() => {
                // 避免在隐藏状态下写入怪尺寸
                if (!isQuickAiPopoverVisible()) return;
                if (pop.classList.contains('minimized')) return;
                clampQuickAiPopoverToViewport();
                saveQuickAiPopoverSize();
            });
            ro.observe(pop);
            pop._quickAiResizeObserver = ro;
        } catch (e) {
            // ResizeObserver not supported
        }
    }

    // 最小化按钮
    const minBtn = getQuickAiMinBtnEl();
    if (minBtn && !minBtn._quickAiMinInitialized) {
        minBtn._quickAiMinInitialized = true;
        minBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            toggleQuickAiPopoverMinimize();
        });
    }

    // 视觉按钮
    const visionBtn = getQuickAiVisionBtnEl();
    if (visionBtn && !visionBtn._quickAiVisionInitialized) {
        visionBtn._quickAiVisionInitialized = true;
        visionBtn.addEventListener('click', async function (e) {
            e.preventDefault();
            e.stopPropagation();
            await toggleQuickAiVisionMode();
        });
    }
}

function toggleQuickAiEditPopover() {
    if (!quickEditMode) {
        showToolbarStatus('请先进入快速编辑模式', 'info');
        return;
    }

    if (isQuickAiPopoverVisible()) {
        hideQuickAiEditPopover({ clearInput: false });
        return;
    }

    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选中一个元素', 'info');
        return;
    }

    showQuickAiEditPopover(selectedQuickEditElement, { focus: true });
}

function getCleanSlideHtmlForQuickAi() {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame || !slideFrame.contentDocument) return '';
    return getCleanSlideHtmlForQuickEdit({ slideFrame });
}

function parseQuickAiElementHtmlToIframeNode(elementHtml, iframeDoc, elementId) {
    if (!iframeDoc || !elementHtml) return null;

    try {
        const parsed = new DOMParser().parseFromString(String(elementHtml), 'text/html');

        // 移除脚本
        parsed.querySelectorAll('script').forEach(s => s.remove());

        const root = parsed.body && parsed.body.firstElementChild;
        if (!root) return null;

        // 移除 on* 事件属性（根 + 子孙）
        const nodes = [root, ...root.querySelectorAll('*')];
        nodes.forEach(node => {
            Array.from(node.attributes || []).forEach(attr => {
                if ((attr.name || '').toLowerCase().startsWith('on')) {
                    node.removeAttribute(attr.name);
                }
            });
        });

        // 强制保留定位属性
        if (elementId) {
            root.setAttribute('data-quick-ai-id', elementId);
        }

        return iframeDoc.importNode(root, true);
    } catch (e) {
        return null;
    }
}

async function quickAiEditApply() {
    if (!quickEditMode) {
        setQuickAiStatus('请先进入快速编辑模式');
        return;
    }

    if (!selectedQuickEditElement) {
        setQuickAiStatus('请先选中一个元素');
        return;
    }

    const inputEl = getQuickAiInputEl();
    const userRequest = (inputEl?.value || '').trim();
    if (!userRequest) {
        setQuickAiStatus('请输入修改要求（Shift+Enter 换行）');
        if (inputEl) inputEl.focus();
        return;
    }

    if (quickAiEditSending) return;

    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame || !slideFrame.contentDocument) {
        setQuickAiStatus('预览未就绪，请稍后重试');
        return;
    }

    const iframeDoc = slideFrame.contentDocument;
    const currentSlide = (typeof slidesData !== 'undefined' && slidesData[currentSlideIndex]) ? slidesData[currentSlideIndex] : null;

    const elementId = ensureQuickAiElementId(selectedQuickEditElement);
    quickAiTargetElementId = elementId;

    setQuickAiStatus('AI 正在处理…');
    setQuickAiSendingState(true);

    try {
        let slideOutline = null;
        if (typeof projectOutline !== 'undefined' && projectOutline && projectOutline.slides && projectOutline.slides[currentSlideIndex]) {
            slideOutline = projectOutline.slides[currentSlideIndex];
        }

        // 视觉模式：捕获所选元素截图发送给AI参考
        let visionEnabledForRequest = !!quickAiVisionEnabled;
        let elementScreenshot = null;
        if (visionEnabledForRequest) {
            setQuickAiStatus('正在捕获所选元素截图…');
            elementScreenshot = await captureQuickAiElementScreenshot(selectedQuickEditElement);
            if (!elementScreenshot) {
                visionEnabledForRequest = false;
                try {
                    showNotification('元素截图捕获失败，将仅使用文本进行编辑（可能是跨域资源导致）', 'warning');
                } catch (_) { }
            }
        }

        // 截图阶段结束后，恢复为“处理中”状态提示（避免一直停留在“截图中”）
        setQuickAiStatus('AI 正在处理…');

        const payload = {
            slideIndex: currentSlideIndex + 1,
            slideTitle: currentSlide?.title || '',
            slideContent: getCleanSlideHtmlForQuickAi() || currentSlide?.html_content || '',
            elementHtml: selectedQuickEditElement.outerHTML,
            elementId: elementId,
            userRequest: userRequest,
            slideOutline: slideOutline,
            visionEnabled: visionEnabledForRequest,
            elementScreenshot: elementScreenshot,
            projectInfo: {
                project_id: (typeof projectId !== 'undefined' ? projectId : null),
                title: window.landpptEditorProjectInfo.title,
                topic: window.landpptEditorProjectInfo.topic,
                scenario: window.landpptEditorProjectInfo.scenario
            }
        };

        const response = await fetch('/api/ai/element-edit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result || !result.success) {
            const message = (result && result.error) ? result.error : `请求失败：HTTP ${response.status}`;
            throw new Error(message);
        }

        const updatedElementHtml = (result.updated_element_html || '').trim();
        if (!updatedElementHtml) {
            throw new Error('AI 未返回可用的元素 HTML');
        }

        // 保存一次撤销点：在真正应用前
        saveStateForUndo();

        const target = iframeDoc.querySelector(`[data-quick-ai-id="${elementId}"]`) || selectedQuickEditElement;
        const newNode = parseQuickAiElementHtmlToIframeNode(updatedElementHtml, iframeDoc, elementId);
        if (!target || !newNode) {
            throw new Error('无法解析或定位要替换的元素');
        }

        target.replaceWith(newNode);

        // 重新绑定快速编辑事件到新元素（允许对新增元素补绑定）
        initQuickEditElementSelection();

        // 重新选中，恢复手柄/拖拽等能力
        selectQuickEditElement(newNode, { allowWhileAiSending: true });

        // 保存并同步到缩略图/服务端
        saveQuickEditChanges();

        showToolbarStatus('AI 已应用到选中元素', 'success');
        setQuickAiStatus('已应用，继续输入可再次编辑');

        // 清理定位属性，避免长期残留在 iframe DOM 中
        try {
            if (selectedQuickEditElement) {
                selectedQuickEditElement.removeAttribute('data-quick-ai-id');
            }
        } catch (e) { }
        quickAiTargetElementId = null;

        // 清空输入，便于下一次操作
        if (inputEl) {
            inputEl.value = '';
            inputEl.focus();
        }

        // 应用后保持浮窗位置（若未被拖动也会记录一次定位）
        saveQuickAiPopoverPosition();
        saveQuickAiPopoverSize();
    } catch (error) {
        setQuickAiStatus(`失败：${error.message || error}`);
        showToolbarStatus('AI 编辑失败', 'warning');
    } finally {
        setQuickAiSendingState(false);
    }
}

let isDragging = false;
let isResizing = false;
let dragStartX = 0;
let dragStartY = 0;
let elementStartX = 0;
let elementStartY = 0;
let resizeHandle = null;
let elementStartWidth = 0;
let elementStartHeight = 0;
const QUICK_EDIT_KEYBOARD_MOVE_STEP = 1;
const QUICK_EDIT_KEYBOARD_MOVE_FAST_STEP = 10;

