function notifyAIAssistantImageSelected(imageInfo) {
    // 更新AI助手界面显示选中的图像信息
    updateAIAssistantSelectedImage(imageInfo);

    // 如果AI助手侧栏未打开，则打开它
    const sidebar = document.getElementById('aiEditSidebar');
    if (!sidebar.classList.contains('open')) {
        openAIEditSidebar();
    }
}

const THUMBNAIL_BASE_WIDTH = 1280;
const THUMBNAIL_BASE_HEIGHT = 720;

function getThumbnailBaseSize(iframe) {
    if (!iframe || !iframe.contentDocument) {
        return { width: THUMBNAIL_BASE_WIDTH, height: THUMBNAIL_BASE_HEIGHT };
    }

    try {
        const doc = iframe.contentDocument;
        const body = doc.body;
        const html = doc.documentElement;
        const bodyStyle = body ? getComputedStyle(body) : null;
        const htmlStyle = html ? getComputedStyle(html) : null;
        const bodyRect = body ? body.getBoundingClientRect() : null;
        const htmlRect = html ? html.getBoundingClientRect() : null;
        const width = parseFloat(bodyStyle?.width || '0')
            || parseFloat(htmlStyle?.width || '0')
            || bodyRect?.width
            || htmlRect?.width
            || THUMBNAIL_BASE_WIDTH;
        const height = parseFloat(bodyStyle?.height || '0')
            || parseFloat(htmlStyle?.height || '0')
            || bodyRect?.height
            || htmlRect?.height
            || THUMBNAIL_BASE_HEIGHT;

        return {
            width: width > 0 ? width : THUMBNAIL_BASE_WIDTH,
            height: height > 0 ? height : THUMBNAIL_BASE_HEIGHT,
        };
    } catch (error) {
        return { width: THUMBNAIL_BASE_WIDTH, height: THUMBNAIL_BASE_HEIGHT };
    }
}

function applyThumbnailPreviewScale(iframe) {
    if (!iframe) return;

    const preview = iframe.closest('.slide-preview');
    if (!preview) return;

    const previewRect = preview.getBoundingClientRect();
    const previewWidth = previewRect.width || preview.clientWidth;
    const previewHeight = previewRect.height || preview.clientHeight;
    if (!previewWidth || !previewHeight) return;

    const baseSize = getThumbnailBaseSize(iframe);
    const scale = Math.min(previewWidth / baseSize.width, previewHeight / baseSize.height);

    iframe.style.width = `${baseSize.width}px`;
    iframe.style.height = `${baseSize.height}px`;
    iframe.style.left = '50%';
    iframe.style.top = '50%';
    iframe.style.transformOrigin = 'center center';
    iframe.style.transform = `translate(-50%, -50%) scale(${scale})`;
}

function applyThumbnailPreviewScaleToAll() {
    document.querySelectorAll('.slide-preview iframe').forEach((iframe) => {
        applyThumbnailPreviewScale(iframe);
    });
}

// 点击其他地方隐藏右键菜单
document.addEventListener('click', function (event) {
    if (!event.target.closest('.context-menu')) {
        hideContextMenu();
    }
});

// 阻止页面默认右键菜单
document.addEventListener('contextmenu', function (event) {
    if (!event.target.closest('.slide-thumbnail')) {
        // 只在非幻灯片区域阻止默认右键菜单
        // event.preventDefault();
    }
});



// 移除重复的checkForUpdates函数定义 - 已在上面定义

// 更新主预览区域
function updateMainPreviewArea() {
    const previewPane = document.getElementById('previewPane');
    if (!previewPane) return;

    if (hasSlidesData && slidesData.length > 0) {
        // 如果有幻灯片数据，更新预览区域
        previewPane.innerHTML = `
            <div class="slide-frame-container">
                <div class="slide-frame-wrapper" id="slideFrameWrapper">
                    <button class="preview-nav-btn left" id="previewPrevBtn" onclick="navigatePreviewSlide(-1)" title="&#19978;&#19968;&#39029; (&#8592;)">
                        <i class="fas fa-chevron-left"></i>
                    </button>

                    <iframe class="slide-frame" id="slideFrame"
                            title="Slide Preview"></iframe>

                    <button class="preview-nav-btn right" id="previewNextBtn" onclick="navigatePreviewSlide(1)" title="&#19979;&#19968;&#39029; (&#8594;)">
                        <i class="fas fa-chevron-right"></i>
                    </button>
                </div>
            </div>
        `;

        updatePreviewNavButtons();

        // 设置第一张幻灯片的内容
        const slideFrame = document.getElementById('slideFrame');
        if (slideFrame && slidesData[0]) {
            setSafeIframeContent(slideFrame, slidesData[0].html_content);

            // 初始化iframe和重新初始化JavaScript
            setTimeout(() => {
                initializeMainFrame();
                applyMainFrameScale();
                forceReinitializeIframeJS(slideFrame);
                updatePreviewNavButtons();
            }, 100);
        }
    } else {
        // 如果没有幻灯片数据，显示等待界面
        previewPane.innerHTML = `
            <div class="d-flex align-items-center justify-content-center h-100" style="background: #f8f9fa; border-radius: 8px;">
                <div class="text-center" style="color: #6c757d;">
                    <div style="font-size: 64px; margin-bottom: 20px;">
                        <i class="fas fa-presentation-screen"></i>
                    </div>
                    <h4 style="margin-bottom: 15px;">等待PPT生成</h4>
                    <p style="margin-bottom: 20px;">PPT生成完成后，预览将在这里显示</p>
                    <button class="btn btn-outline-primary" onclick="checkForUpdates()">
                        <i class="fas fa-refresh"></i> 刷新页面
                    </button>
                </div>
            </div>
        `;
    }
}

// 页面加载完成后应用响应式缩放和绑定事件
document.addEventListener('DOMContentLoaded', function () {
    // 关键：如果服务端返回了缺页的slides_data（例如只存在第2、3页），这里先按page_number/大纲进行归一化，
    // 避免后续编辑/保存把内容写到错误的页（如第2页覆盖第1页）。
    if (normalizeSlidesDataToOutline()) {
        slidesDataWasNormalized = true;
    }

    // 如果归一化导致页数/顺序变化，刷新侧边栏缩略图以对齐 slidesData 的索引
    if (slidesDataWasNormalized && slidesData && slidesData.length > 0) {
        refreshSidebar();
    }

    // 为所有现有的iframe应用缩略图居中适配
    applyThumbnailPreviewScaleToAll();

    // 初始化右侧主iframe
    setTimeout(() => {
        initializeMainFrame();
        applyMainFrameScale();
    }, 100);

    // 初始化缩略图事件监听器
    initializeThumbnailEvents();

    // 初始化AI侧栏宽度调整功能
    initializeSidebarResize();

    // 初始化CodeMirror编辑器
    initializeCodeMirror();

    // 初始化代码编辑器自动保存（fallback）
    initializeCodeEditorAutoSave();

    // 初始化快捷 AI 元素编辑浮窗
    initializeQuickAiEditPopover();

    // Esc 清空多选
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            clearSlideSelections();
        }
    });

    // 绑定按钮事件监听器
    const slideshowBtn = document.getElementById('slideshowBtn');
    const saveSlideBtn = document.getElementById('saveSlideBtn');
    const aiEditBtn = document.getElementById('aiEditBtn');

    if (slideshowBtn) {
        slideshowBtn.addEventListener('click', startSlideshow);
    }
    if (saveSlideBtn) {
        saveSlideBtn.addEventListener('click', saveSlide);
    }
    if (aiEditBtn) {
        aiEditBtn.addEventListener('click', openAIEditSidebar);
    }

    // 绑定AI输入框回车键事件
    const aiInputBox = document.getElementById('aiInputBox');
    if (aiInputBox) {
        aiInputBox.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendAIMessage();
            }
        });
        aiInputBox.addEventListener('paste', handleAIPaste);
    }

    // 绑定自由对话输入框回车键事件
    const aiNativeInputBox = document.getElementById('aiNativeInputBox');
    if (aiNativeInputBox) {
        aiNativeInputBox.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendNativeChatMessage();
            }
        });
        aiNativeInputBox.addEventListener('paste', handleNativePaste);
    }

    // 绑定自由对话图片上传
    const aiNativeImageFileInput = document.getElementById('aiNativeImageFileInput');
    if (aiNativeImageFileInput) {
        aiNativeImageFileInput.addEventListener('change', function (e) {
            const files = e.target.files;
            if (files && files.length > 0) {
                uploadNativeFiles(files);
            }
            // 允许重复选择同一文件
            e.target.value = '';
        });
    }

    // 确保第一张幻灯片被选中
    if (hasSlidesData && slidesData.length > 0) {
        selectSlide(0);
        setSingleSlideSelection(0);
    } else {
        updateSelectedSlidesUI();
    }

    // 更新功能按钮状态
    updateFunctionButtonsState();

    // 移除自动检查逻辑，只在页面加载时检查一次
    // setTimeout(checkForUpdates, 1000); - 已移除
    // setTimeout(startAutoCheck, 2000); - 已移除
});

// 防抖函数，优化窗口大小变化时的性能
let resizeTimeout;
function debounceResize() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        // 重新计算左侧缩略图缩放
        applyThumbnailPreviewScaleToAll();

        // 清除缓存的缩放比例，强制重新计算
        cachedScale = null;
        lastContainerSize = null;

        // 重新计算主iframe缩放
        applyMainFrameScale();

        // 重新计算CodeMirror编辑器尺寸
        resizeCodeMirror();
    }, 150); // 防抖延迟150ms
}

// 窗口大小改变时使用防抖处理
window.addEventListener('resize', debounceResize);

// 触摸手势支持，提升移动设备体验
let touchStartX = 0;
let touchStartY = 0;
let touchEndX = 0;
let touchEndY = 0;
let touchStartTime = 0;

function initializeSlideshowTouchGestures() {
    const overlay = document.getElementById('slideshowOverlay');

    overlay.addEventListener('touchstart', handleTouchStart, { passive: true });
    overlay.addEventListener('touchend', handleTouchEnd, { passive: true });
    overlay.addEventListener('touchmove', handleTouchMove, { passive: false });
}

function removeSlideshowTouchGestures() {
    const overlay = document.getElementById('slideshowOverlay');

    overlay.removeEventListener('touchstart', handleTouchStart);
    overlay.removeEventListener('touchend', handleTouchEnd);
    overlay.removeEventListener('touchmove', handleTouchMove);
}

function handleTouchStart(e) {
    if (!isSlideshow || e.touches.length !== 1) return;

    const touch = e.touches[0];
    touchStartX = touch.clientX;
    touchStartY = touch.clientY;
    touchStartTime = Date.now();
}

function handleTouchMove(e) {
    if (!isSlideshow || e.touches.length !== 1) return;

    // 防止页面滚动
    e.preventDefault();
}

function handleTouchEnd(e) {
    if (!isSlideshow || e.changedTouches.length !== 1) return;

    const touch = e.changedTouches[0];
    touchEndX = touch.clientX;
    touchEndY = touch.clientY;

    const deltaX = touchEndX - touchStartX;
    const deltaY = touchEndY - touchStartY;
    const deltaTime = Date.now() - touchStartTime;

    // 检查是否为有效的滑动手势
    const minSwipeDistance = 50;
    const maxSwipeTime = 500;
    const maxVerticalDistance = 100;

    if (deltaTime > maxSwipeTime) return;
    if (Math.abs(deltaY) > maxVerticalDistance) return;

    if (Math.abs(deltaX) > minSwipeDistance) {
        if (deltaX > 0) {
            // 向右滑动 - 上一张
            previousSlideshow();
        } else {
            // 向左滑动 - 下一张
            nextSlideshow();
        }
    } else if (Math.abs(deltaX) < 10 && Math.abs(deltaY) < 10) {
        // 点击手势 - 下一张
        nextSlideshow();
    }
}
