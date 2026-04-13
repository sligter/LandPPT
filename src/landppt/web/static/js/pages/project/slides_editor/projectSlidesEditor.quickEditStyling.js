// ==================== 工具栏状态显示 ====================
let toolbarStatusTimeout = null;

// 显示工具栏内联状态（替代浮动通知）
function showToolbarStatus(message, type = 'info') {
    const statusEl = document.getElementById('toolbarStatus');
    if (!statusEl) return;

    // 清除之前的定时器
    if (toolbarStatusTimeout) {
        clearTimeout(toolbarStatusTimeout);
    }

    // 移除所有类型类
    statusEl.classList.remove('success', 'warning', 'info', 'visible');

    // 设置内容和类型
    statusEl.textContent = message;
    statusEl.classList.add(type, 'visible');

    // 2秒后自动隐藏
    toolbarStatusTimeout = setTimeout(() => {
        statusEl.classList.remove('visible');
    }, 2000);
}

// ==================== 字体大小调整 ====================

// 增大字体
function quickEditIncreaseFontSize() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();

    const currentSize = window.getComputedStyle(selectedQuickEditElement).fontSize;
    const currentSizeNum = parseFloat(currentSize);
    const newSize = Math.min(currentSizeNum + 2, 200); // 最大200px
    selectedQuickEditElement.style.fontSize = newSize + 'px';

    saveQuickEditChanges();
    showToolbarStatus(`字体: ${Math.round(newSize)}px`, 'success');
}

// 减小字体
function quickEditDecreaseFontSize() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();

    const currentSize = window.getComputedStyle(selectedQuickEditElement).fontSize;
    const currentSizeNum = parseFloat(currentSize);
    const newSize = Math.max(currentSizeNum - 2, 8); // 最小8px
    selectedQuickEditElement.style.fontSize = newSize + 'px';

    saveQuickEditChanges();
    showToolbarStatus(`字体: ${Math.round(newSize)}px`, 'success');
}

// ==================== 文字样式切换 ====================

// 切换粗体
function quickEditToggleBold() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();

    const currentWeight = window.getComputedStyle(selectedQuickEditElement).fontWeight;
    const isBold = currentWeight === 'bold' || parseInt(currentWeight) >= 700;

    selectedQuickEditElement.style.fontWeight = isBold ? 'normal' : 'bold';

    // 更新按钮状态
    const boldBtn = document.getElementById('boldBtn');
    if (boldBtn) {
        boldBtn.classList.toggle('active', !isBold);
    }

    saveQuickEditChanges();
    showToolbarStatus(isBold ? '取消粗体' : '已加粗', 'success');
}

// 切换斜体
function quickEditToggleItalic() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();

    const currentStyle = window.getComputedStyle(selectedQuickEditElement).fontStyle;
    const isItalic = currentStyle === 'italic';

    selectedQuickEditElement.style.fontStyle = isItalic ? 'normal' : 'italic';

    // 更新按钮状态
    const italicBtn = document.getElementById('italicBtn');
    if (italicBtn) {
        italicBtn.classList.toggle('active', !isItalic);
    }

    saveQuickEditChanges();
    showToolbarStatus(isItalic ? '取消斜体' : '已斜体', 'success');
}

// 切换下划线
function quickEditToggleUnderline() {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();

    const currentDecoration = window.getComputedStyle(selectedQuickEditElement).textDecoration;
    const hasUnderline = currentDecoration.includes('underline');

    selectedQuickEditElement.style.textDecoration = hasUnderline ? 'none' : 'underline';

    // 更新按钮状态
    const underlineBtn = document.getElementById('underlineBtn');
    if (underlineBtn) {
        underlineBtn.classList.toggle('active', !hasUnderline);
    }

    saveQuickEditChanges();
    showToolbarStatus(hasUnderline ? '取消下划线' : '已加下划线', 'success');
}

// ==================== 颜色设置 ====================

// 设置字体颜色
function quickEditSetFontColor(color) {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();
    selectedQuickEditElement.style.color = color;
    saveQuickEditChanges();
    showToolbarStatus('字体颜色已更新', 'success');
}

// 设置背景颜色
function quickEditSetBgColor(color) {
    if (!selectedQuickEditElement) {
        showToolbarStatus('请先选择元素', 'warning');
        return;
    }

    saveStateForUndo();
    selectedQuickEditElement.style.backgroundColor = color;
    saveQuickEditChanges();
    showToolbarStatus('背景颜色已更新', 'success');
}

// 更新样式按钮状态（选择元素时调用）
function updateStyleButtonStates() {
    if (!selectedQuickEditElement) return;

    const computedStyle = window.getComputedStyle(selectedQuickEditElement);

    // 更新粗体按钮
    const boldBtn = document.getElementById('boldBtn');
    if (boldBtn) {
        const isBold = computedStyle.fontWeight === 'bold' || parseInt(computedStyle.fontWeight) >= 700;
        boldBtn.classList.toggle('active', isBold);
    }

    // 更新斜体按钮
    const italicBtn = document.getElementById('italicBtn');
    if (italicBtn) {
        italicBtn.classList.toggle('active', computedStyle.fontStyle === 'italic');
    }

    // 更新下划线按钮
    const underlineBtn = document.getElementById('underlineBtn');
    if (underlineBtn) {
        underlineBtn.classList.toggle('active', computedStyle.textDecoration.includes('underline'));
    }

    // 更新颜色选择器
    const fontColorPicker = document.getElementById('fontColorPicker');
    if (fontColorPicker) {
        fontColorPicker.value = rgbToHex(computedStyle.color) || '#000000';
    }

    const bgColorPicker = document.getElementById('bgColorPicker');
    if (bgColorPicker) {
        const bgColor = computedStyle.backgroundColor;
        bgColorPicker.value = (bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent')
            ? '#ffffff'
            : (rgbToHex(bgColor) || '#ffffff');
    }
}

// RGB转HEX颜色
function rgbToHex(rgb) {
    if (!rgb || rgb === 'transparent' || rgb === 'rgba(0, 0, 0, 0)') return null;

    const match = rgb.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!match) return rgb;

    const r = parseInt(match[1]).toString(16).padStart(2, '0');
    const g = parseInt(match[2]).toString(16).padStart(2, '0');
    const b = parseInt(match[3]).toString(16).padStart(2, '0');

    return '#' + r + g + b;
}

// ==================== 重置编辑功能 ====================

// 保存初始状态（页面加载时调用），initialSlideStates 已在页面初始化时定义
function saveInitialSlideState(slideIndex, htmlContent) {
    if (typeof setInitialSlideState === 'function') {
        setInitialSlideState(slideIndex, htmlContent, { overwrite: false });
        return;
    }
    if (!initialSlideStates[slideIndex]) {
        initialSlideStates[slideIndex] = htmlContent;
    }
}

// 重置当前幻灯片到初始状态
async function quickEditReset() {
    if (!confirm('确定要重置当前幻灯片到初始状态吗？所有编辑将会丢失。')) {
        return;
    }

    const slideIndex = currentSlideIndex;

    // 检查是否有保存的初始状态
    const initialState = typeof getInitialSlideState === 'function'
        ? getInitialSlideState(slideIndex)
        : initialSlideStates[slideIndex];

    if (initialState) {
        applyResetState(initialState);
        showToolbarStatus('已重置到初始状态', 'success');
        return;
    }

    // 如果没有缓存，尝试从服务器获取原始数据
    try {
        showToolbarStatus('正在获取初始状态...', 'info');

        const response = await fetch(`/api/projects/${projectId}`);
        if (!response.ok) {
            throw new Error('获取项目数据失败');
        }

        const data = await response.json();
        if (data.slides_data && data.slides_data[slideIndex]) {
            const originalHtml = data.slides_data[slideIndex].html_content;
            if (typeof setInitialSlideState === 'function') {
                setInitialSlideState(slideIndex, originalHtml);
            }
            applyResetState(originalHtml);
            showToolbarStatus('已重置到初始状态', 'success');
        } else {
            showToolbarStatus('未找到初始数据', 'warning');
        }
    } catch (error) {
        console.error('重置失败:', error);
        showToolbarStatus('重置失败', 'warning');

        // 如果API失败，尝试使用undo栈的最早状态
        if (undoStack.length > 0) {
            applyResetState(undoStack[0]);
            showToolbarStatus('已重置到最早状态', 'success');
        }
    }
}

// 应用重置状态
function applyResetState(html) {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame) return;

    // 重置前先取消可能延迟执行的自动保存，避免旧内容回写覆盖重置结果。
    if (saveQuickEditTimeout) {
        clearTimeout(saveQuickEditTimeout);
        saveQuickEditTimeout = null;
    }

    // 若当前仍处于文字直编态，先取消本次编辑，确保不会把未完成输入再次提交。
    if (typeof currentInlineEditor !== 'undefined' && currentInlineEditor) {
        finishDirectEdit(false);
    }

    // 取消当前选择
    deselectQuickEditElement();

    // 清空撤销/重做栈
    undoStack = [];
    redoStack = [];

    // 应用状态
    setSafeIframeContent(slideFrame, html, { force: true });

    // 更新数据
    if (typeof slidesData !== 'undefined' && slidesData[currentSlideIndex]) {
        slidesData[currentSlideIndex].html_content = html;
        slidesData[currentSlideIndex].is_user_edited = false;
    }

    // 更新缩略图
    const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[currentSlideIndex];
    if (thumbnailIframe) {
        setSafeIframeContent(thumbnailIframe, html);
    }

    // 保存到服务器
    if (typeof saveSingleSlideToServer === 'function') {
        saveSingleSlideToServer(currentSlideIndex, html, { isUserEdited: false });
    }

    // 重新保存初始状态用于撤销
    saveStateForUndo();
    updateUndoRedoButtons();

    // 重新初始化编辑元素
    setTimeout(() => {
        initEditableElements();
        initQuickEditElementSelection();
    }, 300);
}

// 保存快速编辑更改（带防抖）
let saveQuickEditTimeout = null;
const SAVE_DEBOUNCE_DELAY = 300; // 300ms 防抖延迟

function saveQuickEditChanges() {
    // 使用防抖机制，避免频繁保存
    if (saveQuickEditTimeout) {
        clearTimeout(saveQuickEditTimeout);
    }

    saveQuickEditTimeout = setTimeout(() => {
        doSaveQuickEditChanges();
    }, SAVE_DEBOUNCE_DELAY);
}

// 实际执行保存操作
function doSaveQuickEditChanges() {
    const slideFrame = document.getElementById('slideFrame');
    if (!slideFrame || !slideFrame.contentDocument) return;

    const updatedHtml = getCleanSlideHtmlForQuickEdit({
        slideFrame,
        stripQuickAiIds: true
    });
    if (typeof syncIframeCurrentContent === 'function') {
        syncIframeCurrentContent(slideFrame, updatedHtml);
    }

    // 更新数据
    if (typeof slidesData !== 'undefined' && slidesData[currentSlideIndex]) {
        slidesData[currentSlideIndex].html_content = updatedHtml;
        slidesData[currentSlideIndex].is_user_edited = true;

        // 更新代码编辑器
        if (typeof codeMirrorEditor !== 'undefined' && codeMirrorEditor && isCodeMirrorInitialized) {
            codeMirrorEditor.setValue(updatedHtml);
        }

        // 更新缩略图
        const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[currentSlideIndex];
        if (thumbnailIframe) {
            setSafeIframeContent(thumbnailIframe, updatedHtml);
        }

        // 只保存当前编辑的幻灯片，避免覆盖生成器正在生成的其他页面
        if (typeof saveSingleSlideToServer === 'function') {
            saveSingleSlideToServer(currentSlideIndex, updatedHtml);
        }
    }
}

// 键盘快捷键支持
function handleQuickEditKeyboardShortcuts(e) {
    if (!quickEditMode) return;

    // 如果焦点在快捷 AI 浮窗内，避免拦截输入框自身快捷键
    const aiPop = getQuickAiPopoverEl();
    if (aiPop && aiPop.contains(document.activeElement)) {
        if (e.key === 'Escape') {
            e.preventDefault();
            hideQuickAiEditPopover({ clearInput: false });
        }
        return;
    }

    if (quickEditMoveSelectedElementByKeyboard(e)) {
        e.preventDefault();
        return;
    }

    const keyLower = typeof e.key === 'string' ? e.key.toLowerCase() : '';

    // Ctrl+Z 撤销
    if ((e.ctrlKey || e.metaKey) && keyLower === 'z') {
        e.preventDefault();
        quickEditUndo();
    }

    // Ctrl+Y 重做
    if ((e.ctrlKey || e.metaKey) && keyLower === 'y') {
        e.preventDefault();
        quickEditRedo();
    }

    // Delete 删除
    if (e.key === 'Delete' && selectedQuickEditElement) {
        e.preventDefault();
        quickEditDelete();
    }

    // Escape 取消选择
    if (e.key === 'Escape') {
        if (isQuickAiPopoverVisible()) {
            e.preventDefault();
            hideQuickAiEditPopover({ clearInput: false });
            return;
        }
        deselectQuickEditElement();
    }
}

document.addEventListener('keydown', handleQuickEditKeyboardShortcuts);

