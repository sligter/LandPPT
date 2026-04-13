async function showImageGalleryDialog() {
    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.className = 'modal fade show';
        modal.style.display = 'block';
        modal.style.backgroundColor = 'rgba(0,0,0,0.5)';
        modal.style.zIndex = '20000';
        modal.innerHTML = `
            <div class="modal-dialog modal-xl modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-images text-primary"></i> 选择图片
                        </h5>
                        <button type="button" class="btn-close" onclick="closeGalleryDialog(null)"></button>
                    </div>
                    <div class="modal-body">
                        <!-- 搜索和筛选区域 -->
                        <div class="row mb-3">
                            <div class="col-md-6">
                                <div class="input-group">
                                    <span class="input-group-text"><i class="fas fa-search"></i></span>
                                    <input type="text" class="form-control" id="imageSearchInput"
                                           placeholder="搜索图片标题或描述..." onkeyup="searchImages(event)">
                                </div>
                            </div>
                            <div class="col-md-3">
                                <select class="form-select" id="imageCategoryFilter" onchange="filterImages()">
                                    <option value="">所有分类</option>
                                    <option value="ai_generated">AI生成</option>
                                    <option value="network_search">网络搜索</option>
                                    <option value="local_upload">本地上传</option>
                                </select>
                            </div>
                            <div class="col-md-3">
                                <select class="form-select" id="imagePageSize" onchange="changePageSize()">
                                    <option value="12">每页12张</option>
                                    <option value="24" selected>每页24张</option>
                                    <option value="48">每页48张</option>
                                </select>
                            </div>
                        </div>

                        <!-- 图片展示区域 -->
                        <div id="imageGalleryContainer" style="min-height: 400px; max-height: 500px; overflow-y: auto;">
                            <div class="text-center">
                                <i class="fas fa-spinner fa-spin"></i> 加载图片库...
                            </div>
                        </div>

                        <!-- 分页区域 -->
                        <div id="imagePagination" class="d-flex justify-content-between align-items-center mt-3">
                            <div id="imageStats" class="text-muted"></div>
                            <nav>
                                <ul class="pagination pagination-sm mb-0" id="paginationList">
                                </ul>
                            </nav>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" onclick="closeGalleryDialog(null)">取消</button>
                        <button type="button" class="btn btn-primary" id="useSelectedBtn" onclick="useSelectedImage()" disabled>
                            <i class="fas fa-check"></i> 使用选中图片
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // 初始化图片库
        initImageGallery();

        window.closeGalleryDialog = (selectedImage) => {
            document.body.removeChild(modal);
            delete window.closeGalleryDialog;
            delete window.selectGalleryImage;
            delete window.useSelectedImage;
            delete window.searchImages;
            delete window.filterImages;
            delete window.changePageSize;
            delete window.goToPage;
            resolve(selectedImage);
        };

        window.selectGalleryImage = (imageData) => {
            // 更新选中状态
            document.querySelectorAll('.gallery-image-item').forEach(item => {
                item.classList.remove('selected');
            });
            event.currentTarget.classList.add('selected');

            // 启用使用按钮
            document.getElementById('useSelectedBtn').disabled = false;

            // 保存选中的图片数据
            window.selectedImageData = imageData;
        };

        window.useSelectedImage = () => {
            if (window.selectedImageData) {
                window.closeGalleryDialog(window.selectedImageData);
            }
        };
    });
}

// 显示进度提示
function showProgressToast(message) {
    const toast = document.createElement('div');
    toast.className = 'progress-toast';
    toast.innerHTML = `
        <div class="progress-toast-content">
            <div class="progress-toast-icon">
                <i class="fas fa-spinner fa-spin"></i>
            </div>
            <div class="progress-toast-text">
                <div class="progress-message">${message}</div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: 0%"></div>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(toast);

    // 添加样式
    if (!document.getElementById('progress-toast-styles')) {
        const style = document.createElement('style');
        style.id = 'progress-toast-styles';
        style.textContent = `
            .progress-toast {
                position: fixed;
                top: 20px;
                right: 20px;
                background: var(--glass-bg);
                backdrop-filter: blur(10px);
                border: 1px solid var(--glass-border);
                border-radius: var(--border-radius-md);
                padding: var(--spacing-md);
                z-index: 25000;
                min-width: 300px;
                box-shadow: 0 8px 25px rgba(31, 38, 135, 0.2);
                animation: slideInRight 0.3s ease;
            }

            .progress-toast-content {
                display: flex;
                align-items: center;
                gap: var(--spacing-sm);
            }

            .progress-toast-icon {
                color: var(--primary-color);
                font-size: 1.2rem;
            }

            .progress-toast-text {
                flex: 1;
            }

            .progress-message {
                font-size: 0.875rem;
                font-weight: 600;
                color: var(--text-primary);
                margin-bottom: var(--spacing-xs);
            }

            .progress-bar {
                height: 4px;
                background: rgba(0,0,0,0.1);
                border-radius: 2px;
                overflow: hidden;
            }

            .progress-fill {
                height: 100%;
                background: var(--primary-gradient);
                transition: width 0.3s ease;
            }

            @keyframes slideInRight {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    }

    return toast;
}

// 更新进度提示
function updateProgressToast(toast, message, progress) {
    const messageEl = toast.querySelector('.progress-message');
    const fillEl = toast.querySelector('.progress-fill');

    if (messageEl) messageEl.textContent = message;
    if (fillEl) fillEl.style.width = `${progress}%`;
}

// 关闭进度提示
function closeProgressToast(toast) {
    if (toast && toast.parentNode) {
        toast.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }
}

// 显示撤销选项
function showUndoOption(originalHtmlContent, slideIndex, operationType = '图像重新生成') {
    const undoToast = document.createElement('div');
    undoToast.className = 'undo-toast';

    const operationMessages = {
        '图像重新生成': { icon: 'fa-sync', message: '图像已重新生成' },
        '图像删除': { icon: 'fa-trash', message: '图像已删除' },
        '图像替换': { icon: 'fa-images', message: '图像已替换' }
    };

    const operation = operationMessages[operationType] || operationMessages['图像重新生成'];

    undoToast.innerHTML = `
        <div class="undo-toast-content">
            <div class="undo-message">
                <i class="fas fa-check-circle text-success"></i>
                ${operation.message}
            </div>
            <button class="undo-btn" onclick="undoImageRegeneration('${slideIndex}', this)">
                <i class="fas fa-undo"></i> 撤销
            </button>
        </div>
    `;

    // 保存原始内容和操作类型到按钮的数据属性中
    const undoBtn = undoToast.querySelector('.undo-btn');
    undoBtn.setAttribute('data-original-content', originalHtmlContent);
    undoBtn.setAttribute('data-operation-type', operationType);

    document.body.appendChild(undoToast);

    // 添加样式
    if (!document.getElementById('undo-toast-styles')) {
        const style = document.createElement('style');
        style.id = 'undo-toast-styles';
        style.textContent = `
            .undo-toast {
                position: fixed;
                bottom: 20px;
                right: 20px;
                background: var(--glass-bg);
                backdrop-filter: blur(10px);
                border: 1px solid var(--glass-border);
                border-radius: var(--border-radius-md);
                padding: var(--spacing-md);
                z-index: 25000;
                box-shadow: 0 8px 25px rgba(31, 38, 135, 0.2);
                animation: slideInUp 0.3s ease;
            }

            .undo-toast-content {
                display: flex;
                align-items: center;
                gap: var(--spacing-md);
            }

            .undo-message {
                font-size: 0.875rem;
                color: var(--text-primary);
            }

            .undo-btn {
                background: var(--accent-gradient);
                border: none;
                color: white;
                padding: var(--spacing-xs) var(--spacing-sm);
                border-radius: var(--border-radius-sm);
                font-size: 0.8125rem;
                cursor: pointer;
                transition: all 0.2s ease;
            }

            .undo-btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 15px rgba(67, 233, 123, 0.3);
            }

            @keyframes slideInUp {
                from { transform: translateY(100%); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    }

    // 15秒后自动隐藏
    setTimeout(() => {
        if (undoToast.parentNode) {
            undoToast.style.animation = 'slideOutDown 0.3s ease';
            setTimeout(() => {
                if (undoToast.parentNode) {
                    undoToast.parentNode.removeChild(undoToast);
                }
            }, 300);
        }
    }, 5000);
}

// 撤销图像操作（重新生成、删除、替换）
async function undoImageRegeneration(slideIndex, button) {
    const originalContent = button.getAttribute('data-original-content');
    const operationType = button.getAttribute('data-operation-type') || '图像重新生成';
    if (!originalContent) return;

    try {
        // 恢复原始内容
        slidesData[slideIndex].html_content = originalContent;

        // 更新预览
        if (slideIndex == currentSlideIndex) {
            const slideFrame = document.getElementById('slideFrame');
            if (slideFrame) {
                setSafeIframeContent(slideFrame, originalContent);
                setTimeout(() => {
                    forceReinitializeIframeJS(slideFrame);
                }, 300);
            }
        }

        // 更新缩略图
        const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[slideIndex];
        if (thumbnailIframe) {
            setSafeIframeContent(thumbnailIframe, originalContent);
        }

        // 保存到服务器
        await saveToServer();

        // 移除撤销提示
        const undoToast = button.closest('.undo-toast');
        if (undoToast && undoToast.parentNode) {
            undoToast.parentNode.removeChild(undoToast);
        }

        showNotification(`已撤销${operationType}`, 'info');

    } catch (error) {
        showNotification('撤销操作失败', 'error');
    }
}

// 从HTML中删除图像（保持完整HTML结构）
function removeImageFromHtml(htmlContent, imageInfo) {
    try {
        const imageType = imageInfo.type || 'img';
        const oldSrc = imageInfo.src || '';

        let updatedHtml = htmlContent;
        let removed = false;

        if (imageType === 'img') {
            // 使用正则表达式删除整个img标签
            const imgRegex = new RegExp(
                `<img[^>]*src=["'][^"']*${escapeRegExp(oldSrc.split('/').pop())}[^"']*["'][^>]*>`,
                'gi'
            );

            if (imgRegex.test(htmlContent)) {
                updatedHtml = htmlContent.replace(imgRegex, '');
                removed = true;
            } else {
                // 后备方案：查找包含特定src的img标签
                const fallbackRegex = new RegExp(
                    `<img[^>]*src=["'][^"']*${escapeRegExp(oldSrc)}[^"']*["'][^>]*>`,
                    'gi'
                );
                if (fallbackRegex.test(htmlContent)) {
                    updatedHtml = htmlContent.replace(fallbackRegex, '');
                    removed = true;
                }
            }
        } else if (imageType === 'background') {
            // 删除背景图像样式，但保留元素和其他样式
            const bgRegex = new RegExp(
                `(style=["'][^"']*?)background-image:\\s*url\\([^)]*${escapeRegExp(oldSrc.split('/').pop())}[^)]*\\);?([^"']*?["'])`,
                'gi'
            );

            if (bgRegex.test(htmlContent)) {
                updatedHtml = htmlContent.replace(bgRegex, (match, before, after) => {
                    // 清理可能的多余分号和空格
                    const cleanBefore = before.replace(/;\s*$/, '');
                    const cleanAfter = after.replace(/^\s*;/, '');

                    if (cleanBefore.trim() === 'style="' && cleanAfter.trim() === '"') {
                        // 如果style属性变空，则完全移除
                        return '';
                    } else {
                        return cleanBefore + (cleanBefore.endsWith(';') ? '' : ';') + cleanAfter;
                    }
                });
                removed = true;
            }
        } else if (imageType === 'svg') {
            // SVG删除相对复杂，这里提供基本支持
            if (imageInfo.outerHTML) {
                const svgContent = imageInfo.outerHTML.substring(0, 100); // 取前100字符作为匹配
                if (htmlContent.includes(svgContent)) {
                    // 尝试找到完整的SVG标签
                    const svgRegex = /<svg[^>]*>[\s\S]*?<\/svg>/gi;
                    const svgMatches = htmlContent.match(svgRegex);

                    if (svgMatches) {
                        for (const svgMatch of svgMatches) {
                            if (svgMatch.includes(svgContent)) {
                                updatedHtml = htmlContent.replace(svgMatch, '');
                                removed = true;
                                break;
                            }
                        }
                    }
                }
            }
        }

        // 清理可能产生的多余空白
        if (removed) {
            updatedHtml = updatedHtml.replace(/\s{2,}/g, ' ').trim();
        }

        return removed ? updatedHtml : htmlContent;

    } catch (error) {
        return htmlContent;
    }
}

// 图片库状态管理
let galleryState = {
    allImages: [],
    filteredImages: [],
    currentPage: 1,
    pageSize: 24,
    searchTerm: '',
    categoryFilter: ''
};

// 初始化图片库
async function initImageGallery() {
    try {
        // 自动分页加载所有图片
        const allImages = await loadAllImages();

        if (allImages.length > 0) {
            galleryState.allImages = allImages;
            galleryState.filteredImages = [...allImages];
            renderImageGallery();
        } else {
            showEmptyGallery();
        }

    } catch (error) {
        showGalleryError(error.message);
    }
}

// 加载所有图片（自动分页）
async function loadAllImages() {
    const allImages = [];
    let currentPage = 1;
    let hasMore = true;

    while (hasMore) {
        try {
            const response = await fetch(`/api/image/gallery/list?page=${currentPage}&per_page=50`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            if (result.success && result.images && result.images.length > 0) {
                allImages.push(...result.images);

                // 检查是否还有更多页面
                hasMore = result.pagination && result.pagination.has_next;
                currentPage++;
            } else {
                hasMore = false;
            }
        } catch (error) {
            hasMore = false;
        }
    }

    return allImages;
}

// 渲染图片库
function renderImageGallery() {
    const container = document.getElementById('imageGalleryContainer');
    if (!container) return;

    const { filteredImages, currentPage, pageSize } = galleryState;

    if (filteredImages.length === 0) {
        showEmptyGallery();
        return;
    }

    // 计算分页
    const totalPages = Math.ceil(filteredImages.length / pageSize);
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize, filteredImages.length);
    const currentImages = filteredImages.slice(startIndex, endIndex);

    // 渲染图片网格
    const imagesHtml = currentImages.map(image => `
        <div class="col-lg-2 col-md-3 col-sm-4 col-6">
            <div class="gallery-image-item"
                 onclick="selectGalleryImage({
                     id: '${image.id}',
                     url: '${image.url}',
                     title: '${escapeHtml(image.title || '')}',
                     alt: '${escapeHtml(image.alt_text || image.title || '')}',
                     width: ${image.width || 0},
                     height: ${image.height || 0},
                     category: '${image.category || image.source || ''}',
                     description: '${escapeHtml(image.description || '')}'
                 })"
                 ondblclick="handleImageDoubleClick({
                     id: '${image.id}',
                     url: '${image.url}',
                     title: '${escapeHtml(image.title || '')}',
                     alt: '${escapeHtml(image.alt_text || image.title || '')}',
                     width: ${image.width || 0},
                     height: ${image.height || 0},
                     category: '${image.category || image.source || ''}',
                     description: '${escapeHtml(image.description || '')}'
                 })"
                 style="cursor: pointer; border: 2px solid transparent; border-radius: 8px; padding: 8px; transition: all 0.2s ease; position: relative;">
                <div class="image-wrapper" style="position: relative; overflow: hidden; border-radius: 4px;">
                    <img src="${getImageUrl(image)}" alt="${escapeHtml(image.alt_text || image.title || '')}"
                         style="width: 100%; height: 120px; object-fit: cover; transition: transform 0.2s ease;"
                         onload="this.style.opacity='1'; this.parentElement.querySelector('.loading-spinner').style.display='none';"
                         onerror="handleImageError(this, '${image.id}');">
                    <div class="loading-spinner" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #ccc;">
                        <i class="fas fa-spinner fa-spin"></i>
                    </div>
                    <div class="image-overlay" style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); opacity: 0; transition: opacity 0.2s ease; display: flex; align-items: center; justify-content: center;">
                        <i class="fas fa-eye text-white" style="font-size: 1.5rem;"></i>
                    </div>
                </div>
                <div class="text-center mt-2">
                    <small class="d-block text-truncate fw-bold">${escapeHtml(image.title || '未命名图片')}</small>
                    <small class="text-muted">${image.width || 0} × ${image.height || 0}</small>
                    ${getImageCategoryBadge(image)}
                </div>
            </div>
        </div>
    `).join('');

    container.innerHTML = `
        <div class="row g-3">
            ${imagesHtml}
        </div>
        <style>
            .gallery-image-item:hover {
                border-color: #007bff !important;
                background-color: rgba(0, 123, 255, 0.1);
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(0, 123, 255, 0.2);
            }
            .gallery-image-item:hover .image-overlay {
                opacity: 1;
            }
            .gallery-image-item:hover img {
                transform: scale(1.05);
            }
            .gallery-image-item.selected {
                border-color: #28a745 !important;
                background-color: rgba(40, 167, 69, 0.1);
                box-shadow: 0 0 0 3px rgba(40, 167, 69, 0.2);
            }
        </style>
    `;

    // 更新分页和统计信息
    updatePagination(totalPages);
    updateStats(startIndex + 1, endIndex, filteredImages.length);
}

// 更新分页
function updatePagination(totalPages) {
    const paginationList = document.getElementById('paginationList');
    if (!paginationList) return;

    const { currentPage } = galleryState;
    let paginationHtml = '';

    // 上一页
    paginationHtml += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToPage(${currentPage - 1}); return false;">
                <i class="fas fa-chevron-left"></i>
            </a>
        </li>
    `;

    // 页码
    const maxVisiblePages = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

    if (endPage - startPage < maxVisiblePages - 1) {
        startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }

    for (let i = startPage; i <= endPage; i++) {
        paginationHtml += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="goToPage(${i}); return false;">${i}</a>
            </li>
        `;
    }

    // 下一页
    paginationHtml += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToPage(${currentPage + 1}); return false;">
                <i class="fas fa-chevron-right"></i>
            </a>
        </li>
    `;

    paginationList.innerHTML = paginationHtml;
}

// 更新统计信息
function updateStats(start, end, total) {
    const statsElement = document.getElementById('imageStats');
    if (statsElement) {
        statsElement.textContent = `显示 ${start}-${end} 项，共 ${total} 张图片`;
    }
}

// 初始化CodeMirror编辑器
function initializeCodeMirror() {
    const textareaElement = document.getElementById('codeEditor');
    if (!textareaElement || isCodeMirrorInitialized) return;

    try {
        // 创建CodeMirror实例
        codeMirrorEditor = CodeMirror.fromTextArea(textareaElement, {
            mode: 'htmlmixed',
            theme: 'material',
            lineNumbers: true,
            lineWrapping: true,
            autoCloseTags: true,
            autoCloseBrackets: true,
            matchTags: true,
            foldGutter: true,
            gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
            indentUnit: 2,
            tabSize: 2,
            indentWithTabs: false,
            extraKeys: {
                // 保存功能
                'Ctrl-S': function (cm) {
                    saveSlide();
                },
                'Cmd-S': function (cm) {
                    saveSlide();
                },
                // 搜索功能
                'Ctrl-F': 'findPersistent',
                'Cmd-F': 'findPersistent',
                // 查找替换功能
                'Ctrl-H': 'replace',
                'Cmd-Alt-F': 'replace',
                'Ctrl-Shift-H': 'replace',
                // 查找下一个/上一个
                'Ctrl-G': 'findNext',
                'Cmd-G': 'findNext',
                'Shift-Ctrl-G': 'findPrev',
                'Shift-Cmd-G': 'findPrev',
                'F3': 'findNext',
                'Shift-F3': 'findPrev',
                // ESC键关闭搜索对话框
                'Esc': function (cm) {
                    if (cm.state.search && cm.state.search.overlay) {
                        cm.execCommand('clearSearch');
                    }
                }
            }
        });

        // 设置编辑器样式 - 使用具体的高度计算
        codeMirrorEditor.setSize('100%', 'auto');

        // 强制刷新编辑器以确保正确的尺寸
        setTimeout(() => {
            codeMirrorEditor.refresh();
            // 计算并设置正确的高度
            const editPane = document.getElementById('editPane');
            if (editPane) {
                const rect = editPane.getBoundingClientRect();
                const height = Math.max(400, rect.height - 40); // 减去padding，最小400px
                codeMirrorEditor.setSize('100%', height + 'px');
            }
        }, 200);

        // 绑定内容变化事件
        codeMirrorEditor.on('change', function (cm) {
            clearTimeout(cm.saveTimeout);
            cm.saveTimeout = setTimeout(() => {
                if (currentMode === 'split') {
                    // Auto-update preview in split mode
                    const slideFrame = document.getElementById('slideFrame');
                    if (slideFrame && slidesData[currentSlideIndex]) {
                        const newContent = codeMirrorEditor.getValue();
                        slidesData[currentSlideIndex].html_content = newContent;
                        setSafeIframeContent(slideFrame, newContent);
                    }
                }
            }, 500);
        });

        isCodeMirrorInitialized = true;

        // 添加搜索功能的增强配置
        codeMirrorEditor.on('cursorActivity', function (cm) {
            // 当光标移动时，如果有搜索状态，保持高亮
            if (cm.state.search && cm.state.search.query) {
                // 搜索功能已激活，保持高亮状态
            }
        });

        // 恢复用户的主题偏好
        setTimeout(() => {
            restoreCodeMirrorTheme();
        }, 100);
    } catch (error) {
        // 如果CodeMirror初始化失败，保持使用原始textarea
    }
}

// 切换CodeMirror主题
function changeCodeMirrorTheme(themeName) {
    if (codeMirrorEditor && isCodeMirrorInitialized) {
        codeMirrorEditor.setOption('theme', themeName);

        // 保存主题偏好到localStorage
        localStorage.setItem('codeMirrorTheme', themeName);

        // 更新下拉菜单显示
        const themeDropdown = document.getElementById('themeDropdown');
        if (themeDropdown) {
            const themeNames = {
                'material': 'Material Dark',
                'monokai': 'Monokai',
                'dracula': 'Dracula',
                'default': '默认浅色'
            };
            themeDropdown.innerHTML = `<i class="fas fa-palette"></i> ${themeNames[themeName] || themeName}`;
        }
    } else {
        // CodeMirror编辑器未初始化，无法切换主题
    }
}

// 从localStorage恢复主题偏好
function restoreCodeMirrorTheme() {
    const savedTheme = localStorage.getItem('codeMirrorTheme');
    if (savedTheme && codeMirrorEditor && isCodeMirrorInitialized) {
        changeCodeMirrorTheme(savedTheme);
    }
}

// 重新计算CodeMirror编辑器的尺寸
function resizeCodeMirror() {
    if (codeMirrorEditor && isCodeMirrorInitialized) {
        const editPane = document.getElementById('editPane');
        if (editPane && editPane.style.display !== 'none') {
            // 刷新编辑器以重新计算尺寸
            codeMirrorEditor.refresh();

            // 设置正确的高度
            const rect = editPane.getBoundingClientRect();
            const height = Math.max(400, rect.height - 40); // 减去padding，最小400px
            if (height > 0) {
                codeMirrorEditor.setSize('100%', height + 'px');
            }
        }
    }
}



// 初始化侧栏宽度调整功能
function initializeSidebarResize() {
    const resizeHandle = document.getElementById('aiSidebarResizeHandle');
    const sidebar = document.getElementById('aiEditSidebar');

    if (!resizeHandle || !sidebar) return;

    resizeHandle.addEventListener('mousedown', (e) => {
        isResizingSidebar = true;
        sidebarStartWidth = sidebar.offsetWidth;
        sidebarStartX = e.clientX;

        document.addEventListener('mousemove', handleSidebarResize);
        document.addEventListener('mouseup', stopSidebarResize);

        e.preventDefault();
    });
}

function handleSidebarResize(e) {
    if (!isResizingSidebar) return;

    const sidebar = document.getElementById('aiEditSidebar');
    if (!sidebar) return;

    const deltaX = sidebarStartX - e.clientX; // 向左拖拽为正值
    const newWidth = Math.max(400, Math.min(800, sidebarStartWidth + deltaX));

    sidebar.style.width = newWidth + 'px';
    sidebar.style.right = sidebar.classList.contains('open') ? '0' : `-${newWidth}px`;
}

function stopSidebarResize() {
    isResizingSidebar = false;
    document.removeEventListener('mousemove', handleSidebarResize);
    document.removeEventListener('mouseup', stopSidebarResize);
}

// AI编辑侧栏控制函数
function openAIEditSidebar() {
    const sidebar = document.getElementById('aiEditSidebar');
    const overlay = document.getElementById('aiSidebarOverlay');

    sidebar.classList.add('open');
    overlay.classList.add('show');

    // 更新当前页数显示
    updateAICurrentSlideInfo();

    // 聚焦到输入框
    setTimeout(() => {
        document.getElementById('aiInputBox').focus();
    }, 300);
}

function closeAIEditSidebar() {
    const sidebar = document.getElementById('aiEditSidebar');
    const overlay = document.getElementById('aiSidebarOverlay');

    sidebar.classList.remove('open');
    overlay.classList.remove('show');
}

// 快捷重新生成功能
function quickRegenerateSlide() {
    if (currentSlideIndex >= 0 && currentSlideIndex < slidesData.length) {
        // 使用与enhanced_ppt_service.py相同的重新生成逻辑
        regenerateSlideByIndex(currentSlideIndex);
        closeAIEditSidebar();
    } else {
        showNotification('请先选择一个幻灯片', 'warning');
    }
}

