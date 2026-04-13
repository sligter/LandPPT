        async function enhanceAllBulletPoints() {
            const bulletPointsContainer = document.getElementById('bulletPointsContainer');
            if (!bulletPointsContainer) {
                showNotification('找不到要点容器', 'error');
                return;
            }

            const bulletPointItems = bulletPointsContainer.querySelectorAll('.bullet-point-item');
            if (bulletPointItems.length === 0) {
                showNotification('没有要点可以增强', 'warning');
                return;
            }

            // 收集所有要点的原始内容
            const originalPoints = [];
            bulletPointItems.forEach((item, index) => {
                const textElement = item.querySelector('.bullet-point-text');
                const text = textElement ? textElement.textContent.trim() : '';
                if (text) {
                    originalPoints.push({
                        index: index,
                        text: text,
                        element: textElement
                    });
                }
            });

            if (originalPoints.length === 0) {
                showNotification('没有有效的要点内容可以增强', 'warning');
                return;
            }

            // 显示加载状态
            const enhanceAllBtn = event.target;
            const originalBtnContent = enhanceAllBtn.innerHTML;
            enhanceAllBtn.disabled = true;
            enhanceAllBtn.style.opacity = '0.6';
            enhanceAllBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>正在增强...</span>';

            try {
                // 获取当前幻灯片和项目信息
                const currentSlide = slidesData[currentSlideIndex];
                let slideOutline = null;
                if (projectOutline && projectOutline.slides && projectOutline.slides[currentSlideIndex]) {
                    slideOutline = projectOutline.slides[currentSlideIndex];
                }

                // 构建AI增强请求
                const enhanceRequest = {
                    slideIndex: currentSlideIndex + 1,
                    slideTitle: currentSlide.title || `第${currentSlideIndex + 1}页`,
                    slideContent: currentSlide.html_content,
                    userRequest: `请增强和优化以下所有要点，使它们更加详细、准确和有吸引力。保持每个要点的核心意思不变，但可以添加更多细节、使用更好的表达方式或提供更具体的描述。要点之间应该保持逻辑连贯性和风格一致性。`,
                    slideOutline: slideOutline,
                    projectInfo: {
                        title: window.landpptEditorProjectInfo.title,
                        topic: window.landpptEditorProjectInfo.topic,
                        scenario: window.landpptEditorProjectInfo.scenario
                    },
                    contextInfo: {
                        allBulletPoints: originalPoints.map(p => p.text),
                        totalPoints: originalPoints.length
                    }
                };

                // 发送AI增强请求
                const response = await fetch('/api/ai/enhance-all-bullet-points', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(enhanceRequest)
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const result = await response.json();

                if (result.success && result.enhancedPoints && Array.isArray(result.enhancedPoints)) {
                    // 显示增强结果的确认对话框
                    showAllBulletPointsEnhancementDialog(originalPoints, result.enhancedPoints);
                } else {
                    throw new Error(result.error || result.message || '增强失败');
                }

            } catch (error) {
                showNotification('AI增强失败：' + error.message, 'error');
            } finally {
                // 恢复按钮状态
                enhanceAllBtn.disabled = false;
                enhanceAllBtn.style.opacity = '1';
                enhanceAllBtn.innerHTML = originalBtnContent;
            }
        }

        // 键盘事件处理
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                if (document.getElementById('bulletPointEnhancementDialog')) {
                    closeBulletPointEnhancementDialog();
                } else if (document.getElementById('imageSelectMenu').style.display === 'flex') {
                    closeImageSelectMenu();
                } else if (document.getElementById('imageLibraryOverlay').style.display === 'flex') {
                    closeImageLibrary();
                } else if (currentPreviewImage) {
                    closeImagePreview();
                }
            }
        });

        // 显示所有要点增强结果对话框
        function showAllBulletPointsEnhancementDialog(originalPoints, enhancedPoints) {
            // 创建对话框
            const dialog = document.createElement('div');
            dialog.id = 'bulletPointEnhancementDialog';
            dialog.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.6);
                z-index: 10002;
                display: flex;
                justify-content: center;
                align-items: center;
                backdrop-filter: blur(5px);
            `;

            const dialogContent = document.createElement('div');
            dialogContent.style.cssText = `
                background: white;
                border-radius: 12px;
                padding: 30px;
                width: 95vw;
                max-width: 1000px;
                max-height: 85vh;
                overflow-y: auto;
                position: relative;
                box-shadow: 0 20px 40px rgba(0,0,0,0.3);
                animation: slideInUp 0.3s ease;
            `;

            // 构建对比内容
            let comparisonContent = '';
            const maxLength = Math.max(originalPoints.length, enhancedPoints.length);

            for (let i = 0; i < maxLength; i++) {
                const original = originalPoints[i] ? originalPoints[i].text : '';
                const enhanced = enhancedPoints[i] ? cleanAIContent(enhancedPoints[i]) : '';

                if (original || enhanced) {
                    comparisonContent += `
                        <div style="margin-bottom: 25px; border: 1px solid #e9ecef; border-radius: 8px; overflow: hidden;">
                            <div style="background: #f8f9fa; padding: 10px 15px; border-bottom: 1px solid #e9ecef; font-weight: bold; color: #495057;">
                                要点 ${i + 1}
                            </div>
                            <div style="padding: 15px;">
                                <div style="margin-bottom: 15px;">
                                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #dc3545; font-size: 13px;">原始内容：</label>
                                    <div style="background: #fff5f5; padding: 12px; border-radius: 6px; border-left: 3px solid #dc3545; font-size: 14px; line-height: 1.4; min-height: 20px;">
                                        ${original || '<em style="color: #999;">无内容</em>'}
                                    </div>
                                </div>
                                <div>
                                    <label style="font-weight: bold; display: block; margin-bottom: 8px; color: #28a745; font-size: 13px;">AI增强后：</label>
                                    <div style="background: #f0fff4; padding: 12px; border-radius: 6px; border-left: 3px solid #28a745; font-size: 14px; line-height: 1.4; min-height: 20px;">
                                        ${enhanced || '<em style="color: #999;">无增强内容</em>'}
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }
            }

            dialogContent.innerHTML = `
                <style>
                    @keyframes slideInUp {
                        from {
                            opacity: 0;
                            transform: translateY(30px);
                        }
                        to {
                            opacity: 1;
                            transform: translateY(0);
                        }
                    }
                </style>
                <h4 style="margin: 0 0 25px 0; color: #2c3e50; display: flex; align-items: center; gap: 10px;">
                    <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 50%; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; font-size: 16px;">🪄</span>
                    AI要点增强结果 (共 ${maxLength} 个要点)
                </h4>

                <div style="margin-bottom: 30px;">
                    ${comparisonContent}
                </div>

                <div style="text-align: right; display: flex; gap: 15px; justify-content: flex-end; border-top: 1px solid #e9ecef; padding-top: 20px;">
                    <button onclick="closeBulletPointEnhancementDialog()"
                            style="background: #6c757d; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; transition: all 0.3s ease;">
                        <i class="fas fa-times"></i> 取消
                    </button>
                    <button onclick="applyAllBulletPointsEnhancement()"
                            style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; transition: all 0.3s ease; box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);">
                        <i class="fas fa-check"></i> 应用所有增强
                    </button>
                </div>
            `;

            dialog.appendChild(dialogContent);
            document.body.appendChild(dialog);

            // 存储增强结果供后续使用
            dialog._enhancedPoints = enhancedPoints;
            dialog._originalPoints = originalPoints;

            // 点击遮罩关闭
            dialog.addEventListener('click', (e) => {
                if (e.target === dialog) {
                    closeBulletPointEnhancementDialog();
                }
            });
        }

        // 关闭要点增强对话框
        function closeBulletPointEnhancementDialog() {
            const dialog = document.getElementById('bulletPointEnhancementDialog');
            if (dialog) {
                document.body.removeChild(dialog);
            }
        }

        // 清理AI返回的内容，移除无关的开场白和格式标记
        function cleanAIContent(content) {
            if (!content) return '';

            // 移除常见的开场白模式
            const unwantedPatterns = [
                /^好的[，,。.]*.*?[。.]/,
                /^作为.*?专家[，,。.]*.*?[。.]/,
                /^我将.*?[。.]/,
                /^我会.*?[。.]/,
                /^以下是.*?[：:]/,
                /^根据.*?[：:]/,
                /^请注意.*?[：:]/,
                /^需要说明.*?[：:]/,
                /^增强后的要点.*?[：:]/,
                /^优化后的.*?[：:]/,
                /^改进后的.*?[：:]/
            ];

            let cleaned = content.trim();

            // 应用清理模式
            unwantedPatterns.forEach(pattern => {
                cleaned = cleaned.replace(pattern, '');
            });

            // 移除开头的编号和符号
            cleaned = cleaned.replace(/^[\d\s\.\-\*\•\·\→\▪\▫]+/, '').trim();

            return cleaned;
        }

        // 应用所有要点增强
        function applyAllBulletPointsEnhancement() {
            const dialog = document.getElementById('bulletPointEnhancementDialog');
            if (!dialog || !dialog._enhancedPoints || !dialog._originalPoints) {
                showNotification('无法获取增强结果', 'error');
                return;
            }

            const enhancedPoints = dialog._enhancedPoints;
            const originalPoints = dialog._originalPoints;
            const bulletPointsContainer = document.getElementById('bulletPointsContainer');

            if (!bulletPointsContainer) {
                showNotification('找不到要点容器', 'error');
                return;
            }

            let appliedCount = 0;

            // 更新现有要点，并清理内容
            originalPoints.forEach((originalPoint, index) => {
                if (enhancedPoints[index] && originalPoint.element) {
                    const cleanedContent = cleanAIContent(enhancedPoints[index]);
                    if (cleanedContent && cleanedContent.length >= 5) {
                        originalPoint.element.textContent = cleanedContent;
                        appliedCount++;
                    }
                }
            });

            // 如果增强后的要点比原始要点多，添加新要点
            if (enhancedPoints.length > originalPoints.length) {
                for (let i = originalPoints.length; i < enhancedPoints.length; i++) {
                    if (enhancedPoints[i]) {
                        const cleanedContent = cleanAIContent(enhancedPoints[i]);
                        if (cleanedContent && cleanedContent.length >= 5) {
                            addNewBulletPointWithContent(cleanedContent);
                            appliedCount++;
                        }
                    }
                }
            }

            closeBulletPointEnhancementDialog();

            if (appliedCount > 0) {
                showNotification(`已成功增强 ${appliedCount} 个要点！`, 'success');
            } else {
                showNotification('没有要点被增强', 'warning');
            }
        }

        // 添加带内容的新要点（用于增强功能）
        function addNewBulletPointWithContent(content) {
            const container = document.getElementById('bulletPointsContainer');
            if (!container) return;

            // 移除空状态提示
            const emptyState = container.querySelector('.empty-bullet-points');
            if (emptyState) {
                emptyState.remove();
            }

            // 获取当前要点数量
            const existingPoints = container.querySelectorAll('.bullet-point-item');
            const newIndex = existingPoints.length;

            // 创建新要点元素
            const newBulletPoint = document.createElement('div');
            newBulletPoint.className = 'bullet-point-item';
            newBulletPoint.setAttribute('data-index', newIndex);
            newBulletPoint.style.cssText = `
                display: flex;
                align-items: flex-start;
                margin-bottom: 8px;
                padding: 8px;
                border-radius: 4px;
                transition: all 0.2s ease;
                position: relative;
            `;

            newBulletPoint.innerHTML = `
                <span style="color: #666; margin-right: 8px; font-weight: bold; min-width: 20px;">•</span>
                <div style="flex: 1; position: relative;">
                    <div class="bullet-point-text" contenteditable="true"
                         style="outline: none; min-height: 20px; line-height: 1.4; word-wrap: break-word;">${content}</div>
                </div>
                <button class="delete-bullet-btn" onclick="deleteBulletPoint(${newIndex})"
                        style="background: #dc3545; color: white; border: none; border-radius: 50%; width: 28px; height: 28px; cursor: pointer; margin-left: 4px; display: flex; align-items: center; justify-content: center; font-size: 12px; transition: all 0.3s ease; opacity: 0.7;"
                        title="删除此要点">
                    <i class="fas fa-trash"></i>
                </button>
            `;

            container.appendChild(newBulletPoint);
        }

        // 点击遮罩层关闭
        document.addEventListener('click', function (e) {
            if (e.target.id === 'imageSelectMenu') {
                closeImageSelectMenu();
            } else if (e.target.id === 'imageLibraryOverlay') {
                closeImageLibrary();
            } else if (e.target.id === 'imagePreviewOverlay') {
                closeImagePreview();
            }
        });

        // 添加新要点功能
        function addNewBulletPoint() {
            const container = document.getElementById('bulletPointsContainer');
            if (!container) return;

            // 移除空状态提示
            const emptyState = container.querySelector('.empty-bullet-points');
            if (emptyState) {
                emptyState.remove();
            }

            // 获取当前要点数量
            const existingPoints = container.querySelectorAll('.bullet-point-item');
            const newIndex = existingPoints.length;

            // 创建新要点元素
            const newBulletPoint = document.createElement('div');
            newBulletPoint.className = 'bullet-point-item';
            newBulletPoint.setAttribute('data-index', newIndex);
            newBulletPoint.style.cssText = `
                display: flex;
                align-items: flex-start;
                margin-bottom: 8px;
                padding: 8px;
                border-radius: 4px;
                transition: all 0.2s ease;
                position: relative;
                background: rgba(40, 167, 69, 0.1);
                border: 2px dashed #28a745;
            `;

            newBulletPoint.innerHTML = `
                <span style="color: #666; margin-right: 8px; font-weight: bold; min-width: 20px;">•</span>
                <div style="flex: 1; position: relative;">
                    <div class="bullet-point-text" contenteditable="true"
                         style="outline: none; min-height: 20px; line-height: 1.4; word-wrap: break-word; background: white; padding: 8px; border-radius: 4px; border: 1px solid #28a745;"
                         placeholder="请输入新要点内容...">
                    </div>
                </div>

                <button class="delete-bullet-btn" onclick="deleteBulletPoint(${newIndex})"
                        style="background: #dc3545; color: white; border: none; border-radius: 50%; width: 28px; height: 28px; cursor: pointer; margin-left: 4px; display: flex; align-items: center; justify-content: center; font-size: 12px; transition: all 0.3s ease; opacity: 0.7;"
                        title="删除此要点">
                    <i class="fas fa-trash"></i>
                </button>
            `;

            container.appendChild(newBulletPoint);

            // 聚焦到新要点的文本区域
            const textArea = newBulletPoint.querySelector('.bullet-point-text');
            textArea.focus();

            // 添加事件监听器
            textArea.addEventListener('blur', function () {
                // 移除新建状态样式
                newBulletPoint.style.background = '';
                newBulletPoint.style.border = '';
                textArea.style.background = '';
                textArea.style.border = '';
                textArea.style.padding = '';
            });

            textArea.addEventListener('input', function () {
                if (this.textContent.trim()) {
                    // 有内容时移除新建状态样式
                    newBulletPoint.style.background = '';
                    newBulletPoint.style.border = '';
                    textArea.style.background = '';
                    textArea.style.border = '';
                    textArea.style.padding = '';
                }
            });

            showNotification('已添加新要点，请输入内容', 'info');
        }

        // 删除要点功能
        function deleteBulletPoint(pointIndex) {
            const bulletPointItem = document.querySelector(`.bullet-point-item[data-index="${pointIndex}"]`);
            if (!bulletPointItem) return;

            const pointText = bulletPointItem.querySelector('.bullet-point-text')?.textContent.trim();
            const confirmMessage = pointText ?
                `确定要删除要点"${pointText.substring(0, 30)}${pointText.length > 30 ? '...' : ''}"吗？` :
                '确定要删除这个要点吗？';

            if (confirm(confirmMessage)) {
                bulletPointItem.remove();

                // 重新编号剩余要点
                const container = document.getElementById('bulletPointsContainer');
                const remainingPoints = container.querySelectorAll('.bullet-point-item');

                remainingPoints.forEach((item, index) => {
                    item.setAttribute('data-index', index);
                    // 更新删除按钮的onclick事件
                    const deleteBtn = item.querySelector('.delete-bullet-btn');
                    if (deleteBtn) deleteBtn.setAttribute('onclick', `deleteBulletPoint(${index})`);
                });

                // 如果没有要点了，显示空状态
                if (remainingPoints.length === 0) {
                    container.innerHTML = `
                        <div class="empty-bullet-points" style="text-align: center; color: #999; padding: 40px 20px;">
                            <i class="fas fa-list" style="font-size: 24px; margin-bottom: 10px; opacity: 0.5;"></i>
                            <p style="margin: 0;">暂无要点，点击下方按钮添加</p>
                        </div>
                    `;
                }

                showNotification('要点已删除', 'info');
            }
        }

        // 验证和修复图片URL
        function validateAndFixImageUrls() {
            uploadedImages.forEach(image => {
                // 确保URL是绝对路径
                if (image.url && !image.url.startsWith('http') && !image.url.startsWith(window.location.origin)) {
                    if (image.url.startsWith('/')) {
                        image.url = window.location.origin + image.url;
                    } else {
                        image.url = window.location.origin + '/' + image.url;
                    }
                }

                // 确保文件大小是数字
                if (typeof image.size === 'string') {
                    image.size = parseInt(image.size) || 0;
                }
            });
        }

        // 添加键盘快捷键支持
        document.addEventListener('keydown', function (e) {
            // Ctrl/Cmd + E 切换快速编辑模式
            if ((e.ctrlKey || e.metaKey) && e.key === 'e' && !e.shiftKey && !e.altKey) {
                e.preventDefault();
                toggleQuickEditMode();
            }

            // ESC 键退出快速编辑模式
            if (e.key === 'Escape' && currentMode === 'quickedit') {
                if (currentInlineEditor) {
                    finishDirectEdit(false); // 取消编辑
                } else {
                    setMode('preview');
                }
            }
        });

        // 在页面加载完成后初始化图片上传功能
        document.addEventListener('DOMContentLoaded', function () {
            // 延迟初始化，确保所有元素都已加载
            setTimeout(() => {
                const imageUploadBtn = document.getElementById('aiImageUploadBtn');
                const inputContainer = document.querySelector('.ai-input-container');

                if (imageUploadBtn && inputContainer) {
                    if (typeof initImageUpload === 'function') {
                        initImageUpload();
                    }

                    // 验证和修复现有图片数据
                    if (typeof validateAndFixImageUrls === 'function') {
                        validateAndFixImageUrls();
                    }
                } else {
                    console.log('图片上传元素未找到:', {
                        uploadBtn: !!imageUploadBtn,
                        inputContainer: !!inputContainer
                    });
                }
            }, 100);
        });

        // Speech Script Generation Functions
        let speechScriptData = null;
        let speechScriptModal = null;
        let currentSpeechLanguage = 'zh';

