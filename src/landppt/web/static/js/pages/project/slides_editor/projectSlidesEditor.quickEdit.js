// ==================== 快速编辑功能 ====================
let quickEditMode = false;
let currentInlineEditor = null;
let editableElements = [];
const QUICK_EDIT_DIRECT_TEXT_TAGS = new Set([
    'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
    'P', 'SPAN', 'DIV', 'LI', 'TD', 'TH',
    'A', 'SMALL', 'STRONG', 'EM', 'B', 'I', 'U', 'S', 'MARK'
]);
const QUICK_EDIT_INLINE_CHILD_TAGS = new Set([
    'BR', 'SPAN', 'A', 'SMALL', 'STRONG', 'EM', 'B', 'I', 'U', 'S', 'MARK', 'SUB', 'SUP', 'CODE'
]);
const QUICK_EDIT_STRUCTURAL_DESCENDANT_SELECTOR = [
    'img', 'svg', 'canvas', 'table', 'thead', 'tbody', 'tfoot', 'tr',
    'ul', 'ol', 'video', 'iframe', 'form', 'button', 'input', 'textarea', 'select',
    'mjx-container', '.MathJax', '.MathJax_Display', '.katex', '.katex-display', '.katex-inline',
    'math', '[data-latex]', '[data-tex]', '[data-formula]', '[data-equation]', '[data-math]',
    '[data-mathml]', '[data-asciimath]'
].join(', ');

function getQuickEditRenderableChildren(element) {
    if (!element || !element.children) return [];
    return Array.from(element.children).filter(child => child && !child.hasAttribute('data-resize-handle'));
}

function isSafeInlineQuickEditChild(child) {
    if (!child || !child.tagName) return false;
    const tagName = child.tagName.toUpperCase();
    if (!QUICK_EDIT_INLINE_CHILD_TAGS.has(tagName)) return false;
    if (tagName !== 'BR' && child.matches && child.matches(QUICK_EDIT_STRUCTURAL_DESCENDANT_SELECTOR)) return false;

    try {
        const childStyle = child.ownerDocument?.defaultView?.getComputedStyle(child);
        const display = String(childStyle?.display || '').toLowerCase();
        return tagName === 'BR' || display.includes('inline') || display === 'contents';
    } catch (error) {
        return tagName === 'BR';
    }
}

function canDirectEditElement(element) {
    if (!element || !element.tagName) return false;
    if (!element.textContent || !element.textContent.trim()) return false;

    const tagName = element.tagName.toUpperCase();
    if (!QUICK_EDIT_DIRECT_TEXT_TAGS.has(tagName)) return false;

    if (element.matches && element.matches(QUICK_EDIT_STRUCTURAL_DESCENDANT_SELECTOR)) {
        return false;
    }

    if (element.querySelector && element.querySelector(QUICK_EDIT_STRUCTURAL_DESCENDANT_SELECTOR)) {
        return false;
    }

    let computedStyle = null;
    try {
        computedStyle = element.ownerDocument?.defaultView?.getComputedStyle(element);
    } catch (error) { }

    const display = String(computedStyle?.display || '').toLowerCase();
    if (['flex', 'grid', 'inline-flex', 'inline-grid', 'table', 'inline-table'].includes(display)) {
        return false;
    }

    const position = String(computedStyle?.position || '').toLowerCase();
    if (position === 'absolute' || position === 'fixed') {
        return false;
    }

    const children = getQuickEditRenderableChildren(element);
    if (children.length === 0) return true;

    return children.every(child => isSafeInlineQuickEditChild(child));
}

// 生成可持久化保存的干净 HTML，避免把快编选中框、拖拽态和拉伸手柄写入幻灯片内容
function getCleanSlideHtmlForQuickEdit(options = {}) {
    const {
        slideFrame = document.getElementById('slideFrame'),
        stripQuickAiIds = false
    } = options || {};

    if (!slideFrame || !slideFrame.contentDocument) return '';

    const iframeDoc = slideFrame.contentDocument;
    const selectedElements = Array.from(iframeDoc.querySelectorAll('.quick-edit-element-selected'));
    const draggingElements = Array.from(iframeDoc.querySelectorAll('.quick-edit-dragging'));
    const highlightedElements = Array.from(iframeDoc.querySelectorAll('.quick-edit-highlight'));
    const resizeHandles = Array.from(iframeDoc.querySelectorAll('[data-resize-handle]'));
    const aiIdElements = stripQuickAiIds
        ? Array.from(iframeDoc.querySelectorAll('[data-quick-ai-id]')).map(el => ({
            el,
            value: el.getAttribute('data-quick-ai-id')
        }))
        : [];

    selectedElements.forEach(el => el.classList.remove('quick-edit-element-selected'));
    draggingElements.forEach(el => el.classList.remove('quick-edit-dragging'));
    highlightedElements.forEach(el => el.classList.remove('quick-edit-highlight'));
    resizeHandles.forEach(handle => handle.remove());
    aiIdElements.forEach(item => {
        try {
            item.el.removeAttribute('data-quick-ai-id');
        } catch (error) { }
    });

    try {
        return iframeDoc.documentElement?.outerHTML || '';
    } finally {
        aiIdElements.forEach(item => {
            try {
                if (item.value) {
                    item.el.setAttribute('data-quick-ai-id', item.value);
                }
            } catch (error) { }
        });

        if (selectedQuickEditElement && selectedQuickEditElement.isConnected) {
            selectedQuickEditElement.classList.add('quick-edit-element-selected');
            addResizeHandles(selectedQuickEditElement);
        }

        draggingElements.forEach(el => {
            if (el && el.isConnected) {
                el.classList.add('quick-edit-dragging');
            }
        });
        highlightedElements.forEach(el => {
            if (el && el.isConnected) {
                el.classList.add('quick-edit-highlight');
            }
        });
    }
}

// 切换快速编辑模式
function toggleQuickEditMode() {
    if (currentMode === 'quickedit') {
        // 如果当前正在编辑，先完成编辑
        if (currentInlineEditor) {
            finishDirectEdit(true);
        }
        // 退出快速编辑模式
        setMode('preview');
    } else {
        // 进入快速编辑模式
        setMode('quickedit');
    }
}

// 启用快速编辑模式
function enableQuickEdit() {
    quickEditMode = true;
    if (typeof setInitialSlideState === 'function' && slidesData[currentSlideIndex]?.html_content) {
        setInitialSlideState(currentSlideIndex, slidesData[currentSlideIndex].html_content, { overwrite: false });
    }
    const previewPane = document.getElementById('previewPane');
    if (previewPane) {
        previewPane.classList.add('quick-edit-mode');
    }

    // 显示快速编辑工具栏
    showQuickEditToolbar();

    // 保存初始状态用于撤销
    saveStateForUndo();

    // 等待iframe加载完成后初始化可编辑元素
    setTimeout(() => {
        initEditableElements();
        initQuickEditElementSelection();

        // 重新初始化图像选择功能
        const slideFrame = document.getElementById('slideFrame');
        if (slideFrame) {
            try {
                const iframeWindow = slideFrame.contentWindow;
                const iframeDoc = slideFrame.contentDocument || iframeWindow.document;
                if (iframeWindow && iframeDoc) {
                    initializeImageSelection(slideFrame, iframeWindow, iframeDoc);
                }
            } catch (e) {
                // 重新初始化图像选择功能失败
            }
        }
    }, 500);


}

// 禁用快速编辑模式
function disableQuickEdit() {
    quickEditMode = false;
    const previewPane = document.getElementById('previewPane');
    if (previewPane) {
        previewPane.classList.remove('quick-edit-mode');
    }

    // 隐藏快速编辑工具栏
    hideQuickEditToolbar();

    // 隐藏快捷 AI 浮窗
    setQuickAiSendingState(false);
    hideQuickAiEditPopover({ clearInput: true });

    // 取消选择的元素
    deselectQuickEditElement();

    // 清除撤销/重做栈
    undoStack = [];
    redoStack = [];
    updateUndoRedoButtons();

    // 清除所有编辑标识
    clearEditableHighlights();

    // 完成当前的直接编辑
    if (currentInlineEditor) {
        finishDirectEdit(true);
    }

    // 清除图像选择状态
    clearImageSelection();

    // 移除图像选择功能和快速编辑事件处理器
    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame) {
        try {
            const iframeDoc = slideFrame.contentDocument || slideFrame.contentWindow.document;
            if (iframeDoc) {
                // 清理图像选择相关样式
                const selectableImages = iframeDoc.querySelectorAll('[data-image-selectable]');
                selectableImages.forEach(element => {
                    element.removeAttribute('data-image-selectable');
                    element.style.cursor = '';
                    element.classList.remove('image-selected', 'image-selectable');
                    element.style.outline = '';
                    element.style.outlineOffset = '';
                    element.style.boxShadow = '';
                    element.style.transform = '';
                });

                // 清理快速编辑事件处理器（包括contextmenu）
                const allElements = iframeDoc.querySelectorAll('div, p, h1, h2, h3, h4, h5, h6, span, ul, ol, li, table, img, svg');
                allElements.forEach(element => {
                    if (element._quickEditClickHandler) {
                        element.removeEventListener('click', element._quickEditClickHandler);
                        delete element._quickEditClickHandler;
                    }
                    if (element._quickEditContextMenuHandler) {
                        element.removeEventListener('contextmenu', element._quickEditContextMenuHandler);
                        delete element._quickEditContextMenuHandler;
                    }
                });

                // 清理 iframe 级别键盘事件处理器
                if (iframeDoc._quickEditKeyboardHandler) {
                    iframeDoc.removeEventListener('keydown', iframeDoc._quickEditKeyboardHandler);
                    delete iframeDoc._quickEditKeyboardHandler;
                }

                // 重置初始化标志，以便下次可以重新初始化
                iframeDoc._quickEditInitialized = false;
            }
        } catch (e) {
            // 清理图像选择功能失败
        }
    }
}

// 初始化可编辑元素
function initEditableElements() {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame || !slideFrame.contentDocument) {
        setTimeout(() => {
            initEditableElements();
        }, 1000);
        return;
    }

    try {
        const iframeDoc = slideFrame.contentDocument;
        editableElements = [];

        // 查找可编辑的文本元素
        const textSelectors = [
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'p', 'span', 'div',
            'li', 'td', 'th',
            '.title', '.subtitle', '.content',
            '[contenteditable]'
        ];

        textSelectors.forEach(selector => {
            const elements = iframeDoc.querySelectorAll(selector);
            elements.forEach(element => {
                if (canDirectEditElement(element) && !editableElements.includes(element)) {
                    editableElements.push(element);
                    addEditableHighlight(element);
                }
            });
        });


    } catch (error) {
        // 初始化可编辑元素时出错
    }
}

// 为元素添加编辑高亮
function addEditableHighlight(element) {
    if (!canDirectEditElement(element)) return;

    element.classList.add('quick-edit-highlight');
    element.style.cursor = 'text'; // 改为文本光标

    // 文本元素单击只做元素选择，双击时再进入文字编辑。
    if (element._quickEditInlineClickHandler) {
        element.removeEventListener('click', element._quickEditInlineClickHandler);
        delete element._quickEditInlineClickHandler;
    }
}

// 清除所有编辑高亮
function clearEditableHighlights() {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame || !slideFrame.contentDocument) return;

    try {
        const iframeDoc = slideFrame.contentDocument;
        const highlightedElements = iframeDoc.querySelectorAll('.quick-edit-highlight');
        highlightedElements.forEach(element => {
            element.classList.remove('quick-edit-highlight');
            element.classList.remove('direct-editing');
            element.style.cursor = 'default';
            element.contentEditable = false;
            if (element._quickEditInlineClickHandler) {
                element.removeEventListener('click', element._quickEditInlineClickHandler);
                delete element._quickEditInlineClickHandler;
            }
        });
    } catch (error) {
        // 清除编辑高亮时出错
    }
}

// 使元素直接可编辑
function makeElementDirectlyEditable(element, clickEvent = null) {
    if (!canDirectEditElement(element)) {
        if (typeof showToolbarStatus === 'function') {
            showToolbarStatus('请选择具体文字，不要直接编辑布局容器', 'info');
        }
        return;
    }

    // 如果已经有元素在编辑中，先完成编辑
    if (currentInlineEditor) {
        finishDirectEdit();
    }

    // 保存原始内容
    const originalText = element.textContent;
    const originalHTML = element.innerHTML;

    // 设置当前编辑元素
    currentInlineEditor = {
        element: element,
        originalText: originalText,
        originalHTML: originalHTML
    };

    if (selectedQuickEditElement === element) {
        removeResizeHandles(element);
        element.classList.remove('quick-edit-element-selected');
    }

    // 使元素可编辑
    element.contentEditable = true;
    element.classList.add('direct-editing');

    // 确保iframe内的样式正确应用
    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && slideFrame.contentDocument) {
        const iframeDoc = slideFrame.contentDocument;

        // 在iframe内添加直接编辑样式
        let styleElement = iframeDoc.getElementById('quick-edit-styles');
        if (!styleElement) {
            styleElement = iframeDoc.createElement('style');
            styleElement.id = 'quick-edit-styles';
            styleElement.textContent = `
                .direct-editing {
                    outline: 2px solid #4facfe !important;
                    outline-offset: 2px !important;
                    transition: outline-color 0.2s ease, outline-offset 0.2s ease, box-shadow 0.2s ease !important;
                    box-shadow: 0 0 0 2px rgba(79, 172, 254, 0.16) !important;
                }
                .direct-editing:focus {
                    outline-color: #2980b9 !important;
                    box-shadow: 0 0 0 2px rgba(79, 172, 254, 0.22) !important;
                }
            `;
            iframeDoc.head.appendChild(styleElement);
        }
    }

    // 聚焦元素并设置光标位置
    element.focus();

    // 设置光标位置
    try {
        if (clickEvent) {
            // 如果有点击事件，尝试根据点击位置设置光标
            const range = element.ownerDocument.createRange();
            const selection = element.ownerDocument.getSelection();

            // 使用点击位置设置光标
            if (element.ownerDocument.caretRangeFromPoint) {
                const clickRange = element.ownerDocument.caretRangeFromPoint(clickEvent.clientX, clickEvent.clientY);
                if (clickRange && element.contains(clickRange.startContainer)) {
                    selection.removeAllRanges();
                    selection.addRange(clickRange);
                } else {
                    // 如果点击位置无效，设置到文本末尾
                    range.selectNodeContents(element);
                    range.collapse(false);
                    selection.removeAllRanges();
                    selection.addRange(range);
                }
            } else {
                // 浏览器不支持caretRangeFromPoint，设置到文本末尾
                range.selectNodeContents(element);
                range.collapse(false);
                selection.removeAllRanges();
                selection.addRange(range);
            }
        } else {
            // 没有点击事件，设置到文本末尾
            const range = element.ownerDocument.createRange();
            const selection = element.ownerDocument.getSelection();
            range.selectNodeContents(element);
            range.collapse(false);
            selection.removeAllRanges();
            selection.addRange(range);
        }
    } catch (error) {
        // 光标设置失败，至少确保元素获得焦点
        element.focus();
    }

    // 添加键盘事件监听
    element.addEventListener('keydown', handleDirectEditKeydown);
    element.addEventListener('blur', handleDirectEditBlur);
    element.addEventListener('input', handleDirectEditInput);
}

// 处理直接编辑的键盘事件
function handleDirectEditKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        // Enter键完成编辑
        e.preventDefault();
        finishDirectEdit(true);
    } else if (e.key === 'Escape') {
        // ESC键取消编辑
        e.preventDefault();
        finishDirectEdit(false);
    }
}

// 处理直接编辑失去焦点
function handleDirectEditBlur(e) {
    // 延迟处理，避免与其他事件冲突
    setTimeout(() => {
        if (currentInlineEditor && currentInlineEditor.element === e.target) {
            finishDirectEdit(true);
        }
    }, 100);
}

// 处理直接编辑输入事件
function handleDirectEditInput(e) {
    // 可以在这里添加实时预览更新逻辑
}

// 完成直接编辑
function finishDirectEdit(save = true) {
    if (!currentInlineEditor) return;

    const element = currentInlineEditor.element;
    const originalText = currentInlineEditor.originalText;
    const originalHTML = currentInlineEditor.originalHTML;
    const newText = element.textContent;

    // 移除事件监听器
    element.removeEventListener('keydown', handleDirectEditKeydown);
    element.removeEventListener('blur', handleDirectEditBlur);
    element.removeEventListener('input', handleDirectEditInput);

    // 恢复元素状态
    element.contentEditable = false;
    element.classList.remove('direct-editing');
    element.style.outline = '';
    element.style.outlineOffset = '';
    element.style.backgroundColor = '';

    if (save && newText !== originalText) {
        // 保存更改
        saveDirectEdit(element, newText);
    } else {
        // 取消更改，恢复原始内容
        element.innerHTML = originalHTML;
    }

    // 结束文字编辑后同步清理当前元素的选择框与手柄，避免布局边框残留
    if (selectedQuickEditElement === element) {
        deselectQuickEditElement({ keepAiPopover: typeof isQuickAiPopoverVisible === 'function' && isQuickAiPopoverVisible() });
    }

    // 清除当前编辑状态
    currentInlineEditor = null;
}

// 保存直接编辑
function saveDirectEdit(element, newText) {
    if (!element || newText === undefined) return;

    // 获取更新后的HTML内容
    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && slideFrame.contentDocument) {
        const updatedHtml = getCleanSlideHtmlForQuickEdit({
            slideFrame,
            stripQuickAiIds: true
        });
        if (typeof syncIframeCurrentContent === 'function') {
            syncIframeCurrentContent(slideFrame, updatedHtml);
        }

        // 更新幻灯片数据
        if (typeof slidesData !== 'undefined' && slidesData[currentSlideIndex]) {
            slidesData[currentSlideIndex].html_content = updatedHtml;
            slidesData[currentSlideIndex].is_user_edited = true;

            // 更新代码编辑器
            if (typeof codeMirrorEditor !== 'undefined' && codeMirrorEditor && typeof isCodeMirrorInitialized !== 'undefined' && isCodeMirrorInitialized) {
                codeMirrorEditor.setValue(updatedHtml);
            } else {
                const codeEditor = document.getElementById('codeEditor');
                if (codeEditor) {
                    codeEditor.value = updatedHtml;
                }
            }

            // 更新缩略图
            const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[currentSlideIndex];
            if (thumbnailIframe && typeof setSafeIframeContent === 'function') {
                setSafeIframeContent(thumbnailIframe, updatedHtml);
            }

            // 只保存当前编辑的幻灯片，而不是保存所有幻灯片
            // 这样可以避免在生成过程中覆盖其他正在生成的幻灯片
            if (typeof saveSingleSlideToServer === 'function') {
                saveSingleSlideToServer(currentSlideIndex, updatedHtml).then(success => {
                    if (success && typeof showNotification === 'function') {
                        showNotification('内容已更新并保存！', 'success');
                    }
                }).catch(err => {
                    if (typeof showNotification === 'function') {
                        showNotification('保存失败：' + err.message, 'error');
                    }
                });
            }
        }
    }
}

