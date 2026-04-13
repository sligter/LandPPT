// Global Master Templates Management JavaScript

async function updateTagFilter() {
    const tagFilter = document.getElementById('tagFilter');

    if (!tagFilter) {
        console.warn('Tag filter element not found');
        return;
    }

    try {
        // Get all templates to extract tags (without pagination)
        const response = await fetch('/api/global-master-templates/?active_only=true&page_size=1000');
        if (response.ok) {
            const data = await response.json();
            const allTemplates = data.templates || [];

            const allTags = new Set();
            allTemplates.forEach(template => {
                if (template.tags && Array.isArray(template.tags)) {
                    template.tags.forEach(tag => {
                        if (tag && tag.trim()) {
                            allTags.add(tag.trim());
                        }
                    });
                }
            });

            // 保存当前选中的值
            const currentValue = tagFilter.value;

            // Clear existing options except "所有标签"
            tagFilter.innerHTML = '<option value="">所有标签</option>';

            // Add tag options
            const sortedTags = Array.from(allTags).sort();
            sortedTags.forEach(tag => {
                const option = document.createElement('option');
                option.value = tag;
                option.textContent = tag;
                tagFilter.appendChild(option);
            });

            // 恢复之前选中的值(如果该标签仍然存在)
            if (currentValue && sortedTags.includes(currentValue)) {
                tagFilter.value = currentValue;
            }

            console.log(`Loaded ${sortedTags.length} tags for filter`);
        } else {
            console.warn('Failed to fetch templates for tag filter:', response.status);
        }
    } catch (error) {
        console.error('Failed to load tags for filter:', error);
        // 确保至少有默认选项
        tagFilter.innerHTML = '<option value="">所有标签</option>';
    }
}

// filterTemplates function removed - now using server-side pagination

function showLoading(show) {
    document.getElementById('loadingIndicator').style.display = show ? 'block' : 'none';
    document.getElementById('templatesGrid').style.display = show ? 'none' : 'grid';
}

function openTemplateModal(templateId = null) {
    editingTemplateId = templateId;
    const modal = document.getElementById('templateModal');
    const title = document.getElementById('modalTitle');
    const form = document.getElementById('templateForm');
    
    if (templateId) {
        title.textContent = '编辑母版';
        loadTemplateForEdit(templateId);
    } else {
        title.textContent = '新建母版';
        form.reset();
    }
    
    modal.style.display = 'flex';
}

function closeTemplateModal() {
    document.getElementById('templateModal').style.display = 'none';
    editingTemplateId = null;
}

function openAIGenerationModal() {
    document.getElementById('aiGenerationModal').style.display = 'flex';
    document.getElementById('aiGenerationForm').reset();
}

function closeAIGenerationModal() {
    document.getElementById('aiGenerationModal').style.display = 'none';

    // 重置模态框状态
    document.getElementById('aiFormContainer').style.display = 'block';
    document.getElementById('aiGenerationProgress').style.display = 'none';
    document.getElementById('aiGenerationComplete').style.display = 'none';

    // 重置表单
    document.getElementById('aiGenerationForm').reset();
}

function closePreviewModal() {
    document.getElementById('previewModal').style.display = 'none';
}

async function loadTemplateForEdit(templateId) {
    try {
        const response = await fetch(`/api/global-master-templates/${templateId}`);
        if (!response.ok) {
            throw new Error('Failed to load template');
        }
        
        const template = await response.json();
        
        document.getElementById('templateName').value = template.template_name;
        document.getElementById('templateDescription').value = template.description;
        document.getElementById('templateTags').value = template.tags.join(', ');
        document.getElementById('isDefault').checked = template.is_default;
        document.getElementById('htmlTemplate').value = template.html_template;
    } catch (error) {
        console.error('Error loading template:', error);
        alert('加载模板失败: ' + error.message);
    }
}

async function handleTemplateSubmit(event) {
    event.preventDefault();
    
    const formData = new FormData(event.target);
    const templateData = {
        template_name: formData.get('template_name'),
        description: formData.get('description'),
        html_template: formData.get('html_template'),
        tags: formData.get('tags').split(',').map(tag => tag.trim()).filter(tag => tag),
        is_default: formData.get('is_default') === 'on'
    };
    
    try {
        let response;
        if (editingTemplateId) {
            // Update existing template
            response = await fetch(`/api/global-master-templates/${editingTemplateId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(templateData)
            });
        } else {
            // Create new template
            response = await fetch('/api/global-master-templates/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(templateData)
            });
        }
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to save template');
        }
        
        closeTemplateModal();
        loadTemplates(currentPage);
        alert(editingTemplateId ? '模板更新成功！' : '模板创建成功！');
    } catch (error) {
        console.error('Error saving template:', error);
        alert('保存模板失败: ' + error.message);
    }
}

async function handleAIGeneration(event) {
    event.preventDefault();

    const formData = new FormData(event.target);
    const requestData = {
        prompt: formData.get('prompt'),
        template_name: formData.get('template_name'),
        description: formData.get('description'),
        tags: formData.get('tags').split(',').map(tag => tag.trim()).filter(tag => tag),
        generation_mode: formData.get('generation_mode') || 'text_only'
    };

    // 如果有上传的图片，添加图片数据
    if (uploadedImageData && requestData.generation_mode !== 'text_only') {
        requestData.reference_image = {
            filename: uploadedImageData.filename,
            data: uploadedImageData.data,
            size: uploadedImageData.size,
            type: uploadedImageData.type
        };
    }

    try {
        // 切换到进度显示界面
        showAIGenerationProgress();

        // 开始生成
        await startGeneration(requestData);

    } catch (error) {
        console.error('Error generating template:', error);
        showAIGenerationError(error.message);
    }
}

function showAIGenerationProgress() {
    // 隐藏表单，显示进度
    document.getElementById('aiFormContainer').style.display = 'none';
    document.getElementById('aiGenerationProgress').style.display = 'block';
    document.getElementById('aiGenerationComplete').style.display = 'none';

    // 重置进度状态
    document.getElementById('statusText').textContent = '正在分析需求...';
}

function showAIGenerationComplete() {
    // 隐藏进度，显示完成
    document.getElementById('aiGenerationProgress').style.display = 'none';
    document.getElementById('aiGenerationComplete').style.display = 'block';
}

function showAIGenerationError(errorMessage) {
    console.error('AI generation error:', errorMessage);

    // 显示错误并返回表单
    document.getElementById('aiGenerationProgress').style.display = 'none';
    document.getElementById('aiGenerationComplete').style.display = 'none';
    document.getElementById('aiFormContainer').style.display = 'block';

    // 重置状态
    document.getElementById('statusText').textContent = '正在分析需求...';

    alert('AI生成模板失败: ' + errorMessage);
}

async function startGeneration(requestData) {
    try {
        // 更新状态
        updateGenerationStatus('正在连接AI服务...');

        const response = await fetch('/api/global-master-templates/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to generate template');
        }

        // 更新状态
        updateGenerationStatus('AI正在分析需求并生成模板...');

        // 处理响应
        const result = await response.json();
        console.log('Generation result:', result); // 调试信息

        // 检查响应格式：可能是包装格式 {success: true, data: {...}} 或直接的模板对象
        let templateData = null;

        if (result.success && result.data) {
            // 包装格式
            templateData = result.data;
        } else if (result.id && result.template_name) {
            // 直接的模板对象格式（已保存的模板）
            templateData = result;
        } else if (result.html_template) {
            // 生成的模板数据格式
            templateData = result;
        }

        if (templateData) {
            // 更新状态
            updateGenerationStatus('正在处理生成结果...');

            // 处理生成完成的数据
            await handleGenerationComplete(templateData);
        } else {
            console.error('Generation failed - unrecognized response format:', result); // 调试信息
            throw new Error(result.message || result.detail || 'Generation failed');
        }

        // 生成完成
        updateGenerationStatus('模板生成完成！');
        showAIGenerationComplete();

    } catch (error) {
        console.error('Generation error:', error);
        throw error;
    }
}



function showTemplatePreview(htmlTemplate) {
    const iframe = document.getElementById('generatedTemplateIframe');
    if (iframe) {
        // 创建一个blob URL来显示HTML内容
        const blob = new Blob([htmlTemplate], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        iframe.src = url;

        // 清理之前的URL
        iframe.onload = () => {
            setTimeout(() => {
                URL.revokeObjectURL(url);
            }, 1000);
        };
    }
}

async function saveGeneratedTemplate() {
    if (!window.generatedTemplateData) {
        alert('没有可保存的模板数据');
        return;
    }

    try {
        const response = await fetch('/api/global-master-templates/save-generated', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(window.generatedTemplateData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to save template');
        }

        const result = await response.json();
        console.log('Template saved successfully:', result);

        // 关闭模态框并刷新列表
        closeAIGenerationModal();
        loadTemplates(1);

        alert('模板保存成功！');

        // 清理临时数据
        delete window.generatedTemplateData;

    } catch (error) {
        console.error('Error saving template:', error);
        alert('保存模板失败: ' + error.message);
    }
}

async function adjustTemplate() {
    const adjustmentInput = document.getElementById('adjustmentInput');
    const adjustmentRequest = adjustmentInput.value.trim();

    if (!adjustmentRequest) {
        alert('请输入调整需求');
        return;
    }

    if (!window.generatedTemplateData) {
        alert('没有可调整的模板数据');
        return;
    }

    try {
        // 显示调整进度
        document.getElementById('adjustmentProgress').style.display = 'block';
        document.getElementById('adjustTemplateBtn').disabled = true;

        const requestData = {
            html_template: window.generatedTemplateData.html_template,
            adjustment_request: adjustmentRequest,
            template_name: window.generatedTemplateData.template_name
        };

        const response = await fetch('/api/global-master-templates/adjust-template', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            },
            body: JSON.stringify(requestData)
        });

        if (!response.ok) {
            throw new Error('Failed to adjust template');
        }

        // 处理流式响应
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (line.trim() === '') continue;

                try {
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6));

                        if (data.type === 'complete' && data.html_template) {
                            // 更新模板数据
                            window.generatedTemplateData.html_template = data.html_template;

                            // 更新预览
                            showTemplatePreview(data.html_template);

                            // 清空输入框
                            adjustmentInput.value = '';

                            alert('模板调整完成！');
                        } else if (data.type === 'error') {
                            // 检查是否是网络错误（502 Bad Gateway等）
                            let errorMessage = data.message;
                            if (errorMessage.includes('502') || errorMessage.includes('Bad gateway')) {
                                errorMessage = 'AI服务暂时不可用，请稍后重试';
                            } else if (errorMessage.includes('504') || errorMessage.includes('Gateway Timeout')) {
                                errorMessage = 'AI服务响应超时，请稍后重试';
                            } else if (errorMessage.includes('<!DOCTYPE html>')) {
                                errorMessage = 'AI服务连接失败，请检查网络连接或稍后重试';
                            }
                            throw new Error(errorMessage);
                        }
                    }
                } catch (e) {
                    console.warn('Failed to parse adjustment stream data:', line, e);
                }
            }
        }

    } catch (error) {
        console.error('Error adjusting template:', error);
        alert('调整模板失败: ' + error.message);
    } finally {
        // 隐藏调整进度
        document.getElementById('adjustmentProgress').style.display = 'none';
        document.getElementById('adjustTemplateBtn').disabled = false;
    }
}

async function handleGenerationComplete(data) {
    console.log('Handling generation complete with data:', data);

    // 处理不同格式的响应数据
    if (data.html_template) {
        // 生成的模板数据格式
        window.generatedTemplateData = {
            html_template: data.html_template,
            template_name: data.template_name,
            description: data.description,
            tags: data.tags,
            llm_response: data.llm_response  // 保存LLM完整响应
        };

        // 显示预览
        showTemplatePreview(data.html_template);

        // 如果有LLM响应，显示LLM响应数据
        if (data.llm_response) {
            displayLLMResponse(data.llm_response);
        }
    } else if (data.id && data.template_name) {
        // 已保存的模板对象格式
        console.log('Template already saved with ID:', data.id);

        // 尝试获取模板的HTML内容来显示预览
        try {
            const response = await fetch(`/api/global-master-templates/${data.id}`);
            if (response.ok) {
                const templateData = await response.json();
                console.log('Fetched template data:', templateData);

                // 检查不同可能的HTML内容字段名
                const htmlContent = templateData.html_content || templateData.content || templateData.html_template;

                if (htmlContent) {
                    window.generatedTemplateData = {
                        html_template: htmlContent,
                        template_name: templateData.name || templateData.template_name,
                        description: templateData.description,
                        tags: templateData.tags,
                        id: templateData.id
                    };

                    // 显示预览
                    showTemplatePreview(htmlContent);
                } else {
                    console.warn('No HTML content found in template data');
                    // 显示占位符预览
                    showTemplatePreview('<div style="padding: 50px; text-align: center; color: #666;">模板预览不可用</div>');
                }

                // 显示成功消息
                console.log('Template generated and saved successfully!');
            } else {
                console.warn('Failed to fetch template details for preview');
            }
        } catch (error) {
            console.error('Error fetching template details:', error);
        }
    } else {
        console.warn('Unrecognized data format:', data);
    }
}

// 保留原有的流式处理函数以备后用
async function handleStreamData(data) {
    switch (data.type) {
        case 'status':
            updateGenerationStatus(data.message);
            break;

        case 'thinking':
            // 显示AI思考过程
            appendToStream(data.content);
            break;

        case 'progress':
            updateGenerationStatus(data.message);
            if (data.content) {
                appendToStream(data.content);
            }
            break;

        case 'complete':
            updateGenerationStatus('模板生成完成！');
            appendToStream('\n\n✅ 模板已成功生成！');

            // 存储生成的模板数据
            if (data.html_template) {
                window.generatedTemplateData = {
                    html_template: data.html_template,
                    template_name: data.template_name,
                    description: data.description,
                    tags: data.tags,
                    llm_response: data.llm_response  // 保存LLM完整响应
                };

                // 显示预览
                showTemplatePreview(data.html_template);

                // 如果有LLM响应，显示LLM响应数据
                if (data.llm_response) {
                    displayLLMResponse(data.llm_response);
                }
            }
            break;

        case 'error':
            // 检查是否是网络错误
            let errorMessage = data.message;
            if (errorMessage.includes('502') || errorMessage.includes('Bad gateway')) {
                errorMessage = 'AI服务暂时不可用，请稍后重试';
            } else if (errorMessage.includes('504') || errorMessage.includes('Gateway Timeout')) {
                errorMessage = 'AI服务响应超时，请稍后重试';
            } else if (errorMessage.includes('<!DOCTYPE html>')) {
                errorMessage = 'AI服务连接失败，请检查网络连接或稍后重试';
            }
            throw new Error(errorMessage);
    }
}

function updateGenerationStatus(message) {
    document.getElementById('statusText').textContent = message;
}

function appendToStream(content) {
    const responseStream = document.getElementById('aiResponseStream');

    // 如果元素不存在，直接返回（非流式模式下不需要显示）
    if (!responseStream) {
        return;
    }

    // 移除之前的光标
    const existingCursor = responseStream.querySelector('.typing-cursor');
    if (existingCursor) {
        existingCursor.remove();
    }

    // 添加新内容
    const contentSpan = document.createElement('span');
    contentSpan.textContent = content;
    responseStream.appendChild(contentSpan);

    // 添加新的光标
    const cursor = document.createElement('span');
    cursor.className = 'typing-cursor';
    responseStream.appendChild(cursor);

    // 滚动到底部
    responseStream.scrollTop = responseStream.scrollHeight;
}

function previewTemplate() {
    const htmlContent = document.getElementById('htmlTemplate').value;
    if (!htmlContent.trim()) {
        alert('请先输入HTML模板代码');
        return;
    }
    
    showPreview(htmlContent);
}

// previewTemplateById 和 showPreview 函数已移至HTML文件中

// 这些函数已移至HTML文件中，以便onclick事件可以访问
// editTemplate, duplicateTemplate, setDefaultTemplate, deleteTemplate

// 导入模板功能
async function handleTemplateImport(event) {
    const file = event.target.files[0];
    if (!file) {
        return;
    }

    try {
        const fileContent = await readFileContent(file);
        let templateData;

        if (file.name.endsWith('.json')) {
            // JSON格式导入
            templateData = JSON.parse(fileContent);

            // 验证必要字段
            if (!templateData.template_name || !templateData.html_template) {
                throw new Error('JSON文件格式不正确，缺少必要字段 template_name 或 html_template');
            }
        } else if (file.name.endsWith('.html')) {
            // HTML文件导入
            const fileName = file.name.replace('.html', '');
            templateData = {
                template_name: fileName,
                description: `从文件 ${file.name} 导入`,
                html_template: fileContent,
                tags: ['导入'],
                is_default: false
            };
        } else {
            throw new Error('不支持的文件格式，请选择 .html 或 .json 文件');
        }

        // 确保标签是数组格式
        if (typeof templateData.tags === 'string') {
            templateData.tags = templateData.tags.split(',').map(tag => tag.trim()).filter(tag => tag);
        }
        if (!Array.isArray(templateData.tags)) {
            templateData.tags = [];
        }

        // 创建模板
        const response = await fetch('/api/global-master-templates/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(templateData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to import template');
        }

        // 清空文件输入
        event.target.value = '';

        // 重新加载模板列表
        loadTemplates(1); // 回到第一页查看新导入的模板
        alert('模板导入成功！');

    } catch (error) {
        console.error('Error importing template:', error);
        alert('导入模板失败: ' + error.message);
        // 清空文件输入
        event.target.value = '';
    }
}

// 读取文件内容
function readFileContent(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.onerror = (e) => reject(new Error('文件读取失败'));
        reader.readAsText(file, 'UTF-8');
    });
}

// 导出模板功能已移至HTML文件中，以便onclick事件可以访问

// ==================== 图片上传功能 ====================

let uploadedImageData = null; // 存储上传的图片数据

// 初始化图片上传功能
function initImageUpload() {
    // 延迟初始化，确保DOM元素存在
    setTimeout(() => {
        const generationModeRadios = document.querySelectorAll('input[name="generation_mode"]');
        const imageUploadArea = document.getElementById('imageUploadArea');
        const uploadDropzone = document.getElementById('uploadDropzone');
        const selectImageBtn = document.getElementById('selectImageBtn');
        const imageFileInput = document.getElementById('imageFileInput');
        const removeImageBtn = document.getElementById('removeImageBtn');

        if (generationModeRadios.length === 0 || !imageUploadArea) {
            return;
        }

        // 监听生成模式变化
        generationModeRadios.forEach(radio => {
            radio.addEventListener('change', function() {
                if (this.value === 'text_only') {
                    imageUploadArea.style.display = 'none';
                    clearUploadedImage();
                } else {
                    imageUploadArea.style.display = 'block';
                }
            });
        });

        // 只有在元素存在时才添加事件监听器
        if (uploadDropzone && selectImageBtn && imageFileInput && removeImageBtn) {
            // 拖拽上传
            uploadDropzone.addEventListener('dragover', handleDragOver);
            uploadDropzone.addEventListener('dragleave', handleDragLeave);
            uploadDropzone.addEventListener('drop', handleDrop);

            // 点击上传
            selectImageBtn.addEventListener('click', (e) => {
                e.stopPropagation(); // 阻止事件冒泡
                imageFileInput.click();
            });
            uploadDropzone.addEventListener('click', (e) => {
                // 只有点击空白区域时才触发，避免与按钮冲突
                if (e.target === uploadDropzone || e.target.closest('.upload-content')) {
                    if (e.target !== selectImageBtn && !selectImageBtn.contains(e.target)) {
                        imageFileInput.click();
                    }
                }
            });
            imageFileInput.addEventListener('change', handleFileSelect);

            // 移除图片
            removeImageBtn.addEventListener('click', clearUploadedImage);
        }
    }, 100);
}

// 处理拖拽悬停
function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.add('dragover');
}

// 处理拖拽离开
function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove('dragover');
}

// 处理拖拽放下
function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove('dragover');

    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleImageFile(files[0]);
    }
}

// 处理文件选择
function handleFileSelect(e) {
    const files = e.target.files;
    if (files.length > 0) {
        handleImageFile(files[0]);
    }
}

// 处理图片文件
function handleImageFile(file) {
    // 验证文件类型
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
    if (!allowedTypes.includes(file.type)) {
        alert('请选择支持的图片格式：JPG、PNG、WebP');
        return;
    }

    // 验证文件大小 (10MB)
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
        alert('图片文件大小不能超过 10MB');
        return;
    }

    // 读取并预览图片
    const reader = new FileReader();
    reader.onload = function(e) {
        const base64Data = e.target.result;
        uploadedImageData = {
            filename: file.name,
            size: file.size,
            type: file.type,
            data: base64Data
        };
        showImagePreview(uploadedImageData);
    };
    reader.readAsDataURL(file);
}

// 显示图片预览
function showImagePreview(imageData) {
    const uploadDropzone = document.getElementById('uploadDropzone');
    const previewContainer = document.getElementById('imagePreviewContainer');
    const imagePreview = document.getElementById('imagePreview');
    const imageFilename = document.getElementById('imageFilename');
    const imageSize = document.getElementById('imageSize');

    // 隐藏上传区域，显示预览
    uploadDropzone.style.display = 'none';
    previewContainer.style.display = 'block';

    // 设置预览内容
    imagePreview.src = imageData.data;
    imageFilename.textContent = imageData.filename;
    imageSize.textContent = formatFileSize(imageData.size);
}

// 清除上传的图片
function clearUploadedImage() {
    uploadedImageData = null;

    const uploadDropzone = document.getElementById('uploadDropzone');
    const previewContainer = document.getElementById('imagePreviewContainer');
    const imageFileInput = document.getElementById('imageFileInput');

    // 显示上传区域，隐藏预览
    uploadDropzone.style.display = 'block';
    previewContainer.style.display = 'none';

    // 清空文件输入
    imageFileInput.value = '';
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// LLM响应处理函数
function displayLLMResponse(rawResponse) {
    // 存储原始响应
    const rawResponseCode = document.getElementById('rawResponseCode');
    if (rawResponseCode && rawResponse) {
        rawResponseCode.textContent = rawResponse;
    } else if (rawResponseCode) {
        rawResponseCode.textContent = '暂无AI响应数据（模板已保存）';
    }
}

function formatLLMResponse(rawResponse) {
    // 基本的Markdown格式化
    let formatted = rawResponse;

    // 处理代码块
    formatted = formatted.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang || 'text'}">${escapeHtml(code.trim())}</code></pre>`;
    });

    // 处理行内代码
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 处理标题
    formatted = formatted.replace(/^### (.*$)/gm, '<h3>$1</h3>');
    formatted = formatted.replace(/^## (.*$)/gm, '<h2>$1</h2>');
    formatted = formatted.replace(/^# (.*$)/gm, '<h1>$1</h1>');

    // 处理粗体
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // 处理列表
    formatted = formatted.replace(/^\* (.*$)/gm, '<li>$1</li>');
    formatted = formatted.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');

    // 处理数字列表
    formatted = formatted.replace(/^\d+\. (.*$)/gm, '<li>$1</li>');

    // 处理段落
    formatted = formatted.replace(/\n\n/g, '</p><p>');
    formatted = '<div class="formatted-response-content"><p>' + formatted + '</p></div>';

    // 清理空段落
    formatted = formatted.replace(/<p><\/p>/g, '');
    formatted = formatted.replace(/<p>\s*<\/p>/g, '');

    return formatted;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
