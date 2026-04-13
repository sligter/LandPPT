// 自由对话（仅当前页）
let isNativeChatSending = false;
const nativeChatHistory = {}; // key: slideIndex, value: [{role, content, timestamp}]
let isNativeImageUploading = false;
const nativeUploadedImagesBySlide = {}; // key: slideIndex, value: [{id,name,size,url}]

function setNativeAssistantMessageText(messageDiv, content) {
    return window.projectSlidesEditorPretext.setAssistantMessageText(messageDiv, content);
}

function refreshNativeAssistantMessageLayout(messageDiv) {
    return window.projectSlidesEditorPretext.refreshAssistantMessageLayout(messageDiv);
}

function destroyNativeAssistantMessageRender(messageDiv) {
    window.projectSlidesEditorPretext.destroyAssistantMessageRender(messageDiv);
}

function openNativeChatDialog() {
    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const dialog = document.getElementById('aiNativeChatDialog');
    if (!dialog) return;
    if (typeof dialog.showModal !== 'function') {
        alert('当前浏览器不支持自由对话框（<dialog>）。');
        return;
    }

    renderNativeChatMessages();
    renderNativeUploadedImages();
    updateNativeUploadButtonState();
    dialog.showModal();

    setTimeout(() => {
        const input = document.getElementById('aiNativeInputBox');
        if (input) input.focus();
    }, 50);
}

function closeNativeChatDialog() {
    const dialog = document.getElementById('aiNativeChatDialog');
    if (dialog && dialog.open) {
        dialog.close();
    }
}

function renderNativeChatMessages() {
    const container = document.getElementById('aiNativeChatMessages');
    if (!container) return;
    container.querySelectorAll('.ai-message.assistant').forEach(destroyNativeAssistantMessageRender);
    container.innerHTML = '';

    const systemDiv = document.createElement('div');
    systemDiv.className = 'ai-message system';
    systemDiv.innerHTML = `
        <div style="text-align: center; padding: var(--spacing-sm);">
            <div style="font-size: 1.8rem; margin-bottom: var(--spacing-sm); color: var(--text-secondary);">
                <i class="fas fa-comments"></i>
            </div>
            <div style="font-weight: 700; margin-bottom: var(--spacing-xs); color: var(--text-primary);">
                自由对话（仅当前页）
            </div>
            <div style="font-size: 0.8125rem; line-height: 1.5; color: var(--text-muted);">
                这里不设置系统提示词；每次仅携带当前页信息进行对话。支持粘贴或上传图片参与对话。
            </div>
        </div>
    `;
    container.appendChild(systemDiv);

    if (!nativeChatHistory[currentSlideIndex]) {
        nativeChatHistory[currentSlideIndex] = [];
    }
    for (const msg of nativeChatHistory[currentSlideIndex]) {
        appendNativeChatMessageToDom(msg.role, msg.content);
    }

    container.scrollTop = container.scrollHeight;
}

function clearNativeChatContext() {
    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    if (!confirm('确定要清除当前页的自由对话上下文吗？这将删除该页的对话记录和已添加图片。')) {
        return;
    }

    nativeChatHistory[currentSlideIndex] = [];
    nativeUploadedImagesBySlide[currentSlideIndex] = [];
    renderNativeChatMessages();
    renderNativeUploadedImages();
    updateNativeUploadButtonState();
    showNotification('自由对话上下文已清除', 'info');
}

function appendNativeChatMessageToDom(role, content, messageId = null) {
    const container = document.getElementById('aiNativeChatMessages');
    if (!container) return null;

    const messageDiv = document.createElement('div');
    messageDiv.className = `ai-message ${role === 'user' ? 'user' : 'assistant'}`;
    if (messageId) messageDiv.id = messageId;

    if (role === 'user') {
        messageDiv.textContent = content;
    } else {
        setNativeAssistantMessageText(messageDiv, content);
    }
    container.appendChild(messageDiv);
    if (role !== 'user') {
        refreshNativeAssistantMessageLayout(messageDiv);
    }
    container.scrollTop = container.scrollHeight;
    return messageDiv;
}

function addNativeWaitingAnimation() {
    const container = document.getElementById('aiNativeChatMessages');
    if (!container) return null;
    const waitingDiv = document.createElement('div');
    waitingDiv.className = 'ai-message assistant ai-waiting';
    waitingDiv.id = 'ai-native-waiting';
    waitingDiv.innerHTML = `
        <div class="ai-typing-indicator">
            <span></span>
            <span></span>
            <span></span>
        </div>
        <span style="margin-left: 10px;">AI正在思考中...</span>
    `;
    container.appendChild(waitingDiv);
    container.scrollTop = container.scrollHeight;
    return waitingDiv;
}

function removeNativeWaitingAnimation() {
    const waitingDiv = document.getElementById('ai-native-waiting');
    if (waitingDiv) waitingDiv.remove();
}

function getNativeUploadedImages() {
    if (!nativeUploadedImagesBySlide[currentSlideIndex]) {
        nativeUploadedImagesBySlide[currentSlideIndex] = [];
    }
    return nativeUploadedImagesBySlide[currentSlideIndex];
}

function updateNativeUploadButtonState() {
    const btn = document.getElementById('aiNativeImageUploadBtn');
    const images = getNativeUploadedImages();
    if (!btn) return;
    if (images.length === 0) {
        btn.classList.remove('has-images');
        btn.removeAttribute('data-count');
    } else {
        btn.classList.add('has-images');
        btn.setAttribute('data-count', images.length);
    }
}

function renderNativeUploadedImages() {
    const container = document.getElementById('aiNativeUploadedImages');
    if (!container) return;

    const images = getNativeUploadedImages();
    container.innerHTML = '';

    images.forEach((image, index) => {
        const imageDiv = document.createElement('div');
        imageDiv.className = 'ai-uploaded-image';
        const previewUrl = image.dataUrl || image.url;

        imageDiv.innerHTML = `
            <img src="${previewUrl}" alt="${escapeHtml(image.name)}" onclick="showNativeUploadedImagePreview(${index})">
            <button class="ai-image-remove" onclick="removeNativeUploadedImage(${index}); event.stopPropagation();" title="移除图片">
                <i class="fas fa-times"></i>
            </button>
            <div class="ai-image-info">
                <div style="font-weight: 600; margin-bottom: 2px;">${escapeHtml(image.name)}</div>
                <div style="opacity: 0.85;">${formatFileSize(image.size || 0)} · 发送时附带</div>
            </div>
        `;

        container.appendChild(imageDiv);
    });
}

function showNativeUploadedImagePreview(index) {
    const images = getNativeUploadedImages();
    if (index < 0 || index >= images.length) return;
    const image = images[index];
    window.currentPreviewOwner = 'native_dialog';
    window.currentPreviewNativeIndex = index;
    const previewUrl = image.dataUrl || image.url;
    showImagePreview({
        id: image.id,
        name: image.name,
        size: image.size || 0,
        url: previewUrl
    });
}

function removeNativeUploadedImage(index) {
    const images = getNativeUploadedImages();
    if (index >= 0 && index < images.length) {
        images.splice(index, 1);
        renderNativeUploadedImages();
        updateNativeUploadButtonState();
    }
}

function triggerNativeImageUpload() {
    if (isNativeImageUploading) {
        showNotification('正在上传中，请稍候...', 'warning');
        return;
    }
    const input = document.getElementById('aiNativeImageFileInput');
    if (input) input.click();
}

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        try {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error('FileReader读取失败'));
            reader.readAsDataURL(file);
        } catch (e) {
            reject(e);
        }
    });
}

async function uploadNativeSingleFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', file.name.split('.')[0]);
    formData.append('description', `AI自由对话上传的图片: ${file.name}`);
    formData.append('category', 'ai_native_dialog');
    formData.append('tags', 'ai_native_dialog,ppt_edit');

    const response = await fetch('/api/image/upload', {
        method: 'POST',
        body: formData
    });

    const result = await response.json();
    if (!result.success) {
        return { success: false, message: result.message || '上传失败' };
    }

    const imageUrl = await getImageAbsoluteUrl(result.image_id);
    return {
        success: true,
        data: {
            id: result.image_id,
            name: file.name,
            size: file.size,
            url: imageUrl
        }
    };
}

async function uploadNativeFiles(files) {
    if (!files || files.length === 0) return;
    if (isNativeImageUploading) return;

    const supportedTypes = [
        'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
        'image/webp', 'image/bmp', 'image/svg+xml'
    ];

    const validFiles = [];
    const errors = [];

    Array.from(files).forEach(file => {
        if (!supportedTypes.includes((file.type || '').toLowerCase())) {
            errors.push(`${file.name}: 不支持的图片格式 (${file.type || 'unknown'})`);
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            errors.push(`${file.name}: 文件大小超过10MB限制 (${formatFileSize(file.size)})`);
            return;
        }
        validFiles.push(file);
    });

    if (errors.length > 0) {
        showNotification(errors[0], 'warning');
    }
    if (validFiles.length === 0) return;

    // 限制数量，避免请求过大
    const images = getNativeUploadedImages();
    const maxImages = 6;
    if (images.length + validFiles.length > maxImages) {
        showNotification(`最多只能上传 ${maxImages} 张图片（当前已上传 ${images.length} 张）`, 'warning');
        return;
    }

    isNativeImageUploading = true;
    updateNativeUploadButtonState();
    try {
        for (const file of validFiles) {
            let dataUrl = null;
            try {
                const maybe = await readFileAsDataUrl(file);
                dataUrl = typeof maybe === 'string' ? maybe : null;
            } catch (e) {
                // 忽略读取失败，继续走上传URL
            }

            const result = await uploadNativeSingleFile(file);
            if (result.success) {
                images.push({
                    ...result.data,
                    dataUrl: dataUrl
                });
            } else {
                // 即使上传失败，仍允许用 dataUrl 参与对话
                if (dataUrl) {
                    images.push({
                        id: null,
                        name: file.name,
                        size: file.size,
                        url: dataUrl,
                        dataUrl: dataUrl
                    });
                    showNotification(`上传失败，已改用本地图片参与对话：${file.name}`, 'warning');
                } else {
                    showNotification(`上传失败: ${file.name} - ${result.message}`, 'error');
                }
            }
        }
        renderNativeUploadedImages();
        updateNativeUploadButtonState();
        showNotification(`已上传 ${validFiles.length} 张图片`, 'success');
    } catch (e) {
        showNotification('上传失败，请重试', 'error');
    } finally {
        isNativeImageUploading = false;
        updateNativeUploadButtonState();
    }
}

async function handleNativePaste(e) {
    if (!e || !e.clipboardData) return;
    const items = e.clipboardData.items;
    if (!items) return;

    const imageFiles = [];
    for (const item of items) {
        if (item && item.type && item.type.startsWith('image/')) {
            const file = item.getAsFile();
            if (file) imageFiles.push(file);
        }
    }

    if (imageFiles.length > 0) {
        e.preventDefault();
        await uploadNativeFiles(imageFiles);
    }
}

// AI编辑助手：视觉模式开启时支持粘贴图片（自动上传并随消息发送）
async function handleAIPaste(e) {
    if (!visionModeEnabled) return;
    if (!e || !e.clipboardData) return;
    const items = e.clipboardData.items;
    if (!items) return;

    const imageFiles = [];
    for (const item of items) {
        if (item && item.type && item.type.startsWith('image/')) {
            const file = item.getAsFile();
            if (file) imageFiles.push(file);
        }
    }

    if (imageFiles.length > 0) {
        e.preventDefault();
        showNotification(`检测到 ${imageFiles.length} 张剪贴板图片，正在处理...`, 'info');
        handleFiles(imageFiles);
    }
}

async function sendNativeChatMessage() {
    const inputBox = document.getElementById('aiNativeInputBox');
    const sendBtn = document.getElementById('aiNativeSendBtn');
    if (!inputBox || !sendBtn) return;

    let message = inputBox.value.trim();
    if (!message || isNativeChatSending) return;

    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    isNativeChatSending = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 响应中...';
    inputBox.disabled = true;

    if (!nativeChatHistory[currentSlideIndex]) nativeChatHistory[currentSlideIndex] = [];

    // 仅发送“此前”历史，避免当前用户消息重复进入上下文
    const chatHistory = nativeChatHistory[currentSlideIndex].map(m => ({
        role: m.role,
        content: m.content
    }));

    // 用户消息入历史 + UI
    nativeChatHistory[currentSlideIndex].push({ role: 'user', content: message, timestamp: Date.now() });
    appendNativeChatMessageToDom('user', message);
    inputBox.value = '';

    addNativeWaitingAnimation();

    try {
        const currentSlide = slidesData[currentSlideIndex];
        const referencedImages = getNativeUploadedImages().map(image => ({
            id: image.id,
            name: image.name,
            size: image.size > 0 ? formatFileSize(image.size) : '未知大小',
            url: image.dataUrl || image.url
        }));

        const payload = {
            slideIndex: currentSlideIndex + 1,
            slideTitle: currentSlide.title,
            slideContent: currentSlide.html_content,
            userRequest: message,
            chatHistory: chatHistory,
            images: referencedImages
        };

        const response = await fetch('/api/ai/slide-native-dialog/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        await handleNativeStreamingResponse(response);
    } catch (error) {
        removeNativeWaitingAnimation();
        appendNativeChatMessageToDom('assistant', '抱歉，无法连接到AI服务。请稍后重试。');
    } finally {
        isNativeChatSending = false;
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<i class="fas fa-paper-plane"></i> 发送';
        inputBox.disabled = false;
        inputBox.focus();
    }
}

async function handleNativeStreamingResponse(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let aiMessageDiv = null;
    let fullResponse = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (!line.trim().startsWith('data: ')) continue;
            const dataStr = line.slice(6).trim();
            if (!dataStr) continue;

            let data;
            try {
                data = JSON.parse(dataStr);
            } catch {
                continue;
            }

            if (data.type === 'start') {
                removeNativeWaitingAnimation();
                const messageId = 'ai-native-streaming-' + Date.now();
                aiMessageDiv = appendNativeChatMessageToDom('assistant', '', messageId);
            } else if (data.type === 'content' && data.content) {
                fullResponse += data.content;
                if (aiMessageDiv) {
                    setNativeAssistantMessageText(aiMessageDiv, fullResponse);
                    const container = document.getElementById('aiNativeChatMessages');
                    if (container) container.scrollTop = container.scrollHeight;
                }
            } else if (data.type === 'complete') {
                fullResponse = data.fullResponse || fullResponse;
                if (aiMessageDiv) {
                    setNativeAssistantMessageText(aiMessageDiv, fullResponse);
                }
                if (!nativeChatHistory[currentSlideIndex]) nativeChatHistory[currentSlideIndex] = [];
                nativeChatHistory[currentSlideIndex].push({ role: 'assistant', content: fullResponse, timestamp: Date.now() });
                return;
            } else if (data.type === 'error') {
                removeNativeWaitingAnimation();
                const err = data.error || '未知错误';
                appendNativeChatMessageToDom('assistant', '抱歉，处理您的请求时出现了错误：' + err);
                return;
            }
        }
    }
}

// AI消息处理函数
