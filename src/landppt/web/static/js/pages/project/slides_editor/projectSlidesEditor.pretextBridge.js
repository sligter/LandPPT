(function () {
    const MODULE_URL = '/static/js/pages/project/slides_editor/projectSlidesEditor.pretextStreamRenderer.js?v=20260406-pretext';
    const rendererMap = new WeakMap();
    let rendererFactoryPromise = null;

    function normalizeText(value) {
        return typeof value === 'string' ? value : String(value ?? '');
    }

    function loadRendererFactory() {
        if (!rendererFactoryPromise) {
            rendererFactoryPromise = import(MODULE_URL).then((mod) => {
                if (typeof mod.createAiStreamPretextRenderer !== 'function') {
                    throw new Error('Missing createAiStreamPretextRenderer');
                }
                return mod.createAiStreamPretextRenderer;
            });
        }
        return rendererFactoryPromise;
    }

    function ensureAssistantMessageContent(messageDiv) {
        if (!(messageDiv instanceof HTMLElement)) {
            return null;
        }

        let contentDiv = messageDiv.querySelector('.ai-message-content');
        if (!contentDiv) {
            contentDiv = document.createElement('div');
            contentDiv.className = 'ai-message-content';
            messageDiv.insertBefore(contentDiv, messageDiv.firstChild);
        }

        contentDiv.classList.add('ai-pretext-message-content');
        return contentDiv;
    }

    function createDeferredRenderer(contentDiv) {
        let liveRenderer = null;
        let latestText = '';
        let destroyed = false;
        let pendingRefresh = false;

        loadRendererFactory().then((factory) => {
            if (destroyed) {
                return;
            }

            liveRenderer = factory(contentDiv);
            liveRenderer.setText(latestText);
            if (pendingRefresh) {
                liveRenderer.refresh();
            }
        }).catch((error) => {
            console.error('pretext renderer load failed', error);
        });

        return {
            setText(nextText) {
                latestText = normalizeText(nextText);
                if (liveRenderer) {
                    liveRenderer.setText(latestText);
                }
            },
            refresh() {
                pendingRefresh = true;
                if (liveRenderer) {
                    liveRenderer.refresh();
                }
            },
            destroy() {
                destroyed = true;
                if (liveRenderer) {
                    liveRenderer.destroy();
                }
                rendererMap.delete(contentDiv);
            },
        };
    }

    function getRenderer(contentDiv) {
        if (!(contentDiv instanceof HTMLElement)) {
            return null;
        }

        let renderer = rendererMap.get(contentDiv);
        if (!renderer) {
            renderer = createDeferredRenderer(contentDiv);
            rendererMap.set(contentDiv, renderer);
        }
        return renderer;
    }

    window.projectSlidesEditorPretext = {
        ensureAssistantMessageContent,
        setAssistantMessageText(messageDiv, text) {
            const contentDiv = ensureAssistantMessageContent(messageDiv);
            const renderer = getRenderer(contentDiv);
            renderer?.setText(text);
            return contentDiv;
        },
        refreshAssistantMessageLayout(messageDiv) {
            const contentDiv = ensureAssistantMessageContent(messageDiv);
            const renderer = getRenderer(contentDiv);
            renderer?.refresh();
            return contentDiv;
        },
        destroyAssistantMessageRender(messageDiv) {
            if (!(messageDiv instanceof HTMLElement)) {
                return;
            }

            const contentDiv = messageDiv.querySelector('.ai-message-content');
            const renderer = contentDiv ? rendererMap.get(contentDiv) : null;
            renderer?.destroy();
        },
    };

    loadRendererFactory().catch(() => { });
})();
