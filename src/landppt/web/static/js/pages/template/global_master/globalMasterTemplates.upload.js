export function createGlobalMasterTemplatesUpload({ state, apiClient, formatBytes, loadTemplates }) {
function initImageUpload() {
    const imageUploadArea = document.getElementById('imageUploadArea');
    const pptxUploadArea = document.getElementById('pptxUploadArea');
    const dropzone = document.getElementById('uploadDropzone');
    const fileInput = document.getElementById('imageFileInput');
    const selectBtn = document.getElementById('selectImageBtn');
    const removeBtn = document.getElementById('removeImageBtn');
    const pptxFileInput = document.getElementById('pptxFileInput');
    const selectPptxBtn = document.getElementById('selectPptxBtn');
    const removePptxBtn = document.getElementById('removePptxBtn');
    const modeRadios = document.querySelectorAll('input[name="generation_mode"]');

    const updateReferenceUploadArea = (modeValue) => {
        const mode = String(modeValue || 'text_only');
        const showImage = mode === 'reference_style' || mode === 'exact_replica';
        const showPptx = mode === 'pptx_extract';
        if (imageUploadArea) {
            imageUploadArea.style.display = showImage ? 'block' : 'none';
        }
        if (pptxUploadArea) {
            pptxUploadArea.style.display = showPptx ? 'block' : 'none';
        }
    };

    modeRadios.forEach((radio) => {
        radio.addEventListener('change', () => {
            updateReferenceUploadArea(radio.value);
        });
    });
    updateReferenceUploadArea(document.querySelector('input[name="generation_mode"]:checked')?.value || 'text_only');

    if (selectBtn && fileInput) {
        selectBtn.addEventListener('click', () => fileInput.click());
    }
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files?.[0];
            if (file) handleImageFile(file);
        });
    }
    if (removeBtn) {
        removeBtn.addEventListener('click', clearUploadedImage);
    }
    if (selectPptxBtn && pptxFileInput) {
        selectPptxBtn.addEventListener('click', () => pptxFileInput.click());
    }
    if (pptxFileInput) {
        pptxFileInput.addEventListener('change', (e) => {
            const file = e.target.files?.[0];
            if (file) handlePptxFile(file);
        });
    }
    if (removePptxBtn) {
        removePptxBtn.addEventListener('click', clearUploadedPptx);
    }
    if (dropzone) {
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });
        dropzone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
        });
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            const file = e.dataTransfer?.files?.[0];
            if (file) handleImageFile(file);
        });
    }
}

function handleImageFile(file) {
    if (!file.type.startsWith('image/')) {
        alert('请上传图片文件');
        return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
        state.uploadedImage = {
            filename: file.name,
            size: file.size,
            type: file.type,
            data: e.target.result,
        };
        showImagePreview();
    };
    reader.readAsDataURL(file);
}

function handlePptxFile(file) {
    const lowerName = String(file?.name || '').toLowerCase();
    const isPptxMime = file?.type === 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
    if (!lowerName.endsWith('.pptx') && !isPptxMime) {
        alert('请上传 .pptx 文件');
        return;
    }
    if (file.size > 50 * 1024 * 1024) {
        alert('PPTX 文件过大，请控制在 50MB 以内');
        return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
        state.uploadedPptx = {
            filename: file.name,
            size: file.size,
            type: file.type || 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            data: e.target.result,
        };
        showPptxPreview();
    };
    reader.onerror = () => alert('读取 PPTX 文件失败');
    reader.readAsDataURL(file);
}

function showImagePreview() {
    const previewContainer = document.getElementById('imagePreviewContainer');
    const preview = document.getElementById('imagePreview');
    const filename = document.getElementById('imageFilename');
    const size = document.getElementById('imageSize');

    if (!state.uploadedImage || !previewContainer || !preview) return;

    preview.src = state.uploadedImage.data;
    previewContainer.style.display = 'block';
    if (filename) filename.textContent = state.uploadedImage.filename;
    if (size) size.textContent = formatBytes(state.uploadedImage.size);
}

function showPptxPreview() {
    const previewContainer = document.getElementById('pptxPreviewContainer');
    const filename = document.getElementById('pptxFilename');
    const size = document.getElementById('pptxSize');
    const hint = document.getElementById('pptxExtractHint');

    if (!state.uploadedPptx || !previewContainer) return;

    previewContainer.style.display = 'block';
    if (filename) filename.textContent = state.uploadedPptx.filename;
    if (size) size.textContent = formatBytes(state.uploadedPptx.size);
    if (hint) hint.textContent = '生成时将自动提取 PPTX 的版式、字体、配色与布局特征';
}

function clearUploadedImage() {
    state.uploadedImage = null;
    const previewContainer = document.getElementById('imagePreviewContainer');
    if (previewContainer) previewContainer.style.display = 'none';
    const fileInput = document.getElementById('imageFileInput');
    if (fileInput) fileInput.value = '';
}

function clearUploadedPptx() {
    state.uploadedPptx = null;
    const previewContainer = document.getElementById('pptxPreviewContainer');
    if (previewContainer) previewContainer.style.display = 'none';
    const fileInput = document.getElementById('pptxFileInput');
    if (fileInput) fileInput.value = '';
}

async function handleTemplateImport(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
        const content = await readFileContent(file);
        let templateData;
        if (file.name.endsWith('.json')) {
            templateData = JSON.parse(content);
        } else if (file.name.endsWith('.html')) {
            templateData = {
                template_name: file.name.replace('.html', ''),
                description: `从文件 ${file.name} 导入`,
                html_template: content,
                tags: ['导入'],
                is_default: false,
            };
        } else {
            throw new Error('请选择 .json 或 .html 文件');
        }

        if (!templateData.template_name || !templateData.html_template) {
            throw new Error('文件缺少模板名称或HTML内容');
        }

        if (typeof templateData.tags === 'string') {
            templateData.tags = templateData.tags.split(',').map((t) => t.trim()).filter(Boolean);
        }
        if (!Array.isArray(templateData.tags)) {
            templateData.tags = [];
        }

        await apiClient.post('/api/global-master-templates/', templateData);
        event.target.value = '';
        loadTemplates(1);
        alert('模板导入成功');
    } catch (error) {
        console.error('导入失败', error);
        alert('导入模板失败: ' + error.message);
        event.target.value = '';
    }
}

function readFileContent(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.onerror = reject;
        reader.readAsText(file);
    });
}

return {
    initImageUpload,
    clearUploadedImage,
    clearUploadedPptx,
    handleTemplateImport,
};
}
