// 图片上传相关函数
        function triggerImageUpload() {
            if (isUploading) {
                showNotification('正在上传中，请稍候...', 'warning');
                return;
            }
            showImageSelectMenu();
        }

        // 初始化图片上传功能
        function initImageUpload() {
            const fileInput = document.getElementById('aiImageFileInput');
            const uploadBtn = document.getElementById('aiImageUploadBtn');
            const inputContainer = document.querySelector('.ai-input-container');



            if (!fileInput || !uploadBtn || !inputContainer) {
                return;
            }

            // 文件选择处理
            fileInput.addEventListener('change', handleFileSelect);

            // 拖拽事件处理 - 使用重命名的函数避免冲突
            inputContainer.addEventListener('dragenter', handleImageDragEnter);
            inputContainer.addEventListener('dragover', handleImageDragOver);
            inputContainer.addEventListener('dragleave', handleImageDragLeave);
            inputContainer.addEventListener('drop', handleImageFileDrop);

            // 阻止默认拖拽行为
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                inputContainer.addEventListener(eventName, preventImageDefaults, false);
            });


        }

        // 检查是否为文件拖拽
        function isFileDrag(e) {
            return e.dataTransfer &&
                e.dataTransfer.types &&
                (e.dataTransfer.types.includes('Files') ||
                    e.dataTransfer.types.includes('application/x-moz-file'));
        }

        function preventImageDefaults(e) {
            // 只处理文件拖拽，不影响其他拖拽操作
            if (isFileDrag(e)) {
                e.preventDefault();
                e.stopPropagation();
            }
        }

        function handleImageDragEnter(e) {
            if (isFileDrag(e)) {
                e.preventDefault();
                const inputContainer = document.querySelector('.ai-input-container');
                inputContainer.classList.add('drag-over');
            }
        }

        function handleImageDragOver(e) {
            if (isFileDrag(e)) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
            }
        }

        function handleImageDragLeave(e) {
            if (isFileDrag(e)) {
                // 检查是否真的离开了容器区域
                const inputContainer = document.querySelector('.ai-input-container');
                const rect = inputContainer.getBoundingClientRect();
                const x = e.clientX;
                const y = e.clientY;

                if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
                    inputContainer.classList.remove('drag-over');
                }
            }
        }

        function handleImageFileDrop(e) {
            // 总是阻止默认行为
            e.preventDefault();
            e.stopPropagation();

            const inputContainer = document.querySelector('.ai-input-container');
            inputContainer.classList.remove('drag-over');

            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                const files = e.dataTransfer.files;

                // 过滤出图片文件
                const imageFiles = Array.from(files).filter(file => file.type.startsWith('image/'));

                if (imageFiles.length > 0) {
                    handleFiles(imageFiles);
                    showNotification(`检测到 ${imageFiles.length} 张图片，正在上传...`, 'info');
                } else {
                    showNotification('请拖拽图片文件到此区域', 'warning');
                }
            } else {
                showNotification('拖拽失败，请重试', 'error');
            }
        }

        function handleFileSelect(e) {
            const files = e.target.files;
            handleFiles(files);
        }

        function handleFiles(files) {
            if (isUploading) {
                showNotification('正在上传中，请稍候...', 'warning');
                return;
            }

            // 支持的图片格式
            const supportedTypes = [
                'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
                'image/webp', 'image/bmp', 'image/svg+xml'
            ];

            const validFiles = [];
            const errors = [];

            Array.from(files).forEach(file => {
                // 验证文件类型
                if (!supportedTypes.includes(file.type.toLowerCase())) {
                    errors.push(`${file.name}: 不支持的图片格式 (${file.type})`);
                    return;
                }

                // 验证文件大小 (10MB)
                if (file.size > 10 * 1024 * 1024) {
                    errors.push(`${file.name}: 文件大小超过10MB限制 (${formatFileSize(file.size)})`);
                    return;
                }

                // 验证文件名
                if (file.name.length > 100) {
                    errors.push(`${file.name}: 文件名过长，请使用较短的文件名`);
                    return;
                }

                validFiles.push(file);
            });

            // 显示错误信息
            if (errors.length > 0) {
                const errorMessage = '以下文件无法上传：\n' + errors.join('\n');
                showNotification(errorMessage, 'error');
            }

            if (validFiles.length === 0) {
                if (errors.length === 0) {
                    showNotification('没有选择有效的图片文件', 'warning');
                }
                return;
            }

            // 检查是否超过最大上传数量
            const maxImages = 10;
            if (uploadedImages.length + validFiles.length > maxImages) {
                showNotification(`最多只能上传${maxImages}张图片，当前已有${uploadedImages.length}张`, 'warning');
                return;
            }

            // 上传文件
            uploadFiles(validFiles);
        }

        async function uploadFiles(files) {
            if (files.length === 0) return;

            isUploading = true;
            showUploadProgress(true);

            try {
                let addedCount = 0;
                for (let i = 0; i < files.length; i++) {
                    const file = files[i];
                    updateUploadProgress((i / files.length) * 100, `上传中 ${i + 1}/${files.length}: ${file.name}`);

                    let dataUrl = null;
                    try {
                        const maybe = await readFileAsDataUrl(file);
                        dataUrl = typeof maybe === 'string' ? maybe : null;
                    } catch (e) {
                        // 忽略读取失败，继续走上传URL
                    }

                    const result = await uploadSingleFile(file);
                    if (result.success) {
                        addUploadedImage({
                            ...result.data,
                            dataUrl: dataUrl
                        });
                        addedCount++;
                    } else {
                        // 即使上传失败，仍允许用 dataUrl 参与对话（视觉模式）
                        if (dataUrl) {
                            addUploadedImage({
                                id: null,
                                name: file.name,
                                size: file.size,
                                url: '',
                                file: file,
                                dataUrl: dataUrl
                            });
                            addedCount++;
                            showNotification(`上传失败，已改用本地图片参与对话：${file.name}`, 'warning');
                        } else {
                            showNotification(`上传失败: ${file.name} - ${result.message}`, 'error');
                        }
                    }
                }

                updateUploadProgress(100, '上传完成');
                setTimeout(() => showUploadProgress(false), 1000);

                if (addedCount > 0) {
                    showNotification(`已添加 ${addedCount} 张图片`, 'success');
                } else {
                    showNotification('未能添加图片，请重试', 'error');
                }

            } catch (error) {
                showNotification('上传失败，请重试', 'error');
            } finally {
                isUploading = false;
                setTimeout(() => showUploadProgress(false), 1000);
            }
        }

        async function uploadSingleFile(file) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('title', file.name.split('.')[0]);
            formData.append('description', `AI编辑助手上传的图片: ${file.name}`);
            formData.append('category', 'ai_assistant');
            formData.append('tags', 'ai_assistant,ppt_edit');

            try {
                const response = await fetch('/api/image/upload', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (result.success) {
                    // 获取图片的绝对URL
                    const imageUrl = await getImageAbsoluteUrl(result.image_id);
                    return {
                        success: true,
                        data: {
                            id: result.image_id,
                            name: file.name,
                            size: file.size,
                            url: imageUrl,
                            file: file
                        }
                    };
                } else {
                    return {
                        success: false,
                        message: result.message || '上传失败'
                    };
                }
            } catch (error) {
                return {
                    success: false,
                    message: '网络错误'
                };
            }
        }

        async function getImageAbsoluteUrl(imageId) {
            try {
                const response = await fetch(`/api/image/${imageId}/info`);
                const result = await response.json();

                if (result.success && result.image_info) {
                    return result.image_info.absolute_url;
                } else {
                    // 如果获取失败，使用默认的URL格式
                    return `${window.location.origin}/api/image/${imageId}`;
                }
            } catch (error) {
                return `${window.location.origin}/api/image/${imageId}`;
            }
        }

        function showUploadProgress(show) {
            const progressDiv = document.getElementById('aiUploadProgress');
            progressDiv.style.display = show ? 'block' : 'none';

            if (!show) {
                updateUploadProgress(0, '');
            }
        }

        function updateUploadProgress(percent, text) {
            const progressFill = document.getElementById('aiProgressFill');
            const progressText = document.getElementById('aiProgressText');

            progressFill.style.width = `${percent}%`;
            progressText.textContent = text;
        }

        function addUploadedImage(imageData) {
            uploadedImages.push(imageData);
            renderUploadedImages();
        }

        function renderUploadedImages() {
            const container = document.getElementById('aiUploadedImages');
            const uploadBtn = document.getElementById('aiImageUploadBtn');

            container.innerHTML = '';

            // 更新上传按钮状态
            if (uploadedImages.length === 0) {
                uploadBtn.classList.remove('has-images');
                uploadBtn.removeAttribute('data-count');
                return;
            } else {
                uploadBtn.classList.add('has-images');
                uploadBtn.setAttribute('data-count', uploadedImages.length);
            }

            uploadedImages.forEach((image, index) => {
                const imageDiv = document.createElement('div');
                imageDiv.className = 'ai-uploaded-image';
                imageDiv.title = `${image.name} (${formatFileSize(image.size)}) - 点击查看大图`;

                // 创建图片预览
                const img = document.createElement('img');
                if (image.file) {
                    // 本地上传的图片
                    img.src = URL.createObjectURL(image.file);
                } else {
                    // 从图床选择的图片
                    img.src = image.url;
                }
                img.alt = image.name;

                // 创建删除按钮
                const removeBtn = document.createElement('button');
                removeBtn.className = 'ai-image-remove';
                removeBtn.innerHTML = '<i class="fas fa-times"></i>';
                removeBtn.onclick = (e) => {
                    e.stopPropagation();
                    removeUploadedImage(index);
                };

                // 创建信息显示
                const infoDiv = document.createElement('div');
                infoDiv.className = 'ai-image-info';
                infoDiv.textContent = formatFileSize(image.size);

                imageDiv.appendChild(img);
                imageDiv.appendChild(removeBtn);
                imageDiv.appendChild(infoDiv);

                // 点击图片显示全屏预览
                imageDiv.addEventListener('click', () => {
                    showImagePreview(image);
                });

                container.appendChild(imageDiv);
            });
        }

        function removeUploadedImage(index) {
            if (index >= 0 && index < uploadedImages.length) {
                const image = uploadedImages[index];
                // 释放blob URL（仅对本地上传的图片）
                if (image.file) {
                    URL.revokeObjectURL(URL.createObjectURL(image.file));
                }
                uploadedImages.splice(index, 1);
                renderUploadedImages();
                showNotification('图片已移除', 'info');
            }
        }



        function formatFileSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        function clearUploadedImages() {
            // 释放所有blob URLs（仅对本地上传的图片）
            uploadedImages.forEach(image => {
                if (image.file) {
                    URL.revokeObjectURL(URL.createObjectURL(image.file));
                }
            });
            uploadedImages = [];
            renderUploadedImages();
        }



        // 自动将所有已上传的图片信息嵌入到消息中
        function autoEmbedUploadedImages(message) {
            if (uploadedImages.length === 0) {
                return message;
            }

            // 构建图片信息文本
            let imageInfoText = '\n\n📷 图片信息：\n';
            uploadedImages.forEach((image, index) => {
                imageInfoText += `${index + 1}. 图片名称：${image.name}\n`;
                const url = (image && typeof image.url === 'string') ? image.url : '';
                const displayUrl = url && url.startsWith('data:image') ? '（本地图片，已随消息发送）' : (url || '（无URL）');
                imageInfoText += `   图片地址：${displayUrl}\n`;
                imageInfoText += `   文件大小：${formatFileSize(image.size)}\n`;
                if (index < uploadedImages.length - 1) {
                    imageInfoText += '\n';
                }
            });

            // imageInfoText += '\n请分析这些图片的内容，并根据我的要求进行处理。';

            return message + imageInfoText;
        }

        // 获取所有已上传的图片信息
        function getAllUploadedImages() {
            return uploadedImages.map(image => ({
                name: image.name,
                // 视觉模式优先使用 dataUrl，避免外部模型无法访问私有URL
                url: visionModeEnabled ? (image.dataUrl || image.url || '') : (image.url || ''),
                size: image.size > 0 ? formatFileSize(image.size) : '未知大小',
                id: image.id
            }));
        }

        // 视觉模式切换功能
        async function toggleVisionMode() {
            const nextEnabled = !visionModeEnabled;
            const visionBtn = document.getElementById('aiVisionToggleBtn');
            if (!visionBtn) return;

            if (nextEnabled) {
                visionModeEnabled = true;
                visionBtn.classList.add('active');
                visionBtn.title = '关闭视觉模式 - AI将不再看到当前幻灯片';
                showNotification('视觉模式启用中：正在捕获当前幻灯片…', 'info');

                // 立即尝试捕获一次，确保视觉模式真的可用（常见失败原因：外链图片跨域导致 canvas 导出失败）
                const screenshot = await captureSlideScreenshot();
                if (!screenshot) {
                    visionModeEnabled = false;
                    visionBtn.classList.remove('active');
                    visionBtn.title = '启用视觉模式 - AI将能看到当前幻灯片';
                    showNotification('视觉模式启用失败：无法捕获幻灯片截图（可能是跨域图片/资源导致）', 'warning');
                    return;
                }

                showNotification('视觉模式已启用 - AI现在可以看到当前幻灯片', 'success');
                return;
            }

            visionModeEnabled = false;

            visionBtn.classList.remove('active');
            visionBtn.title = '启用视觉模式 - AI将能看到当前幻灯片';
            showNotification('视觉模式已关闭', 'info');
        }

        // 捕获当前幻灯片截图
        async function captureSlideScreenshot() {
            if (!visionModeEnabled) {
                return null;
            }

            try {
                const slideFrame = document.getElementById('slideFrame');
                if (!slideFrame) {
                    return null;
                }

                // 等待iframe内容加载完成
                await new Promise(resolve => {
                    if (slideFrame.contentDocument && slideFrame.contentDocument.readyState === 'complete') {
                        resolve();
                    } else {
                        slideFrame.onload = resolve;
                        setTimeout(resolve, 1000); // 超时保护
                    }
                });

                // 获取iframe内容
                const iframeDoc = slideFrame.contentDocument || slideFrame.contentWindow.document;
                if (!iframeDoc) {
                    return null;
                }

                // 使用html2canvas捕获iframe内容
                if (typeof html2canvas === 'undefined') {
                    await loadHtml2Canvas();
                }

                const canvas = await html2canvas(iframeDoc.body, {
                    width: 1280,
                    height: 720,
                    scale: 1,
                    useCORS: true,
                    allowTaint: true,
                    backgroundColor: '#ffffff'
                });

                // 转换为base64
                const dataURL = canvas.toDataURL('image/jpeg', 0.8);
                return dataURL;

            } catch (error) {
                console.error('captureSlideScreenshot failed:', error);
                try {
                    showNotification('捕获幻灯片截图失败：请检查是否存在跨域图片/资源', 'warning');
                } catch (_) {
                    // ignore
                }
                return null;
            }
        }

        // 动态加载html2canvas库
        async function loadHtml2Canvas() {
            return new Promise((resolve, reject) => {
                if (typeof html2canvas !== 'undefined') {
                    resolve();
                    return;
                }

                const script = document.createElement('script');
                script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
                script.onload = resolve;
                script.onerror = reject;
                document.head.appendChild(script);
            });
        }



        // 全屏图片预览相关函数
        function showImagePreview(image) {
            currentPreviewImage = image;

            const overlay = document.getElementById('imagePreviewOverlay');
            const title = document.getElementById('imagePreviewTitle');
            const details = document.getElementById('imagePreviewDetails');
            const img = document.getElementById('imagePreviewImg');
            const loading = document.getElementById('imagePreviewLoading');

            // 显示遮罩层
            overlay.style.display = 'flex';

            // 设置图片信息
            title.textContent = image.name;
            details.textContent = `大小: ${formatFileSize(image.size)} | 发送消息时自动包含此图片`;

            // 显示加载状态
            loading.style.display = 'block';
            img.style.display = 'none';

            // 加载图片
            img.onload = function () {
                loading.style.display = 'none';
                img.style.display = 'block';
            };

            img.onerror = function () {
                loading.style.display = 'none';
                img.style.display = 'block';
                img.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjZGRkIi8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvbnQtZmFtaWx5PSJBcmlhbCwgc2Fucy1zZXJpZiIgZm9udC1zaXplPSIxNCIgZmlsbD0iIzk5OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPuWbvueJh+WKoOi9veWksei0pTwvdGV4dD48L3N2Zz4=';
            };

            // 设置图片源
            img.src = image.dataUrl || image.url;

            // 阻止页面滚动
            document.body.style.overflow = 'hidden';
        }

        function closeImagePreview() {
            const overlay = document.getElementById('imagePreviewOverlay');
            overlay.style.display = 'none';
            currentPreviewImage = null;
            window.currentPreviewOwner = null;
            window.currentPreviewNativeIndex = null;

            // 恢复页面滚动
            document.body.style.overflow = '';
        }

        function downloadCurrentImage() {
            if (!currentPreviewImage) return;

            const link = document.createElement('a');
            link.href = currentPreviewImage.url;
            link.download = currentPreviewImage.name;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            showNotification(`开始下载: ${currentPreviewImage.name}`, 'success');
        }



        function removeCurrentImage() {
            if (!currentPreviewImage) return;

            if (window.currentPreviewOwner === 'native_dialog') {
                const idx = Number(window.currentPreviewNativeIndex);
                if (Number.isInteger(idx) && idx >= 0) {
                    if (confirm(`确定要移除图片 "${currentPreviewImage.name}" 吗？`)) {
                        removeNativeUploadedImage(idx);
                        closeImagePreview();
                    }
                }
                return;
            }

            const index = uploadedImages.findIndex(img => img.id === currentPreviewImage.id);
            if (index !== -1) {
                if (confirm(`确定要删除图片 "${currentPreviewImage.name}" 吗？`)) {
                    removeUploadedImage(index);
                    closeImagePreview();
                }
            }
        }

        // 键盘事件处理
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && currentPreviewImage) {
                closeImagePreview();
            }
        });

        // 点击遮罩层关闭预览
        document.addEventListener('click', function (e) {
            if (e.target.id === 'imagePreviewOverlay') {
                closeImagePreview();
            }
        });

        // 图片选择菜单相关函数
