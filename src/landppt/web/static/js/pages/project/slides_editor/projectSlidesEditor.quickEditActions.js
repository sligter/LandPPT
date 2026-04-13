function parseCssPixelValue(value) {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function getElementNumericPosition(element, axis) {
    if (!element) return 0;
    const inlineValue = parseCssPixelValue(axis === 'x' ? element.style.left : element.style.top);
    if (inlineValue !== null) return inlineValue;

    try {
        const doc = element.ownerDocument || document;
        const view = doc.defaultView || window;
        const computed = view.getComputedStyle(element);
        const computedValue = parseCssPixelValue(axis === 'x' ? computed.left : computed.top);
        if (computedValue !== null) return computedValue;
    } catch (error) {
        // ignore and fallback to zero
    }

    return 0;
}

function isFormLikeElement(target) {
    if (!target) return false;
    if (target.isContentEditable) return true;
    const tag = (target.tagName || '').toUpperCase();
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'OPTION' || tag === 'BUTTON';
}

function quickEditMoveSelectedElementByKeyboard(e) {
    if (!selectedQuickEditElement || !quickEditMode) return false;
    if (currentInlineEditor || isDragging || isResizing) return false;
    if (e.ctrlKey || e.metaKey || e.altKey) return false;
    if (isFormLikeElement(e.target)) return false;

    const key = e.key;
    if (key !== 'ArrowUp' && key !== 'ArrowDown' && key !== 'ArrowLeft' && key !== 'ArrowRight') {
        return false;
    }

    if (!selectedQuickEditElement.style.position || selectedQuickEditElement.style.position === 'static') {
        selectedQuickEditElement.style.position = 'relative';
    }

    const step = e.shiftKey ? QUICK_EDIT_KEYBOARD_MOVE_FAST_STEP : QUICK_EDIT_KEYBOARD_MOVE_STEP;
    let deltaX = 0;
    let deltaY = 0;

    switch (key) {
        case 'ArrowLeft':
            deltaX = -step;
            break;
        case 'ArrowRight':
            deltaX = step;
            break;
        case 'ArrowUp':
            deltaY = -step;
            break;
        case 'ArrowDown':
            deltaY = step;
            break;
        default:
            return false;
    }

    if (!e.repeat) {
        saveStateForUndo();
    }

    const currentLeft = getElementNumericPosition(selectedQuickEditElement, 'x');
    const currentTop = getElementNumericPosition(selectedQuickEditElement, 'y');
    selectedQuickEditElement.style.left = `${currentLeft + deltaX}px`;
    selectedQuickEditElement.style.top = `${currentTop + deltaY}px`;

    saveQuickEditChanges();
    return true;
}

// 保存状态用于撤销
function saveStateForUndo() {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame || !slideFrame.contentDocument) return;

    const currentHtml = slideFrame.contentDocument.documentElement.outerHTML;

    // 如果当前状态和最后保存的状态相同，不保存
    if (undoStack.length > 0 && undoStack[undoStack.length - 1] === currentHtml) {
        return;
    }

    undoStack.push(currentHtml);

    // 限制栈大小
    if (undoStack.length > MAX_UNDO_STEPS) {
        undoStack.shift();
    }

    // 新操作后清空重做栈
    redoStack = [];

    updateUndoRedoButtons();
}

// 更新撤销/重做按钮状态
function updateUndoRedoButtons() {
    const undoBtn = document.getElementById('undoBtn');
    const redoBtn = document.getElementById('redoBtn');

    if (undoBtn) {
        undoBtn.disabled = undoStack.length <= 1;
    }
    if (redoBtn) {
        redoBtn.disabled = redoStack.length === 0;
    }
}

// 撤销操作
function quickEditUndo() {
    if (undoStack.length <= 1) {
        showToolbarStatus('没有可撤销的操作', 'info');
        return;
    }

    const currentState = undoStack.pop();
    redoStack.push(currentState);

    const previousState = undoStack[undoStack.length - 1];
    applyHtmlState(previousState);

    updateUndoRedoButtons();
    showToolbarStatus('已撤销', 'success');
}

// 重做操作
function quickEditRedo() {
    if (redoStack.length === 0) {
        showToolbarStatus('没有可重做的操作', 'info');
        return;
    }

    const nextState = redoStack.pop();
    undoStack.push(nextState);

    applyHtmlState(nextState);

    updateUndoRedoButtons();
    showToolbarStatus('已重做', 'success');
}

// 应用HTML状态
function applyHtmlState(html) {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame) return;

    setSafeIframeContent(slideFrame, html, { force: true });

    // 更新数据
    if (typeof slidesData !== 'undefined' && slidesData[currentSlideIndex]) {
        slidesData[currentSlideIndex].html_content = html;
    }

    // 更新缩略图
    const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[currentSlideIndex];
    if (thumbnailIframe) {
        setSafeIframeContent(thumbnailIframe, html);
    }

    // 重新初始化编辑元素
    setTimeout(() => {
        initEditableElements();
        initQuickEditElementSelection();
    }, 300);
}

// 显示/隐藏快速编辑工具栏
function showQuickEditToolbar() {
    const toolbar = document.getElementById('quickEditToolbar');
    if (toolbar) {
        toolbar.classList.add('visible');
    }
}

function hideQuickEditToolbar() {
    const toolbar = document.getElementById('quickEditToolbar');
    if (toolbar) {
        toolbar.classList.remove('visible');
    }
}

// 初始化快速编辑元素选择
let quickEditElementSelectionInitialized = false;

function initQuickEditElementSelection() {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame || !slideFrame.contentDocument) return;

    const iframeDoc = slideFrame.contentDocument;

    // 标记已初始化（允许重复调用：仅为新增元素补绑定事件）
    if (!iframeDoc._quickEditInitialized) {
        iframeDoc._quickEditInitialized = true;
    }

    // 为所有可选择的元素添加点击事件（包括图片元素）
    const selectableElements = iframeDoc.querySelectorAll('div, p, h1, h2, h3, h4, h5, h6, span, ul, ol, li, table, img, svg');

    selectableElements.forEach(element => {
        // 排除body和html
        if (element.tagName === 'BODY' || element.tagName === 'HTML') return;

        // 排除太小的图像（小于30px）
        if ((element.tagName === 'IMG' || element.tagName === 'SVG') &&
            (element.offsetWidth < 30 || element.offsetHeight < 30)) return;

        // 防止重复绑定
        if (element._quickEditClickHandler) return;

        // 左键点击：选择元素（用于移动和调整大小）
        element._quickEditClickHandler = function (e) {
            if (!quickEditMode) return;
            e.stopPropagation();
            selectQuickEditElement(element);
        };
        element.addEventListener('click', element._quickEditClickHandler);

        // 右键点击：为图像元素触发AI侧边栏
        element._quickEditContextMenuHandler = function (e) {
            if (!quickEditMode) return;

            // 检查是否是图像元素或有背景图像的元素
            const isImage = element.tagName === 'IMG' || element.tagName === 'SVG';
            let hasBackgroundImage = false;

            if (!isImage && slideFrame.contentWindow) {
                const computedStyle = slideFrame.contentWindow.getComputedStyle(element);
                const backgroundImage = computedStyle.backgroundImage;
                hasBackgroundImage = backgroundImage && backgroundImage !== 'none' && backgroundImage.includes('url(');
            }

            if (isImage || hasBackgroundImage) {
                e.preventDefault();
                e.stopPropagation();

                // 先选中元素
                selectQuickEditElement(element);

                // 触发AI侧边栏通知
                const imageInfo = extractImageInfo(element, slideFrame);
                selectedImageInfo = imageInfo;
                notifyAIAssistantImageSelected(imageInfo);
            }
        };
        element.addEventListener('contextmenu', element._quickEditContextMenuHandler);
    });

    // 点击空白区域取消选择
    if (!iframeDoc._quickEditBodyClickHandler) {
        iframeDoc._quickEditBodyClickHandler = function (e) {
            if (e.target === iframeDoc.body || e.target === iframeDoc.documentElement) {
                deselectQuickEditElement();
            }
        };
        iframeDoc.addEventListener('click', iframeDoc._quickEditBodyClickHandler);
    }

    if (!iframeDoc._quickEditKeyboardHandler) {
        iframeDoc._quickEditKeyboardHandler = function (e) {
            handleQuickEditKeyboardShortcuts(e);
        };
        iframeDoc.addEventListener('keydown', iframeDoc._quickEditKeyboardHandler);
    }
}

// 选择元素
function selectQuickEditElement(element, options = {}) {
    const { allowWhileAiSending = false } = options || {};

    if (quickAiEditSending && !allowWhileAiSending) {
        showToolbarStatus('AI处理中，请稍候…', 'info');
        return;
    }
    // 如果当前有元素正在文字编辑中，先完成编辑
    if (currentInlineEditor) {
        finishDirectEdit(true);
    }

    // 先取消之前的选择
    deselectQuickEditElement({ keepAiPopover: isQuickAiPopoverVisible() });

    // 清除之前的图像选择状态
    clearImageSelection();

    selectedQuickEditElement = element;
    element.classList.add('quick-edit-element-selected');

    // 保存原始位置样式
    if (!element.style.position || element.style.position === 'static') {
        element.style.position = 'relative';
    }

    // 添加调整大小手柄
    addResizeHandles(element);

    // 初始化拖拽
    initElementDrag(element);

    // 更新样式按钮状态
    updateStyleButtonStates();

    // 添加双击处理器用于进入文字编辑模式
    if (!element._quickEditDblClickHandler) {
        element._quickEditDblClickHandler = function (e) {
            if (!quickEditMode) return;
            // 对于文字元素，双击进入编辑模式
            if (canDirectEditElement(element)) {
                e.preventDefault();
                e.stopImmediatePropagation();
                e.stopPropagation();
                makeElementDirectlyEditable(element, e);
            } else if (typeof showToolbarStatus === 'function') {
                showToolbarStatus('该元素是布局容器，请双击具体文字', 'info');
            }
        };
        element.addEventListener('dblclick', element._quickEditDblClickHandler);
    }

    // 注意：图像的AI侧边栏通知改为右键触发，左键只用于选择/移动/调整大小

    // 若浮窗已打开，则切换选中元素时同步更新上下文
    if (isQuickAiPopoverVisible()) {
        showQuickAiEditPopover(element, { focus: false });
    }
}

// 取消选择元素
function deselectQuickEditElement(options = {}) {
    const { keepAiPopover = false } = options || {};
    if (selectedQuickEditElement) {
        selectedQuickEditElement.classList.remove('quick-edit-element-selected');
        removeResizeHandles(selectedQuickEditElement);

        // 移除双击处理器
        if (selectedQuickEditElement._quickEditDblClickHandler) {
            selectedQuickEditElement.removeEventListener('dblclick', selectedQuickEditElement._quickEditDblClickHandler);
            delete selectedQuickEditElement._quickEditDblClickHandler;
        }

        // 如果是图像元素，清除图像选择状态
        if (selectedQuickEditElement.tagName === 'IMG' ||
            selectedQuickEditElement.tagName === 'SVG' ||
            selectedImageInfo) {
            clearImageSelection();
        }

        selectedQuickEditElement = null;
    }

    if (!keepAiPopover) {
        // 取消选择时关闭浮窗（避免误应用到错误元素）
        setQuickAiSendingState(false);
        hideQuickAiEditPopover({ clearInput: false });
    }
}

// 添加调整大小手柄
function addResizeHandles(element) {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame || !slideFrame.contentDocument) return;

    const iframeDoc = slideFrame.contentDocument;

    const positions = ['nw', 'ne', 'sw', 'se'];
    positions.forEach(pos => {
        const handle = iframeDoc.createElement('div');
        handle.className = `resize-handle ${pos}`;
        handle.setAttribute('data-resize-handle', pos);
        handle.setAttribute('contenteditable', 'false'); // 防止被父元素的编辑模式影响
        handle.style.cssText = `
            position: absolute;
            width: 10px;
            height: 10px;
            background: #4facfe;
            border: 2px solid white;
            border-radius: 2px;
            z-index: 1001;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            user-select: none;
            -webkit-user-select: none;
            pointer-events: auto;
        `;

        // 设置位置
        switch (pos) {
            case 'nw': handle.style.top = '-5px'; handle.style.left = '-5px'; handle.style.cursor = 'nw-resize'; break;
            case 'ne': handle.style.top = '-5px'; handle.style.right = '-5px'; handle.style.cursor = 'ne-resize'; break;
            case 'sw': handle.style.bottom = '-5px'; handle.style.left = '-5px'; handle.style.cursor = 'sw-resize'; break;
            case 'se': handle.style.bottom = '-5px'; handle.style.right = '-5px'; handle.style.cursor = 'se-resize'; break;
        }

        handle.addEventListener('mousedown', function (e) {
            e.preventDefault(); // 防止触发文本选择
            e.stopPropagation();
            startResize(e, pos);
        });

        element.appendChild(handle);
    });

    // 添加边缘手柄（用于单独调整宽度或高度）
    const edgePositions = ['n', 's', 'e', 'w'];
    edgePositions.forEach(pos => {
        const handle = iframeDoc.createElement('div');
        handle.className = `resize-handle edge ${pos}`;
        handle.setAttribute('data-resize-handle', pos);
        handle.setAttribute('contenteditable', 'false'); // 防止被父元素的编辑模式影响

        // 边缘手柄使用不同的样式
        if (pos === 'n' || pos === 's') {
            // 上下边缘：横向长条
            handle.style.cssText = `
                position: absolute;
                width: 30px;
                height: 6px;
                background: #4facfe;
                border: 1px solid white;
                border-radius: 3px;
                z-index: 1001;
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                left: 50%;
                transform: translateX(-50%);
                user-select: none;
                -webkit-user-select: none;
                pointer-events: auto;
            `;
            if (pos === 'n') {
                handle.style.top = '-3px';
                handle.style.cursor = 'n-resize';
            } else {
                handle.style.bottom = '-3px';
                handle.style.cursor = 's-resize';
            }
        } else {
            // 左右边缘：纵向长条
            handle.style.cssText = `
                position: absolute;
                width: 6px;
                height: 30px;
                background: #4facfe;
                border: 1px solid white;
                border-radius: 3px;
                z-index: 1001;
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                top: 50%;
                transform: translateY(-50%);
                user-select: none;
                -webkit-user-select: none;
                pointer-events: auto;
            `;
            if (pos === 'w') {
                handle.style.left = '-3px';
                handle.style.cursor = 'w-resize';
            } else {
                handle.style.right = '-3px';
                handle.style.cursor = 'e-resize';
            }
        }

        handle.addEventListener('mousedown', function (e) {
            e.preventDefault(); // 防止触发文本选择
            e.stopPropagation();
            startResize(e, pos);
        });

        element.appendChild(handle);
    });
}

// 移除调整大小手柄
function removeResizeHandles(element) {
    if (!element) return;
    const handles = element.querySelectorAll('[data-resize-handle]');
    handles.forEach(h => h.remove());
}

// 开始调整大小
function startResize(e, handlePos) {
    if (!selectedQuickEditElement) return;

    // 如果正在进行文字编辑，不启动调整大小
    if (currentInlineEditor) return;

    isResizing = true;
    resizeHandle = handlePos;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    elementStartWidth = selectedQuickEditElement.offsetWidth;
    elementStartHeight = selectedQuickEditElement.offsetHeight;

    // 保存元素原始状态并设置调整大小时需要的样式
    selectedQuickEditElement._originalContentEditable = selectedQuickEditElement.contentEditable;
    selectedQuickEditElement._originalOverflow = selectedQuickEditElement.style.overflow;
    selectedQuickEditElement._originalBoxSizing = selectedQuickEditElement.style.boxSizing;
    selectedQuickEditElement._originalWhiteSpace = selectedQuickEditElement.style.whiteSpace;
    selectedQuickEditElement._originalMinWidth = selectedQuickEditElement.style.minWidth;
    selectedQuickEditElement._originalMinHeight = selectedQuickEditElement.style.minHeight;

    // 临时禁用 contenteditable 以防止干扰
    selectedQuickEditElement.contentEditable = 'false';
    // 设置必要的样式以允许任意尺寸调整
    selectedQuickEditElement.style.overflow = 'hidden';
    selectedQuickEditElement.style.boxSizing = 'border-box';
    selectedQuickEditElement.style.minWidth = '0';
    selectedQuickEditElement.style.minHeight = '0';

    saveStateForUndo();

    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && slideFrame.contentDocument) {
        slideFrame.contentDocument.addEventListener('mousemove', handleResize);
        slideFrame.contentDocument.addEventListener('mouseup', stopResize);
    }
}

// 处理调整大小
function handleResize(e) {
    if (!isResizing || !selectedQuickEditElement) return;

    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;

    let newWidth = elementStartWidth;
    let newHeight = elementStartHeight;

    switch (resizeHandle) {
        // 角落手柄：同时调整宽高
        case 'se':
            newWidth = elementStartWidth + dx;
            newHeight = elementStartHeight + dy;
            break;
        case 'sw':
            newWidth = elementStartWidth - dx;
            newHeight = elementStartHeight + dy;
            break;
        case 'ne':
            newWidth = elementStartWidth + dx;
            newHeight = elementStartHeight - dy;
            break;
        case 'nw':
            newWidth = elementStartWidth - dx;
            newHeight = elementStartHeight - dy;
            break;
        // 边缘手柄：只调整单一维度
        case 'n':
            // 向上拖动减小高度
            newHeight = elementStartHeight - dy;
            break;
        case 's':
            // 向下拖动增加高度
            newHeight = elementStartHeight + dy;
            break;
        case 'e':
            // 向右拖动增加宽度
            newWidth = elementStartWidth + dx;
            break;
        case 'w':
            // 向左拖动减小宽度
            newWidth = elementStartWidth - dx;
            break;
    }

    // 最小尺寸限制
    newWidth = Math.max(50, newWidth);
    newHeight = Math.max(30, newHeight);

    selectedQuickEditElement.style.width = newWidth + 'px';
    selectedQuickEditElement.style.height = newHeight + 'px';
}

// 停止调整大小
function stopResize(e) {
    if (selectedQuickEditElement) {
        // 恢复元素原始样式
        if (selectedQuickEditElement._originalContentEditable !== undefined) {
            selectedQuickEditElement.contentEditable = selectedQuickEditElement._originalContentEditable;
            delete selectedQuickEditElement._originalContentEditable;
        }
        if (selectedQuickEditElement._originalOverflow !== undefined) {
            selectedQuickEditElement.style.overflow = selectedQuickEditElement._originalOverflow;
            delete selectedQuickEditElement._originalOverflow;
        }
        if (selectedQuickEditElement._originalBoxSizing !== undefined) {
            selectedQuickEditElement.style.boxSizing = selectedQuickEditElement._originalBoxSizing;
            delete selectedQuickEditElement._originalBoxSizing;
        }
        if (selectedQuickEditElement._originalWhiteSpace !== undefined) {
            selectedQuickEditElement.style.whiteSpace = selectedQuickEditElement._originalWhiteSpace;
            delete selectedQuickEditElement._originalWhiteSpace;
        }
        if (selectedQuickEditElement._originalMinWidth !== undefined) {
            selectedQuickEditElement.style.minWidth = selectedQuickEditElement._originalMinWidth;
            delete selectedQuickEditElement._originalMinWidth;
        }
        if (selectedQuickEditElement._originalMinHeight !== undefined) {
            selectedQuickEditElement.style.minHeight = selectedQuickEditElement._originalMinHeight;
            delete selectedQuickEditElement._originalMinHeight;
        }
    }

    isResizing = false;
    resizeHandle = null;

    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && slideFrame.contentDocument) {
        slideFrame.contentDocument.removeEventListener('mousemove', handleResize);
        slideFrame.contentDocument.removeEventListener('mouseup', stopResize);
    }

    saveQuickEditChanges();
}

// 初始化元素拖拽
function initElementDrag(element) {
    element.addEventListener('mousedown', function (e) {
        // 如果点击的是调整大小手柄，不启动拖拽
        if (e.target.hasAttribute('data-resize-handle')) return;
        if (!quickEditMode || element !== selectedQuickEditElement) return;

        // 如果正在进行文字编辑，不启动拖拽（允许用户选择文字）
        if (currentInlineEditor) return;

        startDrag(e);
    });
}

// 开始拖拽
function startDrag(e) {
    if (!selectedQuickEditElement) return;

    isDragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    elementStartX = parseInt(selectedQuickEditElement.style.left) || 0;
    elementStartY = parseInt(selectedQuickEditElement.style.top) || 0;

    selectedQuickEditElement.classList.add('quick-edit-dragging');

    saveStateForUndo();

    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && slideFrame.contentDocument) {
        slideFrame.contentDocument.addEventListener('mousemove', handleDrag);
        slideFrame.contentDocument.addEventListener('mouseup', stopDrag);
    }
}

// 处理拖拽
function handleDrag(e) {
    if (!isDragging || !selectedQuickEditElement) return;

    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;

    selectedQuickEditElement.style.left = (elementStartX + dx) + 'px';
    selectedQuickEditElement.style.top = (elementStartY + dy) + 'px';
}

// 停止拖拽
function stopDrag(e) {
    isDragging = false;

    if (selectedQuickEditElement) {
        selectedQuickEditElement.classList.remove('quick-edit-dragging');
    }

    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && slideFrame.contentDocument) {
        slideFrame.contentDocument.removeEventListener('mousemove', handleDrag);
        slideFrame.contentDocument.removeEventListener('mouseup', stopDrag);
    }

    saveQuickEditChanges();
}

// 删除元素
function quickEditDelete() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择要删除的元素', 'warning');
        return;
    }

    if (confirm('确定要删除此元素吗？')) {
        saveStateForUndo();
        selectedQuickEditElement.remove();
        selectedQuickEditElement = null;
        saveQuickEditChanges();
        showToolbarStatus('元素已删除', 'success');
    }
}

// 复制元素
function quickEditDuplicate() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择要复制的元素', 'warning');
        return;
    }

    saveStateForUndo();

    const clone = selectedQuickEditElement.cloneNode(true);
    clone.classList.remove('quick-edit-element-selected');
    removeResizeHandles(clone);

    // 偏移位置
    const currentLeft = parseInt(selectedQuickEditElement.style.left) || 0;
    const currentTop = parseInt(selectedQuickEditElement.style.top) || 0;
    clone.style.left = (currentLeft + 20) + 'px';
    clone.style.top = (currentTop + 20) + 'px';

    selectedQuickEditElement.parentNode.insertBefore(clone, selectedQuickEditElement.nextSibling);

    // 选择新元素
    selectQuickEditElement(clone);

    saveQuickEditChanges();
    showToolbarStatus('元素已复制', 'success');
}

// 上移层级
function quickEditMoveUp() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();

    const currentZIndex = parseInt(window.getComputedStyle(selectedQuickEditElement).zIndex) || 0;
    selectedQuickEditElement.style.zIndex = currentZIndex + 1;

    saveQuickEditChanges();
    showToolbarStatus('层级已上移', 'success');
}

// 下移层级
function quickEditMoveDown() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();

    const currentZIndex = parseInt(window.getComputedStyle(selectedQuickEditElement).zIndex) || 0;
    selectedQuickEditElement.style.zIndex = Math.max(0, currentZIndex - 1);

    saveQuickEditChanges();
    showToolbarStatus('层级已下移', 'success');
}

// 左对齐
function quickEditAlignLeft() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();
    selectedQuickEditElement.style.textAlign = 'left';
    saveQuickEditChanges();
    showToolbarStatus('已左对齐', 'success');
}

// 居中对齐
function quickEditAlignCenter() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();
    selectedQuickEditElement.style.textAlign = 'center';
    saveQuickEditChanges();
    showToolbarStatus('已居中对齐', 'success');
}

// 右对齐
function quickEditAlignRight() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();
    selectedQuickEditElement.style.textAlign = 'right';
    saveQuickEditChanges();
    showToolbarStatus('已右对齐', 'success');
}

