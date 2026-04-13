/* ── 更换模板弹窗 ── */

let _tplDialogEl = null;
let _tplCurrentTemplateKey = null;
let _tplSelectedKey = null;
let _tplSelectedData = null;
let _tplProjectFreeTemplate = null;
let _tplPage = 1;
let _tplTotalPages = 1;
let _tplSearchTerm = '';
let _tplSearchTimer = null;
let _tplTemplatesByKey = new Map();
let _tplAllTemplates = [];
let _tplLoadedSearchTerm = null;
const _tplPageSize = 8;

// 预览详情会被卡片和右侧大预览反复复用，这里做缓存避免重复请求。
const _tplDetailCache = new Map();
const _tplDetailRequestCache = new Map();

function _tplGetTemplateKey(template) {
    const normalizedTemplate = _tplNormalizeTemplate(template);
    if (!normalizedTemplate) {
        return '';
    }
    if (typeof normalizedTemplate.template_key === 'string' && normalizedTemplate.template_key) {
        return normalizedTemplate.template_key;
    }
    if (Number.isInteger(normalizedTemplate.id)) {
        return `global:${normalizedTemplate.id}`;
    }
    if (normalizedTemplate.is_project_free_template || normalizedTemplate.template_mode === 'free' || normalizedTemplate.created_by === 'ai_free') {
        return 'project-free';
    }
    return '';
}

function _tplBuildProjectFreeTemplate(rawTemplate) {
    const normalizedTemplate = _tplNormalizeTemplate(rawTemplate);
    if (!normalizedTemplate) {
        return null;
    }
    return {
        ...normalizedTemplate,
        id: null,
        template_key: 'project-free',
        template_mode: 'free',
        is_project_free_template: true,
        description: normalizedTemplate.description || '该模板来自当前项目曾使用过的自由模板，不在模板库中。'
    };
}

async function showChangeTemplateDialog() {
    if (_tplDialogEl) {
        closeChangeTemplateDialog();
    }

    _tplSelectedKey = null;
    _tplSelectedData = null;
    _tplProjectFreeTemplate = null;
    _tplTemplatesByKey = new Map();
    _tplAllTemplates = [];
    _tplLoadedSearchTerm = null;
    _tplPage = 1;
    _tplSearchTerm = '';

    try {
        const projectId = _tplGetProjectId();
        if (!projectId) {
            throw new Error('项目ID无效');
        }

        const [selectedResp, freeResp] = await Promise.all([
            fetch(`/api/projects/${projectId}/selected-global-template`),
            fetch(`/api/projects/${projectId}/free-template`)
        ]);

        const selectedData = await _tplReadJsonResponse(selectedResp);
        const currentTemplate = _tplNormalizeTemplate(selectedData?.template || selectedData?.selected_template || selectedData);
        _tplCurrentTemplateKey = _tplGetTemplateKey(currentTemplate) || null;

        const freeData = await _tplReadJsonResponse(freeResp);
        if (freeResp.ok && freeData?.template) {
            _tplProjectFreeTemplate = _tplBuildProjectFreeTemplate(freeData.template);
        }
        if (!_tplProjectFreeTemplate && _tplCurrentTemplateKey === 'project-free') {
            _tplProjectFreeTemplate = _tplBuildProjectFreeTemplate(currentTemplate);
        }
    } catch (_) {
        _tplCurrentTemplateKey = null;
        _tplProjectFreeTemplate = null;
    }

    _tplDialogEl = document.createElement('div');
    _tplDialogEl.className = 'tpl-dialog-overlay';
    _tplDialogEl.innerHTML = `
        <div class="tpl-dialog" onclick="event.stopPropagation()">
            <div class="tpl-dialog-header">
                <div class="tpl-dialog-title">
                    <i class="fas fa-palette"></i>
                    <span>更换模板</span>
                </div>
                <button class="tpl-dialog-close" onclick="closeChangeTemplateDialog()">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="tpl-dialog-body">
                <div class="tpl-list-panel">
                    <div class="tpl-search">
                        <input type="text" id="tplSearchInput" placeholder="搜索模板..." autocomplete="off">
                    </div>
                    <div class="tpl-grid" id="tplGrid">
                        <div class="tpl-loading"><i class="fas fa-spinner fa-spin"></i> 加载中...</div>
                    </div>
                    <div class="tpl-pagination" id="tplPagination" style="display:none;">
                        <button id="tplPrevBtn" onclick="_tplPrevPage()" disabled><i class="fas fa-chevron-left"></i></button>
                        <span id="tplPageInfo">1 / 1</span>
                        <button id="tplNextBtn" onclick="_tplNextPage()" disabled><i class="fas fa-chevron-right"></i></button>
                    </div>
                </div>
                <div class="tpl-preview-panel">
                    <div class="tpl-preview-area" id="tplPreviewArea">
                        <div class="tpl-preview-placeholder">
                            <i class="fas fa-eye"></i>
                            点击左侧模板卡片预览
                        </div>
                    </div>
                    <div class="tpl-preview-info" id="tplPreviewInfo" style="display:none;">
                        <span class="tpl-preview-name" id="tplPreviewName"></span>
                        <span class="tpl-preview-desc" id="tplPreviewDesc"></span>
                    </div>
                </div>
            </div>
            <div class="tpl-dialog-footer">
                <div class="tpl-scope-group">
                    <input type="radio" name="tplScope" id="tplScopeCurrent" value="current" checked>
                    <label for="tplScopeCurrent">当前页</label>
                    <input type="radio" name="tplScope" id="tplScopeSelected" value="selected">
                    <label for="tplScopeSelected">已选页</label>
                    <input type="radio" name="tplScope" id="tplScopeAll" value="all">
                    <label for="tplScopeAll">全部页面</label>
                </div>
                <button class="tpl-apply-btn" id="tplApplyBtn" onclick="_tplApply()" disabled>
                    <i class="fas fa-check"></i> 应用模板
                </button>
            </div>
        </div>
    `;

    _tplDialogEl.addEventListener('click', (event) => {
        if (event.target === _tplDialogEl) {
            closeChangeTemplateDialog();
        }
    });

    document.body.appendChild(_tplDialogEl);

    const searchInput = document.getElementById('tplSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(_tplSearchTimer);
            _tplSearchTimer = setTimeout(() => {
                _tplSearchTerm = searchInput.value.trim();
                _tplPage = 1;
                _tplFetchTemplates();
            }, 300);
        });
    }

    _tplDialogEl._keyHandler = (event) => {
        if (event.key === 'Escape') {
            closeChangeTemplateDialog();
        }
    };
    document.addEventListener('keydown', _tplDialogEl._keyHandler);

    _tplFetchTemplates();
}

function closeChangeTemplateDialog() {
    if (!_tplDialogEl) {
        return;
    }

    clearTimeout(_tplSearchTimer);
    _tplCleanupPreviewObservers(_tplDialogEl);

    if (_tplDialogEl._keyHandler) {
        document.removeEventListener('keydown', _tplDialogEl._keyHandler);
    }

    _tplDialogEl.remove();
    _tplDialogEl = null;
}

async function _tplFetchTemplates() {
    const grid = document.getElementById('tplGrid');
    if (!grid) {
        return;
    }

    try {
        const needsReload = _tplLoadedSearchTerm !== _tplSearchTerm || !_tplAllTemplates.length;
        if (needsReload) {
            grid.innerHTML = '<div class="tpl-loading"><i class="fas fa-spinner fa-spin"></i> 加载中...</div>';
            await _tplLoadAllTemplates();
        }

        _tplRenderCurrentPage();
    } catch (error) {
        grid.innerHTML = '<div class="tpl-loading">加载失败，请重试</div>';
        console.error('Template fetch error:', error);
    }
}

async function _tplLoadAllTemplates() {
    const libraryTemplates = await _tplFetchAllLibraryTemplates();
    const templates = [];

    // 项目自由模板固定放在第一个，便于快速切回项目原始自由模板。
    if (_tplProjectFreeTemplate) {
        templates.push(_tplProjectFreeTemplate);
    }

    libraryTemplates.forEach((template) => {
        if (!template) {
            return;
        }
        if (_tplGetTemplateKey(template) === 'project-free') {
            return;
        }
        templates.push(template);
    });

    _tplTemplatesByKey = new Map();
    templates.forEach((template) => {
        const key = _tplGetTemplateKey(template);
        if (key) {
            _tplTemplatesByKey.set(key, template);
        }
    });

    _tplAllTemplates = templates;
    _tplLoadedSearchTerm = _tplSearchTerm;
    _tplTotalPages = Math.max(1, Math.ceil(templates.length / _tplPageSize));
    if (_tplPage > _tplTotalPages) {
        _tplPage = _tplTotalPages;
    }
}

async function _tplFetchAllLibraryTemplates() {
    const allTemplates = [];
    let page = 1;
    let totalPages = 1;

    do {
        let url = `/api/global-master-templates/?page=${page}&page_size=100&active_only=true`;
        if (_tplSearchTerm) {
            url += `&search=${encodeURIComponent(_tplSearchTerm)}`;
        }

        const resp = await fetch(url);
        const data = await _tplReadJsonResponse(resp);
        if (!resp.ok) {
            throw new Error(data?.detail || data?.message || '模板列表加载失败');
        }

        const pageTemplates = Array.isArray(data?.templates)
            ? data.templates.map(_tplNormalizeTemplate).filter(Boolean)
            : [];
        allTemplates.push(...pageTemplates);

        const pagination = data?.pagination || {};
        totalPages = Math.max(1, Number(pagination.total_pages) || 1);
        page += 1;
    } while (page <= totalPages);

    return allTemplates;
}

function _tplRenderCurrentPage() {
    const start = (_tplPage - 1) * _tplPageSize;
    const templates = _tplAllTemplates.slice(start, start + _tplPageSize);
    _tplRenderGrid(templates);
    _tplRenderPagination();
    _tplWarmupCardPreviews(templates);
}

function _tplRenderGrid(templates) {
    const grid = document.getElementById('tplGrid');
    if (!grid) {
        return;
    }

    if (!templates.length) {
        grid.innerHTML = '<div class="tpl-loading">暂无可用模板</div>';
        return;
    }

    grid.innerHTML = templates.map((template) => {
        const templateKey = _tplGetTemplateKey(template);
        const previewShellId = `tplCardPreview-${templateKey}`;
        const isCurrent = templateKey === _tplCurrentTemplateKey;
        const isSelected = templateKey === _tplSelectedKey;
        const classes = ['tpl-card'];
        if (isCurrent) {
            classes.push('current');
        }
        if (isSelected) {
            classes.push('active');
        }

        return `
            <div class="${classes.join(' ')}" data-tpl-key="${_escHtml(templateKey)}">
                <div class="tpl-card-thumb">
                    <div class="tpl-card-preview-shell${template.preview_image ? '' : ' tpl-card-preview-shell--loading'}" id="${_escHtml(previewShellId)}">
                        ${template.preview_image
            ? `<img src="${template.preview_image}" alt="${_escHtml(template.template_name)}" loading="lazy">`
            : `<div class="tpl-card-preview-placeholder">正在生成预览</div>`}
                    </div>
                </div>
                <div class="tpl-card-name" title="${_escHtml(template.template_name)}">
                    ${_escHtml(template.template_name)}
                    ${template.is_project_free_template ? '<span style="display:block;font-size:11px;color:#7b8190;margin-top:4px;">项目原自由模板</span>' : ''}
                </div>
            </div>
        `;
    }).join('');

    grid.querySelectorAll('.tpl-card[data-tpl-key]').forEach((card) => {
        card.addEventListener('click', () => {
            const templateKey = card.getAttribute('data-tpl-key') || '';
            if (templateKey) {
                void _tplSelectCard(templateKey);
            }
        });
    });
}

function _tplRenderPagination() {
    const el = document.getElementById('tplPagination');
    if (!el) {
        return;
    }

    if (_tplTotalPages <= 1) {
        el.style.display = 'none';
        return;
    }

    el.style.display = 'flex';
    document.getElementById('tplPageInfo').textContent = `${_tplPage} / ${_tplTotalPages}`;
    document.getElementById('tplPrevBtn').disabled = _tplPage <= 1;
    document.getElementById('tplNextBtn').disabled = _tplPage >= _tplTotalPages;
}

function _tplPrevPage() {
    if (_tplPage > 1) {
        _tplPage -= 1;
        _tplFetchTemplates();
    }
}

function _tplNextPage() {
    if (_tplPage < _tplTotalPages) {
        _tplPage += 1;
        _tplFetchTemplates();
    }
}

async function _tplSelectCard(templateKey) {
    _tplSelectedKey = templateKey;

    document.querySelectorAll('.tpl-card').forEach((card) => card.classList.remove('active'));
    const currentCard = document.querySelector(`.tpl-card[data-tpl-key="${templateKey}"]`);
    if (currentCard) {
        currentCard.classList.add('active');
    }

    const applyBtn = document.getElementById('tplApplyBtn');
    if (applyBtn) {
        applyBtn.disabled = false;
    }

    const previewArea = document.getElementById('tplPreviewArea');
    const previewInfo = document.getElementById('tplPreviewInfo');

    if (!previewArea) {
        return;
    }

    previewArea.innerHTML = `
        <div class="tpl-preview-placeholder">
            <i class="fas fa-spinner fa-spin"></i>
            预览加载中...
        </div>
    `;

    try {
        const baseTemplate = _tplTemplatesByKey.get(templateKey);
        const detail = await _tplResolveTemplateDetail(baseTemplate);
        _tplSelectedData = detail;

        const rendered = _tplRenderTemplatePreview(previewArea, detail, { mode: 'detail' });
        if (!rendered) {
            _tplRenderPreviewFallback(previewArea, 'detail', '当前模板暂无预览');
        }

        if (previewInfo) {
            previewInfo.style.display = 'flex';
            document.getElementById('tplPreviewName').textContent = detail.template_name || '未命名';
            document.getElementById('tplPreviewDesc').textContent = detail.description || '已为当前模板生成示意预览';
        }
    } catch (error) {
        _tplSelectedData = null;
        _tplRenderPreviewFallback(previewArea, 'detail', '预览加载失败');
        if (previewInfo) {
            previewInfo.style.display = 'none';
        }
        console.error('Template preview error:', error);
    }
}

async function _tplApply() {
    if (!_tplSelectedKey) {
        return;
    }

    const projectId = _tplGetProjectId();
    if (!projectId) {
        showNotification('项目ID无效，无法切换模板', 'error');
        return;
    }

    const outlineTotal = getOutlineSlidesCount();
    if (outlineTotal <= 0) {
        showNotification('没有可用的幻灯片', 'warning');
        return;
    }

    const scope = document.querySelector('input[name="tplScope"]:checked')?.value || 'current';
    let regenerateAll = false;
    let slideIndices = [];
    let scopeLabel = '当前页';

    if (scope === 'selected') {
        slideIndices = typeof getSelectedSlideIndicesSorted === 'function'
            ? getSelectedSlideIndicesSorted()
            : [currentSlideIndex];
        scopeLabel = `${slideIndices.length}页`;
    } else if (scope === 'all') {
        regenerateAll = true;
        slideIndices = [];
        scopeLabel = '全部页面';
    } else {
        slideIndices = [currentSlideIndex];
    }

    const normalizedSlideIndices = regenerateAll
        ? null
        : slideIndices.filter((index) => Number.isInteger(index) && index >= 0 && index < outlineTotal);

    const total = regenerateAll ? outlineTotal : normalizedSlideIndices.length;
    if (total <= 0) {
        showNotification('请先选择要应用模板的页面', 'warning');
        return;
    }

    const selectedTemplate = _tplSelectedData || _tplTemplatesByKey.get(_tplSelectedKey) || null;
    const templateName = selectedTemplate?.template_name || '所选模板';
    const confirmText = `确定要将${scopeLabel}更换为「${templateName}」模板吗？\n这将重新生成 ${total} 页内容。`;
    if (!confirm(confirmText)) {
        return;
    }

    closeChangeTemplateDialog();

    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'tplChangeLoading';
    loadingDiv.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: rgba(0,0,0,0.85);
        color: white;
        padding: 20px 24px;
        border-radius: 12px;
        z-index: 9999;
        text-align: center;
        min-width: 280px;
    `;
    loadingDiv.innerHTML = `
        <i class="fas fa-spinner fa-spin"></i>
        <div style="margin-top: 10px; font-weight: 700;">正在切换模板...</div>
        <div style="margin-top: 6px; font-size: 12px; opacity: 0.85;">第1步：切换模板</div>
    `;
    document.body.appendChild(loadingDiv);

    try {
        loadingDiv.querySelector('div:last-child').textContent = '第1步：切换模板...';
        const isProjectFreeTemplate = _tplSelectedKey === 'project-free';
        const selectResp = await fetch(`/api/projects/${projectId}/select-template`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: projectId,
                selected_template_id: isProjectFreeTemplate ? null : selectedTemplate?.id,
                template_mode: isProjectFreeTemplate ? 'free' : 'global'
            })
        });
        const selectData = await _tplReadJsonResponse(selectResp);
        if (!selectResp.ok) {
            throw new Error(selectData?.detail || selectData?.message || '模板切换失败');
        }

        _tplCurrentTemplateKey = _tplSelectedKey;

        loadingDiv.querySelector('div:last-child').textContent = `第2步：重新生成${scopeLabel}...`;

        normalizeSlidesDataToOutline();
        ensureSlidesDataLength(outlineTotal);

        const regenResp = await fetch(`/api/projects/${projectId}/slides/batch-regenerate/async`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                regenerate_all: regenerateAll,
                slide_indices: regenerateAll ? null : normalizedSlideIndices,
                scenario: window.landpptEditorProjectInfo.scenario,
                topic: window.landpptEditorProjectInfo.topic,
                requirements: window.landpptEditorProjectRequirements,
                language: 'zh'
            })
        });
        const regenData = await _tplReadJsonResponse(regenResp);

        if (regenResp.status === 409) {
            throw new Error(regenData?.message || '已有重新生成任务正在执行，请稍后重试');
        }
        if (!regenResp.ok) {
            throw new Error(regenData?.error || regenData?.detail || regenData?.message || '批量生成请求失败');
        }

        const taskId = regenData?.task_id;
        if (!taskId) {
            throw new Error('未返回任务ID');
        }

        const statusTextMap = {
            pending: '任务排队中...',
            running: '正在用新模板生成...',
            completed: '生成完成，正在更新页面...',
            failed: '生成失败',
            cancelled: '已取消'
        };

        const taskData = await pollBackgroundTaskUntilDone(taskId, {
            onTick: (task) => {
                const progress = typeof task.progress === 'number' ? Math.round(task.progress) : null;
                const message = statusTextMap[task.status] || '处理中...';
                loadingDiv.innerHTML = `
                    <i class="fas fa-spinner fa-spin"></i>
                    <div style="margin-top: 10px; font-weight: 700;">${message}${progress !== null ? ` (${progress}%)` : ''}</div>
                    <div style="margin-top: 6px; font-size: 12px; opacity: 0.85;">共 ${total} 页</div>
                `;
            }
        });

        const result = taskData?.result;
        if (!result?.success) {
            throw new Error(result?.error || result?.message || '模板更换失败');
        }

        const results = Array.isArray(result.results) ? result.results : [];
        let successCount = 0;
        let failCount = 0;

        results.forEach((item) => {
            if (item?.success && item?.slide_data && Number.isInteger(item.slide_index)) {
                slidesData[item.slide_index] = item.slide_data;
                if (typeof setInitialSlideState === 'function' && item.slide_data.html_content) {
                    setInitialSlideState(item.slide_index, item.slide_data.html_content);
                }
                updateThumbnailDisplay(item.slide_index, item.slide_data);

                if (currentSlideIndex === item.slide_index) {
                    updateMainPreview(item.slide_data);
                    updateCodeEditor(item.slide_data);
                }
                successCount += 1;
            } else if (item) {
                failCount += 1;
            }
        });

        if (document.querySelectorAll('.slide-thumbnail').length !== slidesData.length) {
            refreshSidebar();
        }

        if (typeof updateSelectedSlidesUI === 'function') {
            updateSelectedSlidesUI();
        }

        if (typeof clearSlideSelections === 'function') {
            clearSlideSelections();
        }
        if (typeof setSingleSlideSelection === 'function') {
            setSingleSlideSelection(currentSlideIndex);
        }

        if (failCount > 0) {
            showNotification(`模板更换完成：成功${successCount}页，失败${failCount}页`, 'warning');
        } else {
            showNotification(`模板更换成功！已更新 ${successCount} 页`, 'success');
        }
    } catch (error) {
        console.error('Template change error:', error);
        showNotification(`模板更换失败：${error.message}`, 'error');
    } finally {
        const loadingEl = document.getElementById('tplChangeLoading');
        if (loadingEl) {
            loadingEl.remove();
        }
    }
}

function _tplWarmupCardPreviews(templates) {
    templates.forEach((template) => {
        if (!template || template.preview_image) {
            return;
        }

        void _tplLoadCardPreview(template);
    });
}

async function _tplLoadCardPreview(template) {
    const templateKey = _tplGetTemplateKey(template);
    const cardContainer = document.getElementById(`tplCardPreview-${templateKey}`);
    if (!cardContainer || cardContainer.dataset.state === 'ready' || cardContainer.dataset.state === 'loading') {
        return;
    }

    cardContainer.dataset.state = 'loading';

    try {
        const detail = await _tplResolveTemplateDetail(template);
        const rendered = _tplRenderTemplatePreview(cardContainer, detail, { mode: 'card' });
        if (!rendered) {
            _tplRenderPreviewFallback(cardContainer, 'card', '暂无预览');
        }
        cardContainer.dataset.state = 'ready';
    } catch (error) {
        _tplRenderPreviewFallback(cardContainer, 'card', '预览失败');
        cardContainer.dataset.state = 'error';
        console.error(`Template card preview error (${templateKey}):`, error);
    }
}

async function _tplResolveTemplateDetail(template) {
    const normalizedTemplate = _tplNormalizeTemplate(template);
    if (!normalizedTemplate) {
        throw new Error('模板数据无效');
    }
    if (normalizedTemplate.html_template || normalizedTemplate.preview_image || !Number.isInteger(normalizedTemplate.id)) {
        return normalizedTemplate;
    }
    return _tplGetTemplateDetail(normalizedTemplate.id);
}

async function _tplGetTemplateDetail(templateId) {
    if (_tplDetailCache.has(templateId)) {
        return _tplDetailCache.get(templateId);
    }

    if (_tplDetailRequestCache.has(templateId)) {
        return _tplDetailRequestCache.get(templateId);
    }

    const requestTask = (async () => {
        const resp = await fetch(`/api/global-master-templates/${templateId}`);
        const data = await _tplReadJsonResponse(resp);
        if (!resp.ok) {
            throw new Error(data?.detail || data?.message || `模板 ${templateId} 加载失败`);
        }

        const template = _tplNormalizeTemplate(data);
        _tplDetailCache.set(templateId, template);
        return template;
    })();

    _tplDetailRequestCache.set(templateId, requestTask);

    try {
        return await requestTask;
    } finally {
        _tplDetailRequestCache.delete(templateId);
    }
}

function _tplRenderTemplatePreview(container, template, options = {}) {
    const mode = options.mode || 'detail';
    const normalizedTemplate = _tplNormalizeTemplate(template);
    if (!container || !normalizedTemplate) {
        return false;
    }

    _tplCleanupPreviewObservers(container);
    container.innerHTML = '';
    if (container.classList) {
        container.classList.remove('tpl-card-preview-shell--loading');
    }

    if (normalizedTemplate.preview_image) {
        const image = document.createElement('img');
        image.src = normalizedTemplate.preview_image;
        image.alt = normalizedTemplate.template_name || '模板预览';
        image.loading = 'lazy';
        container.appendChild(image);
        return true;
    }

    const previewUrl = _tplBuildPreviewUrl(normalizedTemplate);
    if (!previewUrl) {
        return false;
    }

    const stage = document.createElement('div');
    stage.className = mode === 'card' ? 'tpl-card-preview-stage' : 'tpl-preview-stage';

    const iframe = document.createElement('iframe');
    iframe.className = mode === 'card' ? 'tpl-card-preview-frame' : 'tpl-preview-frame';
    iframe.title = `${normalizedTemplate.template_name || '模板'}预览`;
    iframe.loading = 'lazy';

    const revokePreviewUrl = () => {
        setTimeout(() => {
            try {
                URL.revokeObjectURL(previewUrl);
            } catch (_) {
                // noop
            }
        }, 1500);
    };

    iframe.addEventListener('load', () => {
        requestAnimationFrame(() => _tplUpdateIframeScale(stage, iframe, mode));
        revokePreviewUrl();
    }, { once: true });

    iframe.addEventListener('error', () => {
        revokePreviewUrl();
        _tplRenderPreviewFallback(container, mode, '预览加载失败');
    }, { once: true });

    stage.appendChild(iframe);
    container.appendChild(stage);
    requestAnimationFrame(() => _tplUpdateIframeScale(stage, iframe, mode));

    if (mode === 'detail' && typeof ResizeObserver === 'function') {
        const observer = new ResizeObserver(() => {
            _tplUpdateIframeScale(stage, iframe, mode);
        });
        observer.observe(stage);
        stage._resizeObserver = observer;
    }

    iframe.src = previewUrl;
    return true;
}

function _tplRenderPreviewFallback(container, mode, message) {
    if (!container) {
        return;
    }

    _tplCleanupPreviewObservers(container);
    container.innerHTML = '';
    if (container.classList) {
        container.classList.remove('tpl-card-preview-shell--loading');
    }

    const fallback = document.createElement('div');
    fallback.className = mode === 'card' ? 'tpl-card-preview-placeholder' : 'tpl-preview-placeholder';

    if (mode === 'detail') {
        fallback.innerHTML = `<i class="fas fa-eye-slash"></i>${_escHtml(message || '暂无预览')}`;
    } else {
        fallback.textContent = message || '暂无预览';
    }

    container.appendChild(fallback);
}

function _tplUpdateIframeScale(stage, iframe, mode) {
    if (!stage || !iframe) {
        return;
    }

    const baseWidth = 1280;
    const baseHeight = 720;
    const rect = stage.getBoundingClientRect();
    if (!rect.width || !rect.height) {
        return;
    }

    const scale = Math.max(
        Math.min(rect.width / baseWidth, rect.height / baseHeight) - (mode === 'detail' ? 0.01 : 0),
        0.05
    );
    iframe.style.setProperty('--tpl-scale', String(scale));
}

function _tplBuildPreviewUrl(template) {
    const previewHtml = _tplBuildPreviewHtml(template);
    if (!previewHtml) {
        return '';
    }

    const blob = new Blob([previewHtml], { type: 'text/html' });
    return URL.createObjectURL(blob);
}

// 模板预览不直接使用原始 HTML，而是先替换占位符并补足预览容器，
// 这样即使模板没有生成 preview_image，也能稳定展示版式效果。
function _tplBuildPreviewHtml(template) {
    const rawHtml = typeof template?.html_template === 'string' ? template.html_template.trim() : '';
    if (!rawHtml) {
        return '';
    }

    const titleText = _tplEscapePreviewText(template.template_name || '模板预览');
    const descText = _tplEscapePreviewText(template.description || '这是模板预览内容，用于展示排版与视觉风格。');
    const bodyText = _tplEscapePreviewText('这是模板预览内容，用于展示当前模板的版式结构、字号层级与色彩风格。');
    const shortText = _tplEscapePreviewText('模板预览');

    const replacements = {
        template_name: titleText,
        title: titleText,
        page_title: titleText,
        main_heading: titleText,
        heading: titleText,
        subtitle: descText,
        page_subtitle: descText,
        sub_title: descText,
        description: descText,
        summary: descText,
        content: bodyText,
        page_content: bodyText,
        body_content: bodyText,
        main_content: bodyText,
        slide_content: bodyText,
        content_text: bodyText,
        text: shortText,
        current_page_number: '1',
        slide_number: '1',
        page_number: '1',
        total_page_count: '8',
        total_slides: '8',
        total_pages: '8'
    };

    let previewHtml = rawHtml;
    Object.entries(replacements).forEach(([key, value]) => {
        previewHtml = previewHtml.replace(new RegExp(`\\{\\{\\s*${key}\\s*\\}\\}`, 'gi'), value);
    });

    previewHtml = previewHtml.replace(/\{\{\s*[^}]+\s*\}\}/g, '');

    if (!/<html[\s>]/i.test(previewHtml)) {
        previewHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=1280, initial-scale=1.0">
    <title>${titleText}</title>
</head>
<body>${previewHtml}</body>
</html>`;
    } else if (!/<!DOCTYPE html>/i.test(previewHtml)) {
        previewHtml = `<!DOCTYPE html>\n${previewHtml}`;
    }

    const previewBaseStyle = `
<style id="tpl-preview-base-style">
html, body {
    width: 1280px !important;
    height: 720px !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    background: transparent;
}
body {
    position: relative;
}
</style>`;

    if (/<\/head>/i.test(previewHtml)) {
        previewHtml = previewHtml.replace(/<\/head>/i, `${previewBaseStyle}\n</head>`);
    } else {
        previewHtml = previewHtml.replace(/<html([^>]*)>/i, `<html$1><head>${previewBaseStyle}</head>`);
    }

    return previewHtml;
}

function _tplNormalizeTemplate(value) {
    if (!value || typeof value !== 'object') {
        return null;
    }

    const source = value.template && typeof value.template === 'object'
        ? value.template
        : value.selected_template && typeof value.selected_template === 'object'
            ? value.selected_template
            : value;

    if (!source || typeof source !== 'object') {
        return null;
    }

    const normalizedId = Number.isInteger(source.id)
        ? source.id
        : (source.id !== null && source.id !== undefined && !Number.isNaN(Number(source.id))
            ? Number(source.id)
            : null);

    return {
        ...source,
        id: normalizedId,
        template_key: typeof source.template_key === 'string' && source.template_key
            ? source.template_key
            : null,
        template_mode: typeof source.template_mode === 'string' ? source.template_mode : '',
        is_project_free_template: !!source.is_project_free_template,
        template_name: source.template_name || source.name || '未命名模板',
        description: typeof source.description === 'string' ? source.description : '',
        html_template: typeof source.html_template === 'string' ? source.html_template : '',
        preview_image: typeof source.preview_image === 'string' && source.preview_image.trim()
            ? source.preview_image.trim()
            : '',
        tags: Array.isArray(source.tags) ? source.tags : []
    };
}

async function _tplReadJsonResponse(response) {
    const rawText = await response.text();
    if (!rawText) {
        return {};
    }

    try {
        return JSON.parse(rawText);
    } catch (error) {
        const snippet = rawText.slice(0, 200).replace(/\s+/g, ' ').trim();
        throw new Error(`接口返回非JSON：${response.status} ${response.statusText}${snippet ? ` - ${snippet}` : ''}`);
    }
}

function _tplCleanupPreviewObservers(root) {
    if (!root || typeof root.querySelectorAll !== 'function') {
        return;
    }

    root.querySelectorAll('.tpl-preview-stage, .tpl-card-preview-stage').forEach((stage) => {
        if (stage._resizeObserver) {
            stage._resizeObserver.disconnect();
            delete stage._resizeObserver;
        }
    });
}

function _tplGetProjectId() {
    return window.landpptEditorConfig?.projectId || '';
}

function _tplEscapePreviewText(text) {
    return _escHtml(text || '');
}

function _escHtml(str) {
    if (!str) {
        return '';
    }

    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
