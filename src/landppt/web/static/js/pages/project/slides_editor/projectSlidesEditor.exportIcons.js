        async function refreshIconExportRules(force = false) {
            if (!force && runtimeIconExportRulesFetchPromise) {
                return runtimeIconExportRulesFetchPromise;
            }

            const run = (async () => {
                try {
                    const response = await fetch('/static/config/icon-export-rules.json?ts=' + Date.now(), {
                        cache: 'no-store'
                    });
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    const payload = await response.json();
                    runtimeIconExportRulesRaw = sanitizeIconExportRules(payload);
                    runtimeIconExportRulesCompiled = null;
                } catch (err) {
                    console.warn('Failed to load icon export rules JSON, using default rules:', err);
                    if (!runtimeIconExportRulesRaw) {
                        runtimeIconExportRulesRaw = sanitizeIconExportRules(null);
                        runtimeIconExportRulesCompiled = null;
                    }
                } finally {
                    runtimeIconExportRulesFetchPromise = null;
                }

                if (typeof window !== 'undefined') {
                    window.__LANDPPT_ICON_EXPORT_RULES__ = getCompiledIconExportRules().rawRules;
                }
                return getCompiledIconExportRules().rawRules;
            })();

            runtimeIconExportRulesFetchPromise = run;
            return run;
        }

        if (typeof window !== 'undefined') {
            window.refreshIconExportRules = refreshIconExportRules;
        }

        function isWhitelistedExportIconClassToken(token) {
            const compiledRules = getCompiledIconExportRules();
            const t = String(token || '').trim().toLowerCase();
            if (!t) return false;
            if (compiledRules.classTokenWhitelistSet.has(t)) return true;
            return compiledRules.classPrefixWhitelist.some(prefix => t.startsWith(prefix));
        }

        function normalizeIconClassAttributeValue(classValue) {
            const compiledRules = getCompiledIconExportRules();
            const raw = String(classValue || '').trim();
            if (!raw) return '';

            const rawTokens = raw.split(/\s+/).filter(Boolean);
            const normalizedTokens = [];
            let hasFontAwesomeToken = false;

            for (const token of rawTokens) {
                const tokenLower = String(token).toLowerCase();
                const looksLikeIconToken = /^(fa|bi|material|ri|ti|ph|mdi|icon)/i.test(tokenLower);
                const isFaToken =
                    /^(fa|fas|far|fab|fal|fad|fat|fa-solid|fa-regular|fa-brands|fa-light|fa-duotone|fa-thin)$/i.test(tokenLower) ||
                    /^fa-[\w-]+$/i.test(tokenLower);

                let nextToken = token;
                if (isFaToken) {
                    hasFontAwesomeToken = true;
                    nextToken = compiledRules.faStyleClassAliases[tokenLower] || tokenLower;
                    nextToken = compiledRules.faClassFallbacks[nextToken] || nextToken;
                }

                if (looksLikeIconToken && !isWhitelistedExportIconClassToken(nextToken)) {
                    nextToken = token;
                }
                if (!normalizedTokens.includes(nextToken)) {
                    normalizedTokens.push(nextToken);
                }
            }

            if (hasFontAwesomeToken) {
                const isBrand = normalizedTokens.some(t => t === 'fab' || t === 'fa-brands');
                const isRegular = normalizedTokens.some(t => t === 'far' || t === 'fa-regular');
                const hasFaIconToken = normalizedTokens.some(t => /^fa-[\w-]+$/.test(t) && !compiledRules.faStyleClassTokensSet.has(t));
                if (!hasFaIconToken) {
                    const fallbackToken = isBrand
                        ? compiledRules.faDefaultFallbackByStyle.brand
                        : isRegular
                            ? compiledRules.faDefaultFallbackByStyle.regular
                            : compiledRules.faDefaultFallbackByStyle.solid;
                    if (fallbackToken && !normalizedTokens.includes(fallbackToken)) {
                        normalizedTokens.push(fallbackToken);
                    }
                }
            }

            if (normalizedTokens.length === 0) return raw;
            return normalizedTokens.join(' ');
        }

        function normalizeIconClassAttributesInHtml(html) {
            return String(html || '').replace(/class\s*=\s*(["'])(.*?)\1/gi, function (_, quote, classValue) {
                const normalizedClass = normalizeIconClassAttributeValue(classValue);
                return 'class=' + quote + normalizedClass + quote;
            });
        }

        function hasFontAwesomeLikeClass(className) {
            if (!className) return false;
            const normalized = normalizeIconClassAttributeValue(className);
            return /(^|\s)(fa|fas|far|fab|fal|fad|fat|fa-solid|fa-regular|fa-brands|fa-light|fa-duotone|fa-thin)(\s|$)|fa-[\w-]+/.test(normalized);
        }

        function cleanupFontAwesomeClasses(node) {
            if (!node || !node.classList) return;
            Array.from(node.classList).forEach(cls => {
                if (/^(fa|fas|far|fab|fal|fad|fat|fa-solid|fa-regular|fa-brands|fa-light|fa-duotone|fa-thin)$/i.test(cls) || /^fa-/i.test(cls)) {
                    node.classList.remove(cls);
                }
            });
            if (!node.className) node.removeAttribute('class');
        }

        function parsePxValue(rawValue, fallback = 0) {
            const parsed = parseFloat(String(rawValue || '').trim());
            return Number.isFinite(parsed) ? parsed : fallback;
        }

        function rasterizeFontAwesomeIconToDataUrl(iconText, styleRef, sourceStyle, sourceWindow, widthPx, heightPx, sourceClassName = '') {
            if (!iconText || !sourceWindow || !sourceWindow.document) return null;
            try {
                const doc = sourceWindow.document;
                const canvas = doc.createElement('canvas');
                const dprRaw = Number(sourceWindow.devicePixelRatio || window.devicePixelRatio || 1);
                const dpr = Number.isFinite(dprRaw) ? Math.min(3, Math.max(1, dprRaw)) : 1;
                const targetWidth = Math.max(1, Math.round(widthPx));
                const targetHeight = Math.max(1, Math.round(heightPx));

                canvas.width = Math.max(1, Math.round(targetWidth * dpr));
                canvas.height = Math.max(1, Math.round(targetHeight * dpr));
                const ctx = canvas.getContext('2d');
                if (!ctx) return null;

                ctx.scale(dpr, dpr);
                ctx.clearRect(0, 0, targetWidth, targetHeight);

                const className = normalizeIconClassAttributeValue(sourceClassName || '');
                const isBrand = /(^|\s)(fab|fa-brands)(\s|$)/.test(className);
                const isRegular = /(^|\s)(far|fa-regular)(\s|$)/.test(className);

                let fontFamily = (styleRef && styleRef.getPropertyValue('font-family')) ||
                    (sourceStyle && sourceStyle.getPropertyValue('font-family')) ||
                    (isBrand ? '"Font Awesome 6 Brands"' : '"Font Awesome 6 Free"');
                if (isBrand) {
                    if (!/font awesome 6 brands/i.test(String(fontFamily))) {
                        fontFamily = '"Font Awesome 6 Brands"';
                    }
                } else if (!fontFamily || /font awesome 6 brands/i.test(String(fontFamily))) {
                    fontFamily = '"Font Awesome 6 Free"';
                }

                let fontWeight = (styleRef && styleRef.getPropertyValue('font-weight')) ||
                    (sourceStyle && sourceStyle.getPropertyValue('font-weight')) ||
                    (isBrand || isRegular ? '400' : '900');
                if (!fontWeight || String(fontWeight) === '0') {
                    fontWeight = isBrand || isRegular ? '400' : '900';
                }
                const fontStyle = (styleRef && styleRef.getPropertyValue('font-style')) ||
                    (sourceStyle && sourceStyle.getPropertyValue('font-style')) ||
                    'normal';
                const color = (styleRef && styleRef.getPropertyValue('color')) ||
                    (sourceStyle && sourceStyle.getPropertyValue('color')) ||
                    '#000000';
                const sourceFontSize = parsePxValue(
                    (styleRef && styleRef.getPropertyValue('font-size')) ||
                    (sourceStyle && sourceStyle.getPropertyValue('font-size')),
                    16
                );
                const fontSize = Math.max(10, Math.min(sourceFontSize, targetHeight * 0.98));

                ctx.fillStyle = color;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.font = fontStyle + ' ' + fontWeight + ' ' + fontSize + 'px ' + fontFamily;
                ctx.fillText(iconText, targetWidth / 2, targetHeight / 2);

                const dataUrl = canvas.toDataURL('image/png');
                return dataUrl && dataUrl.length > 100 ? dataUrl : null;
            } catch (_) {
                return null;
            }
        }

        function materializeIconPseudoContentForExport(sourceRoot, clonedRoot, sourceWindow) {
            if (!sourceRoot || !clonedRoot || !sourceWindow) return;
            const sourceNodes = [sourceRoot, ...Array.from(sourceRoot.querySelectorAll('*'))];
            const clonedNodes = [clonedRoot, ...Array.from(clonedRoot.querySelectorAll('*'))];
            const pairCount = Math.min(sourceNodes.length, clonedNodes.length);

            for (let i = 0; i < pairCount; i++) {
                const src = sourceNodes[i];
                const dst = clonedNodes[i];
                if (!src || !dst || !dst.style) continue;
                const rawCls = src.getAttribute && src.getAttribute('class');
                const cls = normalizeIconClassAttributeValue(rawCls || '');
                if (cls && rawCls && cls !== rawCls && src.className !== undefined) {
                    src.className = cls;
                }
                const tag = src.tagName ? src.tagName.toUpperCase() : '';
                if (!(hasFontAwesomeLikeClass(cls) || tag === 'I')) continue;
                if ((dst.textContent || '').trim()) continue;

                let beforeStyle = null;
                let afterStyle = null;
                try { beforeStyle = sourceWindow.getComputedStyle(src, '::before'); } catch (_) { }
                try { afterStyle = sourceWindow.getComputedStyle(src, '::after'); } catch (_) { }

                const beforeText = decodeCssContentText(beforeStyle && beforeStyle.content);
                const afterText = decodeCssContentText(afterStyle && afterStyle.content);
                const iconText = beforeText || afterText;
                if (!iconText) continue;

                const styleRef = beforeText ? beforeStyle : afterStyle;
                let sourceStyle = null;
                try { sourceStyle = sourceWindow.getComputedStyle(src); } catch (_) { }

                const srcRect = src.getBoundingClientRect ? src.getBoundingClientRect() : { width: 0, height: 0 };
                const fallbackFontSize = parsePxValue(
                    (styleRef && styleRef.getPropertyValue('font-size')) ||
                    (sourceStyle && sourceStyle.getPropertyValue('font-size')),
                    16
                );
                let iconWidth = Math.max(1, Math.round(srcRect.width || 0));
                let iconHeight = Math.max(1, Math.round(srcRect.height || 0));
                if (iconWidth < 2) iconWidth = Math.max(12, Math.round(fallbackFontSize * 1.15));
                if (iconHeight < 2) iconHeight = Math.max(12, Math.round(fallbackFontSize * 1.15));

                const iconDataUrl = rasterizeFontAwesomeIconToDataUrl(
                    iconText,
                    styleRef,
                    sourceStyle,
                    sourceWindow,
                    iconWidth,
                    iconHeight,
                    cls
                );

                cleanupFontAwesomeClasses(dst);
                dst.textContent = '';

                if (iconDataUrl) {
                    dst.style.setProperty('display', 'inline-flex');
                    dst.style.setProperty('align-items', 'center');
                    dst.style.setProperty('justify-content', 'center');
                    dst.style.setProperty('line-height', '1');
                    dst.style.setProperty('vertical-align', 'middle');
                    dst.style.setProperty('width', iconWidth + 'px');
                    dst.style.setProperty('height', iconHeight + 'px');

                    const iconImg = document.createElement('img');
                    iconImg.src = iconDataUrl;
                    iconImg.alt = '';
                    iconImg.setAttribute('data-export-fa-rasterized', 'true');
                    iconImg.style.width = '100%';
                    iconImg.style.height = '100%';
                    iconImg.style.display = 'block';
                    iconImg.style.objectFit = 'contain';
                    dst.appendChild(iconImg);
                    dst.setAttribute('data-export-icon-materialized', 'true');
                    continue;
                }

                dst.textContent = iconText;
                if (styleRef) {
                    const iconProps = ['font-family', 'font-weight', 'font-style', 'font-size', 'line-height', 'color', 'display'];
                    for (const prop of iconProps) {
                        const value = styleRef.getPropertyValue(prop);
                        if (value) dst.style.setProperty(prop, value);
                    }
                }
                dst.style.setProperty('line-height', '1');
                dst.style.setProperty('vertical-align', 'middle');
                dst.setAttribute('data-export-icon-materialized', 'true');
            }
        }

        function extractFirstUrlFromBackgroundImage(bgValue, sourceWindow) {
            if (!bgValue || !/url\s*\(/i.test(bgValue)) return null;
            const match = /url\s*\(\s*(['"]?)(.*?)\1\s*\)/i.exec(bgValue);
            if (!match || !match[2]) return null;
            const rawUrl = match[2].trim();
            if (!rawUrl) return null;
            try {
                return new URL(rawUrl, sourceWindow.location.href).href;
            } catch (_) {
                return rawUrl;
            }
        }

        function inferObjectFitFromBackgroundSize(bgSize) {
            const s = String(bgSize || '').toLowerCase();
            if (s.includes('contain')) return 'contain';
            if (s.includes('cover')) return 'cover';
            if (s.includes('100% 100%') || s.includes('100%')) return 'fill';
            return 'cover';
        }

        function materializeBackgroundImagesForExport(sourceRoot, clonedRoot, sourceWindow) {
            if (!sourceRoot || !clonedRoot || !sourceWindow) return;
            const sourceNodes = [sourceRoot, ...Array.from(sourceRoot.querySelectorAll('*'))];
            const clonedNodes = [clonedRoot, ...Array.from(clonedRoot.querySelectorAll('*'))];
            const pairCount = Math.min(sourceNodes.length, clonedNodes.length);

            for (let i = 0; i < pairCount; i++) {
                const src = sourceNodes[i];
                const dst = clonedNodes[i];
                if (!src || !dst || !dst.style) continue;

                let srcStyle;
                try { srcStyle = sourceWindow.getComputedStyle(src); } catch (_) { continue; }
                const bgImage = srcStyle.getPropertyValue('background-image');
                if (!bgImage || !/url\s*\(/i.test(bgImage)) continue;

                // Keep complex multi-layer backgrounds as-is; only materialize simple URL backgrounds.
                if (bgImage.includes('gradient(') && bgImage.includes('url(')) continue;

                const hasChildren = dst.children && dst.children.length > 0;
                const hasText = !!(dst.textContent && dst.textContent.trim());
                if (hasChildren || hasText) continue;

                const imageUrl = extractFirstUrlFromBackgroundImage(bgImage, sourceWindow);
                if (!imageUrl) continue;

                const img = document.createElement('img');
                img.src = imageUrl;
                img.alt = '';
                img.setAttribute('data-export-bg-image', 'true');
                img.style.width = '100%';
                img.style.height = '100%';
                img.style.display = 'block';
                img.style.objectFit = inferObjectFitFromBackgroundSize(srcStyle.getPropertyValue('background-size'));
                img.style.objectPosition = srcStyle.getPropertyValue('background-position') || '50% 50%';

                dst.style.setProperty('background-image', 'none');
                dst.style.setProperty('background', 'none');
                dst.appendChild(img);
            }
        }

        const EXPORT_FORMULA_SELECTOR = [
            '[data-export-formula="true"]',
            'mjx-container',
            '.MathJax',
            '.MathJax_Display',
            '.katex',
            '.katex-display',
            '.katex-inline',
            'math',
            '[data-latex]',
            '[data-tex]',
            '[data-formula]',
            '[data-equation]',
            '[data-math]',
            '[data-mathml]',
            '[data-asciimath]'
        ].join(', ');

        function isFormulaElementForExport(node) {
            if (!node || node.nodeType !== 1 || typeof node.matches !== 'function') return false;
            if (node.getAttribute('data-export-formula') === 'true') return true;
            try {
                return node.matches(EXPORT_FORMULA_SELECTOR);
            } catch (_) {
                return false;
            }
        }

        function collectFormulaRootsForExport(root) {
            if (!root || typeof root.querySelectorAll !== 'function') return [];

            const candidates = [];
            if (root.nodeType === 1 && isFormulaElementForExport(root)) {
                candidates.push(root);
            }
            candidates.push(...Array.from(root.querySelectorAll(EXPORT_FORMULA_SELECTOR)));

            const deduped = [];
            const seen = new Set();
            for (const node of candidates) {
                if (!node || node.nodeType !== 1 || seen.has(node)) continue;
                seen.add(node);

                let formulaRoot = node;
                if (formulaRoot.tagName && formulaRoot.tagName.toUpperCase() === 'ANNOTATION') {
                    const parentMath = formulaRoot.closest('math, mjx-container, .MathJax, .MathJax_Display, .katex, .katex-display, .katex-inline');
                    if (parentMath) {
                        formulaRoot = parentMath;
                    }
                }

                const parentFormula = formulaRoot.parentElement && formulaRoot.parentElement.closest(EXPORT_FORMULA_SELECTOR);
                if (parentFormula) continue;
                deduped.push(formulaRoot);
            }
            return deduped;
        }

        function tagFormulaNodesForExport(root) {
            const formulaRoots = collectFormulaRootsForExport(root);
            formulaRoots.forEach(node => {
                if (!node || node.nodeType !== 1) return;
                node.setAttribute('data-export-formula', 'true');
                if (node.style && typeof node.style.setProperty === 'function') {
                    node.style.setProperty('overflow', 'visible', 'important');
                }
            });
            return formulaRoots;
        }

        function isFormulaNodeRenderable(node) {
            if (!node || node.nodeType !== 1) return false;
            let style = null;
            try {
                const ownerWin = (node.ownerDocument && node.ownerDocument.defaultView) || window;
                style = ownerWin.getComputedStyle(node);
            } catch (_) { }

            if (style && (style.display === 'none' || style.visibility === 'hidden')) {
                return false;
            }

            const rect = typeof node.getBoundingClientRect === 'function'
                ? node.getBoundingClientRect()
                : { width: 0, height: 0 };
            if (rect.width > 1 && rect.height > 1) return true;

            if (typeof node.querySelector === 'function') {
                const svg = node.querySelector('svg, mjx-container svg');
                if (svg && typeof svg.getBoundingClientRect === 'function') {
                    const svgRect = svg.getBoundingClientRect();
                    if (svgRect.width > 1 && svgRect.height > 1) return true;
                }
            }

            return false;
        }

        async function waitForFormulaRenderReady(doc, timeoutMs = 2600) {
            if (!doc || !doc.body) return;
            const docRoot = doc.body || doc.documentElement || doc;
            const docWin = doc.defaultView || window;

            try {
                const mathJax = docWin.MathJax;
                if (mathJax && mathJax.startup && mathJax.startup.promise) {
                    await Promise.race([
                        Promise.resolve(mathJax.startup.promise).catch(() => null),
                        _sleep(Math.min(timeoutMs, 1800))
                    ]);
                }
            } catch (_) { }

            let formulas = tagFormulaNodesForExport(docRoot);
            if (formulas.length === 0) return;

            const deadline = Date.now() + timeoutMs;
            while (Date.now() < deadline) {
                formulas = tagFormulaNodesForExport(docRoot);
                if (formulas.length === 0) return;
                if (formulas.every(isFormulaNodeRenderable)) {
                    await waitForAnimationFrames(docWin, 1);
                    break;
                }
                await waitForAnimationFrames(docWin, 1);
                await _sleep(80);
            }

            tagFormulaNodesForExport(docRoot);
        }

