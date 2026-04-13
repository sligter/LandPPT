        function showSpeechScriptPreview(result, editMode = false) {
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

            let scriptsHtml = '';
            result.scripts.forEach((script, index) => {
                const slideTitle = script.slide_index === -1 ? '开场白' :
                    script.slide_index >= result.scripts.length - 1 && script.slide_title === '结束语' ? '结束语' :
                        script.slide_title;

                const scriptId = `script-${script.slide_index}-${index}`;
                const contentId = `content-${script.slide_index}-${index}`;
                const editId = `edit-${script.slide_index}-${index}`;

                scriptsHtml += `
                    <div class="speech-script-item" data-slide-index="${script.slide_index}" data-script-index="${index}">
                        <div class="speech-script-header">
                            <h6>${slideTitle}</h6>
                            <div class="speech-script-meta">
                                <span id="${scriptId}" class="speech-script-duration">${script.estimated_duration || '未知时长'}</span>
                            </div>
                        </div>
                        <div class="speech-script-content-wrapper">
                            <div id="${contentId}" class="speech-script-content ${editMode ? 'hidden' : ''}">${script.script_content}</div>
                            <textarea id="${editId}" class="speech-script-edit ${editMode ? '' : 'hidden'}" rows="8">${script.script_content}</textarea>
                        </div>
                        <div class="speech-script-actions">
                            <button class="speech-script-btn save-btn ${editMode ? '' : 'hidden'}" onclick="saveSpeechScript(${script.slide_index}, ${index})">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M19 21H5C4.44772 21 4 20.5523 4 20V4C4 3.44772 4.44772 3 5 3H16L20 7V20C20 20.5523 19.5523 21 19 21Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    <polyline points="9,9 9,15 15,15 15,9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                保存
                            </button>
                            <button class="speech-script-btn edit-btn ${editMode ? 'hidden' : ''}" onclick="toggleEditMode(${script.slide_index}, ${index})">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M11 4H4C3.44772 4 3 4.44772 3 5V20C3 20.5523 3.44772 21 4 21H19C19.5523 21 20 20.5523 20 20V13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M18.5 2.5C18.8978 2.10217 19.4374 1.87868 20 1.87868C20.5626 1.87868 21.1022 2.10217 21.5 2.5C21.8978 2.89783 22.1213 3.43739 22.1213 4C22.1213 4.56261 21.8978 5.10217 21.5 5.5L12 15L8 16L9 12L18.5 2.5Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                编辑
                            </button>
                            <button class="speech-script-btn speech-script-humanize-btn" onclick="humanizeSingleSpeechScript(${script.slide_index}, ${index}, this)">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M12 3L13.85 8.15L19 10L13.85 11.85L12 17L10.15 11.85L5 10L10.15 8.15L12 3Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M5 19L5.8 21.2L8 22L5.8 22.8L5 25L4.2 22.8L2 22L4.2 21.2L5 19Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" transform="translate(0 -2)"/>
                                </svg>
                                一键人话
                            </button>
                            <button class="speech-script-btn" onclick="regenerateSingleScript(${script.slide_index})">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M1 4V10H7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M23 20V14H17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M20.49 9C19.9828 7.56678 19.1209 6.28392 17.9845 5.27304C16.8482 4.26216 15.4745 3.55682 13.9917 3.21834C12.5089 2.87986 10.9652 2.91902 9.50481 3.33329C8.04437 3.74757 6.70779 4.52433 5.64 5.59L1 10M23 14L18.36 18.41C17.2922 19.4757 15.9556 20.2524 14.4952 20.6667C13.0348 21.081 11.4911 21.1201 10.0083 20.7817C8.52547 20.4432 7.1518 19.7378 6.01547 18.727C4.87913 17.7161 4.01717 16.4332 3.51 15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                重新生成
                            </button>
                            <button class="speech-script-btn speech-script-btn-danger" onclick="deleteSpeechScriptBySlide(${script.slide_index})">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M3 6H5H21" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M8 6V4C8 3.44772 8.44772 3 9 3H15C15.5523 3 16 3.44772 16 4V6M19 6V20C19 20.5523 18.4477 21 18 21H6C5.44772 21 5 20.5523 5 20V6H19Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                删除
                            </button>
                        </div>
                    </div>`;
            });

            const narrationVideoToolsPanelHtml = narrationVideoToolsEnabled ? `
                                                <div class="speech-compact-field">
                                                    <span class="speech-compact-label">视频导出</span>
                                                    <div class="speech-compact-input-stack">
                                                        <select class="speech-form-select" id="narrationFps" style="width: 120px;">
                                                            <option value="30" selected>30fps</option>
                                                            <option value="60">60fps</option>
                                                        </select>
                                                        <select class="speech-form-select" id="narrationRenderMode" style="width: 150px;" title="渲染模式">
                                                            <option value="live" selected>Live放映</option>
                                                            <option value="static">Static截图</option>
                                                        </select>
                                                        <button class="speech-btn speech-btn-outline" onclick="exportNarrationVideo()">
                                                            导出讲解视频
                                                        </button>
                                                    </div>
                                                </div>
            ` : '';

            speechScriptModal.innerHTML = `
                <div class="speech-modal-dialog" style="max-width: 90vw; width: 1200px;">
                    <div class="speech-modal-content">
                        <div class="speech-modal-header">
                            <div class="speech-modal-title">
                                <div class="speech-section-title">
                                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                                        <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                                        <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                                    </svg>
                                    演讲稿${editMode ? '编辑' : '预览'}
                                </div>
                            </div>
                            <button type="button" class="speech-modal-close" onclick="closeSpeechScriptDialog()">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </button>
                        </div>
                        <div class="speech-modal-body speech-modal-body-preview">
                            <div class="speech-modal-controls">
                                <div class="speech-toolbar-head">
                                    <div class="speech-duration-info">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                            <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
                                            <polyline points="12,6 12,12 16,14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                        <span>总预计时长: <strong>${result.total_estimated_duration || '未知'}</strong></span>
                                    </div>
                                    <div class="speech-action-group speech-control-row speech-control-row-main">
                                        <select class="speech-form-select" id="narrationLanguage" style="width: 120px;" onchange="currentSpeechLanguage=this.value">
                                            <option value="zh" selected>中文</option>
                                            <option value="en">English</option>
                                        </select>
                                        <button class="speech-btn speech-btn-outline" onclick="exportSpeechScript('docx')">
                                            导出DOCX
                                        </button>
                                        <button class="speech-btn speech-btn-outline" onclick="exportSpeechScript('markdown')">
                                            导出Markdown
                                        </button>
                                        <button class="speech-btn speech-btn-outline" onclick="openNarrationPresentation()">
                                            演示讲解
                                        </button>
                                        <button id="speechHumanizeAllBtn" class="speech-btn speech-btn-outline" onclick="humanizeAllSpeechScripts(this)">
                                            一键人话
                                        </button>
                                        <button id="speechToggleEditModeBtn" class="speech-btn ${editMode ? 'speech-btn-secondary' : 'speech-btn-primary'}" onclick="toggleAllEditMode()">
                                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                                ${editMode ?
                        '<path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' :
                        '<path d="M11 4H4C3.44772 4 3 4.44772 3 5V20C3 20.5523 3.44772 21 4 21H19C19.5523 21 20 20.5523 20 20V13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M18.5 2.5C18.8978 2.10217 19.4374 1.87868 20 1.87868C20.5626 1.87868 21.1022 2.10217 21.5 2.5C21.8978 2.89783 22.1213 3.43739 22.1213 4C22.1213 4.56261 21.8978 5.10217 21.5 5.5L12 15L8 16L9 12L18.5 2.5Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
                    }
                                            </svg>
                                            ${editMode ? '退出编辑' : '编辑'}
                                        </button>
                                        <details class="speech-compact-tools" id="speechCompactTools">
                                            <summary class="speech-compact-tools-toggle">更多工具</summary>
                                            <div class="speech-compact-panel">
                                                <div class="speech-compact-field">
                                                    <span class="speech-compact-label">播放控制</span>
                                                    <div class="speech-compact-input-stack">
                                                        <button class="speech-btn speech-btn-outline" id="narrationPlayBtn" onclick="toggleNarrationPlaybackForCurrentSlide()">
                                                            ${narrationIsPlaying ? '停止播放' : '播放当前页'}
                                                        </button>
                                                        <button class="speech-btn speech-btn-outline" onclick="toggleNarrationAutoNext()">
                                                            自动下一页: <span id="narrationAutoNextLabel">${narrationAutoNext ? '开' : '关'}</span>
                                                        </button>
                                                    </div>
                                                </div>
                                                <div class="speech-compact-field">
                                                    <span class="speech-compact-label">语音服务</span>
                                                    <select class="speech-form-select" id="narrationTtsProvider" style="width: 180px;" onchange="handleNarrationProviderChange()">
                                                        <option value="edge_tts" ${narrationTtsProvider === 'comfyuiapi' ? '' : 'selected'}>Edge-TTS</option>
                                                        <option value="comfyuiapi" ${narrationTtsProvider === 'comfyuiapi' ? 'selected' : ''}>ComfyUI Qwen3-TD</option>
                                                    </select>
                                                </div>
                                                <div class="speech-compact-field" id="speechRefAudioField" style="display: ${narrationTtsProvider === 'comfyuiapi' ? 'flex' : 'none'};">
                                                    <span class="speech-compact-label">参考音频</span>
                                                    <div id="narrationRefAudioContainer">
                                                        <input type="file" id="narrationRefAudioFile" accept="audio/*" onchange="handleNarrationRefAudioSelected(this)" />
                                                        <label class="speech-ref-audio-trigger" for="narrationRefAudioFile">选择音频</label>
                                                        <span id="narrationRefAudioStatus" class="speech-ref-audio-status">
                                                            ${narrationReferenceAudioPath ? '已上传参考音频' : '未上传参考音频'}
                                                        </span>
                                                    </div>
                                                    <span class="speech-compact-help">仅 Qwen3-TD 需要，用于提供参考音色。</span>
                                                </div>
                                                <div class="speech-compact-field">
                                                    <span class="speech-compact-label">音频准备</span>
                                                    <div class="speech-compact-input-stack">
                                                        <button class="speech-btn speech-btn-outline" onclick="generateNarrationAudio()">
                                                            生成讲解音频
                                                        </button>
                                                        <button class="speech-btn speech-btn-outline" onclick="exportNarrationAudio()">
                                                            导出讲解音频
                                                        </button>
                                                    </div>
                                                </div>
                                                ${narrationVideoToolsPanelHtml}
                                            </div>
                                        </details>
                                    </div>
                                </div>
                            </div>
                            <div class="speech-scripts-container">
                                ${scriptsHtml}
                            </div>
                        </div>
                        <div class="speech-modal-footer">
                            <button type="button" class="speech-btn speech-btn-secondary" onclick="closeSpeechScriptDialog()">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                关闭
                            </button>
                            <button type="button" class="speech-btn speech-btn-primary" onclick="regenerateSpeechScript()">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M1 4V10H7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M23 20V14H17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M20.49 9C19.9828 7.56678 19.1209 6.28392 17.9845 5.27304C16.8482 4.26216 15.4745 3.55682 13.9917 3.21834C12.5089 2.87986 10.9652 2.91902 9.50481 3.33329C8.04437 3.74757 6.70779 4.52433 5.64 5.59L1 10M23 14L18.36 18.41C17.2922 19.4757 15.9556 20.2524 14.4952 20.6667C13.0348 21.081 11.4911 21.1201 10.0083 20.7817C8.52547 20.4432 7.1518 19.7378 6.01547 18.727C4.87913 17.7161 4.01717 16.4332 3.51 15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                重新生成全部
                            </button>
                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(speechScriptModal);

            const totalDurationValue = speechScriptModal.querySelector('.speech-duration-info strong');
            if (totalDurationValue) {
                totalDurationValue.id = 'speechTotalDurationValue';
            }

            // Close modal when clicking on the backdrop
            speechScriptModal.addEventListener('click', function (e) {
                if (e.target === speechScriptModal) {
                    closeSpeechScriptDialog();
                }
            });
        }

        async function exportSpeechScript(format) {
            if (!speechScriptData) {
                showNotification('没有可导出的演讲稿数据', 'warning');
                return;
            }

            try {
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-script/export`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        export_format: format,
                        scripts_data: speechScriptData.scripts,
                        include_metadata: true
                    })
                });

                if (response.ok) {
                    // Trigger file download
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;

                    const contentDisposition = response.headers.get('Content-Disposition');
                    let filename = `${window.landpptEditorProjectInfo.topic}_演讲稿.${format === 'docx' ? 'docx' : 'md'}`;
                    if (contentDisposition) {
                        const filenameMatch = contentDisposition.match(/filename\*=UTF-8''(.+)/);
                        if (filenameMatch) {
                            filename = decodeURIComponent(filenameMatch[1]);
                        }
                    }

                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);

                    showNotification(`演讲稿已导出为 ${format.toUpperCase()} 格式`, 'success');
                } else {
                    const result = await response.json();
                    showNotification(`导出失败: ${result.error}`, 'error');
                }
            } catch (error) {
                console.error('Export error:', error);
                showNotification('导出失败，请稍后重试', 'error');
            }
        }

        function regenerateSpeechScript() {
            closeSpeechScriptDialog();
            showSpeechScriptDialog();
        }

        function parseSpeechDurationSeconds(durationText) {
            const text = String(durationText || '').trim();
            if (!text) return 0;

            if (text.includes('分钟')) {
                const minutes = parseFloat(text.replace('分钟', ''));
                return Number.isFinite(minutes) ? minutes * 60 : 0;
            }

            if (text.includes('秒')) {
                const seconds = parseFloat(text.replace('秒', ''));
                return Number.isFinite(seconds) ? seconds : 0;
            }

            return 0;
        }

        function formatSpeechDuration(seconds) {
            if (!Number.isFinite(seconds) || seconds <= 0) {
                return '未知';
            }
            if (seconds < 60) {
                return `${Math.max(1, Math.round(seconds))}秒`;
            }
            return `${(seconds / 60).toFixed(1)}分钟`;
        }

        function refreshSpeechTotalDuration() {
            const totalDurationEl = document.getElementById('speechTotalDurationValue');
            if (!totalDurationEl || !speechScriptData || !Array.isArray(speechScriptData.scripts)) {
                return;
            }

            const totalSeconds = speechScriptData.scripts.reduce((sum, script) => {
                return sum + parseSpeechDurationSeconds(script && script.estimated_duration);
            }, 0);
            totalDurationEl.textContent = formatSpeechDuration(totalSeconds);
        }

        function getSpeechScriptItemElement(slideIndex, scriptIndex) {
            return document.querySelector(`.speech-script-item[data-slide-index="${slideIndex}"][data-script-index="${scriptIndex}"]`);
        }

        function buildSpeechHumanizePayload(itemElement) {
            if (!itemElement) return null;

            const slideIndex = Number.parseInt(itemElement.dataset.slideIndex, 10);
            const scriptIndex = Number.parseInt(itemElement.dataset.scriptIndex, 10);
            if (!Number.isInteger(slideIndex) || !Number.isInteger(scriptIndex)) {
                return null;
            }

            const titleEl = itemElement.querySelector('h6');
            const contentDiv = document.getElementById(`content-${slideIndex}-${scriptIndex}`);
            const editTextarea = document.getElementById(`edit-${slideIndex}-${scriptIndex}`);
            const currentContent = editTextarea && !editTextarea.classList.contains('hidden')
                ? editTextarea.value.trim()
                : (contentDiv ? contentDiv.textContent.trim() : '');

            if (!currentContent) {
                return null;
            }

            return {
                slide_index: slideIndex,
                slide_title: titleEl ? titleEl.textContent.trim() : `第${slideIndex + 1}页`,
                script_content: currentContent
            };
        }

        function syncSpeechScriptDataEntry(script) {
            if (!speechScriptData || !Array.isArray(speechScriptData.scripts) || !script) {
                return;
            }

            const existing = speechScriptData.scripts.find(item => item.slide_index === script.slide_index);
            if (existing) {
                Object.assign(existing, script);
            }
        }

        function applyHumanizedScriptsToDialog(updatedScripts) {
            if (!Array.isArray(updatedScripts)) {
                return;
            }

            updatedScripts.forEach((script) => {
                if (!script || !Number.isInteger(script.slide_index)) {
                    return;
                }

                const itemElement = document.querySelector(`.speech-script-item[data-slide-index="${script.slide_index}"]`);
                if (!itemElement) {
                    syncSpeechScriptDataEntry(script);
                    return;
                }

                const scriptIndex = Number.parseInt(itemElement.dataset.scriptIndex, 10);
                const contentDiv = document.getElementById(`content-${script.slide_index}-${scriptIndex}`);
                const editTextarea = document.getElementById(`edit-${script.slide_index}-${scriptIndex}`);
                const durationEl = document.getElementById(`script-${script.slide_index}-${scriptIndex}`);

                if (contentDiv) {
                    contentDiv.textContent = script.script_content || '';
                }
                if (editTextarea) {
                    editTextarea.value = script.script_content || '';
                }
                if (durationEl) {
                    durationEl.textContent = script.estimated_duration || '未知时长';
                }

                syncSpeechScriptDataEntry(script);
            });

            refreshSpeechTotalDuration();
        }

        async function refreshSpeechScriptsDialogData() {
            const lang = getSpeechLanguage();
            const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts?language=${encodeURIComponent(lang)}`, {
                credentials: 'same-origin'
            });
            const result = await response.json().catch(() => ({}));

            if (!response.ok || !result.success) {
                throw new Error(result.error || `HTTP ${response.status}`);
            }

            const scripts = Array.isArray(result.scripts) ? result.scripts : [];
            if (speechScriptData && typeof speechScriptData === 'object') {
                speechScriptData.scripts = scripts;
            }
            applyHumanizedScriptsToDialog(scripts);
            return scripts;
        }

        function setSpeechActionButtonLoading(button, loadingText) {
            if (!button) return '';
            const originalHtml = button.innerHTML;
            button.disabled = true;
            button.innerHTML = loadingText;
            return originalHtml;
        }

        function restoreSpeechActionButton(button, originalHtml) {
            if (!button) return;
            button.disabled = false;
            if (typeof originalHtml === 'string' && originalHtml) {
                button.innerHTML = originalHtml;
            }
        }

        function setSpeechHumanizeButtonsDisabled(disabled) {
            document.querySelectorAll('.speech-script-humanize-btn, #speechHumanizeAllBtn').forEach((button) => {
                button.disabled = disabled;
            });
        }

        function resetSpeechHumanizeButtons(triggerButton, originalHtml) {
            setSpeechHumanizeButtonsDisabled(false);
            restoreSpeechActionButton(triggerButton, originalHtml);
        }

        function startSpeechHumanizeProgressTracking(taskId, progressToast, options = {}) {
            let checkCount = 0;
            const maxChecks = 180;
            const successMessage = options.successMessage || '演讲稿已完成一键人话';
            const failurePrefix = options.failurePrefix || '一键人话失败';
            const onFinally = typeof options.onFinally === 'function' ? options.onFinally : null;

            const runFinally = async () => {
                if (!onFinally) {
                    return;
                }
                try {
                    await onFinally();
                } catch (callbackError) {
                    console.error('Speech humanize finalize callback error:', callbackError);
                }
            };

            const interval = setInterval(async () => {
                checkCount += 1;

                try {
                    const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts/progress/${taskId}`, {
                        credentials: 'same-origin'
                    });
                    const result = await response.json().catch(() => ({}));

                    if (!response.ok || !result.success || !result.progress) {
                        clearInterval(interval);
                        closeProgressToast(progressToast);
                        await runFinally();
                        showNotification('进度跟踪失败，请刷新页面查看结果', 'warning');
                        return;
                    }

                    const progress = result.progress;
                    const percentage = Number.isFinite(progress.progress_percentage) ? progress.progress_percentage : 0;
                    updateProgressToast(progressToast, progress.message || '正在一键人话...', percentage);

                    if (progress.status === 'completed') {
                        clearInterval(interval);
                        updateProgressToast(progressToast, progress.message || successMessage, 100);

                        setTimeout(async () => {
                            closeProgressToast(progressToast);

                            let notificationMessage = progress.message || successMessage;
                            let notificationType = progress.failed_slides ? 'warning' : 'success';
                            try {
                                await refreshSpeechScriptsDialogData();
                            } catch (refreshError) {
                                console.error('Refresh speech scripts after humanize error:', refreshError);
                                notificationMessage = `一键人话已完成，但刷新结果失败: ${refreshError.message || refreshError}`;
                                notificationType = 'warning';
                            } finally {
                                await runFinally();
                            }

                            showNotification(notificationMessage, notificationType);
                        }, 600);
                        return;
                    }

                    if (progress.status === 'failed') {
                        clearInterval(interval);
                        closeProgressToast(progressToast);
                        await runFinally();
                        showNotification(`${failurePrefix}: ${progress.message || '未知错误'}`, 'error');
                    }
                } catch (error) {
                    console.error('Speech humanize progress tracking error:', error);

                    if (checkCount >= maxChecks) {
                        clearInterval(interval);
                        closeProgressToast(progressToast);
                        await runFinally();
                        showNotification('一键人话进度跟踪超时，请刷新页面查看结果', 'warning');
                    }
                }
            }, 1000);

            return interval;
        }

        async function humanizeSingleSpeechScript(slideIndex, scriptIndex, triggerButton) {
            const itemElement = getSpeechScriptItemElement(slideIndex, scriptIndex);
            const payload = buildSpeechHumanizePayload(itemElement);
            if (!payload) {
                showNotification('当前演讲稿内容为空，无法一键人话', 'warning');
                return;
            }

            const originalHtml = setSpeechActionButtonLoading(triggerButton, '人话化中...');
            setSpeechHumanizeButtonsDisabled(true);
            const progressToast = showProgressToast(`正在处理第${slideIndex + 1}页演讲稿人话化...`, 0);

            try {
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts/humanize`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        language: getSpeechLanguage(),
                        scripts: [payload]
                    })
                });
                const result = await response.json().catch(() => ({}));

                if (!response.ok || !result.success) {
                    throw new Error(result.error || `HTTP ${response.status}`);
                }

                if (!result.task_id) {
                    throw new Error(result.error || '未获取到任务ID');
                }

                startSpeechHumanizeProgressTracking(result.task_id, progressToast, {
                    successMessage: `第${slideIndex + 1}页演讲稿已完成人话化`,
                    failurePrefix: `第${slideIndex + 1}页一键人话失败`,
                    onFinally: () => resetSpeechHumanizeButtons(triggerButton, originalHtml)
                });
            } catch (error) {
                console.error('Humanize single speech script error:', error);
                closeProgressToast(progressToast);
                resetSpeechHumanizeButtons(triggerButton, originalHtml);
                showNotification(`一键人话失败: ${error.message || error}`, 'error');
            }
        }

        async function humanizeAllSpeechScripts(triggerButton) {
            const itemElements = Array.from(document.querySelectorAll('.speech-script-item'));
            const scripts = itemElements
                .map(item => buildSpeechHumanizePayload(item))
                .filter(Boolean);

            if (scripts.length === 0) {
                showNotification('没有可一键人话的演讲稿内容', 'warning');
                return;
            }

            const originalHtml = setSpeechActionButtonLoading(triggerButton, '全部人话中...');
            setSpeechHumanizeButtonsDisabled(true);
            const progressToast = showProgressToast(`正在处理${scripts.length}页演讲稿人话化...`, 0);

            try {
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts/humanize`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        language: getSpeechLanguage(),
                        scripts
                    })
                });
                const result = await response.json().catch(() => ({}));

                if (!response.ok || !result.success) {
                    throw new Error(result.error || `HTTP ${response.status}`);
                }

                if (!result.task_id) {
                    throw new Error(result.error || '未获取到任务ID');
                }

                startSpeechHumanizeProgressTracking(result.task_id, progressToast, {
                    successMessage: `已完成${scripts.length}页演讲稿一键人话`,
                    failurePrefix: '全部一键人话失败',
                    onFinally: () => resetSpeechHumanizeButtons(triggerButton, originalHtml)
                });
            } catch (error) {
                console.error('Humanize all speech scripts error:', error);
                closeProgressToast(progressToast);
                resetSpeechHumanizeButtons(triggerButton, originalHtml);
                showNotification(`全部一键人话失败: ${error.message || error}`, 'error');
            }
        }

        function toggleEditMode(slideIndex, scriptIndex, forceMode = null) {
            const contentDiv = document.getElementById(`content-${slideIndex}-${scriptIndex}`);
            const editTextarea = document.getElementById(`edit-${slideIndex}-${scriptIndex}`);
            const saveBtn = document.querySelector(`[data-slide-index="${slideIndex}"] .save-btn`);
            const editBtn = document.querySelector(`[data-slide-index="${slideIndex}"] .edit-btn`);

            // 确定当前状态
            const isCurrentlyEditing = editTextarea && !editTextarea.classList.contains('hidden');

            // 确定目标状态
            let shouldEdit;
            if (forceMode !== null) {
                shouldEdit = forceMode;
            } else {
                shouldEdit = !isCurrentlyEditing;
            }

            if (shouldEdit) {
                // 进入编辑模式
                if (contentDiv) contentDiv.classList.add('hidden');
                if (editTextarea) {
                    editTextarea.classList.remove('hidden');
                    editTextarea.focus();
                }
                if (saveBtn) saveBtn.classList.remove('hidden');
                if (editBtn) editBtn.classList.add('hidden');
            } else {
                // 退出编辑模式
                if (contentDiv) contentDiv.classList.remove('hidden');
                if (editTextarea) editTextarea.classList.add('hidden');
                if (saveBtn) saveBtn.classList.add('hidden');
                if (editBtn) editBtn.classList.remove('hidden');
            }
        }

        async function saveSpeechScript(slideIndex, scriptIndex) {
            let saveBtn = null;
            let originalText = '';
            try {
                const editTextarea = document.getElementById(`edit-${slideIndex}-${scriptIndex}`);
                const contentDiv = document.getElementById(`content-${slideIndex}-${scriptIndex}`);
                const newContent = editTextarea.value.trim();

                if (!newContent) {
                    showNotification('演讲稿内容不能为空', 'warning');
                    return;
                }

                // 显示保存中状态
                saveBtn = document.querySelector(`[data-slide-index="${slideIndex}"] .save-btn`);
                originalText = saveBtn ? saveBtn.innerHTML : '';
                saveBtn.innerHTML = '保存中...';
                saveBtn.disabled = true;

                // 调用API保存
                const lang = getSpeechLanguage();
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts/slide/${slideIndex}?language=${encodeURIComponent(lang)}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        script_content: newContent,
                        slide_title: document.querySelector(`[data-slide-index="${slideIndex}"] h6`).textContent
                    })
                });

                const result = await response.json();

                if (result.success) {
                    // 更新显示内容
                    contentDiv.textContent = newContent;
                    if (result.script) {
                        const durationEl = document.getElementById(`script-${slideIndex}-${scriptIndex}`);
                        if (durationEl) {
                            durationEl.textContent = result.script.estimated_duration || '未知时长';
                        }
                        syncSpeechScriptDataEntry(result.script);
                        refreshSpeechTotalDuration();
                    }

                    // 退出编辑模式
                    toggleEditMode(slideIndex, scriptIndex, false);

                    showNotification('演讲稿已保存', 'success');
                } else {
                    showNotification(`保存失败: ${result.error}`, 'error');
                }

            } catch (error) {
                console.error('Save speech script error:', error);
                showNotification('保存演讲稿失败', 'error');
            } finally {
                // 恢复按钮状态
                if (saveBtn) {
                    saveBtn.innerHTML = originalText;
                    saveBtn.disabled = false;
                }
            }
        }

        async function regenerateSingleScript(slideIndex) {
            if (!confirm(`确定要重新生成第${slideIndex + 1}页的演讲稿吗？当前内容将被覆盖。`)) {
                return;
            }

            try {
                // 显示进度提示
                const progressToast = showProgressToast(`正在重新生成第${slideIndex + 1}页演讲稿...`, 0);

                // 使用默认参数直接生成（使用正确的API结构）
                const defaultCustomization = {
                    tone: 'conversational',
                    target_audience: 'general_public',
                    language_complexity: 'moderate',
                    speaking_pace: 'normal',
                    include_transitions: true,
                    include_timing_notes: false,
                    custom_style_prompt: null,
                    custom_audience: null
                };

                // 调用生成API
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-script/generate`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        generation_type: 'single',
                        slide_indices: [slideIndex],
                        customization: defaultCustomization,
                        language: getSpeechLanguage()
                    })
                });

                const result = await response.json();

                console.log('Single script regeneration API response:', result);

                if (result.success && result.task_id) {
                    console.log('Starting progress tracking for single script regeneration:', result.task_id);

                    // 开始进度跟踪
                    startSingleScriptProgressTracking(result.task_id, progressToast, slideIndex);
                } else {
                    console.error('Single script regeneration failed:', result);
                    closeProgressToast(progressToast);
                    showNotification(`重新生成失败: ${result.error || result.message || '未知错误'}`, 'error');
                }

            } catch (error) {
                console.error('Regenerate single script error:', error);
                showNotification('重新生成失败', 'error');
            }
        }

        function toggleAllEditMode() {
            // 获取当前是否处于编辑模式（检查第一个textarea是否可见）
            const firstTextarea = document.querySelector('.speech-script-edit');
            const isCurrentlyEditing = firstTextarea && !firstTextarea.classList.contains('hidden');

            // 切换所有项目的编辑模式
            document.querySelectorAll('.speech-script-item').forEach(item => {
                const slideIndex = parseInt(item.dataset.slideIndex);
                const scriptIndex = parseInt(item.dataset.scriptIndex);

                // 强制设置为相反的模式
                toggleEditMode(slideIndex, scriptIndex, !isCurrentlyEditing);
            });

            const newEditMode = !isCurrentlyEditing;

            // 同时更新所有单独的编辑按钮状态
            document.querySelectorAll('.edit-btn').forEach(btn => {
                if (newEditMode) {
                    btn.classList.add('hidden');
                } else {
                    btn.classList.remove('hidden');
                }
            });

            // 更新标题
            const titleElement = speechScriptModal ? speechScriptModal.querySelector('.speech-modal-title .speech-section-title') : null;
            if (titleElement) {
                titleElement.innerHTML = `
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                        <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                        <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                    </svg>
                    演讲稿${newEditMode ? '编辑' : '预览'}
                `;
            }

            // 更新按钮文本和样式 - 查找正确的编辑模式按钮
            const toggleBtn = document.getElementById('speechToggleEditModeBtn');
            if (toggleBtn) {
                // 更新按钮样式
                if (newEditMode) {
                    toggleBtn.className = 'speech-btn speech-btn-secondary';
                } else {
                    toggleBtn.className = 'speech-btn speech-btn-primary';
                }

                // 更新按钮内容
                toggleBtn.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        ${newEditMode ?
                        '<path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' :
                        '<path d="M11 4H4C3.44772 4 3 4.44772 3 5V20C3 20.5523 3.44772 21 4 21H19C19.5523 21 20 20.5523 20 20V13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M18.5 2.5C18.8978 2.10217 19.4374 1.87868 20 1.87868C20.5626 1.87868 21.1022 2.10217 21.5 2.5C21.8978 2.89783 22.1213 3.43739 22.1213 4C22.1213 4.56261 21.8978 5.10217 21.5 5.5L12 15L8 16L9 12L18.5 2.5Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
                    }
                    </svg>
                    ${newEditMode ? '退出编辑' : '编辑'}
                `;
            }
        }

        function toggleCustomToneInput() {
            const toneSelect = document.getElementById('speechTone');
            const customContainer = document.getElementById('customToneContainer');

            if (toneSelect.value === 'custom') {
                customContainer.style.display = 'block';
                document.getElementById('customTone').focus();
            } else {
                customContainer.style.display = 'none';
                document.getElementById('customTone').value = '';
            }
        }

        function toggleCustomAudienceInput() {
            const audienceSelect = document.getElementById('targetAudience');
            const customContainer = document.getElementById('customAudienceContainer');

            if (audienceSelect.value === 'custom') {
                customContainer.style.display = 'block';
                document.getElementById('customAudience').focus();
            } else {
                customContainer.style.display = 'none';
                document.getElementById('customAudience').value = '';
            }
        }

        async function pollForSpeechScripts() {
            const maxAttempts = 30; // 最多尝试30次
            const pollInterval = 1000; // 每1000ms查询一次
            let attempts = 0;

            const poll = async () => {
                attempts++;
                console.log(`Polling attempt ${attempts}/${maxAttempts}...`);

                try {
                    const lang = getSpeechLanguage();
                    const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts?language=${encodeURIComponent(lang)}`);
                    const result = await response.json();

                    if (result.success && result.scripts && result.scripts.length > 0) {
                        console.log(`Found ${result.scripts.length} scripts, displaying...`);
                        // 找到数据，显示演讲稿
                        showCurrentSpeechScripts();
                        return;
                    }

                    // 如果还没到最大尝试次数，继续轮询
                    if (attempts < maxAttempts) {
                        setTimeout(poll, pollInterval);
                    } else {
                        console.warn('Polling timeout: No scripts found after max attempts');
                        showNotification('获取演讲稿超时，请手动刷新页面后查看', 'warning');
                    }
                } catch (error) {
                    console.error('Polling error:', error);
                    // 出错继续尝试
                    if (attempts < maxAttempts) {
                        setTimeout(poll, pollInterval);
                    } else {
                        showNotification('获取演讲稿失败，请刷新页面重试', 'error');
                    }
                }
            };

            // 开始轮询
            poll();
        }

        async function showCurrentSpeechScripts() {
            try {
                // Close current dialog
                closeSpeechScriptDialog();

                console.log('Fetching speech scripts from API...');
                // Fetch current speech scripts
                const lang = getSpeechLanguage();
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts?language=${encodeURIComponent(lang)}`);
                const result = await response.json();

                console.log('API response:', result);

                if (!result.success) {
                    console.error('API returned error:', result.error);
                    showNotification(`获取演讲稿失败: ${result.error}`, 'error');
                    return;
                }

                const scripts = result.scripts;
                console.log(`Found ${scripts.length} scripts`);

                if (scripts.length === 0) {
                    console.warn('No scripts found in database');
                    showNotification('暂无演讲稿，请先生成演讲稿', 'info');
                    return;
                }

                // Sort by slide index
                scripts.sort((a, b) => a.slide_index - b.slide_index);

                // 转换为预览格式
                const totalMinutes = scripts.reduce((total, script) => {
                    if (script.estimated_duration && script.estimated_duration.includes('分钟')) {
                        const minutes = parseFloat(script.estimated_duration.replace('分钟', ''));
                        return total + (isNaN(minutes) ? 0 : minutes);
                    }
                    return total;
                }, 0);

                const previewData = {
                    success: true,
                    scripts: scripts,
                    total_estimated_duration: totalMinutes > 0 ? totalMinutes.toFixed(1) + '分钟' : '未知',
                    generation_metadata: {}
                };

                // 设置全局演讲稿数据，以便导出功能可以使用
                speechScriptData = previewData;

                // 直接使用预览弹窗显示，默认为非编辑模式
                showSpeechScriptPreview(previewData, false);

            } catch (error) {
                console.error('Show current speech scripts error:', error);
                showNotification('获取演讲稿失败，请稍后重试', 'error');
            }
        }

function closeSpeechScriptsDialog() {
            const scriptsModal = document.getElementById('speechScriptsModal');
            if (scriptsModal) {
                document.body.removeChild(scriptsModal);
            }
        }

        function getGenerationTypeText(type) {
            const types = {
                'single': '单页',
                'multi': '多页',
                'full': '全部'
            };
            return types[type] || type;
        }

        function getToneText(tone) {
            const tones = {
                'conversational': '对话式',
                'formal': '正式',
                'casual': '轻松',
                'persuasive': '说服性',
                'educational': '教学式',
                'authoritative': '权威式',
                'storytelling': '叙事性'
            };
            return tones[tone] || tone;
        }

        function getAudienceText(audience) {
            const audiences = {
                'general_public': '普通大众',
                'executives': '企业高管',
                'students': '学生',
                'technical_experts': '技术专家',
                'colleagues': '同事',
                'clients': '客户',
                'investors': '投资者'
            };
            return audiences[audience] || audience;
        }

        // 这个函数已经被regenerateSingleScript替代，保留为兼容性
        async function reuseSpeechScriptParams(slideIndex) {
            regenerateSingleScript(slideIndex);
        }

        async function deleteSpeechScriptBySlide(slideIndex) {
            if (!confirm(`确定要删除第${slideIndex + 1}页的演讲稿吗？此操作不可撤销。`)) {
                return;
            }

            try {
                const lang = getSpeechLanguage();
                const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/speech-scripts/slide/${slideIndex}?language=${encodeURIComponent(lang)}`, {
                    method: 'DELETE'
                });

                const result = await response.json();

                if (result.success) {
                    showNotification(result.message, 'success');
                    // Refresh scripts dialog
                    showCurrentSpeechScripts();
                } else {
                    showNotification(`删除失败: ${result.error}`, 'error');
                }

            } catch (error) {
                console.error('Delete speech script error:', error);
                showNotification('删除演讲稿失败', 'error');
            }
        }

        // 放映模式鼠标控制功能
        let mouseMoveTimeout;
        let isMouseIdle = false;
        let slideshowControls, slideshowExitBtn, slideshowOverlay;

        function handleSlideshowMouseMove() {
            // 显示控制按钮
            showSlideshowControls();

            // 清除之前的定时器
            clearTimeout(mouseMoveTimeout);

            // 设置新的定时器，3秒后隐藏控制按钮
            mouseMoveTimeout = setTimeout(() => {
                hideSlideshowControls();
            }, 3000);
        }

        function showSlideshowControls() {
            if (slideshowControls) slideshowControls.classList.add('visible');
            if (slideshowExitBtn) slideshowExitBtn.classList.add('visible');
            const slideshowInfo = document.getElementById('slideshowInfo');
            if (slideshowInfo) slideshowInfo.classList.add('visible');
            isMouseIdle = false;
            // 显示鼠标光标
            if (slideshowOverlay) slideshowOverlay.style.cursor = 'default';
        }

        function hideSlideshowControls() {
            if (slideshowControls) slideshowControls.classList.remove('visible');
            if (slideshowExitBtn) slideshowExitBtn.classList.remove('visible');
            const slideshowInfo = document.getElementById('slideshowInfo');
            if (slideshowInfo) slideshowInfo.classList.remove('visible');
            isMouseIdle = true;
            // 隐藏鼠标光标
            if (slideshowOverlay) slideshowOverlay.style.cursor = 'none';
        }

        function initializeSlideshowMouseControls() {
            slideshowOverlay = document.getElementById('slideshowOverlay');
            slideshowControls = document.querySelector('.slideshow-controls');
            slideshowExitBtn = document.querySelector('.slideshow-exit');

            // 初始状态：隐藏控制按钮
            hideSlideshowControls();

            // 鼠标移动事件
            slideshowOverlay.addEventListener('mousemove', handleSlideshowMouseMove);

            // 鼠标离开事件
            slideshowOverlay.addEventListener('mouseleave', hideSlideshowControls);
        }

        function removeSlideshowMouseControls() {
            // 清除定时器
            clearTimeout(mouseMoveTimeout);

            // 移除事件监听器
            if (slideshowOverlay) {
                slideshowOverlay.removeEventListener('mousemove', handleSlideshowMouseMove);
                slideshowOverlay.removeEventListener('mouseleave', hideSlideshowControls);

                // 恢复鼠标光标
                slideshowOverlay.style.cursor = 'default';
            }

            // 清理引用
            slideshowControls = null;
            slideshowExitBtn = null;
            slideshowOverlay = null;
        }

        // ========== AI优化大纲功能 ==========

        // 辅助函数：获取正确的目标受众（处理自定义受众情况）
