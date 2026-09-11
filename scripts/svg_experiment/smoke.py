"""Offline rendering smoke test, using synthetic fixtures (no model quality claims).

uv run python -m scripts.svg_experiment.smoke --out artifacts/svg-mode-verification/smoke
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from landppt.services.slide.svg_page import build_slide_html, process_svg_candidate

from .measure_html import measure_html_file
from .measure_svg import measure_svg_file


def fixtures():
    return {
        "cover": (
            "SVG 页面绘制",
            '<text x="100" y="370" font-size="72" fill="#f8fafc">让内容决定构图</text><use href="#ic-star" x="1040" y="265" width="100" height="100" color="#38bdf8"/>',
        ),
        "text": (
            "中英混排与确定性换行",
            '<text x="100" y="230" font-size="30" fill="#f8fafc" data-box-w="750" data-box-h="330">中文与 English terminology 可以一起分行。超长单词 Supercalifragilisticexpialidocious 也应完整保留。先说明结论，再呈现依据，最后解释下一步行动。这里是合成验证内容，不代表模型生成质量。</text>',
        ),
        "flow": (
            "步骤之间的关系",
            "".join(
                f'<circle cx="{180+i*400}" cy="325" r="56" fill="#075985"/><text x="{180+i*400}" y="335" font-size="28" text-anchor="middle" fill="#fff">{label}</text>'
                + (
                    f'<path d="M {250+i*400} 325 H {495+i*400} l -18 -12 m 18 12 l -18 12" fill="none" stroke="#38bdf8" stroke-width="4"/>'
                    if i < 2
                    else ""
                )
                for i, label in enumerate(["准备", "执行", "验证"])
            ),
        ),
        "compare": (
            "两种页面绘制方式",
            '<line x1="640" y1="190" x2="640" y2="580" stroke="#475569"/><text x="100" y="270" font-size="44" fill="#38bdf8">HTML</text><text x="720" y="270" font-size="44" fill="#a78bfa">SVG</text><text x="100" y="350" font-size="28" fill="#fff" data-box-w="440">浏览器布局与现有编辑工具</text><text x="720" y="350" font-size="28" fill="#fff" data-box-w="440">显式坐标与服务端分行检查</text>',
        ),
        "data": (
            "合成数据 · 仅作绘图验证",
            "".join(
                f'<rect x="{150+i*300}" y="{560-v*4}" width="120" height="{v*4}" fill="#38bdf8"/><text x="{210+i*300}" y="{540-v*4}" font-size="30" text-anchor="middle" fill="#fff">{v}</text>'
                for i, v in enumerate([30, 55, 80])
            ),
        ),
        "conclusion": (
            "验证结论",
            '<text x="100" y="300" font-size="56" fill="#f8fafc">格式接通 ≠ 设计质量已验证</text><text x="100" y="420" font-size="28" fill="#94a3b8" data-box-w="1000">真实模型质量还需固定资料、构图计划与修复预算后做盲评。</text>',
        ),
    }


def main(argv=None):
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/svg-mode-verification/smoke")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    gallery = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        for number, (name, (title, body)) in enumerate(fixtures().items(), 1):
            raw = f'<svg><g data-role="background"><rect width="1280" height="720" fill="#0f172a"/></g><g data-role="title"><text x="100" y="110" font-size="44" fill="#fff">{title}</text></g><g data-role="stage">{body}</g><g data-role="footer"><text x="1200" y="690" text-anchor="end" font-size="16" fill="#94a3b8">{number} / 6</text></g></svg>'
            candidate = process_svg_candidate(raw, allowed_image_urls=[])
            target = out / f"{name}.html"
            target.write_text(
                build_slide_html(candidate.markup, title=title), encoding="utf-8"
            )
            (out / f"{name}-raw.svg").write_text(raw, encoding="utf-8")
            measure_svg_file(target).write(out / "svg-metrics" / f"{name}.json")
            measure_html_file(page, target).write(
                out / "browser-metrics" / f"{name}.json"
            )
            page.evaluate("document.fonts.ready")
            actual = page.evaluate(
                """() => {
                const root = document.querySelector('svg');
                const r = root.getBoundingClientRect();
                return {width:r.width,height:r.height,texts:root.querySelectorAll('text').length,
                    symbols:Array.from(root.querySelectorAll('use')).every(u=>!!root.querySelector(u.getAttribute('href')))};
            }"""
            )
            assert (
                actual["width"] == 1280
                and actual["height"] == 720
                and actual["texts"] >= 2
                and actual["symbols"]
            ), actual
            assert not candidate.blocking, candidate.blocking
            page.screenshot(path=str(out / f"{name}.png"))
            results.append(
                {
                    "fixture": name,
                    "browser": actual,
                    "blocking": len(candidate.blocking),
                }
            )
            gallery.append(
                f'<article><h2>{html.escape(title)}</h2><img src="{name}.png" width="640" height="360"></article>'
            )
        index = out / "index.html"
        index.write_text(
            '<!doctype html><meta charset="utf-8"><title>SVG 离线验证</title><style>body{font-family:sans-serif;background:#e2e8f0;margin:20px;display:grid;grid-template-columns:640px 640px;gap:20px}h2{font-size:20px}img{display:block}</style>'
            + "".join(gallery),
            encoding="utf-8",
        )
        page.set_viewport_size({"width": 1340, "height": 1280})
        page.goto(index.resolve().as_uri())
        page.screenshot(path=str(out / "contact-sheet.png"), full_page=True)
        browser.close()
    (out / "smoke.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(results)} synthetic SVG pages rendered and checked; output: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
