"""度量 HTML 页：用 Playwright 在 1280×720 渲染，读取元素包围盒后交给同一批几何函数。

    uv run python -m scripts.svg_experiment.measure_html <file-or-dir>... --out results/html

HTML 组没有 data-role，标题/页脚按 header/footer 元素或页面上下 15% 的文字推断；
文本超框取 scrollWidth/scrollHeight 超出 client 尺寸；压叠只算文字对文字、文字对图片，
且排除祖先-后代关系。这些都是启发式，报告里保留原始矩形供复核。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

from .common import (
    PageMeasurement,
    boxes_from_rects,
    geometry_defects,
    geometry_metrics,
    iter_pages,
)

COLLECT_JS = r"""
() => {
  const W = 1280, H = 720;
  const rects = [];
  const els = Array.from(document.body.querySelectorAll('*'));
  const blockish = new Set(['block','flex','grid','inline-block','inline-flex','inline-grid','list-item','table','table-cell']);
  const texts = [];
  els.forEach((el, index) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const opacity = parseFloat(cs.opacity || '1');
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    const tag = el.tagName.toLowerCase();
    if (tag === 'html' || tag === 'body' || tag === 'script' || tag === 'style') return;
    const ownText = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.replace(/\s+/g, ' ').trim()).join(' ').trim();
    const isMedia = ['img','svg','canvas','video','picture'].includes(tag);
    const bg = cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent';
    const border = ['Top','Right','Bottom','Left'].some(side => parseFloat(cs['border' + side + 'Width'] || '0') > 0 && cs['border' + side + 'Style'] !== 'none');
    const bgImage = cs.backgroundImage && cs.backgroundImage !== 'none';
    const isBox = bg || border || bgImage || parseFloat(cs.boxShadow === 'none' ? '0' : '1') > 0;
    if (!ownText && !isMedia && !isBox) return;
    const inHeader = !!el.closest('header,[data-role="title"],h1');
    const inFooter = !!el.closest('footer,[data-role="footer"]');
    let role = inHeader ? 'title' : inFooter ? 'footer' : '';
    if (!role && ownText) {
      if (r.bottom <= H * 0.15) role = 'title';
      else if (r.top >= H * 0.92) role = 'footer';
    }
    const overflow = !!ownText && blockish.has(cs.display) && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1);
    const rect = {
      path: tag + '#' + index, id: el.id || '', tag, x0: r.left, y0: r.top, x1: r.right, y1: r.bottom,
      text: ownText.slice(0, 60), is_text: !!ownText, is_media: isMedia, is_box: !!isBox && !ownText,
      font_size: parseFloat(cs.fontSize) || 0, opacity, role, overflow,
    };
    rects.push(rect);
    if (ownText && opacity > 0.15) texts.push({ el, rect });
  });
  const overlaps = [];
  for (let i = 0; i < texts.length; i++) {
    for (let j = i + 1; j < texts.length; j++) {
      const a = texts[i], b = texts[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const x0 = Math.max(a.rect.x0, b.rect.x0), y0 = Math.max(a.rect.y0, b.rect.y0);
      const x1 = Math.min(a.rect.x1, b.rect.x1), y1 = Math.min(a.rect.y1, b.rect.y1);
      if (x1 <= x0 || y1 <= y0) continue;
      const inter = (x1 - x0) * (y1 - y0);
      const smaller = Math.min((a.rect.x1 - a.rect.x0) * (a.rect.y1 - a.rect.y0), (b.rect.x1 - b.rect.x0) * (b.rect.y1 - b.rect.y0)) || 1;
      if (inter / smaller >= 0.04) {
        overlaps.push({ a: a.rect.path, b: b.rect.path, a_text: a.rect.text.slice(0, 40), b_kind: b.rect.tag, area: Math.round(inter), bbox: [Math.round(x0), Math.round(y0), Math.round(x1), Math.round(y1)] });
      }
    }
  }
  return { rects, overlaps, canvas: { w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight } };
}
"""


def measure_html_file(page, path: Path) -> PageMeasurement:
    page.set_viewport_size({"width": 1280, "height": 720})
    page.goto(path.resolve().as_uri(), wait_until="load")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(600)
    data: Dict = page.evaluate(COLLECT_JS)
    boxes = boxes_from_rects(data["rects"])
    defects = geometry_defects(boxes, data.get("overlaps"))
    for rect in data["rects"]:
        if rect.get("overflow"):
            defects.append(
                {
                    "type": "text_overflow",
                    "id": rect["path"],
                    "text": rect.get("text", ""),
                    "bbox": [
                        int(rect["x0"]),
                        int(rect["y0"]),
                        int(rect["x1"]),
                        int(rect["y1"]),
                    ],
                }
            )
    measurement = PageMeasurement(source=str(path), render_mode="html", defects=defects)
    measurement.metrics = geometry_metrics(boxes, defects)
    measurement.metrics["scroll_canvas"] = data.get("canvas")
    measurement.metrics["rects"] = data["rects"]
    return measurement


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--out", default="results/html")
    args = parser.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright is required: uv run playwright install chromium",
            file=sys.stderr,
        )
        return 2

    files = [p for p in iter_pages(args.paths, (".html", ".htm"))]
    if not files:
        print("no html pages found", file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        for path in files:
            measurement = measure_html_file(page, path)
            measurement.write(out_dir / (path.stem + ".json"))
            signals = measurement.signals
            print(
                f"{path.name}: blocking={measurement.metrics.get('blocking_count')} overlap={signals['overlap']} "
                f"out={signals['out_of_canvas']} overflow={signals['text_overflow']} empty_band={signals['empty_band']} "
                f"equal_rects={signals['equal_rect_group']} coverage={measurement.metrics.get('stage_coverage')}"
            )
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
