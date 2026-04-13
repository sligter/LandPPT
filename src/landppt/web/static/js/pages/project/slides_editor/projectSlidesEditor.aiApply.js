async function handleStreamingResponse(response, waitingDiv) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let aiMessageDiv = null;
    let streamingMessageId = null;
    let fullResponse = '';
    let newHtmlContent = null;

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.trim().startsWith('data: ')) {
                    try {
                        const dataStr = line.slice(6).trim();
                        if (dataStr) {
                            const data = JSON.parse(dataStr);

                            if (data.type === 'start') {
                                // 移除等待动画，开始显示AI回复
                                removeWaitingAnimation();
                                // 使用时间戳确保每次对话都有唯一的消息ID
                                streamingMessageId = 'ai-streaming-message-' + Date.now();
                                aiMessageDiv = addAIMessage('', 'assistant', streamingMessageId);
                                if (aiMessageDiv) aiMessageDiv.dataset.complete = 'false';
                            } else if (data.type === 'content' && data.content) {
                                // 追加内容到AI消息
                                fullResponse += data.content;
                                if (aiMessageDiv) {
                                    // 转义HTML标签，防止实时渲染
                                    window.projectSlidesEditorPretext.setAssistantMessageText(aiMessageDiv, fullResponse);
                                    // 滚动到底部
                                    const messagesContainer = document.getElementById('aiChatMessages');
                                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                                }
                            } else if (data.type === 'complete') {
                                // 流式输出完成
                                newHtmlContent = data.newHtmlContent;
                                fullResponse = data.fullResponse || fullResponse;
                                if (streamingMessageId) {
                                    updateAIChatHistoryMessage(streamingMessageId, fullResponse);
                                }
                                if (aiMessageDiv) aiMessageDiv.dataset.complete = 'true';

                                console.log('🎯 AI流式响应完成');
                                console.log('📝 完整响应长度:', fullResponse ? fullResponse.length : 0);
                                console.log('🔍 提取的HTML内容:', newHtmlContent ? `长度${newHtmlContent.length}` : '无');

                                if (newHtmlContent) {
                                    console.log('✅ 检测到HTML内容，准备添加按钮');
                                    console.log('📄 HTML内容预览:', newHtmlContent.substring(0, 200));
                                } else {
                                    console.warn('⚠️  未检测到HTML内容');
                                    console.log('📝 完整AI响应预览:', fullResponse ? fullResponse.substring(0, 500) : '无响应内容');
                                }

                                // 确保最终内容正确显示，转义HTML标签
                                if (aiMessageDiv) {
                                    window.projectSlidesEditorPretext.setAssistantMessageText(aiMessageDiv, fullResponse);
                                }

                                // 如果有HTML内容，添加应用按钮
                                if (newHtmlContent) {
                                    console.log('🎯 调用addApplyChangesButton函数');
                                    addApplyChangesButton(aiMessageDiv, newHtmlContent);
                                } else {
                                    // 即使没有HTML，也提供手动提取选项
                                    console.log('🔧 添加手动提取HTML的提示');
                                    addManualHtmlExtractPrompt(aiMessageDiv, fullResponse);
                                }

                                break;
                            } else if (data.type === 'error') {
                                removeWaitingAnimation();
                                const errText = '抱歉，处理您的请求时出现了错误：' + (data.error || '未知错误');
                                if (aiMessageDiv) {
                                    window.projectSlidesEditorPretext.setAssistantMessageText(aiMessageDiv, errText);
                                    aiMessageDiv.dataset.complete = 'true';
                                    if (streamingMessageId) updateAIChatHistoryMessage(streamingMessageId, errText);
                                } else {
                                    addAIMessage(errText, 'assistant');
                                }
                                break;
                            }
                        }
                    } catch (e) {
                        // 解析流式数据失败
                    }
                }
            }
        }
    } catch (error) {
        removeWaitingAnimation();
        const errText = '抱歉，处理流式响应时出现了错误。';
        if (aiMessageDiv) {
            window.projectSlidesEditorPretext.setAssistantMessageText(aiMessageDiv, errText);
            aiMessageDiv.dataset.complete = 'true';
            if (streamingMessageId) updateAIChatHistoryMessage(streamingMessageId, errText);
        } else {
            addAIMessage(errText, 'assistant');
        }
    }
}

// 添加手动HTML提取提示
function addManualHtmlExtractPrompt(messageDiv, fullResponse) {
    if (!messageDiv || !fullResponse) return;

    // 检查是否已经有提示了
    if (messageDiv.querySelector('.manual-html-extract')) return;

    const promptContainer = document.createElement('div');
    promptContainer.className = 'manual-html-extract';
    promptContainer.style.cssText = `
        margin-top: 15px;
        padding: 10px;
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 4px;
        font-size: 14px;
        color: #6c757d;
    `;

    const promptText = document.createElement('p');
    promptText.textContent = '未能自动检测到HTML代码。如果AI的回复中包含HTML代码，您可以点击下方按钮手动提取：';
    promptText.style.margin = '0 0 10px 0';

    const extractBtn = document.createElement('button');
    extractBtn.textContent = '尝试手动提取HTML';
    extractBtn.style.cssText = `
        background: #17a2b8;
        color: white;
        border: none;
        padding: 6px 12px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 12px;
    `;

    extractBtn.addEventListener('click', () => {
        // 尝试更激进的HTML提取
        const htmlContent = extractHtmlFromResponse(fullResponse);
        if (htmlContent) {
            console.log('🎉 手动提取HTML成功');
            promptContainer.remove();
            addApplyChangesButton(messageDiv, htmlContent);
        } else {
            alert('仍然无法提取到HTML内容。请确认AI的回复中包含有效的HTML代码。');
        }
    });

    promptContainer.appendChild(promptText);
    promptContainer.appendChild(extractBtn);
    messageDiv.appendChild(promptContainer);
}

// 更激进的HTML提取函数
function extractHtmlFromResponse(response) {
    if (!response) return null;

    // 尝试多种模式
    const patterns = [
        /```html\s*([\s\S]*?)\s*```/gi,
        /```HTML\s*([\s\S]*?)\s*```/gi,
        /```\s*html\s*([\s\S]*?)\s*```/gi,
        /<html[^>]*>[\s\S]*?<\/html>/gi,
        /<div[^>]*style[^>]*1280px[^>]*>[\s\S]*?<\/div>/gi,
        /<div[^>]*class[^>]*slide[^>]*>[\s\S]*?<\/div>/gi,
        /<div[^>]*>[\s\S]*?<\/div>/gi // 最宽松的匹配
    ];

    for (const pattern of patterns) {
        const matches = response.match(pattern);
        if (matches && matches.length > 0) {
            let extracted = matches[0];
            // 如果是代码块格式，提取内容
            if (extracted.startsWith('```')) {
                const lines = extracted.split('\n');
                lines.shift(); // 移除第一行 ```html
                lines.pop(); // 移除最后一行 ```
                extracted = lines.join('\n').trim();
            }
            if (extracted.length > 50) { // 确保有实质内容
                return extracted;
            }
        }
    }
    return null;
}

// 添加应用更改按钮
function addApplyChangesButton(messageDiv, newHtmlContent) {
    if (!messageDiv || !newHtmlContent) {
        console.error('❌ addApplyChangesButton参数无效:', {
            messageDiv: !!messageDiv,
            newHtmlContent: !!newHtmlContent
        });
        return;
    }

    console.log('🚀 开始添加应用更改按钮');

    // 检查是否已经有按钮了
    if (messageDiv.querySelector('.ai-apply-changes-btn')) {
        console.log('⚠️  按钮已存在，跳过添加');
        return;
    }

    console.log('✅ 开始创建按钮容器和按钮');

    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'ai-apply-changes-container';
    buttonContainer.style.cssText = `
        margin-top: 15px;
        padding-top: 15px;
        border-top: 1px solid #eee;
        display: flex;
        gap: 10px;
        align-items: center;
    `;

    const applyBtn = document.createElement('button');
    applyBtn.className = 'ai-apply-changes-btn';
    applyBtn.innerHTML = '<i class="fas fa-check"></i> 应用更改';
    applyBtn.style.cssText = `
        background: #28a745;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 14px;
        transition: background-color 0.2s ease;
    `;

    const previewBtn = document.createElement('button');
    previewBtn.className = 'ai-preview-changes-btn';
    previewBtn.innerHTML = '<i class="fas fa-eye"></i> 预览';
    previewBtn.style.cssText = `
        background: #007bff;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 14px;
        transition: background-color 0.2s ease;
    `;

    // 绑定事件
    applyBtn.addEventListener('click', async () => {
        applyBtn.disabled = true;
        applyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 应用中...';
        try {
            await applyAIChanges(newHtmlContent);
            applyBtn.innerHTML = '<i class="fas fa-check"></i> 已保存';
            applyBtn.style.background = '#28a745';
            applyBtn.style.color = 'white';

            // 3秒后变为已应用状态
            setTimeout(() => {
                applyBtn.innerHTML = '<i class="fas fa-check-circle"></i> 已应用';
                applyBtn.style.background = '#6c757d';
            }, 3000);
        } catch (error) {
            applyBtn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> 保存失败';
            applyBtn.style.background = '#dc3545';
            applyBtn.style.color = 'white';

            // 显示详细错误信息
            const errorMsg = error.message || '未知错误';
            applyBtn.title = `保存失败: ${errorMsg}`;

            setTimeout(() => {
                applyBtn.innerHTML = '<i class="fas fa-check"></i> 重试应用';
                applyBtn.style.background = '#28a745';
                applyBtn.style.color = 'white';
                applyBtn.title = '';
                applyBtn.disabled = false;
            }, 3000);
        }
    });

    previewBtn.addEventListener('click', () => {
        showHTMLPreview(newHtmlContent);
    });

    // 悬停效果
    applyBtn.addEventListener('mouseenter', () => {
        if (!applyBtn.disabled) applyBtn.style.background = '#218838';
    });
    applyBtn.addEventListener('mouseleave', () => {
        if (!applyBtn.disabled) applyBtn.style.background = '#28a745';
    });

    previewBtn.addEventListener('mouseenter', () => {
        previewBtn.style.background = '#0056b3';
    });
    previewBtn.addEventListener('mouseleave', () => {
        previewBtn.style.background = '#007bff';
    });

    buttonContainer.appendChild(applyBtn);
    buttonContainer.appendChild(previewBtn);
    messageDiv.appendChild(buttonContainer);

    console.log('🎉 按钮添加完成！');
    console.log('📋 按钮容器已添加到消息区域');

    // 验证按钮是否正确添加
    const addedButtons = messageDiv.querySelectorAll('.ai-apply-changes-btn, .ai-preview-changes-btn');
    console.log('🔍 已添加的按钮数量:', addedButtons.length);
}

// 显示HTML预览
function showHTMLPreview(htmlContent) {
    // 创建全屏预览模态框
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: black;
        z-index: 10000;
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 20px;
        box-sizing: border-box;
    `;

    const closeBtn = document.createElement('button');
    closeBtn.innerHTML = '<i class="fas fa-times"></i>';
    closeBtn.style.cssText = `
        position: absolute;
        top: 20px;
        right: 20px;
        background: rgba(255,255,255,0.2);
        color: white;
        border: 2px solid rgba(255,255,255,0.3);
        border-radius: 50%;
        width: 40px;
        height: 40px;
        cursor: pointer;
        font-size: 16px;
        z-index: 10001;
        transition: all 0.3s ease;
    `;

    closeBtn.addEventListener('mouseenter', () => {
        closeBtn.style.background = 'rgba(255,255,255,0.3)';
        closeBtn.style.borderColor = 'rgba(255,255,255,0.5)';
    });

    closeBtn.addEventListener('mouseleave', () => {
        closeBtn.style.background = 'rgba(255,255,255,0.2)';
        closeBtn.style.borderColor = 'rgba(255,255,255,0.3)';
    });

    // 创建PPT容器，使用与全屏放映相同的样式
    const slideContainer = document.createElement('div');
    slideContainer.style.cssText = `
        background: white;
        border-radius: 10px;
        box-shadow: 0 10px 30px rgba(255,255,255,0.2);
        overflow: hidden;
        position: relative;
        width: 100%;
        height: 100%;
        max-width: calc(100vh * 16/9 - 40px);
        max-height: calc(100vw * 9/16 - 40px);
        aspect-ratio: 16/9;
    `;

    const iframe = document.createElement('iframe');
    iframe.style.cssText = `
        width: 100%;
        height: 100%;
        border: none;
        background: white;
    `;
    iframe.srcdoc = htmlContent;

    closeBtn.addEventListener('click', () => {
        document.body.removeChild(modal);
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            document.body.removeChild(modal);
        }
    });

    // 键盘事件支持
    const handleKeyPress = (e) => {
        if (e.key === 'Escape') {
            document.body.removeChild(modal);
            document.removeEventListener('keydown', handleKeyPress);
        }
    };
    document.addEventListener('keydown', handleKeyPress);

    slideContainer.appendChild(iframe);
    modal.appendChild(closeBtn);
    modal.appendChild(slideContainer);
    document.body.appendChild(modal);
}

// 应用AI更改
async function applyAIChanges(newHtmlContent) {
    try {
        // 防御：若slides_data存在缺页导致错位，先按page_number/大纲归一化，避免错页写入
        normalizeSlidesDataToOutline();

        // 验证当前索引状态
        if (!validateCurrentSlideIndex('applyAIChanges')) {
            throw new Error(`无效的幻灯片索引: ${currentSlideIndex}，总页数: ${slidesData ? slidesData.length : 'undefined'}`);
        }

        // 获取当前正在编辑的幻灯片索引，确保索引正确
        const targetSlideIndex = currentSlideIndex;



        // 双重验证索引有效性
        if (targetSlideIndex < 0 || targetSlideIndex >= slidesData.length) {
            throw new Error(`无效的幻灯片索引: ${targetSlideIndex}，总页数: ${slidesData.length}`);
        }

        // 更新当前幻灯片数据
        slidesData[targetSlideIndex].html_content = newHtmlContent;
        if (typeof setInitialSlideState === 'function') {
            setInitialSlideState(targetSlideIndex, newHtmlContent);
        }

        // 标记当前幻灯片为用户编辑状态
        slidesData[targetSlideIndex].is_user_edited = true;

        // 更新预览
        const slideFrame = document.getElementById('slideFrame');
        if (slideFrame) {
            setSafeIframeContent(slideFrame, newHtmlContent);
            setTimeout(() => {
                forceReinitializeIframeJS(slideFrame);
            }, 300);
        }

        // 更新缩略图
        const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[targetSlideIndex];
        if (thumbnailIframe) {
            setSafeIframeContent(thumbnailIframe, newHtmlContent);
        }

        // 更新代码编辑器
        const codeEditor = document.getElementById('codeEditor');
        if (codeEditor) {
            if (codeMirrorEditor && isCodeMirrorInitialized) {
                codeMirrorEditor.setValue(newHtmlContent);
            } else {
                codeEditor.value = newHtmlContent;
            }
        }

        // 保存到服务器 - 使用单个幻灯片保存API，确保使用正确的索引
        const saveSuccess = await saveSingleSlideToServer(targetSlideIndex, newHtmlContent);

        if (saveSuccess) {
            showNotification(`AI更改已应用并保存！(第${targetSlideIndex + 1}页)`, 'success');
        } else {
            showNotification(`AI更改已应用，但保存第${targetSlideIndex + 1}页时出现问题`, 'warning');
        }

    } catch (error) {
        // 尝试恢复原始内容
        try {
            // 这里可以添加恢复逻辑，但需要保存原始内容
        } catch (restoreError) {
            // Failed to restore original content
        }

        showNotification('应用更改失败：' + error.message, 'error');
        throw error; // 重新抛出错误以便按钮状态处理
    }
}

