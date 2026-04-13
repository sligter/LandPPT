window.landpptEditorConfig = JSON.parse(
    document.getElementById('projectEditorConfigScript').textContent
);
window.landpptEditorProjectInfo = window.landpptEditorConfig.projectInfo || { title: '', topic: '', scenario: '' };
window.landpptEditorProjectRequirements = window.landpptEditorConfig.projectRequirements || '';

let currentSlideIndex = 0;
let currentMode = 'preview';
const projectId = JSON.parse(document.getElementById('projectDataScript').textContent).projectId;
window.projectId = projectId;

// 高权限功能：仅管理员或积分>1,000,000 才展示讲解视频导出相关控件
const narrationVideoToolsEnabled = !!window.landpptEditorConfig.narrationVideoToolsEnabled;

let slidesData = JSON.parse(document.getElementById('projectSlidesScript').textContent).slides;
window.slidesData = slidesData;
let slideshowIndex = 0;
let isSlideshow = false;

// 保存初始状态用于重置功能
const initialSlideStates = {};
if (Array.isArray(slidesData)) {
    slidesData.forEach((slide, index) => {
        if (slide && slide.html_content) {
            initialSlideStates[index] = slide.html_content;
        }
    });
}

function getInitialSlideState(slideIndex) {
    if (!Number.isInteger(slideIndex) || slideIndex < 0) {
        return '';
    }
    return typeof initialSlideStates[slideIndex] === 'string' ? initialSlideStates[slideIndex] : '';
}

function setInitialSlideState(slideIndex, htmlContent, options = {}) {
    const { overwrite = true } = options || {};
    if (!Number.isInteger(slideIndex) || slideIndex < 0) {
        return false;
    }
    if (typeof htmlContent !== 'string' || !htmlContent.trim()) {
        return false;
    }
    if (!overwrite && typeof initialSlideStates[slideIndex] === 'string' && initialSlideStates[slideIndex].trim()) {
        return false;
    }
    initialSlideStates[slideIndex] = htmlContent;
    return true;
}

// 幻灯片多选（Ctrl+点击）- 用于批量重新生成等操作
let selectedSlideIndices = new Set();

function getOutlineSlidesCount() {
    const outlineSlides = projectOutline && Array.isArray(projectOutline.slides) ? projectOutline.slides : null;
    if (outlineSlides && outlineSlides.length > 0) return outlineSlides.length;
    return Array.isArray(slidesData) ? slidesData.length : 0;
}

function ensureSlidesDataLength(targetLen) {
    if (!Array.isArray(slidesData)) {
        slidesData = [];
        window.slidesData = slidesData;
    }
    const len = Math.max(0, parseInt(targetLen, 10) || 0);
    while (slidesData.length < len) {
        const pageNumber = slidesData.length + 1;
        slidesData.push({
            page_number: pageNumber,
            title: `第${pageNumber}页`,
            html_content: '<div style="width:1280px;height:720px;display:flex;align-items:center;justify-content:center;font-family:Microsoft YaHei,Arial,sans-serif;color:#6c757d;">待生成</div>'
        });
    }
}

let slidesDataWasNormalized = false;
function normalizeSlidesDataToOutline() {
    if (!Array.isArray(slidesData) || slidesData.length === 0) {
        return false;
    }

    const outlineTotal = getOutlineSlidesCount();
    if (!Number.isInteger(outlineTotal) || outlineTotal <= 0) {
        return false;
    }

    let maxPageNumber = 0;
    slidesData.forEach((s) => {
        const pn = s && (typeof s.page_number === 'number' ? s.page_number : parseInt(s.page_number, 10));
        if (Number.isInteger(pn) && pn > maxPageNumber) maxPageNumber = pn;
    });

    const targetLen = Math.max(outlineTotal, maxPageNumber, slidesData.length);
    const normalized = new Array(targetLen).fill(null);
    const unplaced = [];

    slidesData.forEach((slide) => {
        if (!slide || typeof slide !== 'object') {
            return;
        }
        const pn = typeof slide.page_number === 'number' ? slide.page_number : parseInt(slide.page_number, 10);
        if (Number.isInteger(pn) && pn >= 1 && pn <= targetLen && !normalized[pn - 1]) {
            normalized[pn - 1] = slide;
        } else {
            unplaced.push(slide);
        }
    });

    // 依次填充未能通过page_number定位的内容（兼容历史数据）
    unplaced.forEach((slide) => {
        const idx = normalized.indexOf(null);
        if (idx === -1) return;
        normalized[idx] = slide;
    });

    // 填充缺失页为占位符，确保索引与大纲序号对齐
    for (let i = 0; i < normalized.length; i++) {
        if (!normalized[i]) {
            const outlineSlide = (projectOutline && projectOutline.slides && projectOutline.slides[i]) ? projectOutline.slides[i] : null;
            const title = outlineSlide && outlineSlide.title ? outlineSlide.title : `第${i + 1}页`;
            normalized[i] = {
                page_number: i + 1,
                title,
                html_content: '<div style="width:1280px;height:720px;display:flex;align-items:center;justify-content:center;font-family:Microsoft YaHei,Arial,sans-serif;color:#6c757d;">待生成</div>',
                slide_type: outlineSlide && (outlineSlide.slide_type || outlineSlide.type) ? (outlineSlide.slide_type || outlineSlide.type) : 'content',
                content_points: outlineSlide && Array.isArray(outlineSlide.content_points) ? outlineSlide.content_points : [],
                is_user_edited: false
            };
        }
        // 强制page_number与数组索引一致，避免再次错位
        if (normalized[i] && typeof normalized[i] === 'object') {
            normalized[i].page_number = i + 1;
        }
    }

    const changed =
        normalized.length !== slidesData.length ||
        normalized.some((s, i) => slidesData[i] !== s);

    if (changed) {
        slidesData = normalized;
        window.slidesData = slidesData;
    }
    return changed;
}

function sanitizeSelectedSlides() {
    if (!slidesData || slidesData.length === 0) {
        selectedSlideIndices.clear();
        return;
    }
    selectedSlideIndices = new Set(
        Array.from(selectedSlideIndices).filter(i => Number.isInteger(i) && i >= 0 && i < slidesData.length)
    );
}

function updateSelectedSlidesUI() {
    sanitizeSelectedSlides();

    const countEl = document.getElementById('selectedSlidesCount');
    if (countEl) {
        countEl.textContent = String(selectedSlideIndices.size);
    }

    document.querySelectorAll('.slide-thumbnail').forEach((thumb) => {
        const idx = parseInt(thumb.getAttribute('data-slide-index'));
        if (!Number.isInteger(idx)) return;
        if (selectedSlideIndices.has(idx)) {
            thumb.classList.add('selected');
        } else {
            thumb.classList.remove('selected');
        }
    });
}

function setSingleSlideSelection(index) {
    selectedSlideIndices = new Set([index]);
    updateSelectedSlidesUI();
}

function toggleSlideSelection(index) {
    if (selectedSlideIndices.has(index)) {
        selectedSlideIndices.delete(index);
    } else {
        selectedSlideIndices.add(index);
    }
    updateSelectedSlidesUI();
}

function clearSlideSelections() {
    selectedSlideIndices.clear();
    updateSelectedSlidesUI();
}

function getSelectedSlideIndicesSorted() {
    sanitizeSelectedSlides();
    return Array.from(selectedSlideIndices).sort((a, b) => a - b);
}

const projectMeta = JSON.parse(document.getElementById('projectMetaScript').textContent);
let projectStatus = projectMeta.status || '';
let projectOutline = projectMeta.outline || null;
window.projectOutline = projectOutline;
slidesDataWasNormalized = normalizeSlidesDataToOutline();

// AI编辑相关变量
let aiChatHistory = {}; // 改为对象，按幻灯片索引存储对话历史
let isAISending = false;
let isResizingSidebar = false;
let sidebarStartWidth = 500;
let sidebarStartX = 0;

// 图片上传相关变量
let uploadedImages = window.uploadedImages || [];
window.uploadedImages = uploadedImages;
let isImageUploadExpanded = false;
let isUploading = false;
let currentPreviewImage = null; // 当前预览的图片信息
let selectedLibraryImages = []; // 从图床选择的图片
let libraryImages = []; // 图床中的所有图片

// 视觉模式相关变量
let visionModeEnabled = false;
let filteredLibraryImages = []; // 搜索过滤后的图片
let currentSearchTerm = ''; // 当前搜索关键词
let currentPage = 1; // 当前页码
let totalPages = 1; // 总页数
let totalCount = 0; // 总图片数
let perPage = 1000; // 每页显示数量（设置为大值以获取所有图片）

// CodeMirror编辑器相关变量
let codeMirrorEditor = null;
let isCodeMirrorInitialized = false;

// 创建安全的data URL
function createDataUrl(html) {
    try {
        const encoded = btoa(unescape(encodeURIComponent(html)));
        return `data:text/html;charset=utf-8;base64,${encoded}`;
    } catch (error) {
        throw error;
    }
}

// 优化的iframe内容设置函数，减少卡顿
function prepareHtmlForPreview(html) {
    if (typeof html !== 'string') {
        return html;
    }

    let prepared = stripUnusedTailwindCdn(html).replace(/integrity="[^"]*"/gi, '')
        .replace(/crossorigin="[^"]*"/gi, '');

    prepared = prepared.replace(
        /<script\s+src="https:\/\/cdnjs\.cloudflare\.com\/ajax\/libs\/d3\/[\d\.]+\/d3\.min\.js"[^>]*><\/script>/gi,
        '<' + 'script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></' + 'script>'
    );

    return prepared;
}

function htmlUsesTailwindUtilities(html) {
    if (typeof html !== 'string' || !/class\s*=/i.test(html)) {
        return false;
    }

    const utilityPattern = /^(?:container|sr-only|not-sr-only|block|inline|inline-block|inline-flex|flex|inline-grid|grid|hidden|contents|absolute|relative|fixed|sticky|static|(?:top|right|bottom|left|inset|z)-[\w./:[\]-]+|(?:m|mx|my|mt|mr|mb|ml|p|px|py|pt|pr|pb|pl|w|min-w|max-w|h|min-h|max-h|gap|space-x|space-y|basis|grow|shrink|order|col|row|text|font|leading|tracking|bg|from|via|to|border|rounded|shadow|opacity|items|justify|content|self|place|object|overflow|overscroll|whitespace|break|aspect|ring|fill|stroke|list|underline|line-clamp|animate|duration|delay|ease|scale|rotate|translate|skew)-[\w./:%[\]-]+|(?:prose|antialiased|subpixel-antialiased|uppercase|lowercase|capitalize|truncate|underline|no-underline|italic|not-italic|pointer-events-none|pointer-events-auto|select-none|select-text|align-middle|align-top|align-bottom))$/i;
    const classPattern = /class\s*=\s*["']([^"']+)["']/gi;
    let match;

    while ((match = classPattern.exec(html)) !== null) {
        const tokens = (match[1] || '').trim().split(/\s+/);
        if (tokens.some(token => token && utilityPattern.test(token))) {
            return true;
        }
    }

    return false;
}

function stripUnusedTailwindCdn(html) {
    if (typeof html !== 'string' || !/cdn\.tailwindcss\.com/i.test(html)) {
        return html;
    }
    if (htmlUsesTailwindUtilities(html)) {
        return html;
    }

    return html
        .replace(/<script\b[^>]*src=["']https:\/\/cdn\.tailwindcss\.com(?:\/)?[^"']*["'][^>]*>\s*<\/script>/gi, '')
        .replace(/<script\b(?![^>]*\bsrc=)[^>]*>\s*tailwind\.config\s*=.*?<\/script>/gis, '');
}

function setSafeIframeContent(iframe, html, options = {}) {
    const { force = false } = options || {};

    if (!iframe) {
        return;
    }

    if (!html) {
        return;
    }

    const preparedHtml = prepareHtmlForPreview(html);

    if (!force && iframe.getAttribute('data-current-content') === preparedHtml) {
        return;
    }

    // 先清理现有的Chart实例，防止重复渲染
    cleanupIframeCharts(iframe);

    // 使用requestAnimationFrame优化性能
    requestAnimationFrame(() => {
        try {
            // 直接设置srcdoc，减少延迟
            iframe.srcdoc = preparedHtml;
            iframe.setAttribute('data-current-content', preparedHtml);

            // 简化的加载完成处理
            iframe.onload = function () {
                // 减少延迟，提高响应速度
                setTimeout(() => {
                    try {
                        const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                        const chartElements = iframeDoc.querySelectorAll('canvas[id*="chart"], canvas[id*="Chart"]');

                        if (chartElements.length > 0) {
                            const iframeWindow = iframe.contentWindow;
                            if (iframeWindow && iframeWindow.Chart) {
                                // Chart.js库已加载，图表正常渲染
                            }
                        }

                        // 如果是主预览iframe且处于快速编辑模式，切换幻灯片后自动恢复快速编辑能力
                        try {
                            if (iframe && iframe.id === 'slideFrame' && typeof quickEditMode !== 'undefined' && quickEditMode) {
                                reinitializeQuickEditForCurrentSlideAfterIframeLoad();
                            }
                        } catch (e) {
                            // ignore quick edit reinit errors
                        }
                    } catch (e) {
                        // 静默处理错误，避免控制台噪音
                    }
                }, 50); // 减少延迟时间
            };
        } catch (e) {
            // 设置iframe内容失败
        }
    });
}

function syncIframeCurrentContent(iframe, html) {
    if (!iframe || typeof html !== 'string') {
        return;
    }
    try {
        iframe.setAttribute('data-current-content', prepareHtmlForPreview(html));
    } catch (error) {
        // 忽略缓存同步异常，不影响主流程。
    }
}

function reinitializeQuickEditForCurrentSlideAfterIframeLoad() {
    // 仅在当前模式为 quickedit 时恢复（避免用户实际已切走模式）
    if (typeof currentMode === 'undefined' || currentMode !== 'quickedit') return;
    if (typeof quickEditMode === 'undefined' || !quickEditMode) return;

    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame) return;

    // 清理旧选中引用，避免跨页操作到已卸载的DOM
    try {
        if (typeof deselectQuickEditElement === 'function') {
            deselectQuickEditElement({ keepAiPopover: typeof isQuickAiPopoverVisible === 'function' && isQuickAiPopoverVisible() });
        }
    } catch (e) { }

    // 确保工具栏保持可用
    try {
        if (typeof showQuickEditToolbar === 'function') {
            showQuickEditToolbar();
        }
    } catch (e) { }

    // 重新初始化：可编辑高亮 + 元素选择事件 + 图片选择
    setTimeout(() => {
        try {
            if (typeof initEditableElements === 'function') {
                initEditableElements();
            }
            if (typeof initQuickEditElementSelection === 'function') {
                initQuickEditElementSelection();
            }

            try {
                const iframeWindow = slideFrame.contentWindow;
                const iframeDoc = slideFrame.contentDocument || iframeWindow?.document;
                if (iframeWindow && iframeDoc && typeof initializeImageSelection === 'function') {
                    initializeImageSelection(slideFrame, iframeWindow, iframeDoc);
                }
            } catch (e) {
                // ignore image selection reinit errors
            }
        } catch (e) {
            // ignore
        }
    }, 120);
}

function refreshSlidePreview(index, options = {}) {
    const { force = false } = options || {};
    const targetIndex = typeof index === 'number' ? index : currentSlideIndex;

    if (!slidesData || targetIndex < 0 || targetIndex >= slidesData.length) {
        return;
    }

    const slideContent = slidesData[targetIndex]?.html_content;
    if (!slideContent) {
        return;
    }

    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && targetIndex === currentSlideIndex) {
        setSafeIframeContent(slideFrame, slideContent, { force });
        setTimeout(() => {
            try {
                forceReinitializeIframeJS(slideFrame);
            } catch (e) {
                // 忽略重新初始化错误
            }
        }, 300);
    }

    const thumbnailIframes = document.querySelectorAll('.slide-thumbnail .slide-preview iframe');
    const thumbnailIframe = thumbnailIframes[targetIndex];
    if (thumbnailIframe) {
        setSafeIframeContent(thumbnailIframe, slideContent, { force });
    }
}

function updateCodeEditorContent(newContent) {
    if (typeof newContent !== 'string') {
        newContent = newContent ?? '';
    }

    if (codeMirrorEditor && isCodeMirrorInitialized) {
        try {
            codeMirrorEditor.setValue(newContent);
            return;
        } catch (e) {
            // 如果CodeMirror更新失败，回退到textarea
        }
    }

    const codeEditor = document.getElementById('codeEditor');
    if (codeEditor) {
        codeEditor.value = newContent;
    }
}

// 清理iframe中的Chart实例，防止重复渲染
function cleanupIframeCharts(iframe) {
    if (!iframe) return;

    try {
        const iframeWindow = iframe.contentWindow;
        const iframeDoc = iframe.contentDocument || iframeWindow.document;

        if (!iframeWindow || !iframeDoc) return;

        // 检查是否有Chart.js
        if (iframeWindow.Chart) {
            // 清理现有Chart实例

            // 方法1: 通过Chart.instances清理所有实例
            if (iframeWindow.Chart.instances) {
                Object.values(iframeWindow.Chart.instances).forEach(chart => {
                    if (chart && typeof chart.destroy === 'function') {
                        try {
                            chart.destroy();
                        } catch (e) {
                            // 销毁Chart实例失败
                        }
                    }
                });
            }

            // 方法2: 通过canvas元素清理
            const canvasElements = iframeDoc.querySelectorAll('canvas[id*="chart"], canvas[id*="Chart"]');
            canvasElements.forEach((canvas, index) => {
                if (canvas.chart) {
                    try {
                        canvas.chart.destroy();
                    } catch (e) {
                        // 销毁Chart实例失败
                    }
                }
                // 清理canvas的chart属性
                delete canvas.chart;
            });
        }
    } catch (e) {
        // 清理Chart实例时出错
    }
}

// 拖拽和右键菜单相关变量
let draggedSlideIndex = -1;
let copiedSlideData = null;
let contextMenuSlideIndex = -1;

// 检查是否有幻灯片数据
let hasSlidesData = slidesData && slidesData.length > 0;

// 检查PPT是否生成完成 - 简化逻辑
function isPPTGenerationCompleted() {
    // 简单检查：有幻灯片数据就认为生成完成
    return hasSlidesData && slidesData.length > 0;
}

// 手动检查更新并刷新页面
function checkForUpdates() {
    showNotification('正在检查更新...', 'info');

    // 直接刷新页面以获取最新数据
    setTimeout(() => {
        window.location.reload();
    }, 500);
}

// 移除自动检查功能，只保留手动刷新
// function startAutoCheck() - 已移除定时自动检查逻辑

// 更新功能按钮状态
function updateFunctionButtonsState() {
    const isCompleted = isPPTGenerationCompleted();

    // 获取需要控制的按钮和菜单项
    const contextMenu = document.getElementById('contextMenu');
    if (contextMenu) {
        const copyBtn = contextMenu.querySelector('[onclick="copySlide()"]');
        const pasteBtn = contextMenu.querySelector('[onclick="pasteSlide()"]');
        const insertBtn = contextMenu.querySelector('[onclick="insertNewSlide()"]');
        const duplicateBtn = contextMenu.querySelector('[onclick="duplicateSlide()"]');
        const deleteBtn = contextMenu.querySelector('[onclick="deleteSlide()"]');

        // 禁用或启用按钮
        [copyBtn, pasteBtn, insertBtn, duplicateBtn, deleteBtn].forEach(btn => {
            if (btn) {
                if (isCompleted) {
                    btn.style.opacity = '1';
                    btn.style.pointerEvents = 'auto';
                    btn.style.color = '';
                } else {
                    btn.style.opacity = '0.5';
                    btn.style.pointerEvents = 'none';
                    btn.style.color = '#999';
                }
            }
        });

        // 添加提示信息
        if (!isCompleted) {
            [copyBtn, pasteBtn, insertBtn, duplicateBtn, deleteBtn].forEach(btn => {
                if (btn) {
                    btn.title = 'PPT生成完成后才能使用此功能';
                }
            });
        }
    }
}

// 缓存缩放比例，避免重复计算
let cachedScale = null;
let lastContainerSize = null;

// 计算并应用iframe缩放，确保内容完全可见
function invalidateMainFrameScaleCache() {
    cachedScale = null;
    lastContainerSize = null;
}

function requestMainFrameScaleRefresh() {
    invalidateMainFrameScaleCache();

    const runScale = () => {
        if (typeof applyMainFrameScale === 'function') {
            applyMainFrameScale();
        }
    };

    // 等待布局切换完成后再重算，避免分屏场景继续沿用旧缩放比例
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(runScale);
        });
        return;
    }

    setTimeout(runScale, 0);
}

function applyMainFrameScale() {
    const wrapper = document.getElementById('slideFrameWrapper');
    const iframe = document.getElementById('slideFrame');

    if (!wrapper || !iframe) return;

    // 获取容器的实际尺寸
    const wrapperRect = wrapper.getBoundingClientRect();
    const containerWidth = wrapperRect.width - 20; // 减去内边距
    const containerHeight = wrapperRect.height - 20; // 减去内边距

    // 检查容器尺寸是否变化，如果没有变化则使用缓存的缩放比例
    const currentSize = `${containerWidth}x${containerHeight}`;
    if (lastContainerSize === currentSize && cachedScale !== null) {
        iframe.style.transform = `translate(-50%, -50%) scale(${cachedScale})`;
        return;
    }

    // PPT标准尺寸
    const pptWidth = 1280;
    const pptHeight = 720;

    // 计算缩放比例，确保内容完全可见
    const scaleX = containerWidth / pptWidth;
    const scaleY = containerHeight / pptHeight;
    const scale = Math.min(scaleX, scaleY, 1); // 取较小值，且不超过1

    // 缓存结果
    cachedScale = scale;
    lastContainerSize = currentSize;

    // 应用缩放
    iframe.style.transform = `translate(-50%, -50%) scale(${scale})`;
}

// Preview navigation
function navigatePreviewSlide(direction) {
    if (!hasSlidesData) {
        return;
    }

    const newIndex = currentSlideIndex + direction;

    if (newIndex >= 0 && newIndex < slidesData.length) {
        // 先更新currentSlideIndex
        currentSlideIndex = newIndex;

        // 显式更新侧边栏缩略图选中状态（放在最前面确保执行）
        const thumbnails = document.querySelectorAll('.slide-thumbnail');

        thumbnails.forEach((thumb, i) => {
            if (i === newIndex) {
                thumb.classList.add('active');
                thumb.classList.add('selected');  // 添加选中状态（对勾）
                thumb.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else {
                thumb.classList.remove('active');
                thumb.classList.remove('selected');  // 移除选中状态（对勾）
            }
        });

        // 更新预览和编辑器
        if (slidesData[newIndex]) {
            const slideFrame = document.getElementById('slideFrame');
            const codeEditor = document.getElementById('codeEditor');

            if (slideFrame) {
                slideFrame.style.opacity = '0.8';
                slideFrame.style.transition = 'opacity 0.2s ease';
                setSafeIframeContent(slideFrame, slidesData[newIndex].html_content);
                setTimeout(() => {
                    slideFrame.style.opacity = '1';
                    forceReinitializeIframeJS(slideFrame);
                }, 150);
            }

            if (codeEditor) {
                if (codeMirrorEditor && isCodeMirrorInitialized) {
                    codeMirrorEditor.setValue(slidesData[newIndex].html_content);
                } else {
                    codeEditor.value = slidesData[newIndex].html_content;
                }
            }
        }

        updatePreviewNavButtons();
        updateAICurrentSlideInfo();
        clearAIMessagesForSlideSwitch();
        clearImageSelection();
    }
}

function updatePreviewNavButtons() {
    const prevBtn = document.getElementById('previewPrevBtn');
    const nextBtn = document.getElementById('previewNextBtn');

    if (prevBtn && nextBtn) {
        prevBtn.disabled = currentSlideIndex <= 0;
        nextBtn.disabled = currentSlideIndex >= slidesData.length - 1;
    }
}

// 初始化iframe样式
function initializeMainFrame() {
    const iframe = document.getElementById('slideFrame');
    if (!iframe) return;

    // 设置固定尺寸和居中定位
    iframe.style.position = 'absolute';
    iframe.style.top = '50%';
    iframe.style.left = '50%';
    iframe.style.width = '1280px';
    iframe.style.height = '720px';
    iframe.style.border = 'none';
    iframe.style.background = 'white';
    iframe.style.borderRadius = '8px';
    iframe.style.transformOrigin = 'center center';

    // 应用缩放
    applyMainFrameScale();
}

function selectSlide(index) {
    if (!hasSlidesData) {
        return;
    }

    if (index < 0 || index >= slidesData.length) {
        return;
    }

    // 如果选择的是当前幻灯片，直接返回
    if (currentSlideIndex === index) {
        return;
    }

    currentSlideIndex = index;

    updatePreviewNavButtons();

    // 更新AI编辑助手中的当前页数显示
    updateAICurrentSlideInfo();

    // 切换幻灯片时清除AI对话记录
    clearAIMessagesForSlideSwitch();

    // 切换幻灯片时清除图像选择状态
    clearImageSelection();

    // 使用requestAnimationFrame优化DOM操作
    requestAnimationFrame(() => {
        // Update active thumbnail with animation
        document.querySelectorAll('.slide-thumbnail').forEach((thumb, i) => {
            if (i === index) {
                thumb.classList.add('active');
                // 使用更平滑的滚动
                thumb.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else {
                thumb.classList.remove('active');
            }
        });

        // Update preview and editor
        if (slidesData[index]) {
            const slideFrame = document.getElementById('slideFrame');
            const codeEditor = document.getElementById('codeEditor');

            if (slideFrame) {
                // 简化过渡效果，减少卡顿
                slideFrame.style.opacity = '0.8';
                slideFrame.style.transition = 'opacity 0.2s ease';

                try {
                    setSafeIframeContent(slideFrame, slidesData[index].html_content);
                } catch (error) {
                    // Error setting iframe content
                }

                // 减少延迟时间，提高响应速度
                setTimeout(() => {
                    slideFrame.style.opacity = '1';
                    // 只在必要时重新应用缩放
                    if (cachedScale === null) {
                        applyMainFrameScale();
                    }
                    // 减少Chart.js重新初始化的频率
                    setTimeout(() => {
                        forceReinitializeIframeJS(slideFrame);

                        // 如果当前是快速编辑模式，重新初始化可编辑元素
                        if (currentMode === 'quickedit' && quickEditMode) {
                            setTimeout(() => {
                                initEditableElements();
                            }, 200);
                        }
                    }, 100);
                }, 150);
            }

            if (codeEditor) {
                if (codeMirrorEditor && isCodeMirrorInitialized) {
                    codeMirrorEditor.setValue(slidesData[index].html_content);
                } else {
                    codeEditor.value = slidesData[index].html_content;
                }
            }
        }
    });
}

