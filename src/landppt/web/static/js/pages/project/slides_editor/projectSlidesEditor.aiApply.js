// AI 编辑结果落到画布 / 数据 / 服务端的同步层。
//
// 流式解析已经统一到 projectSlidesEditor.agentClient.js，这里只保留
// 「拿到一份最终 HTML 之后要做什么」：预览、同步本地状态、提交 proposal。

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
function syncAppliedSlideHtml(slideIndex, htmlContent, slideData = {}) {
    if (!Number.isInteger(slideIndex) || slideIndex < 0 || slideIndex >= slidesData.length) {
        throw new Error(`无效的幻灯片索引: ${slideIndex}`);
    }

    slidesData[slideIndex] = {
        ...slidesData[slideIndex],
        ...(slideData || {}),
        html_content: htmlContent,
        is_user_edited: true
    };
    if (slideData.render_mode === 'svg' && slideData.is_user_edited) {
        delete slidesData[slideIndex].generation_failed;
        delete slidesData[slideIndex].generation_error;
        delete slidesData[slideIndex].svg_report;
    }

    if (typeof setInitialSlideState === 'function') {
        setInitialSlideState(slideIndex, htmlContent);
    }

    const slideFrame = document.getElementById('slideFrame');
    if (slideFrame && slideIndex === currentSlideIndex) {
        setSafeIframeContent(slideFrame, htmlContent);
        setTimeout(() => {
            if (typeof forceReinitializeIframeJS === 'function') {
                forceReinitializeIframeJS(slideFrame);
            }
        }, 300);
    }

    const thumbnailIframe = document.querySelectorAll('.slide-thumbnail .slide-preview iframe')[slideIndex];
    if (thumbnailIframe) {
        setSafeIframeContent(thumbnailIframe, htmlContent);
    }

    const codeEditor = document.getElementById('codeEditor');
    if (codeEditor && slideIndex === currentSlideIndex) {
        if (codeMirrorEditor && isCodeMirrorInitialized) {
            codeMirrorEditor.setValue(htmlContent);
        } else {
            codeEditor.value = htmlContent;
        }
    }
}

function syncQuickElementAgentResult(slideIndex, htmlContent, elementId, elementPath = null) {
    const slideFrame = document.getElementById('slideFrame');
    const canSelectElement = slideFrame && slideIndex === currentSlideIndex && elementId;
    const isCurrentIframeContent = canSelectElement
        && typeof prepareHtmlForPreview === 'function'
        && slideFrame.getAttribute('data-current-content') === prepareHtmlForPreview(htmlContent);
    const shouldWaitForIframeLoad = canSelectElement && !isCurrentIframeContent;
    let selectedElement = null;
    let iframeLoadHandler = null;

    const selectAppliedElement = () => {
        const iframeDoc = slideFrame && (slideFrame.contentDocument || slideFrame.contentWindow?.document);
        if (!iframeDoc || !elementId) return null;

        let selected = iframeDoc.querySelector(`[data-quick-ai-id="${elementId}"]`);
        if (!selected && elementPath && typeof findQuickAiElementByDomPath === 'function') {
            selected = findQuickAiElementByDomPath(iframeDoc, elementPath);
            if (selected) {
                selected.setAttribute('data-quick-ai-id', elementId);
            }
        }

        if (selected && typeof selectQuickEditElement === 'function') {
            selectQuickEditElement(selected, { allowWhileAiSending: true });
        }
        return selected;
    };

    const runSelection = () => {
        selectedElement = selectAppliedElement();
        if (selectedElement && iframeLoadHandler) {
            slideFrame.removeEventListener('load', iframeLoadHandler);
            iframeLoadHandler = null;
        }
        return selectedElement;
    };

    if (shouldWaitForIframeLoad) {
        iframeLoadHandler = () => {
            iframeLoadHandler = null;
            if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
                window.requestAnimationFrame(runSelection);
            } else {
                setTimeout(runSelection, 0);
            }
        };
        slideFrame.addEventListener('load', iframeLoadHandler, { once: true });
    }

    syncAppliedSlideHtml(slideIndex, htmlContent, slidesData[slideIndex] || {});

    if (!canSelectElement) return null;

    const retrySelection = () => {
        if (!selectedElement) {
            runSelection();
        }
    };
    if (isCurrentIframeContent) {
        retrySelection();
    } else {
        setTimeout(retrySelection, 800);
        setTimeout(() => {
            retrySelection();
            if (iframeLoadHandler) {
                slideFrame.removeEventListener('load', iframeLoadHandler);
                iframeLoadHandler = null;
            }
        }, 1500);
    }
    return selectedElement;
}

async function applyAgentProposal(proposal) {
    if (!proposal || !proposal.htmlContent) {
        throw new Error('Agent 未返回可应用的方案');
    }

    const slideIndexOneBased = parseInt(
        proposal.slideIndex || (proposal.changedSlideIndices && proposal.changedSlideIndices[0]) || (currentSlideIndex + 1),
        10
    );
    const slideIndexZeroBased = slideIndexOneBased - 1;

    const response = await fetch('/api/ai/slide-edit-agent/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            proposalId: proposal.proposalId,
            projectId: window.landpptEditorConfig.projectId,
            slideIndex: slideIndexOneBased,
            expectedBaseHash: proposal.baseHash,
            htmlContent: proposal.htmlContent,
            slideData: proposal.slideData || {}
        })
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
        const detail = data.detail || data.error || `HTTP ${response.status}`;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }

    syncAppliedSlideHtml(
        slideIndexZeroBased,
        data.htmlContent || proposal.htmlContent,
        data.slideData || proposal.slideData || {}
    );
    showNotification(`Agent 更改已应用并保存：第${slideIndexOneBased}页`, 'success');
    return data;
}


