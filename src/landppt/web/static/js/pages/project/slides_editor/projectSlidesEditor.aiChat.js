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
async function clearAIContext() {
    if (await Notify.confirm('确定要清除当前幻灯片的对话上下文吗？这将删除当前幻灯片的所有对话记录。', { danger: true })) {
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
            <div class="outline-field">
                <label class="outline-field__label" for="slideTitle">标题：</label>
                <input type="text" id="slideTitle" class="outline-field__input" value="${(slideOutline.title || currentSlide.title || '').replace(/"/g, '&quot;')}">
            </div>
            <div class="outline-field">
                <label class="outline-field__label" for="slideType">类型：</label>
                <select id="slideType" class="outline-field__select">
                    <option value="title" ${(slideOutline.slide_type || slideOutline.type) === 'title' ? 'selected' : ''}>标题页</option>
                    <option value="content" ${(slideOutline.slide_type || slideOutline.type) === 'content' ? 'selected' : ''}>内容页</option>
                    <option value="conclusion" ${(slideOutline.slide_type || slideOutline.type) === 'conclusion' ? 'selected' : ''}>结论页</option>
                </select>
            </div>
            ${slideOutline.content_points ? `
                <div class="outline-field">
                    <label class="outline-field__label">要点：</label>
                    <div id="bulletPointsContainer" class="outline-bullets">
                        ${slideOutline.content_points.map((point, index) => `
                            <div class="bullet-point-item" data-index="${index}">
                                <span style="color: #666; margin-right: 8px; font-weight: bold; min-width: 20px;">•</span>
                                <div style="flex: 1; position: relative;">
                                    <div class="bullet-point-text" contenteditable="true" style="outline: none; min-height: 20px; line-height: 1.4; word-wrap: break-word;">${point}</div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                    <div class="outline-bullets__actions">
                        <button class="enhance-all-btn outline-modal-btn" onclick="enhanceAllBulletPoints()" title="AI增强所有要点">
                            <i class="fas fa-magic"></i><span>增强要点</span>
                        </button>
                        <button type="button" class="outline-modal-btn bullet-add-btn" onclick="addNewBulletPoint()" title="添加要点">
                            <i class="fas fa-plus"></i><span>添加要点</span>
                        </button>
                    </div>
                </div>
            ` : `
                <div class="outline-field">
                    <label class="outline-field__label">要点：</label>
                    <div id="bulletPointsContainer" class="outline-bullets">
                        <div class="outline-bullets__empty">
                            <i class="fas fa-list"></i>
                            <p>暂无要点，点击下方按钮添加</p>
                        </div>
                    </div>
                    <div class="outline-bullets__actions">
                        <button type="button" class="enhance-all-btn outline-modal-btn" onclick="enhanceAllBulletPoints()" title="AI增强所有要点">
                            <i class="fas fa-magic"></i><span>增强要点</span>
                        </button>
                        <button type="button" class="outline-modal-btn bullet-add-btn" onclick="addNewBulletPoint()" title="添加要点">
                            <i class="fas fa-plus"></i><span>添加要点</span>
                        </button>
                    </div>
                </div>
            `}
            <div class="outline-field">
                <label class="outline-field__label" for="slideDescription">描述：</label>
                <textarea id="slideDescription" class="outline-field__textarea" rows="4">${slideOutline.description || ''}</textarea>
            </div>
        `;
    } else {
        outlineContent = `
            <div class="outline-field">
                <label class="outline-field__label" for="slideTitle">标题：</label>
                <input type="text" id="slideTitle" class="outline-field__input" value="${(currentSlide.title || '').replace(/"/g, '&quot;')}">
            </div>
            <div class="outline-field">
                <label class="outline-field__label" for="slideType">类型：</label>
                <select id="slideType" class="outline-field__select">
                    <option value="title">标题页</option>
                    <option value="content" selected>内容页</option>
                    <option value="conclusion">结论页</option>
                </select>
            </div>
            <div class="outline-field">
                <label class="outline-field__label" for="slidePoints">要点：</label>
                <textarea id="slidePoints" class="outline-field__textarea" rows="6" placeholder="请输入要点，每行一个..."></textarea>
            </div>
            <div class="outline-field">
                <label class="outline-field__label" for="slideDescription">描述：</label>
                <textarea id="slideDescription" class="outline-field__textarea" rows="4" placeholder="请输入幻灯片描述..."></textarea>
            </div>
        `;
    }

    // 创建大纲编辑模态框
    const modal = document.createElement('div');
    modal.id = 'slideOutlineModal';
    modal.className = 'outline-modal';

    const content = document.createElement('div');
    content.className = 'outline-modal__content';

    // 头部：标题 + 关闭按钮
    const header = document.createElement('div');
    header.className = 'outline-modal__header';
    header.innerHTML = `
        <h5 class="outline-modal__title"><i class="fas fa-file-alt"></i> 第${currentSlideIndex + 1}页大纲编辑</h5>
    `;

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'outline-modal__close';
    closeBtn.setAttribute('aria-label', '关闭');
    closeBtn.innerHTML = '<i class="fas fa-times"></i>';

    header.appendChild(closeBtn);

    // 内容区
    const body = document.createElement('div');
    body.className = 'outline-modal__body';
    body.innerHTML = outlineContent;

    // 底部按钮区
    const footer = document.createElement('div');
    footer.className = 'outline-modal__footer';
    footer.innerHTML = `
        <button onclick="aiOptimizeSingleSlideInSlidesEditor()" class="outline-modal-btn outline-modal-btn--solid">
            <i class="fas fa-robot"></i>
            <span>AI优化</span>
        </button>
        <div class="outline-modal__footer-group">
            <button onclick="saveSlideOutline()" class="outline-modal-btn outline-modal-btn--solid">
                <i class="fas fa-save"></i>
                <span>保存大纲</span>
            </button>
            <button onclick="regenerateFromOutline()" class="outline-modal-btn">
                <i class="fas fa-sync"></i>
                <span>根据大纲重新生成</span>
            </button>
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

    content.appendChild(header);
    content.appendChild(body);
    content.appendChild(footer);
    modal.appendChild(content);
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
        slidesData[currentSlideIndex].slide_type = type;
        slidesData[currentSlideIndex].content_type = type;
        slidesData[currentSlideIndex].description = description;
        slidesData[currentSlideIndex].content_points = points;
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
            if (typeof saveSingleSlideToServer === 'function' && slidesData[currentSlideIndex]?.html_content) {
                await saveSingleSlideToServer(
                    currentSlideIndex,
                    slidesData[currentSlideIndex].html_content,
                    { slideData: slidesData[currentSlideIndex], isUserEdited: true }
                );
            }
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
            <div style="width: 1280px; height: 720px; background: #ffffff;
                        display: flex; flex-direction: column; justify-content: center; align-items: center;
                        color: #111111; font-family: 'Microsoft YaHei', Arial, sans-serif;">
                <h1 style="font-size: 48px; margin-bottom: 20px; text-align: center;">${title}</h1>
                <p style="font-size: 24px; text-align: center; color: #6b7078;">${content}</p>
            </div>
        `;
    }
}

// 根据大纲重新生成幻灯片
async function regenerateFromOutline() {
    if (await Notify.confirm('确定要根据当前大纲重新生成这张幻灯片吗？这将覆盖现有内容。', { danger: true })) {
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

        if (Array.isArray(projectOutline.slides)) {
            projectOutline.slides.forEach((slide, index) => {
                if (slide && typeof slide === 'object') {
                    slide.page_number = index + 1;
                }
            });
        }

        // 保存更新后的大纲到数据库
        const operationPayload = {
            type: operation,
            slide_index: slideIndex
        };
        if (operation === 'move' && slideData && Number.isInteger(slideData.to_index)) {
            operationPayload.to_index = slideData.to_index;
        }
        if (operation === 'insert' && slideData) {
            operationPayload.slide_data = slideData;
        }

        const response = await fetch(`/projects/${window.landpptEditorConfig.projectId}/update-outline`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                outline_content: JSON.stringify(projectOutline, null, 2),
                operation: operationPayload
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

// ---------------------------------------------------------------------------
// 侧栏 AI 助手：agent run 的可视化与实时预览
// ---------------------------------------------------------------------------

/** 当前正在运行的 run；用于「停止」按钮和防重入。 */
let activeAgentRun = null;

const AGENT_TOOL_META = {
    get_context: { label: '读取上下文', icon: 'fa-circle-info' },
    read_slide: { label: '读取页面结构', icon: 'fa-sitemap' },
    find_elements: { label: '查找元素', icon: 'fa-magnifying-glass' },
    read_element: { label: '读取元素', icon: 'fa-code' },
    set_text: { label: '修改文字', icon: 'fa-font' },
    set_attributes: { label: '修改属性', icon: 'fa-tags' },
    set_style: { label: '调整样式', icon: 'fa-paintbrush' },
    insert_html: { label: '插入内容', icon: 'fa-plus' },
    replace_element: { label: '替换元素', icon: 'fa-right-left' },
    remove_element: { label: '删除元素', icon: 'fa-trash' },
    replace_slide: { label: '整页重写', icon: 'fa-file-code' },
    validate_draft: { label: '安全校验', icon: 'fa-shield-halved' },
    diff_draft: { label: '查看改动', icon: 'fa-code-compare' },
    undo_last_edit: { label: '撤销上一步', icon: 'fa-rotate-left' }
};

const AGENT_STATUS_TEXT = {
    completed: '编辑完成',
    max_iterations: '达到最大轮数，返回当前草稿',
    cancelled: '已停止',
    failed: '编辑失败'
};

function getAgentToolMeta(tool) {
    return AGENT_TOOL_META[tool] || { label: tool || '工具', icon: 'fa-wrench' };
}

function compactAgentText(value, maxLength = 420) {
    const text = typeof value === 'string' ? value : String(value ?? '');
    if (text.length <= maxLength) return text;
    return `${text.slice(0, maxLength)}...`;
}

function stringifyAgentPayload(payload) {
    if (payload === null || payload === undefined) return '';
    if (typeof payload !== 'object') return compactAgentText(String(payload));
    try {
        return JSON.stringify(payload, (key, value) => (
            typeof value === 'string' ? compactAgentText(value, 400) : value
        ), 2);
    } catch (error) {
        return compactAgentText(String(payload));
    }
}

/**
 * 一次 run 在聊天气泡里的视图：状态条 + 步骤时间线 + 总结 + 结果操作。
 */
function createAgentRunView(messageDiv, options = {}) {
    const anchor = messageDiv.querySelector('.ai-answer-regenerate-btn');

    const root = document.createElement('div');
    root.className = 'agent-run';

    const status = document.createElement('div');
    status.className = 'agent-run-status is-running';

    const statusIcon = document.createElement('i');
    statusIcon.className = 'fas fa-circle-notch fa-spin agent-run-status-icon';

    const statusText = document.createElement('span');
    statusText.className = 'agent-run-status-text';
    statusText.textContent = '正在分析当前页面…';

    const stopBtn = document.createElement('button');
    stopBtn.type = 'button';
    stopBtn.className = 'agent-run-stop';
    stopBtn.innerHTML = '<i class="fas fa-stop"></i> 停止';
    stopBtn.addEventListener('click', () => {
        stopBtn.disabled = true;
        stopBtn.innerHTML = '<i class="fas fa-hourglass-half"></i> 停止中…';
        if (typeof options.onStop === 'function') options.onStop();
    });

    status.appendChild(statusIcon);
    status.appendChild(statusText);
    status.appendChild(stopBtn);

    const steps = document.createElement('div');
    steps.className = 'agent-run-steps';

    const actions = document.createElement('div');
    actions.className = 'agent-run-actions';

    root.appendChild(status);
    root.appendChild(steps);
    root.appendChild(actions);
    messageDiv.insertBefore(root, anchor || null);

    const stepsByCallId = new Map();

    function scrollToBottom() {
        const container = document.getElementById('aiChatMessages');
        if (container) container.scrollTop = container.scrollHeight;
    }

    function addStepRow({ icon, label, summary, detail, state }) {
        const row = document.createElement('div');
        row.className = `agent-step is-${state || 'running'}`;

        const head = document.createElement('button');
        head.type = 'button';
        head.className = 'agent-step-head';
        head.setAttribute('aria-expanded', 'false');

        const stateIcon = document.createElement('i');
        stateIcon.className = `fas ${icon} agent-step-icon`;

        const labelEl = document.createElement('span');
        labelEl.className = 'agent-step-label';
        labelEl.textContent = label;

        const summaryEl = document.createElement('span');
        summaryEl.className = 'agent-step-summary';
        summaryEl.textContent = summary || '';

        const caret = document.createElement('i');
        caret.className = 'fas fa-chevron-right agent-step-caret';
        caret.setAttribute('aria-hidden', 'true');

        head.appendChild(stateIcon);
        head.appendChild(labelEl);
        head.appendChild(summaryEl);
        head.appendChild(caret);
        row.appendChild(head);

        const detailEl = document.createElement('pre');
        detailEl.className = 'agent-step-detail';
        detailEl.textContent = detail || '';
        if (detail) row.appendChild(detailEl);

        head.addEventListener('click', () => {
            const expanded = row.classList.toggle('is-expanded');
            head.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        });

        steps.appendChild(row);
        scrollToBottom();

        return {
            row,
            setState(nextState) {
                row.className = `agent-step is-${nextState}`;
            },
            setIcon(nextIcon) {
                stateIcon.className = `fas ${nextIcon} agent-step-icon`;
            },
            setSummary(text) {
                summaryEl.textContent = text || '';
            },
            setDetail(text) {
                detailEl.textContent = text || '';
                if (text && !detailEl.isConnected) row.appendChild(detailEl);
            }
        };
    }

    return {
        root,
        setStatus(text, state) {
            statusText.textContent = text;
            if (state) {
                status.className = `agent-run-status is-${state}`;
                statusIcon.className = state === 'running'
                    ? 'fas fa-circle-notch fa-spin agent-run-status-icon'
                    : `fas ${state === 'failed' ? 'fa-triangle-exclamation' : 'fa-check'} agent-run-status-icon`;
            }
        },
        hideStop() {
            stopBtn.remove();
        },
        addThinking(text) {
            if (!text || !text.trim()) return;
            const row = document.createElement('div');
            row.className = 'agent-thought';
            row.textContent = compactAgentText(text.trim(), 600);
            steps.appendChild(row);
            scrollToBottom();
        },
        startTool(event) {
            const meta = getAgentToolMeta(event.tool);
            const step = addStepRow({
                icon: 'fa-circle-notch fa-spin',
                label: meta.label,
                summary: '',
                detail: stringifyAgentPayload(event.toolInput),
                state: 'running'
            });
            stepsByCallId.set(event.callId || `${event.iteration}:${event.tool}`, { step, meta, event });
        },
        finishTool(event) {
            const key = event.callId || `${event.iteration}:${event.tool}`;
            const entry = stepsByCallId.get(key);
            const meta = getAgentToolMeta(event.tool);
            const detail = [
                stringifyAgentPayload(entry ? entry.event.toolInput : event.toolInput),
                '↓',
                stringifyAgentPayload(event.observation)
            ].filter(Boolean).join('\n');

            if (!entry) {
                addStepRow({
                    icon: event.ok ? meta.icon : 'fa-triangle-exclamation',
                    label: meta.label,
                    summary: compactAgentText(event.summary, 140),
                    detail,
                    state: event.ok ? 'done' : 'failed'
                });
                return;
            }
            entry.step.setIcon(event.ok ? meta.icon : 'fa-triangle-exclamation');
            entry.step.setSummary(compactAgentText(event.summary, 140));
            entry.step.setDetail(detail);
            entry.step.setState(event.ok ? 'done' : 'failed');
        },
        addNote(text, state = 'done') {
            addStepRow({
                icon: state === 'failed' ? 'fa-triangle-exclamation' : 'fa-circle-info',
                label: text,
                summary: '',
                detail: '',
                state
            });
        },
        setActions(nodes) {
            actions.innerHTML = '';
            nodes.filter(Boolean).forEach(node => actions.appendChild(node));
            scrollToBottom();
        }
    };
}

function makeAgentActionButton(label, icon, variant, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `agent-action-btn agent-action-btn--${variant}`;
    btn.innerHTML = `<i class="fas ${icon}"></i> ${label}`;
    btn.addEventListener('click', () => onClick(btn));
    return btn;
}

/**
 * run 结束后的结果区：保留并保存 / 撤销 / 看改动 / 全屏预览。
 */
function renderAgentRunResult(view, result, previewSession) {
    const proposal = result && result.proposal;

    if (!proposal || !proposal.changed) {
        view.setActions([
            proposal && proposal.diff
                ? makeAgentActionButton('查看改动', 'fa-code-compare', 'ghost', () => showAgentDiff(proposal.diff))
                : null
        ]);
        if (previewSession) {
            previewSession.revert();
            previewSession.release();
        }
        return;
    }

    const invalid = proposal.validation && proposal.validation.valid === false;

    const hint = document.createElement('span');
    hint.className = 'agent-action-hint';
    hint.textContent = invalid
        ? `校验未通过：${(proposal.validation.errors || []).join('；')}`
        : '预览中，尚未保存';
    if (invalid) hint.classList.add('is-error');

    const keepBtn = makeAgentActionButton('保留并保存', 'fa-check', 'primary', async (btn) => {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 保存中…';
        try {
            await applyAgentProposal(proposal);
            if (previewSession) previewSession.release();
            view.setActions([
                makeAgentActionButton('已保存', 'fa-circle-check', 'muted', () => { }),
                proposal.diff
                    ? makeAgentActionButton('查看改动', 'fa-code-compare', 'ghost', () => showAgentDiff(proposal.diff))
                    : null
            ]);
        } catch (error) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-rotate-right"></i> 重试保存';
            showNotification(`保存失败：${error.message || error}`, 'error');
        }
    });
    keepBtn.disabled = !!invalid;
    if (invalid) keepBtn.title = 'HTML 校验未通过，不能保存';

    const revertBtn = makeAgentActionButton('撤销', 'fa-rotate-left', 'ghost', () => {
        if (previewSession) {
            previewSession.revert();
            previewSession.release();
        }
        view.setActions([
            makeAgentActionButton('已撤销', 'fa-ban', 'muted', () => { })
        ]);
        showNotification('已撤销 Agent 的改动', 'info');
    });

    view.setActions([
        keepBtn,
        revertBtn,
        proposal.diff
            ? makeAgentActionButton('查看改动', 'fa-code-compare', 'ghost', () => showAgentDiff(proposal.diff))
            : null,
        makeAgentActionButton('全屏预览', 'fa-expand', 'ghost', () => showHTMLPreview(proposal.htmlContent)),
        hint
    ]);
}

/** unified diff 查看器。 */
function showAgentDiff(diffText) {
    const modal = document.createElement('div');
    modal.className = 'agent-diff-modal';

    const panel = document.createElement('div');
    panel.className = 'agent-diff-panel';

    const header = document.createElement('div');
    header.className = 'agent-diff-header';
    header.innerHTML = '<span><i class="fas fa-code-compare"></i> Agent 改动</span>';

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'agent-diff-close';
    closeBtn.innerHTML = '<i class="fas fa-times"></i>';
    header.appendChild(closeBtn);

    const body = document.createElement('div');
    body.className = 'agent-diff-body';
    String(diffText || '').split('\n').forEach(line => {
        const row = document.createElement('div');
        row.className = 'agent-diff-line';
        if (line.startsWith('+') && !line.startsWith('+++')) row.classList.add('is-add');
        else if (line.startsWith('-') && !line.startsWith('---')) row.classList.add('is-del');
        else if (line.startsWith('@@')) row.classList.add('is-hunk');
        row.textContent = line || ' ';
        body.appendChild(row);
    });

    const close = () => {
        modal.remove();
        document.removeEventListener('keydown', onKey);
    };
    const onKey = (e) => {
        if (e.key === 'Escape') close();
    };

    closeBtn.addEventListener('click', close);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) close();
    });
    document.addEventListener('keydown', onKey);

    panel.appendChild(header);
    panel.appendChild(body);
    modal.appendChild(panel);
    document.body.appendChild(modal);
}

/**
 * 构造侧栏 agent 请求体。
 */
async function buildSidebarAgentPayload(message, chatHistoryForContext) {
    const currentSlide = slidesData[currentSlideIndex];

    let slideOutline = null;
    if (projectOutline && projectOutline.slides && projectOutline.slides[currentSlideIndex]) {
        slideOutline = projectOutline.slides[currentSlideIndex];
    }

    let slideScreenshot = null;
    if (visionModeEnabled) {
        slideScreenshot = await captureSlideScreenshot();
    }

    return {
        projectId: window.landpptEditorConfig.projectId,
        slideIndex: currentSlideIndex + 1,
        mode: 'slide',
        slideTitle: currentSlide.title,
        slideContent: currentSlide.html_content,
        userRequest: message,
        slideOutline: slideOutline,
        chatHistory: chatHistoryForContext,
        images: getAllUploadedImages(),
        visionEnabled: visionModeEnabled,
        slideScreenshot: slideScreenshot,
        projectInfo: {
            title: window.landpptEditorProjectInfo.title,
            topic: window.landpptEditorProjectInfo.topic,
            scenario: window.landpptEditorProjectInfo.scenario
        }
    };
}

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

    if (!options.skipAutoEmbed) {
        message = autoEmbedUploadedImages(message);
    }

    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    let chatHistoryForContext = [];
    if (Array.isArray(options.chatHistoryOverride)) {
        chatHistoryForContext = options.chatHistoryOverride;
    } else if (aiChatHistory[currentSlideIndex]) {
        chatHistoryForContext = aiChatHistory[currentSlideIndex].map(msg => ({
            role: msg.role,
            content: msg.content
        }));
    }

    isAISending = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 响应中...';
    inputBox.disabled = true;

    if (appendUserMessage) {
        addAIMessage(message, 'user');
        inputBox.value = '';
    }

    const waitingDiv = addWaitingAnimation();
    const slideIndexForRun = currentSlideIndex;
    let view = null;
    let messageDiv = null;
    let messageId = null;
    let previewSession = null;

    const ensureView = () => {
        if (view) return view;
        removeWaitingAnimation();
        messageId = 'ai-agent-message-' + Date.now();
        messageDiv = addAIMessage('', 'assistant', messageId);
        messageDiv.dataset.complete = 'false';
        view = createAgentRunView(messageDiv, {
            onStop: () => {
                if (activeAgentRun) activeAgentRun.cancel();
            }
        });
        return view;
    };

    const setSummary = (text) => {
        if (!messageDiv || !text) return;
        setAIAssistantMessageText(messageDiv, text);
        if (messageId) updateAIChatHistoryMessage(messageId, text);
    };

    try {
        const payload = await buildSidebarAgentPayload(message, chatHistoryForContext);
        previewSession = window.landpptAgentClient.beginPreviewSession(slideIndexForRun);

        const run = window.landpptAgentClient.start({
            payload,
            handlers: {
                onRunStarted: (event) => {
                    ensureView().setStatus(
                        event.protocol === 'text' ? '正在编辑（文本协议）…' : '正在编辑…',
                        'running'
                    );
                },
                onProtocolChanged: (event) => {
                    ensureView().addNote(`已切换为文本协议：${compactAgentText(event.reason, 90)}`);
                },
                onThinking: (event) => {
                    ensureView().addThinking(event.text);
                },
                onToolStarted: (event) => {
                    const v = ensureView();
                    v.setStatus(`${getAgentToolMeta(event.tool).label}…`, 'running');
                    v.startTool(event);
                },
                onToolFinished: (event) => {
                    ensureView().finishTool(event);
                },
                onDraft: (event) => {
                    if (!event.html) return;
                    previewSession.push(event.html);
                    ensureView().setStatus(`已更新预览（第 ${event.revision} 次改动）`, 'running');
                },
                onValidation: (event) => {
                    if (event.valid === false) {
                        ensureView().addNote(
                            `安全校验未通过：${(event.errors || []).join('；')}`,
                            'failed'
                        );
                    }
                },
                onError: (event) => {
                    ensureView().addNote(
                        `${event.phase || '错误'}：${compactAgentText(event.message, 160)}`,
                        'failed'
                    );
                }
            }
        });

        activeAgentRun = run;
        const result = await run.done;

        const v = ensureView();
        v.hideStop();
        const invalidDraft = result.proposal && result.proposal.validation
            && result.proposal.validation.valid === false;
        v.setStatus(
            invalidDraft ? '草稿校验未通过' : (AGENT_STATUS_TEXT[result.status] || '完成'),
            invalidDraft || result.status === 'failed' ? 'failed' : 'done'
        );
        setSummary(result.summary || AGENT_STATUS_TEXT[result.status] || '已完成');
        renderAgentRunResult(v, result, previewSession);
    } catch (error) {
        removeWaitingAnimation();
        const text = error && error.aborted
            ? '已中止本次编辑。'
            : `抱歉，Agent 编辑失败：${(error && error.message) || error}`;
        if (view) {
            view.hideStop();
            view.setStatus(error && error.aborted ? '已中止' : '编辑失败', 'failed');
            setSummary(text);
            if (previewSession) {
                previewSession.revert();
                previewSession.release();
            }
        } else {
            addAIMessage(text, 'assistant');
        }
    } finally {
        if (messageDiv) {
            messageDiv.dataset.complete = 'true';
            refreshAIAssistantMessageLayout(messageDiv);
        }
        activeAgentRun = null;
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
