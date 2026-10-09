"""Publish a readable snapshot of one completed task beside its source."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULT_SUFFIXES = {".csv", ".json"}


def _location(path: Path, report_dir: Path) -> str:
    path = path.resolve()
    if path.is_relative_to(PROJECT_ROOT):
        label = path.relative_to(PROJECT_ROOT).as_posix()
        target = quote(Path(os.path.relpath(path, report_dir)).as_posix())
        return f"[{label}]({target})"
    return f"`{path}`"


def render_latest_report(report_dir: Path, output_dir: Path, manifest: dict) -> str:
    """Combine the run's report files with the paths needed to inspect it."""
    reports = sorted(
        path for path in output_dir.rglob("report.*")
        if path.is_file() and path.suffix in {".md", ".txt"}
    )
    if not reports:
        raise FileNotFoundError(f"本次运行没有 report.md 或 report.txt: {output_dir}")

    lines = [
        f"# 最新运行报告：{manifest['task_id']}", "",
        f"- 任务类型：`{manifest['kind']}`",
        f"- 运行时间（UTC）：`{manifest['generated_at']}`",
        f"- 请求区间：`{manifest['start_date']}` ～ `{manifest['end_date']}`",
        f"- 运行目录：{_location(output_dir, report_dir)}",
        f"- 运行清单：{_location(output_dir / 'run_manifest.json', report_dir)}",
        "- 输入数据：",
    ]
    sources = manifest.get("data_sources", [])
    lines.extend(f"  - {_location(Path(source), report_dir)}" for source in sources)
    if not sources:
        lines.append("  - 无登记输入数据")

    results = sorted(
        path for path in output_dir.iterdir()
        if path.is_file() and path.suffix in RESULT_SUFFIXES and path.name != "run_manifest.json"
    )
    if results:
        lines.extend(["- 关键结果文件：", *(f"  - {_location(path, report_dir)}" for path in results)])
    lines.extend(["", "## 本次报告", ""])
    for report in reports:
        lines.append(f"### {_location(report, report_dir)}")
        lines.append("")
        body = report.read_text(encoding="utf-8").rstrip("\n")
        if report.suffix == ".txt":
            lines.extend(["```text", body, "```", ""])
        else:
            lines.extend([body, ""])
    return "\n".join(lines).rstrip() + "\n"


def publish_latest_report(report_dir: Path, output_dir: Path, manifest: dict) -> Path:
    """Replace the latest snapshot atomically after the new body is complete."""
    report_dir = report_dir.resolve()
    body = render_latest_report(report_dir, output_dir, manifest)
    report_dir.mkdir(parents=True, exist_ok=True)
    destination = report_dir / "latest-report.md"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=report_dir, prefix=".latest-report-", delete=False) as file:
            temporary = Path(file.name)
            file.write(body)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
