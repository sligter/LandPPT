function regenerateContextSlide() {
    hideContextMenu();
    regenerateSlideByIndex(contextMenuSlideIndex);
}

async function pollBackgroundTaskUntilDone(taskId, { timeoutMs = 30 * 60 * 1000, intervalMs = 2000, onTick } = {}) {
    const start = Date.now();
    while (true) {
        const resp = await fetch(`/api/landppt/tasks/${taskId}`);
        if (!resp.ok) {
            const txt = await resp.text();
            throw new Error(txt || `任务状态查询失败: HTTP ${resp.status}`);
        }

        const data = await resp.json();
        if (typeof onTick === 'function') {
            try { onTick(data); } catch (_) { }
        }

        if (data.status === 'completed') return data;
        if (data.status === 'failed' || data.status === 'cancelled') {
            let err = data.error || (data.result && (data.result.error || data.result.message)) || '任务失败';
            if (typeof err === 'string') {
                err = err.split('\n')[0].slice(0, 300);
            }
            throw new Error(err || '任务失败');
        }

        if (Date.now() - start > timeoutMs) {
            throw new Error('等待任务完成超时，请稍后刷新页面查看结果');
        }

        await new Promise(r => setTimeout(r, intervalMs));
    }
}

function regenerateSlideByIndex(slideIndex) {
    // 防御：若slides_data存在缺页导致错位，先按page_number/大纲归一化，避免错页写入
    normalizeSlidesDataToOutline();

    const outlineTotal = getOutlineSlidesCount();
    if (slideIndex < 0 || slideIndex >= outlineTotal) {
        alert('无效的幻灯片索引');
        return;
    }

    ensureSlidesDataLength(outlineTotal);
    const outlineTitle = (projectOutline && projectOutline.slides && projectOutline.slides[slideIndex])
        ? projectOutline.slides[slideIndex].title
        : null;
    const slideTitle = (slidesData[slideIndex] && slidesData[slideIndex].title) || outlineTitle || `第${slideIndex + 1}页`;
    if (confirm(`确定要重新生成"${slideTitle}"吗？这将覆盖现有内容。`)) {
        // Show loading indicator
        const loadingDiv = document.createElement('div');
        loadingDiv.id = 'regenerateLoading';
        loadingDiv.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0,0,0,0.8);
            color: white;
            padding: 20px;
            border-radius: 10px;
            z-index: 9999;
            text-align: center;
        `;
        loadingDiv.innerHTML = `
            <i class="fas fa-spinner fa-spin"></i>
            <div style="margin-top: 10px;">正在重新生成幻灯片...</div>
        `;
        document.body.appendChild(loadingDiv);

        (async () => {
            try {
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/slides/${slideIndex + 1}/regenerate/async`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        scenario: window.landpptEditorProjectInfo.scenario,
                        topic: `${window.landpptEditorProjectInfo.topic}`,
                        requirements: window.landpptEditorProjectRequirements,
                        language: 'zh'
                    })
                });

                const contentType = (response.headers && response.headers.get)
                    ? (response.headers.get('content-type') || '')
                    : '';
                const rawText = await response.text();
                const isJsonByHeader = contentType.toLowerCase().includes('application/json');
                if (!isJsonByHeader) {
                    const snippet = (rawText || '').slice(0, 200).replace(/\s+/g, ' ').trim();
                    throw new Error(`接口返回非JSON：${response.status} ${response.statusText}${snippet ? ' - ' + snippet : ''}`);
                }

                const data = rawText ? JSON.parse(rawText) : {};

                const reusedExistingTask = response.status === 409;
                if (!response.ok && !reusedExistingTask) {
                    throw new Error(data?.error || data?.detail || data?.message || `${response.status} ${response.statusText}`);
                }

                const taskId = data && data.task_id;
                if (!taskId) {
                    throw new Error(data?.error || data?.message || '未返回任务ID');
                }

                if (reusedExistingTask && typeof showNotification === 'function') {
                    showNotification('检测到同页已有重新生成任务，正在继续跟踪该任务', 'info');
                }

                const statusTextMap = {
                    pending: reusedExistingTask ? '已连接到已有任务，排队中...' : '任务排队中...',
                    running: '正在重新生成幻灯片...',
                    completed: '生成完成，正在更新页面...',
                    failed: '生成失败',
                    cancelled: '已取消'
                };

                const taskData = await pollBackgroundTaskUntilDone(taskId, {
                    onTick: (t) => {
                        const p = (typeof t.progress === 'number') ? Math.round(t.progress) : null;
                        const msg = statusTextMap[t.status] || '处理中...';
                        loadingDiv.innerHTML = `
                            <i class="fas fa-spinner fa-spin"></i>
                            <div style="margin-top: 10px;">${msg}${p !== null ? ` (${p}%)` : ''}</div>
                        `;
                    }
                });

                const result = taskData && taskData.result ? taskData.result : null;
                if (!result || !result.success) {
                    throw new Error((result && (result.error || result.message)) || '重新生成失败');
                }

                if (result.slide_data) {
                    slidesData[slideIndex] = result.slide_data;
                    if (typeof setInitialSlideState === 'function' && result.slide_data.html_content) {
                        setInitialSlideState(slideIndex, result.slide_data.html_content);
                    }

                    const thumbnailsCount = document.querySelectorAll('.slide-thumbnail').length;
                    if (thumbnailsCount !== slidesData.length) {
                        refreshSidebar();
                    } else {
                        updateThumbnailDisplay(slideIndex, result.slide_data);
                    }

                    if (currentSlideIndex === slideIndex) {
                        updateMainPreview(result.slide_data);
                        updateCodeEditor(result.slide_data);
                    }

                    showNotification('幻灯片重新生成成功！', 'success');
                } else {
                    showNotification('幻灯片重新生成成功！正在刷新页面...', 'success');
                    setTimeout(() => location.reload(), 600);
                }
            } catch (error) {
                console.error('Slide regenerate error:', error);
                alert('重新生成失败：' + (error && error.message ? error.message : error));
            } finally {
                if (loadingDiv && loadingDiv.parentNode) {
                    loadingDiv.parentNode.removeChild(loadingDiv);
                }
            }
        })();
    }
}

async function regenerateSelectedSlides() {
    const indices = getSelectedSlideIndicesSorted();
    if (!indices || indices.length === 0) {
        showNotification('请先按住 Ctrl 并点击左侧缩略图选择要重新生成的页面', 'warning');
        return;
    }
    await batchRegenerateSlides({ slideIndices: indices, regenerateAll: false });
}

async function regenerateAllSlides() {
    const outlineTotal = getOutlineSlidesCount();
    if (outlineTotal <= 0) {
        showNotification('没有可用的幻灯片', 'warning');
        return;
    }
    await batchRegenerateSlides({ slideIndices: null, regenerateAll: true });
}

async function batchRegenerateSlides({ slideIndices, regenerateAll }) {
    const outlineTotal = getOutlineSlidesCount();
    if (outlineTotal <= 0) {
        showNotification('没有可用的幻灯片', 'warning');
        return;
    }

    const normalizedSlideIndices = regenerateAll
        ? null
        : (Array.isArray(slideIndices)
            ? slideIndices.filter(i => Number.isInteger(i) && i >= 0 && i < outlineTotal)
            : []);

    const total = regenerateAll ? outlineTotal : normalizedSlideIndices.length;
    if (total <= 0) {
        showNotification('未选择任何幻灯片', 'warning');
        return;
    }

    const confirmText = regenerateAll
        ? `确定要一键重新生成全部${total}页吗？这将覆盖现有内容。`
        : `确定要重新生成所选${total}页吗？这将覆盖现有内容。`;

    if (!confirm(confirmText)) {
        return;
    }

    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'batchRegenerateLoading';
    loadingDiv.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: rgba(0,0,0,0.85);
        color: white;
        padding: 20px 22px;
        border-radius: 12px;
        z-index: 9999;
        text-align: center;
        min-width: 280px;
    `;
    loadingDiv.innerHTML = `
        <i class="fas fa-spinner fa-spin"></i>
        <div style="margin-top: 10px; font-weight: 700;">正在重新生成幻灯片...</div>
        <div style="margin-top: 6px; font-size: 12px; opacity: 0.85;">共 ${total} 页</div>
    `;
    document.body.appendChild(loadingDiv);

    try {
        ensureSlidesDataLength(outlineTotal);

        const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/slides/batch-regenerate/async`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                regenerate_all: !!regenerateAll,
                slide_indices: regenerateAll ? null : normalizedSlideIndices,
                scenario: window.landpptEditorProjectInfo.scenario,
                topic: `${window.landpptEditorProjectInfo.topic}`,
                requirements: window.landpptEditorProjectRequirements,
                language: 'zh'
            })
        });

        const contentType = (response.headers && response.headers.get)
            ? (response.headers.get('content-type') || '')
            : '';
        const rawText = await response.text();
        const isJsonByHeader = contentType.toLowerCase().includes('application/json');
        if (!isJsonByHeader) {
            const snippet = (rawText || '').slice(0, 200).replace(/\s+/g, ' ').trim();
            throw new Error(`接口返回非JSON：${response.status} ${response.statusText}${snippet ? ' - ' + snippet : ''}`);
        }

        const data = rawText ? JSON.parse(rawText) : {};

        if (response.status === 409) {
            throw new Error(data?.message || '已有批量重新生成任务正在执行，请稍后重试');
        }

        if (!response.ok) {
            throw new Error(data?.error || data?.detail || data?.message || `${response.status} ${response.statusText}`);
        }

        const taskId = data && data.task_id;
        if (!taskId) {
            throw new Error(data?.error || data?.message || '未返回任务ID');
        }

        const statusTextMap = {
            pending: '任务排队中...',
            running: '正在批量重新生成...',
            completed: '生成完成，正在更新页面...',
            failed: '生成失败',
            cancelled: '已取消'
        };

        const taskData = await pollBackgroundTaskUntilDone(taskId, {
            onTick: (t) => {
                const p = (typeof t.progress === 'number') ? Math.round(t.progress) : null;
                const msg = statusTextMap[t.status] || '处理中...';
                loadingDiv.innerHTML = `
                    <i class="fas fa-spinner fa-spin"></i>
                    <div style="margin-top: 10px; font-weight: 700;">${msg}${p !== null ? ` (${p}%)` : ''}</div>
                    <div style="margin-top: 6px; font-size: 12px; opacity: 0.85;">共 ${total} 页</div>
                `;
            }
        });

        const result = taskData && taskData.result ? taskData.result : null;
        if (!result || !result.success) {
            throw new Error((result && (result.error || result.message)) || '批量重新生成失败');
        }

        const results = Array.isArray(result.results) ? result.results : [];
        let okCount = 0;
        let failCount = 0;

        results.forEach((r) => {
            if (r && r.success && r.slide_data && Number.isInteger(r.slide_index)) {
                slidesData[r.slide_index] = r.slide_data;
                if (typeof setInitialSlideState === 'function' && r.slide_data.html_content) {
                    setInitialSlideState(r.slide_index, r.slide_data.html_content);
                }
                updateThumbnailDisplay(r.slide_index, r.slide_data);

                if (currentSlideIndex === r.slide_index) {
                    updateMainPreview(r.slide_data);
                    updateCodeEditor(r.slide_data);
                }
                okCount += 1;
            } else if (r) {
                failCount += 1;
            }
        });

        // 如果本次是按大纲补齐生成，或缩略图数量不足，刷新侧边栏以显示完整页数
        const thumbnailsCount = document.querySelectorAll('.slide-thumbnail').length;
        if (thumbnailsCount !== slidesData.length) {
            refreshSidebar();
        }

        updateSelectedSlidesUI();

        if (failCount > 0) {
            showNotification(`批量重新生成完成：成功${okCount}页，失败${failCount}页`, 'warning');
        } else {
            showNotification(`批量重新生成完成：成功${okCount}页`, 'success');
        }

        // 操作完成后，默认回到单选当前页，避免后续误操作
        clearSlideSelections();
        setSingleSlideSelection(currentSlideIndex);

    } catch (error) {
        console.error('Batch regenerate error:', error);
        showNotification('批量重新生成失败：' + error.message, 'error');
    } finally {
        const existing = document.getElementById('batchRegenerateLoading');
        if (existing) existing.remove();
    }
}

// 更新缩略图显示
function updateThumbnailDisplay(slideIndex, slideData) {
    const thumbnails = document.querySelectorAll('.slide-thumbnail');
    if (thumbnails[slideIndex]) {
        const thumbnail = thumbnails[slideIndex];

        // 更新缩略图中的iframe内容
        const iframe = thumbnail.querySelector('iframe');
        if (iframe && slideData.html_content) {
            setSafeIframeContent(iframe, slideData.html_content);
        }

        // 更新标题
        const titleElement = thumbnail.querySelector('.slide-title');
        if (titleElement && slideData.title) {
            titleElement.textContent = `${slideIndex + 1}. ${slideData.title}`;
        }
    }
}

// 更新主预览区域
function updateMainPreview(slideData) {
    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && slideData.html_content) {
        setSafeIframeContent(slideFrame, slideData.html_content);
    }
}

// 更新代码编辑器
function updateCodeEditor(slideData) {
    if (slideData.html_content) {
        if (codeMirrorEditor) {
            // 如果使用CodeMirror
            codeMirrorEditor.setValue(slideData.html_content);
        } else {
            // 如果使用普通textarea
            const codeEditor = document.getElementById('codeEditor');
            if (codeEditor) {
                codeEditor.value = slideData.html_content;
            }
        }
    }
}

async function saveToServer() {
    // 改用逐个保存，避免在生成过程中覆盖新生成的幻灯片数据
    // 原batch-save会用前端旧数据覆盖后端新生成的数据，导致数据丢失
    try {
        let saveSuccessCount = 0;
        let saveFailureCount = 0;

        for (let i = 0; i < slidesData.length; i++) {
            try {
                const slide = slidesData[i];
                if (!slide || !slide.html_content) continue;

                // 标记为用户编辑状态
                slide.is_user_edited = true;

                const success = await saveSingleSlideToServer(i, slide.html_content);
                if (success) {
                    saveSuccessCount++;
                } else {
                    saveFailureCount++;
                }
            } catch (error) {
                saveFailureCount++;
                console.error(`保存第${i + 1}页异常:`, error);
            }
        }

        return saveSuccessCount > 0;
    } catch (error) {
        console.error('保存失败:', error);
        return false;
    }
}

// 回退保存方法 - 逐个保存
async function saveToServerFallback() {
    try {

        let saveSuccessCount = 0;
        let saveFailureCount = 0;
        const saveErrors = [];

        for (let i = 0; i < slidesData.length; i++) {
            try {
                const slide = slidesData[i];

                // 标记为用户编辑状态
                slide.is_user_edited = true;

                const success = await saveSingleSlideToServer(i, slide.html_content);
                if (success) {
                    saveSuccessCount++;
                } else {
                    saveFailureCount++;
                    saveErrors.push(`第${i + 1}页保存失败`);
                }
            } catch (error) {
                saveFailureCount++;
                const errorMsg = `第${i + 1}页保存异常: ${error.message}`;
                saveErrors.push(errorMsg);
            }
        }

        if (saveFailureCount > 0) {
            // 即使部分失败，也不抛出错误，让用户知道部分保存成功
            return saveSuccessCount > 0; // 只要有成功的就返回true
        } else {
            return true;
        }

    } catch (error) {
        throw error; // 重新抛出错误以便调用者处理
    }
}

// 清理数据库中多余的幻灯片
async function cleanupExcessSlides() {
    try {

        const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/slides/cleanup`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                current_slide_count: slidesData.length
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (data.success) {
            return true;
        } else {
            throw new Error(data.error || 'Unknown cleanup error');
        }

    } catch (error) {
        // 不抛出错误，因为这不应该阻止删除操作的完成
        return false;
    }
}

// 保存单个幻灯片到服务器
async function saveSingleSlideToServer(slideIndex, htmlContent, options = {}) {
    try {
        // 验证输入参数
        if (typeof slideIndex !== 'number' || slideIndex < 0) {
            throw new Error(`无效的幻灯片索引: ${slideIndex}`);
        }

        if (!htmlContent || typeof htmlContent !== 'string') {
            throw new Error('HTML内容不能为空');
        }

        // 验证索引范围
        if (slideIndex >= slidesData.length) {
            throw new Error(`幻灯片索引超出范围: ${slideIndex}，总页数: ${slidesData.length}`);
        }



        const requestData = {
            html_content: htmlContent
        };
        if (typeof options.isUserEdited === 'boolean') {
            requestData.is_user_edited = options.isUserEdited;
        }



        const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/slides/${slideIndex}/save`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData)
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        // 验证保存是否成功
        if (data.success === true) {
            return true;
        } else {
            throw new Error(data.error || 'Unknown error occurred');
        }

    } catch (error) {
        throw error; // 重新抛出错误以便调用者处理
    }
}

// Auto-save on code change (fallback for non-CodeMirror mode)
function initializeCodeEditorAutoSave() {
    const codeEditor = document.getElementById('codeEditor');
    if (codeEditor && !isCodeMirrorInitialized) {
        codeEditor.addEventListener('input', function () {
            clearTimeout(this.saveTimeout);
            this.saveTimeout = setTimeout(() => {
                if (currentMode === 'split') {
                    // Auto-update preview in split mode
                    const slideFrame = document.getElementById('slideFrame');
                    setSafeIframeContent(slideFrame, this.value);
                }
            }, 1000);
        });
    }
}

// Initialize event listeners for thumbnails using event delegation
