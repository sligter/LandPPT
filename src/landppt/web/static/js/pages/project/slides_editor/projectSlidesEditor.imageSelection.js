// 优化的iframe JavaScript重新初始化函数
let isReinitializing = false; // 防止重复初始化

function forceReinitializeIframeJS(iframe) {
    if (!iframe || isReinitializing) return;

    isReinitializing = true;

    // 使用requestAnimationFrame优化性能
    requestAnimationFrame(() => {
        try {
            const iframeWindow = iframe.contentWindow;
            const iframeDoc = iframe.contentDocument || iframeWindow.document;

            if (!iframeWindow || !iframeDoc) {
                isReinitializing = false;
                return;
            }

            // 只检查Chart.js，减少不必要的操作
            if (iframeWindow.Chart) {
                const canvasElements = iframeDoc.querySelectorAll('canvas[id*="chart"], canvas[id*="Chart"]');

                if (canvasElements.length > 0) {
                    // 简化检查逻辑
                    let needsReinitialization = false;
                    canvasElements.forEach(canvas => {
                        if (!canvas.chart) {
                            needsReinitialization = true;
                        }
                    });

                    // 只在真正需要时才重新初始化
                    if (needsReinitialization) {
                        const scripts = iframeDoc.querySelectorAll('script');
                        scripts.forEach(script => {
                            if (script.textContent && script.textContent.includes('Chart')) {
                                try {
                                    iframeWindow.eval(script.textContent);
                                } catch (e) {
                                    // 静默处理错误
                                }
                            }
                        });
                    }
                }
            }

            // 初始化图像选择功能
            initializeImageSelection(iframe, iframeWindow, iframeDoc);

        } catch (e) {
            // 静默处理错误，避免控制台噪音
        } finally {
            // 延迟重置标志，避免过于频繁的调用
            setTimeout(() => {
                isReinitializing = false;
            }, 500);
        }
    });
}

// 图像选择功能相关变量
let selectedImageInfo = null;
let imageSelectionEnabled = false;

// 初始化图像选择功能（仅在快速编辑模式下启用）
function initializeImageSelection(iframe, iframeWindow, iframeDoc) {
    try {
        // 移除之前的事件监听器
        const existingSelectables = iframeDoc.querySelectorAll('[data-image-selectable]');
        existingSelectables.forEach(element => {
            element.removeAttribute('data-image-selectable');
            element.style.cursor = '';
            element.classList.remove('image-selected', 'image-selectable');
            // 移除之前添加的事件监听器
            if (element._imageClickHandler) {
                element.removeEventListener('click', element._imageClickHandler);
                element.removeEventListener('mouseenter', element._imageMouseEnterHandler);
                element.removeEventListener('mouseleave', element._imageMouseLeaveHandler);
                delete element._imageClickHandler;
                delete element._imageMouseEnterHandler;
                delete element._imageMouseLeaveHandler;
            }
        });

        // 只在快速编辑模式下启用图像选择功能
        if (!quickEditMode || currentMode !== 'quickedit') {
            return;
        }

        let imageIndex = 0;

        // 1. 处理 <img> 标签
        const images = iframeDoc.querySelectorAll('img');
        images.forEach((img) => {
            // 跳过装饰性图像或很小的图像
            if (img.width < 30 || img.height < 30) return;

            setupImageSelection(img, imageIndex++, iframe, 'img');
        });

        // 2. 处理具有背景图像的元素
        const allElements = iframeDoc.querySelectorAll('*');
        allElements.forEach((element) => {
            const computedStyle = iframeWindow.getComputedStyle(element);
            const backgroundImage = computedStyle.backgroundImage;

            // 检查是否有背景图像（排除 none 和渐变）
            if (backgroundImage &&
                backgroundImage !== 'none' &&
                backgroundImage.includes('url(')) {

                // 获取元素尺寸
                const rect = element.getBoundingClientRect();

                // 跳过太小的元素
                if (rect.width < 50 || rect.height < 50) return;

                // 跳过已经处理过的img元素
                if (element.tagName.toLowerCase() === 'img') return;

                setupImageSelection(element, imageIndex++, iframe, 'background');
            }
        });

        // 3. 处理SVG图像
        const svgElements = iframeDoc.querySelectorAll('svg');
        svgElements.forEach((svg) => {
            const rect = svg.getBoundingClientRect();
            if (rect.width < 30 || rect.height < 30) return;

            setupImageSelection(svg, imageIndex++, iframe, 'svg');
        });

        // 添加样式到iframe文档
        addImageSelectionStyles(iframeDoc);



    } catch (e) {
        // 初始化图像选择功能失败
    }
}

// 设置单个元素的图像选择功能（仅用于视觉效果，点击由quick edit selection处理）
function setupImageSelection(element, index, iframe, type) {
    element.setAttribute('data-image-selectable', 'true');
    element.setAttribute('data-image-index', index);
    element.setAttribute('data-image-type', type);
    element.style.cursor = 'pointer';
    element.classList.add('image-selectable');

    // 注意：点击事件由initQuickEditElementSelection中的selectQuickEditElement处理
    // 这里只添加悬停效果，避免与quick edit selection冲突

    element._imageMouseEnterHandler = function () {
        // 只在快速编辑模式下显示悬停效果
        if (!quickEditMode || currentMode !== 'quickedit') {
            return;
        }
        // 如果元素已经被quick edit选中，不改变outline样式
        if (element.classList.contains('quick-edit-element-selected')) {
            return;
        }
        if (!element.classList.contains('image-selected')) {
            element.style.outline = '2px dashed #007bff';
            element.style.outlineOffset = '2px';
        }
    };

    element._imageMouseLeaveHandler = function () {
        // 只在快速编辑模式下处理悬停离开
        if (!quickEditMode || currentMode !== 'quickedit') {
            return;
        }
        // 如果元素已经被quick edit选中，不改变outline样式
        if (element.classList.contains('quick-edit-element-selected')) {
            return;
        }
        if (!element.classList.contains('image-selected')) {
            element.style.outline = '';
            element.style.outlineOffset = '';
        }
    };

    // 只添加悬停事件监听器，不添加点击事件（点击由quick edit处理）
    element.addEventListener('mouseenter', element._imageMouseEnterHandler);
    element.addEventListener('mouseleave', element._imageMouseLeaveHandler);
}

// 添加图像选择相关样式
function addImageSelectionStyles(iframeDoc) {
    let styleElement = iframeDoc.getElementById('image-selection-styles');
    if (!styleElement) {
        styleElement = iframeDoc.createElement('style');
        styleElement.id = 'image-selection-styles';
        styleElement.textContent = `
            .image-selectable {
                transition: all 0.2s ease;
            }
            .image-selectable:hover {
                transform: scale(1.02);
            }
            .image-selected {
                outline: 3px solid #007bff !important;
                outline-offset: 3px !important;
                box-shadow: 0 0 10px rgba(0, 123, 255, 0.3) !important;
                transform: scale(1.02) !important;
            }
        `;
        iframeDoc.head.appendChild(styleElement);
    }
}

// 选择图像
function selectImage(imgElement, iframe) {
    try {
        const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;

        // 清除之前的选择
        const previousSelected = iframeDoc.querySelectorAll('.image-selected');
        previousSelected.forEach(img => {
            img.classList.remove('image-selected');
            img.style.outline = '';
            img.style.outlineOffset = '';
            img.style.boxShadow = '';
            img.style.transform = '';
        });

        // 选择当前图像
        imgElement.classList.add('image-selected');

        // 提取图像信息
        const imageInfo = extractImageInfo(imgElement, iframe);
        selectedImageInfo = imageInfo;

        // 通知AI助手
        notifyAIAssistantImageSelected(imageInfo);

    } catch (e) {
        // 选择图像失败
    }
}

// 提取图像信息
function extractImageInfo(imageElement, iframe) {
    const rect = imageElement.getBoundingClientRect();
    const computedStyle = iframe.contentWindow.getComputedStyle(imageElement);
    const imageType = imageElement.getAttribute('data-image-type') || 'img';

    let imageInfo = {
        index: imageElement.getAttribute('data-image-index'),
        type: imageType,
        className: imageElement.className,
        id: imageElement.id || '',
        style: imageElement.getAttribute('style') || '',
        width: rect.width,
        height: rect.height,
        position: {
            top: rect.top,
            left: rect.left,
            right: rect.right,
            bottom: rect.bottom
        },
        computedStyle: {
            position: computedStyle.position,
            display: computedStyle.display,
            float: computedStyle.float,
            margin: computedStyle.margin,
            padding: computedStyle.padding,
            border: computedStyle.border,
            borderRadius: computedStyle.borderRadius,
            transform: computedStyle.transform,
            zIndex: computedStyle.zIndex,
            opacity: computedStyle.opacity,
            backgroundImage: computedStyle.backgroundImage,
            backgroundSize: computedStyle.backgroundSize,
            backgroundPosition: computedStyle.backgroundPosition,
            backgroundRepeat: computedStyle.backgroundRepeat
        },
        slideIndex: currentSlideIndex,
        slideTitle: slidesData[currentSlideIndex]?.title || '',
        outerHTML: imageElement.outerHTML,
        parentInfo: extractParentInfo(imageElement)
    };

    // 根据图像类型提取特定信息
    if (imageType === 'img') {
        // <img> 标签的特定属性
        imageInfo.src = imageElement.src;
        imageInfo.alt = imageElement.alt || '';
        imageInfo.title = imageElement.title || '';
        imageInfo.naturalWidth = imageElement.naturalWidth;
        imageInfo.naturalHeight = imageElement.naturalHeight;
        imageInfo.computedStyle.objectFit = computedStyle.objectFit;
        imageInfo.computedStyle.objectPosition = computedStyle.objectPosition;
    } else if (imageType === 'background') {
        // 背景图像的特定属性
        const backgroundImage = computedStyle.backgroundImage;
        const urlMatch = backgroundImage.match(/url\(['"]?([^'"]+)['"]?\)/);
        imageInfo.src = urlMatch ? urlMatch[1] : '';
        imageInfo.alt = imageElement.getAttribute('alt') || imageElement.getAttribute('title') || '背景图像';
        imageInfo.title = imageElement.getAttribute('title') || '背景图像';
        imageInfo.isBackgroundImage = true;
    } else if (imageType === 'svg') {
        // SVG 的特定属性
        imageInfo.src = imageElement.getAttribute('src') || 'data:image/svg+xml;base64,' + btoa(imageElement.outerHTML);
        imageInfo.alt = imageElement.getAttribute('alt') || imageElement.getAttribute('title') || 'SVG图像';
        imageInfo.title = imageElement.getAttribute('title') || 'SVG图像';
        imageInfo.isSVG = true;
    }

    return imageInfo;
}

// 提取父容器信息
function extractParentInfo(imgElement) {
    const parent = imgElement.parentElement;
    if (!parent) return null;

    return {
        tagName: parent.tagName,
        className: parent.className,
        style: parent.getAttribute('style') || '',
        id: parent.id || ''
    };
}

// 获取图像类型的显示名称
function getImageTypeDisplay(type) {
    const typeMap = {
        'img': '图片标签',
        'background': '背景图像',
        'svg': 'SVG图像'
    };
    return typeMap[type] || '未知类型';
}

// 客户端图像替换函数（保持完整HTML结构）
function replaceImageInHtmlClient(htmlContent, imageInfo, newImageUrl) {
    try {
        // 使用字符串替换而不是DOM解析，避免样式丢失
        const imageType = imageInfo.type || 'img';
        const oldSrc = imageInfo.src || '';

        let updatedHtml = htmlContent;
        let replaced = false;

        if (imageType === 'img') {
            // 使用正则表达式替换img标签的src属性
            const imgRegex = new RegExp(
                `(<img[^>]*src=["'])[^"']*${escapeRegExp(oldSrc.split('/').pop())}[^"']*(['"][^>]*>)`,
                'gi'
            );

            if (imgRegex.test(htmlContent)) {
                updatedHtml = htmlContent.replace(imgRegex, `$1${newImageUrl}$2`);
                replaced = true;
            } else {
                // 后备方案：直接字符串替换
                if (htmlContent.includes(oldSrc)) {
                    updatedHtml = htmlContent.replace(new RegExp(escapeRegExp(oldSrc), 'g'), newImageUrl);
                    replaced = true;
                }
            }
        } else if (imageType === 'background') {
            // 替换CSS背景图像
            const bgRegex = new RegExp(
                `(background-image:\\s*url\\(['"]?)[^'"\\)]*${escapeRegExp(oldSrc.split('/').pop())}[^'"\\)]*(['"]?\\))`,
                'gi'
            );

            if (bgRegex.test(htmlContent)) {
                updatedHtml = htmlContent.replace(bgRegex, `$1${newImageUrl}$2`);
                replaced = true;
            } else {
                // 后备方案
                if (htmlContent.includes(oldSrc)) {
                    updatedHtml = htmlContent.replace(new RegExp(escapeRegExp(oldSrc), 'g'), newImageUrl);
                    replaced = true;
                }
            }
        }

        return replaced ? updatedHtml : htmlContent;

    } catch (error) {
        return htmlContent;
    }
}

// 搜索图片
function searchImages(event) {
    if (event.key === 'Enter' || event.type === 'input') {
        galleryState.searchTerm = event.target.value.toLowerCase();
        galleryState.currentPage = 1;
        applyFilters();
    }
}



// 筛选图片分类
function filterImages() {
    const categoryFilter = document.getElementById('imageCategoryFilter');
    galleryState.categoryFilter = categoryFilter.value;
    galleryState.currentPage = 1;
    applyFilters();
}

// 改变每页显示数量
function changePageSize() {
    const pageSizeSelect = document.getElementById('imagePageSize');
    galleryState.pageSize = parseInt(pageSizeSelect.value);
    galleryState.currentPage = 1;
    renderImageGallery();
}

// 跳转到指定页面
function goToPage(page) {
    const totalPages = Math.ceil(galleryState.filteredImages.length / galleryState.pageSize);
    if (page >= 1 && page <= totalPages) {
        galleryState.currentPage = page;
        renderImageGallery();
    }
}

// 应用筛选条件
function applyFilters() {
    const { allImages, searchTerm, categoryFilter } = galleryState;

    galleryState.filteredImages = allImages.filter(image => {
        // 搜索筛选
        const matchesSearch = !searchTerm ||
            (image.title && image.title.toLowerCase().includes(searchTerm)) ||
            (image.description && image.description.toLowerCase().includes(searchTerm)) ||
            (image.alt_text && image.alt_text.toLowerCase().includes(searchTerm));

        // 分类筛选 - 兼容多种可能的字段名
        let matchesCategory = true;
        if (categoryFilter) {
            matchesCategory =
                image.category === categoryFilter ||
                image.source === categoryFilter ||
                image.source_type === categoryFilter ||
                image.type === categoryFilter ||
                // 根据图片来源推断分类 - 修复字段映射
                (categoryFilter === 'ai_generated' && (image.source === 'ai_generated' || image.source_type === 'ai_generated' || image.generation_prompt)) ||
                (categoryFilter === 'network_search' && (image.source === 'web_search' || image.source_type === 'web_search')) ||
                (categoryFilter === 'local_upload' && (image.source === 'local_storage' || image.source_type === 'local_storage'));
        }

        return matchesSearch && matchesCategory;
    });

    renderImageGallery();
}

// 双击图片直接选择
function handleImageDoubleClick(imageData) {
    // 双击图片直接选择并关闭对话框
    window.closeGalleryDialog(imageData);
}

// 获取正确的图片URL
function getImageUrl(image) {
    if (!image) return '';

    // 如果已经是完整URL，直接返回
    if (image.url && (image.url.startsWith('http') || image.url.startsWith('/api/'))) {
        return image.url;
    }

    // 如果有image.id，构建API URL
    if (image.id) {
        return `/api/image/view/${image.id}`;
    }

    // 如果有相对路径，转换为API URL
    if (image.url) {
        return image.url.startsWith('/') ? image.url : `/api/image/view/${image.url}`;
    }

    // 默认占位图
    return 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIwIiBoZWlnaHQ9IjEyMCIgdmlld0JveD0iMCAwIDEyMCAxMjAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIxMjAiIGhlaWdodD0iMTIwIiBmaWxsPSIjRjVGNUY1Ii8+CjxwYXRoIGQ9Ik02MCA0NUw3NSA2NUg0NUw2MCA0NVoiIGZpbGw9IiNEREREREQiLz4KPGNpcmNsZSBjeD0iNTAiIGN5PSI0MCIgcj0iNSIgZmlsbD0iI0RERERERCIvPgo8L3N2Zz4K';
}

// 处理图片加载错误
function handleImageError(imgElement, imageId) {
    // 隐藏加载动画
    const spinner = imgElement.parentElement.querySelector('.loading-spinner');
    if (spinner) spinner.style.display = 'none';

    // 尝试备用URL
    const originalSrc = imgElement.src;

    // 如果不是API URL，尝试API URL
    if (!originalSrc.includes('/api/image/view/')) {
        const apiUrl = `/api/image/view/${imageId}`;
        if (originalSrc !== apiUrl) {
            imgElement.src = apiUrl;
            return;
        }
    }

    // 如果API URL也失败，尝试添加时间戳避免缓存
    if (!originalSrc.includes('?t=')) {
        const timestampUrl = `${originalSrc}?t=${Date.now()}`;
        imgElement.src = timestampUrl;
        return;
    }

    // 最终使用占位图
    imgElement.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIwIiBoZWlnaHQ9IjEyMCIgdmlld0JveD0iMCAwIDEyMCAxMjAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIxMjAiIGhlaWdodD0iMTIwIiBmaWxsPSIjRjVGNUY1Ii8+CjxwYXRoIGQ9Ik02MCA0NUw3NSA2NUg0NUw2MCA0NVoiIGZpbGw9IiNEREREREQiLz4KPGNpcmNsZSBjeD0iNTAiIGN5PSI0MCIgcj0iNSIgZmlsbD0iI0RERERERCIvPjx0ZXh0IHg9IjYwIiB5PSI4MCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI4IiBmaWxsPSIjOTk5Ij7liqDovb3lpLHotKU8L3RleHQ+PC9zdmc+';
    imgElement.style.opacity = '0.5';
    imgElement.title = '图片加载失败';
}

// 显示空图片库
function showEmptyGallery() {
    const container = document.getElementById('imageGalleryContainer');
    if (container) {
        container.innerHTML = `
            <div class="text-center text-muted py-5">
                <i class="fas fa-images fa-4x mb-3" style="opacity: 0.3;"></i>
                <h5>图片库中暂无图片</h5>
                <p>您可以先上传一些图片到图片库</p>
                <a href="/image-gallery" class="btn btn-outline-primary" target="_blank">
                    <i class="fas fa-upload"></i> 前往图片库上传
                </a>
            </div>
        `;
    }

    // 清空分页
    const paginationList = document.getElementById('paginationList');
    if (paginationList) paginationList.innerHTML = '';

    const statsElement = document.getElementById('imageStats');
    if (statsElement) statsElement.textContent = '共 0 张图片';
}

// 显示图片库错误
function showGalleryError(errorMessage) {
    const container = document.getElementById('imageGalleryContainer');
    if (container) {
        container.innerHTML = `
            <div class="text-center text-danger py-5">
                <i class="fas fa-exclamation-triangle fa-3x mb-3"></i>
                <h5>加载图片库失败</h5>
                <p>${escapeHtml(errorMessage)}</p>
                <button class="btn btn-outline-danger" onclick="initImageGallery()">
                    <i class="fas fa-redo"></i> 重新加载
                </button>
            </div>
        `;
    }
}

// 获取分类名称
function getCategoryName(category) {
    const categoryNames = {
        'ai_generated': 'AI生成',
        'web_search': '网络搜索',
        'network_search': '网络搜索',
        'network': '网络搜索',
        'local_storage': '本地上传',
        'local_upload': '本地上传',
        'local': '本地上传'
    };
    return categoryNames[category] || category;
}

// 获取图片分类标签
function getImageCategoryBadge(image) {
    let category = '';
    let badgeClass = 'bg-secondary';

    // 尝试从多个字段确定分类
    if (image.category) {
        category = image.category;
    } else if (image.source) {
        category = image.source;
    } else if (image.source_type) {
        category = image.source_type;
    } else if (image.generation_prompt) {
        category = 'ai_generated';
    } else if (image.url && image.url.includes('/network/')) {
        category = 'web_search';
    } else if (image.url && image.url.includes('/local/')) {
        category = 'local_storage';
    }

    // 设置对应的样式 - 修复分类映射
    switch (category) {
        case 'ai_generated':
            badgeClass = 'bg-success';
            break;
        case 'web_search':
        case 'network_search':
        case 'network':
            badgeClass = 'bg-info';
            break;
        case 'local_storage':
        case 'local_upload':
        case 'local':
            badgeClass = 'bg-primary';
            break;
    }

    if (category) {
        return `<small class="d-block"><span class="badge ${badgeClass}">${getCategoryName(category)}</span></small>`;
    }

    return '';
}

// HTML转义函数
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 辅助函数：转义正则表达式特殊字符
function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// 通知AI助手图像已选择
