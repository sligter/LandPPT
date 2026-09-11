"""聚合两组度量结果，输出对照表。

    uv run python -m scripts.svg_experiment.aggregate --group html=results/html --group svg=results/svg \
        [--reports cache/style_genes/<project>_svg_pages.jsonl] [--markdown report.md]

每组一行：页数、阻断缺陷均值、各信号出现率、stage 覆盖率均值、等大矩形组率；
若给了生成报告（JSONL），再补上平均尝试轮数、平均耗时、token 与兜底率。
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .common import SIGNAL_TYPES


def load_group(path: Path) -> List[Dict]:
    return [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(path.glob("*.json"))
    ]


def load_reports(paths: Iterable[str]) -> List[Dict]:
    reports: List[Dict] = []
    for raw in paths:
        for line in Path(raw).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                reports.append(json.loads(line))
    return reports


def summarize(
    name: str, pages: List[Dict], reports: Optional[List[Dict]] = None
) -> Dict:
    count = len(pages) or 1
    signals = {
        kind: sum(1 for p in pages if p.get("signals", {}).get(kind, 0) > 0) / count
        for kind in SIGNAL_TYPES
    }
    blocking = [
        p["metrics"]["blocking_count"]
        for p in pages
        if "blocking_count" in p.get("metrics", {})
    ]
    coverage = [
        p.get("metrics", {}).get("stage_coverage", 0.0)
        for p in pages
        if p.get("metrics")
    ]
    summary = {
        "group": name,
        "pages": len(pages),
        "blocking_mean": round(statistics.mean(blocking), 2) if blocking else 0.0,
        "coverage_mean": round(statistics.mean(coverage), 3) if coverage else 0.0,
        **{f"rate_{kind}": round(rate, 2) for kind, rate in signals.items()},
    }
    if reports:
        attempts = [len(r.get("attempts", [])) for r in reports]
        elapsed = [
            r.get("elapsed", 0.0) for r in reports if r.get("elapsed") is not None
        ]
        tokens = []
        for r in reports:
            for attempt in r.get("attempts", []):
                usage = attempt.get("usage") or {}
                total = usage.get("total_tokens") if isinstance(usage, dict) else None
                if isinstance(total, (int, float)):
                    tokens.append(total)
        summary.update(
            {
                "runs": len(reports),
                "attempts_mean": (
                    round(statistics.mean(attempts), 2) if attempts else 0.0
                ),
                "elapsed_mean_s": (
                    round(statistics.mean(elapsed), 1) if elapsed else 0.0
                ),
                "tokens_per_attempt_mean": (
                    round(statistics.mean(tokens), 0) if tokens else None
                ),
                "degraded_rate": round(
                    sum(1 for r in reports if r.get("outcome") != "ok")
                    / (len(reports) or 1),
                    2,
                ),
            }
        )
    return summary


def render_markdown(rows: List[Dict]) -> str:
    if not rows:
        return "(no data)"
    keys = list(rows[0].keys())
    for row in rows[1:]:
        for key in row:
            if key not in keys:
                keys.append(key)
    header = "| " + " | ".join(keys) + " |"
    divider = "| " + " | ".join("---" for _ in keys) + " |"
    lines = [header, divider]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key, "")) for key in keys) + " |")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group", action="append", required=True, help="name=dir，可重复"
    )
    parser.add_argument(
        "--reports", action="append", default=[], help="name=path.jsonl，可重复"
    )
    parser.add_argument("--markdown", help="把对照表写到这个文件")
    args = parser.parse_args(argv)

    report_map: Dict[str, List[Dict]] = {}
    for item in args.reports:
        name, _, path = item.partition("=")
        report_map.setdefault(name, []).extend(load_reports([path]))

    rows = []
    for item in args.group:
        name, _, path = item.partition("=")
        rows.append(summarize(name, load_group(Path(path)), report_map.get(name)))
    table = render_markdown(rows)
    print(table)
    if args.markdown:
        Path(args.markdown).write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
