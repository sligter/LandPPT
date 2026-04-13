        function showImageSelectMenu() {
            const menu = document.getElementById('imageSelectMenu');
            menu.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }

        function closeImageSelectMenu() {
            const menu = document.getElementById('imageSelectMenu');
            menu.style.display = 'none';
            document.body.style.overflow = '';
        }

        function selectFromLocal() {
            closeImageSelectMenu();
            const fileInput = document.getElementById('aiImageFileInput');
            fileInput.click();
        }

        function selectFromLibrary() {
            closeImageSelectMenu();
            showImageLibrary();
        }

        // 图床选择器相关函数
        function showImageLibrary() {
            const overlay = document.getElementById('imageLibraryOverlay');
            const loading = document.getElementById('imageLibraryLoading');
            const grid = document.getElementById('imageLibraryGrid');
            const empty = document.getElementById('imageLibraryEmpty');

            overlay.style.display = 'flex';
            loading.style.display = 'block';
            grid.style.display = 'none';
            empty.style.display = 'none';

            selectedLibraryImages = [];
            updateSelectionCount();

            document.body.style.overflow = 'hidden';

            // 初始化搜索功能
            initImageLibrarySearch();

            // 加载图床图片
            loadLibraryImages();
        }

        function closeImageLibrary() {
            const overlay = document.getElementById('imageLibraryOverlay');
            overlay.style.display = 'none';
            selectedLibraryImages = [];
            document.body.style.overflow = '';

            // 重置搜索状态
            const searchInput = document.getElementById('imageLibrarySearchInput');
            const clearBtn = document.getElementById('imageLibrarySearchClear');
            if (searchInput) {
                searchInput.value = '';
            }
            if (clearBtn) {
                clearBtn.style.display = 'none';
            }
            currentSearchTerm = '';
            filteredLibraryImages = [];

            // 重置分页状态
            currentPage = 1;
            totalPages = 1;
            totalCount = 0;
            hidePaginationUI();
        }

        async function loadLibraryImages(searchTerm = '', page = 1) {
            try {
                // 使用与pages/image/image_gallery.html相同的API端点
                const params = new URLSearchParams({
                    page: page,
                    per_page: perPage,
                    category: '', // 不限制分类
                    search: searchTerm,
                    sort: 'created_desc'
                });

                const response = await fetch(`/api/image/gallery/list?${params}`);
                const result = await response.json();

                const loading = document.getElementById('imageLibraryLoading');
                const grid = document.getElementById('imageLibraryGrid');
                const empty = document.getElementById('imageLibraryEmpty');

                loading.style.display = 'none';

                if (result.success && result.images && result.images.length > 0) {
                    libraryImages = result.images;
                    filteredLibraryImages = libraryImages;

                    // 更新分页信息
                    if (result.pagination) {
                        currentPage = result.pagination.current_page;
                        totalPages = result.pagination.total_pages;
                        totalCount = result.pagination.total_count;
                        updatePaginationUI();
                    }

                    renderLibraryImages();
                    grid.style.display = 'grid';
                } else {
                    empty.style.display = 'block';
                    hidePaginationUI();
                }
            } catch (error) {
                const loading = document.getElementById('imageLibraryLoading');
                const empty = document.getElementById('imageLibraryEmpty');

                loading.style.display = 'none';
                empty.style.display = 'block';
                empty.innerHTML = `
                    <i class="fas fa-exclamation-triangle"></i>
                `;
                showNotification('加载图床图片失败', 'error');
            }
        }

        function renderLibraryImages() {
            const grid = document.getElementById('imageLibraryGrid');
            grid.innerHTML = '';

            filteredLibraryImages.forEach(image => {
                const item = document.createElement('div');
                item.className = 'image-library-item';
                item.dataset.imageId = image.image_id;

                // 构建图片URL
                const imageUrl = `/api/image/view/${image.image_id}`;

                // 格式化文件大小 - 检查多个可能的位置
                let fileSize = '未知大小';
                if (image.file_size && image.file_size > 0) {
                    // 直接从根级别获取file_size
                    fileSize = formatFileSize(image.file_size);
                } else if (image.metadata) {
                    // 从metadata中获取
                    if (image.metadata.file_size && image.metadata.file_size > 0) {
                        fileSize = formatFileSize(image.metadata.file_size);
                    } else if (image.metadata.size && image.metadata.size > 0) {
                        fileSize = formatFileSize(image.metadata.size);
                    }
                }

                item.innerHTML = `
                    <img src="${imageUrl}" alt="${image.title || '未命名图片'}" loading="lazy" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTUwIiBoZWlnaHQ9IjE1MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjZjBmMGYwIi8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvbnQtZmFtaWx5PSJBcmlhbCwgc2Fucy1zZXJpZiIgZm9udC1zaXplPSIxMiIgZmlsbD0iIzk5OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPuWbvueJh+WKoOi9veWksei0pTwvdGV4dD48L3N2Zz4='">
                    <div class="image-info">
                        <div>${image.title || '未命名图片'}</div>
                        <div>${fileSize}</div>
                    </div>
                    <div class="selection-indicator">
                        <i class="fas fa-check"></i>
                    </div>
                `;

                item.addEventListener('click', () => toggleImageSelection(image, item));
                grid.appendChild(item);
            });
        }

        function toggleImageSelection(image, element) {
            const imageId = image.image_id;
            const index = selectedLibraryImages.findIndex(img => img.image_id === imageId);

            if (index === -1) {
                // 添加到选择列表
                selectedLibraryImages.push(image);
                element.classList.add('selected');
            } else {
                // 从选择列表移除
                selectedLibraryImages.splice(index, 1);
                element.classList.remove('selected');
            }

            updateSelectionCount();
        }

        function updateSelectionCount() {
            const countSpan = document.getElementById('selectedCount');
            const confirmBtn = document.getElementById('confirmSelectionBtn');

            countSpan.textContent = selectedLibraryImages.length;
            confirmBtn.disabled = selectedLibraryImages.length === 0;
        }

        async function confirmImageSelection() {
            if (selectedLibraryImages.length === 0) return;

            let addedCount = 0;

            // 显示处理进度
            showNotification('正在处理选择的图片...', 'info');

            // 逐个处理选择的图片，获取完整信息
            for (const image of selectedLibraryImages) {
                try {
                    // 获取图片的完整信息和绝对URL
                    const imageInfo = await getImageCompleteInfo(image.image_id);

                    const imageData = {
                        id: image.image_id,
                        name: imageInfo.name || image.title || '未命名图片',
                        size: imageInfo.size || 0,
                        url: imageInfo.absoluteUrl,
                        file: null // 从图床选择的图片没有file对象
                    };

                    // 检查是否已经存在
                    const exists = uploadedImages.find(img => img.id === imageData.id);
                    if (!exists) {
                        uploadedImages.push(imageData);
                        addedCount++;
                    }
                } catch (error) {
                    // 如果获取详细信息失败，使用基本信息
                    const imageData = {
                        id: image.image_id,
                        name: image.title || '未命名图片',
                        size: image.file_size || (image.metadata && image.metadata.file_size) || 0,
                        url: `${window.location.origin}/api/image/view/${image.image_id}`,
                        file: null
                    };

                    const exists = uploadedImages.find(img => img.id === imageData.id);
                    if (!exists) {
                        uploadedImages.push(imageData);
                        addedCount++;
                    }
                }
            }

            renderUploadedImages();
            closeImageLibrary();

            if (addedCount > 0) {
                showNotification(`已添加 ${addedCount} 张图片`, 'success');
            } else {
                showNotification('所选图片已存在，未添加新图片', 'info');
            }
        }

        // 获取图片的完整信息，包括绝对URL
        async function getImageCompleteInfo(imageId) {
            try {
                const response = await fetch(`/api/image/${imageId}/info`);
                const result = await response.json();

                if (result.success && result.image_info) {
                    return {
                        name: result.image_info.title || result.image_info.filename,
                        size: result.image_info.file_size || 0,
                        absoluteUrl: result.image_info.absolute_url
                    };
                } else {
                    throw new Error('获取图片信息失败');
                }
            } catch (error) {
                // 如果专用接口失败，尝试使用详情接口
                try {
                    const detailResponse = await fetch(`/api/image/detail/${imageId}`);
                    const detailResult = await detailResponse.json();

                    if (detailResult.success && detailResult.image) {
                        const image = detailResult.image;
                        return {
                            name: image.title || image.filename,
                            size: (image.metadata && image.metadata.file_size) ? image.metadata.file_size : 0,
                            absoluteUrl: `${window.location.origin}/api/image/view/${imageId}`
                        };
                    }
                } catch (detailError) {
                    // 获取图片详情也失败
                }

                throw error;
            }
        }

        // 分页相关函数
        function updatePaginationUI() {
            const pagination = document.getElementById('imageLibraryPagination');
            const paginationInfo = document.getElementById('paginationInfo');
            const prevBtn = document.getElementById('prevPageBtn');
            const nextBtn = document.getElementById('nextPageBtn');

            if (!pagination) return;

            // 显示分页控件
            pagination.style.display = 'flex';

            // 更新分页信息
            paginationInfo.textContent = `第 ${currentPage} 页，共 ${totalPages} 页 (总计 ${totalCount} 张图片)`;

            // 更新按钮状态
            prevBtn.disabled = currentPage <= 1;
            nextBtn.disabled = currentPage >= totalPages;
        }

        function hidePaginationUI() {
            const pagination = document.getElementById('imageLibraryPagination');
            if (pagination) {
                pagination.style.display = 'none';
            }
        }

        function loadPreviousPage() {
            if (currentPage > 1) {
                loadLibraryImages(currentSearchTerm, currentPage - 1);
            }
        }

        function loadNextPage() {
            if (currentPage < totalPages) {
                loadLibraryImages(currentSearchTerm, currentPage + 1);
            }
        }

        // 图片库搜索相关函数
        function initImageLibrarySearch() {
            const searchInput = document.getElementById('imageLibrarySearchInput');
            const clearBtn = document.getElementById('imageLibrarySearchClear');

            if (!searchInput) return;

            // 搜索输入事件
            searchInput.addEventListener('input', function (e) {
                const searchTerm = e.target.value.trim();
                currentSearchTerm = searchTerm;

                if (searchTerm) {
                    clearBtn.style.display = 'block';
                    // 搜索时重置到第一页
                    loadLibraryImages(searchTerm, 1);
                } else {
                    clearBtn.style.display = 'none';
                    // 清空搜索时重置到第一页
                    loadLibraryImages('', 1);
                }
            });

            // 回车键搜索
            searchInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const searchTerm = e.target.value.trim();
                    currentSearchTerm = searchTerm;
                    loadLibraryImages(searchTerm, 1);
                }
            });
        }



        function clearImageLibrarySearch() {
            const searchInput = document.getElementById('imageLibrarySearchInput');
            const clearBtn = document.getElementById('imageLibrarySearchClear');

            searchInput.value = '';
            clearBtn.style.display = 'none';
            currentSearchTerm = '';

            // 重新加载第一页数据
            loadLibraryImages('', 1);
        }

        // AI增强所有要点功能
