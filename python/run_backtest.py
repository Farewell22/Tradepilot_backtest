"""Unified command-line entry for backtests and factor research."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from python.backtest.broker import FeeConfig


ROOT = Path(__file__).resolve().parents[1]
TaskKind = Literal["strategy", "research"]


@dataclass(frozen=True)
class RunRequest:
    task_id: str
    kind: TaskKind
    start_date: str
    end_date: str
    output_dir: Path
    fees: FeeConfig
    execution_mode: str
    config_path: Path | None = None


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    kind: TaskKind
    handler: Callable[[RunRequest], Path]
    default_fees: FeeConfig
    execution_mode: str
    status: Literal["active", "archived"] = "active"
    default_config: Path | None = None
    data_sources: tuple[Path, ...] = ()
    supports_fee_override: bool = False
    source_path_keys: tuple[str, ...] = ()
    report_dir: Path | None = None
    default_start_date: str = "20200101"
    default_end_date: str = "20251231"


def _parse_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise ValueError("日期必须为 YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"无效日期: {value}") from error
    return value


def _git_state() -> tuple[str, bool]:
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip())
        return revision, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def _write_manifest(path: Path, content: dict) -> None:
    (path / "run_manifest.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None, *, tasks: dict[tuple[str, str], TaskSpec] | None = None) -> int:
    parser = argparse.ArgumentParser(description="统一策略回测和因子研究入口")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="列出可运行任务")
    listing.add_argument("kind", choices=("strategies", "research"))
    running = commands.add_parser("run", help="执行指定任务")
    running.add_argument("kind", choices=("strategy", "research"))
    running.add_argument("task_id")
    running.add_argument("--start", help="YYYYMMDD；省略时使用任务默认起点")
    running.add_argument("--end", help="YYYYMMDD；省略时使用任务默认终点")
    running.add_argument("--output-root", type=Path)
    running.add_argument("--config", type=Path)
    for name in ("commission_rate", "min_commission", "stamp_duty_rate", "transfer_fee_rate", "slippage_rate"):
        running.add_argument("--" + name.replace("_", "-"), dest=name, type=float)
    args = parser.parse_args(argv)

    if tasks is None:
        from python.task_registry import TASKS
        tasks = TASKS

    if args.command == "list":
        selected = "strategy" if args.kind == "strategies" else "research"
        for (kind, task_id), spec in sorted(tasks.items()):
            if kind == selected and spec.status == "active":
                print(task_id)
        return 0

    spec = tasks.get((args.kind, args.task_id))
    if spec is None or spec.status != "active":
        print(f"未知或未启用的任务: {args.kind}/{args.task_id}", file=sys.stderr)
        return 2
    try:
        start = _parse_date(args.start if args.start is not None else spec.default_start_date)
        end = _parse_date(args.end if args.end is not None else spec.default_end_date)
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        overrides = {
            name: getattr(args, name) for name in (
                "commission_rate", "min_commission", "stamp_duty_rate", "transfer_fee_rate", "slippage_rate"
            ) if getattr(args, name) is not None
        }
        fees = spec.default_fees.with_overrides(**overrides)
        if overrides and args.kind == "research" and not spec.supports_fee_override:
            raise ValueError(f"研究任务 {spec.task_id} 不支持费用覆盖")
        config_path = args.config or spec.default_config
        if config_path is not None and not config_path.is_file():
            raise ValueError(f"配置文件不存在: {config_path}")
        sources = spec.data_sources
        if spec.source_path_keys:
            if config_path is None:
                raise ValueError(f"任务 {spec.task_id} 缺少数据路径配置")
            import yaml
            try:
                settings = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as error:
                raise ValueError(f"配置文件 YAML 无效: {config_path}: {error}") from error
            configured = settings.get("paths", {}) if isinstance(settings, dict) else {}
            if not isinstance(configured, dict):
                raise ValueError(f"配置文件 paths 必须是映射: {config_path}")
            missing_keys = [key for key in spec.source_path_keys if not isinstance(configured.get(key), str) or not configured[key]]
            if missing_keys:
                raise ValueError("配置缺少数据路径: " + ", ".join(missing_keys))
            sources = tuple(Path(configured[key]) for key in spec.source_path_keys)
            sources = tuple(path if path.is_absolute() else ROOT / path for path in sources)
        missing_sources = [str(path) for path in sources if not path.exists()]
        if missing_sources:
            raise ValueError("必需数据不存在: " + ", ".join(missing_sources))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    root = args.output_root or ROOT / "data" / ("backtest_runs" if args.kind == "strategy" else "factor_research_runs")
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = root / f"{spec.task_id}__{stamp}__{uuid4().hex[:8]}"
    output_dir.mkdir()
    revision, dirty = _git_state()
    request = RunRequest(spec.task_id, spec.kind, start, end, output_dir, fees, spec.execution_mode, config_path)
    manifest = {
        "task_id": spec.task_id, "kind": spec.kind, "start_date": start, "end_date": end,
        "fees": asdict(fees), "execution_mode": spec.execution_mode,
        "config_path": str(config_path) if config_path else None,
        "config_snapshot": config_path.read_text(encoding="utf-8") if config_path else None,
        "data_sources": [str(path.resolve()) for path in sources],
        "git_revision": revision, "git_dirty": dirty,
        "generated_at": datetime.now(UTC).isoformat(), "status": "running",
    }
    _write_manifest(output_dir, manifest)
    try:
        result_path = spec.handler(request)
        manifest["status"] = "complete"
        manifest["result_path"] = str(result_path)
        if spec.report_dir is not None:
            from python.backtest.report_publication import publish_latest_report
            manifest["published_report_path"] = str((spec.report_dir / "latest-report.md").resolve())
        _write_manifest(output_dir, manifest)
        if spec.report_dir is not None:
            publish_latest_report(spec.report_dir, output_dir, manifest)
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        manifest.pop("published_report_path", None)
        _write_manifest(output_dir, manifest)
        print(f"任务失败，详情见 {output_dir / 'run_manifest.json'}: {error}", file=sys.stderr)
        return 1
    print(result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
