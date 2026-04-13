        function getTargetAudience(outline) {
            if (!outline || !outline.metadata) {
                return '普通大众';
            }
            const audienceType = outline.metadata.target_audience;
            // 如果选择的是"自定义"，则使用custom_audience字段的值
            if (audienceType === '自定义' && outline.metadata.custom_audience) {
                return outline.metadata.custom_audience;
            }
            return audienceType || '普通大众';
        }

        // 创建美化的AI优化需求输入弹窗
        function showAIOptimizeModal(config) {
            return new Promise((resolve, reject) => {
                // 创建模态框遮罩
                const modal = document.createElement('div');
                modal.className = 'ai-optimize-modal';
                modal.style.cssText = `
                    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(255, 255, 255, 0.98);
                    z-index: 10002; display: flex; align-items: center; justify-content: center;
                    padding: 20px; animation: fadeIn 0.3s ease;
                `;

                // 创建弹窗内容
                const content = document.createElement('div');
                content.style.cssText = `
                    background: var(--surface);
                    border-radius: 20px; padding: 0; max-width: 600px; width: 100%;
                    border: 1px solid var(--glass-border);
                    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
                    animation: slideIn 0.3s ease; max-height: 90vh; overflow: hidden;
                    display: flex; flex-direction: column;
                `;

                // 建议示例
                const suggestions = config.suggestions || [
                    '增加更多文字说明',
                    '简化内容，突出核心要点',
                    '添加数据支撑和案例分析',
                    '优化逻辑结构，增强说服力',
                    '增加视觉化描述建议'
                ];

                content.innerHTML = `
                    <style>
                        @keyframes fadeIn {
                            from { opacity: 0; }
                            to { opacity: 1; }
                        }
                        @keyframes slideIn {
                            from { transform: translateY(-50px); opacity: 0; }
                            to { transform: translateY(0); opacity: 1; }
                        }
                        .ai-optimize-modal__header {
                            background: var(--surface-contrast);
                            color: var(--surface);
                            padding: 24px 32px;
                        }
                        .ai-optimize-modal__header-content {
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            gap: 16px;
                        }
                        .ai-optimize-modal__title {
                            margin: 0 0 6px 0;
                            font-size: 1.3rem;
                            font-weight: 700;
                            letter-spacing: -0.01em;
                            display: flex;
                            align-items: center;
                            gap: 12px;
                        }
                        .ai-optimize-modal__subtitle {
                            margin: 0;
                            font-size: 0.95rem;
                            color: rgba(255, 255, 255, 0.72);
                        }
                        .ai-optimize-modal__close {
                            border: none;
                            background: var(--surface);
                            color: var(--surface-contrast);
                            width: 36px;
                            height: 36px;
                            border-radius: 50%;
                            font-size: 1.2rem;
                            cursor: pointer;
                            transition: background 0.2s ease, transform 0.2s ease;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                        }
                        .ai-optimize-modal__close:hover {
                            background: var(--surface-subtle);
                            transform: scale(1.05);
                        }
                        .ai-optimize-modal__body {
                            padding: 30px 32px;
                            flex: 1;
                            overflow-y: auto;
                            background: var(--surface);
                            display: flex;
                            flex-direction: column;
                            gap: 20px;
                        }
                        .ai-optimize-modal__body .current-info {
                            background: var(--surface-subtle);
                            border-left: 3px solid var(--surface-contrast);
                            padding: 16px 18px;
                            border-radius: 12px;
                            color: var(--text-secondary);
                            font-size: 0.95rem;
                            line-height: 1.7;
                        }
                        .ai-optimize-modal__body .current-info strong {
                            color: var(--surface-contrast);
                            font-weight: 600;
                            display: inline-flex;
                            align-items: center;
                            gap: 8px;
                        }
                        .input-group {
                            display: flex;
                            flex-direction: column;
                            gap: 10px;
                        }
                        .input-label {
                            display: block;
                            color: var(--text-primary);
                            font-weight: 600;
                            font-size: 0.95rem;
                            letter-spacing: 0.01em;
                        }
                        .input-textarea {
                            width: 100%;
                            min-height: 120px;
                            padding: 16px 18px;
                            border: 1px solid var(--glass-border);
                            border-radius: 12px;
                            font-size: 0.95rem;
                            resize: vertical;
                            font-family: inherit;
                            transition: border-color 0.2s ease, box-shadow 0.2s ease;
                            color: var(--text-primary);
                            background: var(--surface);
                        }
                        .input-textarea::placeholder {
                            color: var(--text-muted);
                            opacity: 0.9;
                        }
                        .input-textarea:focus {
                            outline: none;
                            border-color: var(--surface-contrast);
                            box-shadow: 0 0 0 3px rgba(17, 17, 17, 0.08);
                        }
                        .suggestions {
                            display: flex;
                            flex-direction: column;
                            gap: 12px;
                        }
                        .suggestion-label {
                            display: block;
                            color: var(--text-secondary);
                            font-size: 0.85rem;
                            font-weight: 500;
                            letter-spacing: 0.02em;
                        }
                        .suggestion-list {
                            display: flex;
                            flex-wrap: wrap;
                            gap: 8px;
                        }
                        .suggestion-tag {
                            display: inline-flex;
                            align-items: center;
                            justify-content: center;
                            padding: 6px 14px;
                            background: var(--surface-subtle);
                            border: 1px solid var(--glass-border);
                            border-radius: 999px;
                            font-size: 0.8rem;
                            color: var(--text-primary);
                            cursor: pointer;
                            transition: all 0.2s ease;
                        }
                        .suggestion-tag:hover {
                            transform: translateY(-2px);
                            background: var(--surface-contrast);
                            border-color: var(--surface-contrast);
                            color: var(--surface);
                            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.18);
                        }
                        .ai-optimize-modal__footer {
                            padding: 20px 32px;
                            background: var(--surface);
                            border-top: 1px solid var(--glass-border);
                            display: flex;
                            align-items: center;
                            justify-content: space-between;
                            gap: 16px;
                        }
                        .footer-hint {
                            color: var(--text-secondary);
                            font-size: 0.85rem;
                            display: inline-flex;
                            align-items: center;
                            gap: 8px;
                        }
                        .footer-actions {
                            display: flex;
                            gap: 12px;
                        }
                        .footer-actions .btn {
                            min-width: 110px;
                            justify-content: center;
                        }
                        .modal-cancel {
                            background: var(--surface-subtle);
                            border-color: var(--border-color);
                            color: var(--text-primary);
                        }
                        .modal-cancel:hover {
                            background: var(--surface);
                        }
                        @media (max-width: 520px) {
                            .ai-optimize-modal__header,
                            .ai-optimize-modal__body,
                            .ai-optimize-modal__footer {
                                padding-left: 20px;
                                padding-right: 20px;
                            }
                            .footer-actions {
                                width: 100%;
                                flex-direction: column;
                            }
                            .footer-actions .btn {
                                width: 100%;
                            }
                        }
                    </style>

                    <div class="ai-optimize-modal__header">
                        <div class="ai-optimize-modal__header-content">
                            <div>
                                <h3 class="ai-optimize-modal__title">
                                    <i class="fas fa-magic"></i>${config.title}
                                </h3>
                                <p class="ai-optimize-modal__subtitle">${config.subtitle}</p>
                            </div>
                            <button type="button" class="ai-optimize-modal__close" onclick="this.closest('.ai-optimize-modal').remove()" aria-label="关闭">
                                <span aria-hidden="true">×</span>
                            </button>
                        </div>
                    </div>

                    <div class="ai-optimize-modal__body">
                        <div class="current-info">
                            <div>
                                <strong><i class="fas fa-info-circle"></i> 当前内容</strong><br>
                                ${config.currentInfo}
                            </div>
                        </div>

                        <div class="input-group">
                            <label class="input-label" for="aiOptimizeInput">
                                <i class="fas fa-edit"></i> 请描述您的优化需求
                            </label>
                            <textarea id="aiOptimizeInput" class="input-textarea" placeholder="详细描述您希望如何优化此内容...

例如：
- 增加更多技术细节
- 重新组织逻辑结构
- 添加案例分析"></textarea>
                        </div>

                        <div class="suggestions">
                            <label class="suggestion-label">
                                <i class="fas fa-lightbulb"></i> 点击快捷建议快速填充
                            </label>
                            <div class="suggestion-list">
                                ${suggestions.map(s => `<span class="suggestion-tag" onclick="document.getElementById('aiOptimizeInput').value = '${s}'">${s}</span>`).join('')}
                            </div>
                        </div>
                    </div>

                    <div class="ai-optimize-modal__footer">
                        <div class="footer-hint">
                            <i class="fas fa-robot"></i> AI将根据您的需求智能优化内容
                        </div>
                        <div class="footer-actions">
                            <button type="button" class="btn btn-sm modal-cancel" onclick="this.closest('.ai-optimize-modal').remove()">
                                取消
                            </button>
                            <button type="button" id="confirmOptimizeBtn" class="btn btn-sm btn-primary">
                                开始优化
                            </button>
                        </div>
                    </div>
                `;

                modal.appendChild(content);
                document.body.appendChild(modal);

                // 聚焦输入框
                setTimeout(() => {
                    const input = document.getElementById('aiOptimizeInput');
                    if (input) input.focus();
                }, 100);

                // 点击背景关闭
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) {
                        modal.remove();
                        reject('用户取消');
                    }
                });

                // 确认按钮
                const confirmBtn = document.getElementById('confirmOptimizeBtn');
                confirmBtn.onclick = () => {
                    const input = document.getElementById('aiOptimizeInput');
                    const value = input?.value.trim();
                    if (!value) {
                        // 输入框抖动动画
                        input.style.animation = 'shake 0.5s';
                        setTimeout(() => { input.style.animation = ''; }, 500);
                        return;
                    }
                    modal.remove();
                    resolve(value);
                };

                // 添加shake动画
                const style = document.createElement('style');
                style.textContent = `
                    @keyframes shake {
                        0%, 100% { transform: translateX(0); }
                        25% { transform: translateX(-10px); }
                        75% { transform: translateX(10px); }
                    }
                `;
                document.head.appendChild(style);
            });
        }

        // AI优化单页幻灯片大纲
        async function aiOptimizeSingleSlideInSlidesEditor() {
            // 从表单中获取当前数据
            const title = document.getElementById('slideTitle')?.value.trim() || '';
            const slideType = document.getElementById('slideType')?.value || 'content';
            const description = document.getElementById('slideDescription')?.value.trim() || '';

            // 获取所有内容要点
            let contentPoints = [];
            const bulletPointsContainer = document.getElementById('bulletPointsContainer');
            if (bulletPointsContainer) {
                const bulletPointItems = bulletPointsContainer.querySelectorAll('.bullet-point-item');
                contentPoints = Array.from(bulletPointItems).map(item => {
                    const textElement = item.querySelector('.bullet-point-text');
                    return textElement ? textElement.textContent.trim() : '';
                }).filter(point => point);
            }

            if (!title) {
                showNotification('请先输入页面标题', 'warning');
                return;
            }

            // 显示美化的优化需求输入弹窗
            let userRequest;
            try {
                userRequest = await showAIOptimizeModal({
                    title: `AI优化 - 第${currentSlideIndex + 1}页`,
                    subtitle: '让AI帮助您优化这一页的内容',
                    currentInfo: `<strong>标题：</strong>${title}<br><strong>类型：</strong>${slideType}<br><strong>内容要点：</strong>${contentPoints.length}个`,
                    suggestions: [
                        '增加更多技术细节和实例',
                        '简化内容，突出核心要点',
                        '优化逻辑结构，使内容更连贯',
                        '增强说服力，添加数据支撑',
                        '丰富表达方式，提升专业度'
                    ]
                });
            } catch (e) {
                return; // 用户取消
            }

            if (!userRequest || !userRequest.trim()) {
                return;
            }

            // 显示加载提示
            showNotification('AI正在优化第' + (currentSlideIndex + 1) + '页...', 'info');

            try {
                // 使用项目大纲数据
                if (!projectOutline || !projectOutline.slides) {
                    throw new Error('大纲数据不存在');
                }

                const outlineContent = JSON.stringify(projectOutline);

                // 调用AI优化接口
                const response = await fetch('/api/ai/optimize-outline', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        outline_content: outlineContent,
                        user_request: userRequest.trim(),
                        language: projectOutline?.metadata?.language || 'zh',
                        project_info: {
                            topic: projectOutline.title || '未知',
                            scenario: projectOutline.metadata?.scenario || '通用',
                            target_audience: getTargetAudience(projectOutline)
                        },
                        optimization_type: 'single',
                        slide_index: currentSlideIndex
                    })
                });

                const result = await response.json();

                if (result.success && result.optimized_content) {
                    // 解析优化后的单页数据
                    const optimizedSlide = JSON.parse(result.optimized_content);

                    // 更新弹窗中的表单
                    document.getElementById('slideTitle').value = optimizedSlide.title || '';
                    document.getElementById('slideType').value = optimizedSlide.slide_type || 'content';
                    document.getElementById('slideDescription').value = optimizedSlide.description || '';

                    // 更新内容要点
                    const container = document.getElementById('bulletPointsContainer');
                    if (container && optimizedSlide.content_points && optimizedSlide.content_points.length > 0) {
                        // 清空现有内容
                        container.innerHTML = '';

                        // 添加优化后的要点
                        optimizedSlide.content_points.forEach((point, index) => {
                            const pointDiv = document.createElement('div');
                            pointDiv.className = 'bullet-point-item';
                            pointDiv.setAttribute('data-index', index);
                            pointDiv.style.cssText = 'display: flex; align-items: flex-start; margin-bottom: 8px; padding: 8px; border-radius: 4px; transition: all 0.2s ease; position: relative;';
                            pointDiv.innerHTML = `
                                <span style="color: #666; margin-right: 8px; font-weight: bold; min-width: 20px;">•</span>
                                <div style="flex: 1; position: relative;">
                                    <div class="bullet-point-text" contenteditable="true" style="outline: none; min-height: 20px; line-height: 1.4; word-wrap: break-word;">${point}</div>
                                </div>
                            `;
                            container.appendChild(pointDiv);
                        });
                    }

                    showNotification('✅ AI优化完成，请检查后保存', 'success');

                } else {
                    // 显示详细的错误信息
                    let errorMsg = result.error || '未知错误';
                    if (result.extracted_json) {
                        console.error('提取的JSON:', result.extracted_json);
                    }
                    if (result.raw_response) {
                        console.error('AI原始响应:', result.raw_response);
                    }
                    showNotification('AI优化失败: ' + errorMsg, 'error');
                }

            } catch (error) {
                console.error('AI优化失败:', error);
                showNotification('AI优化失败: ' + error.message, 'error');
            }
        }

