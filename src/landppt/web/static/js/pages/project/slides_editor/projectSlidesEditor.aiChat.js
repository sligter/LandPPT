function setAIAssistantMessageText(messageDiv, content) {
    return window.projectSlidesEditorPretext.setAssistantMessageText(messageDiv, content);
}

function refreshAIAssistantMessageLayout(messageDiv) {
    return window.projectSlidesEditorPretext.refreshAssistantMessageLayout(messageDiv);
}

function destroyAIAssistantMessageRender(messageDiv) {
    window.projectSlidesEditorPretext.destroyAssistantMessageRender(messageDiv);
}

function addAIMessage(content, type = 'assistant', messageId = null) {
    const messagesContainer = document.getElementById('aiChatMessages');

    function attachRegenerateButton(messageDiv) {
        if (!messageDiv) return;
        if (!messageDiv.classList.contains('assistant')) return;
        if (messageDiv.classList.contains('system')) return;
        if (messageDiv.classList.contains('ai-waiting')) return;
        if (!messageDiv.id) return;
        if (messageDiv.querySelector('.ai-answer-regenerate-btn')) return;

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ai-answer-regenerate-btn';
        btn.title = '重新回答';
        btn.innerHTML = '<i class="fas fa-sync-alt"></i>';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            regenerateAIAnswerForMessage(messageDiv.id);
        });
        messageDiv.appendChild(btn);
    }

    // 如果提供了messageId，尝试找到现有消息并更新
    if (messageId) {
        const existingMessage = document.getElementById(messageId);
        if (existingMessage) {
            if (type === 'user') {
                existingMessage.textContent = content;
            } else {
                setAIAssistantMessageText(existingMessage, content);
                attachRegenerateButton(existingMessage);
            }
            messagesContainer.scrollTop = messagesContainer.scrollHeight;

            // 尝试同步更新对话历史（用于流式消息的最终落库/覆盖）
            updateAIChatHistoryMessage(messageId, content);
            return existingMessage;
        }
    }

    // 创建新消息
    const messageDiv = document.createElement('div');
    messageDiv.className = `ai-message ${type}`;
    if (!messageId && type !== 'user') {
        messageId = 'ai-message-' + Date.now() + '-' + Math.random().toString(16).slice(2);
    }
    if (messageId) messageDiv.id = messageId;
    if (type === 'assistant') {
        messageDiv.dataset.complete = (content && String(content).trim()) ? 'true' : 'false';
    }

    if (type === 'user') {
        messageDiv.textContent = content;
    } else {
        setAIAssistantMessageText(messageDiv, content);
        attachRegenerateButton(messageDiv);
    }

    messagesContainer.appendChild(messageDiv);
    if (type !== 'user') {
        refreshAIAssistantMessageLayout(messageDiv);
    }
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // 保存到聊天历史（按幻灯片索引存储）
    if (currentSlideIndex >= 0) {
        if (!aiChatHistory[currentSlideIndex]) {
            aiChatHistory[currentSlideIndex] = [];
        }
        // 将type转换为role格式，以便后端AI能正确理解
        const role = type === 'user' ? 'user' : 'assistant';
        aiChatHistory[currentSlideIndex].push({
            role: role,
            content: content,
            timestamp: Date.now(),
            messageId: messageId
        });
    }

    return messageDiv;
}

function updateAIChatHistoryMessage(messageId, newContent) {
    if (!messageId) return;
    if (currentSlideIndex < 0) return;
    if (!aiChatHistory[currentSlideIndex]) return;

    // 从后往前找，避免同一时间戳生成的ID碰撞（理论上不会）
    for (let i = aiChatHistory[currentSlideIndex].length - 1; i >= 0; i--) {
        const msg = aiChatHistory[currentSlideIndex][i];
        if (msg && msg.messageId === messageId) {
            msg.content = newContent;
            return;
        }
    }
}

// 添加等待响应动画
function addWaitingAnimation() {
    const messagesContainer = document.getElementById('aiChatMessages');
    const waitingDiv = document.createElement('div');
    waitingDiv.className = 'ai-message assistant ai-waiting';
    waitingDiv.id = 'ai-waiting-animation';
    waitingDiv.innerHTML = `
        <div class="ai-typing-indicator">
            <span></span>
            <span></span>
            <span></span>
        </div>
        <span style="margin-left: 10px;">AI正在思考中...</span>
    `;

    messagesContainer.appendChild(waitingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return waitingDiv;
}

// 移除等待动画
function removeWaitingAnimation() {
    document.querySelectorAll('#ai-waiting-animation, .ai-message.ai-waiting').forEach(el => el.remove());
}

function clearAIMessages() {
    const messagesContainer = document.getElementById('aiChatMessages');
    messagesContainer.querySelectorAll('.ai-message.assistant').forEach(destroyAIAssistantMessageRender);
    // 保留系统欢迎消息
    const systemMessage = messagesContainer.querySelector('.ai-message.system');
    messagesContainer.innerHTML = '';
    if (systemMessage) {
        messagesContainer.appendChild(systemMessage);
    }
    // 清除当前幻灯片的对话历史
    if (currentSlideIndex >= 0) {
        aiChatHistory[currentSlideIndex] = [];
    }
}

// 切换幻灯片时清除对话记录
function clearAIMessagesForSlideSwitch() {
    const messagesContainer = document.getElementById('aiChatMessages');
    messagesContainer.querySelectorAll('.ai-message.assistant').forEach(destroyAIAssistantMessageRender);
    // 保留系统欢迎消息
    const systemMessage = messagesContainer.querySelector('.ai-message.system');
    messagesContainer.innerHTML = '';
    if (systemMessage) {
        messagesContainer.appendChild(systemMessage);
    }
}

// 验证当前幻灯片索引的有效性
function validateCurrentSlideIndex(functionName = 'unknown') {
    const isValid = currentSlideIndex >= 0 && currentSlideIndex < (slidesData ? slidesData.length : 0);

    if (!isValid) {
        return false;
    }

    return true;
}

// 清除AI对话上下文
function clearAIContext() {
    if (confirm('确定要清除当前幻灯片的对话上下文吗？这将删除当前幻灯片的所有对话记录。')) {
        clearAIMessages();
        showNotification('对话上下文已清除', 'info');
    }
}

// 显示当前幻灯片大纲
function showSlideOutline() {
    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const currentSlide = slidesData[currentSlideIndex];
    let outlineContent = '';

    // 尝试从项目大纲中获取当前页的信息
    if (projectOutline && projectOutline.slides && projectOutline.slides[currentSlideIndex]) {
        const slideOutline = projectOutline.slides[currentSlideIndex];
        outlineContent = `
            <h5 style="margin-bottom: 25px; color: #2c3e50; font-size: 1.3em;"><i class="fas fa-file-alt"></i> 第${currentSlideIndex + 1}页大纲编辑</h5>
            <div style="background: #f8f9fa; padding: 25px; border-radius: 8px; margin: 15px 0;">
                <div style="margin-bottom: 20px;">
                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">标题：</label>
                    <input type="text" id="slideTitle" value="${(slideOutline.title || currentSlide.title || '').replace(/"/g, '&quot;')}"
                           style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; box-sizing: border-box;">
                </div>
                <div style="margin-bottom: 20px;">
                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">类型：</label>
                    <select id="slideType" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; box-sizing: border-box;">
                        <option value="title" ${(slideOutline.slide_type || slideOutline.type) === 'title' ? 'selected' : ''}>标题页</option>
                        <option value="content" ${(slideOutline.slide_type || slideOutline.type) === 'content' ? 'selected' : ''}>内容页</option>
                        <option value="conclusion" ${(slideOutline.slide_type || slideOutline.type) === 'conclusion' ? 'selected' : ''}>结论页</option>
                    </select>
                </div>
                ${slideOutline.content_points ? `
                    <div style="margin-bottom: 20px;">
                        <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">要点：</label>
                        <div id="bulletPointsContainer" style="background: white; border: 1px solid #ddd; border-radius: 6px; padding: 8px; min-height: 120px;">
                            ${slideOutline.content_points.map((point, index) => `
                                <div class="bullet-point-item" data-index="${index}" style="display: flex; align-items: flex-start; margin-bottom: 8px; padding: 8px; border-radius: 4px; transition: all 0.2s ease; position: relative;">
                                    <span style="color: #666; margin-right: 8px; font-weight: bold; min-width: 20px;">•</span>
                                    <div style="flex: 1; position: relative;">
                                        <div class="bullet-point-text" contenteditable="true" style="outline: none; min-height: 20px; line-height: 1.4; word-wrap: break-word;">${point}</div>
                                    </div>

                                </div>
                            `).join('')}
                        </div>
                        <div style="margin-top: 8px; text-align: right; display: flex; gap: 8px; justify-content: flex-end;">
                            <button class="enhance-all-btn" onclick="enhanceAllBulletPoints()" title="AI增强所有要点" style="background-color: #6c757d; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer;">
                                <span>增强要点</span>
                            </button>
                            <button type="button" onclick="addNewBulletPoint()" class="btn btn-sm modal-btn-primary bullet-add-btn" style="background-color: #6c757d; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer;">
                                <i class="fas fa-plus"></i><span>添加要点</span>
                            </button>
                        </div>
                    </div>
                ` : `
                    <div style="margin-bottom: 20px;">
                        <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">要点：</label>
                        <div id="bulletPointsContainer" style="background: white; border: 1px solid #ddd; border-radius: 6px; padding: 8px; min-height: 120px;">
                            <div class="empty-bullet-points" style="text-align: center; color: #999; padding: 40px 20px;">
                                <i class="fas fa-list" style="font-size: 24px; margin-bottom: 10px; opacity: 0.5;"></i>
                                <p style="margin: 0;">暂无要点，点击下方按钮添加</p>
                            </div>
                        </div>
                        <div class="bullet-actions">
                            <button type="button" class="btn btn-sm modal-btn-neutral" onclick="enhanceAllBulletPoints()" title="AI增强所有要点">
                                <span>增强要点</span>
                            </button>
                            <button type="button" class="btn btn-sm modal-btn-primary bullet-add-btn" onclick="addNewBulletPoint()">
                                <i class="fas fa-plus"></i><span>添加要点</span>
                            </button>
                        </div>
                    </div>
                `}
                <div style="margin-bottom: 15px;">
                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">描述：</label>
                    <textarea id="slideDescription" rows="4" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; box-sizing: border-box; resize: vertical;">${slideOutline.description || ''}</textarea>
                </div>
            </div>
        `;
    } else {
        outlineContent = `
            <h5 style="margin-bottom: 25px; color: #2c3e50; font-size: 1.3em;"><i class="fas fa-file-alt"></i> 第${currentSlideIndex + 1}页大纲编辑</h5>
            <div style="background: #f8f9fa; padding: 25px; border-radius: 8px; margin: 15px 0;">
                <div style="margin-bottom: 20px;">
                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">标题：</label>
                    <input type="text" id="slideTitle" value="${(currentSlide.title || '').replace(/"/g, '&quot;')}"
                           style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; box-sizing: border-box;">
                </div>
                <div style="margin-bottom: 20px;">
                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">类型：</label>
                    <select id="slideType" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; box-sizing: border-box;">
                        <option value="title">标题页</option>
                        <option value="content" selected>内容页</option>
                        <option value="conclusion">结论页</option>
                    </select>
                </div>
                <div style="margin-bottom: 20px;">
                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">要点：</label>
                    <textarea id="slidePoints" rows="6" placeholder="请输入要点，每行一个..." style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; box-sizing: border-box; resize: vertical;"></textarea>
                </div>
                <div style="margin-bottom: 15px;">
                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #495057; font-size: 1.1em;">描述：</label>
                    <textarea id="slideDescription" rows="4" placeholder="请输入幻灯片描述..." style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; box-sizing: border-box; resize: vertical;"></textarea>
                </div>
            </div>
        `;
    }

    // 创建大纲编辑模态框
    const modal = document.createElement('div');
    modal.id = 'slideOutlineModal';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.5);
        z-index: 10001;
        display: flex;
        justify-content: center;
        align-items: center;
    `;

    const outlineContainer = document.createElement('div');
    outlineContainer.style.cssText = `
        background: var(--bg-primary);
        border-radius: 12px;
        padding: 30px;
        width: 90vw;
        max-width: 1200px;
        max-height: 85vh;
        overflow-y: auto;
        position: relative;
        border: 1px solid var(--border-color);
        box-shadow: 0 20px 50px rgba(0,0,0,0.25);
    `;

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'modal-close-button';
    closeBtn.innerHTML = '<i class="fas fa-times"></i>';
    closeBtn.style.cssText += 'position:absolute;top:18px;right:18px;z-index:1;';

    // 添加按钮区域
    const buttonArea = `
        <div style="display: flex; justify-content: space-between; margin-top: 30px; padding-top: 20px; border-top: 2px solid #e9ecef;">
            <button onclick="aiOptimizeSingleSlideInSlidesEditor()" class="outline-modal-btn outline-modal-btn--solid">
                <i class="fas fa-robot"></i>
                <span>AI优化</span>
            </button>
            <div style="display: flex; gap: 15px;">
                <button onclick="saveSlideOutline()" class="outline-modal-btn outline-modal-btn--solid">
                    <i class="fas fa-save"></i>
                    <span>保存大纲</span>
                </button>
                <button onclick="regenerateFromOutline()" class="outline-modal-btn">
                    <i class="fas fa-sync"></i>
                    <span>根据大纲重新生成</span>
                </button>
            </div>
        </div>
    `;

    closeBtn.addEventListener('click', () => {
        document.body.removeChild(modal);
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            document.body.removeChild(modal);
        }
    });

    outlineContainer.innerHTML = outlineContent + buttonArea;
    outlineContainer.appendChild(closeBtn);
    modal.appendChild(outlineContainer);
    document.body.appendChild(modal);
}

// 保存幻灯片大纲
async function saveSlideOutline() {
    const title = document.getElementById('slideTitle').value;
    const type = document.getElementById('slideType').value;
    const description = document.getElementById('slideDescription').value;

    // 从大纲编辑界面收集要点数据
    let points = [];
    const bulletPointsContainer = document.getElementById('bulletPointsContainer');
    if (bulletPointsContainer) {
        const bulletPointItems = bulletPointsContainer.querySelectorAll('.bullet-point-item');
        points = Array.from(bulletPointItems).map(item => {
            const textElement = item.querySelector('.bullet-point-text');
            return textElement ? textElement.textContent.trim() : '';
        }).filter(point => point); // 过滤空要点
    } else {
        // 回退到传统的textarea方式（如果没有新的要点容器）
        const pointsElement = document.getElementById('slidePoints');
        points = pointsElement ? pointsElement.value.split('\n').filter(p => p.trim()) : [];
    }

    // 更新本地数据
    if (!projectOutline) {
        projectOutline = { slides: [] };
    }
    if (!projectOutline.slides) {
        projectOutline.slides = [];
    }

    projectOutline.slides[currentSlideIndex] = {
        title: title,
        slide_type: type,
        type: type,
        description: description,
        content_points: points
    };

    // 更新幻灯片标题
    if (slidesData[currentSlideIndex]) {
        slidesData[currentSlideIndex].title = title;
    }

    try {
        // 保存大纲到数据库
        const response = await fetch(`/projects/${window.landpptEditorConfig.projectId}/update-outline`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                outline_content: JSON.stringify(projectOutline, null, 2)
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        if (data.status === 'success') {
            showNotification('大纲已保存！', 'success');
        } else {
            throw new Error(data.message || data.error || '保存失败');
        }
    } catch (error) {
        showNotification('保存大纲失败：' + error.message, 'error');
        return; // 如果保存失败，不关闭模态框
    }

    // 关闭模态框
    const modal = document.getElementById('slideOutlineModal');
    if (modal) {
        document.body.removeChild(modal);
    }

    // 更新缩略图标题
    const thumbnails = document.querySelectorAll('.slide-thumbnail .slide-title');
    if (thumbnails[currentSlideIndex]) {
        thumbnails[currentSlideIndex].textContent = `${currentSlideIndex + 1}. ${title}`;
    }

    // 更新AI编辑助手右上角的大纲显示
    updateAIOutlineDisplay();
}

// 更新AI编辑助手右上角的大纲显示
function updateAIOutlineDisplay() {
    // 这里可以添加更新右上角大纲显示的逻辑
    // 目前大纲按钮点击时会显示最新的大纲信息
}

// 获取项目选择的全局母版模板
async function getSelectedGlobalTemplate() {
    try {
        const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/selected-global-template`);
        if (!response.ok) {
            return null;
        }
        const data = await response.json();
        return data.template || null;
    } catch (error) {
        return null;
    }
}

// 使用全局母版生成幻灯片HTML内容
async function generateSlideWithGlobalTemplate(template, title, content) {
    try {
        let htmlTemplate = template.html_template;

        // 替换模板中的占位符
        htmlTemplate = htmlTemplate.replace(/\{\{\s*page_title\s*\}\}/g, title);
        htmlTemplate = htmlTemplate.replace(/\{\{\s*main_heading\s*\}\}/g, title);
        htmlTemplate = htmlTemplate.replace(/\{\{\s*page_content\s*\}\}/g, content);
        htmlTemplate = htmlTemplate.replace(/\{\{\s*current_page_number\s*\}\}/g, '1');
        htmlTemplate = htmlTemplate.replace(/\{\{\s*total_page_count\s*\}\}/g, slidesData.length.toString());

        return htmlTemplate;
    } catch (error) {
        // 返回默认的HTML内容
        return `
            <div style="width: 1280px; height: 720px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        display: flex; flex-direction: column; justify-content: center; align-items: center;
                        color: white; font-family: 'Microsoft YaHei', Arial, sans-serif;">
                <h1 style="font-size: 48px; margin-bottom: 20px; text-align: center;">${title}</h1>
                <p style="font-size: 24px; text-align: center;">${content}</p>
            </div>
        `;
    }
}

// 根据大纲重新生成幻灯片
function regenerateFromOutline() {
    if (confirm('确定要根据当前大纲重新生成这张幻灯片吗？这将覆盖现有内容。')) {
        // 先保存大纲
        saveSlideOutline();

        // 然后重新生成
        setTimeout(() => {
            regenerateSlideByIndex(currentSlideIndex);
        }, 500);
    }
}

// 同步更新大纲（插入、删除、排序时调用）
async function updateOutlineForSlideOperation(operation, slideIndex, slideData = null) {
    try {
        if (!projectOutline) {
            projectOutline = { slides: [] };
        }
        if (!projectOutline.slides) {
            projectOutline.slides = [];
        }

        switch (operation) {
            case 'insert':
                // 插入新的幻灯片大纲
                if (slideData) {
                    projectOutline.slides.splice(slideIndex, 0, slideData);
                }
                break;
            case 'delete':
                // 删除指定位置的幻灯片大纲
                if (slideIndex >= 0 && slideIndex < projectOutline.slides.length) {
                    projectOutline.slides.splice(slideIndex, 1);
                }
                break;
            case 'move': {
                // 调整大纲顺序（拖拽排序时调用）
                const toIndex = slideData && Number.isInteger(slideData.to_index) ? slideData.to_index : null;
                if (toIndex === null) break;
                if (slideIndex < 0 || slideIndex >= projectOutline.slides.length) break;
                if (toIndex < 0 || toIndex > projectOutline.slides.length) break;
                if (slideIndex === toIndex) break;

                const moved = projectOutline.slides.splice(slideIndex, 1)[0];
                projectOutline.slides.splice(toIndex, 0, moved);
                break;
            }
        }

        // 保存更新后的大纲到数据库
        const response = await fetch(`/projects/${window.landpptEditorConfig.projectId}/update-outline`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                outline_content: JSON.stringify(projectOutline, null, 2)
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        if (data.status === 'success') {
            // 大纲已同步更新
        } else {
            throw new Error(data.message || data.error || '大纲更新失败');
        }
    } catch (error) {
        throw error;
    }
}

// 发送AI消息 - 使用流式输出
// options:
// - messageOverride: string (optional)
// - appendUserMessage: boolean (default true)
// - chatHistoryOverride: Array<{role:string,content:string}> (optional)
// - skipAutoEmbed: boolean (default false)
async function sendAIMessage(options = {}) {
    const inputBox = document.getElementById('aiInputBox');
    const sendBtn = document.getElementById('aiSendBtn');
    const appendUserMessage = options.appendUserMessage !== false;
    let message = (options.messageOverride ?? inputBox.value).trim();

    if (!message || isAISending) {
        return;
    }

    // 自动将所有已上传的图片信息嵌入到消息中
    if (!options.skipAutoEmbed) {
        message = autoEmbedUploadedImages(message);
    }

    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    // 获取当前幻灯片的对话历史（不包含当前这次的 userRequest）
    let chatHistoryForContext = [];
    if (Array.isArray(options.chatHistoryOverride)) {
        chatHistoryForContext = options.chatHistoryOverride;
    } else if (aiChatHistory[currentSlideIndex]) {
        chatHistoryForContext = aiChatHistory[currentSlideIndex].map(msg => ({
            role: msg.role,
            content: msg.content
        }));
    }

    // 禁用发送按钮和输入框
    isAISending = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 响应中...';
    inputBox.disabled = true;

    if (appendUserMessage) {
        // 添加用户消息
        addAIMessage(message, 'user');
        inputBox.value = '';
    }

    // 添加等待动画
    const waitingDiv = addWaitingAnimation();

    try {
        // 构建AI请求上下文
        const currentSlide = slidesData[currentSlideIndex];

        // 获取当前幻灯片的大纲信息
        let slideOutline = null;
        if (projectOutline && projectOutline.slides && projectOutline.slides[currentSlideIndex]) {
            slideOutline = projectOutline.slides[currentSlideIndex];
        }

        // 捕获幻灯片截图（如果启用了视觉模式）
        let slideScreenshot = null;
        if (visionModeEnabled) {
            slideScreenshot = await captureSlideScreenshot();
        }

        // 获取所有已上传的图片信息
        const referencedImages = getAllUploadedImages();

        const context = {
            slideIndex: currentSlideIndex + 1,
            slideTitle: currentSlide.title,
            slideContent: currentSlide.html_content,
            userRequest: message,
            slideOutline: slideOutline, // 添加当前幻灯片的大纲信息
            chatHistory: chatHistoryForContext, // 添加对话历史（不含当前 userRequest）
            images: referencedImages, // 添加图片信息
            visionEnabled: visionModeEnabled, // 添加视觉模式状态
            slideScreenshot: slideScreenshot, // 添加截图数据
            projectInfo: {
                title: window.landpptEditorProjectInfo.title,
                topic: window.landpptEditorProjectInfo.topic,
                scenario: window.landpptEditorProjectInfo.scenario
            }
        };



        // 发送流式AI编辑请求
        const response = await fetch('/api/ai/slide-edit/stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(context)
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        // 处理流式响应
        await handleStreamingResponse(response, waitingDiv);

    } catch (error) {
        removeWaitingAnimation();
        addAIMessage('抱歉，无法连接到AI服务。请检查网络连接后重试。', 'assistant');
    } finally {
        // 恢复发送按钮和输入框
        isAISending = false;
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<i class="fas fa-paper-plane"></i> 发送';
        inputBox.disabled = false;
        inputBox.focus();
    }
}

async function regenerateLastAIAnswer() {
    if (isAISending) return;

    if (!validateCurrentSlideIndex('regenerateLastAIAnswer')) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const history = aiChatHistory[currentSlideIndex] || [];
    let lastUserIndex = -1;
    for (let i = history.length - 1; i >= 0; i--) {
        if (history[i] && history[i].role === 'user' && (history[i].content || '').trim()) {
            lastUserIndex = i;
            break;
        }
    }

    if (lastUserIndex < 0) {
        showNotification('没有可重新回答的提问', 'warning');
        return;
    }

    const lastUserMessage = (history[lastUserIndex].content || '').trim();
    if (!lastUserMessage) {
        showNotification('没有可重新回答的提问', 'warning');
        return;
    }

    const chatHistoryOverride = history.slice(0, lastUserIndex).map(m => ({
        role: m.role,
        content: m.content
    }));

    // 清理：移除这次提问之后的历史（通常是上一条 assistant 回复）
    aiChatHistory[currentSlideIndex] = history.slice(0, lastUserIndex + 1);

    // UI：移除最后一条 assistant 消息（避免屏幕上同时出现旧答案和新答案）
    const messagesContainer = document.getElementById('aiChatMessages');
    if (messagesContainer) {
        const allMessages = Array.from(messagesContainer.querySelectorAll('.ai-message'));
        for (let i = allMessages.length - 1; i >= 0; i--) {
            const el = allMessages[i];
            if (el.classList.contains('assistant') && !el.classList.contains('ai-waiting')) {
                destroyAIAssistantMessageRender(el);
                el.remove();
                break;
            }
        }
    }

    showNotification('AI正在重新回答...', 'info');
    await sendAIMessage({
        messageOverride: lastUserMessage,
        appendUserMessage: false,
        chatHistoryOverride,
        skipAutoEmbed: true
    });
}

async function regenerateAIAnswerForMessage(assistantMessageId) {
    if (isAISending) return;
    if (!assistantMessageId) return;

    if (!validateCurrentSlideIndex('regenerateAIAnswerForMessage')) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const history = aiChatHistory[currentSlideIndex] || [];
    const assistantIndex = history.findIndex(m => m && m.role === 'assistant' && m.messageId === assistantMessageId);
    if (assistantIndex < 0) {
        showNotification('无法定位要重新回答的消息', 'warning');
        return;
    }

    let userIndex = -1;
    for (let i = assistantIndex - 1; i >= 0; i--) {
        if (history[i] && history[i].role === 'user' && (history[i].content || '').trim()) {
            userIndex = i;
            break;
        }
    }
    if (userIndex < 0) {
        showNotification('没有可重新回答的提问', 'warning');
        return;
    }

    const userMessage = (history[userIndex].content || '').trim();
    if (!userMessage) {
        showNotification('没有可重新回答的提问', 'warning');
        return;
    }

    const chatHistoryOverride = history.slice(0, userIndex).map(m => ({
        role: m.role,
        content: m.content
    }));

    // 截断历史：移除该 assistant 以及其后的所有消息
    aiChatHistory[currentSlideIndex] = history.slice(0, userIndex + 1);

    // DOM：移除该 assistant 气泡以及其后的所有气泡（保留 system/之前消息）
    const assistantEl = document.getElementById(assistantMessageId);
    if (assistantEl && assistantEl.parentElement) {
        let node = assistantEl;
        while (node) {
            const next = node.nextElementSibling;
            if (node.classList && node.classList.contains('ai-message') && !node.classList.contains('system')) {
                if (node.classList.contains('assistant')) {
                    destroyAIAssistantMessageRender(node);
                }
                node.remove();
            }
            node = next;
        }
    }

    showNotification('AI正在重新回答...', 'info');
    await sendAIMessage({
        messageOverride: userMessage,
        appendUserMessage: false,
        chatHistoryOverride,
        skipAutoEmbed: true
    });
}

// 处理流式响应
