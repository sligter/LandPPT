import { prepareWithSegments, layoutWithLines } from '../../../vendor/pretext/layout.js';

function parsePixels(value, fallback = 0) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function buildCanvasFont(style) {
  const fontStyle = style.fontStyle && style.fontStyle !== 'normal' ? `${style.fontStyle} ` : '';
  const fontWeight = style.fontWeight && style.fontWeight !== 'normal' ? `${style.fontWeight} ` : '';
  const fontSize = style.fontSize || '13px';
  const fontFamily = style.fontFamily || 'Consolas, Monaco, "Courier New", monospace';
  return `${fontStyle}${fontWeight}${fontSize} ${fontFamily}`.trim();
}

export function createOutlineStreamPretextRenderer(container) {
  if (!(container instanceof HTMLElement)) {
    throw new Error('outline stream container is required');
  }

  container.replaceChildren();

  const stage = document.createElement('div');
  stage.className = 'outline-stream-pretext-stage';
  container.appendChild(stage);

  const lineNodes = [];
  let text = '';
  let lastText = null;
  let lastWidth = -1;
  let lastFont = '';
  let lastLineHeight = -1;
  let renderFrame = null;

  function syncLinePool(nextLength) {
    while (lineNodes.length < nextLength) {
      const lineNode = document.createElement('div');
      lineNode.className = 'outline-stream-pretext-line';
      stage.appendChild(lineNode);
      lineNodes.push(lineNode);
    }

    while (lineNodes.length > nextLength) {
      const lineNode = lineNodes.pop();
      if (lineNode) {
        lineNode.remove();
      }
    }
  }

  function renderNow() {
    renderFrame = null;

    const width = container.clientWidth;
    if (width <= 2) {
      return;
    }

    const style = window.getComputedStyle(container);
    const paddingLeft = parsePixels(style.paddingLeft);
    const paddingRight = parsePixels(style.paddingRight);
    const paddingTop = parsePixels(style.paddingTop);
    const paddingBottom = parsePixels(style.paddingBottom);
    const lineHeight = parsePixels(
      style.lineHeight,
      Math.round(parsePixels(style.fontSize, 13) * 1.7)
    );
    const font = buildCanvasFont(style);
    const availableWidth = Math.max(1, width - paddingLeft - paddingRight);

    if (
      text === lastText &&
      availableWidth === lastWidth &&
      font === lastFont &&
      lineHeight === lastLineHeight
    ) {
      return;
    }

    lastText = text;
    lastWidth = availableWidth;
    lastFont = font;
    lastLineHeight = lineHeight;

    if (!text) {
      syncLinePool(0);
      stage.style.height = `${Math.max(0, Math.ceil(paddingTop + paddingBottom))}px`;
      return;
    }

    // 直接用 pretext 计算换行，避免依赖浏览器对容器内容做同步回流测量。
    const prepared = prepareWithSegments(text, font, { whiteSpace: 'pre-wrap' });
    const layoutResult = layoutWithLines(prepared, availableWidth, lineHeight);
    const lines = layoutResult.lines;

    syncLinePool(lines.length);
    stage.style.height = `${Math.max(0, Math.ceil(layoutResult.height + paddingTop + paddingBottom))}px`;

    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const lineNode = lineNodes[index];
      if (!line || !lineNode) {
        continue;
      }

      lineNode.textContent = line.text.length > 0 ? line.text : '\u00A0';
      lineNode.style.transform = `translate(${Math.round(paddingLeft)}px, ${Math.round(paddingTop + index * lineHeight)}px)`;
      lineNode.style.maxWidth = `${Math.ceil(availableWidth)}px`;
    }
  }

  function scheduleRender() {
    if (renderFrame !== null) {
      return;
    }

    renderFrame = window.requestAnimationFrame(() => {
      renderNow();
    });
  }

  const resizeObserver = typeof ResizeObserver !== 'undefined'
    ? new ResizeObserver(() => {
        scheduleRender();
      })
    : null;

  resizeObserver?.observe(container);

  let fontsListenerBound = false;
  const fontSet = document.fonts;
  if (fontSet && typeof fontSet.addEventListener === 'function') {
    fontSet.addEventListener('loadingdone', scheduleRender);
    fontsListenerBound = true;
  } else if (fontSet?.ready && typeof fontSet.ready.then === 'function') {
    fontSet.ready.then(() => {
      scheduleRender();
    }).catch(() => {});
  }

  return {
    setText(nextText) {
      text = typeof nextText === 'string' ? nextText : String(nextText ?? '');
      renderNow();
    },
    refresh() {
      lastWidth = -1;
      renderNow();
    },
    destroy() {
      if (renderFrame !== null) {
        window.cancelAnimationFrame(renderFrame);
        renderFrame = null;
      }

      resizeObserver?.disconnect();

      if (fontsListenerBound && fontSet && typeof fontSet.removeEventListener === 'function') {
        fontSet.removeEventListener('loadingdone', scheduleRender);
      }
    },
  };
}
