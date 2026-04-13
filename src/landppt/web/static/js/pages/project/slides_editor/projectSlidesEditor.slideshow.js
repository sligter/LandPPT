function initializeThumbnailEvents() {
    // Use event delegation on the slides container
    const slidesContainer = document.querySelector('.slides-container');
    if (!slidesContainer) {
        return;
    }

    // Remove existing event listeners to prevent duplicates
    slidesContainer.removeEventListener('click', slidesContainer.clickHandler);
    slidesContainer.removeEventListener('contextmenu', slidesContainer.contextHandler);
    slidesContainer.removeEventListener('dragstart', slidesContainer.dragStartHandler);
    slidesContainer.removeEventListener('dragover', slidesContainer.dragOverHandler);
    slidesContainer.removeEventListener('drop', slidesContainer.dropHandler);
    slidesContainer.removeEventListener('dragend', slidesContainer.dragEndHandler);

    // Create event handlers using event delegation
    slidesContainer.clickHandler = (e) => {
        const thumbnail = e.target.closest('.slide-thumbnail');
        if (thumbnail) {
            e.preventDefault();
            e.stopPropagation();
            const index = parseInt(thumbnail.getAttribute('data-slide-index'));
            if (!isNaN(index)) {
                // Ctrl/Meta 多选，用于批量操作；普通点击为单选
                if (e.ctrlKey || e.metaKey) {
                    toggleSlideSelection(index);
                } else {
                    setSingleSlideSelection(index);
                }
                selectSlide(index);
            }
        }
    };

    slidesContainer.contextHandler = (e) => {
        const thumbnail = e.target.closest('.slide-thumbnail');
        if (thumbnail) {
            e.preventDefault();
            const index = parseInt(thumbnail.getAttribute('data-slide-index'));
            if (!isNaN(index)) {
                showContextMenu(e, index);
            }
        }
    };

    slidesContainer.dragStartHandler = (e) => {
        const thumbnail = e.target.closest('.slide-thumbnail');
        if (thumbnail) {
            const index = parseInt(thumbnail.getAttribute('data-slide-index'));
            if (!isNaN(index)) {
                handleDragStart(e, index);
            }
        }
    };

    slidesContainer.dragOverHandler = (e) => {
        const thumbnail = e.target.closest('.slide-thumbnail');
        if (thumbnail) {
            handleDragOver(e);
        }
    };

    slidesContainer.dropHandler = (e) => {
        const thumbnail = e.target.closest('.slide-thumbnail');
        if (thumbnail) {
            const index = parseInt(thumbnail.getAttribute('data-slide-index'));
            if (!isNaN(index)) {
                handleDrop(e, index);
            }
        }
    };

    slidesContainer.dragEndHandler = (e) => {
        const thumbnail = e.target.closest('.slide-thumbnail');
        if (thumbnail) {
            handleDragEnd(e);
        }
    };

    // Add event listeners using delegation
    slidesContainer.addEventListener('click', slidesContainer.clickHandler);
    slidesContainer.addEventListener('contextmenu', slidesContainer.contextHandler);
    slidesContainer.addEventListener('dragstart', slidesContainer.dragStartHandler);
    slidesContainer.addEventListener('dragover', slidesContainer.dragOverHandler);
    slidesContainer.addEventListener('drop', slidesContainer.dropHandler);
    slidesContainer.addEventListener('dragend', slidesContainer.dragEndHandler);
}

// 优化的幻灯片放映功能 - 双缓冲无闪烁系统
let slideshowCache = new Map(); // 缓存幻灯片内容
let isTransitioning = false; // 防止快速切换时的重复操作
let currentFrameIndex = 1; // 当前显示的iframe索引 (1 或 2)
let nextFrameIndex = 2; // 下一个iframe索引 (1 或 2)

function startSlideshow() {
    if (!slidesData || slidesData.length === 0) {
        showNotification('没有可用的幻灯片！', 'warning');
        return;
    }

    isSlideshow = true;
    slideshowIndex = currentSlideIndex;

    // 重置双缓冲系统
    currentFrameIndex = 1;
    nextFrameIndex = 2;

    const overlay = document.getElementById('slideshowOverlay');
    const frame1 = document.getElementById('slideshowFrame1');
    const frame2 = document.getElementById('slideshowFrame2');

    // 初始化iframe状态
    frame1.classList.add('visible');
    frame1.classList.remove('hidden');
    frame2.classList.add('hidden');
    frame2.classList.remove('visible');

    // 使用requestAnimationFrame优化显示
    requestAnimationFrame(() => {
        overlay.style.display = 'flex';

        // 预加载当前和下一张幻灯片
        preloadSlideshowSlides();

        // 在第一个iframe中加载当前幻灯片
        const content = slideshowCache.get(slideshowIndex) || slidesData[slideshowIndex].html_content;
        setSafeIframeContentNoFlash(frame1, content, () => {
            // 更新幻灯片信息
            const info = document.getElementById('slideshowInfo');
            info.textContent = `${slideshowIndex + 1} / ${slidesData.length}`;
        });
    });

    // Add keyboard event listeners
    document.addEventListener('keydown', handleSlideshowKeyboard);

    // Add touch gesture support
    initializeSlideshowTouchGestures();

    // Add mouse movement detection for controls visibility
    initializeSlideshowMouseControls();
}

// 预加载幻灯片内容，提升切换流畅度
function preloadSlideshowSlides() {
    // 预加载当前、前一张和后一张幻灯片
    const indicesToPreload = [
        slideshowIndex - 1,
        slideshowIndex,
        slideshowIndex + 1
    ].filter(index => index >= 0 && index < slidesData.length);

    indicesToPreload.forEach(index => {
        if (!slideshowCache.has(index)) {
            const content = slidesData[index].html_content;
            slideshowCache.set(index, content);
        }
    });
}

function exitSlideshow() {
    isSlideshow = false;
    isTransitioning = false;

    const overlay = document.getElementById('slideshowOverlay');
    const frame1 = document.getElementById('slideshowFrame1');
    const frame2 = document.getElementById('slideshowFrame2');

    // 使用fade out效果
    overlay.style.opacity = '0';
    setTimeout(() => {
        overlay.style.display = 'none';
        overlay.style.opacity = '1';

        // 清理iframe内容，避免内存泄漏
        frame1.srcdoc = '';
        frame2.srcdoc = '';
        frame1.removeAttribute('data-current-content');
        frame2.removeAttribute('data-current-content');
    }, 200);

    // Remove keyboard event listeners
    document.removeEventListener('keydown', handleSlideshowKeyboard);

    // Remove touch gesture listeners
    removeSlideshowTouchGestures();

    // Remove mouse movement listeners
    removeSlideshowMouseControls();

    // 清理缓存（可选，节省内存）
    slideshowCache.clear();
}

// 无闪烁幻灯片更新函数 - 双缓冲系统
function updateSlideshowSlide() {
    if (!slidesData || slidesData.length === 0 || isTransitioning) return;

    isTransitioning = true;

    const info = document.getElementById('slideshowInfo');

    // 立即更新幻灯片信息
    info.textContent = `${slideshowIndex + 1} / ${slidesData.length}`;

    // 获取当前显示的iframe和下一个iframe
    const currentFrame = document.getElementById(`slideshowFrame${currentFrameIndex}`);
    const nextFrame = document.getElementById(`slideshowFrame${nextFrameIndex}`);

    // 在后台iframe中预加载新内容
    const content = slideshowCache.get(slideshowIndex) || slidesData[slideshowIndex].html_content;

    // 使用优化的内容设置方法
    setSafeIframeContentNoFlash(nextFrame, content, () => {
        // 内容加载完成后，瞬间切换显示
        requestAnimationFrame(() => {
            // 隐藏当前iframe，显示新iframe
            currentFrame.classList.remove('visible');
            currentFrame.classList.add('hidden');
            nextFrame.classList.remove('hidden');
            nextFrame.classList.add('visible');

            // 交换iframe索引
            [currentFrameIndex, nextFrameIndex] = [nextFrameIndex, currentFrameIndex];

            isTransitioning = false;

            // 预加载相邻幻灯片
            preloadSlideshowSlides();

            // 异步初始化JavaScript，不阻塞UI
            setTimeout(() => {
                forceReinitializeIframeJS(nextFrame);
            }, 100);
        });
    });
}

// 优化的iframe内容设置，避免闪烁
function setSafeIframeContentNoFlash(iframe, html, callback) {
    if (!iframe || !html) {
        if (callback) callback();
        return;
    }

    // 检查内容是否相同，避免不必要的更新
    if (iframe.getAttribute('data-current-content') === html) {
        if (callback) callback();
        return;
    }

    // 直接设置内容，不使用过渡效果
    try {
        iframe.srcdoc = html;
        iframe.setAttribute('data-current-content', html);

        // 监听加载完成
        const handleLoad = () => {
            iframe.removeEventListener('load', handleLoad);
            if (callback) {
                // 短暂延迟确保内容完全渲染
                setTimeout(callback, 50);
            }
        };

        iframe.addEventListener('load', handleLoad);

        // 备用超时机制
        setTimeout(() => {
            iframe.removeEventListener('load', handleLoad);
            if (callback) callback();
        }, 500);

    } catch (e) {
        if (callback) callback();
    }
}

// 优化的切换函数，支持快速响应和防抖
function previousSlideshow() {
    if (isTransitioning) return; // 防止快速切换时的重复操作

    if (slideshowIndex > 0) {
        slideshowIndex--;
        updateSlideshowSlide();
    } else {
        // 到达第一张时的视觉反馈
        const slideContainer = document.querySelector('.slideshow-slide');
        slideContainer.style.transform = 'translateX(-10px)';
        setTimeout(() => {
            slideContainer.style.transform = 'translateX(0)';
        }, 150);
    }
}

function nextSlideshow() {
    if (isTransitioning) return; // 防止快速切换时的重复操作

    if (slideshowIndex < slidesData.length - 1) {
        slideshowIndex++;
        updateSlideshowSlide();
    } else {
        // 到达最后一张时的视觉反馈
        const slideContainer = document.querySelector('.slideshow-slide');
        slideContainer.style.transform = 'translateX(10px)';
        setTimeout(() => {
            slideContainer.style.transform = 'translateX(0)';
        }, 150);
    }
}

// 快速跳转到指定幻灯片
function jumpToSlide(index) {
    if (isTransitioning || index < 0 || index >= slidesData.length) return;

    slideshowIndex = index;
    updateSlideshowSlide();
}

// 优化的键盘事件处理，支持更多快捷键和防抖
let keyboardTimeout;

function handleSlideshowKeyboard(e) {
    if (!isSlideshow) return;

    // 防抖处理，避免按键过快
    clearTimeout(keyboardTimeout);
    keyboardTimeout = setTimeout(() => {
        switch (e.key) {
            case 'ArrowLeft':
            case 'ArrowUp':
            case 'PageUp':
            case 'Backspace':
                e.preventDefault();
                previousSlideshow();
                break;
            case 'ArrowRight':
            case 'ArrowDown':
            case 'PageDown':
            case ' ':
            case 'Enter':
                e.preventDefault();
                nextSlideshow();
                break;
            case 'Escape':
            case 'q':
            case 'Q':
                e.preventDefault();
                exitSlideshow();
                break;
            case 'Home':
                e.preventDefault();
                jumpToSlide(0);
                break;
            case 'End':
                e.preventDefault();
                jumpToSlide(slidesData.length - 1);
                break;
            case 'f':
            case 'F':
            case 'F11':
                e.preventDefault();
                toggleSlideshowFullscreen();
                break;
            default:
                // 数字键快速跳转
                if (e.key >= '1' && e.key <= '9') {
                    e.preventDefault();
                    const slideNum = parseInt(e.key) - 1;
                    if (slideNum < slidesData.length) {
                        jumpToSlide(slideNum);
                    }
                }
                break;
        }
    }, 50); // 50ms防抖
}

// 全屏切换功能
function toggleSlideshowFullscreen() {
    const overlay = document.getElementById('slideshowOverlay');

    if (!document.fullscreenElement) {
        overlay.requestFullscreen().catch(err => {
            // 无法进入全屏
        });
    } else {
        document.exitFullscreen().catch(err => {
            // 无法退出全屏
        });
    }
}

// 拖拽功能
