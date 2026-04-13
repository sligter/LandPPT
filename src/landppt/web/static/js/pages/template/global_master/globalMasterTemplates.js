import { apiClient } from '../../../modules/apiClient.js';
import { debounce, formatBytes } from '../../../modules/domUtils.js';
import { emit } from '../../../modules/eventBus.js';
import { ensureDomToPptxReady, sanitizeFileName, setButtonLoadingState, renderTemplateSampleHtml, loadHtmlIntoIframe, waitForIframeVisualReady } from './globalMasterTemplates.exportHelpers.js';
import { createGlobalMasterTemplatesUpload } from './globalMasterTemplates.upload.js';

const currentUser = window.__LANDPPT_USER__ || {};
const isAdminUser = Boolean(currentUser.is_admin);

const state = {
    templates: [],
    editingTemplateId: null,
    currentPage: 1,
    pageSize: 6,
    totalPages: 1,
    totalCount: 0,
    currentSearch: '',
    currentTag: '',
    uploadedImage: null,
    uploadedPptx: null,
    generatedTemplate: null,
    effectiveDefaultTemplateId: null,
};

const dom = {};
const previewCache = new Map();
let previewObserver;
let tagsLoaded = false;
let isExportingTemplatePptx = false;

const uploadApi = createGlobalMasterTemplatesUpload({ state, apiClient, formatBytes, loadTemplates });

document.addEventListener('DOMContentLoaded', () => {
    cacheDom();
    bindEvents();
    uploadApi.initImageUpload();
    loadTemplates(1);
});

function cacheDom() {
    dom.templatesGrid = document.getElementById('templatesGrid');
    dom.loadingIndicator = document.getElementById('loadingIndicator');
    dom.tagFilter = document.getElementById('tagFilter');
    dom.searchInput = document.getElementById('searchInput');
    dom.refreshBtn = document.getElementById('refreshBtn');
    dom.paginationContainer = document.getElementById('paginationContainer');
    dom.paginationInfo = document.getElementById('paginationInfo');
    dom.pageNumbers = document.getElementById('pageNumbers');
    dom.prevPageBtn = document.getElementById('prevPageBtn');
    dom.nextPageBtn = document.getElementById('nextPageBtn');
    dom.pageSizeSelect = document.getElementById('pageSizeSelect');

    dom.templateModal = document.getElementById('templateModal');
    dom.modalTitle = document.getElementById('modalTitle');
    dom.templateForm = document.getElementById('templateForm');

    dom.aiModal = document.getElementById('aiGenerationModal');
    dom.aiFormContainer = document.getElementById('aiFormContainer');
    dom.aiGenerationForm = document.getElementById('aiGenerationForm');
    dom.aiGenerationProgress = document.getElementById('aiGenerationProgress');
    dom.aiGenerationComplete = document.getElementById('aiGenerationComplete');
    dom.statusText = document.getElementById('statusText');

    dom.previewModal = document.getElementById('previewModal');
    dom.previewFrame = document.getElementById('previewFrame');

    dom.generatedTemplateIframe = document.getElementById('generatedTemplateIframe');
    dom.rawResponseCode = document.getElementById('rawResponseCode');
    dom.llmResponseContainer = document.getElementById('llmResponseContainer');
    dom.adjustmentInput = document.getElementById('adjustmentInput');
    dom.adjustmentProgress = document.getElementById('adjustmentProgress');
}

function bindEvents() {
    document.getElementById('createTemplateBtn')?.addEventListener('click', () => openTemplateModal());
    document.getElementById('generateWithAIBtn')?.addEventListener('click', openAIGenerationModal);
    document.getElementById('closeModal')?.addEventListener('click', closeTemplateModal);
    document.getElementById('closeAIModal')?.addEventListener('click', closeAIGenerationModal);
    document.getElementById('closePreviewModal')?.addEventListener('click', closePreviewModal);
    document.getElementById('cancelBtn')?.addEventListener('click', closeTemplateModal);
    document.getElementById('cancelAIBtn')?.addEventListener('click', closeAIGenerationModal);
    document.getElementById('cancelGenerationBtn')?.addEventListener('click', showAIGenerationForm);
    document.getElementById('closeCompletionBtn')?.addEventListener('click', () => {
        closeAIGenerationModal();
        loadTemplates(1);
    });

    document.getElementById('saveGeneratedTemplateBtn')?.addEventListener('click', saveGeneratedTemplate);
    document.getElementById('adjustTemplateBtn')?.addEventListener('click', adjustTemplate);
    document.getElementById('regenerateTemplateBtn')?.addEventListener('click', () => {
        dom.aiGenerationComplete.style.display = 'none';
        dom.aiFormContainer.style.display = 'block';
        state.generatedTemplate = null;
    });
    document.getElementById('fullPreviewBtn')?.addEventListener('click', () => {
        if (state.generatedTemplate?.html_template) {
            showPreview(state.generatedTemplate.html_template);
        }
    });
    document.getElementById('toggleLLMResponseBtn')?.addEventListener('click', toggleLLMResponse);
    document.getElementById('copyResponseBtn')?.addEventListener('click', copyLLMResponse);
    document.getElementById('previewTemplateBtn')?.addEventListener('click', previewCurrentTemplate);

    document.getElementById('importTemplateBtn')?.addEventListener('click', () => {
        document.getElementById('importTemplateInput')?.click();
    });
    document.getElementById('importTemplateInput')?.addEventListener('change', uploadApi.handleTemplateImport);

    dom.templateForm?.addEventListener('submit', handleTemplateSubmit);
    dom.aiGenerationForm?.addEventListener('submit', handleAIGeneration);
    dom.templatesGrid?.addEventListener('click', handleTemplateGridClick);

    dom.searchInput?.addEventListener('input', debounce(() => {
        state.currentSearch = dom.searchInput.value.trim();
        loadTemplates(1);
    }, 400));
    dom.tagFilter?.addEventListener('change', () => {
        state.currentTag = dom.tagFilter.value;
        loadTemplates(1);
    });
    dom.refreshBtn?.addEventListener('click', () => loadTemplates(1));
    dom.prevPageBtn?.addEventListener('click', () => loadTemplates(state.currentPage - 1));
    dom.nextPageBtn?.addEventListener('click', () => loadTemplates(state.currentPage + 1));
    dom.pageSizeSelect?.addEventListener('change', () => {
        state.pageSize = parseInt(dom.pageSizeSelect.value, 10) || 6;
        loadTemplates(1);
    });

    window.addEventListener('click', (event) => {
        if (event.target.classList?.contains('modal')) {
            event.target.style.display = 'none';
        }
    });
}

async function loadTemplates(page = 1) {
    showLoading(true);
    try {
        const params = {
            active_only: 'true',
            page,
            page_size: state.pageSize,
        };

        if (state.currentSearch) {
            params.search = state.currentSearch;
        }

        if (state.currentTag) {
            params.tags = state.currentTag;
        }

        const [templatesResult, defaultTemplateResult] = await Promise.allSettled([
            apiClient.get('/api/global-master-templates/', params),
            apiClient.get('/api/global-master-templates/default/template')
        ]);

        if (templatesResult.status !== 'fulfilled') {
            throw templatesResult.reason;
        }

        const data = templatesResult.value;
        state.effectiveDefaultTemplateId = defaultTemplateResult.status === 'fulfilled'
            ? Number(defaultTemplateResult.value?.id) || null
            : null;

        state.templates = data.templates || [];
        applyEffectiveDefaultFlags(state.templates);
        state.currentPage = data.pagination.current_page;
        state.totalPages = data.pagination.total_pages;
        state.totalCount = data.pagination.total_count;

        renderTemplates();
        updatePagination();
        if (!tagsLoaded) {
            await updateTagFilter();
            tagsLoaded = true;
        }
        emit('templates:loaded', { count: state.templates.length, page: state.currentPage });
    } catch (error) {
        console.error('Error loading templates:', error);
        alert('加载模板失败: ' + error.message);
    } finally {
        showLoading(false);
    }
}

function applyEffectiveDefaultFlags(templates) {
    if (!Array.isArray(templates)) return;

    const effectiveId = state.effectiveDefaultTemplateId;
    templates.forEach((template) => {
        template.is_effective_default = effectiveId !== null
            ? Number(template.id) === effectiveId
            : Boolean(template.is_default);
    });
}

function renderTemplates() {
    if (!dom.templatesGrid) return;
    dom.templatesGrid.innerHTML = '';

    if (state.templates.length === 0) {
        dom.templatesGrid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: #666;">
                <h3>暂无模板</h3>
                <p>点击“新建模板”或“AI生成模板”来创建第一个母版</p>
            </div>
        `;
        return;
    }

    const fragment = document.createDocumentFragment();
    state.templates.forEach((template) => {
        fragment.appendChild(buildTemplateCard(template));
    });

    dom.templatesGrid.appendChild(fragment);
    setupPreviewObserver();
}

function buildTemplateCard(template) {
    const card = document.createElement('div');
    card.className = 'template-card';
    card.dataset.templateId = template.id;

    const tags = (template.tags || []).map((tag) => `<span class="tag">${tag}</span>`).join('');
    const showDefaultBadge = template.is_effective_default ?? template.is_default;
    const defaultBadge = showDefaultBadge ? '<span class="default-badge">默认</span>' : '';
    const isUserOwnedTemplate = template.user_id !== null && template.user_id !== undefined;
    const canEditOrDelete = isAdminUser || isUserOwnedTemplate;
    const canSetDefault = isUserOwnedTemplate || isAdminUser;
    const actions = [
        canEditOrDelete ? `<button class="btn btn-sm btn-primary" data-action="edit" data-template-id="${template.id}"><i class="fas fa-pen"></i> 编辑</button>` : '',
        `<button class="btn btn-sm btn-secondary" data-action="duplicate" data-template-id="${template.id}"><i class="fas fa-clone"></i> 复制</button>`,
        `<button class="btn btn-sm btn-outline" data-action="export-json" data-template-id="${template.id}"><i class="fas fa-download"></i> 导出JSON</button>`,
        `<button class="btn btn-sm btn-outline" data-action="export-pptx" data-template-id="${template.id}"><i class="fas fa-file-powerpoint"></i> 导出PPTX</button>`,
        canSetDefault && !showDefaultBadge ? `<button class="btn btn-sm btn-success" data-action="set-default" data-template-id="${template.id}"><i class="fas fa-check"></i> 设为默认</button>` : '',
        canEditOrDelete && !template.is_default ? `<button class="btn btn-sm btn-danger" data-action="delete" data-template-id="${template.id}"><i class="fas fa-trash"></i> 删除</button>` : '',
    ].filter(Boolean).join('');

    card.innerHTML = `
        <div class="template-preview">
            <iframe
                class="template-preview-iframe"
                title="${template.template_name}"
                data-template-id="${template.id}"
                loading="lazy"
            ></iframe>
            <div class="preview-overlay" data-action="preview" data-template-id="${template.id}" title="点击查看完整预览">
                <div class="preview-overlay-text"><i class="fas fa-search-plus"></i> 点击放大预览</div>
            </div>
        </div>
        <div class="template-info">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <h4 style="margin: 0; color: #2c3e50; font-size: 16px;">${template.template_name}</h4>
                ${defaultBadge}
            </div>
            <p style="margin: 0 0 8px 0; color: #666; font-size: 14px; line-height: 1.4;">${template.description || '暂无描述'}</p>
            <div style="margin-bottom: 8px;">${tags}</div>
            <div style="font-size: 12px; color: #999;">使用次数: ${template.usage_count} | 创建者: ${template.created_by}</div>
        </div>
        <div class="template-actions">
            ${actions}
        </div>
    `;

    return card;
}

function setupPreviewObserver() {
    if (!dom.templatesGrid) return;
    if (!previewObserver) {
        previewObserver = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    const iframe = entry.target;
                    const templateId = Number(iframe.dataset.templateId);
                    loadTemplatePreview(templateId, iframe);
                    previewObserver.unobserve(iframe);
                }
            });
        }, { root: dom.templatesGrid, rootMargin: '120px' });
    }

    dom.templatesGrid.querySelectorAll('.template-preview-iframe').forEach((iframe) => {
        previewObserver.observe(iframe);
    });
}

async function loadTemplatePreview(templateId, iframe) {
    if (!iframe) return;
    try {
        const cached = previewCache.get(templateId);
        if (cached) {
            setIframeContent(iframe, cached.html_template);
            return;
        }

        const template = await apiClient.get(`/api/global-master-templates/${templateId}`);
        previewCache.set(templateId, template);
        setIframeContent(iframe, template.html_template, template.template_name);
    } catch (error) {
        console.warn('预览加载失败', error);
        iframe.replaceWith(createPreviewFallback());
    }
}

function setIframeContent(iframe, htmlTemplate, title = '') {
    if (!iframe || !htmlTemplate) return;

    let previewHtml = htmlTemplate;
    previewHtml = previewHtml.replace(/\{\{\s*title\s*\}\}/g, title || '模板预览');
    previewHtml = previewHtml.replace(/\{\{\s*content\s*\}\}/g, '预览内容');
    previewHtml = previewHtml.replace(/\{\{\s*slide_number\s*\}\}/g, '1');
    previewHtml = previewHtml.replace(/\{\{\s*total_slides\s*\}\}/g, '1');

    if (!previewHtml.includes('<html')) {
        previewHtml = `<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><style>body { width: 1280px; height: 720px; margin: 0; padding: 0; }</style></head>
<body>${previewHtml}</body>
</html>`;
    }

    const blob = new Blob([previewHtml], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    iframe.onload = () => setTimeout(() => URL.revokeObjectURL(url), 1500);
    iframe.onerror = () => URL.revokeObjectURL(url);
    iframe.src = url;
}

function createPreviewFallback() {
    const div = document.createElement('div');
    div.style.cssText = 'display:flex;align-items:center;justify-content:center;height:220px;color:#999;background:#f8f9fa;border:1px dashed #ddd;border-radius:10px;';
    div.textContent = '预览加载失败';
    return div;
}

function handleTemplateGridClick(event) {
    const target = event.target.closest('[data-action]');
    if (!target) return;
    const templateId = Number(target.dataset.templateId);
    const action = target.dataset.action;

    switch (action) {
        case 'edit':
            openTemplateModal(templateId);
            break;
        case 'duplicate':
            duplicateTemplate(templateId);
            break;
        case 'export-json':
        case 'export':
            exportTemplate(templateId);
            break;
        case 'export-pptx':
            exportTemplateAsPptxTemplate(templateId, target);
            break;
        case 'set-default':
            setDefaultTemplate(templateId);
            break;
        case 'delete':
            deleteTemplate(templateId);
            break;
        case 'preview':
            previewTemplateById(templateId);
            break;
        default:
            break;
    }
}

function showLoading(show) {
    if (!dom.loadingIndicator || !dom.templatesGrid) return;
    dom.loadingIndicator.style.display = show ? 'flex' : 'none';
    dom.templatesGrid.style.display = show ? 'none' : 'grid';
}

async function updateTagFilter() {
    if (!dom.tagFilter) return;
    const allTags = new Set();
    const maxPageSize = 100; // FastAPI constraint: page_size <= 100
    let currentPage = 1;
    let totalPages = 1;

    try {
        do {
            const data = await apiClient.get('/api/global-master-templates/', {
                active_only: 'true',
                page_size: maxPageSize,
                page: currentPage
            });

            (data.templates || []).forEach((template) => {
                (template.tags || []).forEach((tag) => allTags.add(tag.trim()));
            });

            totalPages = data.pagination?.total_pages || 1;
            currentPage += 1;
        } while (currentPage <= totalPages);

        const currentValue = dom.tagFilter.value;
        dom.tagFilter.innerHTML = '<option value="">所有标签</option>';
        Array.from(allTags)
            .filter(Boolean)
            .sort()
            .forEach((tag) => {
                const option = document.createElement('option');
                option.value = tag;
                option.textContent = tag;
                dom.tagFilter.appendChild(option);
            });

        if (currentValue && allTags.has(currentValue)) {
            dom.tagFilter.value = currentValue;
        }
    } catch (error) {
        console.warn('标签加载失败', error);
        dom.tagFilter.innerHTML = '<option value="">所有标签</option>';
    }
}

function openTemplateModal(templateId = null) {
    state.editingTemplateId = templateId;
    dom.modalTitle.textContent = templateId ? '编辑母版' : '新建母版';
    dom.templateForm?.reset();
    if (templateId) {
        loadTemplateForEdit(templateId);
    }
    dom.templateModal.style.display = 'flex';
}

async function loadTemplateForEdit(templateId) {
    try {
        const template = await apiClient.get(`/api/global-master-templates/${templateId}`);
        document.getElementById('templateName').value = template.template_name || '';
        document.getElementById('templateDescription').value = template.description || '';
        document.getElementById('templateTags').value = (template.tags || []).join(', ');
        document.getElementById('isDefault').checked = Boolean(template.is_default);
        document.getElementById('htmlTemplate').value = template.html_template || '';
    } catch (error) {
        alert('加载模板失败: ' + error.message);
    }
}

function closeTemplateModal() {
    state.editingTemplateId = null;
    dom.templateModal.style.display = 'none';
}

async function handleTemplateSubmit(event) {
    event.preventDefault();
    const formData = new FormData(dom.templateForm);
    const payload = {
        template_name: formData.get('template_name'),
        description: formData.get('description'),
        html_template: formData.get('html_template'),
        tags: (formData.get('tags') || '').split(',').map((tag) => tag.trim()).filter(Boolean),
        is_default: formData.get('is_default') === 'on',
    };

    try {
        if (state.editingTemplateId) {
            await apiClient.put(`/api/global-master-templates/${state.editingTemplateId}`, payload);
            emit('templates:updated', { action: 'update', id: state.editingTemplateId });
        } else {
            await apiClient.post('/api/global-master-templates/', payload);
            emit('templates:updated', { action: 'create' });
        }
        closeTemplateModal();
        loadTemplates(state.editingTemplateId ? state.currentPage : 1);
    } catch (error) {
        alert('保存失败: ' + error.message);
    }
}

function previewCurrentTemplate() {
    const htmlTemplate = document.getElementById('htmlTemplate')?.value;
    if (!htmlTemplate) {
        alert('请先输入HTML模板内容');
        return;
    }
    showPreview(htmlTemplate);
}

function openAIGenerationModal() {
    dom.aiModal.style.display = 'flex';
    dom.aiGenerationForm?.reset();
    showAIGenerationForm();
    state.generatedTemplate = null;
    uploadApi.clearUploadedImage();
    uploadApi.clearUploadedPptx();
}

function showAIGenerationForm() {
    dom.aiFormContainer.style.display = 'block';
    dom.aiGenerationProgress.style.display = 'none';
    dom.aiGenerationComplete.style.display = 'none';
    updateStatusText('准备开始生成');
}

function closeAIGenerationModal() {
    dom.aiModal.style.display = 'none';
    state.generatedTemplate = null;
    uploadApi.clearUploadedImage();
    uploadApi.clearUploadedPptx();
}

async function handleAIGeneration(event) {
    event.preventDefault();
    const formData = new FormData(dom.aiGenerationForm);
    const payload = {
        prompt: formData.get('prompt'),
        template_name: formData.get('template_name'),
        description: formData.get('description'),
        tags: (formData.get('tags') || '').split(',').map((tag) => tag.trim()).filter(Boolean),
        generation_mode: formData.get('generation_mode') || 'text_only',
    };

    if (payload.generation_mode === 'pptx_extract') {
        if (!state.uploadedPptx) {
            alert('请上传 PPTX 文件后再生成');
            return;
        }
        payload.reference_pptx = { ...state.uploadedPptx };
    } else if (state.uploadedImage && payload.generation_mode !== 'text_only') {
        payload.reference_image = { ...state.uploadedImage };
    } else if (payload.generation_mode !== 'text_only') {
        alert('请上传参考图片后再生成');
        return;
    }

    try {
        dom.aiFormContainer.style.display = 'none';
        dom.aiGenerationProgress.style.display = 'block';
        updateStatusText('正在请求AI生成...');

        const result = await apiClient.post('/api/global-master-templates/generate', payload);
        const templateData = normalizeTemplateData(result);
        await handleGenerationComplete(templateData);
        updateStatusText('模板生成完成');
        showAIGenerationComplete();
    } catch (error) {
        console.error('生成失败', error);
        showAIGenerationError(error.message);
    }
}

function normalizeTemplateData(result) {
    if (typeof result === 'string') {
        const parsed = parseTemplateStreamResponse(result);
        if (parsed) return normalizeTemplateData(parsed);
        throw new Error('生成失败');
    }
    if (!result) {
        throw new Error('生成结果为空');
    }
    if (result.success && result.data) return result.data;
    if (result.data && result.data.html_template) return result.data;
    if (result.html_template) return result;
    throw new Error(result.message || '生成失败');
}

function parseTemplateStreamResponse(rawText) {
    if (!rawText || typeof rawText !== 'string') return null;

    const normalized = rawText.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');

    // Sometimes it is plain JSON as text.
    const trimmed = normalized.trim();
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
        try {
            return JSON.parse(trimmed);
        } catch (e) {
            // fall through to SSE parsing
        }
    }

    // SSE: parse blocks separated by blank lines; each block can contain multiple `data:` lines.
    const events = [];
    const blocks = normalized.split(/\n\s*\n/);
    for (const block of blocks) {
        const lines = (block || '').split('\n');
        const dataLines = [];
        for (const line of lines) {
            const trimmedLine = (line || '').replace(/^\uFEFF/, '').trim();
            if (!trimmedLine.startsWith('data:')) continue;
            dataLines.push(trimmedLine.slice(5).trimStart());
        }
        if (!dataLines.length) continue;

        const data = dataLines.join('\n').trim();
        if (!data) continue;

        try {
            events.push(JSON.parse(data));
        } catch (e) {
            // ignore invalid JSON events (some servers may emit non-JSON data lines)
        }
    }

    const lastError = [...events].reverse().find((event) => event && event.type === 'error' && event.message);
    if (lastError) {
        throw new Error(lastError.message);
    }

    const complete = [...events].reverse().find((event) => event && event.type === 'complete' && event.html_template);
    if (complete) return complete;

    const anyTemplate = [...events].reverse().find((event) => event && event.html_template);
    if (anyTemplate) return anyTemplate;

    return null;
}

async function handleGenerationComplete(templateData) {
    state.generatedTemplate = templateData;
    renderGeneratedPreview(templateData.html_template);
    renderLLMResponse(templateData.raw_response || templateData.llm_response || templateData.html_template);
}

function renderGeneratedPreview(html) {
    if (!dom.generatedTemplateIframe || !html) return;
    setIframeContent(dom.generatedTemplateIframe, html, state.generatedTemplate?.template_name || 'AI 生成结果');
}

function renderLLMResponse(rawResponse) {
    if (!dom.rawResponseCode) return;
    dom.rawResponseCode.textContent = typeof rawResponse === 'string'
        ? rawResponse
        : JSON.stringify(rawResponse, null, 2);
}

function showAIGenerationComplete() {
    dom.aiGenerationProgress.style.display = 'none';
    dom.aiGenerationComplete.style.display = 'block';
}

function showAIGenerationError(message) {
    dom.aiGenerationProgress.style.display = 'none';
    dom.aiFormContainer.style.display = 'block';
    alert('AI生成失败: ' + message);
}

async function saveGeneratedTemplate() {
    if (!state.generatedTemplate) {
        alert('没有可保存的模板');
        return;
    }
    try {
        await apiClient.post('/api/global-master-templates/save-generated', state.generatedTemplate);
        alert('模板已保存');
        closeAIGenerationModal();
        loadTemplates(1);
    } catch (error) {
        alert('保存失败: ' + error.message);
    }
}

async function adjustTemplate() {
    if (!state.generatedTemplate) {
        alert('请先生成模板');
        return;
    }
    const adjustment = dom.adjustmentInput.value.trim();
    if (!adjustment) {
        alert('请输入调整意见');
        return;
    }
    try {
        dom.adjustmentProgress.style.display = 'block';
        const result = await apiClient.post('/api/global-master-templates/adjust-template', {
            adjustment,
            template_data: state.generatedTemplate,
        });
        const templateData = normalizeTemplateData(result);
        state.generatedTemplate = templateData;
        renderGeneratedPreview(templateData.html_template);
        renderLLMResponse(templateData.raw_response || templateData.llm_response || templateData.html_template);
    } catch (error) {
        alert('调整失败: ' + error.message);
    } finally {
        dom.adjustmentProgress.style.display = 'none';
    }
}

async function previewTemplateById(templateId) {
    try {
        const data = await apiClient.get(`/api/global-master-templates/${templateId}/preview`);
        showPreview(data.html_template || data);
    } catch (error) {
        alert('预览加载失败: ' + error.message);
    }
}

function showPreview(htmlContent) {
    if (!dom.previewFrame) return;
    setIframeContent(dom.previewFrame, htmlContent || '<div style="padding:20px;">暂无预览内容</div>');
    dom.previewModal.style.display = 'flex';
}

function closePreviewModal() {
    dom.previewModal.style.display = 'none';
}

async function duplicateTemplate(templateId) {
    const newName = prompt('请输入新模板名称:');
    if (!newName) return;
    try {
        await apiClient.post(`/api/global-master-templates/${templateId}/duplicate?new_name=${encodeURIComponent(newName.trim())}`);
        loadTemplates(state.currentPage);
        emit('templates:updated', { action: 'duplicate', id: templateId });
    } catch (error) {
        alert('复制失败: ' + error.message);
    }
}

async function setDefaultTemplate(templateId) {
    if (!confirm('确认将此模板设为默认吗？')) return;
    try {
        await apiClient.post(`/api/global-master-templates/${templateId}/set-default`);
        loadTemplates(state.currentPage);
        emit('templates:updated', { action: 'set-default', id: templateId });
    } catch (error) {
        alert('设置默认失败: ' + error.message);
    }
}

async function deleteTemplate(templateId) {
    if (!confirm('确认删除该模板？')) return;
    try {
        await apiClient.del(`/api/global-master-templates/${templateId}`);
        const shouldGoPrev = state.templates.length === 1 && state.currentPage > 1;
        loadTemplates(shouldGoPrev ? state.currentPage - 1 : state.currentPage);
        emit('templates:updated', { action: 'delete', id: templateId });
    } catch (error) {
        alert('删除失败: ' + error.message);
    }
}

async function exportTemplate(templateId) {
    try {
        const template = await apiClient.get(`/api/global-master-templates/${templateId}`);
        const exportData = {
            template_name: template.template_name,
            description: template.description,
            html_template: template.html_template,
            tags: template.tags,
            is_default: false,
            export_info: {
                exported_at: new Date().toISOString(),
                original_id: template.id,
                original_created_at: template.created_at,
            },
        };
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `${template.template_name}_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(link.href), 500);
    } catch (error) {
        alert('导出失败: ' + error.message);
    }
}

async function exportTemplateAsPptxTemplate(templateId, triggerButton = null) {
    if (isExportingTemplatePptx) {
        alert('已有PPTX模板导出任务进行中，请稍候');
        return;
    }

    let exporter;
    let renderHost;

    try {
        isExportingTemplatePptx = true;
        setButtonLoadingState(triggerButton, true, '导出PPTX中...');
        exporter = await ensureDomToPptxReady();
        if (!exporter || typeof exporter.exportToPptx !== 'function') {
            throw new Error('PPTX导出库不可用');
        }

        const template = await apiClient.get(`/api/global-master-templates/${templateId}`);
        if (!template?.html_template) {
            throw new Error('模板内容为空，无法导出PPTX模板');
        }

        const sampleSlides = [
            {
                kind: 'template',
                pageTitle: '',
                mainHeading: '',
                subtitle: '',
                pageContent: '',
                notes: ''
            }
        ];
        const totalPages = sampleSlides.length;
        const slideNotes = [];

        renderHost = document.createElement('div');
        renderHost.style.cssText = 'position:fixed;left:-99999px;top:-99999px;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none;z-index:-1;';
        document.body.appendChild(renderHost);

        const slideElementStream = (async function* () {
            for (let index = 0; index < sampleSlides.length; index += 1) {
                const sample = sampleSlides[index];
                let iframe = null;

                try {
                    iframe = document.createElement('iframe');
                    iframe.style.cssText = 'width:1280px;height:720px;border:none;background:#fff;';
                    iframe.setAttribute('aria-hidden', 'true');
                    renderHost.appendChild(iframe);

                    const renderedHtml = renderTemplateSampleHtml(
                        template.html_template,
                        sample,
                        index + 1,
                        totalPages
                    );

                    await loadHtmlIntoIframe(iframe, renderedHtml);
                    await waitForIframeVisualReady(iframe);

                    const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
                    if (!iframeDoc?.body) {
                        throw new Error(`第${index + 1}页渲染失败`);
                    }

                    yield iframeDoc.body;
                } finally {
                    if (iframe && iframe.parentNode) {
                        iframe.parentNode.removeChild(iframe);
                    }
                }
            }
        })();

        const fileName = `${sanitizeFileName(template.template_name || '模板')}_PPTX模板.pptx`;
        await exporter.exportToPptx(slideElementStream, {
            fileName,
            svgAsVector: false,
            slideNotes
        });

        alert('PPTX模板导出完成');
    } catch (error) {
        console.error('导出PPTX模板失败:', error);
        alert('导出PPTX模板失败: ' + (error?.message || '未知错误'));
    } finally {
        if (renderHost && renderHost.parentNode) {
            renderHost.parentNode.removeChild(renderHost);
        }
        setButtonLoadingState(triggerButton, false);
        isExportingTemplatePptx = false;
    }
}

function updateStatusText(text) {
    if (dom.statusText) {
        dom.statusText.textContent = text;
    }
}

function toggleLLMResponse() {
    if (!dom.llmResponseContainer) return;
    const btn = document.getElementById('toggleLLMResponseBtn');
    const isHidden = dom.llmResponseContainer.style.display === 'none';
    dom.llmResponseContainer.style.display = isHidden ? 'block' : 'none';
    if (btn) {
        btn.textContent = isHidden ? '收起完整响应' : '查看完整响应';
        btn.classList.toggle('btn-outline-info', !isHidden);
    }
}

function copyLLMResponse() {
    if (!dom.rawResponseCode) return;
    const text = dom.rawResponseCode.textContent || '';
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById('copyResponseBtn');
        if (btn) {
            const original = btn.textContent;
            btn.textContent = '已复制';
            setTimeout(() => { btn.textContent = original; }, 1500);
        }
    }).catch(() => alert('复制失败，请手动复制'));
}

function updatePagination() {
    if (!dom.paginationContainer) return;
    if (state.totalCount === 0) {
        dom.paginationContainer.style.display = 'none';
        return;
    }
    dom.paginationContainer.style.display = 'block';
    const startItem = (state.currentPage - 1) * state.pageSize + 1;
    const endItem = Math.min(state.currentPage * state.pageSize, state.totalCount);
    dom.paginationInfo.textContent = `${startItem}-${endItem} / ${state.totalCount} 条`;
    dom.prevPageBtn.disabled = state.currentPage <= 1;
    dom.nextPageBtn.disabled = state.currentPage >= state.totalPages;
    renderPageNumbers();
}

function renderPageNumbers() {
    if (!dom.pageNumbers) return;
    dom.pageNumbers.innerHTML = '';
    const maxVisible = 5;
    let start = Math.max(1, state.currentPage - Math.floor(maxVisible / 2));
    let end = Math.min(state.totalPages, start + maxVisible - 1);
    if (end - start + 1 < maxVisible) {
        start = Math.max(1, end - maxVisible + 1);
    }

    if (start > 1) {
        dom.pageNumbers.appendChild(createPageButton(1));
        if (start > 2) dom.pageNumbers.appendChild(createEllipsis());
    }

    for (let i = start; i <= end; i++) {
        dom.pageNumbers.appendChild(createPageButton(i));
    }

    if (end < state.totalPages) {
        if (end < state.totalPages - 1) dom.pageNumbers.appendChild(createEllipsis());
        dom.pageNumbers.appendChild(createPageButton(state.totalPages));
    }
}

function createPageButton(pageNum) {
    const btn = document.createElement('button');
    btn.className = `page-number ${pageNum === state.currentPage ? 'active' : ''}`;
    btn.textContent = pageNum;
    btn.addEventListener('click', () => loadTemplates(pageNum));
    return btn;
}

function createEllipsis() {
    const span = document.createElement('span');
    span.className = 'page-number disabled';
    span.textContent = '...';
    return span;
}
