// Extracted narration helpers for project slides editor.

function getNarrationLanguage() {
            const el = document.getElementById('narrationLanguage');
            if (el && el.value) {
                currentSpeechLanguage = el.value;
                return el.value;
            }
            return getSpeechLanguage();
        }

        function getNarrationFps() {
            const el = document.getElementById('narrationFps');
            const raw = el && el.value ? parseInt(el.value, 10) : 30;
            return raw === 60 ? 60 : 30;
        }

        function getNarrationProvider() {
            const el = document.getElementById('narrationTtsProvider');
            if (el && el.value) {
                narrationTtsProvider = el.value;
            }
            return narrationTtsProvider || 'edge_tts';
        }

        function handleNarrationProviderChange() {
            const provider = getNarrationProvider();
            const field = document.getElementById('speechRefAudioField');
            const container = document.getElementById('narrationRefAudioContainer');
            const compactTools = document.getElementById('speechCompactTools');
            const enabled = provider === 'comfyuiapi';
            if (field) {
                field.style.display = enabled ? 'flex' : 'none';
            }
            if (container) {
                container.style.display = enabled ? 'flex' : 'none';
            }
            if (compactTools && enabled) {
                compactTools.open = true;
            }
        }

        async function uploadNarrationReferenceAudio(file) {
            const formData = new FormData();
            formData.append('file', file);

            const resp = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/narration/reference-audio`, {
                method: 'POST',
                credentials: 'same-origin',
                body: formData
            });
            const data = await resp.json();
            if (!resp.ok || !data || !data.success) {
                throw new Error(data && (data.detail || data.error || data.message) || `HTTP ${resp.status}`);
            }
            narrationReferenceAudioPath = data.reference_audio_path || null;
            const status = document.getElementById('narrationRefAudioStatus');
            if (status) {
                status.textContent = narrationReferenceAudioPath ? '已上传参考音频' : '未上传参考音频';
            }
        }

        async function handleNarrationRefAudioSelected(inputEl) {
            let toast = null;
            try {
                const file = inputEl && inputEl.files && inputEl.files[0] ? inputEl.files[0] : null;
                if (!file) return;
                toast = showProgressToast('正在上传参考音频...', 0);
                await uploadNarrationReferenceAudio(file);
                showNotification('参考音频已上传', 'success');
            } catch (error) {
                console.error('Upload narration reference audio error:', error);
                showNotification(`参考音频上传失败: ${error && error.message ? error.message : error}`, 'error');
            } finally {
                try { if (toast) closeProgressToast(toast); } catch (_) { }
            }
        }

        async function generateNarrationAudio() {
            let progressToast = null;
            try {
                const lang = getNarrationLanguage();
                const provider = getNarrationProvider();
                progressToast = showProgressToast(`正在生成${lang === 'en' ? '英文' : '中文'}讲解音频...`, 0);

                if (provider === 'comfyuiapi' && !narrationReferenceAudioPath) {
                    const inputEl = document.getElementById('narrationRefAudioFile');
                    const file = inputEl && inputEl.files && inputEl.files[0] ? inputEl.files[0] : null;
                    if (!file) {
                        closeProgressToast(progressToast);
                        showNotification('请先选择参考音频（ComfyUI 语音克隆需要）', 'warning');
                        return;
                    }
                    await uploadNarrationReferenceAudio(file);
                }

                const resp = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/narration/generate`, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider: provider,
                        language: lang,
                        slide_indices: null,
                        voice: null,
                        rate: '+0%',
                        reference_audio_path: narrationReferenceAudioPath,
                        reference_text: '',
                        force_regenerate: false
                    })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    closeProgressToast(progressToast);
                    throw new Error(data && (data.detail || data.error || data.message) || `HTTP ${resp.status}`);
                }

                const taskId = data.task_id;
                if (!taskId) {
                    closeProgressToast(progressToast);
                    throw new Error(data.error || data.message || '未返回任务ID');
                }

                await pollBackgroundTaskUntilDone(taskId, {
                    onTick: (t) => {
                        const p = (typeof t.progress === 'number') ? Math.round(t.progress) : 0;
                        updateProgressToast(progressToast, `生成讲解音频中... (${p}%)`, p);
                    }
                });
                closeProgressToast(progressToast);
                showNotification('讲解音频生成完成', 'success');
            } catch (error) {
                console.error('Narration audio generation error:', error);
                try { if (progressToast) closeProgressToast(progressToast); } catch (_) { }
                showNotification(`生成讲解音频失败: ${error && error.message ? error.message : error}`, 'error');
            }
        }

        async function playNarrationForSlide(slideIndex) {
            const lang = getNarrationLanguage();
            narrationCurrentIndex = slideIndex;
            if (!narrationAudioEl) {
                narrationAudioEl = new Audio();
                narrationAudioEl.preload = 'auto';
                narrationAudioEl.addEventListener('ended', async () => {
                    narrationIsPlaying = false;
                    updateNarrationPlayButton();
                    if (!narrationAutoNext) return;
                    const next = narrationCurrentIndex + 1;
                    if (typeof slidesData !== 'undefined' && next < slidesData.length) {
                        try {
                            if (typeof goToSlide === 'function') {
                                goToSlide(next);
                            } else if (typeof showSlide === 'function') {
                                showSlide(next);
                            }
                        } catch (_) { }
                        try {
                            await playNarrationForSlide(next);
                        } catch (e) {
                            console.error('Auto-next narration play failed:', e);
                            showNotification('自动播放下一页失败（可能未生成音频）', 'warning');
                        }
                    }
                });
                narrationAudioEl.addEventListener('pause', () => {
                    narrationIsPlaying = false;
                    updateNarrationPlayButton();
                });
                narrationAudioEl.addEventListener('error', () => {
                    narrationIsPlaying = false;
                    updateNarrationPlayButton();
                    showNotification('音频加载失败（可能未生成讲解音频）', 'warning');
                });
            }

            const url = `/api/projects/${window.landpptEditorConfig.projectId}/narration/audio/${slideIndex}?language=${encodeURIComponent(lang)}`;
            try {
                narrationAudioEl.pause();
                narrationAudioEl.currentTime = 0;
            } catch (_) { }

            narrationAudioEl.src = url;
            narrationIsPlaying = true;
            updateNarrationPlayButton();
            try {
                await narrationAudioEl.play();
            } catch (e) {
                narrationIsPlaying = false;
                updateNarrationPlayButton();
                throw e;
            }
        }

        function stopNarrationPlayback() {
            if (!narrationAudioEl) {
                narrationIsPlaying = false;
                updateNarrationPlayButton();
                return;
            }
            try {
                narrationAudioEl.pause();
                narrationAudioEl.currentTime = 0;
                narrationAudioEl.removeAttribute('src');
                narrationAudioEl.load();
            } catch (_) { }
            narrationIsPlaying = false;
            updateNarrationPlayButton();
        }

        function updateNarrationPlayButton() {
            const btn = document.getElementById('narrationPlayBtn');
            if (!btn) return;
            btn.textContent = narrationIsPlaying ? '停止播放' : '播放当前页';
        }

        async function toggleNarrationPlaybackForCurrentSlide() {
            try {
                if (narrationIsPlaying) {
                    stopNarrationPlayback();
                    return;
                }
                if (typeof currentSlideIndex !== 'number') {
                    showNotification('无法获取当前页索引', 'warning');
                    return;
                }
                await playNarrationForSlide(currentSlideIndex);
            } catch (error) {
                console.error('Play narration error:', error);
                showNotification(`播放失败：${error && error.message ? error.message : error}`, 'error');
            }
        }

        function openNarrationPresentation() {
            const lang = getNarrationLanguage();
            const url = `/projects/${window.landpptEditorConfig.projectId}/fullscreen?narration=1&language=${encodeURIComponent(lang)}`;
            window.open(url, '_blank');
        }

        function toggleNarrationAutoNext() {
            narrationAutoNext = !narrationAutoNext;
            const label = document.getElementById('narrationAutoNextLabel');
            if (label) label.textContent = narrationAutoNext ? '开' : '关';
        }

        function getNarrationRenderMode() {
            const el = document.getElementById('narrationRenderMode');
            const v = (el && el.value) ? String(el.value).trim().toLowerCase() : 'live';
            return (v === 'static') ? 'static' : 'live';
        }

        async function exportNarrationVideo() {
            try {
                // Open a blank tab synchronously (user gesture) to avoid popup blockers when we later
                // navigate to the download URL after async task completion.
                const downloadWindow = window.open('about:blank', '_blank');

                const lang = getNarrationLanguage();
                const fps = getNarrationFps();
                const renderMode = getNarrationRenderMode();
                const progressToast = showProgressToast(`正在导出${lang === 'en' ? '英文' : '中文'}讲解视频...`, 0);

                const resp = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/export/narration-video`, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        language: lang,
                        fps: fps,
                        embed_subtitles: true,
                        subtitle_style: null,
                        render_mode: renderMode
                    })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    closeProgressToast(progressToast);
                    throw new Error(data && (data.detail || data.error || data.message) || `HTTP ${resp.status}`);
                }
                const taskId = data.task_id;
                if (!taskId) {
                    closeProgressToast(progressToast);
                    throw new Error(data.error || data.message || '未返回任务ID');
                }

                const taskData = await pollBackgroundTaskUntilDone(taskId, {
                    timeoutMs: 60 * 60 * 1000,
                    onTick: (t) => {
                        const p = (typeof t.progress === 'number') ? Math.round(t.progress) : 0;
                        updateProgressToast(progressToast, `导出视频中... (${p}%)`, p);
                    }
                });

                closeProgressToast(progressToast);
                const downloadUrl = taskData.download_url || `/api/landppt/tasks/${taskId}/download`;
                if (downloadWindow && !downloadWindow.closed) {
                    try {
                        downloadWindow.location.href = downloadUrl;
                        setTimeout(() => {
                            try { downloadWindow.close(); } catch (_) { }
                        }, 3000);
                    } catch (_) {
                        // Fall back to same-tab download trigger
                        if (typeof triggerFileDownload === 'function') {
                            triggerFileDownload(downloadUrl);
                        } else {
                            window.location.href = downloadUrl;
                        }
                    }
                } else {
                    // Pop-up blocked: use same-tab download trigger.
                    if (typeof triggerFileDownload === 'function') {
                        triggerFileDownload(downloadUrl);
                    } else {
                        window.location.href = downloadUrl;
                    }
                }
                showNotification('讲解视频导出完成，已开始下载', 'success');
            } catch (error) {
                console.error('Export narration video error:', error);
                showNotification(`导出失败：${error && error.message ? error.message : error}`, 'error');
            }
        }

        async function exportNarrationAudio() {
            let progressToast = null;
            try {
                const lang = getNarrationLanguage();
                const provider = getNarrationProvider();
                progressToast = showProgressToast(`正在导出${lang === 'en' ? '英文' : '中文'}讲解音频...`, 0);

                if (provider === 'comfyuiapi' && !narrationReferenceAudioPath) {
                    const inputEl = document.getElementById('narrationRefAudioFile');
                    const file = inputEl && inputEl.files && inputEl.files[0] ? inputEl.files[0] : null;
                    if (!file) {
                        closeProgressToast(progressToast);
                        showNotification('请先选择参考音频（ComfyUI 语音克隆需要）', 'warning');
                        return;
                    }
                    await uploadNarrationReferenceAudio(file);
                }

                const resp = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/export/narration-audio`, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider: provider,
                        language: lang,
                        voice: null,
                        rate: '+0%',
                        reference_audio_path: narrationReferenceAudioPath,
                        reference_text: '',
                        force_regenerate: false
                    })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    closeProgressToast(progressToast);
                    throw new Error(data && (data.detail || data.error || data.message) || `HTTP ${resp.status}`);
                }

                const taskId = data.task_id;
                if (!taskId) {
                    closeProgressToast(progressToast);
                    throw new Error(data.error || data.message || '未返回任务ID');
                }

                const taskData = await pollBackgroundTaskUntilDone(taskId, {
                    timeoutMs: 60 * 60 * 1000,
                    onTick: (t) => {
                        const p = (typeof t.progress === 'number') ? Math.round(t.progress) : 0;
                        const taskMessage = t.message || (t.metadata && t.metadata.progress_message) || '导出讲解音频中...';
                        updateProgressToast(progressToast, `${taskMessage} (${p}%)`, p);
                    }
                });

                closeProgressToast(progressToast);
                const downloadUrl = taskData.download_url || `/api/landppt/tasks/${taskId}/download`;
                if (typeof triggerFileDownload === 'function') {
                    triggerFileDownload(downloadUrl);
                } else {
                    window.location.href = downloadUrl;
                }
                showNotification('讲解音频导出完成，已开始下载', 'success');
            } catch (error) {
                console.error('Export narration audio error:', error);
                try { if (progressToast) closeProgressToast(progressToast); } catch (_) { }
                showNotification(`导出失败：${error && error.message ? error.message : error}`, 'error');
            }
        }
