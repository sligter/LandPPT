import { apiClient } from '../../modules/apiClient.js';
import { debounce } from '../../modules/domUtils.js';
import { emit } from '../../modules/eventBus.js';

// 全局变量
let currentImages = [];
let filteredImages = [];
let currentPage = 1;
let itemsPerPage = 20;
let batchMode = false;
let selectedImages = new Set();
let currentImageDetail = null;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initializeGallery);

function initializeGallery() {
    bindControls();
    bindGridEvents();
    bindBatchToolbarEvents();
    bindUploadEvents();
    bindDetailModalEvents();
    bindKeyboardShortcuts();
    loadImages();
}

// 加载图片列表
async function loadImages(page = 1) {
    try {
        const category = document.getElementById('category-filter').value;
        const search = document.getElementById('search-input').value;
        const sort = document.getElementById('sort-option').value;

        const data = await apiClient.get('/api/image/gallery/list', {
            page,
            per_page: itemsPerPage,
            category: category === 'all' ? '' : category,
            search,
            sort
        });

        if (data.success) {
            currentImages = data.images;
            filteredImages = currentImages;
            currentPage = page;

            renderImageGrid();
            renderPagination(data.pagination);
            emit('gallery:loaded', { count: currentImages.length, page: currentPage });
        } else {
            showError('加载图片失败: ' + data.message);
        }
    } catch (error) {
        console.error('Failed to load images:', error);
        showError('加载图片失败');
    }
}

// 渲染图片网格（使用 DocumentFragment + IntersectionObserver 懒加载）
const placeholderSrc = 'data:image/svg+xml,%3Csvg xmlns=\"http://www.w3.org/2000/svg\" width=\"400\" height=\"250\" viewBox=\"0 0 400 250\"%3E%3Crect width=\"400\" height=\"250\" fill=\"%23f3f4f6\"/%3E%3Ctext x=\"200\" y=\"130\" text-anchor=\"middle\" fill=\"%239ca3af\" font-family=\"Arial,sans-serif\" font-size=\"20\"%3Epreview%3C/text%3E%3C/svg%3E';

const lazyObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const target = entry.target;
            if (target.dataset.src) {
                target.src = target.dataset.src;
                lazyObserver.unobserve(target);
            }
        }
    });
}, { rootMargin: '120px' });

function renderImageGrid() {
    const grid = document.getElementById('image-grid');

    if (!grid) return;

    if (filteredImages.length === 0) {
        grid.innerHTML = `
            <div class="loading-placeholder" style="text-align: center; padding: 60px; color: #7f8c8d; grid-column: 1 / -1;">
                <div style="font-size: 3em; margin-bottom: 20px;"><i class="fas fa-image"></i></div>
                <p>暂无图片</p>
            </div>
        `;
        return;
    }

    const fragment = document.createDocumentFragment();
    grid.innerHTML = '';

    filteredImages.forEach(image => {
        const item = document.createElement('div');
        item.className = `image-item ${selectedImages.has(image.image_id) ? 'selected' : ''}`;
        item.dataset.imageId = image.image_id;

        if (batchMode) {
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'batch-checkbox';
            checkbox.checked = selectedImages.has(image.image_id);
            checkbox.dataset.imageId = image.image_id;
            item.appendChild(checkbox);
        }

        const img = document.createElement('img');
        img.alt = image.title || image.filename;
        img.className = 'image-thumbnail';
        img.dataset.src = `${window.location.origin}/api/image/thumbnail/${image.image_id}`;
        img.src = placeholderSrc;
        img.onerror = () => { img.src = placeholderSrc; };
        lazyObserver.observe(img);
        item.appendChild(img);

        const info = document.createElement('div');
        info.className = 'image-info';

        const title = document.createElement('div');
        title.className = 'image-title';
        title.textContent = image.title || image.filename;
        info.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'image-meta';
        meta.innerHTML = `<span class="image-source">${getSourceLabel(image.source_type)}</span><span>${formatFileSize(image.file_size)}</span>`;
        info.appendChild(meta);

        const actions = document.createElement('div');
        actions.className = 'image-actions';
        actions.innerHTML = `
            <button class="btn btn-sm btn-outline" data-action="copy" data-image-id="${image.image_id}" title="复制链接"><i class="fas fa-link"></i></button>
            <button class="btn btn-sm btn-primary" data-action="download" data-image-id="${image.image_id}" title="下载"><i class="fas fa-download"></i></button>
            <button class="btn btn-sm btn-danger" data-action="delete" data-image-id="${image.image_id}" title="删除"><i class="fas fa-trash-alt"></i></button>
        `;
        info.appendChild(actions);

        item.appendChild(info);
        fragment.appendChild(item);
    });

    grid.appendChild(fragment);
}

function bindControls() {
    const categoryFilter = document.getElementById('category-filter');
    const searchInput = document.getElementById('search-input');
    const sortOption = document.getElementById('sort-option');
    const uploadTrigger = document.getElementById('upload-trigger');
    const refreshBtn = document.getElementById('refresh-btn');
    const batchBtn = document.getElementById('batch-mode-btn');

    if (categoryFilter) categoryFilter.addEventListener('change', () => filterImages());
    if (searchInput) searchInput.addEventListener('input', debounce(() => filterImages(), 200));
    if (sortOption) sortOption.addEventListener('change', () => sortImages());
    if (uploadTrigger) uploadTrigger.addEventListener('click', showUploadModal);
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadImages(currentPage));
    if (batchBtn) batchBtn.addEventListener('click', toggleBatchMode);
}

function bindGridEvents() {
    const grid = document.getElementById('image-grid');
    if (!grid) return;

    grid.addEventListener('click', (event) => {
        const actionBtn = event.target.closest('[data-action]');
        if (actionBtn) {
            const imageId = actionBtn.dataset.imageId;
            const action = actionBtn.dataset.action;
            if (!imageId) return;

            switch (action) {
                case 'copy':
                    copySingleImageUrl(imageId);
                    break;
                case 'download':
                    downloadSingleImage(imageId);
                    break;
                case 'delete':
                    deleteSingleImage(imageId);
                    break;
                default:
                    break;
            }
            return;
        }

        const thumbnail = event.target.closest('.image-thumbnail');
        if (thumbnail) {
            const parent = thumbnail.closest('.image-item');
            const imageId = parent?.dataset.imageId;
            if (imageId) {
                showImageDetail(imageId);
            }
        }
    });

    grid.addEventListener('change', (event) => {
        const checkbox = event.target;
        if (checkbox.classList.contains('batch-checkbox')) {
            toggleImageSelection(checkbox.dataset.imageId);
        }
    });
}

function bindBatchToolbarEvents() {
    const toolbar = document.getElementById('batch-toolbar');
    if (!toolbar) return;

    toolbar.addEventListener('click', (event) => {
        const action = event.target.closest('[data-action]')?.dataset.action;
        if (!action) return;
        event.preventDefault();

        switch (action) {
            case 'select-all':
                selectAll();
                break;
            case 'clear-selection':
                clearSelection();
                break;
            case 'batch-delete':
                batchDelete();
                break;
            case 'batch-download':
                batchDownload();
                break;
            default:
                break;
        }
    });

    const clearAllBtn = document.getElementById('clear-all-btn');
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', clearAllImages);
    }
}

function bindUploadEvents() {
    const uploadModal = document.getElementById('upload-modal');
    const closeBtn = document.getElementById('upload-close-btn');
    const dropZone = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');
    const fileTrigger = document.getElementById('file-trigger');
    const startBtn = document.getElementById('start-upload-btn');

    if (closeBtn) closeBtn.addEventListener('click', closeUploadModal);
    if (fileTrigger && fileInput) {
        fileTrigger.addEventListener('click', () => fileInput.click());
    }
    if (fileInput) {
        fileInput.addEventListener('change', handleFileSelect);
    }
    if (dropZone) {
        dropZone.addEventListener('dragover', handleDragOver);
        dropZone.addEventListener('dragleave', handleDragLeave);
        dropZone.addEventListener('drop', handleDrop);
    }
    if (startBtn) startBtn.addEventListener('click', startUpload);

    document.addEventListener('click', (event) => {
        if (event.target === uploadModal) {
            closeUploadModal();
        }
    });
}

function bindDetailModalEvents() {
    const detailModal = document.getElementById('image-detail-modal');
    const closeBtn = document.getElementById('image-detail-close-btn');
    const editToggle = document.getElementById('edit-toggle-btn');
    const saveBtn = document.getElementById('save-image-btn');
    const cancelBtn = document.getElementById('cancel-edit-btn');
    const downloadBtn = document.getElementById('download-image-btn');
    const copyBtn = document.getElementById('copy-image-btn');
    const deleteBtn = document.getElementById('delete-image-btn');

    if (closeBtn) closeBtn.addEventListener('click', closeImageDetailModal);
    if (editToggle) editToggle.addEventListener('click', toggleEditMode);
    if (saveBtn) saveBtn.addEventListener('click', saveImageInfo);
    if (cancelBtn) cancelBtn.addEventListener('click', cancelEdit);
    if (downloadBtn) downloadBtn.addEventListener('click', downloadImage);
    if (copyBtn) copyBtn.addEventListener('click', copyImageUrl);
    if (deleteBtn) deleteBtn.addEventListener('click', deleteImage);

    document.addEventListener('click', (event) => {
        if (event.target === detailModal) {
            closeImageDetailModal();
        }
    });
}

function bindKeyboardShortcuts() {
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            if (document.getElementById('upload-modal').style.display === 'flex') {
                closeUploadModal();
            }
            if (document.getElementById('image-detail-modal').style.display === 'flex') {
                closeImageDetailModal();
            }
        }

        if (event.ctrlKey && event.key === 'a' && batchMode) {
            event.preventDefault();
            selectAll();
        }

        if (event.key === 'Delete' && batchMode && selectedImages.size > 0) {
            batchDelete();
        }
    });
}

// 渲染分页控件
function renderPagination(pagination) {
    const paginationDiv = document.getElementById('pagination');

    if (pagination.total_pages <= 1) {
        paginationDiv.style.display = 'none';
        return;
    }

    paginationDiv.style.display = 'flex';
    paginationDiv.innerHTML = '';

    const fragment = document.createDocumentFragment();
    const createButton = (label, page, { disabled = false, active = false } = {}) => {
        const btn = document.createElement('button');
        btn.textContent = label;
        if (active) btn.classList.add('active');
        btn.disabled = disabled;
        btn.addEventListener('click', () => loadImages(page));
        return btn;
    };

    fragment.appendChild(createButton('上一页', pagination.current_page - 1, { disabled: !pagination.has_prev }));

    const startPage = Math.max(1, pagination.current_page - 2);
    const endPage = Math.min(pagination.total_pages, pagination.current_page + 2);

    if (startPage > 1) {
        fragment.appendChild(createButton('1', 1));
        if (startPage > 2) {
            fragment.appendChild(Object.assign(document.createElement('span'), { textContent: '...' }));
        }
    }

    for (let i = startPage; i <= endPage; i++) {
        fragment.appendChild(createButton(String(i), i, { active: i === pagination.current_page }));
    }

    if (endPage < pagination.total_pages) {
        if (endPage < pagination.total_pages - 1) {
            fragment.appendChild(Object.assign(document.createElement('span'), { textContent: '...' }));
        }
        fragment.appendChild(createButton(String(pagination.total_pages), pagination.total_pages));
    }

    fragment.appendChild(createButton('下一页', pagination.current_page + 1, { disabled: !pagination.has_next }));
    paginationDiv.appendChild(fragment);
}

// 筛选图片
function filterImages() {
    loadImages(1);
}

// 搜索图片
function searchImages(event) {
    if (event.key === 'Enter' || event.type === 'input') {
        loadImages(1);
    }
}

// 排序图片
function sortImages() {
    loadImages(1);
}

// 刷新图库
function refreshGallery() {
    loadImages(currentPage);
}

// 获取来源标签
function getSourceLabel(sourceType) {
    const labels = {
        'ai_generated': 'AI生成',
        'web_search': '网络搜索',
        'local_storage': '本地上传'
    };
    return labels[sourceType] || sourceType;
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// 显示错误信息
function showError(message) {
    // 这里可以集成现有的通知系统
    alert(message);
}

// 显示成功信息
function showSuccess(message) {
    // 这里可以集成现有的通知系统
    alert(message);
}

// 批量选择相关功能
function toggleBatchMode() {
    batchMode = !batchMode;
    const btn = document.getElementById('batch-mode-btn');
    const toolbar = document.getElementById('batch-toolbar');

    if (batchMode) {
        btn.textContent = '退出批量';
        btn.className = 'btn btn-danger';
        toolbar.style.display = 'block';
    } else {
        btn.textContent = '批量选择';
        btn.className = 'btn btn-secondary';
        toolbar.style.display = 'none';
        selectedImages.clear();
    }

    renderImageGrid();
    updateSelectedCount();
}

function toggleImageSelection(imageId) {
    if (selectedImages.has(imageId)) {
        selectedImages.delete(imageId);
    } else {
        selectedImages.add(imageId);
    }

    renderImageGrid();
    updateSelectedCount();
}

function selectAll() {
    filteredImages.forEach(image => selectedImages.add(image.image_id));
    renderImageGrid();
    updateSelectedCount();
}

function clearSelection() {
    selectedImages.clear();
    renderImageGrid();
    updateSelectedCount();
}

function updateSelectedCount() {
    document.getElementById('selected-count').textContent = selectedImages.size;
}

// 批量删除
async function batchDelete() {
    if (selectedImages.size === 0) {
        showError('请先选择要删除的图片');
        return;
    }

    if (!confirm(`确定要删除选中的 ${selectedImages.size} 张图片吗？此操作不可撤销。`)) {
        return;
    }

    try {
        const data = await apiClient.post('/api/image/gallery/batch-delete', {
            image_ids: Array.from(selectedImages)
        });

        if (data.success) {
            showSuccess(`成功删除 ${data.deleted_count} 张图片`);
            selectedImages.clear();
            refreshGallery();
            emit('gallery:updated', { action: 'batch-delete', count: data.deleted_count });
        } else {
            showError('批量删除失败: ' + data.message);
        }
    } catch (error) {
        console.error('Batch delete failed:', error);
        showError('批量删除失败');
    }
}

// 批量下载
async function batchDownload() {
    if (selectedImages.size === 0) {
        showError('请先选择要下载的图片');
        return;
    }

    try {
        const blob = await apiClient.post('/api/image/gallery/batch-download', {
            image_ids: Array.from(selectedImages)
        }, { responseType: 'blob' });

        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `images_${new Date().getTime()}.zip`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showSuccess(`成功下载 ${selectedImages.size} 张图片`);
    } catch (error) {
        console.error('Batch download failed:', error);
        showError('批量下载失败');
    }
}

// 清空当前用户图库
async function clearAllImages() {
    if (!confirm('警告：此操作将删除你图库中的所有图片且不可恢复，确定要继续吗？')) {
        return;
    }

    if (!confirm('请再次确认是否要清空你的整个图库？删除后无法恢复。')) {
        return;
    }

    try {
        const data = await apiClient.post('/api/image/gallery/clear-all');

        if (data.success) {
            showSuccess(data.message || `成功清空你的图库，删除了 ${data.deleted_count} 张图片`);

            selectedImages.clear();

            if (batchMode) {
                toggleBatchMode();
            }

            refreshGallery();
            emit('gallery:updated', { action: 'clear-all', count: data.deleted_count });
        } else {
            showError('清空图库失败: ' + data.message);
        }
    } catch (error) {
        console.error('Clear all images failed:', error);
        showError('清空图库失败');
    }
}

// 单张图片操作
async function copySingleImageUrl(imageId) {
    const url = `${window.location.origin}/api/image/view/${imageId}`;

    try {
        await navigator.clipboard.writeText(url);
        showSuccess('图片链接已复制到剪贴板');
    } catch (error) {
        // 降级方案
        const textArea = document.createElement('textarea');
        textArea.value = url;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showSuccess('图片链接已复制到剪贴板');
    }
}

async function downloadSingleImage(imageId) {
    try {
        const { data: blob, headers } = await apiClient.get(`/api/image/download/${imageId}`, null, { responseType: 'blob', returnResponse: true });

        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;

        const contentDisposition = headers.get('Content-Disposition');
        let filename = 'image';
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="(.+)"/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        console.error('Download failed:', error);
        showError('下载失败');
    }
}

async function deleteSingleImage(imageId) {
    if (!confirm('确定要删除这张图片吗？此操作不可撤销。')) {
        return;
    }

    try {
        const data = await apiClient.del(`/api/image/delete/${imageId}`);

        if (data.success) {
            showSuccess('图片删除成功');
            refreshGallery();
            emit('gallery:updated', { action: 'delete', count: 1 });
        } else {
            showError('删除失败: ' + data.message);
        }
    } catch (error) {
        console.error('Delete failed:', error);
        showError('删除失败');
    }
}

// 上传相关功能
function showUploadModal() {
    document.getElementById('upload-modal').style.display = 'flex';
}

function closeUploadModal() {
    document.getElementById('upload-modal').style.display = 'none';
    document.getElementById('upload-progress').style.display = 'none';
    document.getElementById('image-info-section').style.display = 'none';
    document.getElementById('progress-fill').style.width = '0%';
    document.getElementById('file-input').value = '';

    // 重置输入字段
    document.getElementById('image-title').value = '';
    document.getElementById('image-description').value = '';
    document.getElementById('image-tags').value = '';
    document.getElementById('image-category').value = 'business';

    // 清空选中的文件
    selectedFiles = [];
}

function handleDragOver(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

function handleDragLeave(event) {
    event.preventDefault();
    event.currentTarget.classList.remove('drag-over');
}

function handleDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.remove('drag-over');

    const files = event.dataTransfer.files;
    handleFiles(files);
}

function handleFileSelect(event) {
    const files = event.target.files;
    handleFiles(files);
}

let selectedFiles = [];

function handleFiles(files) {
    if (files.length === 0) return;

    // 验证文件类型
    const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif'];
    const validFiles = Array.from(files).filter(file => validTypes.includes(file.type));

    if (validFiles.length === 0) {
        showError('请选择有效的图片文件 (JPG, PNG, WebP, GIF)');
        return;
    }

    if (validFiles.length !== files.length) {
        showError(`已过滤掉 ${files.length - validFiles.length} 个无效文件`);
    }

    selectedFiles = validFiles;

    // 显示图片信息输入区域
    document.getElementById('image-info-section').style.display = 'block';

    // 如果只有一个文件，自动填入文件名作为标题
    if (validFiles.length === 1) {
        document.getElementById('image-title').value = validFiles[0].name.split('.')[0];
    } else {
        document.getElementById('image-title').placeholder = `批量上传 ${validFiles.length} 个文件`;
    }
}

async function startUpload() {
    if (selectedFiles.length === 0) {
        showError('请先选择文件');
        return;
    }

    // 获取用户输入的信息
    const title = document.getElementById('image-title').value.trim();
    const description = document.getElementById('image-description').value.trim();
    const tags = document.getElementById('image-tags').value.trim();
    const category = document.getElementById('image-category').value;

    // 隐藏信息输入区域，显示进度条
    document.getElementById('image-info-section').style.display = 'none';
    document.getElementById('upload-progress').style.display = 'block';

    let uploadedCount = 0;
    const totalFiles = selectedFiles.length;

    for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];

        try {
            document.getElementById('upload-status').textContent = `正在上传 ${file.name} (${i + 1}/${totalFiles})`;

            const formData = new FormData();
            formData.append('file', file);

            // 使用用户输入的信息，如果为空则使用默认值
            const fileTitle = title || file.name.split('.')[0];
            formData.append('title', fileTitle);
            formData.append('description', description);
            formData.append('tags', tags);
            formData.append('category', category);

            const data = await apiClient.post('/api/image/upload', formData);

            if (data.success) {
                uploadedCount++;
            } else {
                console.error(`Upload failed for ${file.name}:`, data.message);
            }

            // 更新进度条
            const progress = ((i + 1) / totalFiles) * 100;
            document.getElementById('progress-fill').style.width = `${progress}%`;

        } catch (error) {
            console.error(`Upload error for ${file.name}:`, error);
        }
    }

    document.getElementById('upload-status').textContent = `上传完成！成功上传 ${uploadedCount}/${totalFiles} 个文件`;

    if (uploadedCount > 0) {
        setTimeout(async () => {
            closeUploadModal();
            // New uploads (created_desc) should show immediately
            await loadImages(1);
            showSuccess(`成功上传 ${uploadedCount} 张图片`);
            emit('gallery:updated', { action: 'upload', count: uploadedCount });
        }, 800);
    }
}

// 图片详情相关功能
async function showImageDetail(imageId) {
    try {
        const data = await apiClient.get(`/api/image/detail/${imageId}`);

        if (data.success) {
            currentImageDetail = data.image;
            console.log('当前图片详情:', currentImageDetail);

            // 填充详情信息
            document.getElementById('image-detail-title').textContent = data.image.title || data.image.filename;
            document.getElementById('detail-image').src = `${window.location.origin}/api/image/view/${imageId}`;

            // 填充可编辑的图片信息
            document.getElementById('display-title').textContent = data.image.title || '未设置';
            document.getElementById('display-description').textContent = data.image.description || '未设置';
            document.getElementById('display-tags').textContent = data.image.tags || '未设置';
            document.getElementById('display-category').textContent = getCategoryLabel(data.image.category) || '未设置';

            // 填充文件信息
            document.getElementById('detail-filename').textContent = data.image.filename;
            document.getElementById('detail-size').textContent = formatFileSize(data.image.file_size);
            document.getElementById('detail-dimensions').textContent = `${data.image.width} × ${data.image.height}`;
            document.getElementById('detail-format').textContent = data.image.format.toUpperCase();
            document.getElementById('detail-source').textContent = getSourceLabel(data.image.source_type);
            document.getElementById('detail-created').textContent = new Date(data.image.created_at * 1000).toLocaleString();
            document.getElementById('detail-access-count').textContent = data.image.access_count || 0;

            // 重置编辑模式
            exitEditMode();

            // 显示模态框
            document.getElementById('image-detail-modal').style.display = 'flex';
        } else {
            showError('获取图片详情失败: ' + data.message);
        }
    } catch (error) {
        console.error('Failed to load image detail:', error);
        showError('获取图片详情失败');
    }
}

function closeImageDetailModal() {
    // 退出编辑模式
    exitEditMode();

    document.getElementById('image-detail-modal').style.display = 'none';
    currentImageDetail = null;
}

async function downloadImage() {
    if (!currentImageDetail) return;
    await downloadSingleImage(currentImageDetail.image_id);
}

async function copyImageUrl() {
    if (!currentImageDetail) return;

    const url = `${window.location.origin}/api/image/view/${currentImageDetail.image_id}`;

    try {
        await navigator.clipboard.writeText(url);
        showSuccess('图片链接已复制到剪贴板');
    } catch (error) {
        // 降级方案
        const textArea = document.createElement('textarea');
        textArea.value = url;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showSuccess('图片链接已复制到剪贴板');
    }
}

async function deleteImage() {
    if (!currentImageDetail) return;

    await deleteSingleImage(currentImageDetail.image_id);
    closeImageDetailModal();
}

// 图片信息编辑功能
function toggleEditMode() {
    const displayMode = document.getElementById('info-display-mode');
    const editMode = document.getElementById('info-edit-mode');
    const toggleBtn = document.getElementById('edit-toggle-btn');

    if (editMode.style.display === 'none') {
        // 进入编辑模式
        enterEditMode();
    } else {
        // 退出编辑模式
        exitEditMode();
    }
}

function enterEditMode() {
    if (!currentImageDetail) return;

    const displayMode = document.getElementById('info-display-mode');
    const editMode = document.getElementById('info-edit-mode');
    const toggleBtn = document.getElementById('edit-toggle-btn');

    // 填充编辑表单
    document.getElementById('edit-title').value = currentImageDetail.title || '';
    document.getElementById('edit-description').value = currentImageDetail.description || '';
    document.getElementById('edit-tags').value = currentImageDetail.tags || '';
    document.getElementById('edit-category').value = currentImageDetail.category || '';

    // 切换显示模式
    displayMode.style.display = 'none';
    editMode.style.display = 'block';
    toggleBtn.innerHTML = '<i class="fas fa-eye"></i> 查看';
}

function exitEditMode() {
    const displayMode = document.getElementById('info-display-mode');
    const editMode = document.getElementById('info-edit-mode');
    const toggleBtn = document.getElementById('edit-toggle-btn');

    displayMode.style.display = 'block';
    editMode.style.display = 'none';
    toggleBtn.innerHTML = '<i class="fas fa-edit"></i> 编辑';
}

function cancelEdit() {
    exitEditMode();
}

async function saveImageInfo() {
    if (!currentImageDetail) return;

    const title = document.getElementById('edit-title').value.trim();
    const description = document.getElementById('edit-description').value.trim();
    const tags = document.getElementById('edit-tags').value.trim();
    const category = document.getElementById('edit-category').value;

    try {
        const result = await apiClient.put(`/api/image/${currentImageDetail.image_id}/update`, {
            title,
            description,
            tags,
            category
        });

        if (result.success) {
            currentImageDetail.title = title;
            currentImageDetail.description = description;
            currentImageDetail.tags = tags;
            currentImageDetail.category = category;

            document.getElementById('display-title').textContent = title || '未设置';
            document.getElementById('display-description').textContent = description || '未设置';
            document.getElementById('display-tags').textContent = tags || '未设置';
            document.getElementById('display-category').textContent = getCategoryLabel(category) || '未设置';
            document.getElementById('image-detail-title').textContent = title || currentImageDetail.filename;

            exitEditMode();
            loadImages();
            showSuccess('图片信息已更新');
            emit('gallery:updated', { action: 'update', id: currentImageDetail.image_id });
        } else {
            showError('更新失败: ' + (result.message || '未知错误'));
        }
    } catch (error) {
        console.error('Failed to update image info:', error);
        if (error.message) {
            showError('更新失败: ' + error.message);
        } else {
            showError('更新失败，请重试');
        }
    }
}

// 获取分类标签
function getCategoryLabel(category) {
    const categoryLabels = {
        'ai_generated': 'AI生成',
        'web_search': '网络搜索',
        'local_storage': '本地上传'
    };
    return categoryLabels[category] || category;
}
