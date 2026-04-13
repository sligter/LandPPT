        function materializeFormulaNodesForExport(sourceRoot, clonedRoot) {
            if (!sourceRoot || !clonedRoot) return;

            const sourceNodes = [sourceRoot, ...Array.from(sourceRoot.querySelectorAll('*'))];
            const clonedNodes = [clonedRoot, ...Array.from(clonedRoot.querySelectorAll('*'))];
            const pairCount = Math.min(sourceNodes.length, clonedNodes.length);

            for (let i = 0; i < pairCount; i++) {
                const src = sourceNodes[i];
                const dst = clonedNodes[i];
                if (!src || !dst || dst.nodeType !== 1) continue;
                if (!isFormulaElementForExport(src)) continue;
                dst.setAttribute('data-export-formula', 'true');
                if (dst.style && typeof dst.style.setProperty === 'function') {
                    dst.style.setProperty('overflow', 'visible', 'important');
                }
            }

            tagFormulaNodesForExport(clonedRoot);
        }

        async function waitForStylesheetsReadyInContainer(container, timeoutMs = 2200) {
            if (!container || !container.querySelectorAll) return;
            const links = Array.from(container.querySelectorAll('link[rel="stylesheet"]'));
            if (links.length === 0) return;

            const waits = links.map(link => new Promise(resolve => {
                if (link.sheet) return resolve(true);
                const done = () => {
                    link.removeEventListener('load', done);
                    link.removeEventListener('error', done);
                    resolve(true);
                };
                link.addEventListener('load', done, { once: true });
                link.addEventListener('error', done, { once: true });
                setTimeout(done, timeoutMs);
            }));
            await Promise.allSettled(waits);
        }

        async function waitForImagesReadyInContainer(container, timeoutMs = 2600) {
            if (!container || !container.querySelectorAll) return;
            const images = Array.from(container.querySelectorAll('img'));
            const pending = images.filter(img => !img.complete);
            if (pending.length === 0) return;

            await Promise.race([
                Promise.allSettled(
                    pending.map(img => new Promise(resolve => {
                        const done = () => {
                            img.removeEventListener('load', done);
                            img.removeEventListener('error', done);
                            resolve(true);
                        };
                        img.addEventListener('load', done, { once: true });
                        img.addEventListener('error', done, { once: true });
                    }))
                ),
                _sleep(timeoutMs)
            ]);
        }

        function prepareSlideHtmlForExport(html) {
            let slideHtml = prepareHtmlForPreview(html || '');
            // Normalize icon classes via whitelist + fallback mapping to reduce cross-version icon drift.
            slideHtml = normalizeIconClassAttributesInHtml(slideHtml);
            slideHtml = slideHtml.replace(/(oklch|oklab|lch|lab)\([^)]*\)/gi, function (m) {
                return _toHexFallback(m);
            });
            return slideHtml;
        }

        function waitForIframeLoad(iframe, timeoutMs = 6000) {
            return new Promise((resolve, reject) => {
                let settled = false;
                const done = () => {
                    if (settled) return;
                    settled = true;
                    resolve();
                };
                const fail = (error) => {
                    if (settled) return;
                    settled = true;
                    reject(error || new Error('iframe load failed'));
                };
                iframe.onload = done;
                iframe.onerror = () => fail(new Error('iframe load failed'));
                setTimeout(done, timeoutMs);
            });
        }

        async function ensureIframeHasLatestContent(iframe, slideHtml, options = {}) {
            if (!iframe) return false;

            try {
                const forceRefresh = !!options.forceRefresh;
                const loadTimeoutMs = Number.isFinite(options.loadTimeoutMs) ? options.loadTimeoutMs : 3800;
                const visualTimeoutMs = Number.isFinite(options.visualTimeoutMs) ? options.visualTimeoutMs : 3200;
                const imageTimeoutMs = Number.isFinite(options.imageTimeoutMs) ? options.imageTimeoutMs : 3000;
                const animationSettleCapMs = Number.isFinite(options.animationSettleCapMs) ? options.animationSettleCapMs : 5500;
                const preparedHtml = prepareSlideHtmlForExport(slideHtml);
                if (forceRefresh || iframe.getAttribute('data-current-content') !== preparedHtml) {
                    await new Promise((resolve) => {
                        let settled = false;
                        const done = () => {
                            if (settled) return;
                            settled = true;
                            iframe.removeEventListener('load', done);
                            resolve();
                        };
                        iframe.addEventListener('load', done, { once: true });
                        setSafeIframeContent(iframe, preparedHtml, { force: true });
                        setTimeout(done, loadTimeoutMs);
                    });
                }

                await waitForIframeVisualReady(iframe, visualTimeoutMs, { imageTimeoutMs, animationSettleCapMs });
                const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                await waitForDocumentFontsReady(iframeDoc, 1200);
                await waitForFormulaRenderReady(iframeDoc, 2000);
                tagFormulaNodesForExport(iframeDoc.body || iframeDoc);
                return true;
            } catch (_) {
                return false;
            }
        }

        async function loadSlideIntoTempIframe(tempIframe, slideHtml) {
            const preparedHtml = prepareSlideHtmlForExport(slideHtml);
            tempIframe.srcdoc = preparedHtml;
            await waitForIframeLoad(tempIframe, 6500);
            await waitForIframeVisualReady(tempIframe, 4200, { imageTimeoutMs: 3200, animationSettleCapMs: 6000 });
            const tempDoc = tempIframe.contentDocument || tempIframe.contentWindow.document;
            await waitForDocumentFontsReady(tempDoc, 1200);
            await waitForFormulaRenderReady(tempDoc, 2200);
            tagFormulaNodesForExport(tempDoc.body || tempDoc);
        }

        function getThumbnailEntryBySlideIndex(slideIndex) {
            const thumbnail = document.querySelector(`.slide-thumbnail[data-slide-index="${slideIndex}"]`);
            if (!thumbnail) return { thumbnail: null, iframe: null };
            const iframe = thumbnail.querySelector('.slide-preview iframe, iframe');
            return { thumbnail, iframe };
        }

        async function preheatAllThumbnailIframesForExport(sortedSlides) {
            let warmed = 0;
            const total = sortedSlides.length;

            for (let i = 0; i < total; i++) {
                const item = sortedSlides[i];
                const slide = item.slide;
                const warmPct = Math.min(18, Math.round(((i + 1) / total) * 18));
                updateExportUI(null, null, null, '正在预热缩略图渲染缓存...', warmPct, '预热第 ' + (i + 1) + '/' + total + ' 页: ' + (slide.title || '幻灯片'));

                const { thumbnail, iframe } = getThumbnailEntryBySlideIndex(item.originalIndex);
                if (!thumbnail || !iframe) continue;

                try {
                    if (typeof thumbnail.scrollIntoView === 'function') {
                        thumbnail.scrollIntoView({ block: 'nearest' });
                    }
                    iframe.loading = 'eager';
                    await _sleep(50);
                    const ok = await ensureIframeHasLatestContent(iframe, slide.html_content, {
                        forceRefresh: true,
                        loadTimeoutMs: 7000,
                        visualTimeoutMs: 5200,
                        imageTimeoutMs: 4200,
                        animationSettleCapMs: 6500
                    });
                    if (ok) warmed += 1;
                } catch (e) {
                    console.warn('Thumbnail preheat failed for slide ' + (i + 1) + ':', e);
                }
            }

            return warmed;
        }

        async function getRenderedIframeForSlideIndex(slideIndex, slideHtml) {
            const { iframe: thumbIframe } = getThumbnailEntryBySlideIndex(slideIndex);
            if (thumbIframe && await ensureIframeHasLatestContent(thumbIframe, slideHtml, {
                loadTimeoutMs: 4000,
                visualTimeoutMs: 3600,
                imageTimeoutMs: 3200,
                animationSettleCapMs: 6000
            })) {
                return thumbIframe;
            }

            const mainFrame = document.getElementById('slideFrame');
            if (typeof currentSlideIndex !== 'undefined' && slideIndex === currentSlideIndex && mainFrame) {
                if (await ensureIframeHasLatestContent(mainFrame, slideHtml, {
                    loadTimeoutMs: 4000,
                    visualTimeoutMs: 3600,
                    imageTimeoutMs: 3200,
                    animationSettleCapMs: 6000
                })) {
                    return mainFrame;
                }
            }

            return null;
        }

        function replaceClonedCanvasesWithImages(sourceDoc, clonedRoot) {
            if (!sourceDoc || !clonedRoot) return;

            const sourceCanvases = Array.from(sourceDoc.querySelectorAll('canvas'));
            const clonedCanvases = Array.from(clonedRoot.querySelectorAll('canvas'));
            const pairCount = Math.min(sourceCanvases.length, clonedCanvases.length);

            for (let i = 0; i < pairCount; i++) {
                const sourceCanvas = sourceCanvases[i];
                const clonedCanvas = clonedCanvases[i];
                if (!sourceCanvas || !clonedCanvas || !clonedCanvas.parentNode) continue;

                try {
                    const dataUrl = sourceCanvas.toDataURL('image/png');
                    if (!dataUrl || dataUrl.length < 128) continue;

                    const img = document.createElement('img');
                    img.src = dataUrl;
                    img.alt = '';
                    img.className = clonedCanvas.className || '';
                    img.style.cssText = clonedCanvas.getAttribute('style') || '';
                    if (!img.style.width) img.style.width = (sourceCanvas.style.width || sourceCanvas.width + 'px');
                    if (!img.style.height) img.style.height = (sourceCanvas.style.height || sourceCanvas.height + 'px');
                    if (!img.style.display) img.style.display = 'block';

                    clonedCanvas.parentNode.replaceChild(img, clonedCanvas);
                } catch (_) {
                    // Ignore tainted/unsupported canvas and keep original clone.
                }
            }
        }

        const EXPORT_COMPUTED_STYLE_PROPS = [
            'display', 'position', 'top', 'right', 'bottom', 'left', 'z-index',
            'width', 'height', 'min-width', 'min-height', 'max-width', 'max-height',
            'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
            'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
            'box-sizing', 'overflow', 'overflow-x', 'overflow-y',
            'transform', 'transform-origin', 'opacity',
            'font-family', 'font-size', 'font-weight', 'font-style', 'line-height', 'letter-spacing',
            'text-align', 'text-transform', 'text-decoration', 'white-space', 'word-break',
            'color', 'background', 'background-color', 'background-image', 'background-size', 'background-position', 'background-repeat',
            'border', 'border-top', 'border-right', 'border-bottom', 'border-left', 'border-radius',
            'box-shadow', 'filter', 'backdrop-filter',
            'align-items', 'align-content', 'justify-content', 'justify-items',
            'flex', 'flex-direction', 'flex-wrap', 'flex-grow', 'flex-shrink', 'flex-basis', 'gap',
            'grid-template-columns', 'grid-template-rows', 'grid-column', 'grid-row',
            'object-fit', 'object-position'
        ];

        function copyComputedStylesForExport(sourceRoot, clonedRoot, sourceWindow) {
            if (!sourceRoot || !clonedRoot || !sourceWindow) return;

            const sourceNodes = [sourceRoot, ...Array.from(sourceRoot.querySelectorAll('*'))];
            const clonedNodes = [clonedRoot, ...Array.from(clonedRoot.querySelectorAll('*'))];
            const pairCount = Math.min(sourceNodes.length, clonedNodes.length);

            for (let i = 0; i < pairCount; i++) {
                const sourceNode = sourceNodes[i];
                const clonedNode = clonedNodes[i];
                if (!sourceNode || !clonedNode || !clonedNode.style) continue;
                if (clonedNode.tagName === 'SCRIPT' || clonedNode.tagName === 'STYLE') continue;

                try {
                    const computed = sourceWindow.getComputedStyle(sourceNode);
                    for (const prop of EXPORT_COMPUTED_STYLE_PROPS) {
                        const value = computed.getPropertyValue(prop);
                        if (value) clonedNode.style.setProperty(prop, value);
                    }
                } catch (_) { }
            }
        }

        function parseUniformScaleFromTransform(transformValue) {
            const raw = String(transformValue || '').trim();
            if (!raw || raw === 'none') return null;

            const matrixMatch = raw.match(/^matrix\(([^)]+)\)$/i);
            if (matrixMatch) {
                const vals = matrixMatch[1].split(',').map(v => parseFloat(v.trim()));
                if (vals.length >= 6 && vals.every(v => Number.isFinite(v))) {
                    const [a, b, c, d, e, f] = vals;
                    if (Math.abs(b) < 1e-4 && Math.abs(c) < 1e-4 && Math.abs(a - d) < 1e-3 && Math.abs(e) < 0.5 && Math.abs(f) < 0.5) {
                        return a;
                    }
                }
            }

            const matrix3dMatch = raw.match(/^matrix3d\(([^)]+)\)$/i);
            if (matrix3dMatch) {
                const vals = matrix3dMatch[1].split(',').map(v => parseFloat(v.trim()));
                if (vals.length >= 16 && vals.every(v => Number.isFinite(v))) {
                    const sx = vals[0];
                    const sy = vals[5];
                    const tx = vals[12];
                    const ty = vals[13];
                    if (Math.abs(sx - sy) < 1e-3 && Math.abs(tx) < 0.5 && Math.abs(ty) < 0.5) {
                        return sx;
                    }
                }
            }

            const scaleMatch = raw.match(/^scale\(\s*([-\d.]+)(?:\s*,\s*([-\d.]+))?\s*\)$/i);
            if (scaleMatch) {
                const sx = parseFloat(scaleMatch[1]);
                const sy = scaleMatch[2] ? parseFloat(scaleMatch[2]) : sx;
                if (Number.isFinite(sx) && Number.isFinite(sy) && Math.abs(sx - sy) < 1e-3) {
                    return sx;
                }
            }

            return null;
        }

        function neutralizeViewportFitScaleForExport(sourceRoot, clonedRoot, sourceWindow) {
            if (!sourceRoot || !clonedRoot || !sourceWindow) return;

            const sourceNodes = [sourceRoot, ...Array.from(sourceRoot.querySelectorAll('*'))];
            const clonedNodes = [clonedRoot, ...Array.from(clonedRoot.querySelectorAll('*'))];
            const pairCount = Math.min(sourceNodes.length, clonedNodes.length);

            for (let i = 0; i < pairCount; i++) {
                const src = sourceNodes[i];
                const dst = clonedNodes[i];
                if (!src || !dst || !dst.style) continue;

                let cs;
                try { cs = sourceWindow.getComputedStyle(src); } catch (_) { continue; }
                if (!cs) continue;

                const uniformScale = parseUniformScaleFromTransform(cs.transform);
                if (!Number.isFinite(uniformScale) || Math.abs(uniformScale - 1) < 0.01) continue;

                const widthPx = parseFloat(cs.width) || src.getBoundingClientRect().width;
                const heightPx = parseFloat(cs.height) || src.getBoundingClientRect().height;
                if (!(widthPx > 900 && heightPx > 500)) continue;
                const ratio = widthPx / Math.max(1, heightPx);
                if (!(ratio > 1.7 && ratio < 1.8)) continue;

                let parentLooksViewportFitter = false;
                const parent = src.parentElement;
                if (parent) {
                    try {
                        const ps = sourceWindow.getComputedStyle(parent);
                        parentLooksViewportFitter = String(ps.display || '').includes('flex') &&
                            String(ps.justifyContent || '').includes('center') &&
                            String(ps.alignItems || '').includes('center');
                    } catch (_) { }
                }

                const idLikeSlideRoot = !!(src.id && /^(slide|ppt|page|slide-container|ppt-page|page-root)$/i.test(src.id));
                if (!parentLooksViewportFitter && !idLikeSlideRoot) continue;

                // Remove viewport-fit scale (e.g. scaleSlide()) to keep 1:1 export layout.
                dst.style.setProperty('transform', 'none', 'important');
                dst.style.setProperty('transform-origin', 'center center', 'important');
            }
        }

        function buildExportContainerFromDocument(sourceDoc, container) {
            try {
                if (!sourceDoc || !sourceDoc.body || !container) return false;

                const sourceBody = sourceDoc.body;
                const sourceWindow = sourceDoc.defaultView || window;
                const styleClone = document.createElement('div');
                styleClone.style.cssText = 'width:1280px;height:720px;overflow:hidden;position:relative;';
                styleClone.setAttribute('data-export-root', 'true');

                const freezeMotionStyle = document.createElement('style');
                freezeMotionStyle.textContent = '[data-export-root="true"] *, [data-export-root="true"] *::before, [data-export-root="true"] *::after { animation: none !important; transition: none !important; }';
                styleClone.appendChild(freezeMotionStyle);

                sourceDoc.querySelectorAll('style').forEach(s => {
                    styleClone.appendChild(s.cloneNode(true));
                });

                sourceDoc.querySelectorAll('link[rel="stylesheet"]').forEach(l => {
                    styleClone.appendChild(l.cloneNode(true));
                });

                const bodyBg = sourceWindow.getComputedStyle(sourceBody).backgroundColor;
                const bodyBgImage = sourceWindow.getComputedStyle(sourceBody).backgroundImage;
                if (bodyBg && bodyBg !== 'rgba(0, 0, 0, 0)') {
                    styleClone.style.backgroundColor = bodyBg;
                }
                if (bodyBgImage && bodyBgImage !== 'none') {
                    styleClone.style.backgroundImage = bodyBgImage;
                }

                const bodyContent = sourceBody.cloneNode(true);
                copyComputedStylesForExport(sourceBody, bodyContent, sourceWindow);
                neutralizeViewportFitScaleForExport(sourceBody, bodyContent, sourceWindow);
                materializeIconPseudoContentForExport(sourceBody, bodyContent, sourceWindow);
                materializeBackgroundImagesForExport(sourceBody, bodyContent, sourceWindow);
                materializeFormulaNodesForExport(sourceBody, bodyContent);
                replaceClonedCanvasesWithImages(sourceDoc, bodyContent);
                bodyContent.style.margin = '0';
                bodyContent.style.width = '1280px';
                bodyContent.style.height = '720px';
                bodyContent.style.overflow = 'hidden';
                styleClone.appendChild(bodyContent);

                container.innerHTML = '';
                container.appendChild(styleClone);
                return true;
            } catch (_) {
                return false;
            }
        }

        const DOM_TO_PPTX_BUNDLE_VERSION = '20260405-font-resolve-v3';
        const DOM_TO_PPTX_EXPECTED_PATCH_VERSION = '2026-04-05-font-resolve-v3';
        let domToPptxReloadPromise = null;

        function isDomToPptxPatchedInstance(instance) {
            if (!instance || typeof instance.exportToPptx !== 'function') return false;
            const patchVersion = String(instance.__landpptPatchVersion || '').trim();
            if (patchVersion === DOM_TO_PPTX_EXPECTED_PATCH_VERSION) return true;
            return false;
        }

        async function loadDomToPptxBundle(force = false) {
            if (!force && isDomToPptxPatchedInstance(window.domToPptx)) {
                return window.domToPptx;
            }
            if (domToPptxReloadPromise) return domToPptxReloadPromise;

            domToPptxReloadPromise = new Promise((resolve, reject) => {
                const script = document.createElement('script');
                const cacheBust = Date.now().toString();
                script.src = `/static/js/dom-to-pptx.bundle.js?v=${encodeURIComponent(DOM_TO_PPTX_BUNDLE_VERSION)}&ts=${cacheBust}`;
                script.async = true;

                let settled = false;
                const finish = (ok, err) => {
                    if (settled) return;
                    settled = true;
                    domToPptxReloadPromise = null;
                    if (ok) resolve(window.domToPptx);
                    else reject(err || new Error('无法加载最新 PPTX 导出库'));
                };

                script.onload = () => {
                    if (isDomToPptxPatchedInstance(window.domToPptx)) {
                        finish(true);
                        return;
                    }
                    finish(false, new Error('导出库版本未更新，请刷新页面后重试'));
                };
                script.onerror = () => finish(false, new Error('加载 PPTX 导出库失败，请检查网络后重试'));

                document.head.appendChild(script);
                setTimeout(() => {
                    if (!settled) finish(false, new Error('加载 PPTX 导出库超时'));
                }, 12000);
            });

            return domToPptxReloadPromise;
        }

        async function ensureDomToPptxReadyForExport() {
            if (isDomToPptxPatchedInstance(window.domToPptx)) {
                return window.domToPptx;
            }
            return loadDomToPptxBundle(true);
        }

