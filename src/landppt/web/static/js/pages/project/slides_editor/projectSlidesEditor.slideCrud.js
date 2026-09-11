function handleDragStart(event, slideIndex) {
    draggedSlideIndex = slideIndex;
    event.target.classList.add('dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/html', event.target.outerHTML);
}

function handleDragOver(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';

    const thumbnail = event.currentTarget;
    const rect = thumbnail.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;

    // 清除所有指示器
    document.querySelectorAll('.drag-indicator').forEach(indicator => {
        indicator.classList.remove('show');
    });

    // 显示适当的指示器
    if (event.clientY < midY) {
        thumbnail.querySelector('.drag-indicator.top').classList.add('show');
    } else {
        thumbnail.querySelector('.drag-indicator.bottom').classList.add('show');
    }

    thumbnail.classList.add('drag-over');
}

function handleDrop(event, targetIndex) {
    event.preventDefault();

    if (draggedSlideIndex === -1 || draggedSlideIndex === targetIndex) {
        return;
    }

    const rect = event.currentTarget.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const insertBefore = event.clientY < midY;

    // 计算新的插入位置
    let newIndex = targetIndex;
    if (!insertBefore) {
        newIndex = targetIndex + 1;
    }

    // 如果拖拽的元素在目标位置之前，需要调整索引
    if (draggedSlideIndex < newIndex) {
        newIndex--;
    }

    // 移动幻灯片
    moveSlide(draggedSlideIndex, newIndex).catch((error) => {
        console.error('Move slide failed:', error);
        showNotification('移动幻灯片失败：' + (error?.message || error), 'error');
    });
}

function handleDragEnd(event) {
    event.target.classList.remove('dragging');
    document.querySelectorAll('.slide-thumbnail').forEach(thumb => {
        thumb.classList.remove('drag-over');
    });
    document.querySelectorAll('.drag-indicator').forEach(indicator => {
        indicator.classList.remove('show');
    });
    draggedSlideIndex = -1;
}

async function moveSlide(fromIndex, toIndex) {
    if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 ||
        fromIndex >= slidesData.length || toIndex > slidesData.length) {
        return;
    }

    // 移动数据
    const movedSlide = slidesData.splice(fromIndex, 1)[0];
    slidesData.splice(toIndex, 0, movedSlide);

    // 更新已选中的索引（保持选中的是同一组幻灯片，而不是同一组位置）
    if (selectedSlideIndices && selectedSlideIndices.size > 0) {
        const nextSelected = new Set();
        selectedSlideIndices.forEach((idx) => {
            if (!Number.isInteger(idx)) return;
            let nextIdx = idx;
            if (idx === fromIndex) {
                nextIdx = toIndex;
            } else if (fromIndex < toIndex) {
                if (idx > fromIndex && idx <= toIndex) nextIdx = idx - 1;
            } else if (fromIndex > toIndex) {
                if (idx >= toIndex && idx < fromIndex) nextIdx = idx + 1;
            }
            nextSelected.add(nextIdx);
        });
        selectedSlideIndices = nextSelected;
    }

    // 更新页码
    slidesData.forEach((slide, index) => {
        slide.page_number = index + 1;
    });

    // 同步更新大纲顺序（避免重新生成等操作按编辑器序号写入错误页）
    await updateOutlineForSlideOperation('move', fromIndex, { to_index: toIndex });

    // 更新当前选中的索引
    if (currentSlideIndex === fromIndex) {
        currentSlideIndex = toIndex;
    } else if (currentSlideIndex > fromIndex && currentSlideIndex <= toIndex) {
        currentSlideIndex--;
    } else if (currentSlideIndex < fromIndex && currentSlideIndex >= toIndex) {
        currentSlideIndex++;
    }

    // 重新渲染侧边栏
    refreshSidebar();

    // 保存到服务器
    await saveToServer();
}

// 右键菜单功能
function showContextMenu(event, slideIndex) {
    event.preventDefault();
    contextMenuSlideIndex = slideIndex;

    const contextMenu = document.getElementById('contextMenu');
    const pasteMenuItem = document.getElementById('pasteMenuItem');

    // 更新粘贴菜单项状态
    if (copiedSlideData) {
        pasteMenuItem.classList.remove('disabled');
    } else {
        pasteMenuItem.classList.add('disabled');
    }

    // 显示菜单
    contextMenu.style.display = 'block';
    contextMenu.style.left = event.pageX + 'px';
    contextMenu.style.top = event.pageY + 'px';

    // 确保菜单不超出屏幕
    const rect = contextMenu.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
        contextMenu.style.left = (event.pageX - rect.width) + 'px';
    }
    if (rect.bottom > window.innerHeight) {
        contextMenu.style.top = (event.pageY - rect.height) + 'px';
    }
}

function hideContextMenu() {
    document.getElementById('contextMenu').style.display = 'none';
}

function editSlide() {
    hideContextMenu();
    selectSlide(contextMenuSlideIndex);
    setMode('edit');
}

function cloneJsonValue(value, fallback = null) {
    if (value === undefined || value === null) {
        return fallback;
    }
    return JSON.parse(JSON.stringify(value));
}

function getSlideOutlineSnapshot(slideIndex) {
    if (
        projectOutline &&
        Array.isArray(projectOutline.slides) &&
        slideIndex >= 0 &&
        slideIndex < projectOutline.slides.length
    ) {
        return cloneJsonValue(projectOutline.slides[slideIndex], null);
    }
    return null;
}

function normalizeInsertedTitle(title) {
    const baseTitle = title || 'Slide';
    return `${baseTitle} (\u526f\u672c)`;
}

function renumberSlidesDataPages() {
    if (!Array.isArray(slidesData)) {
        return;
    }
    slidesData.forEach((slide, index) => {
        if (slide && typeof slide === 'object') {
            slide.page_number = index + 1;
        }
    });
}

function renumberProjectOutlinePages() {
    if (!projectOutline || !Array.isArray(projectOutline.slides)) {
        return;
    }
    projectOutline.slides.forEach((slide, index) => {
        if (slide && typeof slide === 'object') {
            slide.page_number = index + 1;
        }
    });
}

function cloneSlideForInsert(sourceSlide, insertIndex) {
    const newSlide = cloneJsonValue(sourceSlide, {});
    newSlide.page_number = insertIndex + 1;
    newSlide.title = normalizeInsertedTitle(newSlide.title);
    if (typeof newSlide.html_content !== 'string') {
        newSlide.html_content = '';
    }
    return newSlide;
}

function cloneOutlineForInsert(sourceOutline, sourceSlide, insertIndex, title) {
    const sourceMetadata = sourceSlide && sourceSlide.metadata && typeof sourceSlide.metadata === 'object'
        ? sourceSlide.metadata
        : {};
    const fallbackType =
        (sourceSlide && (sourceSlide.slide_type || sourceSlide.content_type || sourceSlide.type)) ||
        sourceMetadata.slide_type ||
        sourceMetadata.type ||
        'content';

    const outlineSlide = cloneJsonValue(sourceOutline, null) || {
        title: sourceSlide && sourceSlide.title ? sourceSlide.title : title,
        slide_type: fallbackType,
        type: fallbackType,
        description:
            (sourceSlide && sourceSlide.description) ||
            sourceMetadata.description ||
            '',
        content_points: cloneJsonValue(
            (sourceSlide && sourceSlide.content_points) ||
            sourceMetadata.content_points ||
            [],
            []
        )
    };

    outlineSlide.page_number = insertIndex + 1;
    outlineSlide.title = title;
    const outlineType = outlineSlide.slide_type || outlineSlide.type || fallbackType;
    outlineSlide.slide_type = outlineType;
    outlineSlide.type = outlineType;
    if (!Array.isArray(outlineSlide.content_points)) {
        outlineSlide.content_points = [];
    }
    return outlineSlide;
}

function copySlide() {
    hideContextMenu();
    if (!isPPTGenerationCompleted()) {
        showNotification('PPT生成完成后才能使用复制功能', 'warning');
        return;
    }
    if (contextMenuSlideIndex >= 0 && contextMenuSlideIndex < slidesData.length) {
        copiedSlideData = JSON.parse(JSON.stringify(slidesData[contextMenuSlideIndex]));
        copiedSlideOutlineData = getSlideOutlineSnapshot(contextMenuSlideIndex);
        showNotification('幻灯片已复制到剪贴板', 'success');
    }
}

async function pasteSlide() {
    hideContextMenu();
    if (!isPPTGenerationCompleted()) {
        showNotification('PPT生成完成后才能使用粘贴功能', 'warning');
        return;
    }
    if (!copiedSlideData) {
        showNotification('剪贴板中没有幻灯片数据', 'warning');
        return;
    }

    try {
        const insertIndex = contextMenuSlideIndex + 1;
        const newSlide = cloneSlideForInsert(copiedSlideData, insertIndex);
        const newOutline = cloneOutlineForInsert(
            copiedSlideOutlineData,
            copiedSlideData,
            insertIndex,
            newSlide.title
        );

        // 插入到指定位置
        slidesData.splice(insertIndex, 0, newSlide);

        // 更新后续幻灯片的页码
        renumberSlidesDataPages();

        // 同步更新大纲
        await updateOutlineForSlideOperation('insert', insertIndex, newOutline);

        // 刷新界面
        refreshSidebar();
        await saveToServer();
        showNotification('幻灯片已粘贴', 'success');
    } catch (error) {
        showNotification('粘贴幻灯片失败：' + error.message, 'error');
    }
}

async function insertNewSlide() {
    hideContextMenu();
    if (!isPPTGenerationCompleted()) {
        showNotification('PPT生成完成后才能添加新幻灯片', 'warning');
        return;
    }

    try {
        // 获取全局母版模板
        const globalTemplate = await getSelectedGlobalTemplate();

        const slideTitle = `第${contextMenuSlideIndex + 2}页`;
        let htmlContent = `
            <div style="width: 1280px; height: 720px; background: #ffffff;
                        display: flex; flex-direction: column; justify-content: center; align-items: center;
                        color: #111111; font-family: 'Microsoft YaHei', Arial, sans-serif;">
                <h1 style="font-size: 48px; margin-bottom: 20px; text-align: center;">新建幻灯片</h1>
                <p style="font-size: 24px; text-align: center; color: #6b7078;">请编辑此幻灯片内容</p>
            </div>
        `;

        // 如果有全局母版，使用模板生成HTML内容
        if (globalTemplate) {
            htmlContent = await generateSlideWithGlobalTemplate(
                globalTemplate,
                slideTitle,
                '新建幻灯片，请编辑内容'
            );
        }

        // 创建新的空白幻灯片
        const newSlide = {
            page_number: contextMenuSlideIndex + 2,
            title: slideTitle,
            html_content: htmlContent
        };

        // 插入到指定位置
        slidesData.splice(contextMenuSlideIndex + 1, 0, newSlide);

        // 更新后续幻灯片的页码
        for (let i = contextMenuSlideIndex + 2; i < slidesData.length; i++) {
            slidesData[i].page_number = i + 1;
        }

        // 同步更新大纲
        await updateOutlineForSlideOperation('insert', contextMenuSlideIndex + 1, {
            title: slideTitle,
            slide_type: 'content',
            type: 'content',
            description: '新建幻灯片，请编辑内容',
            content_points: []
        });

        // 刷新界面
        refreshSidebar();
        await saveToServer();
        showNotification('新幻灯片已插入', 'success');
    } catch (error) {
        showNotification('插入新幻灯片失败：' + error.message, 'error');
    }
}

async function duplicateSlide() {
    hideContextMenu();
    if (!isPPTGenerationCompleted()) {
        showNotification('PPT生成完成后才能复制幻灯片', 'warning');
        return;
    }
    if (contextMenuSlideIndex >= 0 && contextMenuSlideIndex < slidesData.length) {
        try {
            const originalSlide = slidesData[contextMenuSlideIndex];
            const sourceOutline = getSlideOutlineSnapshot(contextMenuSlideIndex);
            const insertIndex = contextMenuSlideIndex + 1;
            const duplicatedSlide = cloneSlideForInsert(originalSlide, insertIndex);
            const duplicatedOutline = cloneOutlineForInsert(
                sourceOutline,
                originalSlide,
                insertIndex,
                duplicatedSlide.title
            );

            // 插入到原幻灯片后面
            slidesData.splice(insertIndex, 0, duplicatedSlide);

            // 更新后续幻灯片的页码
            renumberSlidesDataPages();

            // 同步更新大纲
            await updateOutlineForSlideOperation('insert', insertIndex, duplicatedOutline);

            // 刷新界面
            refreshSidebar();
            await saveToServer();
            showNotification('幻灯片已复制', 'success');
        } catch (error) {
            showNotification('复制幻灯片失败：' + error.message, 'error');
        }
    }
}

async function deleteSlide() {
    hideContextMenu();
    if (!isPPTGenerationCompleted()) {
        showNotification('PPT生成完成后才能删除幻灯片', 'warning');
        return;
    }
    if (slidesData.length <= 1) {
        showNotification('至少需要保留一张幻灯片', 'warning');
        return;
    }

    if (await Notify.confirm('确定要删除这张幻灯片吗？', { danger: true })) {
        try {
            // 删除幻灯片
            slidesData.splice(contextMenuSlideIndex, 1);

            // 更新后续幻灯片的页码
            for (let i = contextMenuSlideIndex; i < slidesData.length; i++) {
                slidesData[i].page_number = i + 1;
            }

            // 调整当前选中的索引
            if (currentSlideIndex >= contextMenuSlideIndex) {
                currentSlideIndex = Math.max(0, currentSlideIndex - 1);
            }

            // 同步更新大纲
            await updateOutlineForSlideOperation('delete', contextMenuSlideIndex);

            // 刷新界面
            refreshSidebar();
            selectSlide(currentSlideIndex);

            // 保存当前幻灯片数据
            await saveToServer();

            // 清理数据库中多余的幻灯片
            await cleanupExcessSlides();

            showNotification('幻灯片已删除', 'success');
        } catch (error) {
            showNotification('删除幻灯片失败：' + error.message, 'error');
        }
    }
}

function refreshSidebar() {
    const slidesContainer = document.querySelector('.slides-container');
    if (!slidesContainer) return;

    // 如果没有slides数据，显示提示信息
    if (!slidesData || slidesData.length === 0) {
        slidesContainer.innerHTML = `
            <div class="text-center p-4" style="color: #7f8c8d;" id="noSlidesMessage">
                <div style="font-size: 48px; margin-bottom: 15px;">
                    <i class="fas fa-magic"></i>
                </div>
                <h5 style="margin-bottom: 10px;">PPT正在生成中...</h5>
                <p style="margin-bottom: 15px; font-size: 14px;">
                    幻灯片生成完成后，您可以在这里进行编辑和管理
                </p>
                <div class="spinner-border text-primary" role="status" style="margin-bottom: 15px;">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <br>
                <button class="btn btn-primary btn-sm" onclick="checkForUpdates()">
                    <i class="fas fa-refresh"></i> 刷新页面
                </button>
            </div>
        `;
        return;
    }

    // 清除现有的幻灯片缩略图和提示信息
    const existingThumbnails = slidesContainer.querySelectorAll('.slide-thumbnail');
    const noSlidesMessage = slidesContainer.querySelector('#noSlidesMessage');
    existingThumbnails.forEach(thumb => thumb.remove());
    if (noSlidesMessage) noSlidesMessage.remove();

    // 重新生成幻灯片缩略图
    slidesData.forEach((slide, index) => {
        const thumbnailDiv = document.createElement('div');
        const isSelected = selectedSlideIndices && selectedSlideIndices.has(index);
        thumbnailDiv.className = `slide-thumbnail ${index === currentSlideIndex ? 'active' : ''} ${isSelected ? 'selected' : ''}`;
        thumbnailDiv.setAttribute('data-slide-index', index);
        thumbnailDiv.setAttribute('draggable', 'true');
        // 不再使用内联事件处理器，依赖事件委托

        thumbnailDiv.innerHTML = `
            <div class="drag-indicator top"></div>
            <div class="slide-preview">
                <iframe title="Slide ${index + 1}"
                        loading="lazy"></iframe>
            </div>
            <div class="slide-title">${index + 1}. ${slide.title}${(typeof isSvgRenderedSlide === 'function' && isSvgRenderedSlide(slide)) ? '<span class="slide-mode-badge" title="SVG 实验页">SVG</span>' : ''}</div>
            <div class="drag-indicator bottom"></div>
        `;

        slidesContainer.appendChild(thumbnailDiv);

        // 设置iframe内容并应用缩放。先挂载到DOM，确保缩放计算能拿到真实容器宽度。
        const iframe = thumbnailDiv.querySelector('iframe');
        if (iframe) {
            setSafeIframeContent(iframe, slide.html_content);
            requestThumbnailPreviewScale(iframe);
        }
    });

    // 重新初始化事件监听器
    initializeThumbnailEvents();
    updateSelectedSlidesUI();
}

