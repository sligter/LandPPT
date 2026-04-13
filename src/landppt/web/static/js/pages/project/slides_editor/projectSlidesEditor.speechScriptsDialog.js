        function getSpeechLanguage() {
            const el = document.getElementById('speechLanguage');
            if (el && el.value) {
                currentSpeechLanguage = el.value;
            }
            return currentSpeechLanguage || 'zh';
        }

        let narrationAudioEl = null;
        let narrationAutoNext = true;
        let narrationCurrentIndex = 0;
        let narrationIsPlaying = false;
        let narrationTtsProvider = 'edge_tts';
        let narrationReferenceAudioPath = null;

        function showSpeechScriptDialog() {
            if (speechScriptModal) {
                document.body.removeChild(speechScriptModal);
            }

            speechScriptModal = document.createElement('div');
            speechScriptModal.className = 'modal fade show';
            speechScriptModal.style.display = 'flex';
            speechScriptModal.style.alignItems = 'center';
            speechScriptModal.style.justifyContent = 'center';
            speechScriptModal.style.position = 'fixed';
            speechScriptModal.style.top = '0';
            speechScriptModal.style.left = '0';
            speechScriptModal.style.width = '100%';
            speechScriptModal.style.height = '100%';
            speechScriptModal.style.backgroundColor = 'rgba(0,0,0,0.5)';
            speechScriptModal.style.zIndex = '20000';
            speechScriptModal.innerHTML = `
                <div class="speech-modal-dialog" style="max-width: 88vw; width: 960px;">
                    <div class="speech-modal-content">
                        <div class="speech-modal-header">
                            <div class="speech-modal-title">
                                <div class="speech-modal-icon">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path d="M12 2C13.1 2 14 2.9 14 4V12C14 13.1 13.1 14 12 14C10.9 14 10 13.1 10 12V4C10 2.9 10.9 2 12 2Z" fill="currentColor"/>
                                        <path d="M19 10V12C19 15.87 15.87 19 12 19C8.13 19 5 15.87 5 12V10H7V12C7 14.76 9.24 17 12 17C14.76 17 17 14.76 17 12V10H19Z" fill="currentColor"/>
                                        <path d="M10 21H14V23H10V21Z" fill="currentColor"/>
                                    </svg>
                                </div>
                                <span>生成演讲稿</span>
                            </div>
                            <button type="button" class="speech-modal-close" onclick="closeSpeechScriptDialog()">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </button>
                        </div>
                        <div class="speech-modal-body">
                            <!-- Generation Type Selection -->
                            <div class="speech-section">
                                <h6 class="speech-section-title">生成范围</h6>
                                <div class="speech-generation-type-group">
                                    <div class="speech-type-option">
                                        <input type="radio" name="generationType" id="singleSlide" value="single" checked>
                                        <label for="singleSlide" class="speech-type-label">
                                            <div class="speech-type-icon">
                                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                                    <path d="M14 2H6C4.9 2 4 2.9 4 4V20C4 21.1 4.89 22 5.99 22H18C19.1 22 20 21.1 20 20V8L14 2Z" stroke="currentColor" stroke-width="2" fill="none"/>
                                                    <path d="M14 2V8H20" stroke="currentColor" stroke-width="2" fill="none"/>
                                                </svg>
                                            </div>
                                            <div class="speech-type-text">
                                                <div class="speech-type-title">当前页</div>
                                                <div class="speech-type-desc">为当前选中的幻灯片生成演讲稿</div>
                                            </div>
                                        </label>
                                    </div>

                                    <div class="speech-type-option">
                                        <input type="radio" name="generationType" id="multiSlide" value="multi">
                                        <label for="multiSlide" class="speech-type-label">
                                            <div class="speech-type-icon">
                                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                                    <path d="M15 2H6C4.9 2 4 2.9 4 4V20C4 21.1 4.89 22 5.99 22H18C19.1 22 20 21.1 20 20V9L15 2Z" stroke="currentColor" stroke-width="2" fill="none"/>
                                                    <path d="M15 2V9H20" stroke="currentColor" stroke-width="2" fill="none"/>
                                                    <path d="M9 2H8C6.9 2 6 2.9 6 4V18C6 19.1 6.89 20 7.99 20H11" stroke="currentColor" stroke-width="1.5" fill="none" opacity="0.6"/>
                                                </svg>
                                            </div>
                                            <div class="speech-type-text">
                                                <div class="speech-type-title">多页选择</div>
                                                <div class="speech-type-desc">选择多个幻灯片生成演讲稿</div>
                                            </div>
                                        </label>
                                    </div>

                                    <div class="speech-type-option">
                                        <input type="radio" name="generationType" id="fullPresentation" value="full">
                                        <label for="fullPresentation" class="speech-type-label">
                                            <div class="speech-type-icon">
                                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                                    <path d="M3 3V21H21V3H3Z" stroke="currentColor" stroke-width="2" fill="none"/>
                                                    <path d="M9 9L15 15M15 9L9 15" stroke="currentColor" stroke-width="1.5" opacity="0.4"/>
                                                    <path d="M7 1V5M17 1V5M1 7H23" stroke="currentColor" stroke-width="2"/>
                                                </svg>
                                            </div>
                                            <div class="speech-type-text">
                                                <div class="speech-type-title">全部幻灯片</div>
                                                <div class="speech-type-desc">为整个演示生成完整演讲稿</div>
                                            </div>
                                        </label>
                                    </div>
                                </div>
                            </div>

                            <!-- Multi-slide Selection (hidden by default) -->
                            <div id="multiSlideSelection" class="speech-section" style="display: none;">
                                <h6 class="speech-section-title">选择幻灯片</h6>
                                <div class="slide-selection-grid" id="slideSelectionGrid"></div>
                            </div>

                            <!-- Customization Options -->
                            <div class="speech-section">
                                <h6 class="speech-section-title">自定义选项</h6>
                                <div class="speech-config-grid">
                                    <div class="speech-config-card">
                                        <div class="speech-config-title">语言</div>
                                        <div class="speech-config-description">默认中文，可切换生成英文演讲稿。</div>
                                        <div class="speech-config-control">
                                            <select class="speech-form-select" id="speechLanguage">
                                                <option value="zh" selected>中文</option>
                                                <option value="en">English</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div class="speech-config-card">
                                        <div class="speech-config-title">语调风格</div>
                                        <div class="speech-config-control">
                                            <select class="speech-form-select" id="speechTone" onchange="toggleCustomToneInput()">
                                                <option value="conversational">对话式</option>
                                                <option value="formal">正式</option>
                                                <option value="casual">轻松</option>
                                                <option value="persuasive">说服性</option>
                                                <option value="educational">教学式</option>
                                                <option value="authoritative">权威式</option>
                                                <option value="storytelling">叙事性</option>
                                                <option value="custom">自定义</option>
                                            </select>
                                            <div id="customToneContainer" class="speech-config-extra" style="display: none;">
                                                <input type="text" class="speech-form-input" id="customTone"
                                                       placeholder="请描述您希望的语调风格，例如：幽默风趣、严肃专业、温和亲切等...">
                                            </div>
                                        </div>
                                    </div>

                                    <div class="speech-config-card">
                                        <div class="speech-config-title">目标受众</div>
                                        <div class="speech-config-control">
                                            <select class="speech-form-select" id="targetAudience" onchange="toggleCustomAudienceInput()">
                                                <option value="general_public">普通大众</option>
                                                <option value="executives">企业高管</option>
                                                <option value="students">学生</option>
                                                <option value="technical_experts">技术专家</option>
                                                <option value="colleagues">同事</option>
                                                <option value="clients">客户</option>
                                                <option value="investors">投资者</option>
                                                <option value="custom">自定义</option>
                                            </select>
                                            <div id="customAudienceContainer" class="speech-config-extra" style="display: none;">
                                                <input type="text" class="speech-form-input" id="customAudience"
                                                       placeholder="请描述您的目标受众，例如：中小企业主、医疗从业者、教育工作者等...">
                                            </div>
                                        </div>
                                    </div>

                                    <div class="speech-config-card">
                                        <div class="speech-config-title">语言复杂度</div>
                                        <div class="speech-config-control">
                                            <select class="speech-form-select" id="languageComplexity">
                                                <option value="moderate">适中</option>
                                                <option value="simple">简单</option>
                                                <option value="advanced">高级</option>
                                            </select>
                                        </div>
                                    </div>

                                    <div class="speech-config-card">
                                        <div class="speech-config-title">演讲节奏</div>
                                        <div class="speech-config-control">
                                            <select class="speech-form-select" id="speakingPace">
                                                <option value="normal">正常</option>
                                                <option value="slow">缓慢</option>
                                                <option value="fast">快速</option>
                                            </select>
                                        </div>
                                    </div>

                                    <div class="speech-config-card">
                                        <div class="speech-config-title">过渡语句</div>
                                        <div class="speech-config-description">生成内容时自动添加段落衔接提示。</div>
                                        <div class="speech-form-check">
                                            <input type="checkbox" id="includeTransitions" checked>
                                            <label for="includeTransitions" class="speech-checkbox-label">
                                                <span class="speech-checkbox-custom"></span>
                                                包含过渡语句
                                            </label>
                                        </div>
                                    </div>

                                    <div class="speech-config-card speech-config-card-full">
                                        <div class="speech-config-title">自定义风格要求（可选）</div>
                                        <div class="speech-config-control">
                                            <textarea class="speech-form-textarea" id="customStylePrompt" rows="3"
                                                      placeholder="例如：使用更多的数据支撑，增加互动问题，保持幽默感等..."></textarea>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="speech-modal-footer">
                            <button type="button" class="speech-btn speech-btn-outline" onclick="showCurrentSpeechScripts()">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M1 12S5 4 12 4s11 8 11 8-4 8-11 8S1 12 1 12z" stroke="currentColor" stroke-width="2"/>
                                    <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>
                                </svg>
                                查看演讲稿
                            </button>
                            <button type="button" class="speech-btn speech-btn-secondary" onclick="closeSpeechScriptDialog()">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                取消
                            </button>
                            <button type="button" class="speech-btn speech-btn-primary" onclick="generateSpeechScript()">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                                    <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                                    <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                                </svg>
                                生成演讲稿
                            </button>
                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(speechScriptModal);

            // Close modal when clicking on the backdrop only
            speechScriptModal.addEventListener('click', function (e) {
                // Only close if clicking directly on the modal backdrop, not on child elements
                if (e.target === speechScriptModal) {
                    closeSpeechScriptDialog();
                }
            });

            // Prevent modal content from closing the modal
            const modalContent = speechScriptModal.querySelector('.speech-modal-content');
            if (modalContent) {
                modalContent.addEventListener('click', function (e) {
                    e.stopPropagation();
                });
            }

            // Initialize the dialog
            initializeSpeechScriptDialog();
        }

        function initializeSpeechScriptDialog() {
            // Handle generation type changes
            const typeRadios = document.querySelectorAll('input[name="generationType"]');
            typeRadios.forEach(radio => {
                radio.addEventListener('change', function () {
                    const multiSlideSelection = document.getElementById('multiSlideSelection');
                    if (this.value === 'multi') {
                        multiSlideSelection.style.display = 'block';
                        populateSlideSelection();
                    } else {
                        multiSlideSelection.style.display = 'none';
                    }
                });
            });
        }

        function populateSlideSelection() {
            const grid = document.getElementById('slideSelectionGrid');
            if (!grid || !slidesData) return;

            grid.innerHTML = '';

            slidesData.forEach((slide, index) => {
                const slideItem = document.createElement('div');
                slideItem.className = 'slide-selection-item';
                slideItem.innerHTML = `
                    <input class="slide-selection-checkbox" type="checkbox" id="slide_${index}" value="${index}">
                    <label class="slide-selection-card" for="slide_${index}">
                        <span class="slide-selection-indicator" aria-hidden="true"></span>
                        <div class="slide-selection-meta">
                            <span class="slide-selection-title">第${index + 1}页</span>
                            <span class="slide-selection-subtitle">${slide.title || '无标题'}</span>
                        </div>
                    </label>
                `;
                grid.appendChild(slideItem);
            });
        }

        function closeSpeechScriptDialog() {
            if (speechScriptModal) {
                stopNarrationPlayback();
                document.body.removeChild(speechScriptModal);
                speechScriptModal = null;
            }
        }

        function startProgressTracking(taskId, progressToast, totalSlides) {
            let lastProgress = 0;
            let checkCount = 0;
            const maxChecks = 300; // Maximum 5 minutes of tracking

            const interval = setInterval(async () => {
                checkCount++;

                try {
                    const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts/progress/${taskId}`, {
                        credentials: 'same-origin'
                    });
                    const result = await response.json();

                    console.log(`Progress check ${checkCount}:`, result);

                    if (result.success && result.progress) {
                        const progress = result.progress;
                        const percentage = progress.progress_percentage;

                        // Update progress toast
                        updateProgressToast(progressToast, progress.message, percentage);

                        // Check if completed or failed
                        if (progress.status === 'completed') {
                            clearInterval(interval);
                            updateProgressToast(progressToast, progress.message, 100);

                            // Close progress toast and start polling for data
                            setTimeout(() => {
                                closeProgressToast(progressToast);
                                showNotification('演讲稿生成完成！', 'success');

                                // 使用轮询机制等待数据库数据可用
                                console.log('Starting to poll for speech scripts...');
                                pollForSpeechScripts();
                            }, 500);

                        } else if (progress.status === 'failed') {
                            clearInterval(interval);
                            closeProgressToast(progressToast);
                            showNotification(`生成失败: ${progress.message}`, 'error');
                        }

                        lastProgress = percentage;
                    } else {
                        // Task not found or error, stop tracking
                        clearInterval(interval);
                        console.warn('Progress tracking failed, task not found');
                        closeProgressToast(progressToast);
                        showNotification('进度跟踪失败，请刷新页面查看结果', 'warning');
                    }
                } catch (error) {
                    console.error('Progress tracking error:', error);

                    // If too many errors or max checks reached, stop tracking
                    if (checkCount >= maxChecks) {
                        clearInterval(interval);
                        closeProgressToast(progressToast);
                        showNotification('进度跟踪超时，请刷新页面查看结果', 'warning');
                    }
                }
            }, 1000); // Check every second

            return interval;
        }

        function startSingleScriptProgressTracking(taskId, progressToast, slideIndex) {
            let checkCount = 0;
            const maxChecks = 60; // Maximum 1 minute of tracking

            const interval = setInterval(async () => {
                checkCount++;

                try {
                    const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts/progress/${taskId}`, {
                        credentials: 'same-origin'
                    });
                    const result = await response.json();

                    console.log(`Single script progress check ${checkCount}:`, result);

                    if (result.success && result.progress) {
                        const progress = result.progress;
                        const percentage = progress.progress_percentage;

                        // Update progress toast
                        updateProgressToast(progressToast, progress.message, percentage);

                        // Check if completed or failed
                        if (progress.status === 'completed') {
                            clearInterval(interval);
                            updateProgressToast(progressToast, `第${slideIndex + 1}页演讲稿重新生成完成！`, 100);

                            // Close progress toast and refresh display
                            setTimeout(() => {
                                closeProgressToast(progressToast);
                                showNotification(`第${slideIndex + 1}页演讲稿已更新`, 'success');

                                // 刷新当前弹窗显示
                                setTimeout(() => {
                                    showCurrentSpeechScripts();
                                }, 1000);
                            }, 1500);

                        } else if (progress.status === 'failed') {
                            clearInterval(interval);
                            closeProgressToast(progressToast);
                            showNotification(`第${slideIndex + 1}页重新生成失败: ${progress.message}`, 'error');
                        }

                    } else {
                        // Task not found or error, stop tracking
                        clearInterval(interval);
                        console.warn('Single script progress tracking failed, task not found');
                        closeProgressToast(progressToast);
                        showNotification('进度跟踪失败，请刷新页面查看结果', 'warning');
                    }
                } catch (error) {
                    console.error('Single script progress tracking error:', error);

                    // If too many errors or max checks reached, stop tracking
                    if (checkCount >= maxChecks) {
                        clearInterval(interval);
                        closeProgressToast(progressToast);
                        showNotification('进度跟踪超时，请刷新页面查看结果', 'warning');
                    }
                }
            }, 1000); // Check every second

            return interval;
        }

        async function generateSpeechScript() {
            try {
                // Get generation type
                const generationType = document.querySelector('input[name="generationType"]:checked').value;

                // Get slide indices based on type
                let slideIndices = [];
                if (generationType === 'single') {
                    slideIndices = [currentSlideIndex];
                } else if (generationType === 'multi') {
                    const checkedBoxes = document.querySelectorAll('#slideSelectionGrid input[type="checkbox"]:checked');
                    slideIndices = Array.from(checkedBoxes).map(cb => parseInt(cb.value));

                    if (slideIndices.length === 0) {
                        showNotification('请至少选择一页幻灯片', 'warning');
                        return;
                    }
                } else if (generationType === 'full') {
                    slideIndices = Array.from({ length: slidesData.length }, (_, i) => i);
                }

                // Show progress toast
                const progressToast = showProgressToast('正在生成演讲稿...', 0);
                let progressInterval = null;

                // Get customization options
                const languageValue = (document.getElementById('speechLanguage')?.value || 'zh');
                currentSpeechLanguage = languageValue;

                const toneValue = document.getElementById('speechTone').value;
                const audienceValue = document.getElementById('targetAudience').value;

                const customization = {
                    tone: toneValue === 'custom' ? 'conversational' : toneValue,
                    target_audience: audienceValue === 'custom' ? 'general_public' : audienceValue,
                    language_complexity: document.getElementById('languageComplexity').value,
                    speaking_pace: document.getElementById('speakingPace').value,
                    include_transitions: document.getElementById('includeTransitions').checked,
                    custom_style_prompt: document.getElementById('customStylePrompt').value.trim() || null
                };

                // Add custom tone if specified
                if (toneValue === 'custom') {
                    const customTone = document.getElementById('customTone').value.trim();
                    if (customTone) {
                        customization.custom_tone = customTone;
                        // Append to custom style prompt
                        const existingPrompt = customization.custom_style_prompt || '';
                        customization.custom_style_prompt = existingPrompt ?
                            `${existingPrompt}。语调风格：${customTone}` :
                            `语调风格：${customTone}`;
                    } else {
                        showNotification('请输入自定义语调风格描述', 'warning');
                        return;
                    }
                }

                // Add custom audience if specified
                if (audienceValue === 'custom') {
                    const customAudience = document.getElementById('customAudience').value.trim();
                    if (customAudience) {
                        customization.custom_audience = customAudience;
                        // Append to custom style prompt
                        const existingPrompt = customization.custom_style_prompt || '';
                        customization.custom_style_prompt = existingPrompt ?
                            `${existingPrompt}。目标受众：${customAudience}` :
                            `目标受众：${customAudience}`;
                    } else {
                        showNotification('请输入自定义目标受众描述', 'warning');
                        return;
                    }
                }

                // Close the dialog
                closeSpeechScriptDialog();

                // Show progress with detailed info for full generation
                let progressMessage = '正在生成演讲稿...';
                if (generationType === 'full') {
                    progressMessage = `正在生成全部演讲稿 (共${slideIndices.length}页)...`;
                } else if (generationType === 'multi') {
                    progressMessage = `正在生成演讲稿 (共${slideIndices.length}页)...`;
                }

                // Update progress toast message
                updateProgressToast(progressToast, progressMessage, 0);

                // Make API request
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-script/generate`, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        generation_type: generationType,
                        slide_indices: slideIndices,
                        customization: customization,
                        language: (document.getElementById('speechLanguage')?.value || 'zh')
                    })
                });

                const result = await response.json();

                if (result.success && result.task_id) {
                    console.log('Starting progress tracking for task:', result.task_id);
                    // Start progress tracking immediately
                    progressInterval = startProgressTracking(result.task_id, progressToast, slideIndices.length);
                } else {
                    closeProgressToast(progressToast);
                    showNotification(`演讲稿生成失败: ${result.error || '未知错误'}`, 'error');
                }

            } catch (error) {
                console.error('Speech script generation error:', error);

                // Clear progress tracking
                if (progressInterval) {
                    clearInterval(progressInterval);
                }
                closeProgressToast(progressToast);

                showNotification('演讲稿生成失败，请稍后重试', 'error');
            } finally {
                // Close speech script dialog
                closeSpeechScriptDialog();
            }
        }

