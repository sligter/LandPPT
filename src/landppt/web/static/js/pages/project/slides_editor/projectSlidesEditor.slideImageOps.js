function updateEditorContentModeClass(mode) {
    const editorContent = document.querySelector('.editor-content');
    if (!editorContent) {
        return;
    }

    editorContent.classList.remove(
        'is-preview-mode',
        'is-edit-mode',
        'is-split-mode',
        'is-quickedit-mode'
    );

    editorContent.classList.add(`is-${mode}-mode`);
}

function refreshEditorViewport(options = {}) {
    const { refreshPreview = false, refreshEditor = false } = options || {};

    setTimeout(() => {
        if (refreshPreview && typeof requestMainFrameScaleRefresh === 'function') {
            requestMainFrameScaleRefresh();
        }

        if (refreshEditor && typeof resizeCodeMirror === 'function') {
            resizeCodeMirror();
        }
    }, 100);
}

function setMode(mode) {

    currentMode = mode;
    updateEditorContentModeClass(mode);

    // Update button states
    document.querySelectorAll('#previewMode,#editMode,#splitMode,#quickEditMode').forEach(btn => btn.classList.remove('active'));

    // 处理按钮ID映射
    let buttonId;
    switch (mode) {
        case 'quickedit':
            buttonId = 'quickEditMode';
            break;
        default:
            buttonId = mode + 'Mode';
            break;
    }

    const modeButton = document.getElementById(buttonId);
    if (modeButton) {
        modeButton.classList.add('active');
    } else {
        // Mode button not found
    }

    const previewPane = document.getElementById('previewPane');
    const editPane = document.getElementById('editPane');

    if (!previewPane || !editPane) {
        // Required panes not found
        return;
    }

    switch (mode) {
        case 'preview':
            previewPane.style.display = 'block';
            previewPane.style.flex = '';
            editPane.style.display = 'none';
            editPane.style.flex = '';
            if (typeof disableQuickEdit === 'function') {
                disableQuickEdit();
            }
            refreshEditorViewport({ refreshPreview: true });
            break;
        case 'edit':
            previewPane.style.display = 'none';
            editPane.style.display = 'block';
            editPane.style.flex = '';
            if (typeof disableQuickEdit === 'function') {
                disableQuickEdit();
            }
            // 编辑模式切换后重算代码编辑器尺寸，避免容器尺寸沿用旧值
            refreshEditorViewport({ refreshEditor: true });
            break;
        case 'split':
            previewPane.style.display = 'block';
            previewPane.style.flex = '';
            editPane.style.display = 'block';
            editPane.style.flex = '';
            if (typeof disableQuickEdit === 'function') {
                disableQuickEdit();
            }
            // 分屏布局切换后同时重算编辑器和主预览，避免预览沿用旧缩放被右侧遮挡
            refreshEditorViewport({ refreshPreview: true, refreshEditor: true });
            break;
        case 'quickedit':
            previewPane.style.display = 'block';
            previewPane.style.flex = '1';
            editPane.style.display = 'none';
            editPane.style.flex = '';
            if (typeof enableQuickEdit === 'function') {
                enableQuickEdit();
            }
            refreshEditorViewport({ refreshPreview: true });
            break;
        default:
            // Unknown mode
            break;
    }
}

async function saveSlide() {
    const codeEditor = document.getElementById('codeEditor');
    let newContent;

    if (codeMirrorEditor && isCodeMirrorInitialized) {
        newContent = codeMirrorEditor.getValue();
    } else {
        newContent = codeEditor.value;
    }

    // Update slides data
    if (slidesData[currentSlideIndex]) {
        slidesData[currentSlideIndex].html_content = newContent;
        if (typeof setInitialSlideState === 'function') {
            setInitialSlideState(currentSlideIndex, newContent);
        }

        // Update preview
        const slideFrame = document.getElementById('slideFrame');
        setSafeIframeContent(slideFrame, newContent);

        // 延迟重新初始化JavaScript以确保内容加载完成
        setTimeout(() => {
            forceReinitializeIframeJS(slideFrame);
        }, 300);

        // Update thumbnail
        const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[currentSlideIndex];
        if (thumbnailIframe) {
            setSafeIframeContent(thumbnailIframe, newContent);
            // 缩略图不需要重新初始化JavaScript，避免性能问题
        }

        // Save to server
        try {
            // 如果当前项目存在缺页并已做归一化，为避免“批量保存把占位页写入数据库”，这里改为只保存当前页
            const saved = slidesDataWasNormalized
                ? await saveSingleSlideToServer(currentSlideIndex, newContent)
                : await saveToServer();

            if (saved) {
                showNotification('幻灯片已保存！', 'success');
            } else {
                showNotification('保存失败，请重试', 'error');
            }
        } catch (e) {
            showNotification('保存失败：' + (e?.message || e), 'error');
        }
    }
}

function regenerateSlide() {
    regenerateSlideByIndex(currentSlideIndex);
}

// 更新AI编辑助手中的当前页数显示
function updateAICurrentSlideInfo() {
    const slideInfo = document.getElementById('aiCurrentSlideInfo');
    if (slideInfo && slidesData && slidesData.length > 0) {
        slideInfo.textContent = `第${currentSlideIndex + 1}页 / 共${slidesData.length}页`;
    }


}

// 更新AI助手中选中图像的信息显示
function updateAIAssistantSelectedImage(imageInfo) {
    // 检查是否已存在选中图像信息区域
    let selectedImageContainer = document.getElementById('aiSelectedImageContainer');

    if (!selectedImageContainer) {
        // 创建选中图像信息容器
        selectedImageContainer = document.createElement('div');
        selectedImageContainer.id = 'aiSelectedImageContainer';
        selectedImageContainer.className = 'ai-selected-image-container';

        // 插入到AI输入容器之前
        const inputContainer = document.querySelector('.ai-input-container');
        if (inputContainer) {
            inputContainer.parentNode.insertBefore(selectedImageContainer, inputContainer);
        }
    }

    if (imageInfo) {
        // 显示选中图像信息
        selectedImageContainer.innerHTML = `
            <div class="ai-selected-image-header">
                <h6><i class="fas fa-image"></i> 已选择图像</h6>
                <button class="ai-clear-selection-btn" onclick="clearImageSelection()" title="清除选择">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="ai-selected-image-info">
                <div class="ai-selected-image-preview">
                    <img src="${imageInfo.src}" alt="${imageInfo.alt}" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjYwIiBoZWlnaHQ9IjYwIiBmaWxsPSIjRjBGMEYwIi8+CjxwYXRoIGQ9Ik0yMCAyMEg0MFY0MEgyMFYyMFoiIGZpbGw9IiNDQ0NDQ0MiLz4KPC9zdmc+Cg=='">
                </div>
                <div class="ai-selected-image-details">
                    <div class="ai-image-detail-item">
                        <span class="ai-detail-label">类型:</span>
                        <span class="ai-detail-value">${getImageTypeDisplay(imageInfo.type)}</span>
                    </div>
                    <div class="ai-image-detail-item">
                        <span class="ai-detail-label">尺寸:</span>
                        <span class="ai-detail-value">${Math.round(imageInfo.width)} × ${Math.round(imageInfo.height)}</span>
                    </div>
                    <div class="ai-image-detail-item">
                        <span class="ai-detail-label">位置:</span>
                        <span class="ai-detail-value">第${imageInfo.slideIndex + 1}页</span>
                    </div>
                    ${imageInfo.alt ? `
                    <div class="ai-image-detail-item">
                        <span class="ai-detail-label">描述:</span>
                        <span class="ai-detail-value">${imageInfo.alt}</span>
                    </div>
                    ` : ''}
                    ${imageInfo.isBackgroundImage ? `
                    <div class="ai-image-detail-item">
                        <span class="ai-detail-label">背景:</span>
                        <span class="ai-detail-value">CSS背景图像</span>
                    </div>
                    ` : ''}
                </div>
            </div>
            <div class="ai-image-actions">
                <div class="ai-image-action-row">
                    <button class="ai-regenerate-image-btn" onclick="regenerateSelectedImage()" title="重新生成此图像">
                        <i class="fas fa-sync"></i> 重新生成
                    </button>
                    <button class="ai-replace-image-btn" onclick="replaceSelectedImageFromGallery()" title="从图床选择图片替换">
                        <i class="fas fa-images"></i> 选择替换
                    </button>
                </div>
                <div class="ai-image-action-row">
                    <button class="ai-upload-local-image-btn" onclick="triggerLocalImageUploadForReplace()" title="从本地上传图片替换">
                        <i class="fas fa-upload"></i> 本地上传
                    </button>
                    <button class="ai-delete-image-btn" onclick="deleteSelectedImage()" title="删除此图像">
                        <i class="fas fa-trash"></i> 删除图像
                    </button>
                </div>
            </div>
            <input type="file" id="localImageUploadForReplace" accept="image/*" style="display: none;" onchange="handleLocalImageUploadForReplace(event)">
        `;
        selectedImageContainer.style.display = 'block';
    } else {
        // 隐藏选中图像信息
        selectedImageContainer.style.display = 'none';
    }
}

// 清除图像选择
function clearImageSelection() {
    selectedImageInfo = null;

    // 清除幻灯片中的选择状态
    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame) {
        try {
            const iframeDoc = slideFrame.contentDocument || slideFrame.contentWindow.document;
            const selectedImages = iframeDoc.querySelectorAll('.image-selected');
            selectedImages.forEach(img => {
                img.classList.remove('image-selected');
                img.style.outline = '';
                img.style.outlineOffset = '';
                img.style.boxShadow = '';
                img.style.transform = '';
            });
        } catch (e) {
            // 清除图像选择状态失败
        }
    }

    // 更新AI助手界面
    updateAIAssistantSelectedImage(null);
}

// 重新生成选中的图像
async function regenerateSelectedImage() {
    if (!selectedImageInfo) {
        showNotification('请先选择要重新生成的图像', 'warning');
        return;
    }

    // 显示确认对话框
    const confirmed = await showImageRegenerateConfirmDialog();
    if (!confirmed) return;

    const regenerateBtn = document.querySelector('.ai-regenerate-image-btn');
    if (!regenerateBtn) return;

    // 保存原始状态用于撤销
    const originalHtmlContent = slidesData[selectedImageInfo.slideIndex].html_content;

    // 禁用按钮并显示加载状态
    const originalText = regenerateBtn.innerHTML;
    regenerateBtn.disabled = true;
    regenerateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 生成中...';

    // 显示进度提示
    const progressToast = showProgressToast('正在分析图像上下文...');

    try {
        // 更新进度
        updateProgressToast(progressToast, '正在生成新图像...', 30);

        // 构建重新生成请求
        const requestData = {
            slide_index: selectedImageInfo.slideIndex,
            image_info: selectedImageInfo,
            slide_content: {
                title: selectedImageInfo.slideTitle,
                html_content: slidesData[selectedImageInfo.slideIndex].html_content
            },
            project_topic: window.landpptEditorProjectInfo.topic,
            project_scenario: window.landpptEditorProjectInfo.scenario,
            regeneration_reason: '用户请求重新生成图像'
        };

        // 发送重新生成请求
        const response = await fetch('/api/ai/regenerate-image', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData)
        });

        const result = await response.json();

        if (result.success) {
            // 更新进度
            updateProgressToast(progressToast, '正在更新幻灯片...', 80);

            // 更新幻灯片内容
            if (result.updated_html_content) {
                slidesData[selectedImageInfo.slideIndex].html_content = result.updated_html_content;

                // 更新预览
                const slideFrame = document.getElementById('slideFrame');
                if (slideFrame && selectedImageInfo.slideIndex === currentSlideIndex) {
                    setSafeIframeContent(slideFrame, result.updated_html_content);
                    setTimeout(() => {
                        forceReinitializeIframeJS(slideFrame);
                    }, 300);
                }

                // 更新缩略图
                const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[selectedImageInfo.slideIndex];
                if (thumbnailIframe) {
                    setSafeIframeContent(thumbnailIframe, result.updated_html_content);
                }

                // 保存到服务器
                updateProgressToast(progressToast, '正在保存...', 90);
                await saveToServer();

                // 完成进度
                updateProgressToast(progressToast, '完成！', 100);

                // 显示撤销选项
                showUndoOption(originalHtmlContent, selectedImageInfo.slideIndex);

                // 清除选择状态
                clearImageSelection();

                // 关闭进度提示
                setTimeout(() => closeProgressToast(progressToast), 1000);

                showNotification('图像重新生成成功！', 'success');
            } else {
                closeProgressToast(progressToast);
                showNotification('图像生成成功，但更新失败', 'warning');
            }
        } else {
            closeProgressToast(progressToast);
            showNotification(result.message || '图像重新生成失败', 'error');
        }

    } catch (error) {
        closeProgressToast(progressToast);
        showNotification('网络错误，请重试', 'error');
    } finally {
        // 恢复按钮状态
        regenerateBtn.disabled = false;
        regenerateBtn.innerHTML = originalText;
    }
}

// 删除选中的图像
async function deleteSelectedImage() {
    if (!selectedImageInfo) {
        showNotification('请先选择要删除的图像', 'warning');
        return;
    }

    // 显示确认对话框
    const confirmed = await showImageDeleteConfirmDialog();
    if (!confirmed) return;

    try {
        // 保存原始状态用于撤销
        const originalHtmlContent = slidesData[selectedImageInfo.slideIndex].html_content;

        // 从HTML中删除图像
        const updatedHtml = removeImageFromHtml(
            slidesData[selectedImageInfo.slideIndex].html_content,
            selectedImageInfo
        );

        if (updatedHtml === slidesData[selectedImageInfo.slideIndex].html_content) {
            showNotification('未找到要删除的图像', 'warning');
            return;
        }

        // 更新幻灯片内容
        slidesData[selectedImageInfo.slideIndex].html_content = updatedHtml;

        // 更新预览
        const slideFrame = document.getElementById('slideFrame');
        if (slideFrame && selectedImageInfo.slideIndex === currentSlideIndex) {
            setSafeIframeContent(slideFrame, updatedHtml);
            setTimeout(() => {
                forceReinitializeIframeJS(slideFrame);
            }, 300);
        }

        // 更新缩略图
        const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[selectedImageInfo.slideIndex];
        if (thumbnailIframe) {
            setSafeIframeContent(thumbnailIframe, updatedHtml);
        }

        // 保存到服务器
        await saveToServer();

        // 显示撤销选项
        showUndoOption(originalHtmlContent, selectedImageInfo.slideIndex, '图像删除');

        // 清除选择状态
        clearImageSelection();

        showNotification('图像删除成功！', 'success');

    } catch (error) {
        showNotification('删除图像失败，请重试', 'error');
    }
}

// 从图床选择图片替换选中的图像
async function replaceSelectedImageFromGallery() {
    if (!selectedImageInfo) {
        showNotification('请先选择要替换的图像', 'warning');
        return;
    }

    try {
        // 显示图片选择对话框
        const selectedImage = await showImageGalleryDialog();
        if (!selectedImage) return;

        // 保存原始状态用于撤销
        const originalHtmlContent = slidesData[selectedImageInfo.slideIndex].html_content;

        // 构建新图像URL
        const newImageUrl = selectedImage.url;

        // 替换HTML中的图像
        const updatedHtml = replaceImageInHtmlClient(
            slidesData[selectedImageInfo.slideIndex].html_content,
            selectedImageInfo,
            newImageUrl
        );

        if (updatedHtml === slidesData[selectedImageInfo.slideIndex].html_content) {
            showNotification('图像替换失败', 'warning');
            return;
        }

        // 更新幻灯片内容
        slidesData[selectedImageInfo.slideIndex].html_content = updatedHtml;

        // 更新预览
        const slideFrame = document.getElementById('slideFrame');
        if (slideFrame && selectedImageInfo.slideIndex === currentSlideIndex) {
            setSafeIframeContent(slideFrame, updatedHtml);
            setTimeout(() => {
                forceReinitializeIframeJS(slideFrame);
            }, 300);
        }

        // 更新缩略图
        const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[selectedImageInfo.slideIndex];
        if (thumbnailIframe) {
            setSafeIframeContent(thumbnailIframe, updatedHtml);
        }

        // 保存到服务器
        await saveToServer();

        // 显示撤销选项
        showUndoOption(originalHtmlContent, selectedImageInfo.slideIndex, '图像替换');

        // 清除选择状态
        clearImageSelection();

        showNotification('图像替换成功！', 'success');

    } catch (error) {
        showNotification('替换图像失败，请重试', 'error');
    }
}

// 触发本地图片上传用于替换选中图像
function triggerLocalImageUploadForReplace() {
    if (!selectedImageInfo) {
        showNotification('请先选择要替换的图像', 'warning');
        return;
    }

    // 创建或获取隐藏的文件输入
    let fileInput = document.getElementById('localImageUploadForReplace');
    if (!fileInput) {
        fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.id = 'localImageUploadForReplace';
        fileInput.accept = 'image/*';
        fileInput.style.display = 'none';
        fileInput.onchange = handleLocalImageUploadForReplace;
        document.body.appendChild(fileInput);
    }

    // 清除之前的值以便重新选择相同文件
    fileInput.value = '';
    fileInput.click();
}

// 处理本地图片上传并替换选中图像
async function handleLocalImageUploadForReplace(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (!selectedImageInfo) {
        showNotification('请先选择要替换的图像', 'warning');
        return;
    }

    // 验证文件类型
    if (!file.type.startsWith('image/')) {
        showNotification('请选择有效的图片文件', 'error');
        return;
    }

    // 验证文件大小（最大10MB）
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
        showNotification('图片文件过大，请选择小于10MB的图片', 'error');
        return;
    }

    // 显示上传进度
    const progressToast = showProgressToast('正在上传图片...', 10);

    try {
        updateProgressToast(progressToast, '正在上传图片到服务器...', 30);

        // 上传文件
        const uploadResult = await uploadSingleFile(file);

        if (!uploadResult.success) {
            closeProgressToast(progressToast);
            showNotification(uploadResult.message || '图片上传失败', 'error');
            return;
        }

        updateProgressToast(progressToast, '正在替换图像...', 60);

        // 保存原始状态用于撤销
        const originalHtmlContent = slidesData[selectedImageInfo.slideIndex].html_content;

        // 获取新图像URL
        const newImageUrl = uploadResult.data.url;

        // 替换HTML中的图像
        const updatedHtml = replaceImageInHtmlClient(
            slidesData[selectedImageInfo.slideIndex].html_content,
            selectedImageInfo,
            newImageUrl
        );

        if (updatedHtml === slidesData[selectedImageInfo.slideIndex].html_content) {
            closeProgressToast(progressToast);
            showNotification('图像替换失败', 'warning');
            return;
        }

        updateProgressToast(progressToast, '正在更新预览...', 80);

        // 更新幻灯片内容
        slidesData[selectedImageInfo.slideIndex].html_content = updatedHtml;

        // 更新预览
        const slideFrame = document.getElementById('slideFrame');
        if (slideFrame && selectedImageInfo.slideIndex === currentSlideIndex) {
            setSafeIframeContent(slideFrame, updatedHtml);
            setTimeout(() => {
                forceReinitializeIframeJS(slideFrame);
            }, 300);
        }

        // 更新缩略图
        const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[selectedImageInfo.slideIndex];
        if (thumbnailIframe) {
            setSafeIframeContent(thumbnailIframe, updatedHtml);
        }

        // 保存到服务器
        await saveToServer();

        // 显示撤销选项
        showUndoOption(originalHtmlContent, selectedImageInfo.slideIndex, '本地图片替换');

        // 清除选择状态
        clearImageSelection();

        closeProgressToast(progressToast);
        showNotification('本地图片上传并替换成功！', 'success');

    } catch (error) {
        console.error('本地图片上传替换失败:', error);
        showNotification('替换图像失败，请重试', 'error');
    }
}

// 一键修复排版
async function autoRepairSlideLayout() {
    closeAIEditSidebar();
    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const slideInfo = slidesData[currentSlideIndex];
    if (!slideInfo || !slideInfo.html_content) {
        showNotification('当前幻灯片没有可修复的内容', 'warning');
        return;
    }

    const progressToast = showProgressToast('正在准备布局修复...', 5);

    try {
        updateProgressToast(progressToast, '正在生成幻灯片截图...', 20);

        const targetProjectId = projectId || slideInfo.project_id;
        updateProgressToast(progressToast, '正在进行智能排版修复...', 40);
        const response = await fetch(`/api/projects/${targetProjectId}/slides/${currentSlideIndex + 1}/auto-repair-layout`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                html_content: slideInfo.html_content,
                slide_data: slideInfo
            })
        });

        updateProgressToast(progressToast, '正在解析修复结果...', 60);
        const result = await response.json();

        if (!response.ok) {
            closeProgressToast(progressToast);
            console.error('Auto layout repair failed:', result);
            showNotification(result.message || '排版修复失败，请重试', 'error');
            return;
        }

        updateProgressToast(progressToast, '正在应用修复后的排版...', 80);

        if (result && result.repaired_html) {
            slidesData[currentSlideIndex].html_content = result.repaired_html;
            slidesData[currentSlideIndex].is_user_edited = true;

            await refreshSlidePreview(currentSlideIndex, { force: true });
            updateThumbnailDisplay(currentSlideIndex, slidesData[currentSlideIndex]);
            updateCodeEditorContent(result.repaired_html);

            updateProgressToast(progressToast, '正在保存最新内容...', 90);
            if (typeof saveToServer === 'function') {
                await saveToServer();
            }

            closeAIEditSidebar();
            showNotification('排版修复完成！', 'success');
            updateProgressToast(progressToast, '排版修复完成！', 100);
        } else {
            updateProgressToast(progressToast, '未检测到新的排版内容', 100);
            showNotification('排版修复未返回新内容', 'warning');
        }

        closeProgressToast(progressToast);

    } catch (error) {
        console.error('Auto layout repair error:', error);
        closeProgressToast(progressToast);
        showNotification('排版修复失败，请检查网络连接后重试', 'error');
    }
}

// 一键配图功能
async function autoGenerateSlideImages() {
    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const currentSlide = slidesData[currentSlideIndex];
    if (!currentSlide) {
        showNotification('当前幻灯片数据无效', 'error');
        return;
    }

    // 显示确认对话框
    const confirmed = await showAutoImageGenerateConfirmDialog();
    if (!confirmed) return;

    // 显示进度提示
    const progressToast = showProgressToast('正在分析幻灯片内容...');

    try {
        // 更新进度
        updateProgressToast(progressToast, '正在生成配图...', 30);

        // 构建一键配图请求
        const requestData = {
            slide_index: currentSlideIndex,
            slide_content: {
                title: currentSlide.title || `第${currentSlideIndex + 1}页`,
                html_content: currentSlide.html_content
            },
            project_topic: window.landpptEditorProjectInfo.topic,
            project_scenario: window.landpptEditorProjectInfo.scenario
        };

        // 发送一键配图请求
        const response = await fetch('/api/ai/auto-generate-slide-images', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData)
        });

        const result = await response.json();

        if (result.success) {
            // 更新进度
            updateProgressToast(progressToast, '正在更新幻灯片...', 80);

            // 更新幻灯片内容
            if (result.updated_html_content) {
                slidesData[currentSlideIndex].html_content = result.updated_html_content;

                // 更新预览
                const slideFrame = document.getElementById('slideFrame');
                if (slideFrame) {
                    setSafeIframeContent(slideFrame, result.updated_html_content);
                    setTimeout(() => {
                        forceReinitializeIframeJS(slideFrame);
                    }, 300);
                }

                // 更新缩略图
                const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[currentSlideIndex];
                if (thumbnailIframe) {
                    setSafeIframeContent(thumbnailIframe, result.updated_html_content);
                }

                // 更新代码编辑器
                if (codeMirrorEditor && isCodeMirrorInitialized) {
                    codeMirrorEditor.setValue(result.updated_html_content);
                } else {
                    const codeEditor = document.getElementById('codeEditor');
                    if (codeEditor) {
                        codeEditor.value = result.updated_html_content;
                    }
                }

                // 保存到服务器
                await saveToServer();

                // 完成进度
                updateProgressToast(progressToast, '配图完成！', 100);
                setTimeout(() => {
                    closeProgressToast(progressToast);
                }, 1500);

                // 显示成功消息
                const imageCount = result.generated_images_count || 0;
                showNotification(`一键配图完成！已为当前幻灯片生成${imageCount}张图片`, 'success');

                // 显示AI分析信息
                if (result.ai_analysis) {
                    addAIMessage('assistant', `配图分析：${result.ai_analysis.reasoning || '已完成图片生成和插入'}`);
                }

            } else {
                closeProgressToast(progressToast);
                showNotification('配图生成成功，但未能更新幻灯片内容', 'warning');
            }

        } else {
            closeProgressToast(progressToast);
            showNotification(result.message || '一键配图失败，请重试', 'error');
        }

    } catch (error) {
        closeProgressToast(progressToast);
        showNotification('一键配图失败，请检查网络连接后重试', 'error');
    }
}

// 显示一键配图确认对话框
async function showAutoImageGenerateConfirmDialog() {
    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.className = 'modal fade show';
        modal.style.display = 'block';
        modal.style.backgroundColor = 'rgba(0,0,0,0.5)';
        modal.style.zIndex = '20000';
        modal.innerHTML = `
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-magic text-primary"></i> 一键配图
                        </h5>
                    </div>
                    <div class="modal-body">
                        <p>AI将自动分析当前幻灯片内容，为其生成合适的配图并插入到适当位置。</p>
                        <div class="alert alert-info">
                            <i class="fas fa-info-circle"></i>
                            <strong>功能说明：</strong>
                            <ul class="mb-0 mt-2">
                                <li>AI会分析幻灯片的标题和内容</li>
                                <li>根据内容生成相关的图片描述和关键词</li>
                                <li>自动生成配图并插入到合适位置</li>
                                <li>保持原有的布局和样式</li>
                            </ul>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" onclick="closeAutoImageConfirmDialog(false)">取消</button>
                        <button type="button" class="btn btn-primary" onclick="closeAutoImageConfirmDialog(true)">
                            <i class="fas fa-magic"></i> 开始配图
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        window.closeAutoImageConfirmDialog = (confirmed) => {
            document.body.removeChild(modal);
            delete window.closeAutoImageConfirmDialog;
            resolve(confirmed);
        };
    });
}

// 用户体验优化功能

// 显示图像重新生成确认对话框
async function showImageRegenerateConfirmDialog() {
    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.className = 'modal fade show';
        modal.style.display = 'block';
        modal.style.backgroundColor = 'rgba(0,0,0,0.5)';
        modal.style.zIndex = '20000'; // 确保在AI助手侧边栏之上
        modal.innerHTML = `
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-sync text-primary"></i> 重新生成图像
                        </h5>
                    </div>
                    <div class="modal-body">
                        <p>确定要重新生成选中的图像吗？</p>
                        <div class="alert alert-info">
                            <i class="fas fa-info-circle"></i>
                            新图像将保持原有的位置和尺寸，但内容会根据幻灯片上下文重新生成。
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" onclick="closeConfirmDialog(false)">取消</button>
                        <button type="button" class="btn btn-primary" onclick="closeConfirmDialog(true)">
                            <i class="fas fa-sync"></i> 确定重新生成
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        window.closeConfirmDialog = (confirmed) => {
            document.body.removeChild(modal);
            delete window.closeConfirmDialog;
            resolve(confirmed);
        };
    });
}

// 显示图像删除确认对话框
async function showImageDeleteConfirmDialog() {
    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.className = 'modal fade show';
        modal.style.display = 'block';
        modal.style.backgroundColor = 'rgba(0,0,0,0.5)';
        modal.style.zIndex = '20000';
        modal.innerHTML = `
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-trash text-danger"></i> 删除图像
                        </h5>
                    </div>
                    <div class="modal-body">
                        <p>确定要删除选中的图像吗？</p>
                        <div class="alert alert-warning">
                            <i class="fas fa-exclamation-triangle"></i>
                            图像将从幻灯片中完全移除，但可以在5秒内撤销此操作。
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" onclick="closeDeleteDialog(false)">取消</button>
                        <button type="button" class="btn btn-danger" onclick="closeDeleteDialog(true)">
                            <i class="fas fa-trash"></i> 确定删除
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        window.closeDeleteDialog = (confirmed) => {
            document.body.removeChild(modal);
            delete window.closeDeleteDialog;
            resolve(confirmed);
        };
    });
}

// 显示图片库选择对话框
