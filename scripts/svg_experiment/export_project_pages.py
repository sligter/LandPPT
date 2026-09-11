"""把项目里的页面导出成文件，供度量脚本使用。

    uv run python -m scripts.svg_experiment.export_project_pages <project_id> --out pages/<group>

每页写成 ``page-XX.html``；同时写 ``pages.json`` 记录 render_mode、生成失败标记与 svg_report，
以便聚合时统计兜底率与修复轮数。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path


async def export(project_id: str, out_dir: Path) -> int:
    from landppt.services.db_project_manager import DatabaseProjectManager

    manager = DatabaseProjectManager()
    project = await manager.get_project(project_id)
    if not project:
        raise SystemExit(f"project {project_id} not found")
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for i, slide in enumerate(project.slides_data or []):
        if not slide:
            continue
        html = slide.get("html_content") or ""
        name = f"page-{i + 1:02d}.html"
        (out_dir / name).write_text(html, encoding="utf-8")
        index.append(
            {
                "file": name,
                "page": i + 1,
                "title": slide.get("title"),
                "render_mode": slide.get("render_mode")
                or ("svg" if 'data-render-mode="svg"' in html[:600] else "html"),
                "generation_failed": bool(slide.get("generation_failed")),
                "is_user_edited": bool(slide.get("is_user_edited")),
                "svg_report": slide.get("svg_report")
                or (slide.get("metadata") or {}).get("svg_report"),
                "composition_brief": slide.get("composition_brief"),
            }
        )
    (out_dir / "pages.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    metadata = (
        project.project_metadata if isinstance(project.project_metadata, dict) else {}
    )
    (out_dir / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "title": project.title,
                "render_mode": metadata.get("render_mode", "html"),
                "outline_pages": len((project.outline or {}).get("slides", [])),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"exported {len(index)} pages to {out_dir}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    return asyncio.run(export(args.project_id, Path(args.out)))


if __name__ == "__main__":
    raise SystemExit(main())
