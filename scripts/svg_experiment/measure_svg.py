"""度量 SVG 页：直接复用服务端检查器（不做确定性修复，看首轮原貌）。

uv run python -m scripts.svg_experiment.measure_svg <file-or-dir>... --out results/svg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from landppt.services.slide.svg_page import (
    get_text_measurer,
    process_svg_candidate,
    svg_from_shell,
)
from landppt.services.slide.svg_page.sanitize import SvgSanitizeError

from .common import PageMeasurement, iter_pages


def measure_svg_file(path: Path, *, apply_repair: bool = False) -> PageMeasurement:
    text = path.read_text(encoding="utf-8", errors="replace")
    markup = svg_from_shell(text) if path.suffix.lower() in (".html", ".htm") else text
    measurement = PageMeasurement(source=str(path), render_mode="svg")
    if not markup:
        measurement.defects.append({"type": "measurement_failed"})
        measurement.notes.append("no <svg> found")
        return measurement
    try:
        result = process_svg_candidate(
            markup, measurer=get_text_measurer(), apply_repair=apply_repair
        )
    except SvgSanitizeError as exc:
        measurement.defects.append({"type": "measurement_failed"})
        measurement.notes.append(f"unparsable: {exc}")
        return measurement
    measurement.defects = list(result.inspection.defects)
    measurement.metrics = dict(result.metrics)
    measurement.metrics["sanitize_issues"] = len(result.sanitize_issues)
    measurement.metrics["repair_actions"] = len(result.repair_actions)
    return measurement


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--out", default="results/svg")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="先做确定性修复再度量（默认关闭，看首轮原貌）",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    files = iter_pages(args.paths)
    if not files:
        print("no pages found", file=sys.stderr)
        return 1
    for path in files:
        measurement = measure_svg_file(path, apply_repair=args.repair)
        target = out_dir / (path.stem + ".json")
        measurement.write(target)
        signals = measurement.signals
        print(
            f"{path.name}: blocking={measurement.metrics.get('blocking_count', '?')} "
            f"overlap={signals['overlap']} out={signals['out_of_canvas']} overflow={signals['text_overflow']} "
            f"empty_band={signals['empty_band']} equal_rects={signals['equal_rect_group']} "
            f"coverage={measurement.metrics.get('stage_coverage', '?')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
